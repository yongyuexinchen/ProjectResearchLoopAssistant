"""Report consumers must use frozen, exact-run diagrams rather than live architecture rows."""

import json
from copy import deepcopy
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.db.models import AnalysisRun, ArchitectureDiagram, Project
from app.db.session import get_session
from app.llm.router import LLMRouter
from app.main import create_app
from app.services.reports import create_intelligent_report_snapshot, create_report_snapshot
from tests.test_llm_report_generator import create_reportable_project, session_scope

CHAPTER = "\n## 源码流程与架构图\n"


def saved_graph(session, project, run, *, title="Run A source flow"):
    graph = {
        "kind": "source_flow", "title": title, "basis": "deterministic:source_ast",
        "nodes": [
            {"id": "entry", "label": "start app.py:L10", "path": "app.py", "kind": "function", "file_count": 1},
            {"id": "worker", "label": "work lib.py:L30", "path": "lib.py", "kind": "function", "file_count": 1},
        ],
        "edges": [{"source": "entry", "target": "worker", "label": "app.py:L14"}],
        "notes": ["静态调用引用，不代表运行时调用顺序。"],
        "details": {
            "version": 1,
            "files": [{"path": "app.py", "language": "python", "sha256": "a" * 64, "line_count": 20}],
            "functions": [{
                "id": "entry", "path": "app.py", "name": "start", "qualified_name": "start",
                "line_start": 10, "line_end": 18, "parameters": ["request"], "docstring": "Start safely.",
                "statements": [{"kind": "branch", "label": "条件分支", "line_start": 12, "line_end": 15,
                                "excerpt": "if request < 3: <script>alert(1)</script>"}],
                "calls": [{"expression": "work", "line": 14, "column": 4, "target_id": "worker",
                           "resolution": "resolved", "reason": "direct import"},
                          {"expression": "plugin.run", "line": 16, "column": 4, "target_id": None,
                           "resolution": "unresolved", "reason": "dynamic receiver"}],
                "entrypoint": {"kind": "main", "label": "入口候选", "line": 10, "confidence": "candidate"},
            }, {"id": "worker", "path": "lib.py", "name": "work", "qualified_name": "work",
                "line_start": 30, "line_end": 34, "parameters": [], "docstring": "",
                "statements": [], "calls": [], "entrypoint": None}],
            "stats": {"functions": 2}, "limits": {"max_functions": 50}, "warnings": ["动态调用保留为未解析。"],
        },
    }
    row = ArchitectureDiagram(project_id=project.id, diagram_type="source_flow", title=title,
        basis="deterministic:source_ast", mermaid_source='flowchart TD\nentry["start app.py:L10"] -->|"app.py:L14"| worker["work lib.py:L30"]',
        graph_json=graph, stats_json={"run_id": run.id if run else None, "root_label": "repo", "nodes": 2, "edges": 1})
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def report_data():
    with session_scope() as session:
        project, run, evidence = create_reportable_project(session)
        diagram = saved_graph(session, project, run)
        yield session, project, run, evidence, diagram


def test_report_copies_only_matching_project_and_exact_run(report_data):
    session, project, run, _, diagram = report_data
    newer = AnalysisRun(project_id=project.id, status="ready_for_review")
    other_project = Project(name="foreign", topic="foreign")
    session.add_all([newer, other_project]); session.flush()
    saved_graph(session, project, newer, title="NEWER_RUN_ONLY")
    saved_graph(session, project, None, title="UNBOUND_ONLY")
    saved_graph(session, other_project, run, title="FOREIGN_PROJECT_ONLY")

    report = create_report_snapshot(session, project, run_id=run.id)

    snapshots = report.verifier_result_json.get("architecture_diagrams", [])
    assert [item["id"] for item in snapshots] == [diagram.id]
    assert snapshots[0]["graph_json"]["details"]["files"][0]["sha256"] == "a" * 64
    assert CHAPTER in report.markdown_content
    assert "```mermaid" in report.markdown_content
    assert "app.py:L14" in report.markdown_content
    assert "app.py:L10-L18" in report.markdown_content
    assert "app.py:L12-L15" in report.markdown_content
    assert "已解析 → work (lib.py:L30-L34)" in report.markdown_content
    assert "未解析" in report.markdown_content
    assert "&lt;script&gt;" in report.markdown_content
    assert "<script>" not in report.markdown_content
    assert "NEWER_RUN_ONLY" not in report.markdown_content
    assert "FOREIGN_PROJECT_ONLY" not in report.markdown_content


def test_report_with_no_matching_diagram_never_falls_back_to_latest(report_data):
    session, project, _, _, _ = report_data
    no_graph_run = AnalysisRun(project_id=project.id, status="ready_for_review")
    session.add(no_graph_run); session.flush()

    report = create_report_snapshot(session, project, run_id=no_graph_run.id)

    assert report.verifier_result_json.get("architecture_diagrams") == []
    assert "本次运行没有保存架构图" in report.markdown_content
    assert "Run A source flow" not in report.markdown_content


def test_saved_report_graph_is_independent_of_later_graph_mutation(report_data):
    session, project, run, _, diagram = report_data
    report = create_report_snapshot(session, project, run_id=run.id)
    session.flush()
    original_snapshot = deepcopy(report.verifier_result_json.get("architecture_diagrams"))
    original_markdown = report.markdown_content
    graph = deepcopy(diagram.graph_json)
    graph["details"]["functions"][0]["line_start"] = 999
    graph["nodes"][0]["label"] = "CHANGED_AFTER_REPORT"
    diagram.graph_json = graph
    diagram.mermaid_source = "flowchart TD\nchanged[CHANGED_AFTER_REPORT]"
    session.flush(); session.expire(report)

    assert report.verifier_result_json.get("architecture_diagrams") == original_snapshot
    assert original_snapshot is not None
    assert report.markdown_content == original_markdown
    assert "CHANGED_AFTER_REPORT" not in report.markdown_content


def test_intelligent_report_keeps_frozen_deterministic_diagram_chapter(report_data, monkeypatch):
    session, project, run, evidence, _ = report_data
    plain = create_report_snapshot(session, project, run_id=run.id)
    payload = {"executive_summary": "Evidence based explanation.", "sections": [{
        "heading": "源码流程与架构图", "body": "MODEL_ADVISORY_ONLY", "evidence_refs": [evidence.id]}]}
    monkeypatch.setattr(LLMRouter, "chat", lambda self, **kwargs: {"status": "succeeded", "text": json.dumps(payload)})

    intelligent = create_intelligent_report_snapshot(session, project, run_id=run.id)

    assert intelligent.verifier_result_json.get("architecture_diagrams")
    assert intelligent.verifier_result_json["architecture_diagrams"] == plain.verifier_result_json["architecture_diagrams"]
    assert "MODEL_ADVISORY_ONLY" in intelligent.markdown_content
    assert CHAPTER in plain.markdown_content
    assert intelligent.markdown_content.endswith(CHAPTER + plain.markdown_content.split(CHAPTER, 1)[1])


def export_client(session):
    app = create_app()
    engine = session.get_bind()
    def override():
        with Session(engine) as request_session:
            yield request_session
    app.dependency_overrides[get_session] = override
    return TestClient(app)


def test_markdown_and_pdf_exports_use_saved_graph_and_visible_line_keys(report_data):
    session, project, run, _, diagram = report_data
    report = create_report_snapshot(session, project, run_id=run.id)
    session.commit()
    report_id, project_id = report.id, project.id
    diagram.mermaid_source = "flowchart TD\nchanged[CHANGED_AFTER_REPORT]"
    diagram.graph_json = {"nodes": [{"id": "changed", "label": "CHANGED_AFTER_REPORT"}], "edges": []}
    session.commit()
    client = export_client(session)

    markdown = client.get(f"/projects/{project_id}/reports/{report_id}/export.md")
    pdf = client.get(f"/projects/{project_id}/reports/{report_id}/export.pdf")

    assert markdown.status_code == pdf.status_code == 200
    assert "```mermaid" in markdown.text
    assert "app.py:L12-L15" in markdown.text
    reader = PdfReader(BytesIO(pdf.content))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "start app.py:L10" in text
    assert "app.py:L14" in text
    assert "CHANGED_AFTER_REPORT" not in text
    assert "flowchart TD" not in text
    # A diagram export must contain vector boxes, not only printed Mermaid source.
    assert any(b" re" in page.get_contents().get_data() for page in reader.pages)


def test_pdf_graph_cards_paginate_without_omitting_final_nodes(report_data):
    session, project, run, _, diagram = report_data
    graph = deepcopy(diagram.graph_json)
    graph["nodes"] = [{"id": f"n{i}", "label": f"function_{i:03d} file.py:L{i+1}", "path": "file.py", "kind": "function"} for i in range(45)]
    graph["edges"] = [{"source": f"n{i}", "target": f"n{i+1}", "label": f"file.py:L{i+100}"} for i in range(44)]
    diagram.graph_json = graph
    report = create_report_snapshot(session, project, run_id=run.id)
    session.commit()
    response = export_client(session).get(f"/projects/{project.id}/reports/{report.id}/export.pdf")

    reader = PdfReader(BytesIO(response.content))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert len(reader.pages) > 1
    assert "function_044" in text
    assert "file.py:L143" in text
    assert any(b" re" in page.get_contents().get_data() for page in reader.pages)


def test_report_navigation_budget_is_explicit_while_snapshot_keeps_all_functions(report_data):
    session, project, run, _, diagram = report_data
    graph = deepcopy(diagram.graph_json)
    template = graph["details"]["functions"][0]
    functions = []
    for index in range(150):
        function = deepcopy(template)
        function.update(id=f"function-{index}", name=f"bounded_{index:03d}", qualified_name=f"bounded_{index:03d}")
        function["statements"] = [{"kind": "call", "label": "调用", "line_start": i+1, "line_end": i+1,
            "excerpt": f"statement_{index:03d}_{i:03d}"} for i in range(30)]
        function["calls"] = [{"expression": f"call_{index:03d}_{i:03d}", "line": i+1, "target_id": None,
            "resolution": "unresolved", "reason": "dynamic"} for i in range(10)]
        functions.append(function)
    graph["details"]["functions"] = functions
    diagram.graph_json = graph

    report = create_report_snapshot(session, project, run_id=run.id)

    saved_functions = report.verifier_result_json["architecture_diagrams"][0]["graph_json"]["details"]["functions"]
    assert len(saved_functions) == 150
    assert saved_functions[-1]["qualified_name"] == "bounded_149"
    assert "报告导航已截断" in report.markdown_content
    assert "在线报告保存完整本次有界索引，可搜索" in report.markdown_content
    assert "##### bounded_000" in report.markdown_content
    assert "##### bounded_149" not in report.markdown_content
    session.commit()
    response = export_client(session).get(f"/projects/{project.id}/reports/{report.id}/export.pdf")
    reader = PdfReader(BytesIO(response.content))
    pdf_text = "\n".join(page.extract_text() for page in reader.pages)
    assert "报告导航已截断" in pdf_text
    assert "bounded_149" not in pdf_text
    assert len(reader.pages) < 80


def test_pdf_normalizes_graph_breaks_without_altering_source_excerpts(report_data):
    session, project, run, _, diagram = report_data
    graph = deepcopy(diagram.graph_json)
    graph["nodes"][0]["label"] = "start<br/>app.py:L10"
    graph["details"]["functions"][0]["statements"][0]["excerpt"] = "literal<br/>source"
    diagram.graph_json = graph
    report = create_report_snapshot(session, project, run_id=run.id)
    session.commit()
    response = export_client(session).get(f"/projects/{project.id}/reports/{report.id}/export.pdf")
    pdf_text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
    assert "start<br/>" not in pdf_text
    assert "start app.py:L10" in pdf_text
    assert "literal<br/>source" in pdf_text
