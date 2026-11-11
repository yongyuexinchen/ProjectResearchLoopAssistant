from copy import deepcopy

import pytest

from app.architecture.graph_builder import Graph, GraphEdge, GraphNode
from app.db.models import ArchitectureDiagram
from tests.test_collection_api import build_client, create_project


def sequence_snapshot():
    return Graph(
        kind="uml_sequence", title="历史时序图", basis="heuristic:import_order",
        nodes=[
            GraphNode(id="actor", label="调用方", path="", kind="actor"),
            GraphNode(id="s_tools", label="历史 tools", path="tools", kind="participant"),
        ],
        edges=[GraphEdge(source="actor", target="s_tools", label="触发入口")],
    ).to_dict()


def saved_diagram(session, project_id, snapshot=None, **kwargs):
    row = ArchitectureDiagram(
        project_id=project_id, diagram_type="uml_sequence", title="历史时序图",
        basis="heuristic:import_order", mermaid_source="broken historical source",
        graph_json=sequence_snapshot() if snapshot is None else snapshot,
        stats_json={"run_id": "historical-run", "nodes": 2, "edges": 1, "root_label": "old-repo"},
        **kwargs,
    )
    session.add(row)
    session.flush()
    return row


def test_regenerate_one_historical_diagram_preserves_saved_structure_and_other_rows(monkeypatch):
    client, sessions = build_client()
    project = create_project(client)
    with sessions() as session:
        selected = saved_diagram(session, project["id"])
        other = saved_diagram(session, project["id"])
        other.stats_json = {"run_id": "new-current-run"}
        session.commit()
        diagram_id, other_id = selected.id, other.id
        before = client.get(f"/projects/{project['id']}/architecture?run_id=historical-run")
        # No AnalysisRun is necessary to repair an independently saved snapshot.
        assert before.status_code == 404
        snapshot, stats = deepcopy(selected.graph_json), deepcopy(selected.stats_json)
        created_at = selected.created_at.isoformat()

    def reject_live_scan(*args, **kwargs):
        raise AssertionError("single-chart regeneration must only read the saved graph")

    monkeypatch.setattr("app.architecture.service.resolve_source_root", reject_live_scan)
    monkeypatch.setattr("app.architecture.service.build_module_map", reject_live_scan)
    monkeypatch.setattr("app.architecture.service.build_class_diagram", reject_live_scan)
    response = client.post(f"/projects/{project['id']}/architecture/{diagram_id}/regenerate")

    assert response.status_code == 200
    repaired = response.json()
    assert repaired["id"] == diagram_id
    assert repaired["graph_json"] == snapshot
    assert repaired["stats_json"] == stats
    assert repaired["created_at"].replace("Z", "+00:00") == created_at
    assert "历史 tools" in repaired["mermaid_source"]
    assert "participant actor " not in repaired["mermaid_source"]
    assert "actor->>" not in repaired["mermaid_source"]
    with sessions() as session:
        assert session.get(ArchitectureDiagram, diagram_id).mermaid_source == repaired["mermaid_source"]
        untouched = session.get(ArchitectureDiagram, other_id)
        assert untouched.mermaid_source == "broken historical source"
        assert untouched.stats_json == {"run_id": "new-current-run"}
        assert session.query(ArchitectureDiagram).count() == 2


def test_regenerate_class_snapshot_retains_methods_and_human_labels():
    client, sessions = build_client()
    project = create_project(client)
    snapshot = Graph(
        kind="uml_class", title="类图", basis="deterministic:ast + regex",
        nodes=[GraphNode(id="actor", label="HistoryService", path="old.py", kind="class")],
    ).to_dict()
    snapshot["nodes"][0].update(methods=["handle"], bases=["Base"], language="python")
    with sessions() as session:
        row = saved_diagram(session, project["id"], snapshot)
        row.diagram_type = "uml_class"
        session.commit()
        diagram_id = row.id

    response = client.post(f"/projects/{project['id']}/architecture/{diagram_id}/regenerate")

    assert response.status_code == 200
    assert "HistoryService" in response.json()["mermaid_source"]
    assert "+handle()" in response.json()["mermaid_source"]
    assert response.json()["graph_json"] == snapshot


def test_regenerate_rejects_cross_project_and_unknown_ids():
    client, sessions = build_client()
    owner, other = create_project(client), create_project(client)
    with sessions() as session:
        row = saved_diagram(session, owner["id"])
        session.commit()
        diagram_id = row.id
    for project_id, requested_id in ((other["id"], diagram_id), (owner["id"], "missing"), ("missing", diagram_id)):
        assert client.post(f"/projects/{project_id}/architecture/{requested_id}/regenerate").status_code == 404
    with sessions() as session:
        assert session.get(ArchitectureDiagram, diagram_id).mermaid_source == "broken historical source"


@pytest.mark.parametrize("damage", ["empty", "kind", "mismatch", "nodes", "node_id", "edge", "methods"])
def test_regenerate_malformed_snapshot_returns_conflict_without_changing_saved_diagrams(damage):
    client, sessions = build_client()
    project = create_project(client)
    snapshot = sequence_snapshot()
    if damage == "empty":
        snapshot = {}
    elif damage == "kind":
        snapshot["kind"] = "unknown_diagram"
    elif damage == "mismatch":
        snapshot["kind"] = "uml_class"
    elif damage == "nodes":
        snapshot["nodes"] = {"actor": {}}
    elif damage == "node_id":
        del snapshot["nodes"][0]["id"]
    elif damage == "edge":
        snapshot["edges"][0]["target"] = "missing-node"
    elif damage == "methods":
        snapshot["nodes"][0]["methods"] = {"inject": "invalid"}
    with sessions() as session:
        row = saved_diagram(session, project["id"], snapshot)
        other = saved_diagram(session, project["id"])
        session.commit()
        diagram_id, other_id = row.id, other.id

    response = client.post(f"/projects/{project['id']}/architecture/{diagram_id}/regenerate")

    assert response.status_code == 409
    assert "快照" in response.json()["detail"]
    with sessions() as session:
        for requested_id in (diagram_id, other_id):
            assert session.get(ArchitectureDiagram, requested_id).mermaid_source == "broken historical source"
        assert session.get(ArchitectureDiagram, diagram_id).graph_json == snapshot
