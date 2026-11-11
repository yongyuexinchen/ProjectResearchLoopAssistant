import json
from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AnalysisRun,
    CodebaseMap,
    EvidenceItem,
    Finding,
    LLMReportArtifact,
    LoopTurn,
    Project,
    QualityScore,
    Question,
    Recommendation,
    ReportSnapshot,
    Risk,
    RunJob,
    SourceBundle,
    SourceSnapshot,
    utc_now,
)
from app.engine.runner import enqueue_run
from app.llm.json_tools import extract_json_object
from app.llm.router import LLMRouter
from app.research.profiles import get_research_profile
from app.reports.llm_generator import merge_llm_report_markdown, validate_llm_report_sections
from app.reports.project_brief import build_project_brief
from app.reports.renderer import render_report_markdown
from app.reports.architecture import render_architecture_markdown, snapshot_architecture_diagrams, split_architecture_chapter
from app.services.audit import record_event
from app.services.run_scope import scoped_collection_rows
from app.verifiers.package import as_list, verify_analysis_package

REVIEWABLE_RUN_STATUSES = {"ready_for_review", "ready_for_review_with_risks"}
REVIEW_STATUS_BY_DECISION = {
    "approved": ("approved", "completed"),
    "rejected": ("rejected", "ready"),
    "needs_more": ("needs_more", "ready"),
}
FOLLOWUP_REVIEW_DECISIONS = {"rejected", "needs_more"}


def create_report_snapshot(
    session: Session,
    project: Project,
    *,
    run_id: str | None = None,
) -> ReportSnapshot:
    """从一次已结束的 Loop run 生成报告快照。

    生成报告不会重新执行分析，也不会修改外部系统；它只把已经沉淀的
    Analysis Package、Source Inventory 和 verifier 结果固化成可评审产物。
    """

    run = get_run_for_report(session, project, run_id)
    if run.status not in REVIEWABLE_RUN_STATUSES:
        raise ValueError(f"Run status `{run.status}` is not ready for report review")

    package = build_analysis_package(session, run)
    inventory = build_inventory(session, project, run_id=run.id)
    verifier_result = verify_analysis_package(package, inventory)
    diagrams = snapshot_architecture_diagrams(session, project.id, run.id)
    verifier_result["architecture_diagrams"] = diagrams
    profile = get_research_profile(project.research_profile)
    title = f"{project.name} · {profile.label}调研报告"
    markdown = render_report_markdown(project, package, inventory, verifier_result)
    markdown = markdown.rstrip() + "\n\n" + render_architecture_markdown(diagrams)
    report = ReportSnapshot(
        project_id=project.id,
        run_id=run.id,
        status="draft" if verifier_result["passed"] else "blocked",
        title=title,
        markdown_content=markdown,
        verifier_result_json=verifier_result,
    )
    session.add(report)
    record_event(
        session,
        event_type="report.created",
        message="Analysis report snapshot created",
        project_id=project.id,
        payload={"run_id": run.id, "report_id": report.id, "verifier_passed": verifier_result["passed"]},
    )
    return report


def create_intelligent_report_snapshot(
    session: Session,
    project: Project,
    *,
    run_id: str | None = None,
) -> ReportSnapshot:
    """生成确定性报告，再尝试追加受证据约束的 LLM 解读段落。"""

    report = create_report_snapshot(session, project, run_id=run_id)
    session.flush()
    try:
        run = session.get(AnalysisRun, report.run_id)
        if run is None:
            raise LookupError("Run not found")

        package = build_analysis_package(session, run)
        inventory = build_inventory(session, project, run_id=run.id)
        evidence_ids = [
            str(evidence.id).strip()
            for evidence in package["evidence_items"]
            if str(evidence.id).strip()
        ]
        output_ref = f"llm_report_artifact:{report.id}"
        messages = build_llm_report_messages(project, package, inventory, evidence_ids)
        result = LLMRouter(session).chat(
            task_type="report",
            project_id=project.id,
            run_id=run.id,
            report_id=report.id,
            input_refs=evidence_ids,
            output_ref=output_ref,
            required=False,
            messages=messages,
        )
        call_id = result.get("call_id")
        llm_status = str(result.get("status") or "failed")

        if llm_status != "succeeded":
            try_add_llm_report_artifact(
                session,
                project_id=project.id,
                run_id=run.id,
                report_id=report.id,
                call_id=call_id,
                status=llm_status,
                content_json={
                    "llm_status": llm_status,
                    "error_message": result.get("error_message"),
                },
                validation_result_json={
                    "accepted": False,
                    "messages": [f"LLM report generation returned status `{llm_status}`"],
                },
            )
            return report

        raw_text = str(result.get("text") or "")
        payload = extract_json_object(raw_text)
    except Exception as exc:
        try_add_llm_report_artifact(
            session,
            project_id=project.id,
            run_id=report.run_id,
            report_id=report.id,
            call_id=None,
            status="validation_failed" if isinstance(exc, (json.JSONDecodeError, ValueError)) else "failed",
            content_json={"error_message": str(exc)},
            validation_result_json={
                "accepted": False,
                "messages": [f"LLM report enhancement failed: {exc}"],
            },
        )
        return report

    try:
        validation = validate_llm_report_sections(payload, allowed_evidence_refs=set(evidence_ids))
        if not validation.accepted:
            try_add_llm_report_artifact(
                session,
                project_id=project.id,
                run_id=run.id,
                report_id=report.id,
                call_id=call_id,
                status="rejected",
                content_json=payload,
                validation_result_json={
                    "accepted": False,
                    "messages": validation.messages,
                },
            )
            return report
    except Exception as exc:
        try_add_llm_report_artifact(
            session,
            project_id=project.id,
            run_id=report.run_id,
            report_id=report.id,
            call_id=None,
            status="validation_failed",
            content_json={"error_message": str(exc)},
            validation_result_json={
                "accepted": False,
                "messages": [f"LLM report validation failed: {exc}"],
            },
        )
        return report

    try:
        # LLM 段落只是 advisory：优先补进对应调研章节，无法归类的才进入附带的增强区块。
        planned_headings = ["项目速览"]
        profile_summary = package.get("profile_summary")
        if isinstance(profile_summary, dict):
            planned_headings.extend(
                str(section.get("heading"))
                for section in as_list(profile_summary.get("section_plan"))
                if isinstance(section, dict) and section.get("heading")
            )
        deterministic_body, architecture_chapter = split_architecture_chapter(report.markdown_content)
        enhanced_markdown = merge_llm_report_markdown(
            deterministic_body,
            validation.normalized or {},
            planned_headings=planned_headings,
        )
        try_add_llm_report_artifact(
            session,
            project_id=project.id,
            run_id=run.id,
            report_id=report.id,
            call_id=call_id,
            status="accepted",
            content_json=payload,
            validation_result_json={
                "accepted": True,
                "messages": validation.messages,
                "normalized": validation.normalized,
            },
        )
        report.markdown_content = enhanced_markdown.rstrip() + "\n" + architecture_chapter
    except Exception as exc:
        try_add_llm_report_artifact(
            session,
            project_id=project.id,
            run_id=report.run_id,
            report_id=report.id,
            call_id=None,
            status="failed",
            content_json={"error_message": str(exc)},
            validation_result_json={
                "accepted": False,
                "messages": [f"LLM report render failed: {exc}"],
            },
        )
        return report
    return report


def add_llm_report_artifact(
    session: Session,
    *,
    project_id: str,
    run_id: str,
    report_id: str,
    call_id: Any,
    status: str,
    content_json: dict[str, Any],
    validation_result_json: dict[str, Any],
) -> LLMReportArtifact:
    artifact = LLMReportArtifact(
        project_id=project_id,
        run_id=run_id,
        report_id=report_id,
        call_id=str(call_id) if call_id else None,
        status=status,
        content_json=content_json,
        validation_result_json=validation_result_json,
    )
    session.add(artifact)
    session.flush()
    return artifact


def try_add_llm_report_artifact(
    session: Session,
    *,
    project_id: str,
    run_id: str,
    report_id: str,
    call_id: Any,
    status: str,
    content_json: dict[str, Any],
    validation_result_json: dict[str, Any],
) -> LLMReportArtifact | None:
    """Best-effort 记录 LLM 报告增强产物，避免 artifact flush 失败污染外层事务。"""

    try:
        with session.begin_nested():
            return add_llm_report_artifact(
                session,
                project_id=project_id,
                run_id=run_id,
                report_id=report_id,
                call_id=call_id,
                status=status,
                content_json=content_json,
                validation_result_json=validation_result_json,
            )
    except Exception:
        return None


def build_llm_report_messages(
    project: Project,
    package: dict[str, Any],
    inventory: dict[str, Any],
    evidence_ids: list[str],
) -> list[dict[str, Any]]:
    """构造按调研方式组织的紧凑上下文，要求 LLM 只返回 JSON 且只引用允许的证据 ID。"""

    profile = get_research_profile(project.research_profile)
    brief = build_project_brief(project, inventory)
    context = {
        "project": {
            "id": project.id,
            "name": project.name,
            "topic": project.topic,
            "analysis_goal": project.analysis_goal,
            "research_profile": profile.key,
        },
        "research_profile": {
            "key": profile.key,
            "label": profile.label,
            "description": profile.description,
            "audience": profile.audience,
            "core_question": profile.core_question,
            "deliverable": profile.deliverable,
            "checklist": list(profile.checklist),
            "focus_points": list(profile.focus_points),
            "analysis_directives": list(profile.analysis_directives),
            "report_plan": [
                {"heading": section.heading, "question": section.question}
                for section in profile.section_plan
            ],
        },
        "project_brief": asdict(brief),
        "allowed_evidence_refs": evidence_ids,
        "evidence_items": [
            {
                "id": evidence.id,
                "title": evidence.title,
                "summary": evidence.summary,
                "reference": evidence.reference,
            }
            for evidence in package["evidence_items"]
        ],
        "findings": [
            {
                "title": finding.title,
                "summary": finding.summary,
                "category": finding.category,
                "impact_level": finding.impact_level,
                "evidence_refs": finding.evidence_refs_json,
            }
            for finding in package["findings"]
        ],
        "risks": [
            {
                "title": risk.title,
                "summary": risk.summary,
                "severity": risk.severity,
                "mitigation": risk.mitigation,
                "evidence_refs": risk.evidence_refs_json,
            }
            for risk in package["risks"]
        ],
        "recommendations": [
            {
                "summary": recommendation.summary,
                "rationale": recommendation.rationale,
                "confidence": recommendation.confidence,
                "next_steps": recommendation.next_steps_json,
            }
            for recommendation in package["recommendations"]
        ],
        "inventory": {
            "sources": [
                {
                    "title": snapshot.title,
                    "source_type": snapshot.source_type,
                    "status": snapshot.status,
                    "content_excerpt": truncate_text(snapshot.content_excerpt, 600),
                }
                for snapshot in inventory["snapshots"]
            ],
            "source_bundles": [
                {
                    "id": bundle["id"],
                    "name": bundle["name"],
                    "status": bundle["status"],
                    "item_count": bundle["item_count"],
                    "collected_count": bundle["collected_count"],
                    "failed_count": bundle["failed_count"],
                    "pending_count": bundle["pending_count"],
                }
                for bundle in inventory.get("source_bundles", [])
            ],
            "codebase_maps": [
                {
                    "root_label": codebase_map.root_label,
                    "tech_stack": codebase_map.tech_stack_json,
                    "entrypoints": codebase_map.entrypoint_files_json,
                    "tests": codebase_map.test_files_json,
                    "dependency_files": codebase_map.dependency_files_json,
                    "config_files": codebase_map.config_files_json,
                    "readme_excerpt": truncate_text(codebase_map.readme_excerpt, 1200),
                }
                for codebase_map in inventory["codebase_maps"]
            ],
        },
    }
    section_titles = "、".join(f"「{section.heading}」" for section in profile.section_plan)
    return [
        {
            "role": "system",
            "content": (
                f"你是工程调研报告编辑，当前调研方式是「{profile.label}」，面向{profile.audience}。"
                "只能基于提供的 evidence id 做解释，不得新增事实或编造文件、命令、指标。"
                "报告必须围绕该调研方式的核心问题组织，不要把五类调研写成同一份通用报告。"
                "必须返回一个包含 executive_summary 和 sections 两个顶层键的 JSON 对象；"
                "不要把单个 section 直接作为顶层对象返回。"
                "只返回 JSON object，不要使用 Markdown。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "instruction": (
                        "返回一个 JSON 对象，顶层只能有 executive_summary 和 sections 两个键："
                        '{"executive_summary": string, "sections": '
                        '[{"heading": string, "body": string, "evidence_refs": string[]}]}。'
                        "不要返回单个 section 对象，也不要把 section 的 heading/body 放在顶层。"
                        f"section 的 heading 必须从这些章节中选择：{section_titles}，"
                        "也可以补一节「项目速览」。"
                        "executive_summary 在 300 字以内，先回答“项目是什么、为什么做、有什么特点、本次结论”，"
                        "不得复述校验项或证据清单。"
                        "每个 section 的 body 控制在 150-400 字，先给结论，再给依据和边界；"
                        "资料不足时明确写“资料未说明”，不要补写事实。"
                        "每个 section 至少引用一个 allowed_evidence_refs 中的证据 ID。"
                    ),
                    "context": context,
                },
                ensure_ascii=False,
            ),
        },
    ]


def truncate_text(value: Any, limit: int) -> str:
    rendered = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(rendered) <= limit:
        return rendered
    return rendered[: limit - 3] + "..."


def review_report_snapshot(
    session: Session,
    project: Project,
    report: ReportSnapshot,
    *,
    decision: str,
    comment: str | None,
) -> ReportSnapshot:
    if decision not in REVIEW_STATUS_BY_DECISION:
        raise ValueError(f"Unsupported review decision `{decision}`")
    review_comment = normalized_review_comment(decision, comment)
    report_status, project_status = REVIEW_STATUS_BY_DECISION[decision]

    # Lock the project row so two review requests cannot both pass the active-job
    # check and enqueue independent follow-up runs.
    locked_project = session.scalar(
        select(Project).where(Project.id == project.id).with_for_update()
    )
    if locked_project is not None:
        project = locked_project
    latest_run = session.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.project_id == project.id)
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        .limit(1)
    )
    active_job = session.scalar(
        select(RunJob).where(
            RunJob.project_id == project.id,
            RunJob.status.in_(("queued", "running")),
        ).order_by(RunJob.created_at.desc()).limit(1)
    )
    is_current_report = latest_run is not None and latest_run.id == report.run_id

    if decision in FOLLOWUP_REVIEW_DECISIONS:
        existing_feedback = [
            question
            for question in session.scalars(
                select(Question).where(Question.project_id == project.id, Question.run_id == report.run_id)
            ).all()
            if (question.metadata_json or {}).get("source") == "report_review"
            and (question.metadata_json or {}).get("report_id") == report.id
            and (question.metadata_json or {}).get("decision") == decision
        ]
        if existing_feedback:
            return report

    if not is_current_report:
        # Historical review must never mutate the current project's state or
        # enqueue work against the latest run.
        if decision in FOLLOWUP_REVIEW_DECISIONS:
            raise ValueError("历史报告不能启动新的调研任务；请打开当前运行的最新报告再提交该评审。")
        report.status = report_status
        report.review_decision = decision
        report.review_comment = review_comment
        report.reviewed_at = utc_now()
        record_event(
            session,
            event_type="report.reviewed",
            message="Historical analysis report reviewed without changing the current run",
            project_id=project.id,
            payload={"report_id": report.id, "decision": decision, "historical": True},
        )
        return report

    if active_job is not None or (latest_run is not None and latest_run.status in {"queued", "running"}):
        raise ValueError("当前调研仍在运行，完成或取消后才能评审报告。")
    if report.review_decision == decision and report.status == report_status:
        return report

    report.status = report_status
    report.review_decision = decision
    report.review_comment = review_comment
    report.reviewed_at = utc_now()
    project.status = project_status
    feedback_question: Question | None = None
    followup_run: AnalysisRun | None = None
    followup_job = None
    if decision in FOLLOWUP_REVIEW_DECISIONS:
        feedback_question = create_review_feedback_question(
            session,
            project=project,
            report=report,
            decision=decision,
            comment=review_comment or "",
        )
        record_event(
            session,
            event_type="report.review_feedback.created",
            message="Report review feedback recorded for next Loop run",
            project_id=project.id,
            payload={
                "report_id": report.id,
                "question_id": feedback_question.id,
                "decision": decision,
            },
        )
        followup_run, followup_job = enqueue_run(
            session,
            project,
            job_type="start",
            payload={
                "source": "report_review",
                "report_id": report.id,
                "feedback_question_id": feedback_question.id,
            },
        )
    record_event(
        session,
        event_type="report.reviewed",
        message="Analysis report reviewed",
        project_id=project.id,
        payload={
            "report_id": report.id,
            "decision": decision,
            "feedback_question_id": feedback_question.id if feedback_question else None,
            "followup_run_id": followup_run.id if followup_run else None,
            "followup_job_id": followup_job.id if followup_job else None,
        },
    )
    return report


def normalized_review_comment(decision: str, comment: str | None) -> str | None:
    """规范化人工评审备注。

    通过类评审可以没有备注；驳回和要求补充会驱动下一轮 Loop，必须给出
    明确反馈，否则系统只知道“继续”，不知道要修正什么。
    """

    clean_comment = (comment or "").strip()
    if decision in FOLLOWUP_REVIEW_DECISIONS and not clean_comment:
        raise ValueError("Rejected or needs_more reviews require a feedback comment")
    return clean_comment or None


def create_review_feedback_question(
    session: Session,
    *,
    project: Project,
    report: ReportSnapshot,
    decision: str,
    comment: str,
) -> Question:
    """把报告评审意见固化为已回答问题，供下一轮上下文构建读取。"""

    question = Question(
        project_id=project.id,
        run_id=report.run_id,
        prompt="人工评审反馈需要进入下一轮 Loop",
        reason="用户在报告评审中要求系统补充或重做部分分析。",
        impact="high" if decision == "rejected" else "medium",
        status="answered",
        answer_text=comment,
        answered_at=utc_now(),
        metadata_json={
            "source": "report_review",
            "decision": decision,
            "report_id": report.id,
        },
    )
    session.add(question)
    session.flush()
    return question


def get_latest_report(session: Session, project: Project) -> ReportSnapshot | None:
    return session.scalar(
        select(ReportSnapshot)
        .where(ReportSnapshot.project_id == project.id)
        .order_by(ReportSnapshot.created_at.desc(), ReportSnapshot.id.desc())
    )


def get_run_for_report(session: Session, project: Project, run_id: str | None) -> AnalysisRun:
    if run_id:
        run = session.get(AnalysisRun, run_id)
        if run is None or run.project_id != project.id:
            raise LookupError("Run not found")
        return run

    run = session.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.project_id == project.id)
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
    )
    if run is None:
        raise LookupError("No analysis run exists for this project")
    return run


def build_analysis_package(session: Session, run: AnalysisRun) -> dict[str, Any]:
    project = session.get(Project, run.project_id)
    profile = get_research_profile(project.research_profile if project is not None else None)
    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "topic": project.topic,
            "analysis_goal": project.analysis_goal,
            "research_profile": profile.key,
        }
        if project is not None
        else None,
        "research_profile": profile.key,
        "profile_summary": {
            "key": profile.key,
            "label": profile.label,
            "description": profile.description,
            "audience": profile.audience,
            "core_question": profile.core_question,
            "checklist": list(profile.checklist),
            "report_sections": list(profile.report_sections),
            "section_plan": [
                {"heading": section.heading, "question": section.question}
                for section in profile.section_plan
            ],
            "required_evidence_types": list(profile.required_evidence_types),
            "focus_points": list(profile.focus_points),
            "deliverable": profile.deliverable,
        },
        "run": run,
        "turns": list_by_run(session, LoopTurn, run.id),
        "evidence_items": list_by_run(session, EvidenceItem, run.id),
        "findings": list_by_run(session, Finding, run.id),
        "risks": list_by_run(session, Risk, run.id),
        "questions": list_by_run(session, Question, run.id),
        "recommendations": list_by_run(session, Recommendation, run.id),
        "quality_scores": list_by_run(session, QualityScore, run.id),
    }


def build_inventory(session: Session, project: Project, *, run_id: str | None = None) -> dict[str, Any]:
    snapshots = scoped_collection_rows(session, SourceSnapshot, project.id, run_id)
    codebase_maps = scoped_collection_rows(session, CodebaseMap, project.id, run_id)
    source_bundles = scoped_collection_rows(session, SourceBundle, project.id, run_id)
    return {
        "snapshots": snapshots,
        "codebase_maps": codebase_maps,
        "source_bundles": [
            {
                "id": bundle.id,
                "name": bundle.name,
                "status": bundle.status,
                "item_count": len(bundle.items),
                "collected_count": count_bundle_items_by_status(bundle, "collected"),
                "failed_count": count_bundle_items_by_status(bundle, "failed"),
                "pending_count": count_bundle_items_by_status(bundle, "pending"),
            }
            for bundle in source_bundles
        ],
    }


def count_bundle_items_by_status(bundle: SourceBundle, status: str) -> int:
    return sum(1 for item in bundle.items if item.status == status)


def list_by_run(session: Session, model, run_id: str):
    if model is LoopTurn:
        order_by = (LoopTurn.turn_index.asc(), LoopTurn.id.asc())
    else:
        order_by = (model.created_at.asc(), model.id.asc())
    return list(session.scalars(select(model).where(model.run_id == run_id).order_by(*order_by)).all())
