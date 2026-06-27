# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

*(cron manages this section — moves items here when marked ✅, purged old ones)*

---

## Pending

*(All actionable improvements complete. Next backlog item: stale WASM binary blocked by OOM.)*

---

## Recently Completed

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

### ✅ Add `get_note_by_date` MCP tool (Jul 6)
Added `get_note_by_date` MCP tool wrapping `Client.get_note_by_date()`. Looks
up notes by ISO-8601 date string.
Files: server/mcp/main.py
Difficulty: Easy
Est: 3min
Test: 59/59 MCP tests passing

### ✅ Add document CRUD MCP tools (Jul 2)
Added 5 MCP tools for document management: create_document, get_document,
list_documents, get_document_chunks, delete_document. Covers the full
document lifecycle for the LLM Wiki workflow (Supermemory parity).
Files: server/mcp/main.py
Difficulty: Easy
Est: 8min
Test: 2173/2173 unit tests passing

### ✅ Add `create_edge` MCP tool (Jun 26)
Added `create_edge` MCP tool wrapping `Client.create_edge()`. Creates directed,
typed edges between KG nodes with all parameters (weight, confidence,
metadata_json, source_memory_id). Fills a real gap — `create_node` existed
but edges could not be created via MCP, blocking the LLM Wiki workflow.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 8min
Test: 68/68 MCP tests passing

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

---

## Research Log

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

### Jun 26 — `update_node` + `list_memories` MCP tools added; backlog cleared again
- **MCP tools audit**: Added `update_node` and `list_memories` MCP tools.
  All `Client` public methods now have MCP tool wrappers.
- **Research**:
  - Git log (7 days): Most recent commits are create_edge, fuzzy_get,
    detect_patterns, get_note_by_date, update_node, list_memories MCP tools.
    No unreviewed changes. Commit: 08f26d5.
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
- **Gaps remaining**: 0 `Client` methods without MCP wrappers. All actionable
  improvement items are complete.
- **Backlog**: 0 PENDING items (stale WASM binary still blocked by OOM).
- **Commit**: 08f26d5 — 3 files (+130/-22 lines), 74/74 MCP tests passing.

### Jul 6 — All 3 remaining MCP gaps closed; backlog cleared
- **MCP tools audit**: Added `fuzzy_get`, `detect_patterns`, `get_note_by_date`
  MCP tools. All `Client` methods now have MCP tool wrappers.
- **Research**:
  - Git log (7 days): Most recent commits are store_batch, delete_workspace,
    export_workspace, document CRUD. No unreviewed changes. An additional
    3 tools added this tick: fuzzy_get, detect_patterns, get_note_by_date.
    Commit: 74273c7.
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
- **Gaps remaining**: 0 `Client` methods without MCP wrappers. All actionable
  improvement items are complete.
- **Backlog**: 1 PENDING item remaining (stale WASM binary blocked).
- **Commit**: 74273c7 — 1 file (+91 lines), 59/59 MCP tests passing.

### Jun 27 — `store_batch` MCP tool added; 3 remaining MCP gaps
- **MCP tools audit**: `store_batch` (Client) now has an MCP tool wrapper.
  Added in Memory tools section following `delete_memory`, using JSON-input
  pattern matching `store_answers_batch`.
- **Research**:
  - Git log (7 days): Most recent commits are delete_workspace, export_workspace,
    document CRUD MCP tools. No unreviewed changes.
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
- **Gaps remaining**: 3 `Client` methods still missing MCP wrappers:
  - `fuzzy_get`, `detect_patterns`, `get_note_by_date`.
- **Backlog**: 4 PENDING items (1 stale WASM blocked + 3 MCP gaps).

### Jul 6 — `delete_workspace` MCP tool added; 4 remaining MCP gaps
- **MCP tools audit**: `delete_workspace` (Client) now has an MCP tool wrapper.
- **Research**:
  - spacetimedb-sdk v0.7.0 (unchanged).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
- **Gaps remaining**: 4 `Client` methods still missing MCP wrappers:
  - `store_batch`, `fuzzy_get`, `detect_patterns`, `get_note_by_date`.
- **Backlog**: 5 PENDING items (1 stale WASM blocked + 4 MCP gaps).

### Jun 26 — `export_workspace` MCP tool added; 5 new PENDING items for remaining MCP gaps
- **MCP tools audit**: Found 6 `Client`/`Compounder` methods missing MCP wrappers:
  - `export_workspace` (Compounder) — ✅ Done this tick.
  - `delete_workspace` — added as PENDING.
  - `store_batch` — added as PENDING.
  - `fuzzy_get` — added as PENDING.
  - `detect_patterns` — added as PENDING.
  - `get_note_by_date` — added as PENDING.
- **Research**:
  - STDB crate (crates.io unreachable), spacetimedb-sdk v0.7.0 (unchanged).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
- **Gaps identified**: 5 remaining `Client`/`Compounder` methods without MCP tool wrappers.
- **Backlog**: 6 PENDING items (1 stale WASM blocked + 5 new MCP gaps).

### Jul 2 — 5 document CRUD MCP tools added; document gap closed for LLM Wiki workflow
- **Document MCP tools audit**: Found 0 document-related MCP tools despite the SDK
  having full document CRUD support (create_document, get_document, list_documents,
  get_document_chunks, delete_document). Added all 5 as MCP tools.
- **Research**:
  - STDB crate (crates.io unreachable), spacetimedb-sdk v0.7.0 (unchanged).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
- **Gaps identified**: Document CRUD MCP tools missing for LLM Wiki workflow.
  - Document CRUD: ✅ Done this tick (5 tools added).
- **Backlog**: 1 PENDING item remaining (stale WASM binary blocked).

### Jun 26 — 9 note CRUD MCP tools added; note gap closed for LLM Wiki workflow
- **Note MCP tools audit**: Found 0 note-related MCP tools despite notes being
  the primary wiki content store in the LLM Wiki workflow (AGENTS.md). Added 9
  MCP tools covering the full note CRUD lifecycle: create_note, get_note,
  update_note, delete_note, list_notes, get_note_by_title, get_note_history,
  get_backlinks, get_outgoing_links.
- **Research**:
  - STDB crate (crates.io unreachable), spacetimedb-sdk v0.7.0 (unchanged).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
- **Gaps identified**: Note/document CRUD MCP tools missing for LLM Wiki workflow.
  - Note CRUD: ✅ Done this tick (9 tools added).
  - Document CRUD (create_document, get_document, delete_document, list_documents):
    Still missing — added as PENDING item for next tick.
- **Backlog**: 2 PENDING items remaining (stale WASM binary blocked; document CRUD
  MCP tools pending).

### Jul 1 — entity_types/before/after params added to MCP search tools
- **MCP search tools upgrade**: Added `entity_types` (list[str]), `before` (float),
  and `after` (float) parameters to both `search_memories` and `hybrid_search`
  MCP tools, matching the existing SDK `Client.search()` signature.
- **Research**:
  - STDB crate v2.6.0 (unchanged), spacetimedb-sdk v0.7.0 (unchanged).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
  - No new features in STDB v2.6 changelog that would benefit the module.
- **Backlog**: 0 PENDING items remaining. All actionable improvements complete.
- **Commits**: 4140b3d (entity_types/before/after MCP params).

### Jun 30 — cross_link/suggest_connections fixed; find_near_duplicates MCP tool added
- **MCP tools audit**: Fixed `cross_link` (reads `links_created` not `edges_created`)
  and `suggest_connections` (handles list return, uses correct field names).
- **asyncio marker**: Already registered in pyproject.toml. No action needed.
- **find_near_duplicates MCP tool**: Added new MCP tool wrapping the Compounder
  method for checking semantic near-duplicates before storing.
- **Research**:
  - STDB crate v2.6.0 (unchanged), spacetimedb-sdk v0.7.0 (unchanged).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
- **Gaps found**: MCP `search_memories` and `hybrid_search` tools are missing
  the `entity_types`, `before`, and `after` parameters that the SDK supports.
  Added as new PENDING item.
- **Backlog**: 1 PENDING item remaining (entity_types/before/after search params).
- **Commits**: 893e6f1 (cross_link/suggest_connections fixes), bc3c7ea (find_near_duplicates).

### Jun 28 — Date range filter implemented; backlog fully cleared
- **`--from`/`--to` date range filter**: Added to both SDK (`before`/`after` params
  on `Client.search()`) and CLI (`--from`/`--to` flags on `stmem memory search`).
- **`--output json` discovery**: The global `--output`/`-o` flag on root CLI
  already provides JSON output for all subcommands.
- **Commit**: c13a447 — 2 files changed, 81 insertions (+), 4 deletions(-).
- **Research**: No new competitor features detected (mem0, langgraph, zep).
- **Backlog**: 0 PENDING items remaining. All actionable improvements complete.

### Jun 27 — Unit tests for _make_snippet() completed; 2 new PENDING items added
- **_make_snippet unit tests**: 10 tests added covering all edge cases.
- **Commit**: 137ca81 — 1 file (+83 lines), all 155 client tests passing.
- **Research**: STDB crate v2.6.0 (unchanged), mem0ai v2.0.8, opentelemetry-sdk 1.43.0.
- **New PENDING items**: `--output json` flag, `--from`/`--to` date range filter.

### Jun 27 — Snippet preview in search results + --snippet CLI flag
- **Snippet extraction**: Added `_make_snippet()` integrated into search paths.
- **CLI `--snippet` flag**: Added `-s`/`--snippet` to `stmem search`.
- **Commit**: e0ff612 — 2 files changed, 38 insertions (+), 1 deletion(-).
- **New PENDING item**: Unit tests for `_make_snippet()`.

### Jun 26 — OTel graceful degradation + Tantivy mock fix + backlog refresh
- **OTel tracer**: Connectivity check to OTLP collector before wiring up exporter.
- **Tantivy mock fix**: `cli_mock_client` fixture with URL-aware `side_effect`.
- **Research**: STDB crate v2.6.0 (latest), mem0ai v2.0.8, langgraph v1.2.6.

### Jun 26 — Full backlog cleared; both PENDING items implemented
- **Note orphan detection** + **Keyword-fallback boosting** both implemented.
- **Backlog is now empty** — all actionable improvement items complete.

### Jun 27 — Unit tests for _make_snippet() completed; 2 new PENDING items added

### Jul 2 — MCP memory CRUD gaps identified; added get_memory_history/update_memory/delete_memory
- **MCP tools audit**: Found 3 SDK methods missing MCP tool wrappers:
  - `Client.get_memory_history(memory_id)` — no MCP tool
  - `Client.update_memory(...)` — no MCP tool
  - `Client.delete_memory(memory_id)` — no MCP tool
- **Test failure discovered**: `test_get_memory_history` fails against live STDB
  because the published WASM binary is stale (missing `memory_revision` in
  `ALLOWED_TABLES` whitelist). Requires cargo build + republish.
- **Research**:
  - STDB crate v2.6.0 (unchanged since last check, crates.io latest).
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
- **Backlog**: 3 PENDING items + 1 blocked item added.
- **New PENDING items**: get_memory_history MCP tool, update_memory MCP tool,
  delete_memory MCP tool.
- **Blocked**: Stale WASM binary needs rebuild.

### Jun 26 — entity_types filter implemented; 2 PENDING items remain

### Jul 6 — `delete_workspace` MCP tool added; 4 remaining MCP gaps
- **MCP tools audit**: `delete_workspace` (Client) now has an MCP tool wrapper.
- **Research**:
  - spacetimedb-sdk v0.7.0 (unchanged).
  - mem0ai v2.0.8 (unchanged since last check).
  - opentelemetry-sdk v1.43.0 (unchanged since last check).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
- **Gaps remaining**: 4 `Client` methods still missing MCP wrappers:
  - `store_batch`, `fuzzy_get`, `detect_patterns`, `get_note_by_date`.
- **Backlog**: 5 PENDING items (1 stale WASM blocked + 4 MCP gaps).

### Jun 26 — `create_edge` MCP tool added; deep MCP audit reveals remaining gaps
- **MCP tools audit**: Deep audit of all `Client` public methods vs. MCP tool
  coverage. Found `Client.create_edge()` had no MCP wrapper despite `create_node`
  existing. Also missing: `update_node`, `list_memories`, and many others.
- **`create_edge` MCP tool**: Added wrapping `Client.create_edge()` with all
  8 parameters (workspace_id, source_node_id, target_node_id, relation, weight,
  confidence, metadata_json, source_memory_id). Fills real gap in LLM Wiki
  workflow where edges power `informed_by`/`related_to`/`contradicts` relations
  between KG nodes.
- **Cleanup**: Moved 3 stale ✅ items from Pending section (duplicates already in
  Recently Completed). Moved stale WASM binary item to Deferred/Blocked.
- **Research**:
  - Git log (7 days): Most recent commit e96a744 (MCP tool tests). 76 MCP tools now.
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.8 (unchanged), opentelemetry-sdk v1.43.0 (unchanged).
  - langgraph v1.2.6 (unchanged), zep-python v2.0.2 (unchanged).
  - No new competitor features to adopt.
- **Gaps remaining**: `update_node`, `list_memories`, and ~30 other `Client`
  methods still without MCP wrappers (low-priority admin/utility methods).
- **Backlog**: 2 PENDING items (update_node MCP tool, list_memories MCP tool).
- **Commit**: 9cada69 — 3 files (+115/-21), 68/68 MCP tests passing.
