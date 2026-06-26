# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Status: PENDING

### Add search for wiki notes via the hybrid search pipeline
The current hybrid search (semantic + keyword + graph + temporal) only searches
`memory` and `kg_node` via `search_index`. Wiki `note` documents (created by
Compounder.store_answer, create_entity_page, etc.) are not indexed or returned
by `client.search()`. Users must call `client._query("note", ...)` separately.
Add note indexing to the search pipeline so `search()` returns relevant notes
alongside memories and nodes.
Difficulty: Medium
Est: 45min

### Use entity_link aliases in entity-aware boosting
The new `_boost_with_entity_signal` matches entities by KG node labels, label
word-overlap, and summary substring.  The `entity_link` table stores canonical
entity names with aliases (e.g. "RLHF" → ["RLHF", "reinforcement learning from
human feedback"]).  Extend the boosting to also match against entity_link
aliases, so a query mentioning "reinforcement learning from human feedback"
boosts results mentioning the "RLHF" KG node and vice versa.
Difficulty: Easy
Est: 20min

### Add coverage for compilation-critical Rust modules with doc-tests
Several Rust reducer modules (consolidation.rs, change_event.rs, graph_traversal.rs)
have no Rust-level tests.  While full integration tests exist, doc-tests on
pure helper functions would provide fast compilation-free verification.
Add `/// ````````````` doc-test blocks on pure helper functions in these files.
Difficulty: Easy
Est: 30min

---

## Recently Completed

### ✅ Add entity-aware search result boosting (mem0 v3 multi-signal parity) (Jun 26)
Added `_boost_with_entity_signal()` method to the `Client` class that detects
knowledge-graph entities mentioned in the query and boosts the `fused_score` of
search results whose content references those entities. Uses three matching
strategies: (1) exact entity label in query, (2) word-level overlap, (3) query
substring in entity summary. Proportional boost scales with the fraction of
matched entities present in each result's content. Integrated into the
`search()` pipeline after `_enrich_content` and before cross-encoder reranking.
9 new unit tests covering all matching strategies and graceful degradation.
Files: sdk/python/spacetime_memory/client.py, sdk/python/tests/test_client.py

### ✅ Add note versioning/history tracking (note_revision table) (Jun 26)
Following the `memory_revision` pattern, added a `NoteRevision` STDB table with
`record_note_revision` helper function. Modified `update_note` reducer to save
revision snapshots before updates and increment the `version` field.
Added `version: 1` to `create_note`. Updated Python `get_note_history()` to
query real revision history from the `note_revision` table. Added `note_revision`
to `ALLOWED_TABLES` whitelist and `query_note_revision` handler.
Files: server/spacetimedb/src/note.rs, server/spacetimedb/src/query.rs,
       sdk/python/spacetime_memory/client.py

### ✅ Add scheduled workspace maintenance via STDB `#[table(scheduled(...))]` (Jun 26)
Scheduled maintenance was already implemented via `maintenance_schedule` table
with `scheduled(run_maintenance)` + `#[reducer(init)]` in consolidation.rs.
The system runs expiry every 5 min and decay every 60 min. Marking as done.
Files: server/spacetimedb/src/consolidation.rs

### ✅ Add memory versioning/history tracking via memory_revision table (Jun 26)
Added `memory_revision` STDB table with `record_revision` helper function.
Modified `update_memory` reducer to save revision snapshots before updates
and increment the `version` field (previously defined but never incremented).
Updated Python `get_memory_history()` to query real revision history from
the `memory_revision` table (instead of returning just the current state).
Added `memory_revision` to `ALLOWED_TABLES` whitelist and added
`query_memory_revision` handler. 4 new unit tests.
Files: server/spacetimedb/src/memory.rs, server/spacetimedb/src/query.rs,
       sdk/python/spacetime_memory/client.py,
       sdk/python/tests/test_client.py

### ✅ Add near-duplicate memory detection on store (Jun 26)
Added `find_near_duplicates()` method to Compounder that uses the
existing hybrid search pipeline with a configurable threshold (default
0.92) to detect semantically similar content before creating new notes.
Integrated into `store_answer()` and `store_answers()` via new
`skip_duplicates=True` and `duplicate_threshold=0.92` parameters.
When a near-duplicate is found, the method returns early with a
`duplicate_of` key instead of creating a new note. 10 new tests added.
Files: sdk/python/spacetime_memory/compounder.py,
       sdk/python/tests/test_compounder.py

### ✅ Add integration tests for full compounder pipeline (Jun 26)
Added 17 integration tests covering the full LLM Wiki pipeline tested
against real STDB: store_answer, store_answers batch, manual KG
creation, suggest_connections (2-link graph analysis), lint (orphans +
missing crossrefs), export (system note filtering, empty workspace),
and search_entities (label, type, no-match). Also fixed a latent bug
where store_answer/ingest_source silently dropped note IDs because
create_note returns {'status': 'ok'} not the note data.
Files: sdk/python/tests/test_compounder_integration.py,
       sdk/python/spacetime_memory/compounder.py

### ✅ Add MCP tool tests for core graph/pagerank/community tools (Jun 26)
Added `mock_mcp_client` fixture and 19 tests for 8 graph/community MCP
tools: get_node, get_neighbors, get_community, query_graph, shortest_path,
graph_bfs, compute_pagerank, and compute_community_hierarchy.
Tools now have coverage for success, empty, and default-parameter paths.
Files: sdk/python/tests/conftest.py, sdk/python/tests/test_mcp.py

### ✅ Add CLI tests for `store-answers-batch` error paths (Jun 26)
Added 11 CLI tests for `store-answers-batch` covering: help, valid pairs,
empty list, single pair, invalid JSON, not-a-list, wrong structure,
workspace passthrough, source IDs passthrough, file input, and
file-not-found error path.
Files: sdk/python/tests/test_cli_batch2.py

### ✅ Fix broken MCP tests — add missing `mock_compounder` fixture (Jun 26)
The `mock_compounder` fixture referenced by 29 MCP tool tests was never
defined, causing all test_mcp.py tests to fail with fixture-not-found.
Added fixture to conftest.py that patches `spacetime_memory.compounder.Compounder`
so all 39 MCP tests now pass.
Files: sdk/python/tests/conftest.py

### ✅ Add `store_answers_batch` MCP tool tests (Jun 26)
Added 10 unit tests for the `store_answers_batch` MCP tool covering:
valid batches, empty list, single pair, invalid JSON, wrong structure,
workspace ID passthrough, source_memory_ids parsing, and no-entities.
Files: sdk/python/tests/test_mcp.py

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
