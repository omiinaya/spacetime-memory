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

### ✅ Add `list_context_deltas` MCP tool for context pack diffing (Jul 27)
Added `list_context_deltas` MCP tool wrapping `Client.list_context_deltas()`.
Deltas show what changed between consecutive context pack snapshots.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 2/2 new tests passing (190/190 total MCP tests)

### ✅ Add `list_context_entries` MCP tool for context pack introspection (Jul 27)
Added `list_context_entries` MCP tool wrapping `Client.list_context_entries()`.
Returns all entries within a given context pack.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 2/2 new tests passing (190/190 total MCP tests)

### ✅ Add `list_context_packs` MCP tool for context pack listing (Jul 27)
Added `list_context_packs` MCP tool wrapping `Client.list_context_packs()`.
Lists all context packs in a workspace for QMD-style context management.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 2/2 new tests passing (190/190 total MCP tests)

### ✅ Add `create_entity_link` MCP tool for entity resolution (Jul 27)
Added `create_entity_link` MCP tool wrapping `Client.create_entity_link()`.
Enables agent-driven entity linking for name resolution.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 2/2 new tests passing (190/190 total MCP tests)

### ✅ Add `seed_communities` MCP tool for seeding KG nodes (Jul 27)
Added `seed_communities` MCP tool wrapping `Client.seed_communities()`.
Seeds unassigned KG nodes into new communities.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 2/2 new tests passing (190/190 total MCP tests)

### ✅ Add `detect_bridge_nodes` MCP tool for KG analysis (Jul 27)
Added `detect_bridge_nodes` MCP tool wrapping `Client.detect_bridge_nodes()`.
Detects bridge nodes that connect multiple communities in the knowledge graph.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 3/3 new tests passing (190/190 total MCP tests)

### ✅ Add `detect_communities` MCP tool for KG community detection (Jul 27)
Added `detect_communities` MCP tool wrapping `Client.detect_communities()`.
Runs label-propagation community detection on the KG. Returns status,
nodes_processed, and communities_found counts.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 3/3 new tests passing (177/177 total MCP tests)

### ✅ Add `add_dynamic_context` MCP tool for peer profile context (Jul 27)
Added `add_dynamic_context` MCP tool wrapping `Client.add_dynamic_context()`.
Allows agents to append dynamic context to their profile mid-session without
replacing the whole profile. Also added `add_profile_fact` and
`get_profile_context` MCP tools for complete profile coverage.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 7/7 new tests passing (174/174 total MCP tests)

### ✅ Add `check_embedder_health` MCP tool for embedder diagnostics (Jul 27)
Added `check_embedder_health` MCP tool wrapping `Client.check_embedder_health()`.
Standalone embedder health check (previously only embedded in health_check).
Returns reachability status, model, dimension, and uptime.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 3/3 new tests passing (167/167 total MCP tests)

### ✅ Add `run_maintenance` MCP tool for system health (Jul 27)
Added `run_maintenance` MCP tool wrapping `Client.run_maintenance()`. Triggers
periodic maintenance routines (expire stale memories, decay, dedup). Useful
for scheduled system upkeep.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 2/2 new tests passing (167/167 total MCP tests)

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

### Jul 27 — Added 6 MCP tools; cleared all remaining PENDING items; backlog now empty
- **MCP tools**: Added `seed_communities`, `detect_bridge_nodes`,
  `create_entity_link`, `list_context_packs`, `list_context_entries`,
  and `list_context_deltas`. All remaining Client SDK methods that lacked
  MCP wrappers are now covered.
  - `seed_communities`: wraps `Client.seed_communities()` — seeds unassigned
    KG nodes into communities.
  - `detect_bridge_nodes`: wraps `Client.detect_bridge_nodes()` — returns
    JSON with bridge scores.
  - `create_entity_link`: wraps `Client.create_entity_link()` — canonical
    entity link for name resolution.
  - `list_context_packs/entries/deltas`: wraps `Client.list_context_packs()`,
    `Client.list_context_entries()`, `Client.list_context_deltas()` — context
    pack introspection.
- **Cleanup**: Purged 3 oldest Recently Completed entries (list_peers,
  list_profiles, get_peer_reputation). Moved 4 PENDING → Recently Completed.
- **Research**:
  - Git log (7 days): Latest: 4753004 (this commit).
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.10, langgraph v1.2.6, zep-python v2.0.2 — all unchanged.
  - opentelemetry-sdk v1.43.0 (unchanged).
  - No new competitor features to adopt.
- **Backlog**: 0 PENDING items — all Client SDK methods now have MCP tool wrappers.
- **Commit**: 4753004 — 3 files changed, +301 lines, 190/190 MCP tests passing.
