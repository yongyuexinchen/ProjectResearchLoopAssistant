"""Tree-sitter JavaScript/TypeScript/TSX syntax and conservative lexical bindings."""
from __future__ import annotations

from functools import lru_cache
from pathlib import PurePosixPath

from tree_sitter import Language, Parser
import tree_sitter_javascript
import tree_sitter_typescript

from app.architecture.source_common import (
    Binding, Budget, ParsedFile, Scope, call, entry, new_function, statement,
)

FUNCTION_TYPES = {"function_declaration", "generator_function_declaration", "function_expression",
                  "generator_function", "arrow_function", "method_definition"}
NEXT_COMPONENT_FILES = {"page.js", "page.jsx", "page.ts", "page.tsx", "layout.js", "layout.jsx",
                        "layout.ts", "layout.tsx", "middleware.js", "middleware.ts"}
NEXT_ROUTE_FILES = NEXT_COMPONENT_FILES | {"route.js", "route.ts"}


@lru_cache(maxsize=3)
def _language(language: str) -> Language:
    capsule = (tree_sitter_javascript.language() if language == "javascript" else
               tree_sitter_typescript.language_tsx() if language == "tsx" else
               tree_sitter_typescript.language_typescript())
    return Language(capsule)


def parse_javascript(path: str, data: bytes, language: str, budget: Budget,
                     entry_file: bool, max_syntax_nodes: int) -> ParsedFile:
    tree = Parser(_language(language)).parse(data)
    parsed = ParsedFile(path, language, Scope("module"), has_errors=tree.root_node.has_error)
    count = 0

    def text(node):
        return data[node.start_byte:node.end_byte].decode("utf-8", errors="replace") if node else ""

    def names(node):
        if node is None or node.type in {"type_annotation", "type_identifier", "predefined_type"}:
            return []
        if node.type in {"identifier", "shorthand_property_identifier_pattern"}:
            return [text(node)]
        if node.type in {"required_parameter", "optional_parameter"}:
            return names(node.child_by_field_name("pattern"))
        if node.type in {"assignment_pattern", "object_assignment_pattern"}:
            return names(node.child_by_field_name("left"))
        if node.type == "pair_pattern":
            return names(node.child_by_field_name("value"))
        result = []
        for child in node.named_children:
            result.extend(names(child))
        return result

    def parts(node):
        if node is None:
            return None
        if node.type in {"identifier", "this"}:
            return [text(node)]
        if node.type in {"member_expression"}:
            base = parts(node.child_by_field_name("object"))
            prop = node.child_by_field_name("property")
            return [*base, text(prop)] if base and prop and prop.type == "property_identifier" else None
        if node.type in {"parenthesized_expression", "as_expression", "non_null_expression"} and node.named_children:
            return parts(node.named_children[0])
        return None

    def top_export(node):
        current = node.parent
        while current and current.type in {"variable_declarator", "lexical_declaration", "variable_declaration"}:
            current = current.parent
        return current is not None and current.type == "export_statement"

    def scan(node, scope, qualified="", owner=None, current_class=None):
        nonlocal count
        count += 1
        if count > max_syntax_nodes:
            raise ValueError("syntax-node budget exceeded")
        if node.type == "object":
            parent = node.parent
            variable = parent.child_by_field_name("name") if parent and parent.type == "variable_declarator" else None
            object_name = text(variable) or f"<object@{node.start_point.row + 1}:{node.start_point.column}>"
            object_scope = Scope("object", scope)
            object_qualified = f"{qualified}.{object_name}" if qualified else object_name
            for child in node.named_children:
                scan(child, object_scope, object_qualified, owner, None)
            return
        if node.type in FUNCTION_TYPES:
            own_name = node.child_by_field_name("name")
            parent = node.parent
            bind_name = None
            if parent and parent.type == "variable_declarator":
                variable_name = parent.child_by_field_name("name")
                if variable_name and variable_name.type == "identifier":
                    bind_name = text(variable_name)
            declared = node.type in {"function_declaration", "generator_function_declaration", "method_definition"}
            name = bind_name or text(own_name) or (
                "default" if parent and parent.type == "export_statement" and "default" in text(parent)[:24]
                else f"<anonymous@{node.start_point.row + 1}:{node.start_point.column}>"
            )
            qname = f"{qualified}.{name}" if qualified else name
            child = Scope("function", scope.parent if scope.kind in {"class", "object"} else scope,
                          class_scope=current_class)
            parameter_node = node.child_by_field_name("parameters") or node.child_by_field_name("parameter")
            parameter_names = names(parameter_node)
            for parameter in parameter_names:
                child.bind(parameter, None)
            is_static = node.type == "method_definition" and any(c.type == "static" for c in node.children)
            if node.type != "arrow_function":
                child.bindings["this"] = None
            if node.type == "method_definition" and current_class and not is_static:
                child.bindings["this"] = Binding("receiver", current_class)
            marker = None
            if top_export(node) and name in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                marker = entry("exported_handler", "导出的 HTTP 方法名处理函数语法", node.start_point.row + 1)
            elif entry_file and scope.kind == "module" and top_export(node) and (
                PurePosixPath(parsed.path).name.lower() in NEXT_COMPONENT_FILES
            ):
                marker = entry("entry_file", "入口文件中的导出组件候选", node.start_point.row + 1, candidate=True)
            fn = new_function(parsed, child, budget, name=name, qualified_name=qname,
                              line=node.start_point.row + 1, end=node.end_point.row + 1,
                              column=node.start_point.column, parameters=parameter_names,
                              entrypoint=marker, kind="method" if node.type == "method_definition" else "function")
            binding = Binding("function", fn.data["id"]) if fn else None
            if parent and parent.type == "export_statement" and any(c.type == "default" for c in parent.children):
                parsed.exports["default"] = binding
            if bind_name or declared:
                scope.bind(bind_name or name, None if is_static else binding)
            # Named function expressions bind their own name inside, not in the outer namespace.
            if own_name and node.type in {"function_expression", "generator_function"}:
                child.bind(text(own_name), binding)
            if fn:
                body = node.child_by_field_name("body")
                if body:
                    if body.type != "statement_block":
                        statement(fn, budget, "return", body.start_point.row + 1, body.end_point.row + 1, text(body))
                    scan(body, child, qname, fn, current_class)
            return
        if node.type in {"class_declaration", "class"}:
            name_node = node.child_by_field_name("name")
            name = text(name_node) or f"<class@{node.start_point.row + 1}>"
            cls = Scope("class", scope, dynamic_class=any(c.type == "class_heritage" for c in node.named_children))
            scope.bind(name, Binding("class", cls))
            qname = f"{qualified}.{name}" if qualified else name
            body = node.child_by_field_name("body")
            if body:
                scan(body, cls, qname, None, cls)
            return
        if node.type == "import_statement":
            source = node.child_by_field_name("source")
            spec = text(source)[1:-1] if source else ""
            clause = next((c for c in node.named_children if c.type == "import_clause"), None)
            if clause:
                for child in clause.named_children:
                    if child.type == "identifier":
                        scope.bind(text(child), Binding("import", spec, "default", path))
                    elif child.type == "namespace_import":
                        scope.bind(text(child.named_children[-1]), Binding("module", spec, origin=path))
                    elif child.type == "named_imports":
                        for item in child.named_children:
                            if item.type == "import_specifier":
                                imported = item.child_by_field_name("name")
                                local = item.child_by_field_name("alias") or imported
                                scope.bind(text(local), Binding("import", spec, text(imported), path))
            return
        if node.type == "variable_declarator":
            target = node.child_by_field_name("name")
            value = node.child_by_field_name("value")
            if not value or value.type not in FUNCTION_TYPES:
                alias = parts(value)
                for name in names(target):
                    scope.bind(name, Binding("alias", (scope, alias)) if alias and target.type == "identifier" else None)
        elif node.type in {"assignment_expression", "augmented_assignment_expression", "update_expression"}:
            left = node.child_by_field_name("left") or node.child_by_field_name("argument")
            access = parts(left)
            if access and len(access) == 1:
                scope.bind(access[0], None)
            elif access and access[0] == "this" and current_class:
                current_class.blocked_members.add(access[1])
            elif access:
                scope.bindings[access[0]] = None
            else:
                for name in names(left):
                    scope.bind(name, None)
        elif node.type == "for_in_statement":
            for name in names(node.child_by_field_name("left")):
                scope.bind(name, None)
        elif node.type == "catch_clause":
            for name in names(node.child_by_field_name("parameter")):
                scope.bind(name, None)

        if owner:
            kinds = {
                "return_statement": "return", "if_statement": "branch", "switch_statement": "branch",
                "ternary_expression": "branch", "for_statement": "loop", "for_in_statement": "loop",
                "while_statement": "loop", "do_statement": "loop", "try_statement": "exception",
                "catch_clause": "exception", "throw_statement": "exception", "await_expression": "await",
                "yield_expression": "yield", "lexical_declaration": "assignment",
                "variable_declaration": "assignment", "assignment_expression": "assignment",
                "call_expression": "call", "new_expression": "call",
            }
            if node.type in kinds:
                statement(owner, budget, kinds[node.type], node.start_point.row + 1,
                          node.end_point.row + 1, text(node))
            if node.type in {"call_expression", "new_expression"}:
                target = node.child_by_field_name("function") or node.child_by_field_name("constructor")
                call(owner, budget, text(target), node.start_point.row + 1,
                     node.start_point.column, parts(target) if node.type != "new_expression" else None)
        for child in node.named_children:
            scan(child, scope, qualified, owner, current_class)

    executable = [n for n in tree.root_node.named_children if n.type not in {
        "function_declaration", "generator_function_declaration", "class_declaration", "import_statement", "comment", "ERROR",
    } and not (n.type == "export_statement" and n.child_by_field_name("declaration") is not None and n.child_by_field_name("declaration").type in {
        "function_declaration", "generator_function_declaration", "class_declaration"
    })]
    module_fn = None
    if executable:
        module_fn = new_function(parsed, parsed.scope, budget, name="<module>", qualified_name="<module>",
                                 line=1, end=max(1, data.count(b"\n") + (not data.endswith(b"\n"))), kind="module",
                                 entrypoint=(entry("entry_file", "文件顶层执行语句", 1, candidate=True)
                                             if entry_file and PurePosixPath(parsed.path).name.lower() not in NEXT_ROUTE_FILES
                                             else None))
        if module_fn:
            module_fn.data["synthetic"] = True
    scan(tree.root_node, parsed.scope, owner=module_fn)
    for node in tree.root_node.named_children:
        if node.type != "export_statement":
            continue
        declaration = node.child_by_field_name("declaration")
        if declaration:
            name_node = declaration.child_by_field_name("name")
            exported = [text(name_node)] if name_node else [
                name for child in declaration.named_children if child.type == "variable_declarator"
                for name in names(child.child_by_field_name("name"))
            ]
            for name in exported:
                parsed.exports[name] = parsed.scope.lookup(name)
            if any(c.type == "default" for c in node.children):
                if exported:
                    parsed.exports["default"] = parsed.scope.lookup(exported[0])
                else:
                    candidates = [fn for fn in parsed.functions if fn.data["line_start"] == declaration.start_point.row + 1]
                    if len(candidates) == 1:
                        parsed.exports["default"] = Binding("function", candidates[0].data["id"])
        elif not node.child_by_field_name("source"):
            clause = next((c for c in node.named_children if c.type == "export_clause"), None)
            if clause:
                for specifier in clause.named_children:
                    name_node = specifier.child_by_field_name("name")
                    alias_node = specifier.child_by_field_name("alias") or name_node
                    parsed.exports[text(alias_node)] = parsed.scope.lookup(text(name_node))
            value = node.child_by_field_name("value")
            if value and value.type == "identifier":
                parsed.exports["default"] = parsed.scope.lookup(text(value))
    for fn in parsed.functions:
        fn.data["calls"].sort(key=lambda c: (c["line"], c["column"]))
        fn.data["statements"].sort(key=lambda s: (s["line_start"], s["line_end"], s["kind"]))
    return parsed
