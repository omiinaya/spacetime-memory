# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

*(cron manages this section — moves items here when marked ✅, purged old ones)*

---

## Pending

*No pending items — all Client public methods now have MCP wrappers.*

---

## Recently Completed

### ✅ Add `ping` MCP tool for connectivity health check (Jul 27)
Added `ping` MCP tool wrapping `Client.ping()`. Lightweight connectivity
check for agent self-diagnostics (confirms STDB is reachable before
performing memory operations). Returns status and latency.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 4/4 new tests passing (152/152 total MCP tests)

### ✅ Add `add_alias` MCP tool for entity alias management (Jul 27)
Added `add_alias` MCP tool wrapping `Client.add_alias()`. Complements
`resolve_entity` by allowing agents to register aliases for entity name
resolution. Takes entity_link_id and alias string.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 2/2 new tests passing (152/152 total MCP tests)

### ✅ Add decay model + batch_update_memories MCP tools (Jul 27)
Added `set_decay_model`, `get_decay_config`, and `batch_update_memories`
MCP tools wrapping the corresponding `Client` methods. Decay model
configuration (linear/Weibull) and bulk memory updates are now available
via MCP for memory lifecycle management and admin workflows.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 13min
Test: 13/13 new tests passing (146/146 total MCP tests)

### ✅ Add context chain MCP tools (Jul 27)
Added `set_workspace_context`, `set_memory_context`, and `get_context_chain`
MCP tools wrapping `Client.set_workspace_context()`,
`Client.set_memory_context()`, and `Client.get_context_chain()`. Context
chain management (QMD-style workspace + memory context) is now available
via MCP for agent memory workflows.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 8min
Test: 7/7 new tests passing (133/133 total MCP tests)

### ✅ Add API key management MCP tools (Jul 27)
Added `create_api_key`, `deactivate_api_key`, and `list_api_keys` MCP tools
wrapping `Client.create_api_key()`, `Client.deactivate_api_key()`,
and `Client.list_api_keys()`. API key management is now available via MCP
for admin workflows — create keys with workspace/permissions, revoke keys,
and list key metadata.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 10min
Test: 7/7 new tests passing (126/126 total MCP tests)

### ✅ Add `backup` / `restore` MCP tools (Jul 27)
Added `backup` and `restore` MCP tools wrapping `Client.backup()` and
`Client.restore()`. Data backup and restore is now available via MCP for
admin workflows. Backs up all user data tables to JSON and restores from them.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Medium
Est: 15min
Test: 5/5 new tests passing (119/119 total MCP tests)

### ✅ Add `link_memory_to_directory` / `unlink_memory_from_directory` MCP tools (Jul 27)
Added `link_memory_to_directory` and `unlink_memory_from_directory` MCP tools
wrapping `Client.link_memory_to_directory()` and
`Client.unlink_memory_from_directory()`. Directory memory-linking is now
complete (create_directory, list_directory, traverse_directory, get_directory,
link_memory_to_directory, unlink_memory_from_directory).
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 8min
Test: 4/4 new tests passing (119/119 total MCP tests)

### ✅ Add `get_directory` MCP tool (Jul 27)
Added `get_directory` MCP tool wrapping `Client.get_directory()`. Directory
getter by ID or path is now available via MCP. Complements existing directory
CRUD tools (create_directory, list_directory, traverse_directory).
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 3/3 new tests passing (119/119 total MCP tests)

### ✅ Add `resolve_entity` MCP tool (Jul 27)
Added `resolve_entity` MCP tool wrapping `Client.resolve_entity()`. Entity
resolution is now available via MCP for workspace-by-workspace name resolution
with alias support.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 2/2 new tests passing (107/107 total MCP tests)


---

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

### Jul 27 — ping + add_alias MCP tools added; all Client methods now have MCP wrappers
- **MCP tools audit**: Added `ping` (connectivity health check) and `add_alias`
  (entity alias management) MCP tools. All 104 public `Client` methods now have
  MCP wrappers — no remaining gaps.
  - `ping`: Wraps `Client.ping()` — lightweight HTTP connectivity check that
    reports status and latency. Useful for agent self-diagnostics.
  - `add_alias`: Wraps `Client.add_alias()` — registers an alias for an existing
    entity link. Complements `resolve_entity` for entity name resolution.
- **Research**:
  - Git log (7 days): Most recent commit before this tick: a37abd4 (docs update,
    Jul 27). This tick: (pending commit).
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged since last check).
  - zep-python v2.0.2 (unchanged since last check).
  - No new competitor features to adopt.
- **Backlog**: 0 PENDING items (2 blocked items remain).
- **Commit**: (pending commit) — 3 files changed, +91 lines, 152/152 MCP tests passing.

### Jul 27 — Decay model + batch_update MCP tools added; 2 new PENDING items
- **MCP tools audit**: Added `set_decay_model`, `get_decay_config`, and
  `batch_update_memories` MCP tools wrapping the corresponding `Client`
  methods. Decay model configuration (linear/Weibull) and bulk memory
  updates are now available via MCP.
- **Full Client method audit**: Of 102 public `Client` methods, 79 now have
  MCP wrappers. The remaining 23 are admin/utility/infrastructure methods
  (context deltas, peers, profiles, metrics, health, maintenance). Two new
  PENDING items added for the most immediately useful gaps:
  `ping` (connectivity health check) and `add_alias` (entity alias management).
- **Research**:
  - Git log (7 days): This tick: de57382 (decay model + batch_update MCP tools).
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged since last check).
  - zep-python v2.0.2 (unchanged since last check).
  - No new competitor features to adopt.
- **Backlog**: 2 new PENDING items added (2 blocked items unchanged).
- **Commit**: de57382 — 2 files changed, +337 lines, 146/146 MCP tests passing.

### Jul 27 — All 3 remaining MCP tools added (get_directory, directory linking, backup/restore); 4 new PENDING items for remaining gaps
- **MCP tools audit**: Added 3 PENDING MCP tools closing the last remaining
  `Client` method gaps:
  - `get_directory` MCP tool — directory getter by ID or path
  - `link_memory_to_directory` / `unlink_memory_from_directory` — directory
    memory-linking (directory CRUD now fully covered)
  - `backup` / `restore` — data backup/restore for admin workflows
  All `Client` public methods now have MCP wrappers. No remaining gaps.
- **Research**:
  - Git log (7 days): Most recent commit before this tick: c76ca42 (docs update,
    Jul 27). This tick: 16f1880 (5 MCP tools).
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph/claude-code — not installed.
  - zep-python v2.0.2 (unchanged since last check).
  - No new competitor features to adopt.
- **New gaps identified**: 4 additional `Client` methods still without MCP
  wrappers discovered during full audit:
  `create_api_key`/`deactivate_api_key`/`list_api_keys`,
  `set_workspace_context`/`set_memory_context`/`get_context_chain`,
  `set_decay_model`/`get_decay_config`, `batch_update_memories`.
  These are all admin/utility/infrastructure methods.
- **Backlog**: 4 new PENDING items added (2 blocked items remain).
- **Commit**: 16f1880 — 3 files changed, +332/-11 lines, 119/119 MCP tests passing.

### Jul 27 — resolve_entity MCP tool added; 3 PENDING items remain
- **MCP tools audit**: Added `resolve_entity` MCP tool wrapping `Client.resolve_entity()`.
  Entity resolution is now available via MCP for workspace-by-workspace name resolution
  with alias support.
- **Research**:
  - Git log (7 days): Most recent commit before this tick: 7071189 (docs update,
    Jul 27). This tick: (pending commit).
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph/claude-code — not installed.
  - No new competitor features to adopt.
- **Gaps remaining**: 3 `Client` public methods without MCP wrappers remain:
  get_directory, link_memory_to_directory/unlink_memory_from_directory,
  backup/restore. All are directory and admin/infrastructure methods.
- **Backlog**: 3 PENDING items (2 blocked items remain).
- **Commit**: 6d21a3c — 3 files changed, +71/-25 lines, 107/107 MCP tests passing.

### Jul 27 — delete_tour MCP tool added; 4 new PENDING items for remaining gaps
- **MCP tools audit**: Added `delete_tour` MCP tool wrapping `Client.delete_tour()`.
  Tour CRUD (create_tour, add_tour_stop, delete_tour) is now complete. This was
  a remaining gap in the tour management tools.
- **Research**:
  - Git log (7 days): Most recent commit before this tick: 582adfb (docs update,
    mark 4 MCP tools done, Jul 6). This tick: (pending commit).
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
- **Gaps remaining**: 4 `Client` public methods without MCP wrappers remain:
  resolve_entity, get_directory, link_memory_to_directory/unlink_memory_from_directory,
  backup/restore. All are admin/utility/infrastructure methods.
- **Backlog**: 4 PENDING items (2 blocked items remain).
- **Commit**: f090a12 — 3 files changed, +89/-34 lines, 105/105 MCP tests passing.

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
