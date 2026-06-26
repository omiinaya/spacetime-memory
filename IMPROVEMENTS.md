# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Status: PENDING

### Add entity_types filter parameter to search()
The `search()` method has `memory_type` and `tier` filters but no way to
select which content types to return (memory, note, node).  Add an
`entity_types` parameter (e.g. `entity_types=["memory", "note"]`) that
filters after fusion so users can scope searches to notes only or exclude
noisy memory results.  The filter should apply in both semantic and
keyword-fallback paths.
Difficulty: Easy
Est: 15min

### Add note orphan detection to lint_workspace()
The `lint_workspace()` method currently checks for KG nodes with no edges
(orphans) and missing cross-refs between notes and entities.  It does not
check for notes that are entirely disconnected from the KG — notes that
exist as wiki pages but have no corresponding KG nodes or edges.  Add a
`note_orphans` section to the lint result that lists notes whose content
mention no known entities and have no KG connections.
Difficulty: Medium
Est: 30min

### Apply entity-aware boosting in keyword fallback path
When the embedder is unavailable (or semantic search is disabled), `search()`
falls back to `_keyword_fallback()`. That path does NOT call
`_boost_with_entity_signal`, so entity-aware boosting is completely absent
when there are no embeddings. Add boosting (with entity_link alias support)
at the end of `_keyword_fallback`, before the limit+return.
Difficulty: Easy
Est: 15min

---

## Recently Completed

### ✅ Add coverage for compilation-critical Rust modules with doc-tests (Jun 26)
Added a runnable doc-test to `record_to_json` in change_event.rs (the only pure
`pub fn` amongst the three modules). Enhanced doc comment for `edit_distance`
in consolidation.rs with a usage example (function already has 8 unit tests
in a `#[cfg(test)]` block). graph_traversal.rs has no pure helper functions
suitable for doc-tests.
Commit: a16c187
Files: server/spacetimedb/src/change_event.rs, server/spacetimedb/src/consolidation.rs

### ✅ Use entity_link aliases in entity-aware boosting (Jun 26)
The `_boost_with_entity_signal` method now also fetches entity_link records
alongside KG nodes. When the query matches an entity_link alias (e.g.
"reinforcement learning from human feedback" → canonical "RLHF"), the
canonical name AND all aliases are checked against result content for
proportional boosting. Both KG node labels and entity_link aliases contribute
to the entity-hit count. Graceful degradation if entity_link table is
unavailable.
Commit: c907187
Files: sdk/python/spacetime_memory/client.py, sdk/python/tests/test_client.py
Difficulty: Easy
Est: 20min

### ✅ Add search for wiki notes via the hybrid search pipeline (Jun 26)
Notes created via `create_note`/`update_note` are now indexed into `search_index`,
`term_index`, and Tantivy BM25, making them discoverable via `search()` (both
semantic hybrid and keyword fallback). Added `"note"` to valid entity_types in
Rust `index_entity` reducer. Python `_enrich_content` resolves note title+content
for entity_type="note". `_keyword_fallback` merges notes with memory results.
8 new unit tests.
Commit: 21ca33c
Files: server/spacetimedb/src/retrieval.rs, sdk/python/spacetime_memory/client.py,
       sdk/python/tests/test_client.py, sdk/python/tests/test_memory.py

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

| *(cron manages this section — moves items here when marked ✅, purges old ones)*
|

## Research Log

### Jun 26 — Doc-tests added to compilation-critical Rust modules; entity_types filter next
- Added doc-test to `record_to_json` (change_event.rs) + enhanced `edit_distance` doc
- Found: consolidation.rs already has 8 unit tests; graph_traversal.rs has no pure helpers
- Next item in queue: `entity_types` filter parameter for `search()`

### Jun 26 — Entity-link alias boosting done; keyword-fallback boosting gap found
- Implemented: entity_link alias matching in `_boost_with_entity_signal`
- Found gap: `_keyword_fallback` (called when embedder is down) doesn't apply entity-aware boosting at all. Only the semantic search path calls `_boost_with_entity_signal`. Added PENDING item below.
- The remaining 3 PENDING items in the queue are the next targets.