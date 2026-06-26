# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Status: PENDING

### STDB 2% fatal error under heavy concurrent load (deferred for live STDB)
**uuid_v4_uniq mitigation is complete** — all 27 primary-key inserts use
collision-retry. The remaining ~2% fatal errors appear to be a STDB-level
WASM limitation (not UUID-related). Root cause analysis requires a live
STDB instance with replicator stress testing. Deferred until live STDB
infrastructure is available for investigation.
Files: server/spacetimedb/src/lib.rs, tests/concurrent/
Difficulty: Hard (needs live STDB)
Est: N/A (blocked)

### Track STDB UniqueColumn::update() deprecation
**RESOLVED: UniqueColumn::update() is NOT deprecated in STDB v2.6.0.**  
Source code review of STDB 2.6.0 confirms that `update()` on `UniqueColumn` is
still the standard upsert mechanism. No deprecation warning or removal
notice exists. Item kept for periodic re-check but moved to low priority.
Files: server/spacetimedb/src/*.rs (50+ call sites)
Difficulty: Easy (tracking)
Est: 0.5h
Status: Research complete — no action needed

---

## Recently Completed

### ✅ format_uuid_v4() now outputs standard 32-hex-char UUID (Jun 25)
Previously `format_uuid_v4()` produced a non-standard 28-hex-char format
(8-4-4-4-8, 112 bits) where the upper 4 hex digits from the `high` u64
were discarded. Now produces standard RFC 4122 v4 UUIDs (8-4-4-4-12, 128 bits).
Commit: 5c98d30

### ✅ Knowledge Compounder — all 7 patterns implemented (Jun 25)
Compounder operations now use real reducers (``create_edge``, ``update_node``).
``lint_workspace()`` auto-creates contradiction notes. Full 30-test suite.
Commits: 62834b3, 39f6f01, 6ba5195, dad454b

### ✅ update_node reducer added to Rust module (Jun 25)
New ``#[reducer] pub fn update_node(...)`` in ``knowledge_graph.rs``.
Updates label, type, summary, metadata_json, source_memory_id on an
existing KG node. Uses ``ctx.db.kg_node().id().update()`` — preserves
ID, workspace, community, embedding, and timestamps.
Commit: dad454b

### ✅ Knowledge Compounder — persist answers as wiki pages (Jun 24)
New ``Compounder`` class (``client.compounder``) that implements the
LLM Wiki pattern: every search synthesis becomes a persistent note + KG
nodes + index entry, so knowledge compounds rather than disappearing
into chat history. Methods: ``store_answer()``, ``cross_link()``,
``suggest_connections()``. 20 unit tests. All 1700 unit tests pass.
Commits: 62834b3, 53f2f86

### ✅ tracer.py 51% → 100% coverage (Jun 24)
35 new unit tests covering _NoOpSpan, _check_otel_available(), Tracer
init/setup/is_enabled/start_span/instrument_method, get_tracer(), and
module-level start_span(). Needed: mock OTel SDK hierarchy for the
full setup() path, auto-mock-module pattern for sub-imports.
Commit: 62834b3

### ✅ Migrate all uuid_v4() call sites to uuid_v7() for sortable UUIDs (Jun 24)
Replaced `uuid_v4(ctx)` with `uuid_v7(ctx)` at all 57 non-retry call sites
across 21 source files. Uses `ctx.new_uuid_v7().to_string()` which produces
standard 8-4-4-4-12 format UUIDs with time-ordered prefixes for better
B-tree index locality. Remaining `uuid_v4(ctx)` calls in lib.rs are inside
`uuid_v4_uniq()` (the v4 retry wrapper) and are intentionally preserved.
Commit: cc3f49a

### ✅ Multi-region / failover support (Jun 24)
Added `SPACETIMEDB_HOSTS` env var for comma-separated host:port pairs.
`_try_failover()` cycles to next host on connection failure.
`_request_with_retry` fails over after all retries exhausted.
`_ensure_identity` probes all hosts, pins to first responsive one.
6 new tests. Backward compatible.
Commit: b595739

### ✅ uuid_v7() + uuid_v7_uniq() build-block functions (Jun 24)
Added `uuid_v7()` (returns `ctx.new_uuid_v7().to_string()`) and
`uuid_v7_uniq()` (with collision retry) to lib.rs. Runs alongside
existing v4 functions. Standard 8-4-4-4-12 UUID format.
Commit: 202e47f

### ✅ Extend uuid_v4_uniq() to remaining tables (Jun 24)
All 27 no-longer-raw `uuid_v4()` call sites migrated in consolidation.rs,
auth.rs, insight.rs, profile.rs, replication.rs. Zero compiler warnings.
Commit: 6cdb64d

### ✅ Unit test coverage for Rust helper functions (Jun 24)
Extracted pure computation helpers (`format_uuid_v4`, `micros_from_timestamp`,
`compute_expires_at`) from context-dependent functions and added 21 tests.
All 156 unit tests pass. WASM build check passes.
Commits: 7bb4ff3

---

*(cron manages this section — moves items here when marked ✅, purges old ones)*
