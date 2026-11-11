from __future__ import annotations

import re

from app.architecture.graph_builder import Graph

ENTRY_CLASS = "entry"
LAYER_CLASS = "layer"

CLASS_DIAGRAM_KINDS = {"uml_component", "uml_class"}


def render_mermaid(graph: Graph) -> str:
    """按图类型选择 Mermaid 语法：结构图用 flowchart，UML 图用 classDiagram / sequenceDiagram。"""

    if graph.kind in CLASS_DIAGRAM_KINDS:
        return _render_class_diagram(graph)
    if graph.kind == "uml_sequence":
        return _render_sequence_diagram(graph)
    return _render_flowchart(graph)


def _render_flowchart(graph: Graph) -> str:
    ids = _node_ids(graph)
    lines: list[str] = ["flowchart TD" if graph.kind == "module_map" else "flowchart LR"]
    for node in graph.nodes:
        label = _escape_label(node.label, max_length=480 if graph.kind == "source_flow" else 120)
        if node.kind == "root":
            lines.append(f'    {ids[node.id]}(["{label}"])')
        elif node.kind == "entrypoint":
            lines.append(f'    {ids[node.id]}[/"{label}"/]')
        elif node.kind == "layer":
            lines.append(f'    {ids[node.id]}[["{label}"]]')
        else:
            lines.append(f'    {ids[node.id]}["{label}"]')

    for edge in graph.edges:
        if edge.label:
            lines.append(f'    {ids[edge.source]} -->|"{_escape_label(edge.label)}"| {ids[edge.target]}')
        else:
            lines.append(f"    {ids[edge.source]} --> {ids[edge.target]}")

    entry_ids = [ids[node.id] for node in graph.nodes if node.kind == "entrypoint"]
    layer_ids = [ids[node.id] for node in graph.nodes if node.kind == "layer"]
    if entry_ids or layer_ids:
        lines.append(f"    classDef {ENTRY_CLASS} fill:#1f6feb,stroke:#58a6ff,color:#ffffff;")
        lines.append(f"    classDef {LAYER_CLASS} fill:#173a2b,stroke:#3fb950,color:#c9d1d9;")
    if entry_ids:
        lines.append(f"    class {','.join(entry_ids)} {ENTRY_CLASS};")
    if layer_ids:
        lines.append(f"    class {','.join(layer_ids)} {LAYER_CLASS};")
    return "\n".join(lines)


def _render_class_diagram(graph: Graph) -> str:
    ids = _node_ids(graph)
    lines: list[str] = ["classDiagram"]
    # 组件图加 «component» 构件标注；类图就是普通类，不加标注。
    stereotype = "component" if graph.kind == "uml_component" else None

    for node in graph.nodes:
        node_id = ids[node.id]
        lines.append(f'    class {node_id}["{_escape_label(node.label)}"]')
        if stereotype:
            lines.append(f"    <<{stereotype}>> {node_id}")
        for name in node.__dict__.get("methods") or []:
            # Method names come from source code, so never interpolate grammar characters.
            method = re.sub(r"[^\w$]", "_", str(name))[:80]
            lines.append(f"    {node_id} : +{method}()")
    for edge in graph.edges:
        if edge.label == "extends":
            lines.append(f"    {ids[edge.source]} <|-- {ids[edge.target]}")
        elif edge.label:
            lines.append(f"    {ids[edge.source]} ..> {ids[edge.target]} : {_escape_label(edge.label)}")
        else:
            lines.append(f"    {ids[edge.source]} ..> {ids[edge.target]}")
    return "\n".join(lines)


def _render_sequence_diagram(graph: Graph) -> str:
    ids = _node_ids(graph)
    lines: list[str] = ["sequenceDiagram", "    autonumber"]
    for node in graph.nodes:
        label = _escape_label(node.label).replace("<br/>", " ")
        lines.append(f"    participant {ids[node.id]} as {label}")
    for edge in graph.edges:
        lines.append(f"    {ids[edge.source]}->>{ids[edge.target]}: {_escape_label(edge.label) or '调用'}")
    return "\n".join(lines)


def _node_ids(graph: Graph) -> dict[str, str]:
    """Keep snapshot IDs out of Mermaid's grammar, including reserved words like actor/end."""

    ids: dict[str, str] = {}
    for node in graph.nodes:
        if node.id not in ids:
            ids[node.id] = f"node_{len(ids)}"
    return ids


def _escape_label(value: str, *, max_length: int = 120) -> str:
    """Encode grammar/HTML characters; only renderer-owned line breaks remain markup."""

    cleaned = str(value).replace("\\", "/")[:max_length]
    parts = re.split(r"<br\s*/?>|\r\n?|\n", cleaned, flags=re.IGNORECASE)
    reserved = set('#&"<>%|{};[]`')
    return "<br/>".join(
        "".join(f"#{ord(char)};" if char in reserved else " " if ord(char) < 32 else char for char in part)
        for part in parts
    )
