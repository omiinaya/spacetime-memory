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

### P3: Add `expires_at` support to memories (mem0 parity)
mem0 v2.0.10 added `expiration_date` on memory update. We should add `expires_at` column
to the memory store reducer + Python SDK client.update() parameter + auto-cleanup reducer
that runs on a cron to delete/archive expired memories.
Files: server/spacetimedb/src/lib.rs, sdk/python/spacetime_memory/client.py
Difficulty: Medium
Est: 30min

### P2: Add `get_memory_stats` endpoint — workspace-level memory metrics
Expose a reducer or Python SDK method returning per-workspace stats: total memories,
by tier (L0/L1/L2), by type, avg confidence, avg age, top tags, etc. Useful for
dashboards and agent introspection. Similar to mem0's user stats endpoint.
Files: server/spacetimedb/src/lib.rs, sdk/python/spacetime_memory/client.py
Difficulty: Easy
Est: 10min

### P3: Add `cross_encoder_rerank` to TypeScript SDK (TS parity gap)
Python SDK has `CrossEncoderReranker` + MCP tool. TypeScript SDK has no equivalent.
Could be implemented client-side via ONNX runtime web or server-side via the MCP tool.
For now, document the pattern: call MCP tool from TS.
Files: sdk/typescript/client.ts
Difficulty: Medium
Est: 20min

---

## Recently Completed

### P3: Add cross_encoder_rerank MCP tool (July 1, 2026)
Added MCP tool wrapping the existing `CrossEncoderReranker` singleton in the Python SDK.
Takes a JSON array of candidate dicts, returns re-ranked results with cross-encoder scores.
Lazy imports `spacetime_memory.cross_encoder` to avoid hard torch/transformers dependency.
Commit: 0020d83e
Files: server/mcp/main.py
Difficulty: Easy
Est: 10min

### P2: Fix pytest-asyncio deprecation warning (July 1, 2026)
Added `asyncio_default_fixture_loop_scope = true` to `[tool.pytest.ini_options]` in
sdk/python/pyproject.toml to suppress the recurring PytestDeprecationWarning.
Commit: 0020d83e
Files: sdk/python/pyproject.toml
Difficulty: Easy
Est: 1min

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
