from app.engine.analyzer import analyze_context
from app.engine.profile_analysis import build_profile_artifacts, readme_excerpt
from app.reports.project_brief import ProjectBrief
from app.research.profiles import get_research_profile


def build_context(profile_key: str):
    profile = get_research_profile(profile_key)
    return {
        "project": {
            "id": "project-1",
            "name": "Demo",
            "topic": "理解 Demo",
            "analysis_goal": "给出结论",
            "research_profile": profile.key,
        },
        "research_profile": {
            "key": profile.key,
            "label": profile.label,
            "checklist": list(profile.checklist),
            "verifier_checks": list(profile.verifier_checks),
        },
        "snapshots": [
            {
                "id": "s1",
                "source_id": "source-1",
                "source_type": "local_directory",
                "status": "collected",
                "title": "demo",
                "content_excerpt": "# Demo\n\nDemo 是一个用于整理调研结论的工具。",
                "metadata": {},
                "skipped_items": [],
            }
        ],
        "codebase_maps": [
            {
                "id": "m1",
                "source_id": "source-1",
                "root_label": "demo",
                "tech_stack": ["python", "fastapi"],
                "dependency_files": ["pyproject.toml"],
                "config_files": ["docker-compose.yml"],
                "test_files": ["tests/test_api.py"],
                "entrypoint_files": ["app.py"],
                "readme_excerpt": "# Demo\n\nDemo 是一个用于整理调研结论的工具。",
                "file_tree": [
                    {"path": "app.py", "kind": "file"},
                    {"path": "api/routes.py", "kind": "file"},
                    {"path": "services/report.py", "kind": "file"},
                    {"path": "tests/test_api.py", "kind": "file"},
                ],
                "skipped_items": [],
                "metadata": {},
            }
        ],
        "source_bundles": [],
        "review_feedback": [],
    }


def titles(result, key):
    return [item["title"] for item in result[key]]


def test_profile_specific_analysis_adds_different_findings_and_risks():
    quick = analyze_context(build_context("quick_onboarding"))
    architecture = analyze_context(build_context("architecture_understanding"))
    extension = analyze_context(build_context("extension_evaluation"))
    teaching = analyze_context(build_context("teaching_breakdown"))
    delivery = analyze_context(build_context("delivery_acceptance"))

    assert "接手入口已定位" in titles(quick, "findings")
    assert "模块边界线索" in titles(architecture, "findings")
    assert "主流程未经过运行时验证" in titles(architecture, "risks")
    assert "候选改造面" in titles(extension, "findings")
    assert "已有测试保护线索" in titles(extension, "findings")
    assert "教学主线已形成" in titles(teaching, "findings")
    assert "练习与验证素材已具备" in titles(teaching, "findings")
    assert "交付完整性快照" in titles(delivery, "findings")
    assert titles(quick, "findings") != titles(architecture, "findings")
    assert titles(architecture, "risks") != titles(extension, "risks")

    # 所有新增发现和风险都必须带证据引用。
    for result in (quick, architecture, extension, teaching, delivery):
        for item in [*result["findings"], *result["risks"]]:
            assert item["evidence_refs"], item["title"]
            assert all(ref.startswith("evidence:") for ref in item["evidence_refs"])


def test_extension_profile_escalates_risk_when_tests_are_missing():
    context = build_context("extension_evaluation")
    context["codebase_maps"][0]["test_files"] = []

    result = analyze_context(context)

    risk_titles = titles(result, "risks")
    assert "缺少测试保护，二开回归成本高" in risk_titles
    assert any(risk["severity"] == "high" for risk in result["risks"] if risk["title"] == "缺少测试保护，二开回归成本高")


def test_generic_recommendation_carries_profile_deliverable():
    result = analyze_context(build_context("delivery_acceptance"))
    generic = result["recommendations"][-1]

    assert generic["metadata"]["research_profile"] == "delivery_acceptance"
    assert generic["summary"] == "按交付验收清单完成人工复核"
    assert generic["metadata"]["profile_checklist"]
    assert generic["metadata"]["profile_section_plan"]


def test_readme_excerpt_preserves_missing_and_blank_semantics():
    assert readme_excerpt([{"readme_excerpt": None}, {"readme_excerpt": ""}, {"readme_excerpt": "  "}]) == []
    assert readme_excerpt([{"readme_excerpt": "# Real README"}]) == ["# Real README"]


def test_aggregate_profile_finding_references_all_codebase_maps():
    inventory = {
        "snapshots": [],
        "codebase_maps": [
            {"file_tree": [{"path": "src/a.py", "kind": "file"}], "entrypoint_files": []},
            {"file_tree": [{"path": "lib/b.js", "kind": "file"}], "entrypoint_files": []},
        ],
    }
    result = build_profile_artifacts(
        profile_key="architecture_understanding",
        project={"name": "multi"},
        brief=ProjectBrief(modules=[("a", 1), ("b", 1)]),
        inventory=inventory,
        refs={"codebase": ["e1", "e2"], "readme": []},
        existing_risk_titles=set(),
    )

    finding = next(item for item in result["findings"] if item["title"] == "模块边界线索")
    assert finding["evidence_refs"] == ["e1", "e2"]
