# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

*(cron manages this section — moves items here when marked ✅, purged old ones)*

---

|## Pending
|
|### Fix stale WASM binary causing test_get_memory_history failure
|The published WASM binary at target/wasm32-wasip1/release/spacetime_memory.wasm
|is stale and doesn't include `memory_revision` in the query_table ALLOWED_TABLES
|whitelist. `test_get_memory_history` fails against the real STDB server.
|Fix: rebuild WASM module (requires cargo build, currently blocked by OOM).
|Files: server/spacetimedb/src/query.rs
|Difficulty: Medium (needs cargo build)
|Est: N/A (blocked)
|
|### Add `store_batch` MCP tool
|`Client.store_batch()` has no MCP wrapper. Add tool for batch memory storage
|with JSON items input.
|Files: server/mcp/main.py
|Difficulty: Easy
|Est: 5min
|
|### Add `fuzzy_get` MCP tool
|`Client.fuzzy_get()` has no MCP wrapper. Add tool for fuzzy matching by field
|content with difflib SequenceMatcher.
|Files: server/mcp/main.py
|Difficulty: Easy
|Est: 5min
|
|### Add `detect_patterns` MCP tool
|`Client.detect_patterns()` has no MCP wrapper. Add tool for temporal clustering,
|term extraction, and co-occurrence detection.
|Files: server/mcp/main.py
|Difficulty: Easy
|Est: 5min
|
|### Add `get_note_by_date` MCP tool
|`Client.get_note_by_date()` has no MCP wrapper. Add tool to look up notes by
|ISO-8601 date string.
|Files: server/mcp/main.py
|Difficulty: Easy
|Est: 3min
|
|---|

|## Recently Completed

|### ✅ Add `delete_workspace` MCP tool (Jul 6)
|Added `delete_workspace` MCP tool wrapping `Client.delete_workspace()`.
|Simple workspace deletion via MCP.
|Files: server/mcp/main.py
|Difficulty: Easy
|Est: 3min
|
|### ✅ Add `export_workspace` MCP tool (Jun 26)
|Added `export_workspace` MCP tool wrapping `Compounder.export_workspace()`.
|Exports wiki notes as markdown files with YAML frontmatter for Obsidian/git.
|Supports include_kg and include_system_notes flags.
|Files: server/mcp/main.py
|Difficulty: Easy
|Est: 5min
|Test: 58/58 MCP tests passing
|
|### ✅ Add document CRUD MCP tools (Jul 2)
|Added 5 MCP tools for document management: create_document, get_document,
|list_documents, get_document_chunks, delete_document. Covers the full
|document lifecycle for the LLM Wiki workflow (Supermemory parity).
|Files: server/mcp/main.py
|Difficulty: Easy
|Est: 8min
|Test: 2173/2173 unit tests passing
|
|### ✅ Add note CRUD MCP tools (Jun 26)
|Added 9 MCP tools for note management: create_note, get_note, update_note,
|delete_note, list_notes, get_note_by_title, get_note_history, get_backlinks,
|get_outgoing_links. Covers the full LLM Wiki note workflow (AGENTS.md).
|Files: server/mcp/main.py
|Difficulty: Easy
|Est: 12min
|Test: 155/155 unit tests passing
|
|### ✅ Add `entity_types`/`before`/`after` params to MCP search tools (Jun 26)
|Added `entity_types` (list[str]), `before` (float), and `after` (float) parameters
|to both `search_memories` and `hybrid_search` MCP tools, matching the SDK
|`Client.search()` signature.
|Files: server/mcp/main.py
|Difficulty: Easy
|Est: 10min
|
|### ✅ Add `find_near_duplicates` MCP tool (Jun 26)
|Added `find_near_duplicates` MCP tool wrapping the Compounder method. Accepts
|`content`, `workspace_id`, `threshold` (default 0.92), `limit` (default 5).
|Returns formatted list of near-duplicate candidates with entity type, ID, score,
|and content snippet.
|Files: server/mcp/main.py
|Difficulty: Easy
|Est: 8min
|
|### ✅ Add `cross_link` and `suggest_connections` MCP tools (Jun 26)
|Both tools already existed in `server/mcp/main.py` but had field-name mismatches
|with the Compounder return types:
|- `cross_link` read `result["edges_created"]` but compounder returns `links_created`.
|- `suggest_connections` did `result.get("suggestions", [])` on a list (AttributeError),
|  and used wrong field names (`source`/`target`/`score` instead of
|  `source_label`/`target_label`/`common_count`).
|- Both fixed to use correct compounder return field names.
|- Files: server/mcp/main.py
|- Difficulty: Easy
|- Est: 10min
|
|---|
|
|## Deferred / Blocked

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
- **_make_snippet unit tests**: 10 tests added covering all edge cases.
- **Commit**: 137ca81 — 1 file (+83 lines), all 155 client tests passing.
- **Research**: STDB crate v2.6.0 (unchanged), mem0ai v2.0.8, opentelemetry-sdk 1.43.0.
- **New PENDING items**: `--output json` flag, `--from`/`--to` date range filter.

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

|### Jun 26 — Doc-tests added to compilation-critical Rust modules
|
|### Jun 26 — Entity-link alias boosting done; keyword-fallback boosting gap found

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
