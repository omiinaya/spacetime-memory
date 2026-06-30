# Spacetime Memory — Improvement Backlog (June 29, 2026 — FRESH AUDIT)

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Pending (June 29 Audit — 18 New Items)

### P0: Rust — Fix duplicate `require_auth()` in context_directory.rs (7 reducers)
Each of the 7 reducers in context_directory.rs calls `require_auth(ctx)?;` TWICE — a copy-paste bug.
Fix: remove the second redundant call from each reducer.
Files: server/spacetimedb/src/context_directory.rs
Difficulty: Easy
Est: 10min

### P0: Rust — Add `.take(MAX_RESULTS)` to 8+ unbounded `.iter()` calls
Critical for production safety. Every unbounded iter risks reducer timeout/OOM on large tables.
Affected files: consolidation.rs, context_delta.rs, memory_feedback.rs, context_directory.rs, graph_traversal.rs, knowledge_graph.rs
Files: server/spacetimedb/src/consolidation.rs, context_delta.rs, memory_feedback.rs, context_directory.rs, graph_traversal.rs, knowledge_graph.rs
Difficulty: Medium
Est: 1-2h

### P0: Rust — Fix "reader" → "viewer" in knowledge_graph.rs:1143
Invalid permission string "reader" — the valid levels are "owner", "editor", "viewer".
This permission check will always fail (rank=0 for unknown string).
Files: server/spacetimedb/src/knowledge_graph.rs:1143
Difficulty: Easy
Est: 2min

### P1: Rust — Replace uuid_v7().expect() with graceful fallback in lib.rs:125
Panics in WASM if STDB RNG fails. Replace with `.unwrap_or_else(|| uuid_v4(ctx))`.
Files: server/spacetimedb/src/lib.rs:125
Difficulty: Easy
Est: 5min

### P1: Rust — Add logging to 4 silent `serde_json::from_str().unwrap_or_default()` calls
These silently swallow parse errors with zero logging in profile.rs (73, 110), entity_linking.rs (62), hybrid_query.rs (125).
Files: server/spacetimedb/src/profile.rs, entity_linking.rs, hybrid_query.rs
Difficulty: Easy
Est: 15min

### P1: Python — Eliminate 18+ silent `except RuntimeError: pass` blocks
These mask real failures in store(), store_batch(), create_note(), update_note(), entity extraction, restore, and more.
Replace with at minimum logger.debug() or logger.warning().
Files: sdk/python/spacetime_memory/client.py
Difficulty: Medium
Est: 1h

### P1: TypeScript — Fix SQL injection vulnerability
All SQL queries use raw string interpolation with single-char `esc()` function.
Doesn't handle backslash escapes, Unicode attacks, or other injection vectors.
Files: sdk/typescript/client.ts
Difficulty: Medium
Est: 30min

### P1: TypeScript — Publish to npm
npm publish workflow exists but NPM_TOKEN hasn't been set in GitHub secrets.
Files: sdk/typescript/package.json, .github/workflows/npm-publish.yml
Difficulty: Easy
Est: 15min

### P1: Publish benchmark scores (LongMemEval, LoCoMo, BEAM)
Biggest credibility gap vs Mem0, Hindsight, Supermemory.
Files: scripts/benchmark.py (exists, needs integration)
Difficulty: Hard
Est: 1-2 weeks

### P2: Python — Route 5 direct-HTTP methods through retry circuit
ping(), check_embedder_health(), _tantivy_index(), _tantivy_search(), _embed_openai()
all use self._http.get/post directly instead of _request_with_retry().
Files: sdk/python/spacetime_memory/client.py
Difficulty: Medium
Est: 30min

### P2: Python — Add 77 missing Rust reducers to SDK
Auth (9), replication (10), sessions (5), peers (3), connectors (3), messages (2),
harmonics (3), change events (3), context deltas (2), + ~37 miscellaneous.
Files: sdk/python/spacetime_memory/client.py + Rust files
Difficulty: Hard
Est: 4-8h

### P2: TypeScript — Eliminate 38 `any` usages
Replace `Promise<any[]>` with typed interfaces. Add proper return types for all 71 methods.
Files: sdk/typescript/client.ts
Difficulty: Medium
Est: 1h

### P2: TypeScript — Add JSDoc to 70/71 public methods
Currently only 1 method (storeBatch) has JSDoc. 1.4% coverage.
Files: sdk/typescript/client.ts
Difficulty: Medium
Est: 30min

### P2: Add E2E / deep test marker + 10 tests
No E2E test coverage at all. Create deep marker, write integration tests for critical paths
(store → search, create node → query graph, create note → get backlinks).
Files: sdk/python/tests/
Difficulty: Medium
Est: 4h

### P2: Remove 168MB stale `.upstream-venv/`
Size: 168MB. Likely has stale packages.
Files: .upstream-venv/
Difficulty: Easy
Est: 10min

### P3: Python — Move 15+ function-level imports to module top
Style violation: import random, import time, import json, import secrets, etc.
inside function bodies across client.py.
Files: sdk/python/spacetime_memory/client.py
Difficulty: Easy
Est: 30min

### P3: Python — Replace 6 `Any` type annotations with proper Protocols
plugin_manager: Any, event_bus: Any, query_cache: Any, local_llm: Any,
self._metrics: Any. These should be typed Protocols/ABCs.
Files: sdk/python/spacetime_memory/client.py
Difficulty: Medium
Est: 30min

### P3: Bi-temporal fact tracking — Graphiti-style temporal facts
Graphiti's strongest differentiator. Needs: fact valid_from/valid_to columns + auto-invalidation reducer.
Files: server/spacetimedb/src/profile.rs
Difficulty: Hard
Est: 1 week

## Deferred / Blocked

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
