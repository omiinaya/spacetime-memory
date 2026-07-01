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

### P2: Add 3 more TS methods — recommendMemories, searchSessionsSemantic, searchWithFilters
Added recommendMemories(), searchSessionsSemantic(), searchWithFilters().
71/71 TS tests pass, clean tsc. Total TS: 143 methods (was 85).

### P2: Add 8 more TS methods — health, profiles, context, merge suggestions
Added health(), checkEmbedderHealth(), upsertProfile(), suggestMerges(),
searchProfiles(), getProfileContext(), getUserMemories(), getOutgoingLinks().
71/71 TS tests pass, clean tsc. Total TS: 140 methods (was 85).

### P3: TypeScript SDK — Add citation methods (addNodeCitation, addEdgeCitation, getCitations) + fix getEdgeHistory
Added 3 citation methods matching Python SDK parity. Also fixed getEdgeHistory
which was missing the reducer call (known reducer pattern: call reducer to
populate result table, then SELECT from it). All 71 TS tests pass, clean tsc.
Files: sdk/typescript/client.ts
Difficulty: Easy
Est: 10min

### P2: Batch-add 33 TS SDK methods — profiles, context, KG, utilities
Added 33+ methods to complete feature parity: addProfileFact,
addDynamicContext, getProfile, listProfiles, setWorkspaceContext,
setMemoryContext, getContextChain, addAlias, createEntityLink, getNode,
getNoteByDate, getNoteByTitle, getNeighborsViaReducer, getPeerSessions,
getSessionMessages, computePageRank, computeKgStats,
computeCommunityHierarchy, setDecayModel, ping, getPeerReputation,
resolveEntity, approveMerge, rejectMerge, setMemoryScope, escalateMemories,
getOutgoingLinks. 71/71 TS tests pass, clean tsc.
Files: sdk/typescript/client.ts
Difficulty: Medium
Est: 45min

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
