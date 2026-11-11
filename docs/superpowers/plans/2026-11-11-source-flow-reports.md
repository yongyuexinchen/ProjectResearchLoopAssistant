# Source flow diagrams and report integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Use the approved design and bounded parser interfaces below.

**Goal:** Automatically produce source-backed function/callsite diagrams and statement navigation for input repositories, and freeze them into online/MD/PDF reports.

**Architecture:** Python AST and Tree-sitter JS/TS parsers build a bounded, source-hashed static index. A new source_flow Graph stores that index in details and renders an entry-oriented diagram. Reports embed copies of diagrams and details at creation time; the browser renders saved Mermaid, PDF renders offline vector cards and arrows.

**Tech Stack:** Python 3.11+, ast, Tree-sitter, FastAPI/SQLAlchemy, Next.js/React/TypeScript, Mermaid, ReportLab.

**Spec:** ../../review-2026-11-11/自动源码流程图方案.md (approved in chat 2026-11-11).

## Global Constraints

- Read source text only; never execute input code. Python + JavaScript/TypeScript/TSX are the supported precise syntax parsers.
- File paths, function and statement lines, callsite lines and source hashes come from parsed source. Unknown dynamic calls remain unresolved.
- Apply path/sensitive/symlink rules and budgets. Record truncation, unsupported language and parse errors.
- Graph details and reports are JSON/Markdown snapshots scoped to selected run; regeneration must not re-read live source.
- Work in the user-specified local checkout; preserve existing user files. No push or automatic commit.

## Review Focus

1. A method receiver or alias is shadowed: do not connect to an unrelated same-name function.
2. A saved file tree points outside root or through a symlink: never read that target.
3. Graph truncation hides entries: describe limits and retain bounded searchable details.
4. A newer run or changed source exists: an older report continues to show its saved graph.
5. Mermaid/HTML-looking source text: escape labels and render code as text.

## Task 1 — bounded source parser and call graph

**Files:** create app/architecture/source_flow.py plus focused parser helpers; tests/test_source_flow.py; pyproject.toml and uv.lock for Tree-sitter.
**Interface:** build_source_flow(root: Path | None, codebase: dict) -> Graph | None. Graph.details contains version=1, files, functions, stats, limits, warnings. Functions contain id/path/name/qualified_name/line_start/line_end/parameters/docstring/statements/calls/entrypoint. Statements contain kind/label/line_start/line_end/excerpt; calls contain expression/line/column/target_id/resolution/reason. Files contain path/language/sha256/line_count. Stable identifiers include path and qualified name/location.

- [ ] Write and run failing tests for Python/JS/TS direct cross-file calls, aliases, duplicate names, class methods, async and internal syntax categories.
- [ ] Implement parser and conservative resolver; do not infer runtime data lineage from call references.
- [ ] Add and run budget, malformed syntax, symlink, traversal, unknown language and shadowing tests.
- [ ] Generate against current repository; inspect exact line samples and parse resulting Mermaid.

## Task 2 — persistence integration and source navigation

**Files:** graph_builder.py (Graph.details), service.py, mermaid.py if necessary, types/project.ts, architecture page and new source navigation component; regression tests.
**Consumes:** Task 1 interface. **Produces:** new source_flow diagram alongside current diagrams; saved details survive regeneration; user can search functions and inspect classified statements/calls.

- [ ] Write failing service/regeneration tests for source_flow and details isolation.
- [ ] Add details and new graph kind; preserve backward compatibility and safely validate saved details.
- [ ] Build searchable front-end function inspector and meaningful static-fact/unknown labels; avoid executing HTML from source.
- [ ] Run backend architecture tests, frontend tests and TypeScript check.

## Task 3 — report snapshots, browser and PDF

**Files:** services/reports.py, reports/renderer.py or new reports/architecture.py, reports/pdf.py, api/routes_reports.py, report page + reusable saved report diagram component; test_report_architecture.py.
**Consumes:** saved ArchitectureDiagram with source_flow details. **Produces:** immutable report diagrams stored under verifier_result_json.architecture_diagrams and Markdown chapter; PDF draws copies of saved graph data.

- [ ] Write failing tests for plain/intelligent report inclusion, run A/B, no-matching diagrams, graph mutation after snapshot, MD/PDF inclusion.
- [ ] Select diagrams by project and exact run_id; never use latest fallback for a historical report. Copy JSON/Mermaid before LLM enhancement and preserve diagram chapter.
- [ ] Render Mermaid in online report from copied snapshot; keep details accessible. Export PDF using ReportLab vector shapes, bounded/paginated labels and line-number keys; never a remote renderer.
- [ ] Run targeted reports/export tests and visually inspect a generated PDF.

## Task 4 — review and delivery

- [ ] Consolidate original audit results into severity-ordered Chinese report with baseline line references and reproduction scope.
- [ ] Independently review parser semantics, snapshot safety and rendering; correct actionable findings.
- [ ] Run full backend suite, frontend tests, type check and production build; inspect real project output and PDF.
- [ ] Update STATUS/ARCHITECTURE/README with current capabilities, supported languages and explicit static-analysis limits; report any unverified MySQL/crash behavior.
