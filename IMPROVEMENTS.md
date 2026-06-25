# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Status: PENDING

### Track STDB UniqueColumn::update() deprecation
**RESOLVED: UniqueColumn::update() is NOT deprecated in STDB v2.6.0.**  
Source code review of STDB 2.6.0 confirms that `update()` on `UniqueColumn` is
still the standard upsert mechanism. No deprecation warning or removal
notice exists. Item kept for periodic re-check but moved to low priority.
Files: server/spacetimedb/src/*.rs (50+ call sites)
Difficulty: Easy (tracking)
Est: 0.5h
Status: Research complete — no action needed

### Fix non-standard UUID format (8-4-4-4-8 → standard 8-4-4-4-12)
Discovered during unit test work: `format_uuid_v4()` produces a legacy
28-hex-char UUID (8-4-4-4-8, 112 bits) instead of the standard 32-hex-char
format (8-4-4-4-12, 128 bits). The upper 4 hex digits from `high` are
unused. The new `uuid_v7()` function in lib.rs outputs standard format
via `ctx.new_uuid_v7().to_string()`. The legacy `format_uuid_v4()` still
has this quirk but is now only used by the original `uuid_v4()` path.

Status: Addressed for UUID v7 path. Legacy v4 path still non-standard.
Requires data migration to fix existing stored UUIDs.
Files: server/spacetimedb/src/lib.rs
Difficulty: Medium
Est: 1h (plus migration planning)

### STDB 2% fatal error under heavy concurrent load (deferred for live STDB)
**uuid_v4_uniq mitigation is complete** — all 27 primary-key inserts use
collision-retry. The remaining ~2% fatal errors appear to be a STDB-level
WASM limitation (not UUID-related). Root cause analysis requires a live
STDB instance with replicator stress testing. Deferred until live STDB
infrastructure is available for investigation.
Files: server/spacetimedb/src/lib.rs, tests/concurrent/
Difficulty: Hard (needs live STDB)
Est: N/A (blocked)

---

## Recently Completed

### ✅ Migrate all uuid_v4() call sites to uuid_v7() for sortable UUIDs (Jun 24)
Replaced `uuid_v4(ctx)` with `uuid_v7(ctx)` at all 57 non-retry call sites
across 21 source files. Uses `ctx.new_uuid_v7().to_string()` which produces
standard 8-4-4-4-12 format UUIDs with time-ordered prefixes for better
B-tree index locality. Remaining `uuid_v4(ctx)` calls in lib.rs are inside
`uuid_v4_uniq()` (the v4 retry wrapper) and are intentionally preserved.
Commit: pending

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

### ✅ STDB dependency upgrade 2.4 → 2.6 (Jun 24)
Commit: d1d147f

### ✅ OpenTelemetry / observability integration (Jun 24)
P0: Python SDK + P1: Rust server module.
Commits: 5398f8f, 54fe3ab

### ✅ Observability test fix — OTel cache pollution (Jun 24)
Commit: 91f1861

### ✅ .env stale config cleanup (Jun 24)
Commit: ec81a0b

### ✅ PyPI publish pipeline (Jun 24)
Commit: e1ba6fe

---

*(cron manages this section — moves items here when marked ✅, purges old ones)*
