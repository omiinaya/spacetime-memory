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

## Recently Completed

### P2: Batch-add 20 TS SDK methods — docs, directories, API keys, KG communities
Added 20 public methods to the TypeScript SDK matching Python SDK:
getBacklinks, createDocument, getDocument, listDocuments, getDocumentChunks,
deleteDocument, listDirectory, traverseDirectory, getDirectory, createDirectory,
linkMemoryToDirectory, unlinkMemoryFromDirectory, createApiKey (crypto.subtle
SHA-256), deactivateApiKey, listApiKeys, seedCommunities, getCommunity.
71/71 TS tests pass, clean tsc.
Files: sdk/typescript/client.ts
Difficulty: Medium
Est: 30min

### P2: TypeScript SDK — Context pack list queries (listContextPacks, listContextEntries, listContextDeltas)
Added 3 context pack query methods to the TypeScript SDK matching the Python SDK:
listContextPacks(), listContextEntries(), listContextDeltas() — each queries the
corresponding STDB table via _sql(). 71/71 TS tests pass.
Files: sdk/typescript/client.ts
Difficulty: Easy
Est: 10min

### P2: TypeScript SDK — Auth method wrappers (register, login, logout, etc.)
Added 9 public auth method wrappers to the TypeScript SDK matching the Python SDK:
register(), login(), logout(), updateAccount(), deactivateAccount(),
promoteAdmin(), demoteAdmin(), listAdmins(). Also fixed listTags() which was
calling _call() expecting a return value (was void). 71/71 TS tests pass.
Files: sdk/typescript/client.ts
Difficulty: Medium
Est: 20min

### P3: Add listPeers to TypeScript SDK
Added `PeerRecord` interface and `listPeers(workspaceId?)` method to TypeScript
SDK. Lists the `peer` table with optional workspace filter. 71/71 TS tests pass.
Detection: Python SDK already had this method; TypeScript was missing parity.
Files: sdk/typescript/client.ts, sdk/typescript/tests/client.test.ts
Difficulty: Easy
Est: 10min

## Recently Completed

### P3: Add CLI commands for tag management (list, delete)
Added `stmem tag list` and `stmem tag delete` CLI commands with rich table
output, JSON/CSV format support, and confirmation prompt for deletion.
Files: cli/stmem.py
Difficulty: Easy
Est: 15min

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
