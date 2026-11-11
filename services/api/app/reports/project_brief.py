"""从已采集资料中提取「项目速览」事实。

报告需要先回答三个问题：这个项目是什么、为什么做、有什么特点。
这里只使用 README 摘要、依赖清单和代码库扫描结果，不重新读取文件，
也不调用模型；推断项会显式标注，缺失项会进入 gaps 而不是被编造。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.tools.code_scan_tools import (
    detect_frameworks,
    dominant_stack,
    infer_entrypoints,
    is_core_code_path,
    is_source_code_path,
    is_test_file,
    is_valid_entrypoint_path,
)


BADGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
HTML_RE = re.compile(r"<[^>]+>")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
SENTENCE_RE = re.compile(r"(?<=[。！？!?])\s*|(?<=[.])(?=\s)")

INTRO_KEYS = (
    "introduction",
    "overview",
    "about",
    "what is",
    "summary",
    "项目简介",
    "项目介绍",
    "简介",
    "概述",
    "项目概述",
)
WHY_KEYS = (
    "why",
    "background",
    "motivation",
    "problem",
    "goal",
    "purpose",
    "背景",
    "动机",
    "为什么",
    "项目背景",
    "目标",
    "要解决",
    "解决什么",
)
FEATURE_KEYS = (
    "feature",
    "features",
    "function",
    "functionality",
    "capabilit",
    "功能",
    "特性",
    "亮点",
    "能力",
    "主要功能",
)
RUN_KEYS = (
    "quick start",
    "quickstart",
    "getting started",
    "install",
    "installation",
    "usage",
    "run",
    "start",
    "启动",
    "运行",
    "安装",
    "快速开始",
    "快速上手",
    "使用",
)

PURPOSE_SENTENCE_RE = re.compile(
    r"(解决|用于|目标是|旨在|\bwhy\b|\bmotivation\b|\bpurpose\b|\bgoal\b|\bbuilds? upon\b|\bbased on\b|\bgrew out of\b|\bhosted by\b|\bmaintained by\b|\bfunded by\b|诞生|基于|源于)",
    re.IGNORECASE,
)
CAPABILITY_SENTENCE_RE = re.compile(
    r"(\bprovides?\b|\bsupports?\b|\bincludes?\b|\benables?\b|\bmanages?\b|\bdeploys?\b|\bscales?\b|提供|支持|包括|用于|管理|部署|扩展)",
    re.IGNORECASE,
)
TROUBLESHOOT_KEYS = ("troubleshoot", "faq", "常见问题", "排错", "错误处理")
LANGUAGE_TAGS = {"go", "java", "javascript", "python", "typescript"}
RUN_COMMAND_RE = re.compile(
    r"(^|\s)(\$ |pip install|pip3 install|uv sync|uv run|poetry install|npm install|npm run|pnpm install|pnpm run|yarn |uvicorn |gunicorn |python |python3 |node |docker compose|docker-compose|make )",
    re.IGNORECASE,
)

FRAMEWORK_SHAPES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("next", "nextjs"), "Web 前端（Next.js）"),
    (("react",), "Web 前端（React）"),
    (("vue",), "Web 前端（Vue）"),
    (("fastapi",), "HTTP API 服务（FastAPI）"),
    (("flask",), "HTTP API 服务（Flask）"),
    (("django",), "Web 应用（Django）"),
    (("express",), "HTTP 服务（Express）"),
    (("langgraph",), "Agent 工作流（LangGraph）"),
    (("langchain",), "LLM 应用（LangChain）"),
    (("celery",), "异步任务服务（Celery）"),
)

MODULE_ROLE_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("cmd", "command"), "命令入口"),
    (("pkg", "internal", "core"), "核心包"),
    (("staging",), "对外 API/组件库"),
    (("plugin", "plugins", "extension"), "插件与扩展"),
    (("cluster",), "集群部署与脚本"),
    (("hack",), "构建/测试工具"),
    (("third_party", "third-party", "vendor"), "第三方代码"),
    (("api", "routes", "router", "controller", "endpoint"), "接口/路由层"),
    (("service", "services", "usecase", "usecases", "domain"), "业务服务层"),
    (("web", "apps", "frontend", "ui", "pages", "components"), "前端/界面层"),
    (("db", "database", "models", "repository", "repositories", "dao"), "数据访问层"),
    (("config", "settings", "conf"), "配置层"),
    (("worker", "workers", "jobs", "tasks", "queue"), "后台任务层"),
    (("test", "tests", "spec", "e2e"), "测试"),
    (("docs", "doc"), "文档"),
    (("scripts", "tools", "bin"), "脚本/工具"),
)


@dataclass
class BriefItem:
    text: str
    basis: str
    source: str


@dataclass
class ProjectBrief:
    name: str = ""
    topic: str = ""
    goal: str = ""
    readme_title: str | None = None
    positioning: BriefItem | None = None
    problems: list[BriefItem] = field(default_factory=list)
    features: list[BriefItem] = field(default_factory=list)
    traits: list[BriefItem] = field(default_factory=list)
    shapes: list[BriefItem] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    runbook: list[str] = field(default_factory=list)
    modules: list[tuple[str, int]] = field(default_factory=list)
    roots: list[str] = field(default_factory=list)
    evidence_notes: list[str] = field(default_factory=list)


@dataclass
class ReadmeBlock:
    heading: str | None
    level: int
    paragraphs: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    code_lines: list[str] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)


def build_project_brief(project: Any, inventory: dict[str, Any]) -> ProjectBrief:
    codebase_maps = as_list(inventory.get("codebase_maps"))
    snapshots = as_list(inventory.get("snapshots"))
    readme_path = _readme_path(codebase_maps)
    readme = first_text(codebase_value(item, "readme_excerpt") for item in codebase_maps)
    blocks = parse_readme(readme)
    manifests = collect_manifests(codebase_maps)
    manifest = manifests[0] if manifests else {}
    file_tree = [
        item
        for codebase_map in codebase_maps
        for item in as_list(codebase_value(codebase_map, "file_tree_json", "file_tree"))
    ]
    tech_stack = resolve_tech_stack(codebase_maps)
    file_paths = {
        text(value_of(item, "path"))
        for item in file_tree
        if text(value_of(item, "kind", "file")) == "file"
    }
    entrypoints = unique_values(
        [
            *(
                path
                for path in collect_codebase_values(codebase_maps, "entrypoint_files_json", "entrypoint_files")
                if is_valid_entrypoint_path(path)
            ),
            *infer_entrypoints(file_paths, tech_stack),
        ]
    )
    tests = unique_values(collect_codebase_values(codebase_maps, "test_files_json", "test_files"))
    dependencies = unique_values(collect_codebase_values(codebase_maps, "dependency_files_json", "dependency_files"))
    configs = unique_values(collect_codebase_values(codebase_maps, "config_files_json", "config_files"))
    configs = [
        path
        for path in configs
        if path.rsplit("/", maxsplit=1)[-1].lower() not in {".gitignore", ".editorconfig"}
    ]

    brief = ProjectBrief(
        name=text(value_of(project, "name")),
        topic=text(value_of(project, "topic")),
        goal=text(value_of(project, "analysis_goal")),
        readme_title=readme_title(blocks),
        roots=unique_values(text(value_of(codebase_map, "root_label", "")) for codebase_map in codebase_maps),
        modules=top_level_modules(file_tree, code_only=True),
        tech_stack=tech_stack,
    )

    brief.positioning = _positioning(brief, blocks, manifest, readme_path)
    brief.problems = _problems(blocks, snapshots, brief.positioning.text if brief.positioning else "", readme_path)
    brief.features = _features(blocks, manifest, readme_path)
    brief.traits = _traits(brief, entrypoints, tests, dependencies, configs)
    brief.shapes = _shapes(tech_stack, entrypoints, dependencies, configs)
    brief.runbook = extract_readme_runbook(readme)

    if not readme:
        brief.gaps.append("缺少 README/项目说明，项目用途、动机和启动方式无法从资料直接核实。")
    if not brief.problems:
        brief.gaps.append("现有资料没有单独说明项目为什么做、要解决什么问题；报告只记录可核实的功能与定位。")
    if not brief.features:
        brief.gaps.append("现有资料没有功能清单，报告只能根据技术栈和目录结构推断能力边界。")
    if codebase_maps and not entrypoints:
        brief.gaps.append("未识别到入口文件，启动方式和程序形态需要人工确认。")
    if codebase_maps and not tests:
        brief.gaps.append("未发现测试文件，行为与改造结论缺少自动化验证。")
    if codebase_maps and not dependencies:
        brief.gaps.append("未识别到依赖清单，无法核对框架版本和安装步骤。")
    if not codebase_maps:
        brief.gaps.append("本次只有文本资料，没有代码扫描结果，无法验证实际实现和项目形态。")

    brief.evidence_notes = _evidence_notes(brief, manifest, file_paths)
    return brief


def parse_readme(readme: str | None) -> list[ReadmeBlock]:
    if not readme:
        return []
    blocks: list[ReadmeBlock] = [ReadmeBlock(heading=None, level=0)]
    current = blocks[0]
    in_code = False
    table_rows: list[list[str]] = []
    paragraph_parts: list[str] = []

    def flush_table() -> None:
        nonlocal table_rows
        if len(table_rows) >= 2:
            current.tables.append(table_rows)
        table_rows = []

    def flush_paragraph() -> None:
        nonlocal paragraph_parts
        if paragraph_parts:
            current.paragraphs.append(" ".join(paragraph_parts).strip())
        paragraph_parts = []

    for raw_line in readme.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            flush_table()
            flush_paragraph()
            in_code = not in_code
            continue
        if in_code:
            cleaned_code = _normalize_inline(stripped)
            if cleaned_code:
                current.code_lines.append(cleaned_code)
            continue
        heading_match = HEADING_RE.match(stripped)
        if heading_match:
            flush_table()
            flush_paragraph()
            current = ReadmeBlock(
                heading=_normalize_inline(heading_match.group(2)),
                level=len(heading_match.group(1)),
            )
            blocks.append(current)
            continue
        if stripped.startswith("|") and stripped.count("|") >= 2:
            flush_paragraph()
            cells = [_normalize_inline(cell) for cell in stripped.strip("|").split("|")]
            if any(cell and set(cell) <= {"-", ":", " "} for cell in cells):
                continue
            if any(cells):
                table_rows.append(cells)
            continue
        flush_table()
        cleaned = _normalize_inline(raw_line)
        if not cleaned:
            flush_paragraph()
            continue
        if _is_bullet(raw_line):
            flush_paragraph()
            current.bullets.append(cleaned)
        else:
            paragraph_parts.append(cleaned)
    flush_table()
    flush_paragraph()
    return [
        block
        for block in blocks
        if block.heading or block.paragraphs or block.bullets or block.code_lines or block.tables
    ]


def readme_title(blocks: list[ReadmeBlock]) -> str | None:
    for block in blocks:
        if block.heading and block.level == 1:
            title = re.sub(r"^[^\w\u4e00-\u9fff]+", "", block.heading.strip()).strip()
            if title and not title.lower().startswith(("readme", "documentation", "docs")):
                return title
    return None


def extract_readme_runbook(readme: str | None) -> list[str]:
    blocks = parse_readme(readme)
    steps: list[str] = []
    for block in blocks:
        if not block.heading or not _matches_any(block.heading, RUN_KEYS):
            continue
        steps.extend(block.code_lines)
        steps.extend(block.bullets)
        steps.extend(paragraph for paragraph in block.paragraphs if RUN_COMMAND_RE.search(paragraph))
    if not steps:
        for block in blocks:
            steps.extend(line for line in block.code_lines if RUN_COMMAND_RE.search(line))
            steps.extend(line for line in block.bullets if RUN_COMMAND_RE.search(line))
    steps = [shorten(step, 160) for step in unique_values(steps) if step]
    return steps[:8]


def module_role(module_name: str) -> str | None:
    lowered = module_name.lower()
    for keys, label in MODULE_ROLE_HINTS:
        if any(key == lowered or key in lowered for key in keys):
            return label
    return None


def _positioning(
    brief: ProjectBrief,
    blocks: list[ReadmeBlock],
    manifest: dict[str, Any],
    readme_path: str,
) -> BriefItem | None:
    # README 是项目级材料，优先于子包的 package/pyproject 描述。
    intro = _first_intro(blocks)
    if intro:
        return BriefItem(
            text=shorten(_first_sentences(intro, 1), 300),
            basis="资料原文",
            source=f"{readme_path} 首段",
        )

    description = text(manifest.get("description"))
    if description:
        return BriefItem(
            text=shorten(description, 220),
            basis="资料原文",
            source=f"{text(manifest.get('path')) or '依赖清单'} 的 description 字段",
        )

    if brief.topic:
        return BriefItem(
            text=brief.topic,
            basis="用户填写",
            source="调研主题（不是项目自述，需人工确认）",
        )
    return None


def _problems(
    blocks: list[ReadmeBlock],
    snapshots: list[Any],
    positioning_text: str,
    readme_path: str,
) -> list[BriefItem]:
    for block in blocks:
        if block.heading and _matches_any(block.heading, WHY_KEYS):
            content = " ".join(block.paragraphs[:2]) or "；".join(block.bullets[:3])
            if content:
                return [BriefItem(shorten(content, 300), "资料原文", f"{readme_path}「{block.heading}」")]

    for block in blocks[:4]:
        if block.heading and _matches_any(block.heading, TROUBLESHOOT_KEYS):
            continue
        for paragraph in block.paragraphs:
            for sentence in SENTENCE_RE.split(paragraph):
                sentence = sentence.strip()
                if len(sentence) < 12 or not PURPOSE_SENTENCE_RE.search(sentence):
                    continue
                if positioning_text and _is_same_text(sentence, positioning_text):
                    continue
                source = (
                    f"{readme_path}「{block.heading}」"
                    if block.heading and block.level > 1
                    else f"{readme_path} 首段"
                )
                return [BriefItem(shorten(sentence, 220), "资料原文", source)]

    for snapshot in snapshots:
        excerpt = text(value_of(snapshot, "content_excerpt"))
        for sentence in SENTENCE_RE.split(excerpt):
            sentence = sentence.strip()
            if len(sentence) >= 16 and PURPOSE_SENTENCE_RE.search(sentence):
                if positioning_text and _is_same_text(sentence, positioning_text):
                    continue
                title = text(value_of(snapshot, "title")) or text(value_of(snapshot, "source_type")) or "资料"
                return [BriefItem(shorten(sentence, 220), "资料原文", title)]
    return []


def _features(blocks: list[ReadmeBlock], manifest: dict[str, Any], readme_path: str) -> list[BriefItem]:
    for block in blocks:
        if not block.heading or not _matches_any(block.heading, FEATURE_KEYS):
            continue
        source = f"{readme_path}「{block.heading}」"
        table_rows: list[BriefItem] = []
        for table in block.tables:
            header = table[0] if table else []
            for row in table[1:]:
                cells = [cell for cell in row if cell]
                if len(cells) < 2:
                    continue
                detail = "；".join(
                    f"{header[index]}：{cell}" if index < len(header) and header[index] else cell
                    for index, cell in enumerate(cells[1:], start=1)
                )
                table_rows.append(BriefItem(f"{cells[0]} — {detail}", "资料原文", f"{source}表格"))
        if table_rows:
            return table_rows[:15]

        items = _clean_feature_items(block.bullets) or _clean_feature_items(block.paragraphs)
        if items:
            return [BriefItem(shorten(item, 180), "资料原文", source) for item in items[:6]]

    intro = _first_intro(blocks)
    if intro:
        sentences = [sentence.strip() for sentence in SENTENCE_RE.split(intro) if sentence.strip()]
        capabilities = [
            BriefItem(shorten(sentence, 200), "资料原文", f"{readme_path} 首段")
            for sentence in sentences[1:]
            if len(sentence) >= 20 and CAPABILITY_SENTENCE_RE.search(sentence)
        ]
        if capabilities:
            return capabilities[:4]

    keywords = [text(keyword) for keyword in as_list(manifest.get("keywords")) if text(keyword)]
    if keywords:
        return [
            BriefItem(
                text=f"关键词：{'、'.join(keywords[:6])}",
                basis="资料原文",
                source=f"{text(manifest.get('path')) or '依赖清单'} 的 keywords 字段",
            )
        ]
    return []


def _clean_feature_items(items: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in items:
        value = item.strip()
        if len(value) < 8:
            continue
        if value.endswith(("：", ":")):
            continue
        if value.startswith(("依据", "来源")):
            continue
        cleaned.append(value)
    return cleaned


def _traits(
    brief: ProjectBrief,
    entrypoints: list[str],
    tests: list[str],
    dependencies: list[str],
    configs: list[str],
) -> list[BriefItem]:
    traits: list[BriefItem] = []
    if entrypoints:
        traits.append(BriefItem("入口：" + "、".join(entrypoints[:4]), "扫描事实", "入口文件扫描"))
    if brief.modules:
        modules = "、".join(f"`{name}`({count})" for name, count in brief.modules[:6])
        traits.append(BriefItem(f"顶层模块：{modules}", "扫描事实", "目录扫描"))
    if dependencies:
        traits.append(BriefItem("依赖清单：" + "、".join(dependencies[:5]), "扫描事实", "依赖文件扫描"))
    if configs:
        traits.append(BriefItem("运行配置：" + "、".join(configs[:5]), "扫描事实", "配置文件扫描"))
    if tests:
        traits.append(BriefItem(f"测试：发现 {len(tests)} 个测试文件", "扫描事实", "测试文件扫描"))
    deployment = [path for path in configs if "docker" in path.lower()]
    if deployment:
        traits.append(BriefItem("部署：发现 " + "、".join(deployment[:3]), "扫描事实", "配置文件扫描"))
    return traits


def _shapes(
    tech_stack: list[str],
    entrypoints: list[str],
    dependencies: list[str],
    configs: list[str],
) -> list[BriefItem]:
    lowered = {item.lower() for item in [*tech_stack, *dependencies]}
    shapes: list[BriefItem] = []
    frontend_names: list[str] = []
    for keys, label in FRAMEWORK_SHAPES:
        if not any(key in lowered for key in keys):
            continue
        if label.startswith("Web 前端（"):
            frontend_names.append(label.removeprefix("Web 前端（").removesuffix("）"))
        else:
            shapes.append(BriefItem(label, "推断", "依赖/技术栈扫描"))
    if frontend_names:
        shapes.insert(
            0,
            BriefItem(
                f"Web 前端（{' + '.join(frontend_names)}）",
                "推断",
                "依赖/技术栈扫描",
            ),
        )

    if not shapes:
        entry_text = " ".join(entrypoints).lower()
        if entrypoints:
            if any(name in entry_text for name in ("main.py", "app.py", "server.py", "manage.py")):
                shapes.append(BriefItem("Python 应用（入口脚本）", "推断", "入口文件扫描"))
            elif any(name in entry_text for name in ("index.ts", "main.ts", "index.tsx", "main.tsx")):
                shapes.append(BriefItem("前端应用（入口脚本）", "推断", "入口文件扫描"))
            else:
                shapes.append(BriefItem("可执行应用（存在入口文件）", "推断", "入口文件扫描"))
        elif not entrypoints:
            shapes.append(BriefItem("未识别到启动入口，可能是库/模块或需要外部命令启动", "推断", "入口文件扫描"))

    if any("docker" in path.lower() for path in configs):
        shapes.append(BriefItem("容器化部署（Docker）", "扫描事实", "配置文件扫描"))
    return shapes


def collect_manifests(codebase_maps: list[Any]) -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    for codebase_map in codebase_maps:
        metadata = codebase_value(codebase_map, "metadata_json", "metadata") or {}
        if not isinstance(metadata, dict):
            continue
        for manifest in as_list(metadata.get("manifests")):
            if isinstance(manifest, dict):
                manifests.append(manifest)
    return manifests


def resolve_tech_stack(codebase_maps: list[Any]) -> list[str]:
    stored = unique_values(collect_codebase_values(codebase_maps, "tech_stack_json", "tech_stack"))
    manifests = collect_manifests(codebase_maps)
    manifest_dependencies = [
        str(dependency)
        for item in manifests
        for dependency in as_list(item.get("dependencies"))
    ]
    file_tree = [
        item
        for codebase_map in codebase_maps
        for item in as_list(codebase_value(codebase_map, "file_tree_json", "file_tree"))
    ]
    derived = dominant_stack(file_tree)
    frameworks = [
        *sorted(detect_frameworks(manifest_dependencies)),
        *([tag for tag in stored if tag not in LANGUAGE_TAGS] if derived else []),
    ]
    return unique_values([*(derived if derived else stored), *frameworks])


def codebase_tech_stack(codebase_map: Any) -> list[str]:
    return resolve_tech_stack([codebase_map])


def codebase_value(item: Any, *keys: str) -> Any:
    """兼容 ORM 的 `*_json` 字段和上下文包里的短字段名。"""

    for key in keys:
        value = value_of(item, key)
        if value not in (None, "", [], {}):
            return value
    return None


def collect_codebase_values(items: list[Any], *keys: str) -> list[str]:
    values: list[str] = []
    for item in items:
        source = codebase_value(item, *keys)
        values.extend(text(value) for value in as_list(source) if text(value))
    return values


def _readme_path(codebase_maps: list[Any]) -> str:
    for codebase_map in codebase_maps:
        for item in as_list(codebase_value(codebase_map, "file_tree_json", "file_tree")):
            path = text(value_of(item, "path", item))
            if text(value_of(item, "kind", "file")) == "file" and path.rsplit("/", 1)[-1].lower().startswith("readme"):
                return path
    return "README.md"


def _evidence_notes(
    brief: ProjectBrief,
    manifest: dict[str, Any],
    file_paths: set[str],
) -> list[str]:
    notes: list[str] = []
    if brief.positioning is not None:
        notes.append(f"{brief.positioning.source}：{shorten(brief.positioning.text, 200)}")
    if brief.problems:
        notes.append(f"{brief.problems[0].source}：{shorten(brief.problems[0].text, 100)}")
    if brief.features:
        notes.append(f"{brief.features[0].source}：{len(brief.features)} 条功能/能力")
    if file_paths:
        notes.append(
            "代码库扫描："
            + "、".join(
                item
                for item in [
                    "依赖清单" if brief.traits else "",
                    "入口文件" if any("入口：" in trait.text for trait in brief.traits) else "",
                    f"{len(file_paths)} 个文件" if file_paths else "",
                    f"{len(brief.modules)} 个代码模块" if brief.modules else "",
                ]
                if item
            )
        )
    manifest_description = text(manifest.get("description"))
    if manifest_description:
        notes.append(f"{text(manifest.get('path')) or '依赖清单'} 的 description：{shorten(manifest_description, 100)}")
    return unique_values(notes)


def plain_text_excerpt(value: Any, limit: int = 240) -> str:
    """把 README/HTML 摘要压成可读纯文本，避免把徽章、HTML 和标题层级搬进报告。"""

    rendered = text(value)
    if not rendered:
        return ""
    rendered = BADGE_RE.sub("", rendered)
    rendered = LINK_RE.sub(r"\1", rendered)
    rendered = URL_RE.sub(" ", rendered)
    rendered = HTML_RE.sub(" ", rendered)
    rendered = re.sub(r"```.*?```", " ", rendered, flags=re.DOTALL)
    rendered = re.sub(r"^\s{0,3}#{1,6}\s*", " ", rendered, flags=re.MULTILINE)
    rendered = re.sub(r"^\s*[-*+]\s+", " ", rendered, flags=re.MULTILINE)
    rendered = re.sub(r"\|?\s*:?-{3,}:?\s*\|?", " ", rendered)
    rendered = rendered.replace("|", " ")
    rendered = re.sub(r"\s+", " ", rendered).strip()
    return shorten(rendered, limit)


def top_level_modules(file_tree: Any, *, code_only: bool = False) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for item in as_list(file_tree):
        path = text(value_of(item, "path", item))
        if not path or "/" not in path:
            continue
        if code_only and (
            text(value_of(item, "kind", "file")) != "file"
            or not is_core_code_path(path)
        ):
            continue
        module_name = path.split("/", maxsplit=1)[0]
        if not module_name:
            continue
        counts[module_name] = counts.get(module_name, 0) + 1
    return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))


def _first_intro(blocks: list[ReadmeBlock]) -> str:
    for block in blocks:
        if block.heading and _matches_any(block.heading, INTRO_KEYS):
            for paragraph in block.paragraphs:
                if len(paragraph) >= 20 and not _looks_like_run_instruction(paragraph):
                    return paragraph
    # README 常见写法：一级标题下面紧跟一段项目简介，而不是单独的 Introduction 小节。
    for block in blocks:
        if block.level != 1:
            continue
        for paragraph in block.paragraphs:
            if len(paragraph) >= 20 and not _looks_like_run_instruction(paragraph) and not _looks_like_toc(paragraph):
                return paragraph
    for block in blocks:
        if block.heading:
            continue
        for paragraph in block.paragraphs:
            if len(paragraph) >= 20 and not _looks_like_run_instruction(paragraph) and not _looks_like_toc(paragraph):
                return paragraph
    return ""


def _looks_like_run_instruction(value: str) -> bool:
    lowered = value.lower()
    return bool(
        RUN_COMMAND_RE.search(lowered)
        or "run with" in lowered
        or "install" in lowered
        or lowered.startswith(("运行", "启动", "安装", "快速开始"))
    )


def _is_same_text(left: str, right: str) -> bool:
    left_key = re.sub(r"[\s。！？!?，,；;：:]+", "", left)
    right_key = re.sub(r"[\s。！？!?，,；;：:]+", "", right)
    if not left_key or not right_key:
        return False
    return left_key == right_key or left_key in right_key or right_key in left_key


def _first_sentences(value: str, limit: int) -> str:
    sentences = [sentence.strip() for sentence in SENTENCE_RE.split(value) if sentence.strip()]
    return " ".join(sentences[:limit]) or value


def _looks_like_toc(value: str) -> bool:
    lowered = value.lower().strip(" :：")
    if lowered in {"table of contents", "contents", "目录"}:
        return True
    return value.count("](") >= 3


def _matches_any(value: str, keys: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(key in lowered for key in keys)


def _is_bullet(raw_line: str) -> bool:
    stripped = raw_line.lstrip()
    return bool(re.match(r"^([-*+]|\d+[.)])\s+", stripped))


def _normalize_inline(value: str) -> str:
    line = BADGE_RE.sub("", value)
    line = LINK_RE.sub(r"\1", line)
    line = URL_RE.sub("", line)
    line = HTML_RE.sub("", line)
    line = line.strip().lstrip(">").strip()
    line = re.sub(r"^([-*+]|\d+[.)])\s+", "", line)
    line = line.replace("**", "").replace("__", "").replace("`", "")
    line = re.sub(r"\s+", " ", line)
    return line.strip()


def collect_values(items: list[Any], key: str) -> list[str]:
    values: list[str] = []
    for item in items:
        values.extend(text(value) for value in as_list(value_of(item, key, [])) if text(value))
    return values


def unique_values(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = text(value)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def first_text(values: Any) -> str:
    for value in values:
        cleaned = text(value)
        if cleaned:
            return cleaned
    return ""


def shorten(value: Any, limit: int) -> str:
    rendered = text(value)
    if len(rendered) <= limit:
        return rendered
    cut = rendered[:limit]
    # 优先在句末或词边界截断，避免出现 “entit...” 这类半截单词。
    for separator in ("。", "！", "？", ". ", "；", "; "):
        position = cut.rfind(separator)
        if position >= int(limit * 0.55):
            return cut[: position + len(separator)].rstrip() + "…"
    if " " in cut:
        position = cut.rfind(" ")
        if position >= int(limit * 0.55):
            return cut[:position].rstrip() + "…"
    return cut.rstrip() + "…"


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (str, bytes, dict)):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def value_of(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
