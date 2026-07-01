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

### P3: Add `cross_encoder_rerank` to TypeScript SDK (TS parity gap)
Python SDK has `CrossEncoderReranker` + MCP tool. TypeScript SDK has no equivalent.
Could be implemented client-side via ONNX runtime web or server-side via the MCP tool.
For now, document the pattern: call MCP tool from TS.
Files: sdk/typescript/client.ts
Difficulty: Medium
Est: 20min

### P2: Add `exportWorkspace` with full JSON format to TypeScript SDK
Python SDK has `export()` that dumps all tables as JSON. TS `exportWorkspace()` only
dumps notes as markdown. Add a full JSON export matching Python's backup format.
Files: sdk/typescript/client.ts
Difficulty: Easy
Est: 5min

---

## Recently Completed

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

### P2: Add `get_memory_stats` endpoint (July 1, 2026)
New reducer `get_memory_stats` in workspace.rs computes per-workspace memory metrics:
total/active memories, by-tier breakdown, by-type breakdown, avg confidence,
avg age, total revisions, top-10 tags, distinct users. Results stored in
`workspace_memory_stats_result` public table. Python SDK `Client.get_memory_stats()`
returns dict of stat_key → stat_value. Unit tests added (TestMemoryStats).
Files: server/spacetimedb/src/workspace.rs, sdk/python/spacetime_memory/client.py,
sdk/python/tests/test_client_deep.py
Difficulty: Easy
Est: 10min

### P3: Add cross_encoder_rerank MCP tool (July 1, 2026)
Added MCP tool wrapping the existing `CrossEncoderReranker` singleton in the Python SDK.
Commit: 0020d83e
Files: server/mcp/main.py
Difficulty: Easy
Est: 10min

### P2: Fix pytest-asyncio deprecation warning (July 1, 2026)
Added `asyncio_default_fixture_loop_scope = true` to pyproject.toml.
Commit: 0020d83e
Files: sdk/python/pyproject.toml
Difficulty: Easy
Est: 1min

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
