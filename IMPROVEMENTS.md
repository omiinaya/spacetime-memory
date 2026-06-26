# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Status: PENDING

*No pending items — all backlog has been implemented.*

---

## Recently Completed

### ✅ Apply entity-aware boosting in keyword fallback path (Jun 26)
`_boost_with_entity_signal` is now called at the end of `_keyword_fallback`,
applying entity-aware signal boosting (with entity_link alias support) that was
previously only available in the semantic search path. Results get a baseline
`fused_score` based on recency position before boosting, then are re-sorted by
boosted score. Empty query skips boost. 3 new unit tests.
Commit: 2b91198
Files: sdk/python/spacetime_memory/client.py, sdk/python/tests/test_client.py
Difficulty: Easy
Est: 15min

### ✅ Add note orphan detection to lint_workspace() (Jun 26)
Added `_find_note_orphans()` method to Compounder that detects notes
entirely disconnected from the knowledge graph. Notes are flagged when
their content/title mentions no KG node labels AND their ID does not
appear in any KG edge. New `check_note_orphans=True` parameter on
`lint_workspace()`. Included in summary counts, log messages, and MCP output.
5 new unit tests.
Commit: a9d7106
Files: sdk/python/spacetime_memory/compounder.py, sdk/python/tests/test_compounder.py,
       server/mcp/main.py
Difficulty: Medium
Est: 30min

### ✅ Add entity_types filter parameter to search() (Jun 26)
Added `entity_types` parameter to `search()` — filters results by
`entity_type` after fusion, before reranking. Applied in both hybrid
and keyword-fallback paths. 4 new unit tests.
Commit: 4376002
Files: sdk/python/spacetime_memory/client.py, sdk/python/tests/test_client.py
Difficulty: Easy
Est: 15min

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

|| *(cron manages this section — moves items here when marked ✅, purged old ones)*
|

## Research Log

### Jun 26 — Full backlog cleared; both PENDING items implemented
- **Note orphan detection** (Item 1): `_find_note_orphans()` — notes with no
  KG label mentions and no edges flagged in lint output. 5 tests. Done.
- **Keyword-fallback boosting** (Item 2): `_boost_with_entity_signal` now
  called at the end of `_keyword_fallback`. 3 tests. Done.
- **Backlog is now empty** — all actionable improvement items are complete.
- STDB 2.6 is latest; spacetimedb-sdk 0.7.0. No new competitor features
  identified (mem0, langgraph, zep). Deferred item still needs live STDB.

### Jun 26 — entity_types filter implemented; 2 PENDING items remain
- Implemented: `entity_types` filter parameter for `search()` in both
  hybrid and keyword-fallback paths. 4 unit tests, all passing.
- Next items in queue: Note orphan detection, keyword-fallback boosting.

### Jun 26 — Doc-tests added to compilation-critical Rust modules; entity_types filter next
- Added doc-test to `record_to_json` (change_event.rs) + enhanced `edit_distance` doc
- Found: consolidation.rs already has 8 unit tests; graph_traversal.rs has no pure helpers
- Next item in queue: `entity_types` filter parameter for `search()`

### Jun 26 — Entity-link alias boosting done; keyword-fallback boosting gap found
- Implemented: entity_link alias matching in `_boost_with_entity_signal`
- Found gap: `_keyword_fallback` (called when embedder is down) doesn't apply entity-aware boosting at all. Only the semantic search path calls `_boost_with_entity_signal`. Added PENDING item below.
- The remaining 3 PENDING items in the queue are the next targets.
