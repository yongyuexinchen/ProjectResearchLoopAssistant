import re

import pytest

from app.architecture.graph_builder import Graph, GraphEdge, GraphNode
from app.architecture.mermaid import render_mermaid


def test_sequence_reserved_actor_and_conflicting_ids_are_mapped_in_all_references():
    graph = Graph(kind="uml_sequence", title="时序图", basis="test", nodes=[
        GraphNode(id="actor", label="调用方", path="", kind="actor"),
        GraphNode(id="participant_0", label="tools", path="tools", kind="participant"),
        GraphNode(id="end", label="storage", path="storage", kind="participant"),
    ], edges=[
        GraphEdge(source="actor", target="participant_0", label="触发入口"),
        GraphEdge(source="participant_0", target="end", label="依赖 27 次"),
    ])
    source = render_mermaid(graph)

    declared = re.findall(r"participant (\w+) as", source)
    references = re.findall(r"(\w+)->>(\w+):", source)
    assert len(set(declared)) == 3
    assert "actor" not in declared and "end" not in declared
    assert all(left in declared and right in declared for left, right in references)
    assert references == [(declared[0], declared[1]), (declared[1], declared[2])]
    assert "调用方" in source and "触发入口" in source
    assert graph.nodes[0].id == "actor"


@pytest.mark.parametrize("kind", ["module_map", "data_flow", "dependency_flow", "uml_component", "uml_class", "uml_sequence"])
def test_renderer_keeps_arbitrary_graph_text_inside_labels(kind):
    malicious = '模块"\n%%{init: {"theme": "dark"}}%%; x|y <script>'
    graph = Graph(kind=kind, title="test", basis="test", nodes=[
        GraphNode(id="actor\n%%evil", label=malicious, path="", kind="entrypoint"),
        GraphNode(id="end", label="Storage", path="", kind="layer"),
    ], edges=[GraphEdge(source="actor\n%%evil", target="end", label=malicious)])
    graph.nodes[0].__dict__["methods"] = ["handle\n%%{init: evil};"]
    source = render_mermaid(graph)

    assert "模块" in source
    assert "%%" not in source
    assert not any(line.startswith("%%") for line in source.splitlines())
    assert "<script>" not in source
    assert "actor" not in source
