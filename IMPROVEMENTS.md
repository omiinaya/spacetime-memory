# Spacetime Memory — Improvement Backlog (July 2, 2026)

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Recently Completed

### P3: Add `create_insight` + `delete_insight` typed Python SDK methods (July 17, 2026)
Added `InsightMixin` in `sdk/python/spacetime_memory/client/_insights.py` with
`create_insight()` and `delete_insight()` typed methods and wired the mixin into
the composite `Client` class. Verified the module imports cleanly.
Files: sdk/python/spacetime_memory/client/_insights.py, sdk/python/spacetime_memory/client/__init__.py
Difficulty: Easy
Est: 10min

---

## Pending

*(No pending items at this time.)*

---

## Deferred / Blocked

### P2: NoteRecord TS interface — missing fields (July 13, 2026)
Added 4 missing fields to NoteRecord TS interface: `embedding_json`,
`backlink_count`, `block_ref_count`, `version`. `note_date` was already
present. Commit: 92c1f6ac

### P3: Python SDK — user management wrappers (add_user, get_user, update_user, delete_user, list_users, get_user_sessions) (July 2, 2026)
Added 6 typed methods to `Client` covering all user CRUD reducers from
`user.rs`. Each follows the reducer + SQL-read pattern used by existing
SDK methods. Includes `get_user_sessions` with result table SELECT.
Commit: 337e2a05
Files: sdk/python/spacetime_memory/client.py
Difficulty: Easy
Est: 20min

### P2: Dynamic OTel Prometheus metrics reader — add_metric_reader/remove_metric_reader runtime APIs (July 2, 2026)
Added `setup_otel_metrics()` that creates OTel instruments and registers an
`InMemoryMetricReader` via `MeterProvider.add_metric_reader()` for live
metric collection in agent runner environments. Includes `collect_otel_metrics()`,
`remove_otel_metric_readers()`, and runtime status checks. Supports custom
readers (e.g. `PeriodicExportingMetricReader` for OTLP export).
Commit: ba8b6f24
Files: sdk/python/spacetime_memory/metrics.py, __init__.py, tests/test_metrics.py
Difficulty: Medium
Est: 30min

### P3: Add connector, entity_extraction, harmonic_belief SDK wrappers + CLI commands (July 1, 2026)
Added full SDK + CLI coverage for 7 reducers across three modules that were
missing typed wrappers: connector (register/update/delete), entity extraction,
and harmonic beliefs (store/clear/log). New CLI commands: `connector update`,
`connector delete`, `entity extract`, `harmonic store`, `harmonic clear`,
`harmonic log`. Updated `connector register` to use typed SDK methods.
Commit: 98d04717
Files: cli/stmem.py, sdk/python/spacetime_memory/client.py, sdk/typescript/client.ts
Difficulty: Easy
Est: 15min

### P3: `search_by_tags` — tag-filtered search (July 1, 2026)
Added `search_by_tags` reducer in hybrid_query.rs that finds memories with
ALL specified tags (AND intersection), optionally ranks by cosine similarity
when a query embedding is provided, and writes results to `hybrid_result`
with strategy "tagged". Python SDK `search_by_tags()` and TypeScript SDK
`searchByTags()` methods included.
Commit: c05054be
Files: server/spacetimedb/src/hybrid_query.rs, sdk/python/spacetime_memory/client.py,
  sdk/typescript/client.ts
Difficulty: Medium
Est: 1h

### P2: Optimize semantic strategy in hybrid_search reducer — 5s → sub-second (July 1, 2026)
Moved cosine similarity computation from WASM reducer to Python client-side.
The reducer semantic strategy (iterating search_index, parsing 1024-dim embeddings,
individual memory lookups) was ~85ms/row in STDB. Python client-side: fetch
search_index via SQL, compute cosine similarity in pure Python, inject into
per_strat['semantic'] for fusion. Reducer fallback kept if embedder is down.
Commit: 5ea553c7
Files: sdk/python/spacetime_memory/client.py, server/spacetimedb/src/hybrid_query.rs
Difficulty: Medium
Est: 2-3h

### P3: Add `batch_tag_memories` + `batch_untag_memories` reducers + SDK methods (July 1, 2026)
Eliminates O(n) network round-trips for bulk tagging/untagging operations.
Commit: 4a1b3bd3
Difficulty: Medium
Est: 20min

---

## Deferred / Blocked

### P1: TypeScript — Publish to npm (BLOCKED — needs GitHub secrets)
npm publish workflow exists but NPM_TOKEN hasn't been set in GitHub secrets.
Files: sdk/typescript/package.json, .github/workflows/npm-publish.yml
Difficulty: Easy
Est: 15min

### STDB 2% fatal error under heavy concurrent load (BLOCKED — no live STDB for stress testing)
Remaining root cause appears to be STDB-level WASM limitation.
Deferred until live STDB infrastructure is available.
Files: server/spacetimedb/src/lib.rs, tests/concurrent/
Difficulty: Hard

### Frontend / Web UI (BLOCKED — not started, 1-2 week effort)
Zero web UI code exists. React/Vite SPA needed for dashboard, workspace management, KG explorer, note editor.
No code to block on — just not started.
Difficulty: Hard

### No managed cloud (BLOCKED — strategic decision, not code)
Every competitor has a managed option. Self-hosting is correct for current use case.
Difficulty: Hard
