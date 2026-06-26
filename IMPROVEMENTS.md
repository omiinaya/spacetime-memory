# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Status: PENDING

### Add compounder.update_entity_page() method
`create_entity_page()` exists but there's no public compounder method to
update both a KG node and its associated wiki note in one call. Currently
users must update the node and note separately via the client.
Difficulty: Easy
Est: 1h

### Add MCP tool for batch store-answers
The `store_answers()` batch method exists now but has no corresponding MCP
tool. Add an MCP tool wrapping it so agents can batch-persist multiple
Q&A pairs in one call.
Difficulty: Medium
Est: 1h

---

## Recently Completed

### ✅ Batch store_answers() added to compounder (Jun 25)
New `store_answers()` batch method processes multiple query/answer pairs
efficiently: single index traversal, consolidated logging, graceful error
handling (one failure doesn't stop the batch). 3 new unit tests.
Files: sdk/python/spacetime_memory/compounder.py, tests/test_compounder.py

### ✅ format_uuid_v4() now outputs standard 32-hex-char UUID (Jun 25)
Previously `format_uuid_v4()` produced a non-standard 28-hex-char format
(8-4-4-4-8, 112 bits) where the upper 4 hex digits from the `high` u64
were discarded. Now produces standard RFC 4122 v4 UUIDs (8-4-4-4-12, 128 bits).
Commit: 5c98d30

### ✅ Knowledge Compounder — all 7 patterns implemented (Jun 25)
Compounder operations now use real reducers (``create_edge``, ``update_node``).
``lint_workspace()`` auto-creates contradiction notes. Full 30-test suite.
Commits: 62834b3, 39f6f01, 6ba5195, dad454b

### ✅ update_node reducer added to Rust module (Jun 25)
New ``#[reducer] pub fn update_node(...)`` in ``knowledge_graph.rs``.
Updates label, type, summary, metadata_json, source_memory_id on an
existing KG node. Uses ``ctx.db.kg_node().id().update()`` — preserves
ID, workspace, community, embedding, and timestamps.
Commit: dad454b

### ✅ Knowledge Compounder — persist answers as wiki pages (Jun 24)
New ``Compounder`` class (``client.compounder``) that implements the
LLM Wiki pattern: every search synthesis becomes a persistent note + KG
nodes + index entry, so knowledge compounds rather than disappearing
into chat history. Methods: ``store_answer()``, ``cross_link()``,
``suggest_connections()``. 20 unit tests. All 1700 unit tests pass.
Commits: 62834b3, 53f2f86

### ✅ STDB UniqueColumn::update() deprecation tracking — resolved (Jun 25)
**RESOLVED: UniqueColumn::update() is NOT deprecated in STDB v2.6.0.**  
Source code review confirms `update()` on `UniqueColumn` is still the
standard upsert mechanism. No deprecation warning or removal notice exists.
Kept for periodic re-check.

### ✅ Compounder.search_entities() — label/type/semantic entity search (Jun 25)
New `search_entities(workspace_id, label, node_type, semantic_query, limit)`
method on Compounder. Three search modes — label exact match, node_type filter,
semantic search via hybrid engine (filters entity_type=="node"). Merges and
deduplicates results. 6 new unit tests. MCP tool `search_entities` added.
CLI command `stmem search-entities` added. AGENTS.md updated.
Files: sdk/python/spacetime_memory/compounder.py,
       sdk/python/tests/test_compounder.py,
       server/mcp/main.py, cli/stmem.py, AGENTS.md

---

## Deferred / Blocked

### STDB 2% fatal error under heavy concurrent load
**uuid_v4_uniq mitigation is complete** — all 27 primary-key inserts use
collision-retry. The remaining ~2% fatal errors appear to be a STDB-level
WASM limitation (not UUID-related). Root cause analysis requires a live
STDB instance with replicator stress testing. Deferred until live STDB
infrastructure is available for investigation.
Files: server/spacetimedb/src/lib.rs, tests/concurrent/
Difficulty: Hard (needs live STDB)

---

*(cron manages this section — moves items here when marked ✅, purges old ones)*
