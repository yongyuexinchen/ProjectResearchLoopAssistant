"""Durable automatic research stages and their user-visible progress."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import validate_source_input
from app.db.models import AnalysisRun, ArchitectureDiagram, LLMReportArtifact, Project, ReportSnapshot, RunJob, Source, SourceSnapshot
from app.engine.runner import enqueue_run
from app.services.run_events import list_run_events, record_run_event

WORKFLOW_STAGES = (
    ("collection", "采集资料"), ("analysis", "分析与验证"),
    ("architecture", "生成架构图"), ("report", "生成报告"),
)


def enqueue_workflow(session: Session, project: Project):
    # Lock the project so concurrent start requests cannot create duplicate runs.
    session.refresh(project, with_for_update=True)
    active = session.scalar(select(RunJob.id).where(
        RunJob.project_id == project.id, RunJob.status.in_({"queued", "running"}),
    ).limit(1))
    if active is not None:
        raise ValueError("项目已有排队或运行中的任务，请等待当前任务结束。")
    sources = list(session.scalars(select(Source).where(Source.project_id == project.id)).all())
    if not sources:
        raise LookupError("请先添加至少一个有效输入源。")
    for source in sources:
        validate_source_input(source.source_type, source.uri)
    if project.status in {"completed", "cancelled"}:
        project.status = "ready"
    return enqueue_run(session, project, payload={"workflow": True})


def workflow_job(session: Session, run_id: str) -> RunJob | None:
    jobs = session.scalars(select(RunJob).where(RunJob.run_id == run_id)
        .order_by(RunJob.created_at.desc(), RunJob.id.desc())).all()
    return next((job for job in jobs if job.payload_json.get("workflow")), None)


def stage_event(session: Session, project_id: str, run_id: str, stage: str,
                status: str, detail: str, **metadata):
    return record_run_event(session, project_id, run_id, f"workflow_stage_{status}",
                            {"stage": stage, "status": status, "detail": detail, **metadata})


def workflow_state(session: Session, project: Project, run_id: str | None = None,
                   *, include_previous_attempts: bool = False) -> dict:
    if run_id is not None:
        run = session.get(AnalysisRun, run_id)
        if run is None or run.project_id != project.id:
            raise LookupError("Run not found")
    else:
        runs = session.scalars(select(AnalysisRun).where(AnalysisRun.project_id == project.id)
            .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())).all()
        run = next((item for item in runs if workflow_job(session, item.id) is not None), None)
    stages = [{"key": key, "label": label, "status": "pending", "detail": "等待开始"}
              for key, label in WORKFLOW_STAGES]
    warnings = []
    report = None
    state = "idle"
    error = None
    if run is not None:
        events = list_run_events(session, project.id, run.id)
        by_key = {stage["key"]: stage for stage in stages}
        for event in events:
            payload = event.payload_json
            if event.event_type == "run_retry_queued" and not include_previous_attempts:
                for stage in stages:
                    stage.update(status="pending", detail="等待重试；已保存的阶段产物将由 worker 检查后复用")
                warnings.clear()
            if event.event_type.startswith("workflow_stage_") and payload.get("stage") in by_key:
                stage = by_key[payload["stage"]]
                stage.update(status=payload["status"], detail=payload.get("detail", ""))
                if payload.get("warning") and payload["warning"] not in warnings:
                    warnings.append(payload["warning"])
        job = workflow_job(session, run.id)
        state = run.status
        if state in {"ready_for_review", "ready_for_review_with_risks", "resuming"}:
            state = "running"
        if state == "failed":
            error = run.stop_reason or (job.last_error if job else None)
        report = session.scalar(select(ReportSnapshot).where(ReportSnapshot.run_id == run.id)
            .order_by(ReportSnapshot.created_at.desc(), ReportSnapshot.id.desc()).limit(1))
        if job is None:
            warning = "这是旧版仅分析任务，不会自动生成报告；可启动自动调研以完成采集、架构图和报告。"
            warnings.append(warning)
            collected = session.scalar(select(SourceSnapshot.id).where(
                SourceSnapshot.project_id == project.id, SourceSnapshot.status == "collected").limit(1))
            if collected:
                by_key["collection"].update(status="completed", detail="已找到此前保存的采集资料")
            if run.status in {"queued", "running", "resuming"}:
                state = "queued" if run.status == "queued" else "running"
                by_key["analysis"].update(status="pending" if state == "queued" else "running",
                                           detail="旧版分析任务正在排队或运行")
            elif run.status == "paused_for_input":
                state = "paused_for_input"
                by_key["analysis"].update(status="pending", detail="旧版分析任务等待回答问题")
            else:
                state = "idle"
                if run.status in {"ready_for_review", "ready_for_review_with_risks", "completed"}:
                    by_key["analysis"].update(status="completed", detail="此前的分析任务已结束")
                elif run.status == "failed":
                    by_key["analysis"].update(status="failed", detail=run.stop_reason or "此前的分析任务失败")
            if report is not None:
                state = "completed"
                by_key["analysis"].update(status="completed", detail="已找到与该任务对应的分析报告")
                by_key["report"].update(status="completed", detail="此前生成的报告已保存")
                by_key["architecture"].update(status="skipped", detail="旧版任务没有自动架构图阶段")
                warnings[-1] = "这是此前生成的报告；旧版任务没有自动架构图阶段。"
        if report is not None and by_key["report"]["status"] == "completed" and state not in {"failed", "cancelled"}:
            state = "completed"
        if report is not None:
            enhancement = session.scalar(select(LLMReportArtifact).where(LLMReportArtifact.report_id == report.id)
                .order_by(LLMReportArtifact.created_at.desc(), LLMReportArtifact.id.desc()).limit(1))
            if enhancement is not None and enhancement.status != "accepted":
                warnings.append("报告已保存；模型报告增强未完成，当前正文保留确定性分析结果，请结合质量检查阅读。")
    progress = sum(stage["status"] in {"completed", "skipped"} for stage in stages) * 25
    if report is None:
        progress = min(progress, 75)
    count = 0
    if run is not None and next(stage for stage in stages if stage["key"] == "architecture")["status"] == "completed":
        diagrams = session.scalars(select(ArchitectureDiagram).where(ArchitectureDiagram.project_id == project.id)).all()
        count = sum(row.stats_json.get("run_id") == run.id for row in diagrams)
    return {"project_id": project.id, "run": run, "stages": stages, "progress": progress,
            "status": state, "error": error, "report": report,
            "architecture_count": count, "warnings": warnings}
