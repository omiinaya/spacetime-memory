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

---

## Next up (reserve queue — not yet fully scoped)

### P3: Cross-encoder rerank MCP tool
`cross_encoder_rerank()` exists in Python SDK but no MCP tool wraps it. Useful for
retrieval pipelines needing precision re-scoring.
Files: server/mcp/main.py
Difficulty: Easy
Est: 10min

### P2: Fix pytest-asyncio deprecation warning
Add `asyncio_default_fixture_loop_scope = true` to pyproject.toml to suppress the
recurring PytestDeprecationWarning.
Files: sdk/python/pyproject.toml
Difficulty: Easy
Est: 1min

---

## Recently Completed

### P2: TS SDK — Add deleteTourStop + detectPatterns; stage+commit 3 unwritten methods (July 1, 2026)
Added 2 genuinely missing TS methods plus staged the 3 previously-written methods (globGet,
detectBridgeNodes, batchUpdateMemories) that were unstaged. Also added deleteTourStop as an
alias for removeTourStop. detectPatterns is a full client-side pattern detection method
(temporal clustering, frequent term extraction, co-occurrence) matching Python's
`pattern_detection.py` logic. 71/71 TS tests pass, clean tsc. Total TS: 149 public methods.
Files: sdk/typescript/client.ts
Difficulty: Easy
Est: 20min

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
- **Semantic search is 2.5s** (previously 7.5s). Fixed the N+1 `_enrich_content` bottleneck.
- Remaining bottleneck: **1.5s hybrid_search reducer** (WASM BM25 + graph + temporal search).
- Tantivy search returns in **1ms** — but results are empty because benchmark seeds via `_call("store_memory",...)` bypasses Tantivy indexing.
- 0 failures across all 148 operations.

### P2: Fix 10 ruff lint issues in Python SDK (July 1, 2026)
Fixed 10 lint errors across cli.py, client.py, and sdks/hindsight.py.
71/71 TS tests pass, clean tsc.

### P1: Fix module build for STDB v2.6 — tag.rs API breakage
list_tags reducer returned `Result<String, String>` which v2.6 doesn't allow.
Module builds clean and publishes successfully.

### P1: Publish and integrate benchmark runner
Built unified benchmark runner at `sdk/python/scripts/benchmark_runner.py`.
Integrated into `make bench` with auto-DB discovery.

### P2: Fix Python SDK bugs — batch_update_memories dual filter, update_memory arg count
170/170 unit tests pass.

### P2: Add getNoteHistory and fuzzyGet to TS SDK
71/71 TS tests pass. Total TS: 145 methods.

### P2: Add 3 more TS methods — recommendMemories, searchSessionsSemantic, searchWithFilters
71/71 TS tests pass, clean tsc. Total TS: 143 methods.

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
