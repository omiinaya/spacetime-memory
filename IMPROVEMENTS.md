# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Status: PENDING

### STDB 2% fatal error under heavy concurrent load
Despite the UUID collision fix, some concurrent stress scenarios still
trigger WASM fatal errors. Need root cause analysis with replicator.
Files: server/spacetimedb/src/lib.rs, tests/concurrent/
Difficulty: Hard
Est: 4-8h

### Multi-region / failover support
No tests or code for multi-region STDB deployment. Need to document
and implement failover connectivity in the client SDK.
Files: client/spacetime_memory/client.py
Difficulty: Medium
Est: 4h

### Upgrade STDB dependency from 2.4 → 2.6
STDB v2.6.0 is available on crates.io (currently pinned at "2.4", resolves to 2.4.1).
Key changes to audit:
- UUID generation (v4/v7) stabilized — no longer behind `unstable` feature flag
- `ProcedureContext` methods (`sleep_until`, `with_tx`, `try_with_tx`) now take `&mut self`
- `update()` method removed from `UniqueIndex` — migrate to delete + insert pattern
- Edition 2024, minimum Rust version bumped to 1.93.0
- `new_uuid_v4()` / `new_uuid_v7()` now return `Result` (previously `anyhow::Result`)
Files: server/spacetimedb/Cargo.toml, server/spacetimedb/src/*.rs
Difficulty: Medium
Est: 2-3h

### Missing unit tests for expand_query / query expansion
The `query_expansion.py` module lacks direct unit test coverage.
Files: sdk/python/spacetime_memory/query_expansion.py, sdk/python/tests/test_query_expansion.py
Difficulty: Easy
Est: 1h

---

## Recently Completed

### ✅ OpenTelemetry / observability integration
P0: Python SDK — DONE (Jun 24)
  - Created sdk/python/spacetime_memory/tracer.py: Tracer class, get_tracer(),
    start_span() context manager, instrument_method() decorator, optional
    OTLP HTTP export, graceful degradation when OTel packages absent.
  - Added `otel` optional dependency group in pyproject.toml.
  - Exported Tracer/get_tracer/start_span from __init__.py.
  - Instrumented client.py: _call (all reducer calls), _sql, _embed,
    _embed_openai, _embed_batch, _embed_batch_openai, check_embedder_health,
    store (reducer call), store_batch (reducer call), search (hybrid search).
  - All 186 unit tests pass.
  Commit: 5398f8f
P1: Rust server module — DONE (Jun 24)
  - Created server/spacetimedb/src/tracing.rs: `TracingSpan` table (public),
    `record_span()` helper, `trace_span!` macro for automatic timing.
  - Instrumented key hot-path reducers: `store_memory`, `store_memory_batch`,
    `update_memory`, `deactivate_memory`, `expire_memories` (in memory.rs),
    and `hybrid_search` (in hybrid_query.rs).
  - Spans recorded to both `log::info!()` (STDB host logging) and the
    queryable `TracingSpan` table for dashboard/observability use.
  - `cargo check --target wasm32-unknown-unknown` passes (0 errors).
  - Reference: SpacetimeDB v2.4 SDK logging API + custom metrics table.
  Commit: 54fe3ab

### ✅ .env stale config cleanup
EMBEDDER_TYPE=local/openai/auto had no effect since the codebase migrated
to the OpenAI-compatible proxy path. Removed vestigial env var from
client.py, graphiti.py, all docs, example files, and scripts.
Commit: ec81a0b
Date: 2026-06-24

### ✅ PyPI publish pipeline
Package is built, wtih correct packages-dir, twine verification step,
and __version__ attribute. Pushing a v* tag triggers the publish workflow.
Fixed: publish.yml packages-dir path, added twine check, added __version__
to spacetime_memory/__init__.py, updated publish guide.
Commit: e1ba6fe
Date: 2026-06-24

### ✅ Knowledge graph visualization in frontend
The KG works (<20ms) and now has TWO visual graph explorers:
- **KnowledgeGraph** (`/graph`, vis-network based): full interactive graph
  with search, node selection, relation labels, community colors, zoom/pan,
  and statistics panel. Supports PageRank, hierarchy, and dendrogram views.
- **GraphViz** (`/graph-viz`, D3-force based): force-directed layout with
  type-based coloring, highlighting, filtering, minimap, and node tooltips.
Both are lazy-loaded, have Vitest smoke tests, and are linked from the nav bar.
Routes: `/graph` and `/graph-viz` in App.tsx.
Commits: d3b1c9a, f7e2a4b, and earlier

### ✅ Observability test fix — OTel cache pollution
Tests that mock OTel modules (test_console_exporter_path, etc.) install mock
opentelemetry into sys.modules, causing `_check_otel_available()` to cache
`_OTEL_AVAILABLE=True` globally. Subsequent tests then fail with
ModuleNotFoundError on real OTel imports.

Fix: autouse fixture resets `_OTEL_AVAILABLE = None` before each test,
restoring test isolation. Re-runs clean: 44 passed, 1 skipped (OTel not
installed), 0 failed.
Commit: 91f1861
Date: 2026-06-24

---

*(cron manages this section — moves items here when marked ✅, purges old ones)*
