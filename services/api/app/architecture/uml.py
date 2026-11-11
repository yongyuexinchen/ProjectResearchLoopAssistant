"""UML 图集生成器。

用确定性的方式产出组件图、类图与时序图：
- 组件图：复用 import 扫描结果，把一级模块当作 «component»；
- 类图：Python 用 ast 解析真实类/继承/方法，JS/TS 用正则近似；
- 时序图：从入口模块出发，按依赖权重排一条主链路。
不调用 LLM，也不执行被分析代码。
"""

from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.architecture.graph_builder import Graph, GraphEdge, GraphNode, _node_id, _select_scan_files, _top_module

MAX_CLASS_FILES = 120
MAX_CLASSES = 36
MAX_METHODS_PER_CLASS = 8
MAX_FILE_BYTES = 128 * 1024

JS_CLASS_RE = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)(?:\s+extends\s+([A-Za-z_$][\w$.]*))?", re.MULTILINE)
JS_METHOD_RE = re.compile(r"^[ \t]{2,}(?:static\s+|async\s+|get\s+|set\s+)*(#?[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{", re.MULTILINE)


def build_component_diagram(dependency: Graph | None) -> Graph | None:
    """组件图：模块 = 组件，import 依赖 = «use» 关系。"""

    if dependency is None or not dependency.nodes:
        return None

    graph = Graph(kind="uml_component", title="组件图（UML）", basis="deterministic:import_scan")
    kept: set[str] = set()
    for node in dependency.nodes:
        # 根目录散落文件不是组件，画进去只会干扰阅读。
        if node.path == "(根目录)":
            continue
        kept.add(node.id)
        graph.nodes.append(
            GraphNode(id=node.id, label=node.label, path=node.path, kind="component", file_count=node.file_count,
                      description=getattr(node, "description", "") or f"一级模块构件；路径 {node.path or '根目录'}。")
        )
    for edge in dependency.edges:
        if edge.source in kept and edge.target in kept:
            graph.edges.append(GraphEdge(source=edge.source, target=edge.target, label=edge.label, weight=edge.weight))
    if not graph.nodes:
        return None
    graph.notes.append("每个组件对应一个一级模块，虚线箭头表示 import 依赖，数字是引用次数。")
    graph.notes.append("UML 语义：«component» 构件 + dependency 依赖关系；不代表进程或部署单元。")
    return graph


def build_class_diagram(root: Path | None, codebase: dict[str, Any]) -> Graph | None:
    """类图：解析 Python 类（ast）与 JS/TS 类（正则），给出类、继承与主要方法。"""

    if root is None:
        return None

    file_tree = [entry for entry in (codebase.get("file_tree") or []) if entry.get("kind") == "file"]
    candidates = _select_scan_files(file_tree, set())
    if not candidates:
        return None

    classes: list[dict[str, Any]] = []
    scanned = 0
    for relative in candidates:
        if scanned >= MAX_CLASS_FILES or len(classes) >= MAX_CLASSES:
            break
        suffix = Path(relative).suffix.lower()
        if suffix not in {".py", ".js", ".jsx", ".ts", ".tsx"}:
            continue
        absolute = root / relative
        try:
            if not absolute.is_file() or absolute.stat().st_size > MAX_FILE_BYTES:
                continue
            text = absolute.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        scanned += 1
        if suffix == ".py":
            classes.extend(_python_classes(relative, text))
        else:
            classes.extend(_js_classes(relative, text))
        if len(classes) > MAX_CLASSES * 2:
            break

    if not classes:
        return None

    classes = classes[:MAX_CLASSES]
    graph = Graph(kind="uml_class", title="类图（UML）", basis="deterministic:ast + regex")
    class_ids = {
        (item["path"], item["name"]): _node_id("c", f"{item['path']}::{item['name']}")
        for item in classes
    }
    for item in classes:
        node_id = class_ids[(item["path"], item["name"])]
        graph.nodes.append(
            GraphNode(
                id=node_id,
                label=item["name"],
                path=item["path"],
                kind="class",
                file_count=len(item["methods"]),
                description=_class_description(item),
            )
        )
        graph.nodes[-1].__dict__["methods"] = item["methods"]
        graph.nodes[-1].__dict__["bases"] = item["bases"]
        graph.nodes[-1].__dict__["language"] = item["language"]

    by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for item in classes:
        by_name[item["name"]].append((item["path"], item["name"]))
    for item in classes:
        for base in item["bases"]:
            simple = base.split(".")[-1]
            candidates = by_name.get(simple, [])
            if len(candidates) != 1:
                # A short-name-only inheritance lookup is ambiguous across files.
                continue
            target = class_ids[candidates[0]]
            source = class_ids[(item["path"], item["name"])]
            if target != source:
                graph.edges.append(GraphEdge(source=target, target=source, label="extends"))

    graph.notes.append(f"扫描 {scanned} 个源文件，取前 {len(classes)} 个类；实线三角箭头是继承（extends）。")
    graph.notes.append("Python 用 ast 解析，JS/TS 用正则近似，动态特性（mixin、装饰器注入）不在图里。")
    if len(classes) >= MAX_CLASSES:
        graph.notes.append(f"类数量已截断到 {MAX_CLASSES} 个，避免图不可读。")
    return graph


def build_sequence_diagram(codebase: dict[str, Any], dependency: Graph | None) -> Graph | None:
    """时序图：从入口模块出发，按依赖权重展开一条主调用链。"""

    if dependency is None or not dependency.nodes:
        return None

    edges = sorted(dependency.edges, key=lambda edge: edge.weight, reverse=True)
    if not edges:
        return None

    entry_modules = [str(item).split("/", 1)[0] for item in (codebase.get("entrypoint_files") or [])]
    entry_counter = Counter(module for module in entry_modules if module)
    start = entry_counter.most_common(1)[0][0] if entry_counter else None
    if start is None:
        start = _top_module_of_id(edges[0].source, dependency)

    graph = Graph(kind="uml_sequence", title="时序图（UML）", basis="heuristic:import_order")
    graph.nodes.append(GraphNode(id="actor", label="调用方", path="", kind="actor",
                                 description="外部调用方；本次只按 import 依赖画静态主链路，不代表真实请求。"))
    seen: list[str] = [start]
    graph.nodes.append(GraphNode(id=_node_id("s", start), label=start, path=start, kind="participant",
                                 description=f"入口模块「{start}」；时序来自 import 依赖权重排序，不是运行追踪。"))

    # 相邻关系：source 模块 -> [target 模块]
    adjacency: dict[str, list[str]] = defaultdict(list)
    weight_to: dict[str, int] = {}
    for edge in edges:
        source = _top_module_of_id(edge.source, dependency)
        target = _top_module_of_id(edge.target, dependency)
        if not source or not target or source == target:
            continue
        if target not in adjacency[source]:
            adjacency[source].append(target)
        weight_to[target] = weight_to.get(target, 0) + max(1, edge.weight)

    ordered_targets: list[str] = []

    def collect_from(module: str) -> None:
        for target in adjacency.get(module, []):
            if target == start or target in ordered_targets:
                continue
            ordered_targets.append(target)
            if len(ordered_targets) >= 4:
                return

    collect_from(start)
    # 一层不够就顺着下游再走一跳，让时序图至少有三四个参与者。
    if len(ordered_targets) < 2:
        for first in list(ordered_targets):
            collect_from(first)
            if len(ordered_targets) >= 4:
                break

    for target in ordered_targets:
        graph.nodes.append(GraphNode(id=_node_id("s", target), label=target, path=target, kind="participant",
                                     description=f"下游模块「{target}」；按 import 依赖权重进入主链路。"))
        seen.append(target)

    graph.edges.append(GraphEdge(source="actor", target=_node_id("s", start), label="触发入口"))
    for target in ordered_targets:
        graph.edges.append(
            GraphEdge(source=_node_id("s", start), target=_node_id("s", target), label=f"依赖 {weight_to.get(target, 1)} 次")
        )

    graph.notes.append("参与者是一级模块，消息来自 import 依赖的权重排序，属于静态近似，不含运行时参数与返回。")
    graph.notes.append("真实调用会有分支与异步，这里只给一条主链路的骨架，用来快速建立阅读顺序。")
    return graph


def _top_module_of_id(node_id: str, dependency: Graph) -> str | None:
    for node in dependency.nodes:
        if node.id == node_id:
            return node.path
    return None


def _class_description(item: dict[str, Any]) -> str:
    location = f"文件 {item.get('path') or '未记录'}；"
    docstring = str(item.get("docstring") or "").strip()
    if docstring:
        return location + docstring.splitlines()[0][:160]
    methods = item.get("methods") or []
    bases = item.get("bases") or []
    facts = []
    if bases:
        facts.append("继承自 " + "、".join(str(base) for base in bases[:3]))
    if methods:
        facts.append("包含方法：" + "、".join(str(method) for method in methods[:5]))
    return location + ("；".join(facts) if facts else "未提取到类注释或方法，需结合源码人工确认职责。")


def _python_classes(relative: str, text: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    results: list[dict[str, Any]] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = [_base_name(base) for base in node.bases]
        methods = [
            child.name
            for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("__")
        ][:MAX_METHODS_PER_CLASS]
        results.append(
            {
                "name": node.name,
                "path": relative,
                "bases": [base for base in bases if base],
                "methods": methods,
                "language": "python",
                "docstring": (ast.get_docstring(node) or "").strip(),
            }
        )
    return results


def _js_classes(relative: str, text: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for match in JS_CLASS_RE.finditer(text):
        name = match.group(1)
        base = match.group(2) or ""
        body_start = match.end()
        body_end = min(len(text), body_start + 8000)
        methods = [
            method.group(1)
            for method in JS_METHOD_RE.finditer(text[body_start:body_end])
            if method.group(1) not in {"constructor", "if", "for", "while", "switch", "catch"}
        ][:MAX_METHODS_PER_CLASS]
        results.append(
            {
                "name": name,
                "path": relative,
                "bases": [base] if base else [],
                "methods": methods,
                "language": "js",
                "docstring": "",
            }
        )
    return results


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""
