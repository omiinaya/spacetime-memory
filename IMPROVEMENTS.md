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

### P0: Fixed N+1 `_enrich_content` — semantic search 3x faster (July 1, 2026)
`_enrich_content` was doing N individual `_query()` calls (160 queries at 25ms each = 4s).
The `HybridResult` table already stores `content` in each row — the re-fetch was redundant.
Fix: use content from the row directly, batch confidence fetch in one `_query()` call.
**Result: semantic search 7.5s → 2.5s p50 (3x speedup).**

### P1: Tantivy sidecar + embedder sidecar are now systemd services (July 1, 2026)
Both Tantivy BM25 sidecar (:9091) and ONNX embedder (:9090, bge-large-en-v1.5, 1024-dim) are now:
- Built from source (Rust + ONNX runtime)
- Registered as systemd services with `Restart=always` + `RestartSec=5-10s`
- Standard output goes to journald

Services:
- `systemctl enable/start tantivy-sidecar.service` → :9091
- `systemctl enable/start embedder-sidecar.service` → :9090

Published fresh benchmark scores from clean module on STDB v2.6 (127.0.0.1:3001).
Benchmark runner at `sdk/python/scripts/benchmark_runner.py`.
Integrated into `make bench`.

**Latency (20 iterations, 0/148 failures, July 1 2026) — with N+1 fix:**
| # | Operation | p50 (ms) | p90 (ms) | p99 (ms) | Notes |
|---|-----------|---------:|---------:|---------:|-------|
| 1 | memory.store (single, short) | 1.2 | 1.4 | 2.0 | Pure WASM |
| 2 | memory.store (single, long) | 1.2 | 1.4 | 8.8 | Pure WASM |
| 3 | memory.store (batch 10) | 11.8 | 13.1 | 14.9 | 10× STDB calls |
| 4 | search.keyword (top-5) | 122.5 | 127.0 | 150.7 | Client-side BM25 fallback |
| 5 | search.semantic (top-5, w/ embedder) | **2529.4** | 2530.1 | 2530.3 | Previously 7513ms — **3x faster** |
| 6 | graph.query | 33.7 | 34.5 | 46.4 | WASM-only |
| 7 | memory.count (_query) | 38.5 | 39.6 | 40.1 | query_table reducer |
| 8 | ping (round-trip) | 1.2 | 1.3 | 1.3 | STDB round-trip |
| 9 | create_node (KG) | 523.2 | 554.9 | 556.6 | Includes entity extraction |
| 10 | create_edge (KG) | 1.2 | 1.4 | 1.5 | Pure WASM |
| 11 | get_neighbors | 189.0 | 210.1 | 216.2 | Graph traversal |

**Key takeaways:**
- Pure WASM ops (store, create_edge) are **1-2ms** — STDB is fast.
- **Semantic search is 2.5s** (previously 7.5s). Fixed the N+1 `_enrich_content` bottleneck that was doing 160 individual STDB queries at 25ms each. Now uses content already in `hybrid_result` rows + single batch confidence query.
- Remaining bottleneck: **1.5s hybrid_search reducer** (WASM BM25 + graph + temporal search). That's the Rust side — would need indexing or parallelism to cut.
- Tantivy search returns in **1ms** — but results are empty because the benchmark seeds via `_call("store_memory",...)` which bypasses Tantivy indexing. Real usage through `c.store()` indexes into Tantivy.
- 0 failures across all 148 operations.

**Retrieval quality (keyword-only, 5 queries, 8 eval memories):**
P@5=40.0%  R@5=40.0%  MRR=0.400

**Key gaps:**
- Embedder health check works; `_embed()` runs in 250ms with bge-large-en-v1.5 at :9090.
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
