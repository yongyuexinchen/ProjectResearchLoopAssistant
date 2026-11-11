from __future__ import annotations

import re
from copy import deepcopy
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CodebaseMap, Project, Source, SourceSnapshot

# 只读扫描的硬预算：避免在几万文件的大仓库上失控。
MAX_IMPORT_SCAN_FILES = 240
MAX_IMPORT_FILE_BYTES = 128 * 1024
MAX_TOP_MODULES = 12
MAX_CHILD_DIRS = 5
MAX_CHILDREN_OF_ROOT = 6
MAX_FANOUT_EDGES = 20

SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go", ".java", ".rs", ".php", ".rb", ".cs",
}

PY_IMPORT_RE = re.compile(
    r"^[ \t]*(?:from[ \t]+([\w\.]+)[ \t]+import|import[ \t]+([\w\.]+))",
    re.MULTILINE,
)
JS_IMPORT_RE = re.compile(r"""(?:from[ \t]*|require\([ \t]*)['"]([^'"]+)['"]""")

# 分层只是命名启发式：把一级目录归到「输入 / 接口 / 编排 / 领域 / 数据」这类角色上。
LAYER_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("输入与界面", ("app", "apps", "pages", "ui", "components", "web", "frontend", "website", "public", "static", "views", "desktop")),
    ("接口接入", ("api", "routes", "routers", "controllers", "handlers", "endpoints", "grpc", "graphql", "gateway")),
    ("编排调度", ("engine", "graph", "workflow", "orchestrator", "runner", "agent", "workers", "scheduler", "jobs", "cli")),
    ("领域能力", ("services", "core", "domain", "context", "llm", "research", "tools", "verifiers", "reports", "analysis", "packages", "lib", "libs", "python")),
    ("数据与模型", ("db", "models", "migrations", "repositories", "store", "schemas", "storage", "dao", "sql", "database")),
    ("测试与验证", ("tests", "test", "__tests__", "spec", "specs", "benchmarks", "e2e")),
    ("文档与脚本", ("docs", "doc", "scripts", "script", "tools", "examples", "samples", "patches", "vendor", "snapshots", "native")),
)


@dataclass
class GraphNode:
    id: str
    label: str
    path: str
    kind: str
    file_count: int = 0
    entrypoint: bool = False
    description: str = ""


@dataclass
class GraphEdge:
    source: str
    target: str
    label: str = ""
    weight: int = 0


@dataclass
class Graph:
    kind: str
    title: str
    basis: str
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "basis": self.basis,
            "nodes": [node.__dict__ for node in self.nodes],
            "edges": [edge.__dict__ for edge in self.edges],
            "notes": list(self.notes),
            "details": deepcopy(self.details),
        }


def codebase_map_payload(codebase_map: CodebaseMap) -> dict[str, Any]:
    return {
        "id": codebase_map.id,
        "root_label": codebase_map.root_label,
        "tech_stack": list(codebase_map.tech_stack_json or []),
        "dependency_files": list(codebase_map.dependency_files_json or []),
        "config_files": list(codebase_map.config_files_json or []),
        "test_files": list(codebase_map.test_files_json or []),
        "entrypoint_files": list(codebase_map.entrypoint_files_json or []),
        "file_tree": list(codebase_map.file_tree_json or []),
        "metadata": dict(codebase_map.metadata_json or {}),
    }


def resolve_source_root(session: Session, project: Project, source_id: str | None = None) -> Path | None:
    """找到这个项目在磁盘上的真实根目录，用于 import 扫描；找不到就返回 None。"""

    statement = select(Source).where(Source.project_id == project.id)
    if source_id is not None:
        statement = statement.where(Source.id == source_id)
    sources = list(session.scalars(statement).all())
    for source in sources:
        snapshot = session.scalar(
            select(SourceSnapshot)
            .where(SourceSnapshot.source_id == source.id, SourceSnapshot.status == "collected")
            .order_by(SourceSnapshot.created_at.desc())
        )
        candidates: list[str] = []
        if snapshot is not None and snapshot.metadata_json:
            local_path = snapshot.metadata_json.get("local_path")
            if isinstance(local_path, str):
                candidates.append(local_path)
        if isinstance(source.normalized_uri, str) and not source.normalized_uri.lower().startswith("http"):
            candidates.append(source.normalized_uri)
        for candidate in candidates:
            path = Path(candidate).expanduser()
            try:
                if path.is_dir():
                    return path.resolve()
            except OSError:
                continue
    return None


def build_module_map(codebase: dict[str, Any]) -> Graph:
    """纯结构图：只读 file_tree，给出目录层级和文件数量。"""

    file_tree = codebase.get("file_tree") or []
    entrypoints = [str(item) for item in (codebase.get("entrypoint_files") or [])]
    graph = Graph(kind="module_map", title="模块结构图", basis="deterministic:file_tree")
    graph.notes.append("节点来自采集到的目录树，括号内是该目录下的文件数。")
    graph.notes.append("隐藏目录（以 . 开头）已略过，避免 .git/.venv 之类的噪声。")

    file_counts: Counter[str] = Counter()
    dir_paths: set[str] = set()
    for entry in file_tree:
        raw_path = str(entry.get("path") or "").strip("/")
        if not raw_path:
            continue
        parts = raw_path.split("/")
        if parts[0].startswith("."):
            continue
        is_dir = entry.get("kind") == "directory"
        if is_dir:
            dir_paths.add(raw_path)
        depth_limit = len(parts) if is_dir else len(parts) - 1
        for depth in range(1, depth_limit + 1):
            if parts[depth - 1].startswith("."):
                break
            file_counts["/".join(parts[:depth])] += 0 if is_dir else 1

    top_level = sorted(
        (path for path in file_counts if path.count("/") == 0),
        key=lambda path: file_counts[path],
        reverse=True,
    )[:MAX_TOP_MODULES]
    ids: dict[str, str] = {}
    visible_file_count = sum(
        entry.get("kind") == "file" and bool(entry.get("path"))
        and not any(part.startswith(".") for part in str(entry["path"]).strip("/").split("/"))
        for entry in file_tree
    )
    root_label = str(codebase.get("root_label") or "工程根目录")
    graph.nodes.append(GraphNode(id="n_root", label=f"{root_label}（{visible_file_count} 文件）",
                                 path="", kind="root", file_count=visible_file_count,
                                 description="采集到的工程根目录；括号内是参与扫描的文件/目录线索数量。"))
    ids[""] = "n_root"
    if not top_level:
        graph.notes.append("未识别出可展示的子目录，根节点表示采集到的工程根目录。")

    for path in top_level:
        node_id = _node_id("n", path)
        ids[path] = node_id
        graph.nodes.append(
            GraphNode(id=node_id, label=f"{path}（{file_counts[path]} 文件）", path=path, kind="directory", file_count=file_counts[path],
                      description=f"{_module_role(path)}；目录下约 {file_counts[path]} 个文件/目录线索。")
        )
        graph.edges.append(GraphEdge(source="n_root", target=node_id))

    # 只为文件数最多的若干一级目录展开二级目录，避免图过大。
    for parent in top_level[:MAX_CHILDREN_OF_ROOT]:
        children = sorted(
            (path for path in file_counts if path.startswith(parent + "/") and path.count("/") == 1),
            key=lambda path: file_counts[path],
            reverse=True,
        )[:MAX_CHILD_DIRS]
        for child in children:
            node_id = _node_id("n", child)
            if node_id in {node.id for node in graph.nodes}:
                continue
            label = child.split("/")[-1]
            graph.nodes.append(
                GraphNode(id=node_id, label=f"{label}/（{file_counts[child]} 文件）", path=child, kind="directory", file_count=file_counts[child],
                          description=f"{parent} 下的子目录，约 {file_counts[child]} 个文件/目录线索。")
            )
            graph.edges.append(GraphEdge(source=ids[parent], target=node_id))

    for index, entrypoint in enumerate([item for item in entrypoints if not item.startswith(".")][:10]):
        parent_path = entrypoint.rsplit("/", 1)[0] if "/" in entrypoint else ""
        parent_id = ids.get(parent_path) or "n_root"
        node_id = f"n_entry_{index}"
        graph.nodes.append(GraphNode(id=node_id, label=f"▶ {entrypoint}", path=entrypoint, kind="entrypoint", entrypoint=True,
                                     description="采集阶段识别的入口文件线索；从这里开始阅读启动/请求装配。"))
        graph.edges.append(GraphEdge(source=parent_id, target=node_id, label="入口"))
    if entrypoints:
        graph.notes.append("▶ 标记的是采集阶段识别出的入口文件线索。")
    return graph


def build_dependency_flow(root: Path | None, codebase: dict[str, Any]) -> Graph | None:
    """只读 import 扫描，聚合到一级模块之间的依赖流向。"""

    if root is None:
        return None

    file_tree = [entry for entry in (codebase.get("file_tree") or []) if entry.get("kind") == "file"]
    candidates = _select_scan_files(file_tree, {str(item) for item in (codebase.get("entrypoint_files") or [])})
    if not candidates:
        return None

    module_files: Counter[str] = Counter(_top_module(path) for path in candidates)
    total_by_module: Counter[str] = Counter(
        _top_module(str(entry.get("path"))) for entry in file_tree if entry.get("path")
    )
    scanned = 0
    module_of_file: dict[str, str] = {}
    raw_edges: Counter[tuple[str, str]] = Counter()
    for relative in candidates:
        if scanned >= MAX_IMPORT_SCAN_FILES:
            break
        absolute = root / relative
        try:
            if not absolute.is_file() or absolute.stat().st_size > MAX_IMPORT_FILE_BYTES:
                continue
            text = absolute.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        scanned += 1
        source_module = _top_module(relative)
        module_of_file[relative] = source_module
        for imported in _extract_imports(relative, text):
            target_module = _resolve_import_module(relative, imported, set(module_files), root)
            if target_module is None or target_module == source_module:
                continue
            raw_edges[(source_module, target_module)] += 1

    if not raw_edges:
        return None

    graph = Graph(kind="dependency_flow", title="依赖流向图", basis="deterministic:import_scan")
    top_pairs = raw_edges.most_common(MAX_FANOUT_EDGES)
    used = {module for (source, target), _weight in top_pairs for module in (source, target)}
    for module in sorted(used):
        display = "根目录文件" if module == "(根目录)" else f"{module}（{total_by_module.get(module, 0)} 文件）"
        graph.nodes.append(
            GraphNode(id=_node_id("m", module), label=display, path=module, kind="module", file_count=total_by_module.get(module, 0),
                      description=f"{_module_role(module)}；该模块被其他模块 import 引用。")
        )
    graph.edges = [
        GraphEdge(source=_node_id("m", source), target=_node_id("m", target), weight=weight, label=str(weight))
        for (source, target), weight in top_pairs
    ]
    graph.notes.append(
        f"从 {scanned} 个源文件（每个模块最多采样 {max(6, MAX_IMPORT_SCAN_FILES // max(1, len(module_files)))} 个）里读取 import，"
        "聚合为一级模块之间的依赖；边上的数字是引用次数。"
    )
    graph.notes.append("扫描只读、有文件数和体积上限，不解析语法树，因此是近似依赖关系。")
    return graph


def build_data_flow(codebase: dict[str, Any], dependency: Graph | None) -> Graph:
    """分层数据流：按目录命名把一级模块归到角色层，再用依赖边连接层与层。"""

    graph = Graph(kind="data_flow", title="分层数据流图", basis="heuristic:directory_naming")
    module_counts: Counter[str] = Counter()
    for entry in codebase.get("file_tree") or []:
        if entry.get("kind") != "file":
            continue
        path = str(entry.get("path") or "")
        if "/" not in path or path.startswith("."):
            continue
        module_counts[path.split("/", 1)[0]] += 1

    layer_modules: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for module, count in module_counts.items():
        layer_modules[_layer_of(module)].append((module, count))

    layer_ids: dict[str, str] = {}
    for index, (layer, _keywords) in enumerate(LAYER_RULES):
        modules = sorted(layer_modules.get(layer, []), key=lambda item: item[1], reverse=True)
        if not modules:
            continue
        preview = "、".join(name for name, _count in modules[:4])
        node_id = f"L{index}"
        layer_ids[layer] = node_id
        graph.nodes.append(
            GraphNode(id=node_id, label=f"{layer}<br/>{preview}", path=layer, kind="layer", file_count=sum(count for _n, count in modules),
                      description=f"按目录命名归入「{layer}」的模块：{preview}。这是静态分层，不是运行调用链。")
        )

    entrypoints = [str(item) for item in (codebase.get("entrypoint_files") or [])][:3]
    if entrypoints:
        graph.nodes.append(GraphNode(id="L_entry", label="入口文件<br/>" + "<br/>".join(entrypoints), path="", kind="entrypoint", entrypoint=True,
                                     description="采集阶段识别到的入口文件线索，是阅读启动装配的起点。"))

    layer_edges: Counter[tuple[str, str]] = Counter()
    if dependency is not None:
        node_module = {node.id: node.path for node in dependency.nodes}
        for edge in dependency.edges:
            source_layer = _layer_of(node_module.get(edge.source, ""))
            target_layer = _layer_of(node_module.get(edge.target, ""))
            if source_layer == target_layer:
                continue
            layer_edges[(source_layer, target_layer)] += max(1, edge.weight)

    for (source_layer, target_layer), weight in layer_edges.most_common(MAX_FANOUT_EDGES):
        if source_layer in layer_ids and target_layer in layer_ids:
            graph.edges.append(GraphEdge(source=layer_ids[source_layer], target=layer_ids[target_layer], weight=weight, label=str(weight)))
    if layer_edges:
        graph.notes.append("层间连线来自上面的 import 依赖，数字是跨层引用次数。")
    else:
        ordered = [node.path for node in graph.nodes if node.kind == "layer"]
        for left, right in zip(ordered, ordered[1:]):
            graph.edges.append(GraphEdge(source=layer_ids[left], target=layer_ids[right]))
        graph.notes.append("没有可用的 import 依赖，按分层顺序给出示意链路。")

    if entrypoints:
        first_layer = next((node.id for node in graph.nodes if node.kind == "layer"), None)
        if first_layer:
            graph.edges.append(GraphEdge(source="L_entry", target=first_layer, label=""))
    graph.notes.append("分层按目录命名推断（api/engine/services/db 等），是启发式归类，不代表严格调用链。")
    return graph


def _select_scan_files(file_tree: list[dict[str, Any]], entrypoints: set[str]) -> list[str]:
    """按模块轮询分配扫描预算，避免像 scripts/ 这种目录把预算吃光。"""

    by_module: dict[str, list[str]] = defaultdict(list)
    for entry in file_tree:
        path = str(entry.get("path") or "")
        if not path or path.startswith("."):
            continue
        if Path(path).suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        by_module[_top_module(path)].append(path)

    ordered: list[str] = []
    seen: set[str] = set()
    for entrypoint in sorted(entrypoints):
        if Path(entrypoint).suffix.lower() not in SOURCE_EXTENSIONS or entrypoint in seen:
            continue
        seen.add(entrypoint)
        ordered.append(entrypoint)

    quota = max(6, MAX_IMPORT_SCAN_FILES // max(1, len(by_module)))
    for module in sorted(by_module, key=lambda name: len(by_module[name]), reverse=True):
        picked = sorted(by_module[module], key=lambda path: (path.count("/"), len(path)))[:quota]
        for path in picked:
            if path in seen:
                continue
            seen.add(path)
            ordered.append(path)
        if len(ordered) >= MAX_IMPORT_SCAN_FILES:
            break
    return ordered[:MAX_IMPORT_SCAN_FILES]


def _extract_imports(relative: str, text: str) -> list[str]:
    suffix = Path(relative).suffix.lower()
    if suffix == ".py":
        matches = [first or second for first, second in PY_IMPORT_RE.findall(text)]
        return [match for match in matches if match]
    return [match for match in JS_IMPORT_RE.findall(text) if match]


def _resolve_import_module(
    relative: str,
    imported: str,
    known_modules: set[str],
    root: Path,
) -> str | None:
    if imported.startswith("."):
        base = Path(relative).parent
        target = _normalize_relative((base / imported).as_posix())
        head = target.split("/", 1)[0] if "/" in target else target
        return head if head in known_modules else None

    if imported.startswith("@/"):
        head = imported[2:].split("/", 1)[0]
        return head if head in known_modules else None

    candidate = imported.replace("\\", "/").lstrip("@").split("/", 1)[0]
    for probe in (candidate, candidate.replace(".", "-")):
        if probe in known_modules:
            return probe
    # Python 的点分模块：app.engine.x -> app
    dotted = imported.split(".", 1)[0]
    if dotted in known_modules:
        return dotted
    if (root / candidate).is_dir() and candidate in known_modules:
        return candidate
    return None


def _normalize_relative(path: str) -> str:
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _top_module(relative: str) -> str:
    return relative.split("/", 1)[0] if "/" in relative else "(根目录)"


def _layer_of(module: str) -> str:
    lowered = module.lower().lstrip(".")
    for layer, keywords in LAYER_RULES:
        if any(keyword in lowered for keyword in keywords):
            return layer
    return "其他模块"


def _module_role(module: str) -> str:
    first = module.split("/", 1)[0].lower()
    if first in {"src", "source"}:
        return "源码根目录"
    if first in {"server", "serverless", "convex"}:
        return "服务端代码"
    if first in {"sdk", "client", "clients"}:
        return "客户端 SDK"
    if any(token in first for token in ("shared", "common", "utils", "helpers")):
        return "共享工具"
    if first in {"proto", "protos", "idl"} or "proto" in first:
        return "协议/接口定义"
    if first.endswith("-site") or first.endswith("web") or first.endswith("frontend"):
        return "站点/前端"
    return _layer_of(first)


def _node_id(prefix: str, value: str) -> str:
    """Mermaid 的节点 id 只能是字母数字下划线，路径必须转义。"""

    slug = re.sub(r"[^0-9A-Za-z]+", "_", value).strip("_")[:40]
    return f"{prefix}_{slug}" if slug else f"{prefix}_node"
