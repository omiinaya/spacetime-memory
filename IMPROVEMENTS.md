# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Status: PENDING

### Add integration test that exercises the full ingest→search→cross-link pipeline
Current integration tests cover individual components but not the full
LLM Wiki workflow end-to-end (ingest source → search → cross-link →
suggest-connections → export). Add a test that runs the full pipeline.
Difficulty: Medium
Est: 1h

### Add memory versioning/history tracking (inspired by mem0 v3 `history`)
mem0 v2.0.8 (v3) supports per-memory change history tracking. The current
spacetime-memory system only has `_log_activity` for workspace-wide
audit tracking. Adding per-memory revision history (via an STDB
`memory_revision` table + reducer) would enable undo, diff, and
audit at the individual memory level.
Difficulty: Medium
Est: 1-2h

### Add scheduled workspace maintenance via STDB `#[procedure]`
STDB v2.5+ stabilized `#[spacetimedb::procedure]` for scheduled,
transaction-capable server-side functions. The module currently has
no `init` function or scheduled tasks. Adding a procedure for
periodic cross-linking, decay, or lint would reduce reliance on
external cron and improve consistency.
Difficulty: Medium
Est: 2h

### Add near-duplicate memory detection on store
When similar content is stored multiple times (e.g., same fact
re-phrased), the system creates duplicate memory entries. Adding
a lightweight similarity check before insert (using the existing
hybrid search) with a configurable threshold would prevent
duplication at write time.
Difficulty: Easy
Est: 30min

### Add entity-aware search result boosting (inspired by mem0 v3)
mem0 v3's multi-signal retrieval fuses semantic, BM25, and entity
signals. The current search pipeline does hybrid search (semantic +
BM25) but has no entity-aware boosting at query time. Add a step
that detects entities in the query and boosts results matching
those entities (KG node labels/summaries).
Difficulty: Easy
Est: 30min

---

## Recently Completed

### ✅ Add MCP tool tests for core graph/pagerank/community tools (Jun 26)
Added `mock_mcp_client` fixture and 19 tests for 8 graph/community MCP
tools: get_node, get_neighbors, get_community, query_graph, shortest_path,
graph_bfs, compute_pagerank, and compute_community_hierarchy.
Tools now have coverage for success, empty, and default-parameter paths.
Files: sdk/python/tests/conftest.py, sdk/python/tests/test_mcp.py
Commit: 2263d28

### ✅ Add CLI tests for `store-answers-batch` error paths (Jun 26)
Added 11 CLI tests for `store-answers-batch` covering: help, valid pairs,
empty list, single pair, invalid JSON, not-a-list, wrong structure,
workspace passthrough, source IDs passthrough, file input, and
file-not-found error path.
Files: sdk/python/tests/test_cli_batch2.py
Commit: feada71

### ✅ Fix broken MCP tests — add missing `mock_compounder` fixture (Jun 26)
The `mock_compounder` fixture referenced by 29 MCP tool tests was never
defined, causing all test_mcp.py tests to fail with fixture-not-found.
Added fixture to conftest.py that patches `spacetime_memory.compounder.Compounder`
so all 39 MCP tests now pass.
Files: sdk/python/tests/conftest.py
Commit: 37817bc

### ✅ Add `store_answers_batch` MCP tool tests (Jun 26)
Added 10 unit tests for the `store_answers_batch` MCP tool covering:
valid batches, empty list, single pair, invalid JSON, wrong structure,
workspace ID passthrough, source_memory_ids parsing, and no-entities.
Files: sdk/python/tests/test_mcp.py
Commit: 37817bc

### ✅ Add cross-link/suggest-connections CLI edge-case tests (Jun 26)
Added 3 new tests for `cross-link --dry-run`, `suggest-connections --limit 5`,
and `suggest-connections --json --limit 10` to fill coverage gaps.
Files: sdk/python/tests/test_cli_batch2.py
Commit: 37817bc

### ✅ Add unit tests for MCP tools (server/mcp/main.py) (Jun 25)
The MCP server has 40+ tools but zero test coverage. Start by adding
unit tests for `store_answers_batch`, `search_entities`, and the
compounder-related LLM Wiki tools (`ingest_source`, `lint_workspace`).
Use mocked client similar to test_compounder.py patterns.
Difficulty: Medium
Est: 1-2h

### ✅ Add `search_entities` MCP tool tests (Jun 25)
The MCP `search_entities` tool exists (line 1275) but has no dedicated
unit tests. Add tests for label/type/semantic search modes and empty
results edge case.
Difficulty: Easy
Est: 20min

### ✅ Add cross-link and suggest-connections coverage in CLI tests (Jun 25)
CLI commands `cross-link` and `suggest-connections` exist but
`test_cli_batch2.py` may not cover all error/edge-case paths.
Audit and fill gaps.
Difficulty: Easy
Est: 30min

### ✅ Add `store-answers-batch` CLI command (Jun 25)
Added `stmem store-answers-batch --pairs '[[...]]'` CLI command with
JSON validation, file input support (--file), and --json output.
Previously only existed as MCP tool.
Files: cli/stmem.py
Commit: ebff101

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
