# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Status: PENDING

### Add unit tests for MCP tools (server/mcp/main.py)
The MCP server has 40+ tools but zero test coverage. Start by adding
unit tests for `store_answers_batch`, `search_entities`, and the
compounder-related LLM Wiki tools (`ingest_source`, `lint_workspace`).
Use mocked client similar to test_compounder.py patterns.
Difficulty: Medium
Est: 1-2h

### Add `search_entities` MCP tool tests
The MCP `search_entities` tool exists (line 1275) but has no dedicated
unit tests. Add tests for label/type/semantic search modes and empty
results edge case.
Difficulty: Easy
Est: 20min

### Add cross-link and suggest-connections coverage in CLI tests
CLI commands `cross-link` and `suggest-connections` exist but
`test_cli_batch2.py` may not cover all error/edge-case paths.
Audit and fill gaps.
Difficulty: Easy
Est: 30min

---

## Recently Completed

### ✅ Add `store-answers-batch` CLI command (Jun 25)
Added `stmem store-answers-batch --pairs '[[...]]'` CLI command with
JSON validation, file input support (--file), and --json output.
Previously only existed as MCP tool.
Files: cli/stmem.py
Commit: ebff101

### ✅ Fix stale docstring in zep.py (Jun 25)
The module docstring claimed get_session_message/get_session_messages/
update_message_metadata were missing — they're fully implemented and
tested. Updated docstring to "Full API parity with zep-python v2.0.2".
Files: sdk/python/spacetime_memory/sdks/zep.py
Commit: ebff101

### ✅ Add zep adapter missing features — get/session/message APIs (Jun 25)
All three methods (`get_session_message`, `get_session_messages`,
`update_message_metadata`) are fully implemented in `sdks/zep.py`
and covered by 12+ tests in `test_zep_adapter.py`.
(Already done when research re-checked the codebase.)
Files: sdk/python/spacetime_memory/sdks/zep.py, sdk/python/tests/test_zep_adapter.py

### ✅ Add LangChain memory integration tests (Jun 25)
`test_langchain_adapter.py` exists with 753 lines covering all public
methods of StmemStore, StmemMemoryStore, and StmemChatMessageHistory.
(Already done when research re-checked the codebase.)
Files: sdk/python/tests/test_langchain_adapter.py

### ✅ Add MCP tool for batch store-answers (Jun 25)
New `store_answers_batch` MCP tool accepts a JSON string of
`[[query, answer], ...]` pairs and delegates to `Compounder.store_answers()`.
Includes input validation with clear error messages.
Files: server/mcp/main.py
Commit: 3a8951d

### ✅ Add compounder.update_entity_page() method (Jun 25)
Implemented `Compounder.update_entity_page()` that updates both the KG
node (label, type, summary) and the associated wiki note (title, content)
in a single call. Partial updates supported (None = keep existing).
Includes MCP tool `update_entity_page`, CLI command `stmem update-entity-page`,
5 unit tests. Documentation added to AGENTS.md.
Files: sdk/python/spacetime_memory/compounder.py, server/mcp/main.py,
       cli/stmem.py, tests/test_compounder.py, AGENTS.md
Commit: 3d18628

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
