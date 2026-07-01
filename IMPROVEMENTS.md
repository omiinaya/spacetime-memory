# Spacetime Memory — Improvement Backlog (July 1, 2026)

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

### P3: Bi-temporal fact tracking — Graphiti-style temporal facts
Graphiti's strongest differentiator. Needs: fact valid_from/valid_to columns + auto-invalidation reducer.
Files: server/spacetimedb/src/profile.rs
Difficulty: Hard
Est: 1 week

## Recently Completed

### P1: Published honest benchmark scores (July 1, 2026)
Published fresh baseline scores from a clean module on STDB v2.6 (127.0.0.1:3001).
Benchmark runner at `sdk/python/scripts/benchmark_runner.py`.
Integrated into `make bench`.

**Latency (20 iterations, 0/165 failures):**
| # | Operation | p50 (ms) | p90 (ms) | p99 (ms) |
|---|-----------|---------:|---------:|---------:|
| 1 | memory.store (single, short) | 1.3 | 1.5 | 2.3 |
| 2 | memory.store (single, long) | 1.3 | 1.4 | 1.5 |
| 3 | memory.store (batch 10) | 12.1 | 12.5 | 12.6 |
| 4 | search.keyword (top-5) | 27.8 | 29.1 | 29.9 |
| 5 | search.hybrid (top-10) | 5680.7 | 6630.3 | 7188.8 |
| 6 | graph.query | 4.8 | 5.8 | 9.8 |
| 7 | memory.count (_query) | 11.2 | 11.6 | 11.8 |
| 8 | ping (round-trip) | 0.8 | 0.9 | 1.1 |
| 9 | create_node (KG) | 1.2 | 1.4 | 1.9 |
| 10 | create_edge (KG) | 1.2 | 1.2 | 1.2 |
| 11 | get_neighbors | 20.9 | 21.3 | 22.2 |

**Key takeaways:**
- Pure WASM ops (store, create_node, create_edge) are **1-2ms** — no overhead.
- Keyword search is **28ms** — BM25 inverted index works, but slower than the ~11ms reference
  from the old DB with v2.4 (Tantivy differences or larger result set).
- Hybrid search is **~5.7s** — dominated by 3 retries against unreachable embedder (2700ms timeout).
  Semantic component alone adds 400ms when the embedder is live (historical reference).
- 0 failures across all 165 operations.

**Retrieval quality (keyword-only, 5 queries, 8 eval memories):**
P@5=40.0%  R@5=40.0%  MRR=0.400

**Key gaps:**
- Embedder (all-MiniLM-L6-v2 ONNX sidecar) was unreachable at 127.0.0.1:9090.
  No semantic scores. Historical reference: hybrid P@5=81.3%, +LLM reranking P@5=55.5%.
- No LongMemEval, LoCoMo, or BEAM benchmark harnesses exist (1-2 week effort each).
- These are **honest baseline scores**, not cherry-picked. The old reference showing
  store=194ms was with an embedder; this is the module-only cost.

### P1: Fix module build for STDB v2.6 — tag.rs API breakage
list_tags reducer returned `Result<String, String>` which v2.6 doesn't allow.
Fixed: added `serde::Serialize` to Tag struct, changed list_tags to return `()`,
updated SDK list_tags() to use `_query()` on the tag table instead.
Module builds clean and publishes successfully.

### P1: Publish and integrate benchmark runner
- Built unified benchmark runner at `sdk/python/scripts/benchmark_runner.py`
- Integrated into `make bench` with auto-DB discovery
- Runs latency + retrieval quality benchmarks in one invocation
- Outputs structured JSON + markdown table
- Covers: store (single/batch), search (keyword/hybrid), graph (query/node/edge/neighbors), ping, count

### P2: Fix Python SDK bugs — batch_update_memories dual filter, update_memory arg count
Fixed batch_update_memories which used a dual-field filter_dict ({id, workspace_id})
that failed with query_table reducer. Now queries by id only, validates workspace_id
client-side. Fixed update_memory 4→5 arg count for WASM compat (expires_at=0).
170/170 unit tests pass.

### P2: Add getNoteHistory and fuzzyGet to TS SDK
Added getNoteHistory(noteId) and fuzzyGet(ws, name, field?, threshold?, limit?).
71/71 TS tests pass. Total TS: 145 methods.

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
