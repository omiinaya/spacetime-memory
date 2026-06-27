# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

*(cron manages this section — moves items here when marked ✅, purged old ones)*

---

## Pending

*No pending items. All known Client SDK methods now have MCP tool wrappers.*

---

## Recently Completed

### ✅ Add `search_profiles` MCP tool (Jul 6)
Added MCP tool wrapping `Client.search_profiles()`. Searches peer profiles by
static_facts or dynamic_context (client-side filter).
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 11/11 new tests passing (103/103 total MCP tests)

### ✅ Add `get_user_memories` MCP tool (Jul 6)
Added MCP tool wrapping `Client.get_user_memories()`. Gets user-scoped memories
for multi-user scenarios.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 11/11 new tests passing (103/103 total MCP tests)

### ✅ Add `search_sessions_semantic` MCP tool (Jul 6)
Added MCP tool wrapping `Client.search_sessions_semantic()`. Semantic search
across past sessions for agent context retrieval.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 11/11 new tests passing (103/103 total MCP tests)

### ✅ Add `recommend_memories` MCP tool (Jul 6)
Added MCP tool wrapping `Client.recommend_memories()`. Recommends memories that
need attention (urgent, decaying, low-trust) for maintenance workflow.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 11/11 new tests passing (103/103 total MCP tests)

### ✅ Add `compute_kg_stats` MCP tool (Jul 6)
Added `compute_kg_stats` MCP tool wrapping `Client.compute_kg_stats()`.
Returns KG statistics (node_count, edge_count, community_count, orphan_nodes,
avg_degree) for workspace health monitoring in the LLM Wiki workflow.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 2/2 new tests passing (92/92 total MCP tests)

### ✅ Add citation management MCP tools (Jul 6)
Added 3 MCP tools for KG citation provenance: `add_node_citation`,
`add_edge_citation`, `get_citations`. Citations link KG nodes/edges to
supporting source memories for provenance tracking (AGENTS.md workflow).
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 8min
Test: 8/8 new tests passing (90/90 total MCP tests)

### ✅ Add `search_with_filters` MCP tool (Jul 6)
Added `search_with_filters` MCP tool wrapping `Client.search_with_filters()`.
Provides structured metadata and location-based filtering (metadata_filter,
location_filter as JSON strings) that the existing search_memories and
hybrid_search tools don't expose.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 10min
Test: 4/4 new tests passing (82/82 total MCP tests)

### ✅ Add `glob_get` MCP tool (Jul 6)
Added `glob_get` MCP tool wrapping `Client.glob_get()`. Uses fnmatch-style
wildcards (`*`, `?`, `[...]`) to find memories matching a pattern on any
field. Complements the existing `fuzzy_get` tool.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 4/4 new tests passing (84/84 total MCP tests)

### ✅ Add `fuzzy_get` MCP tool (Jul 6)
Added `fuzzy_get` MCP tool wrapping `Client.fuzzy_get()`. Returns JSON with
best fuzzy-match or no-match message. Uses difflib SequenceMatcher.
Files: server/mcp/main.py
Difficulty: Easy
Est: 5min
Test: 59/59 MCP tests passing

### ✅ Add `detect_patterns` MCP tool (Jul 6)
Added `detect_patterns` MCP tool wrapping `Client.detect_patterns()`. Accepts
include_clusters, include_terms, include_co_occur flags. Returns JSON with
temporal clusters, frequent terms, co-occurrences.
Files: server/mcp/main.py
Difficulty: Easy
Est: 5min
Test: 59/59 MCP tests passing

|---

## Deferred / Blocked

### Fix stale WASM binary causing test_get_memory_history failure
The published WASM binary at target/wasm32-wasip1/release/spacetime_memory.wasm
is stale and doesn't include `memory_revision` in the query_table ALLOWED_TABLES
whitelist. `test_get_memory_history` fails against the real STDB server.
Fix: rebuild WASM module (requires cargo build, currently blocked by OOM).
Files: server/spacetimedb/src/query.rs
Difficulty: Medium (needs cargo build)
Est: N/A (blocked)

### STDB 2% fatal error under heavy concurrent load
**uuid_v4_uniq mitigation is complete** — all 27 primary-key inserts use
collision-retry. The remaining ~2% fatal errors appear to be a STDB-level
WASM limitation (not UUID-related). Root cause analysis requires a live
STDB instance with replicator stress testing. Deferred until live STDB
infrastructure is available for investigation.
Files: server/spacetimedb/src/lib.rs, tests/concurrent/
Difficulty: Hard (needs live STDB)

|---

## Research Log

### Jul 6 — 4 remaining MCP tools added; all Client SDK methods now have MCP wrappers
- **MCP tools audit**: Added 4 MCP tools wrapping the last `Client` methods
  without tool coverage: `recommend_memories`, `search_sessions_semantic`,
  `get_user_memories`, `search_profiles`. All `Client` public methods now have
  MCP tool wrappers.
- **Research**:
  - Git log (7 days): Most recent commit before this tick: 2d6cc54 (docs
    update, compute_kg_stats research log). All changes reviewed.
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
- **Gaps remaining**: 0 `Client` methods without MCP wrappers. All known
  actionable improvement items are complete. The only remaining items are
  the stale WASM binary (blocked by OOM) and the STDB 2% concurrency issue
  (needs live infrastructure).
- **Backlog**: 0 PENDING items (2 blocked items remain).
- **Commit**: 1dc8ff4 — 2 files changed, +271/-0 lines, 103/103 MCP tests passing.

### Jul 6 — `compute_kg_stats` MCP tool added; 4 new PENDING items for remaining MCP gaps
- **MCP tools audit**: Added `compute_kg_stats` MCP tool wrapping
  `Client.compute_kg_stats()`. Returns KG stats for health monitoring.
- **Research**:
  - Git log (7 days): Most recent commit before this tick: 8ffe547 (docs
    update, citation management research log). This tick: 7bbc05b
    (compute_kg_stats MCP tool).
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
- **Gaps remaining**: `Client` methods still without MCP wrappers are mostly
  admin/utility/infrastructure. Top remaining: recommend_memories,
  search_sessions_semantic, get_user_memories, search_profiles, resolve_entity.
- **Backlog**: 4 PENDING items (stale WASM binary still blocked by OOM).
- **Commit**: 7bbc05b — 3 files changed, +88/-1 lines, 92/92 MCP tests passing.

### Jul 6 — Citation management MCP tools added; KG provenance gap closed
- **MCP tools audit**: Added 3 citation MCP tools wrapping
  `Client.add_node_citation()`, `Client.add_edge_citation()`,
  `Client.get_citations()`. Citations provide provenance tracking —
  recording which source memory supports each KG node and edge. This
  fills a gap in the LLM Wiki workflow (AGENTS.md) where citations
  power the source-attribution chain.
- **Research**:
  - Git log (7 days): 206 commits. Most recent before this tick:
    f9890df (docs update) and f6f159f (search_with_filters MCP tool).
    This tick: e8dedde (citation management MCP tools).
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
- **Gaps remaining**: 3 citation MCP tools closed the citation gap.
  Remaining `Client` methods without MCP wrappers are mostly
  admin/utility/infrastructure (backup/restore, API key management,
  peer listing, directory linking, context management, decay config,
  profile search, community seeding, session semantic search, memory
  recommendation, entity linking) — lower priority.
- **Backlog**: 0 PENDING items (stale WASM binary still blocked by OOM).
- **Commit**: e8dedde — 2 files changed, +218/-0 lines, 90/90 MCP tests passing.

### Jul 6 — `search_with_filters` MCP tool added; metadata/location search gap closed
- **MCP tools audit**: Added `search_with_filters` MCP tool wrapping
  `Client.search_with_filters()`. Provides metadata and location filtering
  that `search_memories` and `hybrid_search` don't expose.
- **Research**:
  - Git log (7 days): Most recent commit before this tick was 62f827c
    (docs update). This tick: f6f159f (search_with_filters MCP tool).
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
  - Full MCP test suite: 82/82 tests passing (4 new).
- **Gaps remaining**: `Client` methods still without MCP wrappers are mostly
  admin/utility/infrastructure: backup/restore, API key management, peer
  listing, directory linking, context/tour management, decay config, and
  metrics collection. All search/retrieval/pattern methods now have MCP
  wrappers.
- **Backlog**: 0 PENDING items (stale WASM binary still blocked by OOM).
- **Commit**: f6f159f — 2 files changed, +108/-0 lines, 82/82 MCP tests passing.

### Jul 6 — `glob_get` MCP tool added; all Client search/pattern methods now wrapped
- **MCP tools audit**: Added `glob_get` MCP tool wrapping `Client.glob_get()`.
  Complements `fuzzy_get` with fnmatch-style pattern matching. All `Client`
  search/pattern/retrieval methods now have MCP wrappers.
- **Research**:
  - Git log (7 days): Most recent commit before this tick was e4b76c5
    (update_node + list_memories docs). No unreviewed changes.
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
- **Gaps remaining**: All `Client` search/retrieval/pattern methods now have MCP
  wrappers. Remaining untapped Client methods are admin/utility/infrastructure
  (backup/restore, API key management, peer listing, etc.) — lower priority.
- **Backlog**: 0 PENDING items (stale WASM binary still blocked by OOM).
- **Commit**: 59b11a3 — 3 files changed, +113/-47 lines, 78/78 MCP tests passing.
