from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from threading import Event, Thread
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.models import AnalysisRun, Project, RunJob
from app.db.session import get_worker_session_factory
from app.engine import langgraph_runner
from app.services.run_events import record_run_event
from app.services.run_jobs import claim_next_job, finalize_owned_job, heartbeat_job


class JobLeaseLost(RuntimeError):
    """当前 worker 不再持有 job 租约时停止本轮执行，避免覆盖新 worker 状态。"""


def run_one_job(
    worker_id: str | None = None,
    queue_name: str = "default",
    lease_seconds: int = 60,
) -> bool:
    """执行一个排队中的 run job，便于本地开发、测试和 daemon 复用。"""

    worker_id = worker_id or f"local-worker-{uuid4()}"
    session_factory = get_worker_session_factory()
    with session_factory() as session:
        job = claim_next_job(
            session,
            worker_id=worker_id,
            queue_name=queue_name,
            lease_seconds=lease_seconds,
        )
        if job is None:
            return False
        run = require_run(session, job.run_id)
        project = require_project(session, job.project_id)
        run.status = "running" if job.job_type != "resume" else "resuming"
        project.status = run.status
        record_run_event(session, project.id, run.id, "run_started", {"status": run.status, "job_id": job.id})
        job_id = job.id
        job_attempt = job.attempt_count
        project_id = project.id
        run_id = run.id
        thread_id = run.thread_id or f"run:{run.id}"
        job_type = job.job_type
        payload = job.payload_json
        session.commit()

    try:
        with maintain_job_lease(session_factory, job_id, worker_id, lease_seconds) as guard:
            with session_factory() as session:
                if payload.get("workflow"):
                    execute_workflow(session, project_id, run_id, thread_id, job_type, payload, guard)
                elif job_type == "resume":
                    for event_payload in langgraph_runner.stream_run_graph_events(
                        session, project_id, run_id, thread_id,
                        guard=lambda: guard(session), resume_payload=payload,
                    ):
                        guard()
                        record_run_event(session, project_id, run_id, "node_completed", event_payload)
                        session.commit()
                        heartbeat_current_job(session_factory, job_id, worker_id, lease_seconds)
                else:
                    for event_payload in langgraph_runner.stream_run_graph_events(
                        session, project_id, run_id, thread_id, guard=lambda: guard(session),
                    ):
                        guard()
                        record_run_event(session, project_id, run_id, "node_completed", event_payload)
                        session.commit()
                        heartbeat_current_job(session_factory, job_id, worker_id, lease_seconds)

        with session_factory() as session:
            if not finalize_owned_job(
                session, job_id=job_id, worker_id=worker_id,
                attempt_count=job_attempt, status="succeeded",
            ):
                return True
            run = require_run(session, run_id)
            project = require_project(session, project_id)
            record_run_event(
                session,
                project.id,
                run.id,
                "run_paused" if payload.get("workflow") and run.status == "paused_for_input" else "run_completed",
                {"status": run.status, "turn_count": run.current_turn, "job_id": job_id},
            )
            session.commit()
        return True
    except JobLeaseLost:
        return True
    except Exception as exc:
        with session_factory() as session:
            if not finalize_owned_job(
                session, job_id=job_id, worker_id=worker_id,
                attempt_count=job_attempt, status="failed", error=str(exc),
            ):
                return True
            run = require_run(session, run_id)
            project = require_project(session, project_id)
            run.status = "failed"
            run.stop_reason = str(exc)
            project.status = "failed"
            record_run_event(session, project.id, run.id, "run_failed", {"message": str(exc), "job_id": job_id})
            session.commit()
        return True


@contextmanager
def maintain_job_lease(session_factory, job_id: str, worker_id: str, lease_seconds: int):
    """Renew independently of node duration, including slow network collection/LLM calls."""
    stopped = Event()
    failures = []

    def keepalive():
        while not stopped.wait(max(0.1, min(10.0, lease_seconds / 3))):
            try:
                heartbeat_current_job(session_factory, job_id, worker_id, lease_seconds)
            except Exception as exc:
                failures.append(exc)
                return

    def guard(current_session=None):
        if failures:
            raise JobLeaseLost("任务续租已停止，等待 worker 恢复。") from failures[0]
        # In-memory SQLite shares a single physical connection; closing a second
        # session there would roll back the graph's uncommitted writes.
        if current_session is not None and current_session.get_bind().pool.__class__.__name__ == "StaticPool":
            from sqlalchemy import select
            ownership = current_session.execute(select(RunJob.status, RunJob.locked_by).where(RunJob.id == job_id)).first()
            if ownership is None or ownership.status != "running" or ownership.locked_by != worker_id:
                raise JobLeaseLost("Run job lease is no longer owned by this worker")
            return
        ensure_job_still_owned(session_factory, job_id, worker_id)

    thread = Thread(target=keepalive, name=f"run-lease-{job_id}", daemon=True)
    thread.start()
    try:
        yield guard
    finally:
        stopped.set()
        thread.join(timeout=2)


def execute_workflow(session, project_id, run_id, thread_id, job_type, payload, guard):
    from sqlalchemy import select
    from app.architecture.service import generate_architecture
    from app.core.config import get_settings
    from app.db.models import CodebaseMap, Source
    from app.services.collection import collect_project_sources
    from app.services.run_scope import scoped_collection_rows
    from app.services.reports import create_intelligent_report_snapshot
    from app.services.workflow import stage_event, workflow_state

    lease_guard = guard
    guard = lambda: lease_guard(session)

    project = require_project(session, project_id)
    run = require_run(session, run_id)
    previous = workflow_state(session, project, run_id, include_previous_attempts=True)
    previous_stages = {item["key"]: item for item in previous["stages"]}
    completed = {item["key"] for item in previous["stages"]
                 if item["status"] in {"completed", "skipped"}}

    def reuse_stage(key):
        guard()
        previous_stage = previous_stages[key]
        stage_event(session, project_id, run_id, key, previous_stage["status"],
                    "已检查并复用上次保存的阶段产物。" + previous_stage["detail"],
                    **({"warning": "；".join(previous["warnings"])} if key == "collection" and previous["warnings"] else {}))
        session.commit()

    @contextmanager
    def stage(key, detail):
        guard()
        stage_event(session, project_id, run_id, key, "running", detail)
        session.commit()
        try:
            yield
            guard()
        except JobLeaseLost:
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            stage_event(session, project_id, run_id, key, "failed", str(exc))
            session.commit()
            raise

    if "collection" not in completed:
        with stage("collection", "正在读取并扫描已配置的输入源"):
            sources = list(session.scalars(select(Source).where(Source.project_id == project_id)).all())
            for source in sources:
                guard()
                collect_project_sources(session, project, get_settings(), source_ids={source.id}, run_id=run_id)
                guard()
                session.commit()
            if not any(source.status == "collected" for source in sources):
                raise RuntimeError("所有输入源采集失败，请检查路径或网络后重试。")
            failed_count = sum(source.status != "collected" for source in sources)
            warning = f"{failed_count} 个输入源采集失败，报告仅基于成功采集的资料。" if failed_count else None
            stage_event(session, project_id, run_id, "collection", "completed", "输入源已采集并保存",
                        **({"warning": warning} if warning else {}))
            session.commit()

    else:
        reuse_stage("collection")

    if "analysis" not in completed:
        with stage("analysis", "正在分析证据并运行质量校验"):
            for event_payload in langgraph_runner.stream_run_graph_events(
                session, project_id, run_id, thread_id, guard=guard,
                resume_payload=payload if job_type == "resume" else None,
            ):
                guard()
                record_run_event(session, project_id, run_id, "node_completed", event_payload)
                session.commit()
            session.refresh(run)
            if run.status == "paused_for_input":
                stage_event(session, project_id, run_id, "analysis", "pending", "需要补充关键问题后继续")
                session.commit()
                return
            if run.status not in {"ready_for_review", "ready_for_review_with_risks"}:
                raise RuntimeError(run.stop_reason or "分析未生成可用于报告的结果。")
            stage_event(session, project_id, run_id, "analysis", "completed", "证据分析与质量校验已完成")
            session.commit()
    else:
        # The graph may already be complete when a later stage is retried.
        # Serialize with cancel_run, which locks the project row, and only
        # restore status while this worker still owns the job lease.
        session.scalar(select(Project).where(Project.id == project_id).with_for_update())
        guard()
        run.status = "ready_for_review_with_risks"
        project.status = run.status
        session.commit()
        reuse_stage("analysis")

    if "architecture" not in completed:
        with stage("architecture", "正在根据采集的代码生成架构图"):
            codebase = scoped_collection_rows(session, CodebaseMap, project_id, run_id)
            if not codebase:
                warning = "输入源中没有代码库，已跳过架构图；报告仍会基于文本资料生成。"
                stage_event(session, project_id, run_id, "architecture", "skipped", warning, warning=warning)
            else:
                diagrams = generate_architecture(session, project, run_id=run_id)
                guard()
                stage_event(session, project_id, run_id, "architecture", "completed", f"已生成 {len(diagrams)} 张架构图")
            session.commit()
    else:
        reuse_stage("architecture")

    if "report" not in completed:
        with stage("report", "正在生成并保存可下载的调研报告"):
            report = create_intelligent_report_snapshot(session, project, run_id=run_id)
            guard()
            stage_event(session, project_id, run_id, "report", "completed", "调研报告已保存，可查看和下载",
                        report_id=report.id)
            session.commit()
    else:
        reuse_stage("report")


def ensure_job_still_owned(
    session_factory: Callable[[], Session],
    job_id: str,
    worker_id: str,
) -> None:
    """重新读取 job 租约；取消或换 owner 后立即停止，避免继续写节点事件。"""

    with session_factory() as session:
        job = require_job(session, job_id)
        ensure_loaded_job_still_owned(job, worker_id)


def ensure_loaded_job_still_owned(job: RunJob, worker_id: str) -> None:
    if job.status != "running" or job.locked_by != worker_id:
        raise JobLeaseLost("Run job lease is no longer owned by this worker")


def heartbeat_current_job(
    session_factory: Callable[[], Session],
    job_id: str,
    worker_id: str,
    lease_seconds: int,
) -> None:
    """节点事件提交后单独续租，避免长图执行期间 daemon 误判为 stale job。"""

    try:
        with session_factory() as session:
            job = require_job(session, job_id)
            heartbeat_job(job, worker_id=worker_id, lease_seconds=lease_seconds)
            session.commit()
    except ValueError as exc:
        raise JobLeaseLost("Run job lease was claimed by another worker") from exc


def require_job(session: Session, job_id: str) -> RunJob:
    job = session.get(RunJob, job_id)
    if job is None:
        raise RuntimeError("Run job not found")
    return job


def require_run(session: Session, run_id: str) -> AnalysisRun:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise RuntimeError("Run not found")
    return run


def require_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise RuntimeError("Project not found")
    return project
