from copy import deepcopy

import pytest

from app.architecture.graph_builder import Graph, GraphNode
from app.architecture.mermaid import render_mermaid
from app.architecture.service import _graph_from_snapshot, regenerate_diagram
from app.db.models import ArchitectureDiagram


def source_graph():
    return Graph(
        kind="source_flow", title="源码调用总图", basis="static:source_ast",
        nodes=[GraphNode(id="f_main", label="main · L2", path="app.py", kind="function")],
        details={
            "version": 1, "files": [{"path": "app.py", "sha256": "a" * 64, "line_count": 3, "language": "python"}],
            "functions": [{"id": "f_main", "path": "app.py", "name": "main", "qualified_name": "main",
                           "line_start": 2, "line_end": 3, "parameters": [], "docstring": "",
                           "statements": [{"kind": "return", "label": "返回结果", "line_start": 3,
                                           "line_end": 3, "excerpt": "return 1"}], "calls": [], "entrypoint": None}],
            "stats": {}, "limits": {}, "warnings": [],
        },
    )


def test_source_diagram_keeps_function_file_and_line_in_long_labels():
    graph = source_graph()
    graph.nodes[0].label = "service_" * 12 + "<br/>services/api/app/very_long_module/main.py:L123-L145"
    source = render_mermaid(graph)
    assert "main.py:L123-L145" in source


def test_source_snapshot_regeneration_preserves_exact_index_without_live_scan():
    graph = source_graph()
    snapshot = graph.to_dict()
    diagram = ArchitectureDiagram(
        id="saved", project_id="project", diagram_type=graph.kind,
        title=graph.title, basis=graph.basis, mermaid_source="broken", graph_json=deepcopy(snapshot),
        stats_json={"run_id": "old-run"},
    )
    regenerate_diagram(diagram)
    assert diagram.mermaid_source == render_mermaid(graph)
    assert diagram.graph_json == snapshot
    assert _graph_from_snapshot(snapshot, "source_flow").to_dict() == snapshot
    restored = _graph_from_snapshot(snapshot, "source_flow")
    restored.details["functions"][0]["name"] = "changed"
    assert snapshot["details"]["functions"][0]["name"] == "main"


@pytest.mark.parametrize("invalid", [None, [], "not-an-index"])
def test_source_snapshot_rejects_invalid_details(invalid):
    snapshot = source_graph().to_dict()
    snapshot["details"] = invalid
    with pytest.raises(ValueError):
        _graph_from_snapshot(snapshot, "source_flow")


def test_generation_persists_source_lines_and_regenerates_without_reading_changed_source(tmp_path):
    from tests.test_collection_api import build_client, create_project

    client, _ = build_client()
    project = create_project(client)
    source = tmp_path / "app.py"
    source.write_text("def helper():\n    return 1\n\ndef main():\n    return helper()\n", encoding="utf-8")
    response = client.post(f"/projects/{project['id']}/sources",
                           json={"source_type": "local_directory", "uri": str(tmp_path)})
    assert response.status_code == 201
    assert client.post(f"/projects/{project['id']}/collect").status_code == 200
    response = client.post(f"/projects/{project['id']}/architecture")
    assert response.status_code == 201
    diagrams = response.json()
    source_diagrams = [item for item in diagrams if item["diagram_type"] == "source_flow"]
    assert len(source_diagrams) == 1
    saved = source_diagrams[0]
    functions = saved["graph_json"]["details"]["functions"]
    main = next(fn for fn in functions if fn["qualified_name"] == "main")
    helper = next(fn for fn in functions if fn["qualified_name"] == "helper")
    assert main["line_start"] == 4 and main["calls"][0]["line"] == 5
    assert main["calls"][0]["target_id"] == helper["id"]
    source.write_text("def replacement():\n    pass\n", encoding="utf-8")
    repaired = client.post(f"/projects/{project['id']}/architecture/{saved['id']}/regenerate")
    assert repaired.status_code == 200
    assert repaired.json()["graph_json"] == saved["graph_json"]
    assert "replacement" not in repaired.json()["mermaid_source"]



def test_old_graph_snapshot_without_details_remains_supported():
    graph = Graph(kind="module_map", title="old", basis="deterministic:file_tree",
                  nodes=[GraphNode(id="root", label="root", path="", kind="root")])
    snapshot = graph.to_dict()
    snapshot.pop("details", None)
    assert _graph_from_snapshot(snapshot, "module_map").nodes[0].label == "root"


def test_manual_generation_attaches_to_current_run_for_report_selection(tmp_path):
    from tests.test_collection_api import build_client, create_project
    from app.db.models import AnalysisRun

    client, sessions = build_client()
    project = create_project(client)
    (tmp_path / "main.py").write_text("print('entry')\n", encoding="utf-8")
    client.post(f"/projects/{project['id']}/sources",
                json={"source_type": "local_directory", "uri": str(tmp_path)})
    client.post(f"/projects/{project['id']}/collect")
    with sessions() as session:
        run = AnalysisRun(project_id=project["id"], status="ready_for_review_with_risks")
        session.add(run)
        session.commit()
        run_id = run.id
    response = client.post(f"/projects/{project['id']}/architecture")
    assert response.status_code == 201
    assert response.json()
    assert all(diagram["stats_json"]["run_id"] == run_id for diagram in response.json())

@pytest.mark.parametrize("field,value", [("reason", {}), ("column", -1), ("column", True)])
def test_source_snapshot_rejects_malformed_call_metadata(field, value):
    snapshot = source_graph().to_dict()
    call = {"expression": "handler", "line": 3, "column": 0, "target_id": None,
            "resolution": "unresolved", "reason": "dynamic"}
    call[field] = value
    snapshot["details"]["functions"][0]["calls"] = [call]
    with pytest.raises(ValueError):
        _graph_from_snapshot(snapshot, "source_flow")
