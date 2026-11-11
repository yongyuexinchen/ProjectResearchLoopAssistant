from pathlib import Path

from app.reports.project_brief import build_project_brief, top_level_modules
from app.tools.code_scan_tools import infer_entrypoints, scan_codebase


def test_scan_detects_nextjs_entrypoints_and_skips_generated_files(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"next":"16.0.0","react":"19.0.0"},"scripts":{"dev":"next dev","start":"next start"}}',
        encoding="utf-8",
    )
    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "src" / "app" / "layout.tsx").write_text("export default function Layout() {}", encoding="utf-8")
    (tmp_path / "src" / "app" / "page.tsx").write_text("export default function Page() {}", encoding="utf-8")
    (tmp_path / "src" / "app" / "api" / "aircraft").mkdir(parents=True)
    (tmp_path / "src" / "app" / "api" / "aircraft" / "route.ts").write_text("export const GET = () => {}", encoding="utf-8")
    (tmp_path / "src" / "middleware.test.ts").write_text("test('x', () => {})", encoding="utf-8")
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "logo.png").write_bytes(b"png")
    (tmp_path / "engine" / "__pycache__").mkdir(parents=True)
    (tmp_path / "engine" / "__pycache__" / "runner.cpython-314.pyc").write_bytes(b"pyc")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide", encoding="utf-8")

    result = scan_codebase(tmp_path, max_file_bytes=1_000_000, excerpt_chars=4_000)

    assert "src/app/layout.tsx" in result["entrypoint_files"]
    assert "src/app/page.tsx" in result["entrypoint_files"]
    paths = {item["path"] for item in result["file_tree"]}
    assert "engine/__pycache__/runner.cpython-314.pyc" not in paths
    modules = top_level_modules(result["file_tree"], code_only=True)
    assert [name for name, _ in modules] == ["src"]
    assert "public" not in [name for name, _ in modules]
    assert "docs" not in [name for name, _ in modules]


def test_infer_entrypoints_works_for_historical_file_tree():
    paths = {
        "src/app/layout.tsx",
        "src/app/page.tsx",
        "src/app/api/aircraft/route.ts",
        "public/logo.png",
    }

    entrypoints = infer_entrypoints(paths, ["nextjs", "react"])

    assert entrypoints[:2] == ["src/app/layout.tsx", "src/app/page.tsx"]


def test_readme_capability_table_becomes_readable_features_and_evidence_notes():
    readme = (
        "# OSIRIS\n\n"
        "OSIRIS is a production-grade OSINT platform. A real-time global intelligence dashboard aggregates live feeds.\n\n"
        "## Key Capabilities\n\n"
        "| Domain | Data Points | Sources |\n"
        "| --- | --- | --- |\n"
        "| Aviation | Commercial, Private, Military | OpenSky Network |\n"
        "| CCTV | 17,000+ Cameras | TfL, WSDOT |\n"
    )
    inventory = {
        "snapshots": [
            {
                "id": "s1",
                "source_type": "github_repo",
                "title": "osiris",
                "content_excerpt": readme[:300],
            }
        ],
        "codebase_maps": [
            {
                "id": "m1",
                "root_label": "osiris",
                "readme_excerpt": readme,
                "tech_stack_json": ["nextjs", "react"],
                "dependency_files_json": ["package.json"],
                "config_files_json": ["next.config.ts"],
                "test_files_json": ["src/middleware.test.ts"],
                "entrypoint_files_json": [],
                "file_tree_json": [
                    {"path": "README.md", "kind": "file"},
                    {"path": "package.json", "kind": "file"},
                    {"path": "src/app/layout.tsx", "kind": "file"},
                    {"path": "src/app/page.tsx", "kind": "file"},
                    {"path": "src/app/api/aircraft/route.ts", "kind": "file"},
                    {"path": "src/middleware.test.ts", "kind": "file"},
                    {"path": "public/logo.png", "kind": "file"},
                ],
                "metadata_json": {},
            }
        ],
    }

    brief = build_project_brief({"name": "OSIRIS", "topic": "教学拆解"}, inventory)

    feature_text = "\n".join(feature.text for feature in brief.features)
    assert "Aviation — Data Points：Commercial, Private, Military；Sources：OpenSky Network" in feature_text
    assert "CCTV — Data Points：17,000+ Cameras；Sources：TfL, WSDOT" in feature_text
    assert "|" not in feature_text
    assert brief.problems == []
    assert any("README.md「Key Capabilities」表格" in note for note in brief.evidence_notes)
    assert brief.evidence_notes[0].startswith("README.md 首段")
