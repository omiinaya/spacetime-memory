# Spacetime Memory — Improvement Backlog (June 30, 2026)

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Pending

### P1: TypeScript — Publish to npm
npm publish workflow exists but NPM_TOKEN hasn't been set in GitHub secrets.
Files: sdk/typescript/package.json, .github/workflows/npm-publish.yml
Difficulty: Easy
Est: 15min
BLOCKED: requires GitHub secrets to be set (NPM_TOKEN)

### P1: Publish benchmark scores (LongMemEval, LoCoMo, BEAM)
Biggest credibility gap vs Mem0, Hindsight, Supermemory.
Files: scripts/retrieval_benchmark.py exists; scripts/benchmark.py doesn't exist yet
Difficulty: Hard
Est: 1-2 weeks

### P3: Bi-temporal fact tracking — Graphiti-style temporal facts
Graphiti's strongest differentiator. Needs: fact valid_from/valid_to columns + auto-invalidation reducer.
Files: server/spacetimedb/src/profile.rs
Difficulty: Hard
Est: 1 week

### P3: Add list_peers / peer discovery Python SDK method
Rust `list_peers` reducer exists, Python SDK only has raw _call() access.
Files: sdk/python/spacetime_memory/client.py, server/spacetimedb/src/peer.rs
Difficulty: Easy
Est: 10min

## Recently Completed

### P3: Add CLI commands for tag management (list, delete)
Added `stmem tag list` and `stmem tag delete` CLI commands with rich table
output, JSON/CSV format support, and confirmation prompt for deletion.
Files: cli/stmem.py
Difficulty: Easy
Est: 15min

### P3: Add listTags/deleteTag tests to TypeScript SDK test suite
Added vitest tests verifying `listTags` calls `list_tags` reducer and
`deleteTag` calls `delete_tag` reducer with correct arguments.
68/69 tests pass (1 pre-existing ESM import failure unrelated).
Files: sdk/typescript/tests/client.test.ts
Difficulty: Easy
Est: 10min

### P3: Add list_tags + delete_tag reducers with full SDK + MCP support
Added Rust reducers (list_tags, delete_tag), Python SDK methods (list_tags, delete_tag),
TypeScript SDK methods (listTags, deleteTag), and MCP tools (list_tags, delete_tag).
All 170 existing Python tests pass.
Files: server/spacetimedb/src/tag.rs, sdk/python/spacetime_memory/client.py,
       sdk/typescript/client.ts, server/mcp/main.py
Difficulty: Easy
Est: 30min

### P3: Python SDK — Add public auth method wrappers
Added register(), login(), logout(), update_account(), deactivate_account(),
promote_admin(), demote_admin(), list_admins() public methods with proper
docstrings and type hints. These auth reducers were only accessible via
raw _call(). 861 tests pass (2 pre-existing failures unrelated).
Files: sdk/python/spacetime_memory/client.py
Difficulty: Easy
Est: 20min

### P2: Python — Add 77 missing Rust reducers to SDK
All 162 Rust reducers now have corresponding Python _call() wrappers or
high-level public methods. Auth (9), replication (10), sessions (5),
peers (3), connectors (3), messages (2), harmonics (3), change events (3),
context deltas (2), consolidation (9), knowledge graph (12), and ~37
miscellaneous all covered.
Files: sdk/python/spacetime_memory/client.py
Difficulty: Hard
Est: 4-8h

### P3: Python — Replace 6 `Any` type annotations with proper Protocols
plugin_manager: Any, event_bus: Any, query_cache: Any, local_llm: Any,
self._metrics: Any. These should be typed Protocols/ABCs.
Created sdk/python/spacetime_memory/_protocols.py with 5 runtime-checkable Protocols.
All 304 existing tests pass. Concrete classes verified via isinstance().
Files: sdk/python/spacetime_memory/_protocols.py, sdk/python/spacetime_memory/client.py
Difficulty: Medium
Est: 30min

### P2: Add E2E / deep test marker + 8 tests
Created `deep` marker, wrote 8 E2E pipeline tests exercising store→search,
create node→query graph, create note→get backlinks, and multi-step lifecycles.
All pass via mocked HTTP (no live STDB needed). 170/170 existing tests still pass.
Files: sdk/python/tests/test_e2e.py, sdk/python/tests/conftest.py
Difficulty: Medium
Est: 4h

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
