# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Status: PENDING

### Add zep adapter missing features — get/session/message APIs
The Zep adapter (`sdks/zep.py`) explicitly documents missing features:
`get_session_message()`, `get_session_messages()`, `update_message_metadata()`.
Implement these to reach full Zep API parity.
Difficulty: Medium
Est: 1-2h

### Add LangChain memory integration tests
The `sdks/langchain.py` adapter exists but has no dedicated test file.
Add `test_langchain_adapter.py` with unit tests for all public methods
to match the coverage level of the mem0/zep adapters.
Difficulty: Easy
Est: 30min

---

## Recently Completed

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
