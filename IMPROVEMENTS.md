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

---

## Recently Completed

### ✅ OpenTelemetry / observability integration
P0: Python SDK — DONE (Jun 24)
  - Tracer class, get_tracer(), start_span() context manager, instrument_method()
  - Optional OTLP HTTP export, graceful degradation when OTel packages absent
  - `otel` optional dependency group in pyproject.toml
  - Instrumented client.py: _call, _sql, _embed, _embed_openai, store, search, etc.
  - All 186 unit tests pass.
  Commit: 5398f8f
P1: Rust server module — DONE (Jun 24)
  - TracingSpan table (public), record_span() helper, trace_span! macro
  - Instrumented key reducers in memory.rs and hybrid_query.rs
  - `cargo check --target wasm32-unknown-unknown` passes.
  Commit: 54fe3ab

### ✅ Observability test fix — OTel cache pollution (Jun 24)
Tests that mock OTel modules install mock opentelemetry into sys.modules,
causing `_check_otel_available()` to cache `_OTEL_AVAILABLE=True` globally.
Subsequent tests fail with ModuleNotFoundError.
Fix: autouse fixture resets `_OTEL_AVAILABLE = None` before each test.
Re-runs clean: 44 passed, 1 skipped, 0 failed.
Commit: 91f1861

### ✅ .env stale config cleanup (Jun 24)
Removed vestigial EMBEDDER_TYPE env var from client.py, graphiti.py,
docs, and all scripts.
Commit: ec81a0b

### ✅ PyPI publish pipeline (Jun 24)
Package builds with correct packages-dir, twine verification step,
and __version__ attribute. v* tag triggers publish workflow.
Commit: e1ba6fe

### ✅ Knowledge graph visualization in frontend
Two visual graph explorers implemented and routed:
- **KnowledgeGraph** (`/graph`, vis-network): interactive graph with search,
  node selection, relation labels, community colors, PageRank, dendrogram.
- **GraphViz** (`/graph-viz`, D3-force): force-directed layout, type-based
  coloring, highlighting, filtering, minimap, node tooltips.
Both have Vitest smoke tests and navigation entries.
Routes: `/graph` and `/graph-viz` in App.tsx.

### ✅ Query expansion unit tests
`query_expansion.py` already has 31 unit tests covering:
- Basic expansion, custom endpoint/model, API key headers, timeout, temperature
- Content edge cases (too short, same as query, empty, None, whitespace)
- Reasoning model fallback (o1/deepseek-r1 style)
- Network errors (connect, timeout, protocol, HTTP 500, generic HTTP)
- Environment variable fallback chain
- Whitespace trimming, empty query
All pass cleanly as part of the 1805 unit test suite.

---

*(cron manages this section — moves items here when marked ✅, purges old ones)*
