# Reducer Audit — 2026-07-07 (Re-verified 2026-07-07)

## Summary

Verification of reducer list matching between current code and deployed module
(`spacetime-memory` database). **MISMATCH DETECTED — still unresolved.**

| Metric | Value |
|--------|-------|
| Code reducers (incl. `init`) | 191 |
| Deployed reducers | 183 |
| Real matches | 183 |
| Code-only (not deployed) | 7 real reducers |
| Deployed-only (not in code) | 0 |

## Reducers in code but NOT deployed

These 7 `#[reducer]` functions exist in the current source code but are NOT present
in the deployed WASM module. The module needs to be republished.

| # | Reducer | File | Added in commit |
|---|---------|------|-----------------|
| 1 | `auto_invalidate` | `memory.rs:494` | 96ae23dc |
| 2 | `cleanup_rate_limits` | `auth.rs:185` | 287d2123 |
| 3 | `get_backlinks` | `note.rs:339` | effb612c |
| 4 | `get_outgoing_links` | `note.rs:384` | effb612c |
| 5 | `get_peer_reputation` | `memory_feedback.rs:526` | 4da2a9a5 |
| 6 | `update_api_key` | `auth.rs:505` | 287d2123 |
| 7 | `verify_api_key` | `auth.rs:457` | 9c0c7019 |

## False positives (excluded)

- `my_reducer` — commented out example code in `tracing.rs` (not a real reducer)
- `init` — present in both code (`consolidation.rs:764`) and deployed, grep caught it under `#[reducer(init)]`

## Deployed-but-not-code

None. All 183 deployed reducers exist in code (including `init`).

## Recommendation

Publish the module to `spacetime-memory` database to bring it in sync with
the current codebase. The WASM was successfully built at
`target/wasm32-wasip1/release/spacetime_memory.wasm` (9.9 MB).
