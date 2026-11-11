from pathlib import Path

from app.llm.router import LLMRouter

from tests.test_runs_api import build_client, create_collected_project, enqueue_and_process_run


def create_project_with_run(tmp_path: Path):
    client = build_client()
    project = create_collected_project(client, tmp_path)
    return client, project, enqueue_and_process_run(client, project["id"])


def cancel_active_runs(client, project_id: str) -> None:
    for run in client.get(f"/projects/{project_id}/runs").json():
        if run["status"] in {"queued", "running", "paused_for_input"}:
            client.post(f"/projects/{project_id}/runs/{run['id']}/cancel")


def test_create_get_latest_and_export_report(tmp_path: Path):
    client, project, run_package = create_project_with_run(tmp_path)

    create_response = client.post(f"/projects/{project['id']}/reports")
    latest_response = client.get(f"/projects/{project['id']}/reports/latest")

    assert create_response.status_code == 201
    report = create_response.json()
    assert report["project_id"] == project["id"]
    assert report["run_id"] == run_package["run"]["id"]
    assert report["status"] == "draft"
    assert report["verifier_result_json"]["checks"]
    assert "# Run project 项目调研报告" in report["markdown_content"]

    assert latest_response.status_code == 200
    assert latest_response.json()["id"] == report["id"]

    markdown_response = client.get(f"/projects/{project['id']}/reports/{report['id']}/markdown")
    assert markdown_response.status_code == 200
    assert "## 校验摘要" in markdown_response.json()["markdown"]


def test_report_api_loads_source_index_lazily(tmp_path: Path):
    client, project, _ = create_project_with_run(tmp_path)
    architecture = client.post(f"/projects/{project['id']}/architecture")
    assert architecture.status_code == 201
    report = client.post(f"/projects/{project['id']}/reports").json()

    loaded = client.get(f"/projects/{project['id']}/reports/{report['id']}")
    assert loaded.status_code == 200
    diagrams = loaded.json()["verifier_result_json"]["architecture_diagrams"]
    assert diagrams
    assert all("details" not in item["graph_json"] for item in diagrams)

    source_index = client.get(f"/projects/{project['id']}/reports/{report['id']}/source-index")
    assert source_index.status_code == 200
    rows = source_index.json()["diagrams"]
    assert rows
    assert rows[0]["details"]["functions"]


def test_create_intelligent_report_falls_back_when_llm_raises(tmp_path: Path, monkeypatch):
    def fake_chat(self, **kwargs):
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(LLMRouter, "chat", fake_chat)
    client, project, run_package = create_project_with_run(tmp_path)

    create_response = client.post(f"/projects/{project['id']}/reports/intelligent")

    assert create_response.status_code == 201
    report = create_response.json()
    assert report["project_id"] == project["id"]
    assert report["run_id"] == run_package["run"]["id"]
    assert "智能报告增强" not in report["markdown_content"]

    latest_response = client.get(f"/projects/{project['id']}/reports/latest")
    assert latest_response.status_code == 200
    assert latest_response.json()["id"] == report["id"]


def test_approved_report_marks_project_completed(tmp_path: Path):
    client, project, _ = create_project_with_run(tmp_path)
    report = client.post(f"/projects/{project['id']}/reports").json()

    review_response = client.post(
        f"/projects/{project['id']}/reports/{report['id']}/review",
        json={"decision": "approved", "comment": "Approved for the next milestone."},
    )

    assert review_response.status_code == 200
    reviewed_report = review_response.json()
    assert reviewed_report["status"] == "approved"
    assert reviewed_report["review_decision"] == "approved"
    assert reviewed_report["review_comment"] == "Approved for the next milestone."
    assert client.get(f"/projects/{project['id']}").json()["status"] == "completed"


def test_needs_more_report_keeps_project_reviewable_with_risks(tmp_path: Path):
    client, project, _ = create_project_with_run(tmp_path)
    report = client.post(f"/projects/{project['id']}/reports").json()

    review_response = client.post(
        f"/projects/{project['id']}/reports/{report['id']}/review",
        json={"decision": "needs_more", "comment": "Need stronger evidence coverage."},
    )

    assert review_response.status_code == 200
    reviewed_report = review_response.json()
    assert reviewed_report["status"] == "needs_more"
    assert reviewed_report["review_decision"] == "needs_more"
    assert client.get(f"/projects/{project['id']}").json()["status"] == "queued"


def test_followup_review_requires_comment(tmp_path: Path):
    client, project, _ = create_project_with_run(tmp_path)
    report = client.post(f"/projects/{project['id']}/reports").json()

    needs_more_response = client.post(
        f"/projects/{project['id']}/reports/{report['id']}/review",
        json={"decision": "needs_more", "comment": ""},
    )
    rejected_response = client.post(
        f"/projects/{project['id']}/reports/{report['id']}/review",
        json={"decision": "rejected"},
    )

    assert needs_more_response.status_code == 400
    assert rejected_response.status_code == 400


def test_needs_more_review_is_idempotent_and_does_not_queue_twice(tmp_path: Path):
    client, project, _ = create_project_with_run(tmp_path)
    report = client.post(f"/projects/{project['id']}/reports").json()

    first = client.post(
        f"/projects/{project['id']}/reports/{report['id']}/review",
        json={"decision": "needs_more", "comment": "Need stronger evidence coverage."},
    )
    second = client.post(
        f"/projects/{project['id']}/reports/{report['id']}/review",
        json={"decision": "needs_more", "comment": "Need stronger evidence coverage."},
    )

    assert first.status_code == second.status_code == 200
    assert len(client.get(f"/projects/{project['id']}/runs").json()) == 2
    cancel_active_runs(client, project["id"])


def test_historical_review_cannot_change_current_project_or_enqueue(tmp_path: Path):
    client, project, first_package = create_project_with_run(tmp_path)
    report = client.post(f"/projects/{project['id']}/reports").json()
    second = client.post(f"/projects/{project['id']}/workflow")
    assert second.status_code == 202
    before_runs = len(client.get(f"/projects/{project['id']}/runs").json())

    approved = client.post(
        f"/projects/{project['id']}/reports/{report['id']}/review",
        json={"decision": "approved", "comment": "Historical approval."},
    )
    needs_more = client.post(
        f"/projects/{project['id']}/reports/{report['id']}/review",
        json={"decision": "needs_more", "comment": "Should not enqueue from history."},
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert needs_more.status_code == 400
    assert client.get(f"/projects/{project['id']}").json()["status"] == "queued"
    assert len(client.get(f"/projects/{project['id']}/runs").json()) == before_runs
    assert first_package["run"]["id"] != second.json()["run"]["id"]
    cancel_active_runs(client, project["id"])


def test_review_is_blocked_while_current_run_is_active(tmp_path: Path):
    client, project, first_package = create_project_with_run(tmp_path)
    report = client.post(f"/projects/{project['id']}/reports").json()
    second = client.post(f"/projects/{project['id']}/workflow")
    assert second.status_code == 202
    # The newly queued run is current; its report does not exist yet, but a
    # follow-up review of the old report must not create more work.
    response = client.post(
        f"/projects/{project['id']}/reports/{report['id']}/review",
        json={"decision": "needs_more", "comment": "Blocked while queued."},
    )

    assert response.status_code == 400
    assert len(client.get(f"/projects/{project['id']}/runs").json()) == 2
    assert first_package["run"]["id"] != second.json()["run"]["id"]
    cancel_active_runs(client, project["id"])


def test_needs_more_review_records_feedback_and_starts_followup_run(tmp_path: Path):
    client, project, first_package = create_project_with_run(tmp_path)
    report = client.post(f"/projects/{project['id']}/reports").json()

    review_response = client.post(
        f"/projects/{project['id']}/reports/{report['id']}/review",
        json={"decision": "needs_more", "comment": "Need stronger evidence coverage."},
    )

    assert review_response.status_code == 200
    reviewed_report = review_response.json()
    assert reviewed_report["status"] == "needs_more"
    assert reviewed_report["review_decision"] == "needs_more"
    assert reviewed_report["review_comment"] == "Need stronger evidence coverage."

    runs = client.get(f"/projects/{project['id']}/runs").json()
    assert len(runs) == 2
    assert runs[0]["id"] != first_package["run"]["id"]
    assert runs[0]["status"] == "queued"
    assert runs[0]["execution_mode"] == "background"
    events = client.get(f"/projects/{project['id']}/runs/{runs[0]['id']}/events").json()
    assert events[0]["event_type"] == "run_queued"

    reviewed_package = client.get(f"/projects/{project['id']}/runs/{first_package['run']['id']}").json()
    assert any(
        question["status"] == "answered"
        and question["answer_text"] == "Need stronger evidence coverage."
        and question["metadata_json"]["source"] == "report_review"
        and question["metadata_json"]["decision"] == "needs_more"
        for question in reviewed_package["questions"]
    )
