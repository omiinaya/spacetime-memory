# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

*(cron manages this section — moves items here when marked ✅, purged old ones)*

---

## Pending

*No pending items.* All known `Client` methods now have MCP wrappers. New items
will be added when research identifies viable improvements.

---

## Recently Completed

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

### ✅ Add `get_peer_reputation` MCP tool for trust monitoring (Jul 27)
Added `get_peer_reputation` MCP tool wrapping `Client.get_peer_reputation()`.
Returns reputation stats (trust score, feedback count, positive/negative
breakdown, last-updated) for a peer. Returns None if no feedback history.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 3/3 new tests passing (167/167 total MCP tests)

### ✅ Add `list_profiles` MCP tool for profile listing (Jul 27)
Added `list_profiles` MCP tool wrapping `Client.list_profiles()`. Lists all
profiles in a workspace. Complements existing `search_profiles` and
`get_profile` tools for admin browsing.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 3/3 new tests passing (159/159 total MCP tests)

### ✅ Add `list_peers` MCP tool for peer discovery (Jul 27)
Added `list_peers` MCP tool wrapping `Client.list_peers()`. Lets agents
discover who is connected to the system — returns peer IDs, workspace
membership, and profile metadata. Useful for admin workflows and multi-agent
coordination.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min
Test: 4/4 new tests passing (156/156 total MCP tests)

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

### Jul 27 — All remaining Client methods now have MCP wrappers; backlog empty
- **MCP tools audit**: Added `get_peer_reputation`, `run_maintenance`, and
  `check_embedder_health` MCP tools wrapping the corresponding `Client`
  methods. All 104+ public `Client` methods now have MCP wrappers — no
  remaining gaps.
  - `get_peer_reputation`: Peer trust monitoring (trust score, feedback count).
  - `run_maintenance`: Trigger periodic maintenance (expire, decay, dedup).
  - `check_embedder_health`: Standalone embedder diagnostics (reachability,
    model, dimension, uptime).
- **Research**:
  - Git log (7 days): Latest commit before this tick: abc34f2 (docs, list_profiles
    research log). This tick: 3d05831 (3 MCP tools).
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.10 (previously v2.0.8). New feature: `expiration_date` exposed on
    `MemoryClient.update()` — not applicable to SpacetimeMemory (uses STDB reducers).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged since last check).
  - zep-python v2.0.2 (unchanged since last check).
  - No new competitor features to adopt.
- **Backlog**: 0 PENDING items (2 blocked items remain, both infrastructure-dependent).
- **Commit**: 3d05831 — 2 files changed, +176 lines, 167/167 MCP tests passing.
