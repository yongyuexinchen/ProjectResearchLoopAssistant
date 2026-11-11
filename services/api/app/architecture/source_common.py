"""Internal parsing records; none of the input repository's code is imported."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any


@dataclass
class Binding:
    kind: str
    value: Any = None
    member: str = ""
    origin: str = ""


@dataclass
class Scope:
    kind: str
    parent: Scope | None = None
    bindings: dict[str, Binding | None] = field(default_factory=dict)
    class_scope: Scope | None = None
    dynamic_class: bool = False
    blocked_members: set[str] = field(default_factory=set)

    def bind(self, name: str, binding: Binding | None) -> None:
        if not name:
            return
        # Multiple assignments/declarations are ambiguous without control-flow analysis.
        self.bindings[name] = binding if name not in self.bindings else None

    def lookup(self, name: str) -> Binding | None:
        if self.kind == "module" and "*" in self.bindings:
            return None
        if name in self.bindings:
            return self.bindings[name]
        return self.parent.lookup(name) if self.parent else None


@dataclass
class Function:
    data: dict[str, Any]
    scope: Scope
    raw_calls: list[tuple[dict[str, Any], list[str] | None]] = field(default_factory=list)
    guard_ranges: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class ParsedFile:
    path: str
    language: str
    scope: Scope
    functions: list[Function] = field(default_factory=list)
    exports: dict[str, Binding | None] = field(default_factory=dict)
    has_errors: bool = False


@dataclass
class Budget:
    maxima: dict[str, int]
    counts: dict[str, int] = field(default_factory=dict)
    exhausted: set[str] = field(default_factory=set)

    def take(self, kind: str) -> bool:
        if self.counts.get(kind, 0) >= self.maxima[kind]:
            self.exhausted.add(kind)
            return False
        self.counts[kind] = self.counts.get(kind, 0) + 1
        return True


def function_id(path: str, qualified_name: str, line: int, column: int) -> str:
    identity = f"{path}:{qualified_name}:{line}:{column}".encode("utf-8")
    return "sf_" + sha256(identity).hexdigest()[:24]


def new_function(parsed: ParsedFile, scope: Scope, budget: Budget, *, name: str,
                 qualified_name: str, line: int, end: int, column: int = 0,
                 parameters: list[str] | None = None, docstring: str = "",
                 entrypoint: dict | None = None, kind: str = "function") -> Function | None:
    if not budget.take("functions"):
        return None
    data = {
        "id": function_id(parsed.path, qualified_name, line, column),
        "path": parsed.path, "name": name, "qualified_name": qualified_name,
        "line_start": line, "line_end": end, "parameters": parameters or [],
        "docstring": docstring[:1200], "statements": [], "calls": [],
        "entrypoint": entrypoint, "kind": kind,
    }
    item = Function(data, scope)
    parsed.functions.append(item)
    return item


def statement(function: Function, budget: Budget, kind: str, start: int, end: int,
              excerpt: str) -> None:
    if budget.take("statements"):
        labels = {"import": "导入", "assignment": "赋值/数据准备", "call": "调用",
                  "return": "返回", "branch": "条件分支", "loop": "循环",
                  "exception": "异常处理", "await": "异步等待", "yield": "生成器输出",
                  "declaration": "声明", "other": "语句"}
        function.data["statements"].append({
            "kind": kind, "label": labels.get(kind, kind),
            "line_start": start, "line_end": end, "excerpt": excerpt[:240],
        })


def call(function: Function, budget: Budget, expression: str, line: int, column: int,
         parts: list[str] | None) -> None:
    if budget.take("calls"):
        data = {"expression": expression[:180], "line": line, "column": column,
                "target_id": None, "resolution": "unresolved",
                "reason": "目标不是可证明的本地直接函数引用"}
        function.data["calls"].append(data)
        function.raw_calls.append((data, parts))


def entry(kind: str, label: str, line: int, *, candidate: bool = False) -> dict:
    return {"kind": kind, "label": label[:180], "line": line,
            "confidence": "candidate" if candidate else "syntax"}
