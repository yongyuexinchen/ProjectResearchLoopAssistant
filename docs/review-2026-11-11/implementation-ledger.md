# Implementation ledger

Plan: docs/superpowers/plans/2026-11-11-source-flow-reports.md
Baseline: 6b66b51c357fc893bb52c4d22d34777d09af4125
Design approved in chat: Python + JS/TS source graphs, reports online/MD/PDF.

Ruling: Use the explicitly named local checkout on a dedicated codex/source-flow-reports branch. No automatic commits, merges or pushes.
Ruling: AST references are static facts; runtime ordering, object dispatch, cross-HTTP data lineage remain unverified and must not be drawn as resolved calls.

- Task 1 parser/index: complete. Python AST + Tree-sitter JS/TS/TSX; lexical binding resolver; budgets; path/symlink/sensitive filtering; recoverable Tree-sitter errors retained with warnings.
- Task 2 integration/navigation: complete. `source_flow` diagram populated from saved source index; front-end search and statement/call navigation; legacy diagrams tolerated.
- Task 3 report snapshots/export: complete. Exact-run diagram copy in `verifier_result_json.architecture_diagrams`; Markdown chapter; online Mermaid; offline ReportLab vector diagrams; report actions bind displayed run.
- Task 4 audit/review/verification: complete for this feature. Full backend/frontend/build and a real OSIRIS report/PDF were verified; separate audit findings remain out of scope.

Local verification after continuation:

- Backend: 411 passed, 2 skipped.
- Frontend: 19 passed; TypeScript exit 0.
- Production build: passed with a temporary `.next-*` dist; temporary dist removed.
- Real repository: OSIRIS produced 500 files, 2400 functions, 8613 calls; report 117,839 chars; PDF 42 pages with vector cards.
- No real model call in this continuation; no MySQL concurrency/crash test claimed.

Continuation fixes for the audit items named in the delivery summary:

- IF-01: report review locks the project row, rejects active runs, makes repeated follow-up review idempotent, and prevents historical reports from changing current project state or enqueueing.
- IF-02: `source_snapshots`, `codebase_maps`, and `source_bundles` carry nullable `run_id`; collection binds the worker run; report/context/architecture use `run_scope.py`; Alembic revision `20261111_0016` applied locally.
- IF-04/05: web collection checks DNS/IP against non-public targets and every redirect; streamed responses stop at a byte budget; private targets require `WEB_ALLOW_PRIVATE_HOSTS=true`.
- IF-06: malformed IPv6 URIs are converted to `SourceValidationError` instead of a 500.
- Report payload: report APIs omit source-index details; the online report fetches `/reports/{id}/source-index` only after the user clicks “按需加载源码逐段导航”. OSIRIS report HTML dropped from ~6.1 MB to ~559 KB.

Known limits:

- Only Python and JS/TS/TSX have precise syntax parsing; Go/Java are reported as unsupported for the fine-grained source graph.
- Source index is bounded and may truncate at 500 files / 2400 functions; warnings and counts are persisted.
- Path aliases, CommonJS `require`, constructor calls and dynamic dispatch remain unresolved by design.
- This task did not fix the separate worker fencing/cancellation/checkpointer findings or evidence-chain/readme-fallback findings from the audit.
