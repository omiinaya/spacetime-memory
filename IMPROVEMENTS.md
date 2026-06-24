# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Status: PENDING

### STDB 2% fatal error under heavy concurrent load
Despite the UUID collision fix, some concurrent stress scenarios still
trigger WASM fatal errors. Need root cause analysis with replicator.

**Progress (Jun 24):** Added `uuid_v4_uniq()` helper in lib.rs with
collision-check + retry closure for any table. Migrated memory.rs,
change_event.rs, knowledge_graph.rs, and workspace.rs to use it.
Remaining tables (consolidation.rs, document.rs, etc.) still use
raw `uuid_v4()` without retry.
Files: server/spacetimedb/src/lib.rs, tests/concurrent/
Difficulty: Hard
Est: 4-8h

### Multi-region / failover support
No tests or code for multi-region STDB deployment. Need to document
and implement failover connectivity in the client SDK.
Files: client/spacetime_memory/client.py
Difficulty: Medium
Est: 4h

### Track STDB UniqueColumn::update() deprecation
STDB v2.6 still has `.id().update()` on UniqueColumn, but it may be
removed in a future version. Monitor upstream and plan delete+insert
migration when removal is confirmed.
Files: server/spacetimedb/src/*.rs (60+ call sites)
Difficulty: Easy (tracking)
Est: 0.5h

### Migrate to sortable UUID v7 for index performance
`ctx.new_uuid_v7()` is now stable in STDB v2.6 (behind `rand` default feature).
Sortable UUIDs improve B-tree index locality vs v4 random UUIDs.
Could replace or supplement `uuid_v4()` in lib.rs.
Files: server/spacetimedb/src/lib.rs
Difficulty: Medium
Est: 1-2h

### Extend uuid_v4_uniq() to remaining tables
The new `uuid_v4_uniq()` helper was added to lib.rs and deployed to
memory.rs, change_event.rs, knowledge_graph.rs, and workspace.rs.
Remaining tables that still use raw `uuid_v4()` for primary key inserts
without retry: consolidation.rs (10+ sites), document.rs (3 sites),
auth.rs (4 sites), note.rs, insight.rs, profile.rs, etc.
Files: server/spacetimedb/src/consolidation.rs, document.rs, auth.rs, ...
Difficulty: Medium
Est: 2-3h

### Unit test coverage for Rust helper functions
No Rust unit tests exist for `uuid_v4()`, `uuid_v4_uniq()`, `now_micros()`,
or `default_expires_at()`. These are pure functions (no STDB dependency)
and could be unit-tested on the host target.
Files: server/spacetimedb/src/lib.rs
Difficulty: Easy
Est: 0.5h

---

## Recently Completed

### ✅ Upgrade STDB dependency from 2.4 → 2.6 (Jun 24)
Successfully bumped and verified:
- spacetimedb resolved from 2.4.1 → 2.6.0
- `cargo check --target wasm32-unknown-unknown` passes (zero warnings)
- `UniqueColumn::update()` still present in v2.6 — no migration needed yet
- Fixed pre-existing unused import warning in knowledge_graph.rs
- `new_uuid_v4()` / `new_uuid_v7()` now stable behind default `rand` feature
Commit: d1d147f

### ✅ OpenTelemetry / observability integration (Jun 24)
P0: Python SDK — DONE
  - Tracer class, get_tracer(), start_span() context manager, instrument_method()
  - Optional OTLP HTTP export, graceful degradation when OTel packages absent
  - `otel` optional dependency group in pyproject.toml
  - Instrumented client.py: _call, _sql, _embed, _embed_openai, store, search, etc.
  - All 186 unit tests pass.
  Commit: 5398f8f
P1: Rust server module — DONE
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

### ✅ Knowledge graph visualization in frontend (Jun 24)
Two visual graph explorers implemented and routed:
- **KnowledgeGraph** (`/graph`, vis-network): interactive graph with search,
  node selection, relation labels, community colors, PageRank, dendrogram.
- **GraphViz** (`/graph-viz`, D3-force): force-directed layout, type-based
  coloring, highlighting, filtering, minimap, node tooltips.
Both have Vitest smoke tests and navigation entries.

### ✅ Query expansion unit tests (Jun 24)
`query_expansion.py` already has 31 unit tests covering:
- Basic expansion, custom endpoint/model, API key headers, timeout, temperature
- Content edge cases (too short, same as query, empty, None, whitespace)
- Reasoning model fallback (o1/deepseek-r1 style)
- Network errors (connect, timeout, protocol, HTTP 500, generic HTTP)
- Environment variable fallback chain
- Whitespace trimming, empty query
All pass cleanly as part of the unit test suite.

---

*(cron manages this section — moves items here when marked ✅, purges old ones)*
