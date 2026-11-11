import pytest

from app.architecture.graph_builder import build_dependency_flow
from app.architecture.uml import build_class_diagram


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_class_diagram_reads_python_with_or_without_utf8_bom(tmp_path, encoding):
    (tmp_path / "service.py").write_text(
        "class Service:\n    def handle(self):\n        return 'ok'\n", encoding=encoding,
    )
    graph = build_class_diagram(tmp_path, {"file_tree": [{"path": "service.py", "kind": "file"}]})

    assert graph is not None
    service = next(node for node in graph.nodes if node.label == "Service")
    assert service.path == "service.py"
    assert service.__dict__["methods"] == ["handle"]


def test_malformed_python_is_still_skipped_without_aborting_class_scan(tmp_path):
    (tmp_path / "broken.py").write_text("class Broken(\n", encoding="utf-8-sig")

    graph = build_class_diagram(tmp_path, {"file_tree": [{"path": "broken.py", "kind": "file"}]})

    assert graph is None


def test_import_scan_preserves_python_first_line_import_after_utf8_bom(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "storage").mkdir()
    (tmp_path / "src" / "service.py").write_text("from storage.models import Item\n", encoding="utf-8-sig")
    (tmp_path / "storage" / "models.py").write_text("class Item:\n    pass\n", encoding="utf-8")
    graph = build_dependency_flow(tmp_path, {"file_tree": [
        {"path": "src/service.py", "kind": "file"},
        {"path": "storage/models.py", "kind": "file"},
    ]})

    assert graph is not None
    paths = {node.id: node.path for node in graph.nodes}
    assert any(paths[edge.source] == "src" and paths[edge.target] == "storage" for edge in graph.edges)
