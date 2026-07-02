# Spacetime Memory — Improvement Backlog (July 1, 2026)

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Pending

### P3: `harmonic_belief` reducers — SDK method coverage
`store_harmonic_beliefs`, `clear_harmonic_beliefs`, `log_resonance_session`
reducers in `harmonic_belief.rs` lack Python SDK and TypeScript SDK wrappers.
Files: sdk/python/spacetime_memory/client.py, sdk/typescript/client.ts
Difficulty: Easy
Est: 15min

### P3: `entity_linking` reducers — SDK method coverage (CHECK — may already have methods)
`create_entity_link`, `add_alias`, `resolve_entity` reducers in
`entity_linking.rs` need Python and TypeScript SDK wrappers.
Files: sdk/python/spacetime_memory/client.py, sdk/typescript/client.ts
Difficulty: Easy
Est: 10min

---

## Recently Completed

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

### P3: Enhanced `dedup_memories` — merge tags, KG edges, entities (July 1, 2026)
Enhanced the `dedup_memories` reducer to fully migrate MemoryTag associations,
KG edges and entities_json arrays from the duplicate to the survivor.
Commit: 82c30702
Difficulty: Medium
Est: 30min

### P2: Time-weighted memory retrieval — `temporal_search_with_weight` (July 1, 2026)
Added new `temporal_search_with_weight` reducer. Commit: fa97ee0d
Difficulty: Medium
Est: 1-2h

### P3: Add `batch_delete_memories` reducer + SDK methods (July 1, 2026)
Bulk deletion reducer + Python + TS SDK wrappers. Commit: 09da711a
Difficulty: Medium
Est: 15min

### P2: Python `batch_update_memories` SDK method (July 1, 2026)
Verified exists at line 2705. Item was stale. Difficulty: Easy
Est: 5min

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
