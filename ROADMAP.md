# Spacetime Memory — Implementation Roadmap

This roadmap tracks the gap between what the README claims and what's actually
shippable. Each phase is ordered by dependency: nothing in Phase N starts until
Phase N-1 is complete.

## Current state (baseline)

- **Rust backend (2,964 LOC, 21 files):** compiles clean, real tables & reducers,
  correct v2.4 API usage. The data model covers most domains. The delta context
  pack logic (309 lines) and hybrid query engine (441 lines) are the strongest
  modules.
- **Frontend (19 files):** 7 of 8 pages use hardcoded mock data. Only
  KnowledgeGraph connects to real SpacetimeDB via HTTP SQL API.
- **MCP server (351 LOC):** real, connects to DB, exposes 15 tools.
- **CLI (533 LOC):** real, click + httpx + Rich, works.

## Projects to remove from README claims

**Logseq** — full note-taking application, not a memory library.
**Obsidian** — full knowledge-base application, not a memory library.
Having them in the inspirations table signals scope confusion. Drop them.

## Phase 0 — Foundation

### 0a. Rust ONNX embedding pipeline

**What:** Replace the fake "semantic" search (keyword matching in
`hybrid_query.rs`) with real vector embeddings computed via ONNX Runtime in
Rust. Embed text on write (via `store_memory`, `create_document`, `create_node`)
and store vectors in `SearchIndex.embedding_json` / new `KgNode.embedding_json`.
Add a `cosine_similarity` strategy to `hybrid_search`.

**Why ONNX:** Keeps everything in-process in the SpacetimeDB module or in a
companion Rust binary. No external Python process, no vector DB dependency.
Fastest path once built.

**Work:**
1. Add `ort` (ONNX Runtime for Rust) or `tract` crate to Cargo.toml
2. Download/embed `all-MiniLM-L6-v2` model in ONNX format (~23MB)
3. Create `embedding::generate(content: &str) -> Vec<f32>` helper
4. Add an `embedding_json` field to `SearchIndex` (or new `Embedding` table)
5. Wire `store_memory` → generate embedding → write to `SearchIndex`
6. Wire `create_node` → generate embedding → write to `KgNode.embedding_json`
7. Add `cosine_similarity` scoring to `hybrid_search` strategy
8. Add weighted fusion for multi-strategy ranking

**Risks:** `ort` crate has native dep on ONNX Runtime shared lib (libonnxruntime).
Need to bundle or build from source. WASM target limitation — embeddings
computed server-side (companion process or sidecar), not inside the
SpacetimeDB WASM module itself. SpacetimeDB reducers run in WASM and can't
load native libs. The embedding engine needs to be a sidecar or pre-compute
step.

### 0b. Wire frontend to real data

**What:** Replace hardcoded mock data in all 7 pages with real SpacetimeDB HTTP
SQL API calls (same pattern as KnowledgeGraph).

**Pages to wire:**
- **Dashboard:** stat widgets call `SELECT COUNT(*) FROM memory WHERE ...`,
  `SELECT COUNT(*) FROM peer`, `SELECT COUNT(*) FROM session WHERE created_at > ...`
- **Peers:** `SELECT * FROM peer` with status computed from session activity
- **Sessions:** `SELECT s.*, COUNT(m.id) as message_count FROM session s LEFT JOIN message m ...`
- **MemoryBrowser:** `SELECT * FROM memory ORDER BY updated_at DESC` with search/filter
- **Documents:** `SELECT * FROM document`
- **Search:** trigger `hybrid_search` reducer, then read `hybrid_result` table
- **Settings:** functional settings (SpacetimeDB host, etc.) stored in a config table

### 0c. Scheduled maintenance jobs

**What:** Run existing but uncalled maintenance reducers on a schedule.

**Jobs:**
- `expire_memories` every 5 minutes
- `decay_weak_memories(strength_threshold: 0.3)` every 1 hour
- `compute_god_nodes(workspace_id, top_n: 20)` every 6 hours

**Delivery:** Hermes cron job calling MCP server tools.

### 0d. Auto-reinforcement on read

**What:** `reinforce_memory` exists but nothing ever calls it because no read
path goes through the reinforcement hook.

**Work:**
- Wrap all read paths (MCP `get_memory`, MCP `search_memories`, CLI get, SQL
  read patterns) to call `reinforce_memory(memory_id)` after each access
- For batch reads (search results), batch-call `reinforce_memories(reducer)` to
  avoid N+1
- Add `access_count→tier` escalation: when a L2 memory hits N accesses,
  auto-upgrade to L1 (Phase 1d prerequisite)

## Phase 1 — Real intelligence

### 1a. Community detection (Graphify parity)

**What:** `kg_community` table and `assign_to_community` reducer exist. No
algorithm computes communities from edge topology.

**Work:**
- Implement Leiden community detection in Rust on `kg_edge` adjacency
- Reducer `detect_communities(workspace_id, resolution: f64)` recomputes all
  cluster assignments, writes to `kg_community` and `KgNode.community_id`
- Wire `compute_god_nodes` per-community (currently global degree centrality only)
- Add community-aware graph traversal to `hybrid_search` graph strategy

### 1b. Reputation-weighted retrieval (Holographic parity)

**What:** `MemoryFeedback` table, `trust_score` field, `rate_memory` reducer
exist. No query path weights by trust score.

**Work:**
- Add `min_trust_score` filter to `hybrid_search` and MCP `search_memories`
- Boost result scores by `trust_score` in keyword/graph/temporal strategies
- Add confidence threshold (`feedback_count > 3` for reliable score)
- Add `rate_memory` call to MCP `search_memories` UI feedback buttons

### 1c. Automatic consolidation (RetainDB parity)

**What:** `consolidate_memories` takes explicit source IDs. No dedup, no rollup.

**Work:**
- `auto_dedup(workspace_id)`: find memories with ≥85% content similarity
  (cosine of embeddings + edit distance), merge duplicates
- `auto_rollup(workspace_id)`: group similar low-confidence memories into a
  single consolidated high-confidence memory
- Wire into scheduled maintenance (Phase 0c)

### 1d. Runtime tier escalation (OpenViking parity)

**What:** Tier field (L0/L1/L2), `update_memory_tier` reducer exist. Nothing
auto-escalates on access.

**Work:**
- After `reinforce_memory`, check `access_count` threshold and auto-escalate
  (L2→L1 at 5 accesses, L1→L0 at 20 accesses)
- Add `escalate_memories(workspace_id, thresholds)` scheduled reducer for
  batch reconciliation
- Add tier filter to all retrieval paths in `hybrid_search`
- Runtime: when a L2 memory is accessed via search, include it in results but
  mark the escalation

## Phase 2 — API compatibility (drop-in replacement)

### 2a. Mem0 SDK

**What:** `pip install stmem-mem0` → drop-in replacement for `mem0.Memory`.

**Work:** Python package wrapping MCP HTTP API with identical `add()`,
`search()`, `get_history()`, `delete()` signatures. Embedding calls route
through the ONNX sidecar.

### 2b. Hindsight SDK

**What:** `pip install stmem-hindsight` → `retain()` / `recall()` / `reflect()`.

**Work:** `retain()` → `store_memory`, `recall()` → `hybrid_search`,
`reflect()` → LLM call + `create_insight`. Wraps MCP API.

### 2c. Honcho REST API

**What:** Serve Honcho-compatible routes at `/v1/apps/...`.

**Work:** Axum proxy sidecar mapping Honcho route params to
workspace/peer/session IDs. Pagination middleware.

### 2d. Graphify MCP compatibility

**What:** Alias MCP tools to Graphify's exact tool names/schemas.

**Work:** Add `query_graph`, `get_node`, `get_neighbors`, `triage_prs`,
`get_pr_impact` aliases. `triage_prs` and `get_pr_impact` require codebase
ingestion (Phase 3b).

## Phase 3 — Ecosystem features

### 3a. Codebase ingestion (Understand Anything parity)

**Work:** CLI command `stmem ingest /path/to/repo`. Uses tree-sitter to parse
source files, creates `kg_node` per function/class/file, creates `kg_edge` with
call/inherit/import/depend relations. PR impact analysis via git diff.

### 3b. Connectors (Supermemory parity)

**Work:** Plugin system for external data sources: browser bookmarklet, RSS
feeds (`blogwatcher` integration), GitHub repo watcher. Each connector calls
`store_memory` / `create_document`.

### 3c. Context routing agent (RetainDB parity)

**Work:** Agent loop that consumes `generate_context_pack` and `get_delta`.
Receives query → calls pack generation → reads `context_pack` → calls LLM →
returns answer. On subsequent queries uses `previous_pack_id` for delta mode.
Proves the context system works end-to-end.

## Effort overview

| Phase | New LOC | Key risk |
|---|---|---|
| 0a ONNX embedding | ~200 Rust + ~50 Python | Native ONNX Runtime dep, WASM limitation |
| 0b Wire frontend | ~420 TypeScript | Subscription timing (loading state) |
| 0c Scheduled jobs | ~50 Python | None |
| 0d Auto-reinforce | ~30 Python | N+1 on batch reads |
| 1a Community detection | ~150 Rust | Algorithm complexity |
| 1b Reputation weight | ~50 Rust | Scoring math |
| 1c Auto-consolidation | ~120 Rust | Similarity thresholds |
| 1d Tier escalation | ~45 Rust | None |
| 2a Mem0 SDK | ~300 Python | API surface matching |
| 2b Hindsight SDK | ~300 Python | Same |
| 2c Honcho REST | ~400 Rust | Route design |
| 2d Graphify MCP | ~50 Python | Tool name mapping |
| 3a Codebase ingest | ~400 Python | tree-sitter integration |
| 3b Connectors | ~600 Python | External API maintenance |
| 3c Context agent | ~200 Python | Making it actually useful |

**Total new code:** ~3,100 lines across everything.
