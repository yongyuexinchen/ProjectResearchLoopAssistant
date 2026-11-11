import json

from app.reports.llm_generator import merge_llm_report_markdown, validate_llm_report_sections
from app.services.reports import build_llm_report_messages

from tests.test_llm_report_generator import create_reportable_project, session_scope


def test_validator_coerces_single_section_payload_into_report_shape():
    result = validate_llm_report_sections(
        {"heading": "模块边界", "body": "模型直接返回了单个 section。", "evidence_refs": ["evidence-1"]},
        allowed_evidence_refs={"evidence-1"},
    )

    assert result.accepted is True
    assert result.normalized["executive_summary"] == "模型直接返回了单个 section。"
    assert result.normalized["sections"][0]["heading"] == "模块边界"


def test_merge_inserts_matching_section_before_next_heading():
    base = (
        "# Demo 项目调研报告\n\n"
        "## 项目速览\n\n- 定位：示例项目\n\n"
        "## 执行摘要\n\n- 校验结论：通过\n\n"
        "## 模块边界\n\n- 已有确定性正文\n\n"
        "## 证据索引\n\n- evidence-1\n"
    )
    normalized = {
        "executive_summary": "模型认为项目适合先做 POC。",
        "sections": [
            {
                "heading": "模块边界",
                "body": "入口与业务模块分离，建议先验证入口到服务层的调用。",
                "evidence_refs": ["evidence-1"],
            }
        ],
    }

    merged = merge_llm_report_markdown(base, normalized, planned_headings=["项目速览", "模块边界", "证据索引"])

    assert "## 智能报告增强" not in merged
    assert "### 模型补充解读" in merged
    assert merged.index("入口与业务模块分离") < merged.index("## 证据索引")
    assert "模型认为项目适合先做 POC。" in merged
    assert "已有确定性正文" in merged


def test_merge_keeps_unmatched_sections_in_enhancement_block():
    base = "# Demo\n\n## 项目速览\n\n- 定位\n\n## 证据索引\n\n- evidence-1\n"
    normalized = {
        "executive_summary": "结论",
        "sections": [
            {"heading": "额外洞察", "body": "这段无法归类。", "evidence_refs": ["evidence-1"]}
        ],
    }

    merged = merge_llm_report_markdown(base, normalized, planned_headings=["项目速览"])

    assert "## 智能报告增强" in merged
    assert "### 额外洞察" in merged
    assert "这段无法归类。" in merged


def test_llm_report_prompt_carries_profile_plan_and_project_brief():
    with session_scope() as session:
        project, run, _ = create_reportable_project(session)
        project.research_profile = "teaching_breakdown"
        from app.services.reports import build_analysis_package, build_inventory

        package = build_analysis_package(session, run)
        inventory = build_inventory(session, project)
        messages = build_llm_report_messages(
            project,
            package,
            inventory,
            [str(evidence.id) for evidence in package["evidence_items"]],
        )

    payload = json.loads(messages[1]["content"])
    context = payload["context"]

    assert context["research_profile"]["key"] == "teaching_breakdown"
    assert context["research_profile"]["report_plan"]
    assert context["research_profile"]["core_question"]
    assert context["project"]["topic"] == "Evidence-bounded reports"
    assert "report_plan" in context["research_profile"]
    assert context["project_brief"]["positioning"] is not None
