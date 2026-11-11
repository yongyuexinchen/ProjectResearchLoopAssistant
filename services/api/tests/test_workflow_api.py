from pathlib import Path

import pytest

from app.llm.router import LLMRouter
from app.workers.run_worker import run_one_job
from tests.test_runs_api import build_client


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    monkeypatch.setattr(LLMRouter, "chat", lambda *args, **kwargs: {"status": "not_configured"})


def setup_payload(tmp_path: Path, *, text_only=False, goal="Understand this project"):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("# Example\nA small Python service.", encoding="utf-8")
    (root / "app.py").write_text("class Service:\n    pass\n", encoding="utf-8")
    return {
        "name": "Automatic research", "topic": "Engineering onboarding", "analysis_goal": goal,
        "sources": [{"source_type": "local_file" if text_only else "local_directory",
                     "uri": str(root / "README.md" if text_only else root)}],
    }


def test_setup_is_atomic_when_a_source_is_invalid(tmp_path):
    client = build_client()
    payload = setup_payload(tmp_path)
    payload["sources"].append({"source_type": "local_directory", "uri": str(tmp_path / "missing")})

    response = client.post("/projects/setup", json=payload)

    assert response.status_code == 400
    assert client.get("/projects").json() == []


def test_setup_enqueues_and_worker_persists_entire_research_package(tmp_path):
    client = build_client()
    response = client.post("/projects/setup", json=setup_payload(tmp_path))
    assert response.status_code == 202
    created = response.json()
    project_id = created["run"]["project_id"]
    assert created["job"]["payload_json"]["workflow"] is True
    queued = client.get(f"/projects/{project_id}/workflow").json()
    assert queued["status"] == "queued"
    assert queued["progress"] == 0
    assert queued["report"] is None

    assert run_one_job() is True

    result = client.get(f"/projects/{project_id}/workflow").json()
    assert result["status"] == "completed"
    assert result["progress"] == 100
    assert [stage["status"] for stage in result["stages"]] == ["completed"] * 4
    assert result["report"]["run_id"] == created["run"]["id"]
    assert result["report"]["markdown_content"]
    assert result["architecture_count"] >= 2


def test_text_input_skips_diagrams_with_warning_and_still_generates_report(tmp_path):
    client = build_client()
    created = client.post("/projects/setup", json=setup_payload(tmp_path, text_only=True)).json()
    project_id = created["run"]["project_id"]
    run_one_job()

    result = client.get(f"/projects/{project_id}/workflow").json()

    assert result["status"] == "completed"
    assert result["stages"][2]["status"] == "skipped"
    assert result["warnings"]
    assert result["architecture_count"] == 0
    assert result["report"] is not None


def test_existing_workflow_rejects_missing_sources_and_active_duplicate(tmp_path):
    client = build_client()
    project = client.post("/projects", json={"name": "Empty", "topic": "Research"}).json()
    assert client.post(f"/projects/{project['id']}/workflow").status_code == 400
    created = client.post("/projects/setup", json=setup_payload(tmp_path)).json()
    assert client.post(f"/projects/{created['run']['project_id']}/workflow").status_code == 409


def test_failed_collection_is_truthful_and_retry_keeps_workflow(tmp_path, monkeypatch):
    from app.services import collection
    client = build_client()
    created = client.post("/projects/setup", json=setup_payload(tmp_path)).json()
    project_id, run_id = created["run"]["project_id"], created["run"]["id"]
    original = collection.collect_one_source
    monkeypatch.setattr(collection, "collect_one_source", lambda *args: (_ for _ in ()).throw(RuntimeError("disk unavailable")))
    run_one_job()
    failed = client.get(f"/projects/{project_id}/workflow").json()
    assert failed["status"] == "failed"
    assert failed["progress"] == 0
    assert failed["stages"][0]["status"] == "failed"
    assert failed["error"]
    assert failed["report"] is None

    monkeypatch.setattr(collection, "collect_one_source", original)
    retried = client.post(f"/projects/{project_id}/runs/{run_id}/retry")
    assert retried.status_code == 202
    assert retried.json()["job"]["payload_json"]["workflow"] is True
    run_one_job()
    assert client.get(f"/projects/{project_id}/workflow").json()["status"] == "completed"


def test_paused_workflow_can_resume_in_background_and_finish_report(tmp_path):
    client = build_client()
    created = client.post("/projects/setup", json=setup_payload(tmp_path, goal=None)).json()
    project_id, run_id = created["run"]["project_id"], created["run"]["id"]
    run_one_job()
    paused = client.get(f"/projects/{project_id}/workflow").json()
    assert paused["status"] == "paused_for_input"
    assert paused["progress"] < 100
    assert paused["report"] is None
    package = client.get(f"/projects/{project_id}/runs/{run_id}").json()
    question = next(question for question in package["questions"] if question["status"] == "open")
    client.post(f"/projects/{project_id}/questions/{question['id']}/answer", json={"answer_text": "Assess adoption."})
    resumed = client.post(f"/projects/{project_id}/runs/{run_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["run"]["status"] == "queued"
    run_one_job()
    result = client.get(f"/projects/{project_id}/workflow").json()
    assert result["status"] == "completed"
    assert result["report"] is not None


def test_cancelled_workflow_never_claims_completion(tmp_path):
    client = build_client()
    created = client.post("/projects/setup", json=setup_payload(tmp_path)).json()
    project_id, run_id = created["run"]["project_id"], created["run"]["id"]
    client.post(f"/projects/{project_id}/runs/{run_id}/cancel")
    assert run_one_job() is False
    result = client.get(f"/projects/{project_id}/workflow").json()
    assert result["status"] == "cancelled"
    assert result["progress"] < 100
    assert result["report"] is None


def test_cancellation_during_analysis_is_not_overwritten_by_node_commit(tmp_path, monkeypatch):
    from app.engine import langgraph_runner
    client = build_client()
    created = client.post("/projects/setup", json=setup_payload(tmp_path)).json()
    project_id, run_id = created["run"]["project_id"], created["run"]["id"]
    original = langgraph_runner.analyze_context

    def cancel_during_analysis(context):
        client.post(f"/projects/{project_id}/runs/{run_id}/cancel")
        return original(context)

    monkeypatch.setattr(langgraph_runner, "analyze_context", cancel_during_analysis)
    run_one_job()
    result = client.get(f"/projects/{project_id}/workflow").json()
    assert result["status"] == "cancelled"
    assert result["report"] is None
    assert result["progress"] == 25


def test_architecture_scans_the_source_of_the_selected_codebase_map(tmp_path):
    client = build_client()
    payload = setup_payload(tmp_path)
    second_root = tmp_path / "second_repo"
    second_root.mkdir()
    (second_root / "app.py").write_text("class SecondService:\n    pass\n", encoding="utf-8")
    payload["sources"].append({"source_type": "local_directory", "uri": str(second_root)})
    created = client.post("/projects/setup", json=payload).json()
    project_id = created["run"]["project_id"]
    run_one_job()
    diagrams = client.get(f"/projects/{project_id}/architecture").json()
    assert diagrams
    assert all(Path(diagram["stats_json"]["scanned_root"]) == second_root.resolve() for diagram in diagrams)


def test_long_operation_keeps_job_lease_alive(tmp_path):
    from time import sleep
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.base import Base
    from app.db.models import RunJob
    from app.services.run_jobs import mark_job_running, recover_stale_jobs
    from app.workers.run_worker import maintain_job_lease
    from tests.test_run_jobs_events import create_project_and_run

    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'lease.sqlite').as_posix()}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        project, run = create_project_and_run(session)
        job = RunJob(project_id=project.id, run_id=run.id, job_type="start")
        session.add(job)
        session.flush()
        mark_job_running(job, "worker-a", lease_seconds=1)
        session.commit()
        job_id = job.id
    with maintain_job_lease(factory, job_id, "worker-a", 1) as guard:
        sleep(1.3)
        guard()
        with factory() as session:
            assert recover_stale_jobs(session) == []
            assert session.get(RunJob, job_id).locked_by == "worker-a"
    engine.dispose()


def test_legacy_run_without_report_does_not_claim_automatic_pipeline(tmp_path):
    from tests.test_runs_api import create_collected_project, enqueue_and_process_run
    client = build_client()
    project = create_collected_project(client, tmp_path)
    package = enqueue_and_process_run(client, project["id"])
    result = client.get(f"/projects/{project['id']}/workflow", params={"run_id": package["run"]["id"]}).json()
    assert result["status"] == "idle"
    assert result["progress"] < 100
    assert result["report"] is None
    assert result["warnings"]


def test_legacy_report_is_shown_as_persisted_result(tmp_path):
    from tests.test_runs_api import create_collected_project, enqueue_and_process_run
    client = build_client()
    project = create_collected_project(client, tmp_path)
    package = enqueue_and_process_run(client, project["id"])
    report = client.post(f"/projects/{project['id']}/reports").json()
    result = client.get(f"/projects/{project['id']}/workflow", params={"run_id": package["run"]["id"]}).json()
    assert result["status"] == "completed"
    assert result["report"]["id"] == report["id"]
    assert result["warnings"]


def test_report_failure_retry_starts_at_zero_then_reuses_saved_analysis(tmp_path, monkeypatch):
    from app.services import reports
    client = build_client()
    created = client.post("/projects/setup", json=setup_payload(tmp_path)).json()
    project_id, run_id = created["run"]["project_id"], created["run"]["id"]
    original = reports.create_intelligent_report_snapshot
    monkeypatch.setattr(reports, "create_intelligent_report_snapshot", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("report unavailable")))
    run_one_job()
    failed = client.get(f"/projects/{project_id}/workflow").json()
    assert failed["status"] == "failed"
    assert failed["progress"] == 75
    original_package = client.get(f"/projects/{project_id}/runs/{run_id}").json()
    client.post(f"/projects/{project_id}/runs/{run_id}/retry")
    queued = client.get(f"/projects/{project_id}/workflow").json()
    assert queued["progress"] == 0
    monkeypatch.setattr(reports, "create_intelligent_report_snapshot", original)
    run_one_job()
    result = client.get(f"/projects/{project_id}/workflow").json()
    retried_package = client.get(f"/projects/{project_id}/runs/{run_id}").json()
    assert result["status"] == "completed"
    assert len(original_package["evidence_items"]) == len(retried_package["evidence_items"])


def test_retry_resumes_checkpoint_without_duplicating_analysis_artifacts(tmp_path, monkeypatch):
    from app.engine import langgraph_runner
    client = build_client()
    created = client.post("/projects/setup", json=setup_payload(tmp_path)).json()
    project_id, run_id = created["run"]["project_id"], created["run"]["id"]
    original = langgraph_runner.verify_package_node
    monkeypatch.setattr(langgraph_runner, "verify_package_node", lambda *args: (_ for _ in ()).throw(RuntimeError("verifier unavailable")))
    run_one_job()
    first = client.get(f"/projects/{project_id}/runs/{run_id}").json()
    assert first["run"]["status"] == "failed"
    assert first["evidence_items"]
    monkeypatch.setattr(langgraph_runner, "verify_package_node", original)
    client.post(f"/projects/{project_id}/runs/{run_id}/retry")
    run_one_job()
    second = client.get(f"/projects/{project_id}/runs/{run_id}").json()
    assert second["run"]["status"] in {"ready_for_review", "ready_for_review_with_risks"}
    assert len(second["evidence_items"]) == len(first["evidence_items"])


def test_retry_old_run_cannot_interrupt_new_active_workflow(tmp_path):
    client = build_client()
    created = client.post("/projects/setup", json=setup_payload(tmp_path)).json()
    project_id, run_id = created["run"]["project_id"], created["run"]["id"]
    client.post(f"/projects/{project_id}/runs/{run_id}/cancel")
    assert client.post(f"/projects/{project_id}/workflow").status_code == 202
    assert client.post(f"/projects/{project_id}/runs/{run_id}/retry").status_code == 409


def test_completed_workflow_cannot_be_cancelled_after_report_is_saved(tmp_path):
    client = build_client()
    created = client.post("/projects/setup", json=setup_payload(tmp_path)).json()
    project_id, run_id = created["run"]["project_id"], created["run"]["id"]
    run_one_job()
    assert client.post(f"/projects/{project_id}/runs/{run_id}/cancel").status_code == 409
    assert client.get(f"/projects/{project_id}/workflow").json()["status"] == "completed"


def test_duplicate_retry_does_not_create_another_active_job(tmp_path):
    from sqlalchemy import select
    from app.db.models import RunJob
    from app.db.session import get_worker_session_factory
    client = build_client()
    created = client.post("/projects/setup", json=setup_payload(tmp_path)).json()
    project_id, run_id = created["run"]["project_id"], created["run"]["id"]
    client.post(f"/projects/{project_id}/runs/{run_id}/cancel")
    assert client.post(f"/projects/{project_id}/runs/{run_id}/retry").status_code == 202
    assert client.post(f"/projects/{project_id}/runs/{run_id}/retry").status_code == 409
    with get_worker_session_factory()() as session:
        jobs = list(session.scalars(select(RunJob).where(RunJob.project_id == project_id,
                                                       RunJob.status.in_({"queued", "running"}))).all())
        assert len(jobs) == 1


def test_historical_paused_run_cannot_resume_while_another_project_job_is_active(tmp_path):
    from app.db.models import AnalysisRun, Project
    from app.db.session import get_worker_session_factory
    from app.services.run_jobs import create_run_job
    client = build_client()
    created = client.post("/projects/setup", json=setup_payload(tmp_path, goal=None)).json()
    project_id, run_id = created["run"]["project_id"], created["run"]["id"]
    run_one_job()
    with get_worker_session_factory()() as session:
        project = session.get(Project, project_id)
        project.status = "queued"
        other = AnalysisRun(project_id=project_id, status="queued")
        session.add(other)
        session.flush()
        create_run_job(session, project_id, other.id, "start", payload={"workflow": True})
        session.commit()
    response = client.post(f"/projects/{project_id}/runs/{run_id}/resume")
    assert response.status_code == 409
    with get_worker_session_factory()() as session:
        assert session.get(AnalysisRun, run_id).status == "paused_for_input"


def test_architecture_is_retained_and_filtered_for_each_workflow_run(tmp_path):
    client = build_client()
    created = client.post("/projects/setup", json=setup_payload(tmp_path)).json()
    project_id, first_id = created["run"]["project_id"], created["run"]["id"]
    run_one_job()
    first_diagrams = client.get(f"/projects/{project_id}/architecture", params={"run_id": first_id}).json()
    second = client.post(f"/projects/{project_id}/workflow").json()
    second_id = second["run"]["id"]
    run_one_job()
    first_again = client.get(f"/projects/{project_id}/architecture", params={"run_id": first_id}).json()
    second_diagrams = client.get(f"/projects/{project_id}/architecture", params={"run_id": second_id}).json()
    assert first_diagrams and second_diagrams
    assert {row["id"] for row in first_again} == {row["id"] for row in first_diagrams}
    assert all(row["stats_json"]["run_id"] == second_id for row in second_diagrams)
    latest = client.get(f"/projects/{project_id}/architecture").json()
    assert {row["id"] for row in latest} == {row["id"] for row in second_diagrams}
    state = client.get(f"/projects/{project_id}/workflow", params={"run_id": first_id}).json()
    assert state["architecture_count"] == len(first_diagrams)
    assert client.get(f"/projects/{project_id}/architecture", params={"run_id": "missing"}).status_code == 404


def test_text_workflow_does_not_count_later_code_workflow_diagrams(tmp_path):
    client = build_client()
    payload = setup_payload(tmp_path, text_only=True)
    created = client.post("/projects/setup", json=payload).json()
    project_id, first_id = created["run"]["project_id"], created["run"]["id"]
    run_one_job()
    client.post(f"/projects/{project_id}/sources", json={"source_type": "local_directory", "uri": str(tmp_path / "repo")})
    client.post(f"/projects/{project_id}/workflow")
    run_one_job()
    state = client.get(f"/projects/{project_id}/workflow", params={"run_id": first_id}).json()
    assert state["architecture_count"] == 0
    assert client.get(f"/projects/{project_id}/architecture", params={"run_id": first_id}).json() == []
