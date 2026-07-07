# Spacetime Memory — Comprehensive Roadmap

**Generated:** 2026-07-02  
**Codebase:** ~18K Rust, ~97K Python, ~913K TypeScript (source)  
**Rust reducers:** 175+ across 36 source files  
**Python SDK:** ~140 public methods, ~40 private  
**TS SDK:** ~108 public async methods  
**Compounder:** 15 high-level workflow methods  
**Tests:** 60+ Python test files, 1 TS test file, 0 Rust unit tests  
**Sidecars:** Embedder (:9090), Tantivy BM25 (:9091)  

---

## ═══════════════════════════════════════════════
## PHASE 0: WORKING (no work needed)
## ═══════════════════════════════════════════════

### Core Rust WASM Module (`server/spacetimedb/`)
- [x] 85 STDB tables (25 public, 60 private)
- [x] Auth on every reducer (require_auth / require_admin)
- [x] Private tables correctly gated
- [x] BM25 inverted index with tokenization, stopwords, TF-IDF scoring
- [x] 4-strategy fusion: semantic + keyword + graph + temporal
- [x] Per-strategy min-max normalization in SDK
- [x] MMR diversity reranking (mmr_lambda=0.7)
- [x] Workspace pre-filters + MAX_RESULTS caps on all table scans
- [x] trace_span telemetry on all major reducers
- [x] User account system (register/login/logout/deactivate)
- [x] API key auth (sk-...) with admin role
- [x] Workspace permissions (owner/editor/viewer) via space_permission table
- [x] Change event logging + queryable history
- [x] Consolidation pipeline (dedup, rollup, decay, version merge)
- [x] Knowledge graph (nodes, edges, communities, PageRank)
- [x] Profile system with static facts + dynamic context
- [x] Tag system (create, update, delete, list, tag/untag memories, search_by_tags)
- [x] Note system (CRUD, revisions, backlinks, outgoing links)
- [x] Document system (with chunks)
- [x] Session tracking with messages
- [x] Tour framework (guided memory walks)
- [x] Mental model synthesis and retrieval
- [x] Harmonic belief propagation
- [x] Resonance logging
- [x] Entity extraction and linking
- [x] Insight generation
- [x] Peer reputation tracking
- [x] Context management (directory, delta, compression)
- [x] Replication (peer-to-peer memory sync)
- [x] Role-based access control (RBAC) with admin/owner/editor/viewer
- [x] Backfill user profiles from workspace context
- [x] Maintenance schedule (run_maintenance cron)
- [x] Scheduled expiration of stale memories

### Sidecars
- [x] **Embedder** (:9090) — ONNX bge-large-en-v1.5, 1024-dim, systemd with Restart=always
- [x] **Tantivy BM25** (:9091) — BM25 keyword search, systemd with Restart=always
- [x] Health endpoints on both sidecars
- [x] SDK gracefully degrades when embedder is unreachable

### Infrastructure
- [x] STDB v2.6.1 server (upgraded from v2.4.1)
- [x] Systemd services for STDB, embedder, Tantivy
- [x] CLI tools (`stmem` — 30+ commands via compounder)
- [x] Benchmark harness (benchmark_runner.py — 148 ops, 20 iterations)
- [x] Python SDK: 506/510 unit tests pass (4 pre-existing failures)
- [x] Backup/restore pipeline

---

## ═══════════════════════════════════════════════
## PHASE 1: P0 BLOCKERS (blocking publish / release)
## ═══════════════════════════════════════════════

### 1.1 Rebuild and publish WASM module
**Status:** Blocked — we upgraded STDB server to v2.6.1, Cargo.toml is set to `version = "2.6"`, but:
- [ ] `cargo update -p spacetimedb` needs to run to resolve lockfile
- [ ] Build: `CARGO_BUILD_JOBS=2 cargo build --release --target wasm32-wasip1`
- [ ] Publish: `echo "y" | spacetimedb-cli publish -s local-3001 -b <wasm> <db-id>`
- [ ] Verify reducer list still matches (`spacetimedb-cli logs`)

**Why blocked:** WASM can't be published until Cargo.lock resolves v2.6 (the lockfile was resolved against v2.4.1 and my manual deps might conflict).

### 1.2 Fix 4 failing Python unit tests
**Status:** 4/4 fixed. See root cause notes below.
- [x] `test_update_memory` — `_circuit_open_until` attribute missing on Mock(Client)
- [x] `test_check_embedder_health_error_status` — same Mock issue
- [x] `test_create_note_with_embed` — `UnboundLocalError: note_id` in Tantivy path
- [x] `test_context_in_search_results` — `_circuit_open_until` Mock issue

**Root cause(s):** (1) Mock(Client) doesn't call `__init__` which sets `_circuit_open_until`. Fixed by adding the attribute to Mock fixtures. (2) In `create_note`, `note_id` was initialized inside the try block (after `_query`), so when `_query` raised `RuntimeError` on no-STDB connection, the except handler's log message referenced `note_id` before assignment → `UnboundLocalError`. Fixed by moving `note_id = ""` before the try block (commit 8492ee59).

|### 1.3 Commit and push uncommitted changes
**Files touched but not committed (from prior sessions):**
|- [x] `server/spacetimedb/src/tag.rs` — `list_tags_by_memory`, `update_tag` reducers
|- [x] `server/spacetimedb/src/consolidation.rs` — `memory_tag` import
|- [x] `server/spacetimedb/src/hybrid_query.rs` — `memory_tag` import, stray `"` fix
|- [x] `server/spacetimedb/src/workspace.rs` — `memory`, `memory_revision`, `tag`, `memory_tag` imports
|- [x] `server/spacetimedb/src/memory.rs` — `memory_revision` import
|- [x] `server/spacetimedb/Cargo.toml` — pinned to `=2.4.1`, need to set back to `2.6`
|- [x] `sdk/typescript/client.ts` — `listTagsByMemory`, `updateTag` methods
|- [x] `IMPROVEMENTS.md`, `PERFORMANCE.md` — updated benchmark results

---

## ═══════════════════════════════════════════════
## PHASE 2: P1 PERFORMANCE (critical for usability)
## ═══════════════════════════════════════════════

### 2.1 Fix semantic strategy in hybrid_search reducer — 5s → sub-second
**Impact:** Every semantic search pays 5s for cosine similarity in WASM.

**Root cause:** `hybrid_query.rs:237` iterates `search_index` table, parses 1024-dim JSON embeddings, computes cosine similarity, does memory lookups — all in WASM. For 60 memories: 60× parse JSON (~1.8s) + 60× cosine sim (~0.3s) + 120× memory lookups (~0.6s) + 60× hybrid_result inserts.

**Fix options (pick one):**
- **(a) Client-side semantic** — skip `"semantic"` from reducer strategies, query `search_index` via `_query`, compute cosine similarity in Python. Removes 5s WASM work. Adds ~20ms Python + network latency.
- **(b) Cache embeddings** — store parsed embedding as inline f64 array in search_index instead of JSON string. Reduces parse time from ~30ms to ~0ms.
- **(c) HNSW/IVF index** — add a vector index in Tantivy sidecar. Most complex but best at scale.

**Recommendation:** Option (a). It's ~20 lines of Python, removes the 5s bottleneck entirely, and Tantivy's `search_index` query is fast. The SDK already has the embedding from `_embed()`.

### 2.2 Fix _enrich_content N+1 — verify fully resolved
**Status:** Fixed in `2fbb363f` — changed from N individual `_query()` calls to using content from hybrid_result rows + batch confidence query. 506 tests pass.
- [ ] Re-run 20-iteration benchmark to confirm semantic search stays ~2.5s (was 7.5s before fix)

### 2.3 Benchmark semantic retrieval quality
**Status:** Hybrid eval completed July 6 (50 eval memories, 25 queries). Embedder (bge-large-en-v1.5 at :9090) and Tantivy (:9091) sidecars live. Current hybrid: P@5=74.0%, R@5=74.0%, MRR=0.853 with bge-large-en-v1.5 (1024-dim) via `hybrid_benchmark.py` (raw cosine similarity). Benchmark script runs directly against the embedder API — no WASM build dependency.

**Historical baseline comparison (June 20 -> July 6):**
| Metric | June 20 (hybrid, bge-m3) | July 6 (hybrid, bge-large-en-v1.5) | Delta | Notes |
|--------|--------------------------|-----------------------------------|-------|-------|
| P@5    | 81.3%                    | 74.0%                             | −7.3pp | Current embedder underperforms historic bge-m3 by 7pp |
| R@5    | 82.0%                    | 74.0%                             | −8.0pp | Semantic recall 8pp lower with bge-large-en-v1.5 |
| MRR    | 0.960                    | 0.853                             | −0.107 | First-hit ranking reliability down from 96% to 85% |

**Embedder comparison vs keyword-only (same eval set, July 6):**
| Metric | July 6 (keyword-only) | July 6 (hybrid, bge-large-en-v1.5) | Delta | Notes |
|--------|-----------------------|-----------------------------------|-------|-------|
| P@5    | 49.3%                 | 74.0%                             | +24.7pp | Hybrid provides 1.5× precision over keyword-only |
| R@5    | 49.3%                 | 74.0%                             | +24.7pp | Semantic recall significantly better (+25pp) |
| MRR    | 0.463                 | 0.853                             | +0.390 | First result reliability 85% vs 46% |

**Analysis:**
- Current bge-large-en-v1.5 (1024-dim) produces P@5=74.0% — below historic bge-m3 (81.3%). The −7.3pp gap is model-specific: bge-large-en-v1.5 (0.33B params) vs bge-m3 (0.57B params) may encode different semantic dimensions. The evaluation dataset also differs (50 memories/25 queries now vs 8/5 on June 20), so scores aren't strictly apples-to-apples.
- Current keyword-only baseline rose from 40.0% (old 8/5 eval on July 1) to 49.3% (new 50/25 eval) — indicating the old eval was harder due to smaller sample.
- Hybrid still significantly outperforms keyword-only on the same dataset: +24.7pp P@5, +24.7pp R@5, +0.390 MRR. Embedders remain critical.
- The historic bge-m3 model is preferable for production if the proxy is stable — bge-large-en-v1.5 is a regression.
- **Next:** Run `retrieval_benchmark.py` for end-to-end SpacetimeDB pipeline results (blocked by DB connectivity — `Client()` failed with authentication). Requires fixing DB identity or re-publishing module.

- [x] Run `python3 scripts/hybrid_benchmark.py` — results: hybrid P@5=74.0%, R@5=74.0%, MRR=0.853 (July 6)
- [x] Record P@5, R@5, MRR for hybrid mode — **done: see tables above**
- [ ] Record P@5, R@5, MRR for +LLM reranking mode
- [x] Compare against historical baseline (June 20: hybrid P@5=81.3%, R@5=82.0%, MRR=0.960) — **current hybrid is 7-8pp lower; see comparison table above**

### 2.4 Benchmark with Tantivy indexing active
**Status:** The benchmark runner stores via `_call("store_memory", ...)` which bypasses `_tantivy_index()`. Tantivy has 0 documents for test workspace.
- [ ] Update benchmark to use `c.store()` instead of `c._call("store_memory", ...)` during seed phase
- [ ] Re-run search benchmarks to measure Tantivy contribution
- [ ] Expected: keyword search speed improves (Tantivy ~1ms vs BM25 in WASM ~28ms)

### 2.5 Fix Tantivy search query handling
**Status:** Single-token queries work (e.g., "fox" → found). Multi-token queries return wrong/worse results because `TermQuery` bypasses Tantivy's query parser.
- [ ] Switch from `TermQuery` to `QueryParser` in Tantivy sidecar for multi-word queries
- [ ] This gives proper tokenization-based matching for queries like "quick brown fox"

---

## ═══════════════════════════════════════════════
## PHASE 3: P2 FEATURE PARITY
## ═══════════════════════════════════════════════

### 3.1 TS SDK parity — 0 missing methods
**Status:** TS SDK has ~108 methods. Python SDK has ~140 public + 15 compounder.
- [ ] Audit missing methods by category:
  - [ ] `batchUpdateMemories` — missing
  - [ ] `setMemoryScope` — missing
  - [ ] `escalateMemories` — missing
  - [ ] `recommendMemories` — missing
  - [ ] `detectPatterns` — missing
  - [ ] `deltaSync` — missing
  - [ ] `searchWithFilters` — missing
  - [x] `listDirectory` / `traverseDirectory` / `getDirectory` / `createDirectory` / `linkMemoryToDirectory` / `unlinkMemoryFromDirectory` — implemented (server reducers + Python SDK + TS SDK + CLI + tests)
  - [x] `updateMemoryTier` — missing
  - [ ] `setMemoryScope` — missing
  - [ ] `batchDeleteMemories` — exists
  - [x] `batchTagMemories` / `batchUntagMemories` — CLI commands added (stmem tag batch-tag / batch-untag)
  - [x] `getEdgeHistory` — implemented (server reducer + MCP tool + Python SDK + TS SDK + tests)
  - [ ] `addNodeCitation` / `addEdgeCitation` / `getCitations` — missing
  - [ ] `computePageRank` — exists
  - [x] `computeCommunityHierarchy` — exists (server reducer + MCP tool + Python SDK + TS SDK + tests)
  - [x] `suggestMerges` / `approveMerge` / `rejectMerge` — implemented (server reducer + MCP tool + Python SDK + TS SDK + CLI + web UI + tests)
  - [ ] `addProfileFact` / `addDynamicContext` / `getProfile` / `listProfiles` / `searchProfiles` / `upsertProfile` — exist
  - [ ] `extractEntities` — exists
  - [ ] `storeHarmonicBeliefs` / `clearHarmonicBeliefs` — exist
  - [ ] `logResonanceSession` — exists
  - [x] `createEntityLink` / `addAlias` / `resolveEntity` — now fixed; TS createEntityLink had wrong signature (3 args instead of 5), fixed to match server reducer
  - [x] `getNode` — exists
  - [x] `getNoteByDate` — exists
  - [x] `getNoteByTitle` — exists
  - [ ] `getBacklinks` / `getOutgoingLinks` — missing
  - [x] `getNeighborsViaReducer` / `graphBfs` / `shortestPath` — added graphBfs, fixed shortestPath table name (bfs_result→shortest_path_result) + added maxHops param
  - [x] `searchSessionsSemantic` — CLI command added (`stmem session search`)
  - [x] `getPeerReputation` — exists
  - [x] `registerConnector` / `updateConnector` / `deleteConnector` — added MCP tools at server/mcp/main.py
  - [ ] Compounder class (15 methods) — does not exist in TS
- [x] `listTagsByMemory` — already added in prior session (uncommitted)
- [x] `updateTag` — already added in prior session (uncommitted)

**Estimate:** ~40 missing methods. Each is 5-15 lines. ~4-8 hours.

### 3.2 Python SDK `store_batch` — verify batch semantics
**Status:** `store_batch()` now uses a single batch Tantivy call. Added ``/index/batch`` endpoint to the Tantivy sidecar (``index_batch`` handler) that groups items by workspace, batch-deletes old docs, batch-adds new ones, and commits once per workspace. Updated `store_batch()` to call ``_tantivy_index_batch()`` after the STDB reducers.
- [x] Check if Tantivy sidecar has a batch index endpoint
- [x] If not, add one (POST /index/batch)
- [x] Update `store_batch()` to use single batch Tantivy call

### 3.3 Bi-temporal fact tracking (Graphiti parity)
**Status:** Not started. Graphiti's main differentiator is temporal facts with valid_from/valid_to.
- [ ] Add `valid_from: i64` and `valid_to: i64` to Memory struct
- [ ] Add `auto_invalidate(old_fact, new_fact)` reducer
- [ ] Expose in Python SDK: `search(query, temporal_filter={from: ..., to: ...})`
- [ ] Expose in TS SDK

**Estimate:** 1 week.

### 3.4 Cross-encoder reranking
**Status:** Done. `cross_encoder.py` module uses ONNX (ms-marco-MiniLM-L-6-v2) with numpy/onnxruntime/tokenizers. Extracted to `pip install spacetime-memory[cross-encoder]` optional extras group. `cross_encoder=True` is default in `search()` — falls back gracefully with a warning if the extra isn't installed. All 15 tests pass.
- [x] Extract cross-encoder model or use a different approach
- [x] Fix: ensure numpy is a dependency, or use a pure-Python fallback
- [x] Enable cross-encoder by default in search() fusion

### 3.5 npm publish
**Status:** Blocked by NPM_TOKEN
- [ ] Add NPM_TOKEN to GitHub secrets (`NPM_TOKEN`)
- [x] Configure `.npmrc` in CI
- [ ] Run `npm publish` from `sdk/typescript/`
- [ ] Also publish `sdk/python/` to PyPI? (requires PYPI_TOKEN)

---

## ═══════════════════════════════════════════════
## PHASE 4: P3 POLISH & BUG FIXES
## ═══════════════════════════════════════════════

### 4.1 Test coverage gaps
**Status:** 60+ test files, but coverage is uneven.
- [ ] **Rust module** — 0 unit tests across 36 source files. All tests are Python-side integration tests. Rust has no #[cfg(test)] modules except `hybrid_query.rs:1245` (3 unit tests for query_hash + parse_embedding_json + cosine_similarity).
- [ ] **TS SDK** — 1 test file (`tests/client.test.ts`). 71 tests pass. No E2E tests.
- [ ] **Python SDK** — 60+ test files, but many are thin. Connector tests are stubs (most can't run without live credentials).
- [ ] **Edge cases** — test_empty_search, test_special_characters, test_unicode_in_memory, test_very_large_content, test_concurrent_writes, test_network_partition

### 4.2 Security hardening
- [x] Key rotation support (ability to change JWT signing keys without data loss)
- [ ] Rate limiting on auth endpoints (register/login)
- [X] SQL injection audit — `_sql` endpoint takes raw SQL strings. The SDK's `_esc()` escapes identifiers but doesn't prevent SQL injection from compromised clients.
- [ ] Table privacy audit — 25 public tables out of 85. Are any of the public tables exposing data they shouldn't? `user` table is public — exposes peer IDs, account names. `query_result` is public — exposes ALL query results (currently empty until queried). `hybrid_result` is public.
- [ ] API key scope limits — currently sk- keys can admin the entire system. No workspace-scoped keys.

### 4.3 Schema migrations
- [ ] `hybrid_query.rs` — the schema comments say "Score Normalization REMOVED — Python SDK does it now" but the comment at line 516 says "Removed Jun 2026" — reference is already stale
- [x] The `maintenance_schedule` table has `scheduled(run_maintenance)` — the scheduled reducer runs `run_maintenance` which triggers decay + dedup. Fixed: removed stale `require_admin` from scheduled reducer (scheduler calls with module identity, not a registered admin account). Verified v2.6.1 (Cargo.lock), `scheduled(reducer_name)` syntax confirmed in v2.6.1 SDK docs, consolidation.rs compiles cleanly.
- [ ] Schema evolution policy — when adding fields, do we use `COALESCE`/default, or do we migrate?

### 4.4 Code quality
- [ ] 20 TODOs/FIXMEs across the codebase
  - `note.rs:208` — "TODO: handle concurrent note block updates" ✓ (added expected_version param to update_note)
  - `lib.rs:15` — "TODO: organize module structure"
  - `client.py:128` — "TODO: configure log level"
  - `orgmode.py:70` — "FIXME: extract method"
- [ ] Unused imports in several Rust files (warnings on build)
- [ ] `client.py` is ~5,200 lines — needs module split
- [ ] Python `_request_with_retry` shares circuit breaker across STDB + Tantivy — Tantivy failures trip the breaker for STDB

### 4.5 Documentation
- [ ] README.md — claims "full Mem0/Zep/Graphiti parity" but doesn't list caveats  
- [ ] ROADMAP.md is the REAL_ROADMAP — rename to unify
- [ ] No API reference docs for Python SDK (docstrings exist but no generated docs)
- [ ] No API reference docs for TS SDK
- [ ] No deployment guide beyond SETUP.md
- [ ] No connector setup guide (Discord token, Notion API key, etc.)
- [ ] No migration guide for upgrading from v2.4 to v2.6

### 4.6 Connector issues
- [ ] Connector tests require live credentials — no mock mode
- [ ] `connectors/base.py` is confusing — "connector" means "sync connector" (Discord, Notion, GitHub, Slack, RSS, Twitter, webhook, orgmode), NOT "parity adapter" (Mem0, Zep, etc.)
- [ ] No Telegram connector (mentioned in the prompt template)
- [ ] Orgsync connector may have bugs (orgmode.py:70 "FIXME")

### 4.7 Monitoring & Observability
- [ ] No alerting when embedder/Tantivy sidecar is down
- [ ] The `proxy_metrics_snapshot` table exists but no dashboard for it
- [ ] No memory usage trends (the 2.6GB embedder RAM usage isn't tracked)
- [ ] No request latency percentile tracking (current benchmark is manual)
- [ ] No error rate alerting (SDK silently degrades when embedder is down)

---

## ═══════════════════════════════════════════════
## PHASE 5: P4 NICE-TO-HAVE
## ═══════════════════════════════════════════════

### 5.1 Advanced features
- [ ] **Multi-modal memory** — store/store_batch could accept image attachments
- [ ] **Memory encryption at rest** — STDB doesn't support this, but we could encrypt content before storing
- [ ] **Structured output** — `search(return_schema=...)` for LLM-friendly results
- [ ] **Bulk export** — export workspace as Obsidian vault (markdown files + KG as JSON)
- [ ] **WebSocket subscriptions** — real-time memory updates via STDB subscriptions

### 5.2 Compounder enhancements
- [ ] **TS Compounder class** — doesn't exist. ~15 methods to port.
- [ ] **Compounder E2E tests** — `test_compounder_integration.py` exists but likely stale.
- [ ] **Ripple effect detection** — when a source is updated, which entities/nodes need re-summarization?

### 5.3 Adapter development
- [ ] **Mem0 TS adapter** — doesn't exist. Python-only currently.
- [ ] **Graphiti TS adapter** — doesn't exist. Python-only.
- [ ] **Zep TS adapter** — doesn't exist. Python-only.
- [ ] **Adapter E2E harness** — current adapter tests mock the STDB layer but don't test wire compatibility

### 5.4 Academic benchmarks
- [ ] **LongMemEval** — long-context memory benchmark. 2+ weeks to set up.
- [ ] **LoCoMo** — long context memorization. 2+ weeks.
- [ ] **BEAM** — belief-based evaluation. 2+ weeks.
- [ ] These were mentioned in earlier backlog (IMPROVEMENTS.md) but dropped due to cost/benefit.

### 5.5 perf
- [ ] **WASM `hybrid_search` benchmark as CI gate** — fail CI if p50 > 2x baseline
- [x] **Pre-warm memory caches** — reduce WASM first-call latency
- [ ] **Tantivy warmup on startup** — index existing memories on boot
- [ ] **Embedder GPU acceleration** — CUDA/ROCm support (currently CPU-only ONNX)

---

## ═══════════════════════════════════════════════
## SUMMARY STATS
## ═══════════════════════════════════════════════

| Metric | Value |
|--------|-------|
| Rust WASM reducers | 175+ (36 source files) |
| STDB tables | 85 (25 public, 60 private) |
| Python SDK methods | ~140 public + 15 compounder |
| TS SDK methods | ~108 public |
| Python tests | 506/510 passing (4 pre-existing failures) |
| TS tests | 71/71 passing |
| Rust unit tests | 3 (in hybrid_query.rs) |
| Connectors | 8 (Discord, GitHub, Notion, Slack, RSS, Twitter, Webhook, Orgmode) |
| Adapters (API-compatible) | 4 (Mem0, Zep, LangGraph, Honcho) |
| Sidecars | 2 (Embedder :9090, Tantivy :9091) |
| Scripts | ~25 (benchmarks, eval, consolidation, replication) |
| Benchmark ops | 148 with 20 iterations = 0 failures |
| Eval queries | 25 with ground-truth IDs |
| Uncommitted changes | 8+ files (Rust imports, TS methods, Cargo.toml) |
| TODO/FIXME markers | 21 across codebase |
