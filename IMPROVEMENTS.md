# Spacetime Memory — Improvement Backlog (July 1, 2026)

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Pending

### P3: Bi-temporal fact tracking — Graphiti-style temporal facts
Graphiti's strongest differentiator. Needs: fact valid_from/valid_to columns + auto-invalidation reducer.
Files: server/spacetimedb/src/profile.rs
Difficulty: Hard
Est: 1 week

### P2: Time-weighted memory retrieval scoring (mem0 v3 temporal parity)
mem0 v3 adds temporal reasoning — time-aware retrieval scoring that ranks memories
based on recency relevance to the query. Add `recency_weight` param to hybrid search
that boosts newer memories exponentially, and a `time_context` filter for queries
about "recent" / "last week" / "current state".
Files: server/spacetimedb/src/hybrid_query.rs, sdk/python/spacetime_memory/query_expansion.py
Difficulty: Medium
Est: 1-2h

### P2: Add Python `batch_update_memories` SDK method (Python parity gap)
TypeScript SDK has `batchUpdateMemories()`. Python SDK has no equivalent batch
update method — only loops calling `update_memory` individually via network.
Add `batch_update_memories` that uses the `store_memory_batch` reducer pattern.
Files: sdk/python/spacetime_memory/client.py
Difficulty: Easy
Est: 5min

### P3: Add `batch_delete_memories` SDK method (both Python + TypeScript)
No batch delete exists — delete operations are O(n) network calls. Add a new
reducer `batch_delete_memories(ids: Vec<String>)` and SDK wrappers for both
Python and TypeScript for bulk deletion.
Files: server/spacetimedb/src/memory.rs, sdk/python/spacetime_memory/client.py, sdk/typescript/client.ts
Difficulty: Medium
Est: 15min

### P3: Add `merge_duplicate_memories` consolidation step
Consolidation cron lacks memory deduplication. Add a reducer + SDK method
that finds near-duplicate memories (by content hash or cosine similarity > 0.95),
merges metadata (tags, edge references), and deactivates the duplicate.
Files: server/spacetimedb/src/consolidation.rs
Difficulty: Medium
Est: 30min

---

## Recently Completed

### P3: Add `crossEncoderRerank` to TypeScript SDK via MCP (July 1, 2026)
Added `crossEncoderRerank(query, candidates, opts?)` method that calls the MCP
server's `cross_encoder_rerank` tool for server-side ONNX reranking. Includes
`CrossEncoderRerankOptions` interface, `mcpUrl` config option (default port 8099),
handles both 'result' and 'content' MCP response formats. 6 unit tests.
Commit: 492b94c5
Files: sdk/typescript/client.ts, sdk/typescript/tests/client.test.ts
Difficulty: Medium
Est: 20min

### P3: Cross-encoder rerank unit tests (July 1, 2026)
15 tests already existed and pass covering CrossEncoderReranker init,
rerank scoring, fallback behavior, singleton lifecycle, and custom content keys.
Verified: `python3 -m pytest tests/test_cross_encoder.py -v` — 15/15 pass.
Files: sdk/python/tests/test_cross_encoder.py (verified existing)
Difficulty: Easy
Est: 5min

### P2: Add `exportWorkspaceJson` with full JSON format to TypeScript SDK (July 1, 2026)
Added `exportWorkspaceJson(workspaceId, opts?)` method that exports all workspace-scoped
data (notes, KG nodes/edges, memories, profiles, facts, sessions, tours, directories,
25+ tables) as structured JSON matching the backup format (v0.3.0). Includes
optional system-note filtering, file writing for Node.js. 2 unit tests.
Commit: 21faab53
Files: sdk/typescript/client.ts, sdk/typescript/tests/client.test.ts
Difficulty: Easy
Est: 5min

### P2: Add getMemoryStats, backup, restore to TypeScript SDK (July 1, 2026)
Added `getMemoryStats()` calling the get_memory_stats reducer + reading the result
table, plus `backup()` and `restore()` matching Python SDK's backup format.
Commit: 36d1cae6
Files: sdk/typescript/client.ts
Difficulty: Easy
Est: 5min

### P2: Add `expire_memories` call to consolidation cron (July 1, 2026)
Added `expire_stale()` function calling `Client.expire_memories()` at start
of consolidation tick, plus 3 pre-existing test fixes.
Commit: 8492ee59
Files: scripts/consolidate.py
Difficulty: Easy
Est: 2min

### P3: Add workspace-level memory stats CLI + MCP tool (July 1, 2026)
Added `stmem memory stats <workspace_id>` CLI command under the memory group with
rich table output showing total/active memories, by-tier, by-type, avg confidence,
avg age, revisions, top tags, and users. Also added `get_memory_stats` MCP tool
to the MCP server for agent access.
Files: sdk/python/spacetime_memory/cli.py, server/mcp/main.py
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
