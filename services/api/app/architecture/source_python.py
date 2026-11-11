"""Python syntax indexing with lexical bindings and no input-code execution."""
from __future__ import annotations

import ast

from app.architecture.source_common import (
    Binding, Budget, Function, ParsedFile, Scope, call, entry, new_function, statement,
)


def parse_python(path: str, source: str, budget: Budget, entry_file: bool,
                 max_syntax_nodes: int) -> ParsedFile:
    tree = ast.parse(source, filename=path)
    if sum(1 for _ in ast.walk(tree)) > max_syntax_nodes:
        raise ValueError("syntax-node budget exceeded")
    parsed = ParsedFile(path, "python", Scope("module"))
    lines = source.splitlines()
    utf8_lines = [line.encode("utf-8") for line in lines]

    def excerpt(node):
        return "\n".join(lines[node.lineno - 1:min(getattr(node, "end_lineno", node.lineno), node.lineno + 4)])[:240]

    def expression(node):
        start, end = node.lineno - 1, node.end_lineno - 1
        if start == end:
            return utf8_lines[start][node.col_offset:node.end_col_offset].decode("utf-8")
        chunks = [utf8_lines[start][node.col_offset:]]
        for position in range(start + 1, min(end + 1, start + 5)):
            chunks.append(utf8_lines[position][:node.end_col_offset] if position == end else utf8_lines[position])
        return b"\n".join(chunks)[:720].decode("utf-8", errors="replace")

    def parts(node):
        if isinstance(node, ast.Name):
            return [node.id]
        if isinstance(node, ast.Attribute):
            base = parts(node.value)
            return [*base, node.attr] if base else None
        return None

    def params(node):
        args = node.args
        return [arg.arg for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]] + (
            [args.vararg.arg] if args.vararg else []) + ([args.kwarg.arg] if args.kwarg else [])

    def visit_body(nodes, scope, qualified="", owner=None, current_class=None):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qname = f"{qualified}.{node.name}" if qualified else node.name
                # Python methods do not lexically inherit their class namespace.
                lexical_parent = scope.parent if scope.kind == "class" else scope
                child = Scope("function", lexical_parent, class_scope=current_class)
                parameter_names = params(node)
                for name in parameter_names:
                    child.bind(name, None)
                decorators = [ast.unparse(d) for d in node.decorator_list]
                if scope.kind == "class" and current_class and parameter_names and parameter_names[0] == "self" and not any(
                    d == "staticmethod" for d in decorators
                ):
                    child.bindings["self"] = Binding("receiver", current_class)
                marker = None
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr in {
                        "get", "post", "put", "delete", "patch", "route", "websocket", "options", "head"
                    }:
                        marker = entry("http_decorator", "装饰器语法候选：" + ast.unparse(decorator),
                                       decorator.lineno, candidate=True)
                        break
                if marker is None and entry_file and scope.kind == "module" and node.name in {
                    "main", "app", "create_app", "run", "start"
                }:
                    marker = entry("entry_file", "入口文件中的主函数候选", node.lineno, candidate=True)
                fn = new_function(parsed, child, budget, name=node.name, qualified_name=qname,
                                  line=node.lineno, end=node.end_lineno, column=node.col_offset,
                                  parameters=parameter_names, docstring=ast.get_docstring(node) or "",
                                  entrypoint=marker, kind="method" if scope.kind == "class" else "function")
                scope.bind(node.name, Binding("function", fn.data["id"]) if fn else None)
                if fn:
                    visit_body(node.body, child, qname, fn, current_class)
                continue
            if isinstance(node, ast.ClassDef):
                cls = Scope("class", scope, dynamic_class=bool(node.bases or node.decorator_list))
                scope.bind(node.name, Binding("class", cls))
                class_name = f"{qualified}.{node.name}" if qualified else node.name
                visit_body(node.body, cls, class_name, None, cls)
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:
                    spec = alias.name if alias.asname else alias.name.split(".")[0]
                    scope.bind(alias.asname or alias.name.split(".")[0], Binding("module", spec, origin=path))
            elif isinstance(node, ast.ImportFrom):
                module = "." * node.level + (node.module or "")
                for alias in node.names:
                    if alias.name == "*":
                        # Star imports make otherwise global resolutions unknowable.
                        scope.bindings["*"] = None
                    else:
                        scope.bind(alias.asname or alias.name, Binding("import", module, alias.name, path))
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                for name in node.names:
                    scope.bind(name, None)
            else:
                # Binding writes apply throughout the lexical function, not only after the write.
                targets = []
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr, ast.Delete)):
                    targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
                elif isinstance(node, (ast.For, ast.AsyncFor)):
                    targets = [node.target]
                elif isinstance(node, (ast.With, ast.AsyncWith)):
                    targets = [item.optional_vars for item in node.items if item.optional_vars]
                elif isinstance(node, ast.ExceptHandler) and node.name:
                    scope.bind(node.name, None)
                elif isinstance(node, ast.match_case):
                    for pattern in ast.walk(node.pattern):
                        name = getattr(pattern, "name", None) or getattr(pattern, "rest", None)
                        if name:
                            scope.bind(name, None)
                for target in targets:
                    for sub in ast.walk(target):
                        if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
                            value = getattr(node, "value", None)
                            alias_parts = parts(value) if value else None
                            binding = Binding("alias", (scope, alias_parts)) if alias_parts and sub is target else None
                            scope.bind(sub.id, binding)
                        elif isinstance(sub, ast.Attribute):
                            access = parts(sub)
                            if access and access[0] == "self" and current_class:
                                current_class.blocked_members.add(access[1])
                            elif access:
                                scope.bindings[access[0]] = None
            if owner:
                classify(node, owner)
            # Walk compound bodies without entering a different function/class namespace.
            for field in ("body", "orelse", "finalbody", "handlers", "cases"):
                children = getattr(node, field, None)
                if isinstance(children, list):
                    visit_body(children, scope, qualified, owner, current_class)

    def classify(node, fn):
        kinds = {
            ast.Import: "import", ast.ImportFrom: "import",
            ast.Assign: "assignment", ast.AnnAssign: "assignment", ast.AugAssign: "assignment",
            ast.Return: "return", ast.If: "branch", ast.Match: "branch",
            ast.For: "loop", ast.AsyncFor: "loop", ast.While: "loop",
            ast.Try: "exception", ast.ExceptHandler: "exception", ast.Raise: "exception",
        }
        if hasattr(ast, "TryStar"):
            kinds[ast.TryStar] = "exception"
        if hasattr(node, "lineno"):
            statement(fn, budget, kinds.get(type(node), "other"), node.lineno,
                      getattr(node, "end_lineno", node.lineno), excerpt(node))
        # Only the expressions owned by this statement; compound bodies are visited separately.
        stack = []
        for field, value in ast.iter_fields(node):
            if field in {"body", "orelse", "finalbody", "handlers", "cases"}:
                continue
            stack.extend(value if isinstance(value, list) else [value])
        while stack:
            child = stack.pop()
            if not isinstance(child, ast.AST) or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Call):
                call(fn, budget, expression(child.func),
                     child.lineno, child.col_offset, parts(child.func))
                statement(fn, budget, "call", child.lineno, child.end_lineno, excerpt(child))
            elif isinstance(child, ast.Await):
                statement(fn, budget, "await", child.lineno, child.end_lineno, excerpt(child))
            elif isinstance(child, (ast.Yield, ast.YieldFrom)):
                statement(fn, budget, "yield", child.lineno, child.end_lineno, excerpt(child))
            elif isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                # Comprehension targets have their own scope; do not resolve calls through them.
                names = {n.id for gen in child.generators for n in ast.walk(gen.target) if isinstance(n, ast.Name)}
                for name in names:
                    fn.scope.bindings[name] = None
            elif isinstance(child, ast.NamedExpr):
                for name in ast.walk(child.target):
                    if isinstance(name, ast.Name):
                        fn.scope.bind(name.id, None)
            stack.extend(reversed(list(ast.iter_child_nodes(child))))

    # Module initializer is an explicit synthetic navigation owner, not an invented function call.
    executable = [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom))]
    module_fn = None
    if executable:
        module_fn = new_function(parsed, parsed.scope, budget, name="<module>", qualified_name="<module>",
                                 line=1, end=max(1, len(lines)), kind="module",
                                 entrypoint=entry("entry_file", "文件顶层执行语句", 1, candidate=True) if entry_file else None)
        if module_fn:
            module_fn.data["synthetic"] = True
    visit_body(tree.body, parsed.scope, owner=module_fn)
    for fn in parsed.functions:
        fn.data["calls"].sort(key=lambda c: (c["line"], c["column"]))
        fn.data["statements"].sort(key=lambda s: (s["line_start"], s["line_end"], s["kind"]))
    # Mark only exact __name__ == "__main__" guards; target marking is done after resolution.
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            try:
                exact = isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__" and len(node.test.ops) == 1 and isinstance(node.test.ops[0], ast.Eq) and len(node.test.comparators) == 1 and isinstance(node.test.comparators[0], ast.Constant) and node.test.comparators[0].value == "__main__"
            except AttributeError:
                exact = False
            if exact and module_fn:
                module_fn.guard_ranges.append((node.lineno, node.end_lineno))
                module_fn.data["entrypoint"] = entry("main_guard", '__name__ == "__main__"', node.lineno)
    return parsed
