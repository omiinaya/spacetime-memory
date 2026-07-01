# Spacetime Memory — Improvement Backlog (July 1, 2026)

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Pending

### P2: Optimize semantic strategy in hybrid_search reducer — 5s → sub-second
The `semantic` strategy in the WASM reducer iterates `search_index` table and computes
cosine similarity for every row individually (60 memories × ~85ms each = 5s).
Each row parses full 1024-dim embedding JSON, computes cosine similarity, then does
a memory lookup for trust_score and context. Fix options:
(a) Client-side cosine similarity: fetch search_index, compute in Python, skip reducer
(b) Batch embedding comparison in WASM: process all memories in one loop
(c) Limit to fewer candidates before vector comparison
Files: server/spacetimedb/src/hybrid_query.rs (lines 229-286)
Difficulty: Medium
Est: 2-3h for option (a)

### P3: `search_by_tags` — tag-filtered semantic search
Combine tag filtering with vector search in a single reducer: specify tag IDs
and only return memories that have *all* matching tags.
Files: server/spacetimedb/src/hybrid_query.rs, tag.rs
Difficulty: Medium
Est: 1h

---

## Recently Completed

### P3: Add `batch_tag_memories` + `batch_untag_memories` reducers + SDK methods (July 1, 2026)
Eliminates O(n) network round-trips for bulk tagging/untagging operations.
- Rust: batch_tag_memories (idempotent — skips already-tagged) and
  batch_untag_memories (idempotent — skips missing associations) reducers
- Python SDK: batch_tag_memories() + batch_untag_memories()
- TypeScript SDK: batchTagMemories() + batchUntagMemories()
- 10 Python unit tests + 4 TypeScript unit tests
Commit: 4a1b3bd3
Files: server/spacetimedb/src/tag.rs, sdk/python/spacetime_memory/client.py,
  sdk/python/tests/test_tags.py, sdk/typescript/client.ts,
  sdk/typescript/tests/client.test.ts
Difficulty: Medium
Est: 20min

### P3: Enhanced `dedup_memories` — merge tags, KG edges, entities (July 1, 2026)
Enhanced the `dedup_memories` reducer to fully migrate MemoryTag associations,
KG edges (source_memory_id redirect with 'merged_from' annotation), and
entities_json arrays from the duplicate to the survivor, not just deactivate.
Commit: 82c30702
Files: server/spacetimedb/src/consolidation.rs
Difficulty: Medium
Est: 30min

### P2: Time-weighted memory retrieval — `temporal_search_with_weight` (July 1, 2026)
Added new `temporal_search_with_weight` reducer in hybrid_query.rs that provides
exponential recency boosting (controlled by `recency_weight` 0.0–1.0) and
`time_context` filters ("recent", "last_week", "last_month").
Python SDK: `client.temporal_search_with_weight()`.
Commit: fa97ee0d
Files: server/spacetimedb/src/hybrid_query.rs, sdk/python/spacetime_memory/client.py
Difficulty: Medium
Est: 1-2h

### P3: Add `batch_delete_memories` reducer + SDK methods (July 1, 2026)
Added a new `batch_delete_memories(ids_json: String)` reducer in
server/spacetimedb/src/memory.rs that accepts a JSON array of memory IDs and
deactivates them in a single call — eliminating O(n) network round-trips for
bulk deletion. Idempotent per-memory (skips missing IDs).
Added `batch_delete_memories(memory_ids)` to Python SDK and
`batchDeleteMemories(memoryIds)` to TypeScript SDK.
Commit: 09da711a
Files: server/spacetimedb/src/memory.rs, sdk/python/spacetime_memory/client.py, sdk/typescript/client.ts
Difficulty: Medium
Est: 15min

### P2: Python `batch_update_memories` SDK method (July 1, 2026)
Python SDK already had `batch_update_memories(memory_ids, updates)` — confirmed
existing at line 2705 of client.py. Item was stale; verified code exists and works.
Files: sdk/python/spacetime_memory/client.py (verified existing, line 2705)
Difficulty: Easy
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
