from app.architecture.graph_builder import build_module_map
from app.architecture.mermaid import render_mermaid


def test_flat_repository_shows_root_file_count_and_entrypoint():
    graph = build_module_map({
        "root_label": "flat-repo",
        "file_tree": [{"path": name, "kind": "file"}
                      for name in ("README.md", "app.py", "services.py", "pyproject.toml")],
        "entrypoint_files": ["app.py"],
    })

    root = next((node for node in graph.nodes if node.kind == "root"), None)
    assert root is not None
    assert root.file_count == 4
    assert "flat-repo" in root.label
    entrypoint = next(node for node in graph.nodes if node.path == "app.py")
    assert any(edge.source == root.id and edge.target == entrypoint.id for edge in graph.edges)
    assert len(render_mermaid(graph).splitlines()) > 1


def test_repository_without_visible_files_still_renders_its_known_root():
    graph = build_module_map({"root_label": "empty-repo", "file_tree": []})

    assert len(graph.nodes) == 1
    assert graph.nodes[0].kind == "root"
    assert graph.nodes[0].file_count == 0
    assert graph.edges == []
    assert "empty-repo" in render_mermaid(graph)
