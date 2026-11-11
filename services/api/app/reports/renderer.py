import re
from typing import Any

from app.reports.project_brief import (
    ProjectBrief,
    build_project_brief,
    codebase_tech_stack,
    extract_readme_runbook,
    first_text,
    module_role,
    plain_text_excerpt,
    resolve_tech_stack,
    top_level_modules,
)
from app.research.profiles import ResearchProfile, get_research_profile
from app.tools.code_scan_tools import (
    infer_entrypoints,
    is_core_code_path,
    is_test_file,
    is_valid_entrypoint_path,
)
from app.verifiers.package import as_list, value_of

DEFAULT_LIST_LIMIT = 6

TECH_STACK_LABELS = {
    "python": "Python 语言",
    "typescript": "TypeScript 前端类型语言",
    "javascript": "JavaScript 脚本语言",
    "go": "Go 语言",
    "java": "Java 语言",
    "fastapi": "FastAPI 后端框架",
    "flask": "Flask 后端框架",
    "django": "Django Web 框架",
    "starlette": "Starlette ASGI 框架",
    "nextjs": "Next.js 前端框架",
    "next": "Next.js 前端框架",
    "react": "React 前端库",
    "vue": "Vue 前端框架",
    "express": "Express 服务框架",
    "langgraph": "LangGraph 工作流框架",
    "langchain": "LangChain LLM 框架",
    "sqlalchemy": "SQLAlchemy ORM",
    "pydantic": "Pydantic 数据模型",
    "pytest": "pytest 测试框架",
    "mysql": "MySQL 数据库",
    "redis": "Redis 缓存",
    "celery": "Celery 异步任务",
    "mermaid": "Mermaid 图表",
    "docker": "Docker 容器化",
}

PROJECT_RESEARCH_SECTION_HEADINGS = [
    "工程接手指南",
    "启动与运行线索",
    "架构地图",
    "证据索引",
    "后续阅读路径",
]

PROFILE_AWARE_SECTION_HEADINGS = [
    "调研 Profile",
    "资料包摘要",
]

MISSING_ITEM_LABELS = {
    "readme": "README/项目说明",
    "entrypoint": "入口文件",
    "dependency": "依赖清单",
    "config": "运行配置",
    "test": "测试",
}


def render_report_markdown(
    project: Any,
    package: dict[str, Any],
    inventory: dict[str, Any],
    verifier_result: dict[str, Any],
) -> str:
    """按调研方式把 Analysis Package 渲染成中文 Markdown 报告。

    报告不重新推理、不调用模型，只组织已经落库的事实与校验结果。
    不同调研方式使用不同的章节计划；每个档位都先给「项目速览」，
    再进入该档位真正关心的章节。
    """

    profile = resolve_profile(package, verifier_result)
    brief = build_project_brief(project, inventory)
    project_name = text(value_of(project, "name", "项目"))

    lines: list[str] = [
        f"# {project_name} 项目调研报告",
        "",
        f"> 调研方式：{profile.label} ｜ 面向：{profile.audience}",
        "",
    ]

    lines.extend(render_research_task(project, profile))
    lines.extend(render_profile_summary(package, verifier_result))
    lines.extend(render_source_bundle_summary(inventory))
    lines.extend(render_project_brief(project, package, brief, profile))
    lines.extend(render_verification_summary(verifier_result))
    lines.extend(render_executive_summary(project, package, verifier_result))
    lines.extend(render_profile_report_sections(project, package, inventory, profile, brief))
    lines.extend(render_conclusion(project, package, inventory, brief, profile, verifier_result))
    lines.extend(render_evidence_chain(package))
    lines.extend(render_llm_assisted_verifier(verifier_result))
    lines.extend(["## 证据与校验", ""])
    lines.extend(render_checks(verifier_result))
    lines.extend(render_evidence_index(package))
    lines.extend(render_source_inventory(inventory))
    lines.extend(render_findings(package))
    lines.extend(render_risks(package))
    lines.extend(render_questions(package))
    lines.extend(render_recommendations(package))
    lines.extend(render_timeline(package))
    return "\n".join(lines).strip() + "\n"


def resolve_profile(package: dict[str, Any], verifier_result: dict[str, Any] | None = None) -> ResearchProfile:
    summary = package.get("profile_summary")
    if isinstance(summary, dict) and text(summary.get("key")):
        return get_research_profile(text(summary.get("key")))
    project = package.get("project")
    project_profile = text(value_of(project, "research_profile", ""))
    if project_profile:
        return get_research_profile(project_profile)
    if isinstance(verifier_result, dict):
        verifier_profile = verifier_result.get("research_profile")
        if isinstance(verifier_profile, dict) and text(verifier_profile.get("key")):
            return get_research_profile(text(verifier_profile.get("key")))
    return get_research_profile(text(package.get("research_profile")) or None)


def render_research_task(project: Any, profile: ResearchProfile) -> list[str]:
    goal = text(value_of(project, "analysis_goal", "")) or profile.description
    structure = " → ".join(f"{index}. {heading}" for index, heading in enumerate(profile.report_sections, start=1))
    return [
        "## 调研任务",
        "",
        f"- 调研方式：{profile.label} (`{profile.key}`)",
        f"- 核心问题：{profile.core_question}",
        f"- 你的补充目标：{goal}",
        f"- 本次交付：{profile.deliverable}",
        f"- 报告结构：{structure}",
        "",
    ]


def render_profile_summary(package: dict[str, Any], verifier_result: dict[str, Any]) -> list[str]:
    profile = profile_info(package, verifier_result)
    lines = ["## 调研 Profile", ""]
    if not profile:
        lines.append("- 当前报告未声明调研档位，按默认快速接手档位处理。")
        lines.append("")
        return lines

    lines.append(f"- 档位：{text(value_of(profile, 'label', '未命名'))} (`{text(value_of(profile, 'key', 'unknown'))}`)")
    description = text(value_of(profile, "description", ""))
    if description:
        lines.append(f"- 说明：{description}")
    audience = text(value_of(profile, "audience", ""))
    if audience:
        lines.append(f"- 面向：{audience}")
    core_question = text(value_of(profile, "core_question", ""))
    if core_question:
        lines.append(f"- 核心问题：{core_question}")
    deliverable = text(value_of(profile, "deliverable", ""))
    if deliverable:
        lines.append(f"- 交付物：{deliverable}")
    checklist = as_list(value_of(profile, "checklist", []))
    if checklist:
        lines.append(f"- 核心检查：{join_values(checklist)}")
    required_evidence = as_list(value_of(profile, "required_evidence_types", []))
    if required_evidence:
        lines.append(f"- 需要证据类型：{join_values(required_evidence)}")
    lines.append("")
    return lines


def render_source_bundle_summary(inventory: dict[str, Any]) -> list[str]:
    lines = ["## 资料包摘要", ""]
    bundles = as_list(inventory.get("source_bundles"))
    if not bundles:
        lines.append("- 暂未登记资料包，报告基于已采集输入源生成。")
        lines.append("")
        return lines

    for bundle in bundles:
        lines.append(
            f"- {text(value_of(bundle, 'name', '未命名资料包'))} "
            f"(`{status_label(text(value_of(bundle, 'status', 'unknown')))}`)"
        )
        lines.append(
            f"  - 条目：`{text(value_of(bundle, 'item_count', 0))}`；"
            f"已采集：`{text(value_of(bundle, 'collected_count', 0))}`；"
            f"失败：`{text(value_of(bundle, 'failed_count', 0))}`；"
            f"待处理：`{text(value_of(bundle, 'pending_count', 0))}`"
        )
    lines.append("")
    return lines


def render_project_brief(
    project: Any,
    package: dict[str, Any],
    brief: ProjectBrief,
    profile: ResearchProfile,
) -> list[str]:
    lines = [
        "## 项目速览",
        "",
        "> 以下内容是报告直接从采集资料中提取的项目事实；本节末尾列出可核对的依据。",
        "",
    ]

    if brief.positioning:
        lines.append(f"- 项目定位：{brief.positioning.text}")
    else:
        lines.append("- 项目定位：资料中没有可直接引用的项目简介，见下方资料缺口。")

    if brief.problems:
        lines.append(f"- 背景与目标：{brief.problems[0].text}")
        for extra in brief.problems[1:3]:
            lines.append(f"  - 补充：{extra.text}")

    if brief.features:
        lines.append("- 主要能力：")
        for feature in brief.features[:15]:
            lines.append(f"  - {feature.text}")
    else:
        lines.append("- 主要能力：资料没有给出功能清单，无法确认产品功能（见资料缺口）。")

    if brief.tech_stack or brief.traits:
        lines.append("- 工程特点：")
        if brief.tech_stack:
            lines.append(f"  - 技术栈：{join_values(brief.tech_stack)}")
        for trait in brief.traits[:6]:
            lines.append(f"  - {trait.text}")

    if brief.shapes:
        shapes = "；".join(
            f"{shape.text}{'（推断）' if shape.basis == '推断' else ''}"
            for shape in unique_brief_items(brief.shapes)
        )
        lines.append(f"- 技术形态：{shapes}")

    if brief.readme_title:
        lines.append(f"- README 标题：{brief.readme_title}")

    if brief.gaps:
        lines.append("- 资料缺口：")
        for gap in brief.gaps:
            lines.append(f"  - {gap}")
    else:
        lines.append("- 资料缺口：暂未发现明显缺口；运行时行为和真实业务规则仍需人工确认。")

    if brief.evidence_notes:
        lines.append("- 依据：")
        for note in brief.evidence_notes:
            lines.append(f"  - {note}")

    lines.append("")
    return lines


def render_verification_summary(verifier_result: dict[str, Any]) -> list[str]:
    return [
        "## 校验摘要",
        "",
        f"- 是否通过：`{bool_label(bool(verifier_result.get('passed', False)))}`",
        f"- 风险等级：`{risk_label(text(verifier_result.get('risk_level', 'unknown')))}`",
        f"- 摘要：{text(verifier_result.get('summary', ''))}",
        "",
    ]


def render_executive_summary(project: Any, package: dict[str, Any], verifier_result: dict[str, Any]) -> list[str]:
    findings_count = len(as_list(package.get("findings")))
    risks_count = len(as_list(package.get("risks")))
    passed = bool(verifier_result.get("passed", False))
    risk_level = text(verifier_result.get("risk_level", "unknown"))
    summary = text(verifier_result.get("summary", ""))
    conclusion = f"{bool_label(passed)}，风险等级：{risk_label(risk_level)}"
    if summary:
        conclusion = f"{conclusion}；{summary}"

    return [
        "## 执行摘要",
        "",
        f"- 项目：{text(value_of(project, 'name', '项目'))}",
        f"- 发现数量：`{findings_count}`",
        f"- 风险数量：`{risks_count}`",
        f"- 校验结论：{conclusion}",
        "",
    ]


def render_profile_report_sections(
    project: Any,
    package: dict[str, Any],
    inventory: dict[str, Any],
    profile: ResearchProfile,
    brief: ProjectBrief,
) -> list[str]:
    lines: list[str] = []
    for section in profile.section_plan:
        lines.extend([f"## {section.heading}", "", f"> 本节回答：{section.question}", ""])
        body = profile_section_body(
            section.heading,
            package,
            inventory,
            project=project,
            brief=brief,
        )
        lines.extend(body)
        lines.append("")
    return lines


def profile_section_body(
    heading: str,
    package: dict[str, Any],
    inventory: dict[str, Any],
    *,
    project: Any = None,
    brief: ProjectBrief | None = None,
) -> list[str]:
    project = project if project is not None else package.get("project")
    brief = brief if brief is not None else build_project_brief(project, inventory)

    if heading == "工程接手指南":
        return render_onboarding_guide(project, package, inventory, brief)
    if heading == "启动与运行线索":
        return render_runbook_clues(inventory)
    if heading == "架构地图":
        return render_architecture_map(inventory, package)
    if heading in {"新人接手路径"}:
        return render_profile_reading_items(inventory)
    if heading == "30 分钟阅读路线":
        return render_thirty_minute_route(inventory, brief)
    if heading == "后续阅读路径":
        return render_reading_path(package, inventory)
    if heading == "上手前必须确认的事项":
        return render_onboarding_confirmations(package, inventory, brief)
    if heading == "系统定位与边界":
        return render_system_positioning(project, brief, inventory)
    if heading == "模块边界":
        return render_module_boundary_items(package, inventory)
    if heading == "主流程与数据流":
        return render_main_flow_items(package, inventory)
    if heading == "外部依赖与集成":
        return render_external_dependency_items(inventory)
    if heading == "扩展点":
        return render_extension_point_items(package, inventory)
    if heading == "架构风险与验证缺口":
        return render_architecture_verification_gaps(package, inventory)
    if heading == "二开范围与改造面":
        return render_extension_surface(package, inventory)
    if heading == "二开可行性":
        return render_extension_feasibility(package, inventory)
    if heading == "改造风险":
        return render_extension_risks(package, inventory)
    if heading == "测试与配置复杂度":
        return render_test_config_complexity(package, inventory)
    if heading == "分阶段落地建议":
        return render_phased_extension_plan(package, inventory)
    if heading == "二开前必须补齐的证据":
        return render_extension_evidence_gaps(package, inventory)
    if heading == "教学目标与受众":
        return render_teaching_goals(brief, inventory)
    if heading == "课程章节建议":
        return render_course_chapter_suggestions(package, inventory)
    if heading == "关键代码讲解顺序":
        return render_code_walkthrough_order(inventory)
    if heading == "学习难点与前置知识":
        return render_learning_difficulties(package, inventory, brief)
    if heading == "练习任务":
        return render_practice_tasks(package, inventory)
    if heading == "教学材料缺口":
        return render_teaching_material_gaps(package, inventory, brief)
    if heading == "交付范围":
        return render_delivery_scope(inventory)
    if heading == "交付完整性":
        return render_profile_delivery_items(package, inventory)
    if heading == "可启动性":
        return render_startability(inventory)
    if heading == "文档与运维缺口":
        return render_docs_operations_gaps(package, inventory, brief)
    if heading == "验收问题清单":
        return render_acceptance_questions(package, inventory, brief)
    if heading == "验收结论":
        return render_acceptance_verdict(package, inventory, brief)
    return ["- 当前调研包暂未生成该档位的专属结构化内容。"]


# ---------------------------------------------------------------------------
# 快速接手
# ---------------------------------------------------------------------------


def render_onboarding_guide(
    project: Any,
    package: dict[str, Any],
    inventory: dict[str, Any],
    brief: ProjectBrief,
) -> list[str]:
    maps = as_list(inventory.get("codebase_maps"))
    entrypoints = unique_values(inventory_entrypoints(inventory))
    dependencies = unique_values(collect_codebase_values(inventory, "dependency_files_json"))
    configs = unique_values(inventory_configs(inventory))
    tests = unique_values(collect_codebase_values(inventory, "test_files_json"))
    goal = text(value_of(project, "analysis_goal", "")) or "完成第一次接手"
    steps = [
        f"第 1 步 · 建立项目定位：读 README 的简介与动机；当前资料定位为“{brief.positioning.text if brief.positioning else '未提供'}”。",
        f"第 2 步 · 准备运行环境：依赖清单 {join_values(dependencies) if dependencies else '未识别'}；运行配置 {join_values(configs) if configs else '未识别'}。",
        f"第 3 步 · 找到启动入口：{join_values(entrypoints) if entrypoints else '未识别入口文件，需要向项目方确认启动命令'}。",
        f"第 4 步 · 阅读主流程：从入口出发，按“接口 → 业务服务 → 数据/外部依赖”的顺序看一个完整请求。",
        f"第 5 步 · 做一次最小验证：{f'尝试运行 {join_values(tests[:3])} 中的测试' if tests else '当前未发现测试，先用一次实际启动或手工请求验证'}。",
    ]
    lines = [
        f"- 接手目标：{goal}",
        f"- 调研方式：快速接手（先跑通，再读主流程，不展开全部实现细节）",
        *[f"- {step}" for step in steps],
    ]
    if not maps:
        lines.append("- 注意：本次只有文本资料，没有代码库扫描结果，步骤 3-5 只能作为待确认项。")
    lines.append(f"- 接手判断：{quick_readiness(inventory)}。")
    for risk in as_list(package.get("risks"))[:3]:
        lines.append(f"- 接手风险：{text(value_of(risk, 'title', '未命名风险'))}（{text(value_of(risk, 'mitigation', '未提供缓解建议'))}）")
    return lines


def render_runbook_clues(inventory: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    codebase_maps = as_list(inventory.get("codebase_maps"))
    if not codebase_maps:
        lines.append("- 当前调研包暂未形成代码库地图，无法提取依赖与入口线索。")
    for codebase_map in codebase_maps:
        root_label = text(value_of(codebase_map, "root_label", "codebase"))
        lines.append(f"- `{root_label}`")
        lines.append(f"  - 依赖文件：{join_values(value_of(codebase_map, 'dependency_files_json', []))}")
        lines.append(f"  - 配置文件：{join_values(codebase_configs(codebase_map))}")
        lines.append(f"  - 入口文件：{join_values(codebase_entrypoints(codebase_map))}")
        readme_excerpt = text(value_of(codebase_map, "readme_excerpt", ""))
        if readme_excerpt:
            lines.append(f"  - README 线索：{truncate(' '.join(readme_excerpt.split()), 160)}")
    runbook = extract_readme_runbook(first_readme(inventory))
    if runbook:
        lines.append("- 资料中可核对的启动/安装线索：")
        for step in runbook[:6]:
            lines.append(f"  - `{step}`")
    else:
        lines.append("- 资料中没有可直接引用的启动命令；启动步骤需要人工确认。")
    return lines or ["- 暂未形成启动与运行线索。"]


def render_architecture_map(inventory: dict[str, Any], package: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    codebase_maps = as_list(inventory.get("codebase_maps"))
    findings = as_list(package.get("findings"))
    if not codebase_maps and not findings:
        lines.append("- 当前调研包暂未形成足够证据描述架构地图。")
    for codebase_map in codebase_maps:
        lines.append(f"- `{text(value_of(codebase_map, 'root_label', 'codebase'))}`")
        lines.append(f"  - 技术栈：{join_values(codebase_tech_stack(codebase_map))}")
        lines.append(f"  - 入口线索：{join_values(codebase_entrypoints(codebase_map))}")
        lines.append(f"  - 测试线索：{join_values(value_of(codebase_map, 'test_files_json', []))}")
        modules = top_level_modules(value_of(codebase_map, "file_tree_json", []), code_only=True)
        if modules:
            lines.append(f"  - 顶层模块：{join_values([f'{name}({count})' for name, count in modules[:8]])}")
    if findings:
        lines.append("- 关键结构发现：")
        for finding in findings[:5]:
            if is_empty_finding(finding):
                continue
            lines.append(f"  - {display_title(value_of(finding, 'title', '未命名发现'), '未命名发现')}")
    return lines or ["- 暂未形成架构地图线索。"]


def render_profile_reading_items(inventory: dict[str, Any]) -> list[str]:
    items: list[tuple[str, str]] = []
    if first_readme(inventory):
        items.append(("README", "先确认项目用途、动机和启动前提"))
    for path in unique_values(inventory_entrypoints(inventory)):
        items.append((path, "从入口看启动参数、路由注册和主流程调用"))
    for path in unique_values(inventory_configs(inventory))[:3]:
        items.append((path, "确认运行配置、环境变量和默认值"))
    for path in unique_values(collect_codebase_values(inventory, "test_files_json"))[:3]:
        items.append((path, "用测试反推预期行为和边界"))
    if not items:
        return ["- 暂未识别明确阅读路径，请先补充代码目录或 README 输入源。"]
    seen: set[str] = set()
    lines = []
    for path, reason in items:
        if path in seen:
            continue
        seen.add(path)
        lines.append(f"- `{path}` — {reason}")
    return lines[:8]


def render_thirty_minute_route(inventory: dict[str, Any], brief: ProjectBrief) -> list[str]:
    entrypoints = unique_values(inventory_entrypoints(inventory))
    modules = collect_modules(inventory)
    tests = unique_values(collect_codebase_values(inventory, "test_files_json"))
    configs = unique_values(inventory_configs(inventory))
    module_names = "、".join(f"`{name}`" for name, _, _ in modules[:3]) or "核心目录"
    lines = [
        f"- 0–5 分钟 · 建立定位：读 README 首段和「项目速览」，能回答“它是什么、为什么做”即可；当前定位：{brief.positioning.text if brief.positioning else '待补充'}",
        f"- 5–10 分钟 · 找到入口：打开 {join_values(entrypoints) if entrypoints else '项目根目录'}，只看启动方式和主流程入口，不展开实现。",
        f"- 10–20 分钟 · 看主流程：按 {module_names} 各打开一个代表文件，记录输入、输出和依赖，不追求读懂每一行。",
        f"- 20–25 分钟 · 核对运行前提：查看 {join_values(configs) if configs else '依赖与配置说明'}，确认需要哪些环境变量和外部服务。",
        f"- 25–30 分钟 · 做一次验证：{f'运行 {join_values(tests[:3])} 中的测试' if tests else '执行一次最小启动或手工请求'}，记录成功/失败点。",
        "- 完成标准：能说清项目用途、画出入口到模块的路径、完成一次最小验证；做不到的项写入「上手前必须确认的事项」。",
    ]
    return lines


def render_reading_path(package: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    reading_items: list[str] = []
    for codebase_map in as_list(inventory.get("codebase_maps")):
        reading_items.extend(codebase_entrypoints(codebase_map))
        reading_items.extend(codebase_configs(codebase_map))
        reading_items.extend(as_list(value_of(codebase_map, "test_files_json", []))[:3])
    if reading_items:
        lines.append("- 第一轮之后建议深入：")
        for item in unique_values(reading_items)[:8]:
            lines.append(f"  - `{text(item)}`")
    else:
        lines.append("- 当前调研包暂未识别明确阅读路径，请先补充代码目录或 README 输入源。")

    modules = collect_modules(inventory)
    if modules:
        lines.append("- 按模块继续读：")
        for name, count, sample in modules[:6]:
            role = module_role(name)
            lines.append(f"  - `{name}`（{role or '未分类'}，约 {count} 个条目）{f'，可从 `{sample}` 开始' if sample else ''}")

    open_questions = open_question_items(package)
    if open_questions:
        lines.append("- 阅读前建议先确认的开放问题：")
        for question in open_questions[:3]:
            lines.append(f"  - {text(value_of(question, 'prompt', '未命名问题'))}")
    return lines


def render_onboarding_confirmations(
    package: dict[str, Any],
    inventory: dict[str, Any],
    brief: ProjectBrief,
) -> list[str]:
    lines: list[str] = []
    if brief.gaps:
        for gap in brief.gaps:
            lines.append(f"- 资料缺口：{gap}")
    questions = [
        "项目方能否提供一份可执行的启动命令或部署说明？",
        "README 中的启动步骤是否与当前代码版本一致？",
        "是否有需要在本地准备的外部服务（数据库、缓存、第三方账号）？",
        "接手后的第一个真实任务是修 Bug、加功能，还是只做维护？",
    ]
    if not unique_values(collect_codebase_values(inventory, "test_files_json")):
        questions.insert(0, "是否有未纳入仓库的自动化测试或验收脚本？")
    lines.append("- 建议向项目方确认：")
    for question in questions[:6]:
        lines.append(f"  - {question}")
    for risk in as_list(package.get("risks"))[:3]:
        lines.append(f"- 已登记风险：{text(value_of(risk, 'title', '未命名风险'))}（{text(value_of(risk, 'mitigation', '未提供缓解建议'))}）")
    return lines


def quick_readiness(inventory: dict[str, Any]) -> str:
    state = codebase_presence(inventory)
    if not state["codebase"]:
        return "暂不具备接手条件：只有文本资料，无法验证代码和启动方式"
    missing = [label for key, label in MISSING_ITEM_LABELS.items() if not state[key]]
    if not missing:
        return "具备接手条件：依赖、入口和测试线索齐全，但仍需实际跑一次启动"
    return "有条件接手：缺少" + "、".join(missing)


# ---------------------------------------------------------------------------
# 架构理解
# ---------------------------------------------------------------------------


def render_system_positioning(project: Any, brief: ProjectBrief, inventory: dict[str, Any]) -> list[str]:
    lines = []
    if brief.positioning:
        lines.append(f"- 系统定位：{brief.positioning.text}")
    else:
        lines.append("- 系统定位：资料中没有可直接引用的项目简介。")
    if brief.shapes:
        lines.append(f"- 技术形态：{'；'.join(shape.text for shape in brief.shapes)}")
    roots = unique_values(text(value_of(item, "root_label", "")) for item in as_list(inventory.get("codebase_maps")))
    if roots:
        lines.append(f"- 本次扫描边界：{join_values(roots)}（只包含已采集目录，不包含未提供的服务和部署环境）")
    deps = unique_values(collect_codebase_values(inventory, "dependency_files_json"))
    configs = unique_values(inventory_configs(inventory))
    lines.append(f"- 内部实现锚点：入口 {join_values(inventory_entrypoints(inventory))}")
    lines.append(f"- 外部边界锚点：依赖 {join_values(deps)}；配置 {join_values(configs)}")
    lines.append("- 明确不在本次证据内：运行时拓扑、线上部署结构、真实调用量、未提交代码。")
    return lines


def render_profile_architecture_items(package: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    """兼容旧接口：用紧凑条目概括代码库结构，不展开完整文件树。"""

    lines = []
    for codebase_map in as_list(inventory.get("codebase_maps")):
        root_label = text(value_of(codebase_map, "root_label", "codebase"))
        entrypoints = codebase_entrypoints(codebase_map)
        dependencies = value_of(codebase_map, "dependency_files_json", [])
        configs = codebase_configs(codebase_map)
        tests = value_of(codebase_map, "test_files_json", [])
        file_tree = as_list(value_of(codebase_map, "file_tree_json", []))
        file_count = sum(1 for item in file_tree if value_of(item, "kind") == "file")
        directory_count = sum(1 for item in file_tree if value_of(item, "kind") == "directory")

        lines.append(f"- `{root_label}`")
        lines.append(f"  - 技术栈和特性：{join_values(codebase_tech_stack(codebase_map))}")
        lines.append(f"  - 模块入口：{join_values(entrypoints)}")
        lines.append(f"  - 依赖与外部边界：{join_values(dependencies)}")
        lines.append(f"  - 配置边界：{join_values(configs)}")
        lines.append(f"  - 测试验证线索：{join_values(tests)}")
        lines.append(f"  - 目录规模：约 `{file_count}` 个文件、`{directory_count}` 个目录；完整文件清单保留在代码库地图页，不在报告正文展开。")
    for finding in as_list(package.get("findings"))[:3]:
        lines.append(f"- 结构发现：{text(value_of(finding, 'title', '未命名发现'))}")
    return lines or ["- 暂未形成结构化架构线索。"]


def render_module_boundary_items(package: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for codebase_map in as_list(inventory.get("codebase_maps")):
        root_label = text(value_of(codebase_map, "root_label", "codebase"))
        modules = top_level_modules(value_of(codebase_map, "file_tree_json", []), code_only=True)
        samples = module_samples(value_of(codebase_map, "file_tree_json", []))
        lines.append(f"- `{root_label}` 的模块边界")
        if modules:
            for module_name, count in modules[:8]:
                role = module_role(module_name)
                sample = samples.get(module_name)
                lines.append(
                    f"  - `{module_name}`（{role or '职责待确认'}）：约 `{count}` 个文件/目录线索"
                    f"{f'，代表文件 `{sample}`' if sample else ''}"
                )
                if count > 300:
                    children = nested_module_breakdown(
                        value_of(codebase_map, "file_tree_json", []),
                        module_name,
                        depth=5 if module_name == "staging" else 3,
                    )
                    if children:
                        lines.append(
                            "    - 下钻："
                            + "、".join(f"`{name}`({child_count})" for name, child_count, _ in children[:5])
                        )
                        lines.append("    - 说明：该模块文件量过大，单层计数不能直接当作一个职责边界。")
        else:
            lines.append("  - 暂未识别出稳定的顶层模块，请结合代码库地图页继续确认。")
        lines.append(f"  - 入口边界：{join_values(codebase_entrypoints(codebase_map))}")
        lines.append(f"  - 配置边界：{join_values(codebase_configs(codebase_map))}")
    if not as_list(inventory.get("codebase_maps")):
        lines.append("- 没有代码库扫描结果，无法判断模块边界。")
    for finding in as_list(package.get("findings"))[:3]:
        if is_empty_finding(finding):
            continue
        lines.append(f"- 架构发现：{display_title(value_of(finding, 'title', '未命名发现'), '未命名发现')}")
    return lines or ["- 暂未形成模块边界线索。"]


def render_main_flow_items(package: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for codebase_map in as_list(inventory.get("codebase_maps")):
        root_label = text(value_of(codebase_map, "root_label", "codebase"))
        entrypoints = codebase_entrypoints(codebase_map)
        configs = codebase_configs(codebase_map)
        dependencies = as_list(value_of(codebase_map, "dependency_files_json", []))
        tests = as_list(value_of(codebase_map, "test_files_json", []))
        modules = top_level_modules(value_of(codebase_map, "file_tree_json", []), code_only=True)
        runtime_modules = [
            (name, count)
            for name, count in modules
            if module_role(name) not in {"文档", "测试"}
        ]
        lines.append(f"- `{root_label}` 主流程（静态推断，未经过运行时验证）")
        lines.append(f"  - 1. 入口：{join_values(entrypoints)} 接收启动参数或请求。")
        lines.append(f"  - 2. 装配：读取 {join_values(configs)} 与 {join_values(dependencies)} 完成配置和依赖初始化。")
        if runtime_modules:
            module_names = "、".join(f"`{name}`" for name, _ in runtime_modules[:5])
            lines.append(f"  - 3. 处理：请求/任务进入 {module_names} 等模块，按目录边界完成业务处理。")
        else:
            lines.append("  - 3. 处理：未识别稳定模块，业务处理路径无法进一步拆分。")
        lines.append("  - 4. 输出：处理结果通过入口返回，或写入数据层/外部服务。")
        lines.append(f"  - 5. 验证出口：{join_values(tests) if tests else '未发现测试，无法从自动化测试确认流程'}。")
        lines.append("  - 说明：以上步骤由目录、入口和依赖关系推断，不代表真实调用链；需要日志或追踪抽样验证。")
    if not as_list(inventory.get("codebase_maps")):
        lines.append("- 没有代码库扫描结果，无法推断主流程。")
    return lines or ["- 暂未形成主流程线索。"]


def render_external_dependency_items(inventory: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    stack = unique_values(inventory_tech_stack(inventory))
    lowered = {item.lower() for item in stack}
    integration = []
    if lowered & {"mysql", "sqlalchemy"}:
        integration.append("数据库/ORM（MySQL/SQLAlchemy）")
    if "redis" in lowered:
        integration.append("缓存（Redis）")
    if lowered & {"langgraph", "langchain"}:
        integration.append("模型/Agent 工作流（LangGraph/LangChain）")
    if lowered & {"fastapi", "flask", "django", "express"}:
        integration.append("HTTP 接口层")
    if lowered & {"nextjs", "react", "vue"}:
        integration.append("前端页面/组件")
    lines.append(f"- 技术栈：{join_values(stack)}")
    lines.append(f"- 依赖清单：{join_values(collect_codebase_values(inventory, 'dependency_files_json'))}")
    lines.append(f"- 配置文件：{join_values(inventory_configs(inventory))}")
    lines.append(f"- 可识别的集成点：{join_values(integration) if integration else '未从依赖名识别出数据库、缓存或外部服务'}")
    lines.append("- 未覆盖：消息队列、第三方 API、云资源等只有在代码或配置中出现时才能确认，本次扫描不做网络探测。")
    return lines


def render_extension_point_items(package: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for codebase_map in as_list(inventory.get("codebase_maps")):
        root_label = text(value_of(codebase_map, "root_label", "codebase"))
        modules = top_level_modules(value_of(codebase_map, "file_tree_json", []), code_only=True)
        lines.append(f"- `{root_label}` 可扩展点")
        lines.append(f"  - 入口扩展：{join_values(codebase_entrypoints(codebase_map))}（新增路由/命令通常从这里接入）")
        if modules:
            module_names = "、".join(f"`{name}`" for name, _ in modules[:5])
            lines.append(f"  - 模块扩展：{module_names}（优先新增模块，避免直接改入口）")
        lines.append(f"  - 配置扩展：{join_values(codebase_configs(codebase_map))}")
        lines.append(f"  - 依赖扩展：{join_values(value_of(codebase_map, 'dependency_files_json', []))}")
        lines.append(f"  - 测试保护：{join_values(value_of(codebase_map, 'test_files_json', [])) if value_of(codebase_map, 'test_files_json', []) else '无测试，扩展前必须先补'}") 
    for recommendation in as_list(package.get("recommendations"))[:3]:
        lines.append(f"- 后续建议：{text(value_of(recommendation, 'summary', '未命名建议'))}")
    for risk in as_list(package.get("risks"))[:3]:
        lines.append(f"- 扩展风险：{text(value_of(risk, 'title', '未命名风险'))}")
    return lines or ["- 暂未形成扩展点线索。"]


def render_architecture_verification_gaps(package: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    lines = []
    risks = as_list(package.get("risks"))
    for risk in risks[:5]:
        lines.append(f"- 风险：{text(value_of(risk, 'title', '未命名风险'))}（{risk_label(text(value_of(risk, 'severity', 'unknown')))}）")
        mitigation = text(value_of(risk, "mitigation", ""))
        if mitigation:
            lines.append(f"  - 缓解：{mitigation}")
    if not risks:
        lines.append("- 当前没有登记架构风险；这不代表没有风险，只代表扫描没有发现可证据化的风险。")
    lines.append("- 验证缺口与建议：")
    lines.append("  - 主流程和数据流是静态推断：用一次真实请求、启动日志或追踪抽样验证。")
    lines.append("  - 模块职责来自目录命名：打开代表文件确认职责，不要只按目录名下结论。")
    if not unique_values(collect_codebase_values(inventory, "test_files_json")):
        lines.append("  - 没有测试文件：架构判断缺少行为回归保护，优先补最小 smoke test。")
    lines.append("  - 外部集成点未做网络探测：检查配置和启动日志确认实际连接。")
    return lines


# ---------------------------------------------------------------------------
# 二开评估
# ---------------------------------------------------------------------------


def render_extension_surface(package: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    modules = collect_modules(inventory)
    lines = [
        f"- 可改造入口：{join_values(inventory_entrypoints(inventory))}",
        f"- 候选模块：{join_values([name for name, _, _ in modules]) if modules else '未识别到稳定模块'}",
        f"- 配置改动面：{join_values(inventory_configs(inventory))}",
        f"- 依赖改动面：{join_values(collect_codebase_values(inventory, 'dependency_files_json'))}",
    ]
    if modules:
        lines.append("- 改动类型判断：")
        lines.append("  - 新增功能：优先在业务模块内新增文件，降低对入口的改动。")
        lines.append("  - 修改核心：入口、配置或共享数据层改动会影响全部模块，需要单独回归。")
    lines.append("- 本次未覆盖：未提交代码、线上部署结构、真实运行数据和业务规则；这些需要在 POC 前补充确认。")
    return lines


def render_extension_feasibility(package: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    state = codebase_presence(inventory)
    lines = ["- 判断维度："]
    lines.append(f"  - 可定位改造点：{'是' if state['entrypoint'] and state['codebase'] else '否'}（入口与模块扫描）")
    lines.append(f"  - 有测试保护：{'是' if state['test'] else '否'}（测试文件扫描）")
    lines.append(f"  - 配置可核对：{'是' if state['config'] else '否'}（配置文件扫描）")
    lines.append(f"  - 依赖可核对：{'是' if state['dependency'] else '否'}（依赖清单扫描）")
    verdict, strength = extension_verdict(inventory)
    lines.append(f"- 结论：{verdict}（可信度：{strength}）")
    lines.append("- 说明：该结论只基于静态扫描，未执行构建、启动或回归测试。")
    return lines


def render_extension_risks(package: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    return render_profile_extension_items(package, inventory)


def render_profile_extension_items(package: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    risks = as_list(package.get("risks"))
    lines = [
        f"- 测试线索：{join_values(collect_codebase_values(inventory, 'test_files_json'))}",
        f"- 配置线索：{join_values(inventory_configs(inventory))}",
    ]
    if not risks:
        lines.append("- 当前没有登记改造风险；建议在开工前补一轮风险评审。")
    for risk in risks[:5]:
        lines.append(f"- 改造风险：{text(value_of(risk, 'title', '未命名风险'))}（{risk_label(text(value_of(risk, 'severity', 'unknown')))}）")
        lines.append(f"  - 缓解：{text(value_of(risk, 'mitigation', '未提供缓解建议'))}")
    for finding in as_list(package.get("findings")):
        if text(value_of(finding, "category", "")) == "extension":
            lines.append(f"- 改造线索：{text(value_of(finding, 'title', '未命名发现'))} — {text(value_of(finding, 'summary', ''))}")
    return lines


def render_test_config_complexity(package: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    tests = unique_values(collect_codebase_values(inventory, "test_files_json"))
    configs = unique_values(inventory_configs(inventory))
    dependencies = unique_values(collect_codebase_values(inventory, "dependency_files_json"))
    stack = unique_values(inventory_tech_stack(inventory))
    lines = [
        f"- 测试文件：{f'发现 {len(tests)} 个：' + join_values(tests) if tests else '未发现测试文件'}",
        f"- 测试框架线索：{'、'.join(name for name in stack if name in {'pytest', 'vitest', 'jest'}) or '未从依赖名识别'}",
        f"- 配置文件：{join_values(configs) if configs else '未发现配置文件'}",
        f"- 依赖清单：{join_values(dependencies) if dependencies else '未发现依赖清单'}",
        f"- 技术栈：{join_values(stack)}",
        "- 复杂度判断：",
        f"  - 回归成本：{'低（有测试基线）' if tests else '高（没有测试基线，任何改动都需要手工回归）'}",
        f"  - 配置成本：{'中（需要同步修改多个配置）' if len(configs) > 3 else '低（配置面较小）'}",
        f"  - 依赖成本：{'中（依赖数量较多，升级需验证兼容性）' if len(stack) > 4 else '低（依赖面较小）'}",
        "- 注意：静态扫描只能看到测试文件数量，无法判断覆盖率和测试质量。",
    ]
    return lines


def render_phased_extension_plan(package: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    modules = collect_modules(inventory)
    module_name = modules[0][0] if modules else "最小业务模块"
    tests = unique_values(collect_codebase_values(inventory, "test_files_json"))
    return [
        f"- 阶段 1 · POC：只改 `{module_name}` 中的一个最小路径，验证接口、配置和依赖能跑通；不碰共享数据层。",
        f"- 阶段 2 · 回归：围绕改动路径补 1-3 个测试用例（现有测试：{join_values(tests) if tests else '无，需要新建'}），确认旧行为不回归。",
        "- 阶段 3 · 放量：补日志/监控和回滚方案，再扩大改动范围；上线前确认配置变更可回滚。",
        "- 每个阶段结束都要有可验证产物：POC 可运行、回归可重复、放量可回滚。",
        "- 以上分期基于静态证据，实际排期需要研发负责人结合团队和业务节奏确认。",
    ]


def render_extension_evidence_gaps(package: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    brief = build_project_brief(package.get("project"), inventory)
    lines = [f"- {gap}" for gap in brief.gaps]
    questions = open_question_items(package)
    for question in questions[:5]:
        lines.append(f"- 待确认：{text(value_of(question, 'prompt', '未命名问题'))}")
    lines.append("- 必须确认二开目标范围：本次要改哪些模块、哪些行为绝对不能变、谁能验收。")
    lines.append("- 必须确认真实启动步骤和外部依赖：POC 需要在可复现环境里跑通。")
    if not unique_values(collect_codebase_values(inventory, "test_files_json")):
        lines.append("- 必须先补：一条可重复运行的 smoke test，否则无法判断改动是否破坏现有行为。")
    else:
        lines.append("- 必须先补：测试覆盖说明；测试文件数量不等于覆盖率，需确认关键路径是否被测到。")
    lines.append("- 必须先补：回滚方案和上线观察指标，放量阶段需要可回滚、可观测。")
    return lines


# ---------------------------------------------------------------------------
# 教学拆解
# ---------------------------------------------------------------------------


def render_teaching_goals(brief: ProjectBrief, inventory: dict[str, Any]) -> list[str]:
    stack = unique_values(inventory_tech_stack(inventory))
    entrypoints = unique_values(inventory_entrypoints(inventory))
    lines = [
        f"- 项目导入：{brief.positioning.text if brief.positioning else '资料未提供项目简介，需要讲师自行补充背景。'}",
        f"- 授课对象：面向该项目的使用者、维护者或二次开发者；默认假设学生具备基础编程能力，具体水平和课程时长需要讲师确认。",
        "- 学完后的可验证目标：",
        "  - 能用自己的话说清项目用途、动机和主要特点。",
        f"  - 能按资料启动项目（当前入口：{join_values(entrypoints) if entrypoints else '未识别'}）。",
        "  - 能画出模块边界并解释一次主流程（静态推断，课堂上需说明验证方式）。",
        "  - 能在一个模块内完成小改动，并运行测试或手工验证。",
        f"- 前置知识：{join_values(stack) if stack else '未识别技术栈，需讲师补充'}；建议先补命令行、Git 和基础测试概念。",
    ]
    return lines


def render_course_chapter_suggestions(package: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    modules = collect_teaching_modules(inventory)
    teaching_modules = [
        module
        for module in modules
        if module_role(module[0]) not in {"文档", "测试", "脚本/工具"}
    ]
    entrypoints = unique_values(inventory_entrypoints(inventory))
    tests = unique_values(collect_codebase_values(inventory, "test_files_json"))
    brief = build_project_brief(package.get("project"), inventory)
    chapters = [
        ("第 1 章 · 项目导入", f"讲清项目用途、动机和特点；素材：项目速览和主要能力表。当前定位：{brief.positioning.text if brief.positioning else '需讲师补充'}"),
        ("第 2 章 · 运行与入口", f"带学生完成一次启动，认识入口和配置；文件：{join_values(entrypoints) if entrypoints else '待确认'}"),
    ]
    for index, (name, count, sample) in enumerate(teaching_modules[:4], start=3):
        role = module_role(name)
        chapters.append(
            (
                f"第 {index} 章 · 模块 `{name}`",
                f"讲解{role or '该模块'}的职责、输入输出和关键实现；文件：{sample or f'`{name}/` 下代表文件'}（约 {count} 个条目）",
            )
        )
    if tests:
        chapters.append((f"第 {len(chapters) + 1} 章 · 测试与改造", f"读测试、改一个小功能并验证；文件：{join_values(tests[:3])}"))
    else:
        chapters.append((f"第 {len(chapters) + 1} 章 · 手工验证", "没有测试文件，改为设计手工验证清单和一次小改动练习。"))

    lines = []
    for title, detail in chapters:
        lines.append(f"- {title}：{detail}")
    lines.append("- 章节顺序说明：先建立项目全貌和可运行认知，再按模块拆解，最后用测试/改造收束，避免一开始陷进实现细节。")
    return lines


def render_code_walkthrough_order(inventory: dict[str, Any]) -> list[str]:
    steps: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(path: str, reason: str) -> None:
        if not path or path in seen:
            return
        seen.add(path)
        steps.append((path, reason))

    for path in unique_values(inventory_entrypoints(inventory))[:3]:
        add(path, "入口：启动参数、路由注册、主流程调用")
    for name, _count, sample in collect_modules(inventory)[:4]:
        if module_role(name) in {"文档", "脚本/工具"}:
            continue
        add(sample, f"模块 `{name}`：职责边界和关键实现")
    for path in representative_code_files(inventory, limit=4):
        add(path, "关键实现：选一个可讲清职责的源码文件")
    for path in unique_values(collect_codebase_values(inventory, "test_files_json"))[:3]:
        add(path, "测试：预期行为和边界条件")
    if not steps:
        return ["- 暂未识别关键代码文件，请先补充代码目录或 README 输入源。"]
    return [f"- 第 {index} 步：`{path}` — {reason}" for index, (path, reason) in enumerate(steps[:10], start=1)]


def render_learning_difficulties(package: dict[str, Any], inventory: dict[str, Any], brief: ProjectBrief) -> list[str]:
    modules = collect_teaching_modules(inventory)
    stack = unique_values(inventory_tech_stack(inventory))
    tests = unique_values(collect_codebase_values(inventory, "test_files_json"))
    lines = []
    if len(modules) >= 4:
        lines.append(f"- 难点 1 · 模块多：有 {len(modules)} 个顶层模块，学生容易迷路；先画边界图再读代码。")
    elif modules:
        lines.append(f"- 难点 1 · 建立整体感：模块较少（{len(modules)} 个），但仍需先讲清入口到模块的路径。")
    else:
        lines.append("- 难点 1 · 缺少模块信息：没有稳定目录结构，需要讲师补充代码地图。")
    if stack:
        lines.append(f"- 难点 2 · 技术栈门槛：需要先掌握 {join_values(stack)} 的基本用法，否则读不懂框架约定。")
    if not tests:
        lines.append("- 难点 3 · 缺少测试反馈：学生改完代码无法自动判断对错，需要准备手工验收清单。")
    else:
        lines.append(f"- 难点 3 · 测试阅读：测试文件 {len(tests)} 个，需先讲测试结构和断言方式。")
    if not brief.positioning or not brief.problems:
        lines.append("- 难点 4 · 背景材料不足：项目动机和业务背景缺失，建议课前补一页项目介绍。")
    lines.append("- 建议前置知识：命令行与 Git、至少一门项目主语言、基础测试概念；框架知识按技术栈补充。")
    return lines


def render_practice_tasks(package: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    modules = collect_teaching_modules(inventory)
    entrypoints = unique_values(inventory_entrypoints(inventory))
    tests = unique_values(collect_codebase_values(inventory, "test_files_json"))
    runbook = extract_readme_runbook(first_readme(inventory))
    launch = (
        "依次执行 " + "、".join(f"`{step}`" for step in runbook[:3])
        if runbook
        else "按资料中的启动说明完成一次启动"
    )
    tasks = [
        f"练习 1 · 复现启动：{launch}，记录每一步命令和失败点（入口：{join_values(entrypoints) if entrypoints else '待确认'}）。",
    ]
    if modules:
        name, _count, sample = modules[0]
        tasks.append(f"练习 2 · 读懂模块：阅读 `{sample or name}`，用自己的话写出 `{name}` 的职责、输入和输出。")
        tasks.append(f"练习 3 · 小改动：在 `{name}` 中增加一个可观察的小改动（日志、字段或返回值），并说明影响范围。")
    else:
        tasks.append("练习 2 · 画结构图：根据目录和入口画出模块关系，并标出不确定的边。")
    if tests:
        tasks.append(f"练习 4 · 测试验证：修改或新增一个测试（参考 {join_values(tests[:2])}），运行并解释失败/通过原因。")
    else:
        tasks.append("练习 4 · 设计验收：为一次小改动写出 3 条手工验收步骤，并说明预期结果。")
    if as_list(package.get("risks")):
        tasks.append("练习 5 · 风险演练：选一条风险，写出一个可执行的缓解或验证动作。")
    return [f"- {task}" for task in tasks]


def render_teaching_material_gaps(package: dict[str, Any], inventory: dict[str, Any], brief: ProjectBrief) -> list[str]:
    lines = [f"- {gap}" for gap in brief.gaps]
    if not unique_values(collect_codebase_values(inventory, "test_files_json")):
        lines.append("- 缺测试材料：需要讲师准备可运行的验收脚本，否则练习无法自动判分。")
    if not unique_values(inventory_configs(inventory)):
        lines.append("- 缺配置材料：需要补充环境变量样例和本地依赖说明。")
    if not first_readme(inventory):
        lines.append("- 缺阅读材料：建议课前补一页项目背景、架构图和术语表。")
    lines.append("- 建议补充课程材料：讲义/PPT、示例数据、常见错误清单和课后作业说明。")
    lines.append("- 建议补一张课堂用的模块图（可参考报告「架构地图」和架构图页面），并标注哪些是扫描事实、哪些是推断。")
    return lines


# ---------------------------------------------------------------------------
# 交付验收
# ---------------------------------------------------------------------------


def render_delivery_scope(inventory: dict[str, Any]) -> list[str]:
    maps = as_list(inventory.get("codebase_maps"))
    snapshots = as_list(inventory.get("snapshots"))
    modules = collect_modules(inventory)
    lines = [
        f"- 交付资料：{len(snapshots)} 个采集快照" if snapshots else "- 交付资料：未记录采集快照",
        f"- 代码根目录：{join_values([text(value_of(item, 'root_label', 'codebase')) for item in maps]) if maps else '未提供代码目录'}",
        f"- 代码规模线索：{len(modules)} 个顶层模块" if modules else "- 代码规模线索：未识别顶层模块",
        f"- 技术栈：{join_values(inventory_tech_stack(inventory))}",
        f"- 交付入口：{join_values(inventory_entrypoints(inventory))}",
    ]
    return lines


def render_profile_delivery_items(package: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    state = codebase_presence(inventory)
    checks = [
        ("README/项目说明", state["readme"], "说明项目用途、启动方式和验收前提"),
        ("入口文件", state["entrypoint"], "证明交付物存在可启动入口"),
        ("依赖清单", state["dependency"], "支持安装和版本核对"),
        ("运行配置", state["config"], "支持环境准备和部署核对"),
        ("测试", state["test"], "支持交接后的回归验证"),
    ]
    lines = ["- 交付完整性核对："]
    for label, present, purpose in checks:
        mark = "已具备" if present else "缺失"
        lines.append(f"  - [{ 'x' if present else ' ' }] {label}：{mark}（{purpose}）")
    missing = [label for label, present, _ in checks if not present]
    lines.append(f"- 缺失项：{'、'.join(missing) if missing else '无'}")
    if "入口文件" in missing:
        lines.append("- 可启动性：暂无法确认，缺少入口文件。")
    elif "依赖清单" in missing:
        lines.append("- 可启动性：有条件确认，缺少依赖清单，安装步骤需要人工补充。")
    else:
        lines.append("- 可启动性：具备静态线索，但仍需按 README 实际启动一次。")
    runbook = extract_readme_runbook(first_readme(inventory))
    if runbook:
        lines.append(f"- 资料中的启动线索：`{runbook[0]}`" + (f" 等 {len(runbook)} 条" if len(runbook) > 1 else ""))
    else:
        lines.append("- 资料中没有可直接执行的启动命令。")
    open_questions = open_question_items(package)
    lines.append(f"- 待确认问题：`{len(open_questions)}` 条（详见「验收问题清单」）。")
    return lines


def render_startability(inventory: dict[str, Any]) -> list[str]:
    state = codebase_presence(inventory)
    runbook = extract_readme_runbook(first_readme(inventory))
    lines = [
        f"- 启动入口：{join_values(inventory_entrypoints(inventory))}",
        f"- 依赖清单：{join_values(collect_codebase_values(inventory, 'dependency_files_json'))}",
        f"- 运行配置：{join_values(inventory_configs(inventory))}",
    ]
    if runbook:
        lines.append("- 资料中的启动步骤（原文摘录）：")
        for step in runbook[:6]:
            lines.append(f"  - `{step}`")
    else:
        lines.append("- 资料中没有可直接执行的启动步骤。")
    if not state["entrypoint"]:
        lines.append("- 可启动性判断：无法确认，缺少入口文件。")
    elif not state["dependency"]:
        lines.append("- 可启动性判断：有条件确认，缺少依赖清单，需要补充安装步骤。")
    else:
        lines.append("- 可启动性判断：静态线索齐全，但仍需按资料实际启动一次并记录结果。")
    lines.append("- 静态扫描不会执行构建或启动命令，因此不能替代真实启动验收。")
    return lines


def render_docs_operations_gaps(package: dict[str, Any], inventory: dict[str, Any], brief: ProjectBrief) -> list[str]:
    state = codebase_presence(inventory)
    lines = []
    if not state["readme"]:
        lines.append("- README 缺失：接手方无法确认用途、启动方式和运行前提。")
    else:
        lines.append("- README 已提供：仍需核对启动步骤是否与当前版本一致。")
    configs = unique_values(inventory_configs(inventory))
    if not any("docker" in path.lower() for path in configs):
        lines.append("- 未发现 Docker/部署配置：部署方式和运行环境需要在验收前补充说明。")
    else:
        lines.append(f"- 部署配置：{join_values([path for path in configs if 'docker' in path.lower()])}（仍需确认镜像来源和环境变量）。")
    env_files = [path for path in all_file_paths(inventory) if ".env" in path.lower()]
    if not env_files:
        lines.append("- 未发现环境变量样例或配置模板：新环境部署时容易缺参数。")
    else:
        lines.append(f"- 环境变量样例：{join_values(env_files[:4])}（仍需确认样例是否覆盖全部必填项）。")
    lines.append("- 未覆盖：日志、监控、告警、备份和回滚方案，本次静态扫描无法判断，需要交付方补充运维说明。")
    for gap in brief.gaps:
        if "README" in gap or "配置" in gap or "测试" in gap:
            lines.append(f"- 资料缺口：{gap}")
    return lines


def render_acceptance_questions(package: dict[str, Any], inventory: dict[str, Any], brief: ProjectBrief) -> list[str]:
    lines = []
    for question in open_question_items(package)[:6]:
        lines.append(f"- {text(value_of(question, 'prompt', '未命名问题'))}（状态：{status_label(text(value_of(question, 'status', 'unknown')))}）")
    if not open_question_items(package):
        lines.append("- 当前分析中没有记录在案的开放问题。")
    if brief.gaps:
        lines.append("- 根据资料缺口补充的验收问题：")
        for gap in brief.gaps:
            lines.append(f"  - {gap} 是否已有书面说明？")
    lines.append("- 建议在验收会上确认：交付范围、启动责任人、依赖环境、测试证据、问题反馈渠道。")
    return lines


def render_acceptance_verdict(package: dict[str, Any], inventory: dict[str, Any], brief: ProjectBrief) -> list[str]:
    verdict, conditions = delivery_verdict(inventory)
    lines = [f"- 验收结论：{verdict}"]
    if conditions:
        lines.append("- 条件 / 缺口：")
        for condition in conditions:
            lines.append(f"  - {condition}")
    else:
        lines.append("- 条件 / 缺口：未发现结构性缺口；仍建议按 README 完成一次实际启动验收。")
    lines.append("- 结论依据：本次只核对了已采集的代码、依赖、配置和文档线索，未执行构建、部署或真实运行。")
    return lines


# ---------------------------------------------------------------------------
# 结论与通用章节
# ---------------------------------------------------------------------------


def render_conclusion(
    project: Any,
    package: dict[str, Any],
    inventory: dict[str, Any],
    brief: ProjectBrief,
    profile: ResearchProfile,
    verifier_result: dict[str, Any],
) -> list[str]:
    verdict, reasons = profile_verdict(profile.key, inventory, brief, verifier_result)
    lines = [
        "## 本次调研结论",
        "",
        f"- 结论：{verdict}",
        f"- 判断依据：{'；'.join(reasons) if reasons else '基于已采集证据和确定性校验。'}",
    ]
    recommendations = as_list(package.get("recommendations"))
    if recommendations:
        lines.append("- 建议先做：")
        for index, recommendation in enumerate(recommendations[:3], start=1):
            lines.append(f"  {index}. {text(value_of(recommendation, 'summary', '未命名建议'))}")
            next_steps = as_list(value_of(recommendation, "next_steps_json", []))
            for step in next_steps[:2]:
                lines.append(f"     - {text(step)}")
    else:
        lines.append("- 建议先做：补齐资料后重新运行调研。")
    lines.append(f"- 本次调研可信度：{confidence_label(verifier_result)}；运行时行为和真实业务规则仍需人工确认。")
    lines.append("")
    return lines


def profile_verdict(
    profile_key: str,
    inventory: dict[str, Any],
    brief: ProjectBrief,
    verifier_result: dict[str, Any],
) -> tuple[str, list[str]]:
    state = codebase_presence(inventory)
    reasons = []
    if state["readme"]:
        reasons.append("已取得 README/说明材料")
    if state["entrypoint"]:
        reasons.append("已识别入口文件")
    if state["test"]:
        reasons.append("已发现测试文件")
    if verifier_result.get("risk_level"):
        reasons.append(f"确定性风险等级为{risk_label(text(verifier_result.get('risk_level')))}")

    if profile_key == "architecture_understanding":
        modules = collect_modules(inventory)
        if not state["codebase"]:
            return "无法形成架构判断：本次没有代码库扫描结果。", reasons
        if modules and state["entrypoint"]:
            return f"可形成初步架构判断：识别到 {len(modules)} 个顶层模块；主流程仍是静态推断，需要运行时验证。", reasons
        if modules:
            return "只能给出目录边界：缺少入口文件，主流程和数据流无法判断。", reasons
        return "暂无法形成架构判断：未识别稳定的模块结构。", reasons

    if profile_key == "extension_evaluation":
        if not state["codebase"]:
            return "无法评估二开：本次没有代码库扫描结果。", reasons
        if state["test"] and state["entrypoint"]:
            return "可进入小范围 POC：已有测试基线；正式改造前仍需补回归用例和回滚方案。", reasons
        return "暂不建议直接二开：缺少测试保护或入口线索，先补 smoke test 或做隔离 POC。", reasons

    if profile_key == "teaching_breakdown":
        modules = collect_teaching_modules(inventory)
        if not state["codebase"]:
            return "无法排课：缺少代码材料。", reasons
        if modules and state["entrypoint"]:
            return f"可作为课程案例：可拆成约 {min(len(modules) + 3, 7)} 章；背景材料需要讲师补充。", reasons
        return "仅可作为单章案例：模块或入口信息不足，难以拆成完整课程。", reasons

    if profile_key == "delivery_acceptance":
        verdict, conditions = delivery_verdict(inventory)
        if conditions:
            reasons = reasons + [f"验收条件：{condition}" for condition in conditions[:4]]
        return verdict, reasons

    if not state["codebase"]:
        return "暂不具备接手条件：只有文本资料，无法验证代码和启动方式。", reasons
    missing = [label for key, label in MISSING_ITEM_LABELS.items() if not state[key]]
    if not missing:
        return "具备接手条件：依赖、入口和测试线索齐全；仍需实际跑一次启动验证。", reasons
    return "有条件接手：缺少" + "、".join(missing) + "，按报告中的阅读路线先补齐关键信息。", reasons


def render_evidence_index(package: dict[str, Any]) -> list[str]:
    lines = ["## 证据索引", ""]
    evidence_items = as_list(package.get("evidence_items"))
    if not evidence_items:
        lines.append("- 当前调研包暂未形成证据索引。")
    for evidence in evidence_items:
        lines.append(
            f"- `{text(value_of(evidence, 'id', 'evidence'))}` "
            f"{plain_text_excerpt(value_of(evidence, 'title', '证据'), 160) or '证据'} "
            f"({text(value_of(evidence, 'evidence_type', 'unknown'))})"
        )
        summary = text(value_of(evidence, "summary", ""))
        if summary:
            lines.append(f"  - {plain_text_excerpt(summary, 240)}")
    lines.append("")
    return lines


def render_evidence_chain(package: dict[str, Any]) -> list[str]:
    lines = ["## 关键证据链", ""]
    evidence_by_id = {
        text(value_of(evidence, "id")): evidence
        for evidence in as_list(package.get("evidence_items"))
        if text(value_of(evidence, "id"))
    }
    has_visible_chain = False

    for finding in as_list(package.get("findings")):
        if is_empty_finding(finding):
            continue
        linked_evidence = []
        for ref in as_list(value_of(finding, "evidence_refs_json", [])):
            ref_id = text(ref)
            evidence = evidence_by_id.get(ref_id)
            if evidence is not None:
                linked_evidence.append((ref_id, evidence))
        if not linked_evidence:
            continue

        has_visible_chain = True
        lines.append(f"- {display_title(value_of(finding, 'title', '未命名发现'), '未命名发现')}")
        for ref_id, evidence in linked_evidence:
            title = text(value_of(evidence, "title", "证据"))
            summary = text(value_of(evidence, "summary", ""))
            lines.append(f"  - `{ref_id}` {title}：{plain_text_excerpt(summary, 180) or '未填写摘要'}")

    if not has_visible_chain:
        lines.append("- 暂无可展示证据链。")
    lines.append("")
    return lines


def render_llm_assisted_verifier(verifier_result: dict[str, Any]) -> list[str]:
    llm_assisted = verifier_result.get("llm_assisted")
    if not isinstance(llm_assisted, dict):
        llm_assisted = {"status": "skipped"}

    status = text(value_of(llm_assisted, "status", "skipped")) or "skipped"
    summary = text(value_of(llm_assisted, "summary", ""))
    issues = []
    for issue in as_list(value_of(llm_assisted, "issues", [])):
        message = text(value_of(issue, "message", ""))
        if not message:
            continue
        severity = text(value_of(issue, "severity", "warning")) or "warning"
        issues.append((severity, message))
    lines = [
        "## 智能复核意见",
        "",
        f"- 状态：`{status}`",
        f"- 摘要：{summary or '未提供。'}",
    ]

    if issues:
        lines.append("- 问题：")
        for severity, message in issues:
            lines.append(f"  - `{severity}` {message}")
    else:
        lines.append("- 问题：暂无。")
    lines.append("")
    return lines


def render_checks(verifier_result: dict[str, Any]) -> list[str]:
    lines = ["### 校验项", ""]
    for check in as_list(verifier_result.get("checks")):
        passed = "通过" if value_of(check, "passed") else "需关注"
        lines.append(
            f"- `{check_name_label(text(value_of(check, 'name', 'check')))}` "
            f"[{passed}/{severity_label(text(value_of(check, 'severity', 'info')))}]"
        )
        for message in as_list(value_of(check, "messages", [])):
            lines.append(f"  - {text(message)}")
    lines.append("")
    return lines


def render_source_inventory(inventory: dict[str, Any]) -> list[str]:
    lines = ["## 输入源与采集", ""]
    snapshots = as_list(inventory.get("snapshots"))
    codebase_maps = as_list(inventory.get("codebase_maps"))
    if not snapshots:
        lines.append("- 暂未采集输入源快照。")
    for snapshot in snapshots:
        lines.append(
            f"- {text(value_of(snapshot, 'title', '未命名输入源'))} "
            f"(`{text(value_of(snapshot, 'source_type', 'unknown'))}`, "
            f"`{status_label(text(value_of(snapshot, 'status', 'unknown')))}`)"
        )
        excerpt = value_of(snapshot, "content_excerpt")
        if excerpt:
            lines.append(f"  - 摘要：{plain_text_excerpt(excerpt, 180)}")
    if codebase_maps:
        lines.append("")
        lines.append("### 代码库地图")
        lines.append("")
    for codebase_map in codebase_maps:
        lines.append(f"- `{text(value_of(codebase_map, 'root_label', 'codebase'))}`")
        lines.append(f"  - 技术栈：{join_values(codebase_tech_stack(codebase_map))}")
        lines.append(f"  - 依赖文件：{join_values(value_of(codebase_map, 'dependency_files_json', []))}")
        lines.append(f"  - 入口线索：{join_values(codebase_entrypoints(codebase_map))}")
        lines.append(f"  - 测试文件：{join_values(value_of(codebase_map, 'test_files_json', []))}")
    lines.append("")
    return lines


def render_findings(package: dict[str, Any]) -> list[str]:
    lines = ["## 发现", ""]
    findings = as_list(package.get("findings"))
    if not findings:
        lines.append("- 暂无发现。")
    for finding in findings:
        if is_empty_finding(finding):
            continue
        lines.append(f"- {display_title(value_of(finding, 'title', '未命名发现'), '未命名发现')}")
        lines.append(f"  - 类别：`{text(value_of(finding, 'category', 'unknown'))}`")
        lines.append(f"  - 影响：`{risk_label(text(value_of(finding, 'impact_level', 'unknown')))}`")
        lines.append(f"  - 摘要：{plain_text_excerpt(value_of(finding, 'summary', ''), 320)}")
        lines.append(f"  - 证据引用：{join_values(value_of(finding, 'evidence_refs_json', []))}")
    lines.append("")
    return lines


def render_risks(package: dict[str, Any]) -> list[str]:
    lines = ["## 风险登记", ""]
    risks = as_list(package.get("risks"))
    if not risks:
        lines.append("- 暂无登记风险。")
    for risk in risks:
        lines.append(f"- {plain_text_excerpt(value_of(risk, 'title', '未命名风险'), 160) or '未命名风险'}")
        lines.append(f"  - 严重程度：`{risk_label(text(value_of(risk, 'severity', 'unknown')))}`")
        lines.append(f"  - 摘要：{plain_text_excerpt(value_of(risk, 'summary', ''), 320)}")
        lines.append(f"  - 缓解建议：{plain_text_excerpt(value_of(risk, 'mitigation', ''), 320)}")
        lines.append(f"  - 证据引用：{join_values(value_of(risk, 'evidence_refs_json', []))}")
    lines.append("")
    return lines


def render_questions(package: dict[str, Any]) -> list[str]:
    lines = ["## 开放问题", ""]
    questions = as_list(package.get("questions"))
    if not questions:
        lines.append("- 暂无开放问题。")
    for question in questions:
        lines.append(f"- {plain_text_excerpt(value_of(question, 'prompt', '未命名问题'), 240) or '未命名问题'}")
        lines.append(f"  - 状态：`{status_label(text(value_of(question, 'status', 'unknown')))}`")
        lines.append(f"  - 影响：`{risk_label(text(value_of(question, 'impact', 'unknown')))}`")
        lines.append(f"  - 背景：{inline(value_of(question, 'reason', ''))}")
        answer = value_of(question, "answer_text")
        if answer:
            lines.append(f"  - 回答：{inline(answer)}")
    lines.append("")
    return lines


def render_recommendations(package: dict[str, Any]) -> list[str]:
    lines = ["## 建议", ""]
    recommendations = as_list(package.get("recommendations"))
    if not recommendations:
        lines.append("- 暂无建议。")
    for recommendation in recommendations:
        lines.append(f"- {inline(value_of(recommendation, 'summary', '建议'))}")
        lines.append(f"  - 依据：{inline(value_of(recommendation, 'rationale', ''))}")
        lines.append(f"  - 可信度：`{text(value_of(recommendation, 'confidence', 'unknown'))}`")
        next_steps = as_list(value_of(recommendation, "next_steps_json", []))
        if next_steps:
            lines.append(f"  - 下一步：{join_values(next_steps)}")
    lines.append("")
    return lines


def render_timeline(package: dict[str, Any]) -> list[str]:
    lines = ["## 调研过程时间线", ""]
    turns = sorted(as_list(package.get("turns")), key=lambda turn: int(value_of(turn, "turn_index", 0) or 0))
    if not turns:
        lines.append("- 暂无 Loop 轮次记录。")
    for turn in turns:
        lines.append(f"- #{text(value_of(turn, 'turn_index', '?'))} `{text(value_of(turn, 'node_name', 'node'))}`")
        lines.append(f"  - 动作：{inline(value_of(turn, 'action', ''))}")
        lines.append(f"  - 观察：{inline(value_of(turn, 'observation', ''))}")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def codebase_presence(inventory: dict[str, Any]) -> dict[str, bool]:
    maps = as_list(inventory.get("codebase_maps"))
    return {
        "codebase": bool(maps),
        "readme": bool(first_readme(inventory)),
        "entrypoint": bool(unique_values(inventory_entrypoints(inventory))),
        "dependency": bool(unique_values(collect_codebase_values(inventory, "dependency_files_json"))),
        "config": bool(unique_values(inventory_configs(inventory))),
        "test": bool(unique_values(collect_codebase_values(inventory, "test_files_json"))),
    }


def extension_verdict(inventory: dict[str, Any]) -> tuple[str, str]:
    state = codebase_presence(inventory)
    if not state["codebase"]:
        return "无法评估：缺少代码扫描结果", "低"
    if state["test"] and state["entrypoint"] and state["dependency"]:
        return "可进入小范围 POC，需先补回归用例", "中"
    if state["entrypoint"]:
        return "先做隔离 POC，不建议直接改核心", "低"
    return "暂缓：入口或依赖信息不足", "低"


def delivery_verdict(inventory: dict[str, Any]) -> tuple[str, list[str]]:
    state = codebase_presence(inventory)
    missing = [label for key, label in MISSING_ITEM_LABELS.items() if not state[key]]
    if not state["codebase"]:
        return "不通过：没有代码扫描结果，无法核对交付物", ["缺少代码目录或仓库输入"]
    if not missing:
        return "通过（静态核对）：关键资产齐全，仍需实际启动验收", []
    if len(missing) <= 2:
        return "有条件通过：补齐缺失项后可进入验收", [f"缺少{label}" for label in missing]
    return "不通过：关键交付资产缺失较多", [f"缺少{label}" for label in missing]


def collect_modules(inventory: dict[str, Any]) -> list[tuple[str, int, str]]:
    modules: list[tuple[str, int, str]] = []
    for codebase_map in as_list(inventory.get("codebase_maps")):
        file_tree = value_of(codebase_map, "file_tree_json", [])
        samples = module_samples(file_tree)
        for name, count in top_level_modules(file_tree, code_only=True):
            modules.append((name, count, samples.get(name, "")))
    return modules


def collect_teaching_modules(inventory: dict[str, Any]) -> list[tuple[str, int, str]]:
    """课程章节用更细的模块：单个容器目录过大时展开到二级目录。"""

    expanded: list[tuple[str, int, str]] = []
    for name, count, sample in collect_modules(inventory):
        if count > 80:
            children = child_modules(inventory, name)
            if len(children) >= 2:
                expanded.extend(children)
                continue
        expanded.append((name, count, sample))
    return expanded


def nested_module_breakdown(
    file_tree: Any,
    parent: str,
    *,
    depth: int = 3,
    limit: int = 6,
) -> list[tuple[str, int, str]]:
    counts: dict[str, int] = {}
    candidates: dict[str, list[str]] = {}
    for item in as_list(file_tree):
        path = text(value_of(item, "path", item))
        if text(value_of(item, "kind", "file")) != "file":
            continue
        if not is_core_code_path(path) or is_test_file(path):
            continue
        parts = path.split("/")
        if len(parts) < depth or parts[0] != parent:
            continue
        group = "/".join(parts[:depth])
        counts[group] = counts.get(group, 0) + 1
        candidates.setdefault(group, []).append(path)
    return [
        (name, count, min(candidates.get(name, [""]), key=sample_rank))
        for name, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
    ]


def child_modules(inventory: dict[str, Any], parent: str) -> list[tuple[str, int, str]]:
    counts: dict[str, int] = {}
    candidates: dict[str, list[str]] = {}
    for codebase_map in as_list(inventory.get("codebase_maps")):
        for item in as_list(value_of(codebase_map, "file_tree_json", [])):
            path = text(value_of(item, "path", item))
            if text(value_of(item, "kind", "file")) != "file":
                continue
            if not is_core_code_path(path) or is_test_file(path):
                continue
            parts = path.split("/")
            if len(parts) < 3 or parts[0] != parent:
                continue
            child = f"{parent}/{parts[1]}"
            counts[child] = counts.get(child, 0) + 1
            candidates.setdefault(child, []).append(path)
    return [
        (
            child,
            count,
            min(candidates.get(child, [""]), key=sample_rank),
        )
        for child, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:6]
    ]


def sample_rank(path: str) -> tuple[int, int, int, str]:
    name = path.rsplit("/", maxsplit=1)[-1]
    preferred = {
        "App.jsx",
        "App.tsx",
        "app.py",
        "index.js",
        "index.jsx",
        "index.ts",
        "index.tsx",
        "layout.tsx",
        "main.js",
        "main.jsx",
        "main.py",
        "main.ts",
        "main.tsx",
        "page.tsx",
    }
    if name == "page.tsx":
        return (-1, len(path.split("/")), path)
    return (0 if name in preferred else 1, len(path.split("/")), path)


def module_samples(file_tree: Any) -> dict[str, str]:
    candidates: dict[str, list[str]] = {}
    for item in as_list(file_tree):
        path = text(value_of(item, "path", item))
        if not path or "/" not in path:
            continue
        if text(value_of(item, "kind", "file")) != "file":
            continue
        if not is_core_code_path(path) or is_test_file(path):
            continue
        module_name = path.split("/", maxsplit=1)[0]
        if not module_name:
            continue
        candidates.setdefault(module_name, []).append(path)

    preferred = {
        "App.jsx",
        "App.tsx",
        "app.py",
        "index.js",
        "index.jsx",
        "index.ts",
        "index.tsx",
        "layout.tsx",
        "main.js",
        "main.jsx",
        "main.py",
        "main.ts",
        "main.tsx",
        "page.tsx",
        "server.js",
        "server.ts",
    }
    samples: dict[str, str] = {}
    for module_name, paths in candidates.items():
        samples[module_name] = min(
            paths,
            key=lambda path: (
                0 if path.rsplit("/", maxsplit=1)[-1] in preferred else 1,
                len(path.split("/")),
                len(path),
                path,
            ),
        )
    return samples


def representative_code_files(inventory: dict[str, Any], limit: int = 4) -> list[str]:
    """每个二级目录挑一个非测试源码文件，避免讲解顺序全被测试或图片占满。"""

    groups: dict[str, list[str]] = {}
    for codebase_map in as_list(inventory.get("codebase_maps")):
        for item in as_list(value_of(codebase_map, "file_tree_json", [])):
            path = text(value_of(item, "path", item))
            if text(value_of(item, "kind", "file")) != "file":
                continue
            if not is_core_code_path(path) or is_test_file(path):
                continue
            if "/" not in path:
                continue
            if set(path.split("/")) & {"tools", "scripts", "bin", "scratch", "public", "docs"}:
                continue
            name = path.rsplit("/", maxsplit=1)[-1].lower()
            if ".config." in name or name.startswith(
                ("next.config", "postcss", "tailwind", "vitest", "eslint", "jest", "tsconfig")
            ):
                continue
            parts = path.split("/")
            key = "/".join(parts[:3]) if len(parts) >= 4 else "/".join(parts[:2])
            groups.setdefault(key, []).append(path)
    selected = [
        min(paths, key=lambda path: (len(path.split("/")), len(path), path))
        for paths in groups.values()
        if paths
    ]
    selected.sort(key=lambda path: (len(path.split("/")), path))
    return selected[:limit]


def first_readme(inventory: dict[str, Any]) -> str:
    return first_text(value_of(item, "readme_excerpt") for item in as_list(inventory.get("codebase_maps")))


def collect_codebase_values(inventory: dict[str, Any], key: str) -> list[str]:
    values: list[str] = []
    for codebase_map in as_list(inventory.get("codebase_maps")):
        values.extend(text(value) for value in as_list(value_of(codebase_map, key, [])) if text(value))
    return values


def codebase_entrypoints(codebase_map: Any) -> list[str]:
    explicit = [
        path
        for path in unique_values(value_of(codebase_map, "entrypoint_files_json", []))
        if is_valid_entrypoint_path(path)
    ]
    if explicit:
        return explicit
    file_tree = as_list(value_of(codebase_map, "file_tree_json", []))
    paths = {
        text(value_of(item, "path", item))
        for item in file_tree
        if text(value_of(item, "kind", "file")) == "file"
    }
    tech_stack = as_list(codebase_tech_stack(codebase_map))
    return [
        path
        for path in infer_entrypoints(paths, tech_stack)
        if is_valid_entrypoint_path(path)
    ]


def inventory_entrypoints(inventory: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for codebase_map in as_list(inventory.get("codebase_maps")):
        values.extend(codebase_entrypoints(codebase_map))
    return unique_values(values)


def inventory_tech_stack(inventory: dict[str, Any]) -> list[str]:
    return resolve_tech_stack(as_list(inventory.get("codebase_maps")))


def codebase_configs(codebase_map: Any) -> list[str]:
    return [
        path
        for path in unique_values(value_of(codebase_map, "config_files_json", []))
        if path.rsplit("/", maxsplit=1)[-1].lower() not in {".gitignore", ".editorconfig"}
    ]


def inventory_configs(inventory: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for codebase_map in as_list(inventory.get("codebase_maps")):
        values.extend(codebase_configs(codebase_map))
    return unique_values(values)


def all_file_paths(inventory: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for codebase_map in as_list(inventory.get("codebase_maps")):
        for item in as_list(value_of(codebase_map, "file_tree_json", [])):
            path = text(value_of(item, "path", item))
            if path and text(value_of(item, "kind", "file")) == "file":
                paths.append(path)
    return paths


def open_question_items(package: dict[str, Any]) -> list[Any]:
    return [
        question
        for question in as_list(package.get("questions"))
        if text(value_of(question, "status", "")) == "open"
    ]


def confidence_label(verifier_result: dict[str, Any]) -> str:
    if bool(verifier_result.get("passed", False)):
        return "中（确定性校验通过，但未做真实运行验证）"
    return "低（存在阻塞问题或关键证据缺口）"


def profile_info(package: dict[str, Any], verifier_result: dict[str, Any]) -> Any:
    profile = package.get("profile_summary")
    if profile:
        return profile
    return verifier_result.get("research_profile") if isinstance(verifier_result, dict) else {}


def unique_brief_items(items: list[Any]) -> list[Any]:
    seen = set()
    result = []
    for item in items:
        key = text(getattr(item, "text", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result or items


def join_values(values: Any, *, limit: int = DEFAULT_LIST_LIMIT) -> str:
    items = [display_value(value) for value in as_list(values) if value not in (None, "")]
    items = [item for item in items if item]
    if not items:
        return "未检测到"
    visible = items[:limit]
    rendered = "，".join(visible)
    omitted_count = len(items) - len(visible)
    if omitted_count > 0:
        rendered = f"{rendered} (+{omitted_count} more)"
    return rendered


def display_value(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("path", "name", "title", "summary"):
            nested = text(value.get(key, ""))
            if nested:
                return nested
        return text(value)
    raw = text(value)
    return TECH_STACK_LABELS.get(raw.lower(), raw)


def unique_values(values: Any) -> list[str]:
    seen = set()
    result = []
    for value in as_list(values):
        item = text(value)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def truncate(value: Any, max_length: int) -> str:
    rendered = text(value)
    if len(rendered) <= max_length:
        return rendered
    return rendered[: max_length - 3] + "..."


def text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def inline(value: Any, max_length: int | None = None) -> str:
    """把可能包含 Markdown 标题或代码块的摘要压成一行，避免污染报告章节结构。"""

    rendered = re.sub(r"\s+", " ", text(value)).strip()
    if max_length is not None:
        return truncate(rendered, max_length)
    return rendered


def display_title(value: Any, fallback: str) -> str:
    cleaned = plain_text_excerpt(value, 160)
    if cleaned.endswith(("：", ":")):
        cleaned += "（原文缺失）"
    return cleaned or fallback


def is_empty_finding(finding: Any) -> bool:
    title = plain_text_excerpt(value_of(finding, "title", ""), 160)
    summary = plain_text_excerpt(value_of(finding, "summary", ""), 160)
    if not summary and title.endswith(("：", ":")):
        return True
    return "（原文缺失）" in title and not summary


def bool_label(value: bool) -> str:
    return "是" if value else "否"


def risk_label(value: str) -> str:
    labels = {
        "low": "低",
        "medium": "中",
        "high": "高",
        "critical": "严重",
        "unknown": "未知",
    }
    return labels.get(value, value)


def severity_label(value: str) -> str:
    labels = {
        "info": "信息",
        "warning": "警告",
        "error": "错误",
    }
    return labels.get(value, value)


def status_label(value: str) -> str:
    labels = {
        "draft": "草稿",
        "ready": "就绪",
        "running": "运行中",
        "paused_for_input": "等待输入",
        "pending": "待处理",
        "partial": "部分完成",
        "ready_for_review": "待评审",
        "ready_for_review_with_risks": "带风险待评审",
        "completed": "已完成",
        "failed": "失败",
        "blocked": "存在阻塞",
        "approved": "已通过",
        "rejected": "已驳回",
        "needs_more": "要求补充",
        "answered": "已回答",
        "open": "待回答",
        "collected": "已采集",
        "unknown": "未知",
    }
    return labels.get(value, value)


def check_name_label(value: str) -> str:
    labels = {
        "structure_completeness": "结构完整度",
        "evidence_coverage": "证据覆盖",
        "codebase_coverage": "代码覆盖",
        "risk_transparency": "风险透明度",
        "question_resolution": "问题关闭率",
        "quality_score": "质量评分",
    }
    if value.startswith("profile:"):
        check = value.split(":", 1)[1]
        profile_labels = {
            "has_entrypoint": "入口线索",
            "has_dependency_clues": "依赖线索",
            "has_reading_path": "阅读路径",
            "has_module_boundaries": "模块边界",
            "has_architecture_clues": "架构线索",
            "has_test_clues": "测试线索",
            "has_risk_register": "风险登记",
            "has_mitigation": "缓解建议",
            "has_key_files": "关键文件",
            "has_learning_path": "学习路径",
            "has_exercises": "练习任务",
            "has_runbook_clues": "启动线索",
            "has_open_questions": "开放问题",
            "has_delivery_readiness_summary": "交付可接手总结",
        }
        return "档位检查 · " + profile_labels.get(check, check)
    return labels.get(value, value)
