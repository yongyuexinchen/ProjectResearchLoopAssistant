from app.reports.renderer import render_report_markdown
from app.research.profiles import get_research_profile, list_research_profiles

README = (
    "# Demo Console\n\n"
    "Demo Console 是一个用于整理工程调研结论的工作台。\n\n"
    "## 背景\n\n"
    "原来的调研结论散落在多个文档里，难以复核，因此需要把证据和报告放在同一条流程里。\n\n"
    "## 主要功能\n\n"
    "- 采集代码与文档\n"
    "- 生成带证据引用的报告\n\n"
    "## 快速开始\n\n"
    "```bash\npip install demo\npython app.py\n```\n"
)


def build_inventory():
    return {
        "snapshots": [
            {"id": "s1", "source_type": "local_directory", "status": "collected", "title": "demo", "content_excerpt": README[:200]}
        ],
        "codebase_maps": [
            {
                "id": "m1",
                "root_label": "demo",
                "readme_excerpt": README,
                "tech_stack_json": ["python", "fastapi"],
                "dependency_files_json": ["pyproject.toml"],
                "config_files_json": ["docker-compose.yml"],
                "test_files_json": ["tests/test_api.py"],
                "entrypoint_files_json": ["app.py"],
                "file_tree_json": [
                    {"path": "app.py", "kind": "file"},
                    {"path": "api/routes.py", "kind": "file"},
                    {"path": "services/report.py", "kind": "file"},
                    {"path": "tests/test_api.py", "kind": "file"},
                ],
                "metadata_json": {"manifests": [{"path": "pyproject.toml", "dependencies": ["fastapi"]}]},
            }
        ],
        "source_bundles": [],
    }


def build_package(profile_key: str):
    profile = get_research_profile(profile_key)
    return {
        "research_profile": profile.key,
        "profile_summary": {
            "key": profile.key,
            "label": profile.label,
            "description": profile.description,
            "audience": profile.audience,
            "core_question": profile.core_question,
            "checklist": list(profile.checklist),
            "report_sections": list(profile.report_sections),
            "section_plan": [
                {"heading": section.heading, "question": section.question}
                for section in profile.section_plan
            ],
            "required_evidence_types": list(profile.required_evidence_types),
            "deliverable": profile.deliverable,
        },
        "project": {
            "id": "project-1",
            "name": "Demo Console",
            "topic": "理解 Demo Console",
            "analysis_goal": "确认项目定位和下一步工作",
            "research_profile": profile.key,
        },
        "turns": [],
        "evidence_items": [
            {
                "id": "ev-1",
                "title": "代码库地图：demo",
                "summary": "识别到 FastAPI 与 Python。",
                "evidence_type": "codebase_map",
                "reference": "demo",
                "confidence": 90,
            }
        ],
        "findings": [
            {
                "title": "项目定位：整理工程调研结论的工作台",
                "summary": "README 提供了明确定位。",
                "category": "project_positioning",
                "impact_level": "medium",
                "confidence": 85,
                "evidence_refs_json": ["ev-1"],
            }
        ],
        "risks": [],
        "questions": [],
        "recommendations": [
            {
                "summary": "先验证一次最小流程。",
                "rationale": "报告定位清晰。",
                "confidence": 80,
                "next_steps_json": ["跑一次启动"],
            }
        ],
        "quality_scores": [],
    }


def verifier_result():
    return {
        "passed": True,
        "risk_level": "low",
        "summary": "报告已通过确定性校验。",
        "checks": [],
        "blocking_reasons": [],
        "warning_reasons": [],
        "llm_assisted": {"status": "skipped"},
    }


def test_all_profiles_share_project_brief_but_use_different_report_structures():
    headings_by_profile = {}
    markdown_by_profile = {}
    for profile in list_research_profiles():
        markdown = render_report_markdown(
            build_package(profile.key)["project"],
            build_package(profile.key),
            build_inventory(),
            verifier_result(),
        )
        markdown_by_profile[profile.key] = markdown
        assert "## 项目速览" in markdown
        assert "项目定位：Demo Console 是一个用于整理工程调研结论的工作台。" in markdown
        assert "背景与目标：原来的调研结论散落在多个文档里" in markdown
        assert "主要能力：" in markdown and "采集代码与文档" in markdown
        headings_by_profile[profile.key] = tuple(
            line[3:] for line in markdown.splitlines() if line.startswith("## ")
        )

    assert len(set(headings_by_profile.values())) == 5
    assert "模块边界" in headings_by_profile["architecture_understanding"]
    assert "二开可行性" in headings_by_profile["extension_evaluation"]
    assert "课程章节建议" in headings_by_profile["teaching_breakdown"]
    assert "验收结论" in headings_by_profile["delivery_acceptance"]
    assert "工程接手指南" in headings_by_profile["quick_onboarding"]
    assert "工程接手指南" not in headings_by_profile["teaching_breakdown"]
    assert "## 模块边界" not in markdown_by_profile["quick_onboarding"]


def test_teaching_profile_builds_chapters_from_modules_and_dedupes_walkthrough():
    package = build_package("teaching_breakdown")
    markdown = render_report_markdown(package["project"], package, build_inventory(), verifier_result())

    assert "第 3 章 · 模块 `api`" in markdown
    assert "第 4 章 · 模块 `services`" in markdown
    assert "`app.py` — 入口" in markdown
    assert markdown.count("第 1 步：`app.py`") == 1


def test_quick_profile_has_time_boxed_route_and_next_steps():
    package = build_package("quick_onboarding")
    markdown = render_report_markdown(package["project"], package, build_inventory(), verifier_result())

    assert "30 分钟阅读路线" in markdown
    assert "0–5 分钟 · 建立定位" in markdown
    assert "25–30 分钟 · 做一次验证" in markdown
    assert "## 上手前必须确认的事项" in markdown


def test_readme_headings_do_not_leak_into_report_outline():
    package = build_package("architecture_understanding")
    markdown = render_report_markdown(package["project"], package, build_inventory(), verifier_result())

    assert "\n## 背景" not in markdown
    assert "\n## 主要功能" not in markdown
    assert "\n## 快速开始" not in markdown
    assert "## 项目速览" in markdown


def test_delivery_profile_uses_static_checklist_not_runtime_claims():
    package = build_package("delivery_acceptance")
    markdown = render_report_markdown(package["project"], package, build_inventory(), verifier_result())

    assert "[x] README/项目说明：已具备" in markdown
    assert "静态扫描不会执行构建或启动命令" in markdown
    assert "通过（静态核对）" in markdown
