# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

| Status | Item |
|--------|------|
| ✅ | Add `find_near_duplicates` MCP tool |
| PENDING | Add `entity_types` and `before`/`after` params to MCP search tools |

### ✅ Add `find_near_duplicates` MCP tool
Added `find_near_duplicates` MCP tool wrapping the Compounder method. Accepts
`content`, `workspace_id`, `threshold` (default 0.92), `limit` (default 5).
Returns formatted list of near-duplicate candidates with entity type, ID, score,
and content snippet.
Files: server/mcp/main.py
Difficulty: Easy
Est: 8min

### Add `entity_types` and `before`/`after` params to MCP search tools
The SDK `Client.search()` supports `entity_types` (list[str]), `before` (float),
and `after` (float) parameters for filtering by entity type and creation date.
The MCP `search_memories` and `hybrid_search` tools don't expose these yet.
Files: server/mcp/main.py
Difficulty: Easy
Est: 10min

---

## Recently Completed

### ✅ Add `cross_link` and `suggest_connections` MCP tools (Jun 30)
Both tools already existed in `server/mcp/main.py` but had field-name mismatches
with the Compounder return types:
- `cross_link` read `result["edges_created"]` but compounder returns `links_created`.
- `suggest_connections` did `result.get("suggestions", [])` on a list (AttributeError),
  and used wrong field names (`source`/`target`/`score` instead of
  `source_label`/`target_label`/`common_count`).
- Both fixed to use correct compounder return field names.
- Files: server/mcp/main.py
- Difficulty: Easy
- Est: 10min

### ✅ Register `asyncio` pytest marker to stop warning noise (Jun 30)
The `asyncio` marker was already registered in `sdk/python/pyproject.toml`'s
`[tool.pytest.ini_options]` markers list (line 75). No code change needed.
Files: sdk/python/pyproject.toml
Difficulty: Trivial
Est: 2min

### ✅ Add `--from`/`--to` date range filter to CLI search (Jun 28)
Added `--from` and `--to` flags to `stmem memory search` for filtering results
by creation date. Accepts ISO-8601 dates (e.g. `2026-06-01`, `2026-06-01T12:00:00Z`)
or Unix epoch timestamps. SDK `search()` gained `before`/`after` parameters.
Commit: c13a447
Difficulty: Easy
Est: 15min

### ✅ Add unit tests for `_make_snippet()` (Jun 27)
Added 10 unit tests for the word-boundary text truncation function.
Commit: 137ca81
Difficulty: Easy
Est: 10min

### ✅ Add note content preview to search results (snippet extraction) (Jun 27)
When `search()` returns results, each result dict includes a `snippet` key with
word-boundary truncated preview (~200 chars) of the content.
Commit: e0ff612
Files: sdk/python/spacetime_memory/client.py
Difficulty: Easy
Est: 15min

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

*(cron manages this section — moves items here when marked ✅, purged old ones)*

---

## Research Log

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

### Jun 26 — entity_types filter implemented; 2 PENDING items remain

### Jun 26 — Doc-tests added to compilation-critical Rust modules

### Jun 26 — Entity-link alias boosting done; keyword-fallback boosting gap found
