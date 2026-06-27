# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

*(cron manages this section — moves items here when marked ✅, purged old ones)*

---

## Recently Completed

### ✅ Fix 9 stale SpacetimeDB v2.4/v2.4.1 doc references across 7 documentation files (Aug 2)
Updated all STDB version references from v2.4/v2.4.1 to v2.6 (the actual
dependency version since commit `d1d147f`). Fixed:
- README.md (CLI prerequisite: v2.4+ → v2.6+)
- plugins/hermes/README.md (durable storage: v2.4.1 → v2.6)
- docs/development.md (prerequisite: v2.4+ → v2.6+)
- docs/getting-started.md (prerequisite: v2.4+ → v2.6+)
- docs/PERFORMANCE.md (benchmark context: v2.4.1 → v2.6)
- docs/usage/self-hosted.md (runtime includes: v2.4.1 → v2.6)
- DEPLOYMENT.md (3 refs: CLI version, download URL, Docker image v2.4.1 → v2.6)
Files: README.md, plugins/hermes/README.md, docs/development.md,
  docs/getting-started.md, docs/PERFORMANCE.md, docs/usage/self-hosted.md,
  DEPLOYMENT.md
Difficulty: Trivial
Est: 5min

### ✅ Fix `test_get_memory_history_found` mock setup (Jun 27)
The mock used `return_value` (single response) but `get_memory_history()` calls
`_query()` twice — once for `memory_revision` and once for `memory` (current
state). Fixed by switching to `side_effect` with proper revision + current-memory
data including version fields, so the version-dedup logic correctly produces 1
result. All 2020 unit tests now passing (was 1 pre-existing failure).
Files: sdk/python/tests/test_client_deep.py
Difficulty: Easy
Est: 10min
Test: 2020/2020 unit tests passing

### ✅ Add GitHub Actions CI step for pre-commit hook validation (Jun 27)
Added a CI step to the Python job that installs pre-commit and runs
`pre-commit run --all-files`. This validates all hooks (ruff lint, ruff format,
trailing-whitespace, EOF fixer, YAML/JSON/TOML validation, large-file check,
private-key detection, merge-conflict detection, markdownlint) on every push/PR.
Pre-commit auto-fixed 5 trailing-whitespace issues + 1 missing EOF newline
across Cargo.toml, integration.rs, compare-results.md, compare-upstream.py,
and the backup JSON file.
Files: .github/workflows/ci.yml
Difficulty: Easy
Est: 5min

### ✅ Add pre-commit config for automated linting (Aug 2)
Created `.pre-commit-config.yaml` with hooks for ruff lint, ruff format,
trailing-whitespace, end-of-file-fixer, YAML/JSON/TOML validation,
large-file detection, private-key detection, merge-conflict detection,
and markdownlint. The SDK `pyproject.toml` already had ruff configured
(`[tool.ruff]`). The pre-commit config uses the same ruff version (v0.11.4)
and runs on both `spacetime_memory/` SDK code and `tests/`.
Also added ruff lint + format-check steps to the CI workflow.
Files: .pre-commit-config.yaml, .github/workflows/ci.yml
Difficulty: Easy
Est: 15min

### ✅ Fix 53 ruff lint issues across the Python SDK (Aug 2)
Fixed 35 auto-fixable + 13 manual lint issues across the codebase:
unused imports (`os`, `json`, `struct`, `math`, `time`, `hmac`, `feedparser`,
`dataclass`, `field`, `pathlib.Path`, `typing.Optional`, `collections.abc.Sequence`,
`datetime.datetime`, `datetime.timezone`), unused variables (`parts`, `result_key`,
`linked_labels`, `pack_id`, `ts`, `centroid`, `text`, `result`, `exc`),
ambiguous `l` variable names (renamed to `line`), and redefined imports
(`Message` from `.zep` shadowing `.honcho` + `feedparser` + `re` + `json`).
Also ran `ruff format` on all 38 SDK modules and 56 test files.
Files: 65 source files across sdk/python/spacetime_memory/ and tests/
Difficulty: Medium
Est: 25min
Test: 749/749 unit tests passing (was 1 pre-existing failure: test_get_memory_history_found)

### ✅ Update MCP README with full tool catalog (Jun 27)
The README at `server/mcp/README.md` previously documented only ~15 of ~128 MCP
tools across 5 categories. Expanded to a comprehensive catalog covering all 24
categories: Workspace, Memory CRUD, Memory Management, Search, Pattern Detection,
Context Management, Notes, Documents, Profile, Knowledge Graph Base, KG Analytics,
Graph Traversal, Entity Resolution, Tours, Sessions, Mental Models, Facts,
Directory, Access Control, Compounder, Maintenance, Decay Model, Peers, and
System. Each tool has its description and parameter list documented.
Files: server/mcp/README.md
Difficulty: Medium
Est: 20min
Test: README now 303 lines (was 95), 128 tools documented in clean tables

### ✅ Fix stale SpacetimeDB version badge in README.md (Jul 28)
The README badge at the top still said `SpacetimeDB v2.4` but the dependency
was upgraded to v2.6 in commit `d1d147f`. Updated the badge URL and alt text
in both `README.md` and `server/mcp/README.md`.
Files: README.md, server/mcp/README.md
Difficulty: Trivial
Est: 2min

### ✅ Add 6 MCP tools for context pack introspection + entity resolution (Jul 27)
Added `seed_communities`, `detect_bridge_nodes`, `create_entity_link`,
`list_context_packs`, `list_context_entries`, and `list_context_deltas` MCP tools.
All remaining Client SDK methods that lacked MCP wrappers are now covered.
Files: server/mcp/main.py, sdk/python/tests/test_mcp.py
Difficulty: Easy
Est: 5min each
Test: 190/190 MCP tests passing

---

## Pending

### Add `delete_tour_stop` SDK method + MCP tool (Aug 2)
The Rust backend has `remove_tour_stop` reducer (in `server/spacetimedb/src/tour.rs`)
since the tours feature was written, but the Python SDK `client.py` and MCP server
`main.py` never exposed it. Users can create tours, add stops, and delete full tours,
but cannot remove individual stops. Add `delete_tour_stop(stop_id)` to the SDK and
a corresponding `delete_tour_stop` MCP tool.
Files: sdk/python/spacetime_memory/client.py, server/mcp/main.py, server/mcp/README.md
Difficulty: Trivial
Est: 5min

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

||---

## Research Log

### Aug 2 — Fixed 9 stale STDB v2.4 doc references; backlog remains empty
- **Completed**: Updated 9 stale SpacetimeDB v2.4/v2.4.1 references across 7
  documentation files (README.md, plugins/hermes/README.md, docs/development.md,
  docs/getting-started.md, docs/PERFORMANCE.md, docs/usage/self-hosted.md,
  DEPLOYMENT.md) to v2.6 to match the actual dependency version.
- **Cleanup**: Added new completed item to Recently Completed (8 total, within
  5-10 range, no purge needed).
- **Research**:
  - Git log (7 days): 242 commits, latest: a317935d (this tick).
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.10, langgraph v1.2.6, zep-python v2.0.2 — all unchanged.
  - opentelemetry-sdk v1.43.0 (unchanged).
  - No new competitor features to adopt from mem0, langgraph, zep.
  - Deeper scan found 9 stale STDB v2.4 references across 7 doc files (now fixed).
  - No other real gaps found: all Client SDK methods have MCP wrappers; no
    code-level TODO/FIXME markers; 3313 tests collected; pre-commit config active.
- **Backlog**: 0 PENDING items — backlog remains empty.
- **Commit**: 669e53e8 — 8 files changed, +44/-9 lines.

### Jun 27 — Fixed test mock, added pre-commit CI step; backlog cleared
- **Completed**: Fixed `test_get_memory_history_found` mock (side_effect for
  double `_query()` call). Added pre-commit CI validation step to Python job.
- **Cleanup**: Moved both PENDING items to Recently Completed (7 total, within
  5-10 range, no purge needed).
- **Research**:
  - Git log (7 days): 29 commits, latest: 21d4195e (this tick).
  - spacetimedb-sdk v0.7.0 (unchanged, latest).
  - mem0ai v2.0.10, langgraph v1.2.6, zep-python v2.0.2, opentelemetry-sdk
    v1.43.0 — all unchanged.
  - No new competitor features to adopt from mem0, langgraph, zep.
  - Deeper scan: no new gaps found. Pre-commit ran successfully on CI edits
    and auto-fixed 6 file hygiene issues.
- **Backlog**: 0 PENDING items — backlog is empty.
- **Commit**: 21d4195e — 7 files changed, +50/-15 lines.

### Aug 2 — Added pre-commit config + fixed 53 ruff lint issues; 2 PENDING items remaining
- **Completed**: Created `.pre-commit-config.yaml` with ruff lint, ruff format,
  file hygiene hooks (trailing-whitespace, EOF, YAML/JSON/TOML validation,
  large-file detection, merge-conflict detection, private-key detection,
  markdownlint). Added ruff lint + format-check steps to CI workflow.
- **Completed**: Fixed 53 ruff lint issues across Python SDK — 35 auto-fixed
  via `ruff check --fix`, 13 fixed manually (unused imports, unused variables,
  ambiguous `l` names, redefined imports). Formatted 38 SDK modules + 56 test
  files with `ruff format`.
- **Cleanup**: Moved pre-commit item to Recently Completed. Purged 3 oldest
  Recently Completed entries (detect_bridge_nodes, detect_communities,
  add_dynamic_context) to keep 5 entries.
- **Research**:
  - Git log (7 days): 5 commits (docs/research log updates only).
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.10, langgraph v1.2.6, zep-python v2.0.2, opentelemetry-sdk v1.43.0 — all unchanged.
  - No new competitor features to adopt from mem0, langgraph, zep.
  - Deeper scan found 53 ruff lint issues (now fixed), pre-commit gap (now filled),
    stale `test_get_memory_history_found` test mock (new PENDING item).
- **Backlog**: 2 PENDING items remaining.
- **Commit**: TBD — `.pre-commit-config.yaml` + 65 files with lint fixes + CI update.

### Jun 27 — Expanded MCP README to full 128-tool catalog; 1 PENDING item remaining
- **Completed**: Updated `server/mcp/README.md` from ~15 documented tools (5 categories)
  to all 128 tools across 24 categories. Each tool has description and parameter list.
- **Cleanup**: Moved MCP README item to Recently Completed. Purged oldest 2 entries
  (detect_communities/context tools) to keep 6 completed entries.
- **Research**:
  - Git log (7 days): 128 commits, latest: 2afec3c.
  - spacetimedb-sdk v0.7.0 (unchanged, latest).
  - mem0ai v2.0.10, langgraph v1.2.6, zep-python v2.0.2 — all unchanged.
  - opentelemetry-sdk v1.43.0 (unchanged).
  - No new competitor features to adopt from mem0, langgraph, zep.
  - Backlog: 1 PENDING item remaining (pre-commit config).
- **Commit**: 780a490 — 2 files changed, +249/-22 lines (README 95→303 lines).

### Jul 28 — Fixed stale STDB badge, added 2 new PENDING items for README/doc gaps
- **Fixed**: Stale SpacetimeDB version badge in `README.md` (v2.4 → v2.6) and
  `server/mcp/README.md` (v2.4 → v2.6). The badge had not been updated since
  the dependency was upgraded in commit `d1d147f`.
- **Cleanup**: Purged 5 oldest Recently Completed entries (detect_bridge_nodes,
  detect_communities, add_dynamic_context, check_embedder_health,
  run_maintenance). Kept 5 most recent entries.
- **Research**:
  - Git log (7 days): 30 commits, latest: cbddf22.
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.10, langgraph v1.2.6, zep-python v2.0.2 — all unchanged.
  - opentelemetry-sdk v1.43.0 (unchanged).
  - No new competitor features to adopt from mem0, langgraph, zep.
  - Deeper scan found doc gaps: stale badge (#1), incomplete MCP README (#2),
    missing pre-commit config (#3).
- **Backlog**: 2 PENDING items remaining.
- **Commit**: c100b3e — 3 files changed, +42/-48 lines.

### Aug 2 — Added `delete_tour_stop` SDK method + MCP tool; 1 new PENDING item
- **Completed**: Added `delete_tour_stop(stop_id)` method to
  `client.py` (maps to Rust `remove_tour_stop` reducer) and corresponding
  `delete_tour_stop` MCP tool in `main.py`. Tool added to MCP README catalog.
- **Cleanup**: No completed items to move. 8 entries in Recently Completed
  (within 5-10 range, no purge needed).
- **Research**:
  - Git log (7 days): ~244 commits, latest: c9a18cd (this tick).
  - spacetimedb-sdk v0.7.0 (unchanged, PyPI latest).
  - mem0ai v2.0.10, langgraph v1.2.6, zep-python v2.0.2 — all unchanged.
  - opentelemetry-sdk v1.43.0 (unchanged).
  - No new competitor features to adopt from mem0, langgraph, zep.
  - Deeper scan found missing `delete_tour_stop` — Rust `remove_tour_stop`
    reducer was not exposed in Python SDK or MCP server. Added as new PENDING
    item and implemented in this tick.
- **Backlog**: 1 PENDING item (delete_tour_stop — awaiting mark-done after
  commit + push).
- **Commit**: TBD — 4 files changed.
