from app.reports.project_brief import build_project_brief


def project(**overrides):
    base = {
        "name": "Demo",
        "topic": "理解 Demo 项目",
        "analysis_goal": "判断是否适合二开",
    }
    base.update(overrides)
    return base


def test_project_brief_extracts_positioning_motivation_features_and_runbook():
    readme = (
        "# Demo\n\n"
        "Demo 是一个用于验证调研流程的示例项目。\n\n"
        "## 背景\n\n"
        "旧方案需要人工串行整理资料，容易遗漏证据；因此需要把流程自动化。\n\n"
        "## 主要功能\n\n"
        "- 自动采集代码与文档\n"
        "- 生成带证据引用的报告\n\n"
        "## 快速开始\n\n"
        "```bash\npip install demo\npython app.py\n```\n"
    )
    inventory = {
        "snapshots": [{"id": "s1", "source_type": "local_directory", "title": "demo", "content_excerpt": readme[:200]}],
        "codebase_maps": [
            {
                "id": "m1",
                "root_label": "demo",
                "readme_excerpt": readme,
                "tech_stack_json": ["python", "fastapi"],
                "dependency_files_json": ["pyproject.toml"],
                "config_files_json": ["docker-compose.yml"],
                "test_files_json": ["tests/test_app.py"],
                "entrypoint_files_json": ["app.py"],
                "file_tree_json": [{"path": "app.py", "kind": "file"}],
                "metadata_json": {},
            }
        ],
    }

    brief = build_project_brief(project(), inventory)

    assert brief.positioning is not None
    assert "Demo 是一个用于验证" in brief.positioning.text
    assert brief.positioning.basis == "资料原文"
    assert brief.problems and "旧方案" in brief.problems[0].text
    assert [feature.text for feature in brief.features] == ["自动采集代码与文档", "生成带证据引用的报告"]
    assert any("pip install demo" in step for step in brief.runbook)
    assert any("python app.py" in step for step in brief.runbook)
    assert any("fastapi" in item for item in brief.tech_stack)
    assert not any("缺少 README" in gap for gap in brief.gaps)


def test_project_brief_falls_back_to_manifest_description_without_readme():
    inventory = {
        "snapshots": [
            {
                "id": "s1",
                "source_type": "local_file",
                "title": "notes.md",
                "content_excerpt": "# Notes\n\n这里没有项目简介。",
            }
        ],
        "codebase_maps": [
            {
                "id": "m1",
                "root_label": "repo",
                "readme_excerpt": None,
                "tech_stack_json": ["typescript"],
                "dependency_files_json": ["package.json"],
                "config_files_json": [],
                "test_files_json": [],
                "entrypoint_files_json": ["src/index.ts"],
                "file_tree_json": [{"path": "src/index.ts", "kind": "file"}],
                "metadata_json": {
                    "manifests": [
                        {
                            "path": "package.json",
                            "name": "demo-web",
                            "description": "A web console for research workflows.",
                            "keywords": ["research", "console"],
                            "dependencies": ["next", "react"],
                        }
                    ]
                },
            }
        ],
    }

    brief = build_project_brief(project(), inventory)

    assert brief.positioning is not None
    assert brief.positioning.text == "A web console for research workflows."
    assert "package.json" in brief.positioning.source
    assert any("缺少 README" in gap for gap in brief.gaps)
    assert any("为什么做" in gap for gap in brief.gaps)
    assert any("nextjs" in item for item in brief.tech_stack)


def test_project_brief_marks_text_only_input_as_gap():
    inventory = {
        "snapshots": [
            {
                "id": "s1",
                "source_type": "web_url",
                "title": "产品介绍",
                "content_excerpt": "这是一个帮助团队整理调研结论的知识库产品。",
            }
        ],
        "codebase_maps": [],
    }

    brief = build_project_brief(project(topic="调研一个知识库产品"), inventory)

    assert brief.positioning is not None
    assert "知识库" in brief.positioning.text
    assert any("只有文本资料" in gap for gap in brief.gaps)
