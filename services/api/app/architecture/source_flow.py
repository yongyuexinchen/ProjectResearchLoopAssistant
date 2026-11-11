"""Bounded, read-only source index and source-positioned static call-reference graph.

Resolved edges identify declarations referenced by syntax, never runtime dispatch,
request order, data lineage or proof that a branch executes.
"""
from __future__ import annotations

from collections import Counter, deque
from hashlib import sha256
import os
import posixpath
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
from typing import Any

from app.architecture.graph_builder import Graph, GraphEdge, GraphNode
from app.architecture.source_common import Binding, Budget, ParsedFile, Scope
from app.architecture.source_python import parse_python
from app.architecture.source_javascript import parse_javascript
from app.tools.path_policy import should_skip_path

MAX_SOURCE_FILES = 500
MAX_FILE_BYTES = 384 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_FUNCTIONS = 2400
MAX_CALLS = 12000
MAX_STATEMENTS = 24000
MAX_GRAPH_NODES = 80
MAX_GRAPH_EDGES = 240
MAX_GRAPH_ENTRYPOINTS = 16
MAX_SYNTAX_NODES = 100000
MAX_FILE_TREE_ENTRIES = 50000
MAX_WARNINGS = 100

LANGUAGES = {".py": "python", ".js": "javascript", ".jsx": "javascript",
             ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript",
             ".tsx": "tsx", ".mts": "typescript", ".cts": "typescript"}

CORE_PATH_PARTS = {"src", "app", "apps", "lib", "components", "server", "backend", "services", "packages"}
AUXILIARY_PATH_PARTS = {"tests", "test", "__tests__", "scratch", "scripts", "tools", "examples", "demo", "docs", "fixtures"}
ENTRY_FILENAMES = {"main.py", "app.py", "server.py", "manage.py", "wsgi.py", "asgi.py", "index.js", "index.jsx",
                   "index.ts", "index.tsx", "main.js", "main.jsx", "main.ts", "main.tsx"}
NEXT_ENTRY_FILENAMES = {"page.js", "page.jsx", "page.ts", "page.tsx", "layout.js", "layout.jsx", "layout.ts",
                        "layout.tsx", "route.js", "route.ts", "middleware.js", "middleware.ts"}
CONFIG_PREFIXES = ("next.config.", "vite.config.", "vitest.config.", "eslint.config.", "postcss.config.",
                   "tailwind.config.", "jest.config.", "playwright.config.", "webpack.config.", "rollup.config.")


def _infer_entrypoints(file_tree: list[Any]) -> set[str]:
    """Infer conventional entry files when the older scan produced no entrypoint list."""

    entries = set()
    for item in file_tree:
        if not isinstance(item, dict) or item.get("kind", "file") != "file":
            continue
        path = str(item.get("path") or "").replace("\\", "/")
        name = PurePosixPath(path).name.lower()
        parts = set(PurePosixPath(path).parts)
        if parts & AUXILIARY_PATH_PARTS:
            continue
        if name in ENTRY_FILENAMES:
            entries.add(path)
        elif name in NEXT_ENTRY_FILENAMES and (
            "app" in parts or "pages" in parts
            or (name.startswith("middleware.") and len(PurePosixPath(path).parts) <= 2)
        ):
            entries.add(path)
    return entries


def _is_config_or_declaration(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return (name.startswith(CONFIG_PREFIXES) or name in {"tsconfig.json", "package.json", "package-lock.json"}
            or name.endswith(".d.ts"))


def _source_priority(path: str, entrypoints: set[str]) -> int:
    if path in entrypoints:
        return 0
    parts = set(PurePosixPath(path).parts)
    if parts & AUXILIARY_PATH_PARTS:
        return 4
    if parts & CORE_PATH_PARTS:
        return 1
    return 2


def _linked(path: Path) -> bool:
    info = path.lstat()
    # Windows junctions/reparse points are not always reported as is_symlink().
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _safe_path(root: Path, relative: str) -> tuple[Path | None, str]:
    normalized = relative.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if (not normalized or not parts or PurePosixPath(normalized).is_absolute()
            or PureWindowsPath(relative).drive or ".." in parts or ":" in normalized):
        return None, "unsafe relative path"
    target = root.joinpath(*parts)
    try:
        current = root
        for part in parts:
            current = current / part
            if _linked(current):
                return None, "symlink/junction path"
        if not target.resolve().is_relative_to(root):
            return None, "path escapes source root"
        decision = should_skip_path(target, root, MAX_FILE_BYTES)
        if decision:
            return None, decision["reason"]
        if not target.is_file():
            return None, "not a regular source file"
    except (OSError, ValueError):
        return None, "unreadable source path"
    return target, ""


def _python_module(origin: str, spec: str, files: dict[str, ParsedFile]) -> str | None:
    if spec.startswith("."):
        level = len(spec) - len(spec.lstrip("."))
        parent = list(PurePosixPath(origin).parent.parts)
        if parent == ["."]:
            parent = []
        package_depth = 0
        for depth in range(len(parent), 0, -1):
            if "/".join(parent[:depth]) + "/__init__.py" not in files:
                break
            package_depth += 1
        if level > package_depth:
            return None
        base = parent[:len(parent) - level + 1]
        rest = spec[level:].split(".") if spec[level:] else []
        stem = "/".join([*base, *rest])
        candidates = [f"{stem}.py", f"{stem}/__init__.py"] if stem else ["__init__.py"]
        found = [candidate for candidate in candidates if candidate in files]
        return found[0] if len(found) == 1 else None
    pieces = spec.split(".")
    if not all(piece.isidentifier() for piece in pieces):
        return None
    stem = "/".join(pieces)
    suffixes = [f"{stem}.py", f"{stem}/__init__.py"]
    found = set()
    for path in files:
        for suffix in suffixes:
            if path == suffix:
                found.add(path)
            elif path.endswith("/" + suffix):
                # Explicit __init__.py package chains allow monorepo source roots.
                prefix = path[:-len(suffix)]
                package_count = len(pieces) if suffix.endswith("/__init__.py") else len(pieces) - 1
                if package_count and all(
                    prefix + "/".join(pieces[:depth]) + "/__init__.py" in files
                    for depth in range(1, package_count + 1)
                ):
                    found.add(path)
    return next(iter(found)) if len(found) == 1 else None


def _javascript_module(origin: str, spec: str, files: dict[str, ParsedFile]) -> str | None:
    # Aliases, packages, Node resolution rules and tsconfig paths are not guessed.
    if not spec.startswith(("./", "../")) or "\\" in spec:
        return None
    base = posixpath.normpath(posixpath.join(posixpath.dirname(origin), spec))
    if base.startswith("../") or base == ".." or base.startswith("/"):
        return None
    if base in files:
        return base
    if PurePosixPath(base).suffix:
        return None
    candidates = [base + ext for ext in LANGUAGES if ext != ".py"]
    candidates.extend(base + "/index" + ext for ext in LANGUAGES if ext != ".py")
    found = [candidate for candidate in candidates if candidate in files]
    return found[0] if len(found) == 1 else None


def _resolve_calls(parsed_files: list[ParsedFile]) -> None:
    files = {parsed.path: parsed for parsed in parsed_files}
    functions = {fn.data["id"]: fn for parsed in parsed_files for fn in parsed.functions}
    module_cache = {}

    def module_path(origin, spec):
        key = (origin.path, spec)
        if key not in module_cache:
            module_cache[key] = (_python_module(origin.path, spec, files) if origin.language == "python"
                                 else _javascript_module(origin.path, spec, files))
        return module_cache[key]

    def resolve_binding(binding, rest, seen):
        if binding is None or len(seen) > 24:
            return None
        key = (id(binding), tuple(rest))
        if key in seen:
            return None
        seen = {*seen, key}
        if binding.kind == "function":
            return binding.value if not rest and binding.value in functions else None
        if binding.kind == "alias":
            scope, alias_parts = binding.value
            if not alias_parts:
                return None
            return resolve_binding(scope.lookup(alias_parts[0]), [*alias_parts[1:], *rest], seen)
        if binding.kind == "receiver":
            cls = binding.value
            if cls.dynamic_class or len(rest) != 1 or rest[0] in cls.blocked_members:
                return None
            return resolve_binding(cls.bindings.get(rest[0]), [], seen)
        if binding.kind in {"import", "module"}:
            origin = files.get(binding.origin)
            if origin is None:
                return None
            members = ([binding.member] if binding.kind == "import" else []) + rest
            return resolve_module_members(origin, binding.value, members, seen)
        return None

    def resolve_module_members(origin, spec, members, seen):
        path = module_path(origin, spec)
        target = files.get(path) if path else None
        if target and members:
            bindings = target.scope.bindings if target.language == "python" else target.exports
            if target.language == "python" and "*" in bindings:
                return None
            first = members[0]
            if first in bindings:
                return resolve_binding(bindings[first], members[1:], seen)
        # Python package.submodule may not be explicitly re-exported by __init__.py.
        if origin.language == "python" and members and target and target.path.endswith("/__init__.py"):
            extension = spec + ("" if spec.endswith(".") else ".") + members[0]
            if module_path(origin, extension):
                return resolve_module_members(origin, extension, members[1:], seen)
        return None

    for parsed in parsed_files:
        for function in parsed.functions:
            for data, parts in function.raw_calls:
                if not parts:
                    data["reason"] = "动态表达式、下标调用或构造调用；未猜测目标"
                    continue
                binding = function.scope.lookup(parts[0])
                target = resolve_binding(binding, parts[1:], set())
                if target:
                    data.update(target_id=target, resolution="resolved",
                                reason="词法绑定及本地声明对应的静态调用引用；不是运行时执行证明")
                    if any(start <= data["line"] <= end for start, end in function.guard_ranges):
                        target_data = functions[target].data
                        if target_data.get("entrypoint") is None or target_data["entrypoint"].get("confidence") == "candidate":
                            target_data["entrypoint"] = {
                                "kind": "main_guard", "label": "main guard 中直接引用的函数",
                                "line": data["line"], "confidence": "syntax",
                            }
                else:
                    data["reason"] = (
                        "名称被参数/赋值遮蔽，或是外部/动态绑定" if binding is None else
                        "导入/导出目标不在已解析范围内、存在歧义，或动态接收者不能证明"
                    )


def _describe_function(fn: dict) -> str:
    docstring = str(fn.get("docstring") or "").strip()
    if docstring:
        return docstring.splitlines()[0][:180]
    if fn.get("synthetic"):
        statements = fn.get("statements") or []
        if statements:
            first = statements[0]
            excerpt = str(first.get("excerpt") or "").strip().splitlines()[0][:100]
            return f"文件顶层执行语句；首段：{first.get('label') or first.get('kind')}；{excerpt}"
        return "文件顶层执行语句；不是独立函数。"
    statements = fn.get("statements") or []
    if statements:
        first = statements[0]
        excerpt = str(first.get("excerpt") or "").strip().splitlines()[0][:100]
        return f"语法流程首段：{first.get('label') or first.get('kind')}；{excerpt}"
    kind = "方法" if fn.get("kind") == "method" else "函数"
    return f"{kind}；未提取到 docstring 或语句摘要。"


def _describe_file(parsed: ParsedFile, path: str) -> str:
    docstring = str(parsed.module_docstring or "").strip()
    if docstring:
        return docstring.splitlines()[0][:180]
    name = PurePosixPath(path).name.lower()
    functions = [fn.data.get("qualified_name") or fn.data.get("name") for fn in parsed.functions]
    if name in {"page.tsx", "page.ts", "page.jsx", "page.js", "layout.tsx", "layout.ts", "route.ts", "route.js"}:
        return f"Next.js 路由/页面文件；包含 {len(functions)} 个函数或组件。"
    if functions:
        preview = "、".join(str(item) for item in functions[:4])
        return f"源码文件；包含 {len(functions)} 个函数/方法：{preview}{' 等' if len(functions) > 4 else ''}。"
    return "未提取到函数或注释；可能是配置、数据或纯类型声明文件。"


def _canvas(functions: list[dict], warnings: list[str]) -> tuple[list[GraphNode], list[GraphEdge]]:
    by_id = {fn["id"]: fn for fn in functions}
    adjacency = {fn["id"]: [c for c in fn["calls"] if c["target_id"] in by_id] for fn in functions}
    incoming = Counter(call["target_id"] for calls in adjacency.values() for call in calls)
    priorities = {"main_guard": 0, "entry_file": 1, "http_decorator": 2, "exported_handler": 2}
    entries = sorted((fn for fn in functions if fn["entrypoint"]), key=lambda fn: (
        priorities.get(fn["entrypoint"]["kind"], 3), fn["name"] != "main", fn["path"], fn["line_start"],
    ))
    roots = entries or sorted((fn for fn in functions if not incoming[fn["id"]]), key=lambda fn: (
        fn["kind"] == "module", fn["path"], fn["line_start"],
    )) or functions
    seeds = roots[:MAX_GRAPH_ENTRYPOINTS]
    queue = deque(fn["id"] for fn in seeds)
    visible = []
    seen = set()
    while queue and len(visible) < MAX_GRAPH_NODES:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        visible.append(by_id[current])
        queue.extend(c["target_id"] for c in adjacency[current] if c["target_id"] not in seen)
    nodes = [GraphNode(id=fn["id"],
                       label=f'{fn["qualified_name"]}<br/>{fn["path"]}:L{fn["line_start"]}-L{fn["line_end"]}',
                       path=fn["path"], kind="entrypoint" if fn["entrypoint"] else "function",
                       entrypoint=bool(fn["entrypoint"]),
                       description=_describe_function(fn)) for fn in visible]
    edges = []
    for fn in visible:
        for reference in adjacency[fn["id"]]:
            if reference["target_id"] in seen:
                if len(edges) >= MAX_GRAPH_EDGES:
                    break
                edges.append(GraphEdge(source=fn["id"], target=reference["target_id"],
                                       label=f'L{reference["line"]}', weight=1))
    if len(nodes) < len(functions):
        warnings.append(f"画布只展示入口邻域 {len(nodes)}/{len(functions)} 个节点；其余已解析函数保留在明细索引。")
    if sum(1 for fn in visible for call in adjacency[fn["id"]] if call["target_id"] in seen) > len(edges):
        warnings.append("画布调用边达到预算；明细中仍保留有预算的调用位置。")
    return nodes, edges


def build_source_flow(root: Path | None, codebase: dict) -> Graph | None:
    if root is None:
        return None
    warnings: list[str] = []
    graph = Graph(kind="source_flow", title="源码函数与调用位置", basis="static:source_ast")
    limits = {
        "max_files": MAX_SOURCE_FILES, "max_file_bytes": MAX_FILE_BYTES,
        "max_total_bytes": MAX_TOTAL_BYTES, "max_functions": MAX_FUNCTIONS,
        "max_calls": MAX_CALLS, "max_statements": MAX_STATEMENTS,
        "max_graph_nodes": MAX_GRAPH_NODES, "max_graph_edges": MAX_GRAPH_EDGES,
        "max_syntax_nodes_per_file": MAX_SYNTAX_NODES, "max_file_tree_entries": MAX_FILE_TREE_ENTRIES,
    }
    budget = Budget({"functions": MAX_FUNCTIONS, "calls": MAX_CALLS, "statements": MAX_STATEMENTS})
    parsed_files = []
    file_details = []
    stats = {"candidate_files": 0, "excluded_files": 0, "unsupported_files": 0,
             "parse_errors": 0, "scanned_bytes": 0, "truncated": False}

    def warn(message):
        if len(warnings) < MAX_WARNINGS:
            warnings.append(message[:300])

    source_root = Path(os.path.abspath(root.expanduser()))
    unsafe_root = False
    try:
        for ancestor in [*reversed(source_root.parents), source_root]:
            if _linked(ancestor):
                unsafe_root = True
                warn("源码根目录或祖先是符号链接/junction；未读取源码。")
                break
        source_root = source_root.resolve()
        if not source_root.is_dir():
            unsafe_root = True
            warn("源码根目录不存在或不是目录；未读取源码。")
    except OSError:
        unsafe_root = True
        warn("源码根目录不可读取。")

    entrypoints = {str(path).replace("\\", "/") for path in codebase.get("entrypoint_files") or []}
    entrypoints.update(_infer_entrypoints(codebase.get("file_tree") or []))
    candidates = set()
    if not unsafe_root:
        for position, item in enumerate(codebase.get("file_tree") or []):
            if position >= MAX_FILE_TREE_ENTRIES:
                stats["truncated"] = True
                warn("file_tree entry budget reached；未检查其余路径。")
                break
            if not isinstance(item, dict) or item.get("kind", "file") != "file":
                continue
            relative = str(item.get("path") or "")
            suffix = PurePosixPath(relative.replace("\\", "/")).suffix.lower()
            if suffix not in LANGUAGES:
                stats["unsupported_files"] += 1
                continue
            if _is_config_or_declaration(relative):
                stats["excluded_files"] += 1
                continue
            candidates.add(relative)
        stats["candidate_files"] = len(candidates)
        ordered = sorted(candidates, key=lambda path: (
            _source_priority(path.replace("\\", "/"), entrypoints),
            len(PurePosixPath(path).parts), path,
        ))
        attempted = 0
        indexed_paths = set()
        for relative in ordered:
            if attempted >= MAX_SOURCE_FILES:
                stats["truncated"] = True
                warn("source file count budget reached；其余文件未解析。")
                break
            absolute, reason = _safe_path(source_root, relative)
            if absolute is None:
                if reason == "large_file":
                    stats["truncated"] = True
                stats["excluded_files"] += 1
                warn(f"{relative}: skipped ({reason})")
                continue
            normalized = absolute.relative_to(source_root).as_posix()
            if normalized in indexed_paths:
                continue
            indexed_paths.add(normalized)
            remaining = MAX_TOTAL_BYTES - stats["scanned_bytes"]
            try:
                size = absolute.stat().st_size
                if size > remaining:
                    stats["truncated"] = True
                    warn(f"{normalized}: total source byte budget reached")
                    continue
                # Limit the actual read as well as stat, including a concurrently growing file.
                with absolute.open("rb") as stream:
                    data = stream.read(min(MAX_FILE_BYTES, remaining) + 1)
                if len(data) > min(MAX_FILE_BYTES, remaining):
                    stats["truncated"] = True
                    warn(f"{normalized}: source byte budget exceeded while reading")
                    continue
            except OSError:
                warn(f"{normalized}: read failed")
                continue
            attempted += 1
            stats["scanned_bytes"] += len(data)
            language = LANGUAGES[absolute.suffix.lower()]
            descriptor = {"path": normalized, "language": language, "sha256": sha256(data).hexdigest(),
                          "line_count": data.count(b"\n") + (bool(data) and not data.endswith(b"\n"))}
            file_details.append(descriptor)
            try:
                if language == "python":
                    # utf-8-sig removes only BOM, preserving all actual source line positions.
                    parsed = parse_python(normalized, data.decode("utf-8-sig"), budget,
                                          normalized in entrypoints, MAX_SYNTAX_NODES)
                else:
                    parsed = parse_javascript(normalized, data, language, budget,
                                              normalized in entrypoints, MAX_SYNTAX_NODES)
                parsed_files.append(parsed)
                descriptor["description"] = _describe_file(parsed, normalized)
                if parsed.has_errors:
                    stats["parse_errors"] += 1
                    descriptor["parse_error"] = True
                    warn(f"{normalized}: 语法树含错误/缺失节点；保留可恢复的函数，动态或损坏部分未解析")
            except (SyntaxError, UnicodeError, ValueError, RecursionError, MemoryError) as exc:
                stats["parse_errors"] += 1
                descriptor["parse_error"] = True
                descriptor["description"] = "源码解析失败；未提取函数或类说明，需人工查看原始文件。"
                warn(f"{normalized}: parse failed ({type(exc).__name__}: {str(exc)[:100]})")

    if stats["unsupported_files"]:
        warn(f'{stats["unsupported_files"]} 个非 Python/JS/TS/TSX 文件未做精细语法解析。')
    for kind in sorted(budget.exhausted):
        stats["truncated"] = True
        warn(f"{kind} index budget reached；未收录项不参与调用解析。")
    _resolve_calls(parsed_files)
    functions = [fn.data for parsed in parsed_files for fn in parsed.functions]
    graph.nodes, graph.edges = _canvas(functions, warnings)
    if not graph.nodes:
        graph.nodes = [GraphNode(id="source_info", label="没有可展示的已解析函数<br/>请查看解析范围与限制", path="", kind="source_info")]
    stats.update(file_count=len(file_details), function_count=len(functions),
                 call_count=sum(len(fn["calls"]) for fn in functions),
                 statement_count=sum(len(fn["statements"]) for fn in functions),
                 resolved_calls=sum(c["target_id"] is not None for fn in functions for c in fn["calls"]),
                 unresolved_calls=sum(c["target_id"] is None for fn in functions for c in fn["calls"]),
                 graph_nodes=len(graph.nodes), graph_edges=len(graph.edges),
                 omitted_canvas_functions=max(0, len(functions) - sum(node.kind != "source_info" for node in graph.nodes)))
    if stats["omitted_canvas_functions"]:
        stats["truncated"] = True
    graph.details = {"version": 1, "files": file_details, "functions": functions,
                     "stats": stats, "limits": limits, "warnings": warnings[:MAX_WARNINGS]}
    graph.notes = [
        "基于本次读取源码的 Python AST / Tree-sitter JS/TS/TSX 静态索引；不执行源码。",
        "节点是声明，边是可对应本地声明的调用引用；L 为真实调用行，不代表运行顺序或数据血缘。",
        "动态分派、外部依赖、未配置的路径别名与有歧义的绑定保留为未解析，不按同名猜测。",
        "line 为 1-based；column 为 0-based UTF-8 字节列。文件 SHA-256 绑定本次读取内容。",
        *graph.details["warnings"][:12],
    ]
    return graph
