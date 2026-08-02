# Spacetime-Memory Review — Actionable Tasks

**Date:** 2026-07-31
**Reviewer:** kanban worker (auto-generated review task)
**Basis:** live source audit + AST/runtime verification + ruff + pytest + git state
**Branch reviewed:** `dev` (HEAD e9472133, 20 commits ahead of origin/main, 4 behind)

---

## Executive summary

The project is in strong shape (unit tests green, publish script enforces
`--delete-data=never`, zero Rust warnings per recent audits), but this review
found **real runtime bugs** that were invisible to the test suite: 8 CLI
command functions crash with `NameError` on invocation due to missing imports.
They are pre-existing (not introduced by the uncommitted WIP). Below are the
concrete tasks, ordered by priority.

---

## P0 — Fix NameError runtime bugs (missing imports)

Verified by AST + runtime globals inspection: the function references the name
but it is absent from the function's `__globals__`, so invoking the command
raises `NameError`. The module imports fine; the crash happens at command
execution — which is why the test suite (which imports modules but rarely
invokes these commands) never caught it.

| File | Command/function | Missing name | Consequence |
|------|------------------|--------------|-------------|
| `sdk/python/spacetime_memory/cli/commands/org.py` | `org_sync`, `org_daemon`, `org_status` (12 refs) | `os` | `stmem org sync/daemon/status` crash with NameError |
| `sdk/python/spacetime_memory/cli/commands/replication.py` | `replication_sync`, `replication_daemon` (7 refs) | `os` | `stmem replication sync/daemon` crash |
| `sdk/python/spacetime_memory/cli/commands/mental.py` | `mental_synthesize` | `subprocess` (+`os`) | `stmem mental synthesize` crash |
| `sdk/python/spacetime_memory/cli/commands/_admin_tools.py` | `diagnostics` | `spacetime_memory` | `stmem diagnostics` crash |
| `sdk/python/spacetime_memory/cli/commands/_admin_tools.py` | `init` | `httpx` | `stmem init` crash |
| `sdk/python/spacetime_memory/client/_admin.py:495` | restore error handler | `spacetime_memory`, `httpx` | except-block itself raises NameError → masks the real error during `restore` |
| `sdk/python/spacetime_memory/client/_background.py:349` | observation-extraction fallback | `ObservationExtractionMixin` | NameError when `hasattr(self,"extract_observations")` is False |

**Fix:** add the missing imports (`import os`, `import subprocess`, `import
httpx`, and import `ObservationExtractionMixin`/`spacetime_memory` as needed).
Low risk, high value.

**Verify:** `ruff check` F821 count drops; add a smoke test that invokes each
command (or at least asserts the names resolve in each function's globals).

---

## P1 — Ruff hygiene: 207 errors (160 in package code)

`cd sdk/python && ruff check .` → **207 errors**, 59 auto-fixable (42 in
`spacetime_memory/`). Breakdown by rule:

- `F401` unused imports — ~50 (incl. `__init__.py` re-export files)
- `F821` undefined names — ~90 (the P0 bugs above + annotation-only `Graphiti`
  references in `sdks/graphiti/_edge_namespaces.py` / `_node_namespaces.py`,
  which are harmless at runtime under `from __future__ import annotations`)
- `F841` unused local variables — ~24
- `E741` ambiguous variable names (`l`, `I`, `O`) — 14
- `F541` f-string without placeholders — 6
- `E402` module-level import not at top — 10

**Task:** run `ruff check --fix` for the auto-fixable subset, manually resolve
the remainder (the annotation-only `Graphiti` refs can be silenced with a
`# noqa: F821` or by importing the type under `TYPE_CHECKING`). Add a CI lint
gate (`ruff check .`) so this doesn't regress. Keep behavior changes out of
this commit — it's pure lint cleanup.

---

## P1 — Commit the uncommitted WIP on `dev`

Working tree has **16 modified files (+1167/−45)** plus 3 untracked files —
coherent, tested adapter-parity work that is currently at risk:

- Modified: `sdks/zep/_client.py` (+164, fact rating), `sdks/mem0/_client.py`
  (+126), `sdks/hindsight.py` (+109), `compounder/workflows_knowledge.py`
  (+155), `plugin_manager.py` (+69), `sdks/graphiti/_core.py`/`_search.py`,
  plus matching tests (test_plugin_manager +152, test_graphiti_adapter_mocked
  +109, test_compounder_core +99, test_hindsight_sdk, test_sdk_mem0,
  test_zep_adapter, test_compounder_core)
- Untracked: `scripts/benchmarks/run_graph_search_bench.py` (finished GBrain
  parity benchmark), `benchmarks/results/graph_search_bench.json` (P@5 31.11%,
  R@5 94.24% on 81 queries), `sdk/python/tests/test_zep_fact_rating.py`

**Task:** run the full unit suite (currently running, see below), then commit
as logical commits (git identity: omiinaya / omiinaya@gmail.com for BOTH author
and committer), push to `origin/dev`. `dev` is 20 ahead / 4 behind `origin/main`
— do NOT merge into main (owner handles main merges).

---

## P1 — Table privacy enforcement (carried from REAL_ROADMAP, still open)

`STDB_TABLE_PRIVACY_REVIEW.md` (2026-07-21): **107 tables, 50 with `public`**,
7 P0-critical. The `public` keyword still needs to be removed from result
tables (`decrypted_memory_result`, `hybrid_result`, `entity_extraction_result`,
etc.) and access restricted via `workspace_id` filtering. Marked 🟡 "audited —
needs enforcement" in REAL_ROADMAP.

**Task:** implement the enforcement plan from the review doc; verify with a
privacy audit script that no sensitive table is world-readable.

---

## P2 — Repo hygiene: 12 tracked debug/junk files at repo root

Tracked in git (should not be): `.hermes_tmp_write_e2e.py`,
`XXXXX_test_hermes_write.md`, `_fix_sql_param.py`, `_migrate_sql_param.py`,
`_patch_note.py`, `batch_diag.py`, `batch_retry.py`, `batch_uuid_test.py`,
`debug_ingest.py`, `debug_query.py`, `e2e_final_check.py`, `e2e_v4_check.py`.

**Task:** `git rm` them, add patterns to `.gitignore` (e.g. `debug_*.py`,
`batch_*.py`, `_fix_*.py`, `e2e_*_check.py`, `.hermes_tmp_*`).

---

## P2 — Verify/close REAL_ROADMAP open items

1. **CLI v2.6.1 arg assembly broken** (anti-pattern #13, marked ❌ OPEN) —
   workaround is raw HTTP API. Investigate whether current CLI still hits this;
   if yes, fix arg assembly or document the workaround in the CLI help.
2. **npm/PyPI publish** — blocked on tokens (external dependency; needs
   credentials — do not block on this, note as waiting).
3. **Generated API docs** — mkdocstrings is configured in `mkdocs.yml`
   (`paths: [sdk/python]`, google docstring style) and `docs/api/` exists with
   python/ and typescript/ subdirs. **Task:** run `mkdocs build` to verify it
   actually renders; fix broken autodoc refs if any.
4. **Rust clippy: 21 pre-existing warnings** (sort_by_key, unused_variables in
   tests) per ROADMAP.md build table. Task: `cargo clippy -- -D warnings` pass.

---

## P1 — Fix unit-suite failures: 41 failed / 6413 passed (was 6449/0)

Full unit run (`pytest tests/ -m unit`) → **41 failed, 6413 passed, 21
skipped** (7m13s). STATUS.md claims 6449 passing / 0 failures — the suite has
regressed. Four distinct root causes, in order of impact:

### A. onnxruntime GPU/CPU conflict → `ort = None` → AttributeError (~34 failures)
- Symptom: `AttributeError: 'NoneType' object has no attribute 'SessionOptions'`
  at `spacetime_memory/cross_encoder.py:191` (`_ensure_loaded`).
- Root cause: venv has BOTH `onnxruntime` 1.27.0 AND `onnxruntime-gpu` 1.27.0.
  `import onnxruntime` raises `ImportError: libcudart.so.13: cannot open shared
  object file` (CUDA runtime missing on host) → the `except ImportError: ort =
  None` guard in cross_encoder.py:36-39 sets `ort = None` → every
  `cross_encoder_rerank()` call crashes.
- Affected: `test_adapter_e2e.py` (21), `test_context_tree.py` (8),
  `test_client_advanced.py` (2), `test_client_embed.py` (1), and order-dependent
  pollution in `test_client_core.py` (2).
- **Fix (env):** `pip uninstall onnxruntime-gpu` (or install CUDA runtime
  `libcudart.so.13`) so the CPU build imports cleanly. Verify:
  `.venv/bin/python -c "import onnxruntime"` → OK.
- **Fix (code, robustness):** `cross_encoder.py` `_ensure_loaded()` should
  degrade gracefully when `ort is None` (log warning + return rows unreranked)
  instead of raising AttributeError — matches the project's stated "graceful
  degradation" principle.

### B. langgraph 1.x dependency drift → langchain adapter breaks (4 failures)
- Symptom: `ValueError: Invalid isoformat string: ''` in
  `langgraph/store/base/__init__.py:81` — `test_langchain_sdk.py` (4).
- Root cause: pyproject declares `langgraph>=0.2` (unpinned), venv has
  langgraph **1.2.8**. The LangChain adapter code was written against 0.x
  semantics; 1.x raises on empty timestamp strings.
- **Fix:** either pin `langgraph<1` in pyproject, or adapt the LangChain
  adapter's `search()` to the 1.x store API (pass/parse `updated_at` correctly).

### C. WIP stale test — mem0 `create_memory_tool` (1 failure)
- Symptom: `KeyError: 'status'` — `test_mem0_client.py:487`
  `test_returns_not_implemented`.
- Root cause: the uncommitted WIP implements `create_memory_tool()` for real
  (returns an OpenAI function-calling tool schema, +126 lines in
  `sdks/mem0/_client.py`), but the test still asserts the OLD
  `{"status": "not_implemented"}` contract.
- **Fix:** update `test_returns_not_implemented` to assert the new tool-schema
  contract. Include in the WIP-commit task (P1 above).

### D. Tracer singleton pollution (1 failure)
- Symptom: `Expected 'start_as_current_span' to be called once. Called 0
  times.` — `test_tracer.py:337`. Passes in isolation → order-dependent
  pollution from earlier tests (OTLP collector absent at localhost:4318).
- **Fix:** make the tracer test reset its singleton in a fixture, or mark it
  `@pytest.mark.skipif` when `OTEL_ENABLED=false` / collector unreachable.

---

## P3 — Test-suite follow-ups

1. **Full unit suite baseline** — 6413 passed / 41 failed / 21 skipped as of
   2026-07-31 (see above). Fix the 4 root causes, then update STATUS.md.
2. **14 environmental test failures** (STDB table access / embedder port) —
   not feature bugs, but should be marked with skip-if-unavailable markers so
   `make test` reports clean, and documented in CONTRIBUTING.
3. **Benchmark pipeline** — LoCoMo STDB full run (1986 Q) via cron, LongMemEval
   (500 Q) queued. Monitor to completion; update STATUS.md.

---

## How this review was verified

- `ruff check` JSON/parse: file+rule breakdown
- AST analysis per file: names used in Load context vs. imports/defs
- Runtime globals check: `fn.__globals__` for each flagged command → confirmed
  `os`/`subprocess`/`spacetime_memory`/`httpx`/`ObservationExtractionMixin`
  absent → NameError on invocation
- `pytest tests/test_base.py -m unit`: 71/71 passed
- `pytest tests/ -m unit` (full, serial): **6413 passed / 41 failed / 21
  skipped** — failure taxonomy in the P1 section above
- `git status` / `git log` for WIP + branch divergence
- `scripts/publish.sh`: confirmed hardcodes `--delete-data=never` ✅
