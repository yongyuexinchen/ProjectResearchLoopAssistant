"""Source positions and bindings are hand-checked against these small input programs."""
import importlib
import importlib.util
from pathlib import Path

import pytest


def build(tmp_path, sources, entrypoints=()):
    for relative, text in sources.items():
        file = tmp_path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
    if importlib.util.find_spec("app.architecture.source_flow") is None:
        return None
    module = importlib.import_module("app.architecture.source_flow")
    return module.build_source_flow(tmp_path, {
        "root_label": "fixture",
        "entrypoint_files": list(entrypoints),
        "file_tree": [{"path": path, "kind": "file"} for path in sources],
    })


def functions(graph):
    assert graph is not None, "source parser must produce a saved graph"
    return {(item["path"], item["qualified_name"]): item for item in graph.details["functions"]}


def test_python_cross_file_alias_and_actual_callsite(tmp_path):
    graph = build(tmp_path, {
        "helper.py": "def work(value):\n    return value + 1\n",
        "main.py": "from helper import work as run\n\ndef main():\n    return run(3)\n\nif __name__ == '__main__':\n    main()\n",
    }, ["main.py"])
    items = functions(graph)
    main, target = items[("main.py", "main")], items[("helper.py", "work")]
    assert (main["line_start"], main["line_end"], main["parameters"]) == (3, 4, [])
    assert main["calls"][0]["target_id"] == target["id"]
    assert main["calls"][0]["line"] == 4
    assert main["calls"][0]["column"] == 11
    assert main["entrypoint"] is not None
    assert any(edge.source == main["id"] and edge.target == target["id"] and "L4" in edge.label for edge in graph.edges)
    assert graph.details["files"][0]["sha256"]
    assert graph.details["version"] == 1


def test_python_module_import_and_relative_package_alias(tmp_path):
    items = functions(build(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/helper.py": "def work():\n    return 1\n",
        "pkg/main.py": "from . import helper as h\n\ndef main():\n    return h.work()\n",
    }))
    assert items[("pkg/main.py", "main")]["calls"][0]["target_id"] == items[("pkg/helper.py", "work")]["id"]


def test_same_names_do_not_cross_files_without_import(tmp_path):
    items = functions(build(tmp_path, {
        "a.py": "def work():\n    return 1\n",
        "b.py": "def work():\n    return 2\n",
        "main.py": "def main():\n    return work()\n",
    }))
    assert items[("a.py", "work")]["id"] != items[("b.py", "work")]["id"]
    call = items[("main.py", "main")]["calls"][0]
    assert call["target_id"] is None and call["resolution"] == "unresolved"


@pytest.mark.parametrize("body", [
    "def main(work):\n    return work()\n",
    "def main():\n    work = factory()\n    return work()\n",
])
def test_python_parameter_and_assignment_shadowing(tmp_path, body):
    items = functions(build(tmp_path, {
        "helper.py": "def work():\n    return 1\n",
        "main.py": "from helper import work\n\n" + body,
    }))
    calls = items[("main.py", "main")]["calls"]
    assert all(c["target_id"] is None for c in calls)


def test_python_self_methods_async_and_statement_ranges(tmp_path):
    items = functions(build(tmp_path, {"server.py": (
        "class Worker:\n"
        "    async def run(self, value):\n"
        "        \"\"\"Run one request.\"\"\"\n"
        "        try:\n"
        "            if value:\n"
        "                for item in value:\n"
        "                    await self.save(item)\n"
        "        except ValueError:\n"
        "            return None\n"
        "        return value\n"
        "\n"
        "    async def save(self, item):\n"
        "        return item\n"
    )}))
    run = items[("server.py", "Worker.run")]
    assert run["parameters"] == ["self", "value"]
    assert run["docstring"] == "Run one request."
    assert run["calls"][0]["target_id"] == items[("server.py", "Worker.save")]["id"]
    assert run["calls"][0]["line"] == 7
    kinds = {s["kind"] for s in run["statements"]}
    assert {"branch", "loop", "exception", "await", "call", "return"} <= kinds
    assert all(2 <= s["line_start"] <= s["line_end"] <= 10 for s in run["statements"])


def test_python_rebound_self_and_imports_stay_unresolved(tmp_path):
    items = functions(build(tmp_path, {"main.py": (
        "class Worker:\n"
        "    def run(self, other):\n"
        "        self = other\n"
        "        return self.save()\n"
        "    def save(self):\n"
        "        return 1\n"
    )}))
    assert items[("main.py", "Worker.run")]["calls"][0]["target_id"] is None


@pytest.mark.parametrize("extension", ["js", "ts", "tsx"])
def test_tree_sitter_relative_named_import_and_arrow(tmp_path, extension):
    graph = build(tmp_path, {
        "helper." + extension: "export function work(value) { return value; }\n",
        "main." + extension: "import { work as run } from './helper';\nexport const GET = async (request) => {\n  return await run(request);\n};\n",
    })
    items = functions(graph)
    handler = items[("main." + extension, "GET")]
    assert handler["calls"][0]["target_id"] == items[("helper." + extension, "work")]["id"]
    assert handler["calls"][0]["line"] == 3
    assert handler["entrypoint"]["kind"] == "exported_handler"
    assert {"await", "return", "call"} <= {s["kind"] for s in handler["statements"]}


def test_javascript_namespace_default_imports_and_tsx_syntax(tmp_path):
    items = functions(build(tmp_path, {
        "helper.ts": "export default function work() { return 1; }\nexport function more() { return 2; }\n",
        "page.tsx": "import run, * as h from './helper';\nexport default function Page() {\n  const result = run();\n  h.more();\n  return <main>{result}</main>;\n}\n",
    }))
    page = items[("page.tsx", "Page")]
    assert [c["target_id"] for c in page["calls"]] == [
        items[("helper.ts", "work")]["id"], items[("helper.ts", "more")]["id"],
    ]


def test_javascript_parameter_shadowing_and_unconfigured_alias(tmp_path):
    items = functions(build(tmp_path, {
        "helper.ts": "export function work() { return 1; }\n",
        "main.ts": "import {work} from './helper';\nimport {work as unknown} from '@/helper';\nexport function main(work: () => number) {\n return work() + unknown();\n}\n",
    }))
    calls = items[("main.ts", "main")]["calls"]
    assert len(calls) == 2 and all(c["target_id"] is None for c in calls)


def test_next_page_is_an_entrypoint_even_when_scan_has_no_entrypoints(tmp_path):
    graph = build(tmp_path, {
        "src/lib/format.ts": "export function format(value: string) { return value; }\n",
        "src/app/page.tsx": "import { format } from '../lib/format';\nexport default function Page() { return <main>{format('x')}</main>; }\n",
        "next.config.ts": "export default {};\n",
    })
    items = functions(graph)
    page = items[("src/app/page.tsx", "Page")]
    assert page["entrypoint"]["kind"] == "entry_file"
    assert ("next.config.ts", "<module>") not in items
    assert any(node.path == "src/app/page.tsx" for node in graph.nodes)


def test_tsx_with_recoverable_jsx_error_still_indexes_valid_functions(tmp_path):
    graph = build(tmp_path, {"panel.tsx": (
        "export default function Panel() {\n"
        "  return <a href=\"https://example.com/?a=1&b=2\">link</a>;\n"
        "}\n"
    )})
    items = functions(graph)
    assert ("panel.tsx", "Panel") in items
    assert graph.details["stats"]["parse_errors"] == 1
    assert any("可恢复" in warning for warning in graph.details["warnings"])


def test_malformed_files_do_not_invent_functions(tmp_path):
    graph = build(tmp_path, {
        "bad.py": "def broken(:\n",
        "bad.ts": "export function broken( {\n",
        "ok.py": "def valid():\n    return 1\n",
    })
    items = functions(graph)
    assert ("ok.py", "valid") in items
    assert all(path == "ok.py" for path, name in items)
    assert len(graph.details["warnings"]) >= 2


def test_unsupported_language_is_described_without_invented_calls(tmp_path):
    graph = build(tmp_path, {"main.go": "package main\nfunc main() {}\n"})
    assert graph is not None
    assert graph.details["functions"] == []
    assert graph.details["warnings"]
    assert graph.edges == []


def test_source_path_escape_sensitive_and_generated_are_never_read(tmp_path):
    outside = tmp_path.parent / "outside.py"
    outside.write_text("def forbidden(): pass\n", encoding="utf-8")
    graph = build(tmp_path, {
        "good.py": "def allowed(): pass\n",
        "node_modules/evil.py": "def forbidden(): pass\n",
        ".env.py": "def forbidden(): pass\n",
    })
    module = importlib.import_module("app.architecture.source_flow")
    codebase = {"file_tree": [{"path": p, "kind": "file"} for p in [
        "good.py", "../outside.py", str(outside), "node_modules/evil.py", ".env.py",
    ]]}
    graph = module.build_source_flow(tmp_path, codebase)
    assert {f["path"] for f in graph.details["files"]} == {"good.py"}
    assert all(f["name"] != "forbidden" for f in graph.details["functions"])
    assert graph.details["warnings"]


def test_symlink_ancestor_is_rejected(tmp_path):
    external = tmp_path.parent / "external"
    external.mkdir(exist_ok=True)
    (external / "secret.py").write_text("def forbidden(): pass\n", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    graph = build(tmp_path, {"good.py": "def allowed(): pass\n"})
    module = importlib.import_module("app.architecture.source_flow")
    graph = module.build_source_flow(tmp_path, {"file_tree": [
        {"path": "good.py", "kind": "file"}, {"path": "link/secret.py", "kind": "file"},
    ]})
    assert {f["path"] for f in graph.details["files"]} == {"good.py"}


def test_budgets_bound_index_calls_and_canvas_without_losing_limits(tmp_path, monkeypatch):
    graph = build(tmp_path, {"main.py": "def main():\n    return 1\n"})
    module = importlib.import_module("app.architecture.source_flow")
    monkeypatch.setattr(module, "MAX_FUNCTIONS", 8)
    monkeypatch.setattr(module, "MAX_CALLS", 3)
    monkeypatch.setattr(module, "MAX_STATEMENTS", 4)
    monkeypatch.setattr(module, "MAX_GRAPH_NODES", 2)
    source = "".join("def f%d():\n    return f%d()\n" % (i, i + 1) for i in range(20))
    graph = build(tmp_path, {"main.py": source}, ["main.py"])
    assert len(graph.details["functions"]) <= 8
    assert sum(len(f["calls"]) for f in graph.details["functions"]) <= 3
    assert sum(len(f["statements"]) for f in graph.details["functions"]) <= 4
    assert len(graph.nodes) <= 2
    assert graph.details["warnings"]
    assert graph.details["stats"]["truncated"] is True


def test_file_and_total_byte_budgets_and_deterministic_hash(tmp_path, monkeypatch):
    graph = build(tmp_path, {"a.py": "def a(): pass\n", "b.py": "def b(): pass\n"})
    assert graph is not None
    first = graph.to_dict()
    module = importlib.import_module("app.architecture.source_flow")
    assert build(tmp_path, {"a.py": "def a(): pass\n", "b.py": "def b(): pass\n"}).to_dict() == first
    monkeypatch.setattr(module, "MAX_SOURCE_FILES", 1)
    graph = build(tmp_path, {"a.py": "def a(): pass\n", "b.py": "def b(): pass\n"})
    assert len(graph.details["files"]) == 1 and graph.details["warnings"]
    monkeypatch.setattr(module, "MAX_TOTAL_BYTES", 3)
    graph = build(tmp_path, {"a.py": "def a(): pass\n"})
    assert graph.details["files"] == [] and graph.details["warnings"]


def test_none_root_has_no_diagram():
    if importlib.util.find_spec("app.architecture.source_flow") is None:
        pytest.fail("source parser is missing")
    module = importlib.import_module("app.architecture.source_flow")
    assert module.build_source_flow(None, {}) is None


def test_explicit_monorepo_package_root_and_ambiguous_duplicate_package(tmp_path):
    sources = {
        "services/api/app/__init__.py": "",
        "services/api/app/services/__init__.py": "",
        "services/api/app/services/workflow.py": "def enqueue_workflow():\n    return 1\n",
        "services/api/app/api/routes.py": "from app.services.workflow import enqueue_workflow\n\ndef setup():\n    return enqueue_workflow()\n",
    }
    items = functions(build(tmp_path, sources))
    assert items[("services/api/app/api/routes.py", "setup")]["calls"][0]["target_id"] == items[("services/api/app/services/workflow.py", "enqueue_workflow")]["id"]
    sources.update({
        "other/app/__init__.py": "",
        "other/app/services/__init__.py": "",
        "other/app/services/workflow.py": "def enqueue_workflow():\n    return 2\n",
    })
    items = functions(build(tmp_path, sources))
    assert items[("services/api/app/api/routes.py", "setup")]["calls"][0]["target_id"] is None


@pytest.mark.parametrize("extension, helper, main", [
    ("py", "def work(): return 1\n", "from helper import work\n\ndef main():\n    run = work\n    return run()\n"),
    ("ts", "export function work() { return 1; }\n", "import {work} from './helper';\nexport function main() { const run = work; return run(); }\n"),
])
def test_direct_alias_assignment_follows_known_binding(tmp_path, extension, helper, main):
    items = functions(build(tmp_path, {"helper." + extension: helper, "main." + extension: main}))
    assert items[("main." + extension, "main")]["calls"][0]["target_id"] == items[("helper." + extension, "work")]["id"]


@pytest.mark.parametrize("extension, source", [
    ("py", "import helper as h\n\ndef main(replacement):\n    h.work = replacement\n    return h.work()\n"),
    ("ts", "import * as h from './helper';\nexport function main(replacement) { h.work = replacement; return h.work(); }\n"),
])
def test_imported_module_member_reassignment_is_not_resolved(tmp_path, extension, source):
    helper = "def work(): return 1\n" if extension == "py" else "export function work() { return 1; }\n"
    items = functions(build(tmp_path, {"helper." + extension: helper, "main." + extension: source}))
    assert items[("main." + extension, "main")]["calls"][-1]["target_id"] is None


def test_main_guard_marks_only_guard_target_not_bootstrap_or_downstream(tmp_path):
    items = functions(build(tmp_path, {"program.py": (
        "def bootstrap(): return 1\n"
        "def leaf(): return 2\n"
        "def main(): return leaf()\n"
        "bootstrap()\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )}))
    assert items[("program.py", "main")]["entrypoint"]["kind"] == "main_guard"
    assert items[("program.py", "bootstrap")]["entrypoint"] is None
    assert items[("program.py", "leaf")]["entrypoint"] is None


def test_inherited_dynamic_self_and_js_this_remain_unresolved(tmp_path):
    items = functions(build(tmp_path, {
        "main.py": "class Base:\n    def save(self): pass\nclass Worker(Base):\n    def run(self): return self.save()\n",
        "main.ts": "class Base { save() {} }\nclass Worker extends Base { run() { return this.save(); } }\n",
    }))
    assert items[("main.py", "Worker.run")]["calls"][0]["target_id"] is None
    assert items[("main.ts", "Worker.run")]["calls"][0]["target_id"] is None


def test_duplicate_inventory_spellings_do_not_duplicate_functions(tmp_path):
    graph = build(tmp_path, {"a.py": "def unique(): pass\n"})
    module = importlib.import_module("app.architecture.source_flow")
    graph = module.build_source_flow(tmp_path, {"file_tree": [
        {"path": "a.py", "kind": "file"}, {"path": "./a.py", "kind": "file"},
    ]})
    assert len(graph.details["files"]) == 1
    assert len(graph.details["functions"]) == 1


def test_source_hash_changes_when_source_changes_and_snapshot_stays_frozen(tmp_path):
    graph = build(tmp_path, {"a.py": "def a():\n    return 1\n"})
    frozen = graph.to_dict()
    changed = build(tmp_path, {"a.py": "def a():\n    return 2\n"})
    assert graph.to_dict() == frozen
    assert changed.details["files"][0]["sha256"] != graph.details["files"][0]["sha256"]


def test_single_file_byte_budget_is_explicit(tmp_path, monkeypatch):
    graph = build(tmp_path, {"a.py": "def a():\n    return 1\n"})
    module = importlib.import_module("app.architecture.source_flow")
    monkeypatch.setattr(module, "MAX_FILE_BYTES", 4)
    graph = build(tmp_path, {"a.py": "def a():\n    return 1\n"})
    assert graph.details["files"] == []
    assert graph.details["stats"]["truncated"] is True
    assert graph.details["warnings"]


def test_python_nested_parameter_self_is_not_outer_method_receiver(tmp_path):
    items = functions(build(tmp_path, {"main.py": (
        "class Worker:\n"
        "    def run(self):\n"
        "        def inner(self):\n"
        "            return self.save()\n"
        "        return inner\n"
        "    def save(self):\n"
        "        return 1\n"
    )}))
    assert items[("main.py", "Worker.run.inner")]["calls"][0]["target_id"] is None


@pytest.mark.parametrize("source, qualified", [
    ("class Worker { run() { function inner() { return this.save(); } return inner; } save() {} }", "Worker.run.inner"),
    ("class Worker { static run() { return this.save(); } save() {} }", "Worker.run"),
    ("class Worker { run() { return this.save(); } static save() {} }", "Worker.run"),
])
def test_javascript_dynamic_or_static_this_does_not_use_instance_namespace(tmp_path, source, qualified):
    items = functions(build(tmp_path, {"main.ts": source}))
    assert items[("main.ts", qualified)]["calls"][0]["target_id"] is None


@pytest.mark.parametrize("body", [
    "def main(value):\n    match value:\n        case work:\n            return work()\n",
    "def main():\n    del work\n    return work()\n",
])
def test_python_match_and_delete_shadow_imports(tmp_path, body):
    items = functions(build(tmp_path, {
        "helper.py": "def work(): return 1\n",
        "main.py": "from helper import work\n\n" + body,
    }))
    assert items[("main.py", "main")]["calls"][0]["target_id"] is None


@pytest.mark.parametrize("body", [
    "export function main(other) { ({work} = other); return work(); }",
    "export function main(items) { for (work of items) { work(); } }",
])
def test_javascript_destructuring_and_for_assignment_shadow_import(tmp_path, body):
    items = functions(build(tmp_path, {
        "helper.ts": "export function work() { return 1; }",
        "main.ts": "import {work} from './helper';\n" + body,
    }))
    assert items[("main.ts", "main")]["calls"][0]["target_id"] is None


def test_python_direct_call_keeps_utf8_columns_and_multiline_expression(tmp_path):
    items = functions(build(tmp_path, {"main.py": (
        "def worker(): return 1\n"
        "def main():\n"
        "    文本 = '中文'; worker(\n"
        "    )\n"
    )}))
    call = items[("main.py", "main")]["calls"][0]
    assert call["expression"] == "worker"
    assert (call["line"], call["column"]) == (3, 23)


def test_javascript_object_method_is_not_a_module_level_function_binding(tmp_path):
    items = functions(build(tmp_path, {"main.js": (
        "const obj = { work() { return 1; } };\n"
        "function main() { return work(); }\n"
    )}))
    assert items[("main.js", "main")]["calls"][0]["target_id"] is None
    assert ("main.js", "obj.work") in items


def test_python_relative_import_cannot_escape_explicit_top_package(tmp_path):
    items = functions(build(tmp_path, {
        "target.py": "def work(): return 1\n",
        "pkg/__init__.py": "",
        "pkg/a.py": "from .. import target\n\ndef main(): return target.work()\n",
    }))
    assert items[("pkg/a.py", "main")]["calls"][0]["target_id"] is None


def test_python_ambiguous_package_does_not_fall_through_to_child_module(tmp_path):
    items = functions(build(tmp_path, {
        "pkg.py": "def other(): return 1\n",
        "pkg/__init__.py": "",
        "pkg/helper.py": "def work(): return 1\n",
        "main.py": "from pkg import helper\n\ndef main(): return helper.work()\n",
    }))
    assert items[("main.py", "main")]["calls"][0]["target_id"] is None


def test_python_unknown_star_import_invalidates_prior_module_binding(tmp_path):
    items = functions(build(tmp_path, {
        "helper.py": "def work(): return 1\n",
        "main.py": "from helper import work\nfrom unknown import *\n\ndef main(): return work()\n",
    }))
    assert items[("main.py", "main")]["calls"][0]["target_id"] is None


def test_unknown_get_decorator_is_a_candidate_not_proven_http_registration(tmp_path):
    items = functions(build(tmp_path, {"main.py": (
        "@decorators.get('/path')\n"
        "def work(): return 1\n"
    )}))
    assert items[("main.py", "work")]["entrypoint"]["confidence"] == "candidate"


def test_javascript_anonymous_default_arrow_resolves_through_default_import(tmp_path):
    items = functions(build(tmp_path, {
        "helper.ts": "export default () => 1;\n",
        "main.ts": "import run from './helper';\nexport function main() { return run(); }\n",
    }))
    assert items[("main.ts", "main")]["calls"][0]["target_id"] == items[("helper.ts", "default")]["id"]


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows junction boundary")
def test_windows_junction_ancestor_is_rejected_without_symlink_privilege(tmp_path):
    import subprocess
    source = tmp_path / "source"
    source.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (external / "secret.py").write_text("def forbidden(): pass\n", encoding="utf-8")
    link = source / "link"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(external)],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        pytest.skip("Junction creation unavailable")
    graph = build(source, {"good.py": "def allowed(): pass\n"})
    module = importlib.import_module("app.architecture.source_flow")
    graph = module.build_source_flow(source, {"file_tree": [
        {"path": "good.py", "kind": "file"}, {"path": "link/secret.py", "kind": "file"},
    ]})
    assert {f["path"] for f in graph.details["files"]} == {"good.py"}
    assert graph.details["warnings"]
    assert (external / "secret.py").exists()
