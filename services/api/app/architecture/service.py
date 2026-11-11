from __future__ import annotations

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.architecture.graph_builder import (
    Graph,
    GraphEdge,
    GraphNode,
    build_data_flow,
    build_dependency_flow,
    build_module_map,
    codebase_map_payload,
    resolve_source_root,
)
from app.architecture.mermaid import render_mermaid
from app.architecture.source_flow import build_source_flow
from app.architecture.uml import build_class_diagram, build_component_diagram, build_sequence_diagram
from app.db.models import ArchitectureDiagram, CodebaseMap, Project
from app.services.run_scope import scoped_collection_rows

DIAGRAM_ORDER = {
    "source_flow": -1,
    "module_map": 0,
    "uml_component": 1,
    "uml_class": 2,
    "uml_sequence": 3,
    "data_flow": 4,
}

SUPPORTED_DIAGRAM_KINDS = set(DIAGRAM_ORDER) | {"dependency_flow"}


def regenerate_diagram(diagram: ArchitectureDiagram) -> ArchitectureDiagram:
    """Repair one saved diagram from its own snapshot, including historical runs."""

    graph = _graph_from_snapshot(diagram.graph_json, diagram.diagram_type)
    source = render_mermaid(graph)
    # Validate and render before changing any persisted field. Metadata and snapshot stay intact.
    diagram.mermaid_source = source
    return diagram


def _graph_from_snapshot(snapshot: object, diagram_type: str) -> Graph:
    error = "这张图的已保存快照不完整或格式不受支持，无法单独重新生成。请在当前调研中重新生成全部架构图。"
    if not isinstance(snapshot, dict):
        raise ValueError(error)
    kind = snapshot.get("kind")
    if not isinstance(kind, str) or kind not in SUPPORTED_DIAGRAM_KINDS or kind != diagram_type:
        raise ValueError(error)
    if not all(isinstance(snapshot.get(key), str) for key in ("title", "basis")):
        raise ValueError(error)
    nodes, edges, notes = snapshot.get("nodes"), snapshot.get("edges"), snapshot.get("notes", [])
    if not isinstance(nodes, list) or not nodes or not isinstance(edges, list):
        raise ValueError(error)
    if not isinstance(notes, list) or not all(isinstance(note, str) for note in notes):
        raise ValueError(error)
    graph = Graph(kind=kind, title=snapshot["title"], basis=snapshot["basis"], notes=list(notes))
    details = snapshot.get("details", {})
    if not isinstance(details, dict):
        raise ValueError(error)
    if kind == "source_flow":
        from app.architecture.source_snapshot import validate_source_details
        if not validate_source_details(details):
            raise ValueError(error)
    graph.details = deepcopy(details)
    for item in nodes:
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) for key in ("id", "label", "path", "kind")):
            raise ValueError(error)
        if not item["id"] or type(item.get("file_count", 0)) is not int or not isinstance(item.get("entrypoint", False), bool):
            raise ValueError(error)
        methods = item.get("methods", [])
        if not isinstance(methods, list) or not all(isinstance(method, str) for method in methods):
            raise ValueError(error)
        description = item.get("description", "")
        if not isinstance(description, str):
            raise ValueError(error)
        node = GraphNode(**{key: item[key] for key in ("id", "label", "path", "kind")},
                         file_count=item.get("file_count", 0), entrypoint=item.get("entrypoint", False),
                         description=description)
        if "methods" in item:
            node.__dict__["methods"] = list(methods)
        graph.nodes.append(node)
    ids = {node.id for node in graph.nodes}
    for item in edges:
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) for key in ("source", "target")):
            raise ValueError(error)
        if item["source"] not in ids or item["target"] not in ids:
            raise ValueError(error)
        if not isinstance(item.get("label", ""), str) or type(item.get("weight", 0)) is not int:
            raise ValueError(error)
        graph.edges.append(GraphEdge(source=item["source"], target=item["target"],
                                     label=item.get("label", ""), weight=item.get("weight", 0)))
    return graph


def list_diagrams(session: Session, project: Project, run_id: str | None = None) -> list[ArchitectureDiagram]:
    rows = list(
        session.scalars(
            select(ArchitectureDiagram)
            .where(ArchitectureDiagram.project_id == project.id)
            .order_by(ArchitectureDiagram.created_at.desc(), ArchitectureDiagram.id.desc())
        ).all()
    )
    if run_id is not None:
        rows = [row for row in rows if row.stats_json.get("run_id") == run_id]
    elif rows:
        latest_run_id = rows[0].stats_json.get("run_id")
        rows = [row for row in rows if row.stats_json.get("run_id") == latest_run_id]
    return sorted(rows, key=lambda row: DIAGRAM_ORDER.get(row.diagram_type, 99))


def generate_architecture(session: Session, project: Project, run_id: str | None = None) -> list[ArchitectureDiagram]:
    """从已采集地图和只读源码文本生成图；不执行输入代码、不调用 LLM。"""

    maps = scoped_collection_rows(session, CodebaseMap, project.id, run_id)
    codebase_map = maps[-1] if maps else None
    if codebase_map is None:
        raise ValueError("还没有代码库地图，请先在「输入源」页采集本地目录或 GitHub 仓库。")

    payload = codebase_map_payload(codebase_map)
    root = resolve_source_root(session, project, source_id=codebase_map.source_id)

    graphs = [build_module_map(payload)]
    source_flow = build_source_flow(root, payload)
    if source_flow is not None:
        graphs.insert(0, source_flow)
    dependency = build_dependency_flow(root, payload)
    if dependency is not None:
        dependency.notes.append("如果图为空，说明扫描预算内没有发现跨模块 import。")

    # UML 图集：组件图 / 类图 / 时序图，都用确定性数据生成，缺数据就跳过而不是硬凑。
    # 组件图取代了早期的 dependency_flow 流程图，避免同一份依赖关系画两遍。
    component = build_component_diagram(dependency)
    if component is not None:
        graphs.append(component)
    class_diagram = build_class_diagram(root, payload)
    if class_diagram is not None:
        graphs.append(class_diagram)
    sequence = build_sequence_diagram(payload, dependency)
    if sequence is not None:
        graphs.append(sequence)

    graphs.append(build_data_flow(payload, dependency))

    previous_rows = session.scalars(select(ArchitectureDiagram).where(ArchitectureDiagram.project_id == project.id)).all()
    for previous in previous_rows:
        if previous.stats_json.get("run_id") == run_id:
            session.delete(previous)
    rows: list[ArchitectureDiagram] = []
    for graph in graphs:
        row = ArchitectureDiagram(
            project_id=project.id,
            diagram_type=graph.kind,
            title=graph.title,
            basis=graph.basis,
            mermaid_source=render_mermaid(graph),
            graph_json=graph.to_dict(),
            stats_json={
                "run_id": run_id,
                "nodes": len(graph.nodes),
                "edges": len(graph.edges),
                "root_label": payload.get("root_label"),
                "scanned_root": str(root) if root is not None else None,
            },
        )
        session.add(row)
        rows.append(row)
    session.flush()
    return sorted(rows, key=lambda row: DIAGRAM_ORDER.get(row.diagram_type, 99))
