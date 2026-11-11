from pathlib import Path
from app.tools.code_scan_tools import scan_codebase


def test_custom_next_build_and_task_workspaces_do_not_consume_source_inventory(tmp_path: Path):
    (tmp_path / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    for directory in (".next-build-check", ".next-source-preview", ".tmp", ".worktrees", ".superpowers"):
        target = tmp_path / directory / "generated.js"
        target.parent.mkdir(parents=True)
        target.write_text("function generated() { return 1; }", encoding="utf-8")
    result = scan_codebase(tmp_path, max_file_bytes=10000, excerpt_chars=1000)
    assert [entry["path"] for entry in result["file_tree"] if entry["kind"] == "file"] == ["main.py"]
    assert len(result["skipped_items"]) == 5


def test_collection_excludes_its_own_nested_runtime_workspace_without_excluding_input_root(tmp_path):
    from app.core.config import Settings
    from app.db.models import Project, Source
    from app.services.collection import collect_one_source

    workspace = tmp_path / "workspace" / "projects"
    workspace.mkdir(parents=True)
    (tmp_path / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    (workspace / "cloned.py").write_text("def from_other_repository(): pass\n", encoding="utf-8")
    settings = Settings(workspace_root=workspace)
    source = Source(source_type="local_directory", uri=str(tmp_path), normalized_uri=str(tmp_path))
    _, codebase = collect_one_source(source, Project(name="self"), settings)
    assert "workspace/projects/cloned.py" not in [entry["path"] for entry in codebase["file_tree"]]
    assert any(item["reason"] == "runtime_workspace" for item in codebase["skipped_items"])

    source.normalized_uri = str(workspace)
    _, codebase = collect_one_source(source, Project(name="explicit input"), settings)
    assert "cloned.py" in [entry["path"] for entry in codebase["file_tree"]]
