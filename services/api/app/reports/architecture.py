"""Freeze run-scoped diagrams and describe their static source locations in reports."""

import html
import json
import re
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ArchitectureDiagram

ARCHITECTURE_HEADING = "## 源码流程与架构图"
STATIC_LIMITATION = "图表示静态源码引用，不证明运行时调用顺序、参数取值或真实数据流；动态调用保留为未解析，不按同名函数猜测连接。"
MAX_REPORT_FUNCTIONS = 120
MAX_REPORT_SOURCE_ITEMS = 1200
MAX_REPORT_ITEMS_PER_FUNCTION = 24
MAX_REPORT_FILES = 80


def snapshot_architecture_diagrams(session: Session, project_id: str, run_id: str) -> list[dict[str, Any]]:
    """Copy only this exact project's run; an empty selection must remain empty."""

    rows = session.scalars(select(ArchitectureDiagram).where(ArchitectureDiagram.project_id == project_id)
        .order_by(ArchitectureDiagram.created_at.asc(), ArchitectureDiagram.id.asc())).all()
    snapshots = []
    for row in rows:
        if not isinstance(row.stats_json, dict) or row.stats_json.get("run_id") != run_id:
            continue
        snapshots.append({
            "id": row.id, "project_id": row.project_id, "run_id": run_id,
            "diagram_type": row.diagram_type, "title": row.title, "basis": row.basis,
            "mermaid_source": row.mermaid_source, "graph_json": deepcopy(row.graph_json),
            "stats_json": deepcopy(row.stats_json), "created_at": row.created_at.isoformat(),
        })
    snapshots.sort(key=lambda item: item["diagram_type"] != "source_flow")
    # JSON round-trip also prevents references to mutable ORM-owned JSON values.
    return json.loads(json.dumps(snapshots, ensure_ascii=False))


def records(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def text(value: Any) -> str:
    return str(value) if value is not None else ""


def markdown_text(value: Any) -> str:
    cleaned = re.sub(r"<br\s*/?>", " ", text(value), flags=re.IGNORECASE)
    return html.escape(cleaned, quote=False).replace("`", "&#96;").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def source_location(item: dict[str, Any], *, path: Any = None) -> str:
    path = text(item.get("path") if path is None else path)
    start, end = item.get("line_start"), item.get("line_end")
    if not isinstance(start, int):
        return path or "位置未记录"
    lines = f"L{start}" if not isinstance(end, int) or end == start else f"L{start}-L{end}"
    return f"{path}:{lines}" if path else lines


def split_architecture_chapter(markdown: str) -> tuple[str, str]:
    base, marker, chapter = markdown.rpartition("\n" + ARCHITECTURE_HEADING + "\n")
    return (base.rstrip() + "\n", marker + chapter) if marker else (markdown, "")


def call_resolution_label(call: dict[str, Any], functions_by_id: dict[str, dict[str, Any]]) -> str:
    if not call.get("target_id"):
        return "未解析"
    target = functions_by_id.get(text(call["target_id"]))
    if target is None:
        return "已解析目标（此快照未保存目标定义）"
    return f"已解析 → {text(target.get('qualified_name') or target.get('name'))} ({source_location(target)})"


def report_navigation(details: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    """Bound document output while leaving the complete saved/searchable index intact."""

    all_files, raw_functions = records(details.get("files")), records(details.get("functions"))
    # Keep named functions and entry declarations in the bounded document; anonymous
    # JSX callbacks remain available in the complete online/searchable index.
    all_functions = [
        function for function in raw_functions
        if not text(function.get("name")).startswith("<anonymous@")
    ] + [
        function for function in raw_functions
        if text(function.get("name")).startswith("<anonymous@")
    ]
    files, selected = all_files[:MAX_REPORT_FILES], all_functions[:MAX_REPORT_FUNCTIONS]
    functions, remaining = [], MAX_REPORT_SOURCE_ITEMS
    total_items = sum(len(records(function.get("statements"))) + len(records(function.get("calls"))) for function in all_functions)
    for index, function in enumerate(selected):
        statements, calls = records(function.get("statements")), records(function.get("calls"))
        budget = min(MAX_REPORT_ITEMS_PER_FUNCTION, remaining // max(1, len(selected) - index))
        call_count = min(len(calls), budget // 2 if statements else budget)
        statement_count = min(len(statements), budget - call_count)
        call_count = min(len(calls), budget - statement_count)
        functions.append({**function, "statements": statements[:statement_count], "calls": calls[:call_count]})
        remaining -= statement_count + call_count
    shown_items = MAX_REPORT_SOURCE_ITEMS - remaining
    truncated = len(files) < len(all_files) or len(functions) < len(all_functions) or shown_items < total_items
    notice = (f"报告导航已截断：函数 {len(functions)}/{len(all_functions)}；语句/调用 {shown_items}/{total_items}；文件 {len(files)}/{len(all_files)}。"
        "在线报告保存完整本次有界索引，可搜索；此处仅缩短文档导航，不扩充未解析的源码。") if truncated else None
    return files, functions, notice


def render_architecture_markdown(diagrams: list[dict[str, Any]]) -> str:
    lines = [ARCHITECTURE_HEADING, "", "以下图与源码位置已复制到本报告快照；后续重新画图或修改源码不会改变本报告。", "", STATIC_LIMITATION, ""]
    if not diagrams:
        lines.extend(["本次运行没有保存架构图；未借用其他运行或项目的图。纯文档资料可能没有源码图。", ""])
        return "\n".join(lines)
    for diagram in diagrams:
        graph = diagram.get("graph_json") if isinstance(diagram.get("graph_json"), dict) else {}
        lines.extend([f"### {markdown_text(diagram.get('title'))}", "",
            f"- 生成依据：{markdown_text(diagram.get('basis'))}",
            f"- 运行：{markdown_text(diagram.get('run_id'))}；图快照：{markdown_text(diagram.get('id'))}",
            f"- 来源工程：{markdown_text(diagram.get('stats_json', {}).get('root_label') or '未记录')}", ""])
        for note in graph.get("notes", []) if isinstance(graph.get("notes"), list) else []:
            lines.append(f"- {markdown_text(note)}")
        mermaid = text(diagram.get("mermaid_source"))
        fence = "`" * max(3, max((len(match) + 1 for match in re.findall(r"`+", mermaid)), default=3))
        lines.extend(["", f"{fence}mermaid", mermaid, fence, ""])
        nodes = records(graph.get("nodes"))
        if nodes:
            lines.extend(["节点索引：", "", "| 节点 | 源码/目录位置 | 说明 |", "| --- | --- | --- |"])
            lines.extend(
                f"| {markdown_text(node.get('label'))} | {markdown_text(node.get('path'))} | {markdown_text(node.get('description') or '未记录')} |"
                for node in nodes
            )
            lines.append("")
        details = graph.get("details")
        if not isinstance(details, dict):
            continue
        lines.extend(render_source_details_markdown(details))
    return "\n".join(lines).rstrip() + "\n"


def render_source_details_markdown(details: dict[str, Any]) -> list[str]:
    lines = ["#### 源码校验与范围", ""]
    files, functions, notice = report_navigation(details)
    if notice:
        lines.extend([notice, ""])
    for file in files:
        lines.append(
            f"- {markdown_text(file.get('path'))} · {markdown_text(file.get('language'))} · "
            f"{markdown_text(file.get('line_count'))} 行 · SHA-256 {markdown_text(file.get('sha256'))} · "
            f"说明：{markdown_text(file.get('description') or '未记录')}"
        )
    for warning in details.get("warnings", []) if isinstance(details.get("warnings"), list) else []:
        lines.append(f"- 限制/提示：{markdown_text(warning)}")
    if isinstance(details.get("limits"), dict):
        lines.append(f"- 解析预算：{markdown_text(json.dumps(details['limits'], ensure_ascii=False, sort_keys=True))}")
    functions_by_id = {text(function.get("id")): function for function in records(details.get("functions"))}
    lines.extend(["", "#### 函数与语句导航", "", "语句标签来自语法分类，帮助定位阅读；不是对业务目的或实际执行路径的断言。", ""])
    for function in functions:
        path = function.get("path")
        lines.extend([f"##### {markdown_text(function.get('qualified_name') or function.get('name'))}", "",
            f"- 定义位置：{markdown_text(source_location(function))}",
            f"- 参数：{markdown_text(', '.join(text(item) for item in function.get('parameters', [])))}"])
        if function.get("docstring"):
            lines.append(f"- 源码文档注释：{markdown_text(function['docstring'])}")
        entrypoint = function.get("entrypoint")
        if isinstance(entrypoint, dict):
            lines.append(f"- 入口标识：{markdown_text(entrypoint.get('label'))}；依据 {markdown_text(entrypoint.get('kind'))}；置信类别 {markdown_text(entrypoint.get('confidence'))}")
        statements = records(function.get("statements"))
        if statements:
            lines.extend(["", "| 语法分类 | 位置 | 源码摘要 |", "| --- | --- | --- |"])
            for statement in statements:
                lines.append(f"| {markdown_text(statement.get('label') or statement.get('kind'))} | {markdown_text(source_location(statement, path=path))} | {markdown_text(statement.get('excerpt'))} |")
        calls = records(function.get("calls"))
        if calls:
            lines.extend(["", "| 静态调用表达式 | 调用位置 | 解析结果 |", "| --- | --- | --- |"])
            for call in calls:
                result = call_resolution_label(call, functions_by_id)
                result += f"；{text(call.get('reason'))}"
                lines.append(f"| {markdown_text(call.get('expression'))} | {markdown_text(path)}:L{markdown_text(call.get('line'))} | {markdown_text(result)} |")
        lines.append("")
    return lines
