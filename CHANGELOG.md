# Changelog

## 2026-07-27 — Full Table Scan Elimination

- **Full scans reduced 73→22 (-70%) across 4 optimization sessions**: 51 full-table `.iter()` calls converted to indexed lookups or workspace-filtered scans.
- **28 btree indexes added** across 23 table structs — no schema migrations.
- **workspace_id migration**: Added to 5 tables (MemoryTag, NoteBacklink, CitationResult, EntityTermIndex, NodeEdgeIndex) enabling workspace-scoped indexed filtering.
- **Index usage correction**: 9 existing indexes were being bypassed by `.iter()`. Fixed across context_directory, memory, graph_traversal, consolidation, knowledge_graph, context_delta, entity_extraction.
- **Reducer API**: `tag_memory` and `batch_tag_memories` now require `workspace_id` parameter.
- **Internal API**: `register_entity_term` and `register_node_edge` now require `workspace_id` parameter.
- **ITER_AUDIT.md**: Complete audit document updated with per-file classifications.
- **Rust build**: Zero clippy warnings, cargo check clean.
- **Python tests**: 395 unit tests passing, 13 skipped, 0 regressions from Rust changes.
- **TypeScript tests**: 221 tests across 6 files, all passing.
- **CI**: Python matrix reduced to [3.11] (3.12 unavailable on runner), dtolnay/rust-toolchain for WASM, cargo-deny with `--force`.

## 2026-07-28 — Veracity Tiers (Bayesian Confidence) + Anomaly Detection

### New
- **Veracity Tiers**: Full Bayesian confidence scoring system with Beta(α, β) posterior. 5 tiers (SPECULATIVE→LOW→MEDIUM→HIGH→CERTAIN) with tier thresholds based on both confidence score and total evidence count. Initial Beta(1,1) uniform prior, auto-compounding on every search hit (α +0.05), explicit positive/negative feedback support.
- **VeracityEvidence table**: Stores per-memory alpha, beta, evidence count, contradictory/confirmatory counts.
- **Reducers**: `update_memory_veracity`, `batch_update_veracity`, `get_memory_veracity`, `list_workspace_veracity`.
- **Anomaly Detection**: Statistical z-score outlier detection across 3 metrics (confidence, content length, entity count). Identifies memories >3σ from workspace mean. `anomaly_result` table + `detect_anomalies` reducer.
- **Frontend Veracity Badge**: Color-coded tier badge (emerald/blue/yellow/orange/gray) in search result cards. Fetched via SQL JOIN from memory table.
- **Python SDK**: `update_memory_veracity()`, `batch_update_veracity()`, `get_memory_veracity()`, `list_workspace_veracity()`, `detect_anomalies()` methods on Client.
- **Query Cache**: `hybrid_search` now supports `compound` parameter to auto-boost veracity on search hits.
- **23 new Rust tests** (veracity module: Bayesian math, tier progression, edge cases) + **5 new tests** (anomaly detection: mean/std computation).

### Changed
- `insert_memory` now automatically initializes VeracityEvidence with Beta(1,1) prior.
- `hybrid_search` now accepts `compound` parameter (defaults to compound on search hits).
- All TypeScript and Python callers updated to pass `compound` parameter.
- README updated with Veracity Tiers, Anomaly Detection, and Query Cache documentation.
- Mnemosyne parity score revised from ~55-60% → ~70-75%.

## 2026-07-21 — Polish & Refactoring Pass

- **Modular imports wired up**: client/, compounder/ packages now active; monoliths renamed to _legacy
- **client.ts split**: 4,643→729 lines barrel, 15 domain modules in src/
- **_memories_search.py split**: Search helpers and session search extracted
- **25 new typed Python SDK wrappers**: Full coverage for community, ripple, peer, session, notes, documents, directory, admin, subscriptions, search profiles
- **36 new Python tests**: tests/test_sdk_wrappers.py covers all new wrappers
- **Rust clippy: zero warnings**: 14 issues fixed, 15 too_many_arguments allowed at crate level
- **P2 table privacy**: entity_search_index, entity_term_index, node_edge_index, workspace_index made private
- **hybrid_result btree index**: (workspace_id, query_hash) composite index eliminates linear scan
- **CI runs on dev branch**: ci.yml and docs.yml now trigger on dev pushes and PRs
- **TS type quality**: Promise<any> → typed signatures across all 15 src/ modules

## 0.6.0 (unreleased)

### Bug Fixes & Polish (July 21, 2026)

- **Python test suite rescued** (P1-1) — 14 collection errors eliminated (lazy imports in `connectors/__init__.py`), 7 assertion fixes (stale `127.0.0.1` → `127.0.0.1`, OTel deps), 5 hanging tests fixed (circuit breaker `max_retries=0`). `_call_with_result()` implemented — `test_base.py` 71/71 green.
- **`delete_workspace` cascade** (P1-5) — `cascade_ws!` macro now invoked on workspace deletion. 33 tables (memory, peer, session, document, note, kg_node, kg_edge, term_index, +25 more) no longer orphaned.
- **TS client SQL injection fixed** (P1-4) — 29 ORDER BY/LIKE violations converted to `_sqlExec` with parameterized queries + client-side sort/filter. 3 critical raw `_sql()` calls with interpolated user input fixed. `tsc` zero errors. 220/221 tests passing.
- **Table privacy audit** (P1-3) — All 107 STDB tables categorized. 7 P0 critical tables identified (decrypted_memory_result, hybrid_result, entity_extraction_result, etc.). Report saved to `STDB_TABLE_PRIVACY_REVIEW.md`.
- **Rust warnings eliminated** (P3-8) — 16 compiler warnings fixed. Clean build.
- **Admin force-deactivate** (P3-11) — `admin_deactivate_account` reducer added (admin can deactivate any account, self-protection enforced).
- **Single `delete_memory` reducer** (P3-11) — API symmetry with batch version.
- **Python Zep `add_triplet`** (P2-7) — Ported from TS implementation. 17/17 zep_graph tests pass.
- **TS ripple-stale wrappers** (P2-6) — `detectRippleEffects`, `applyRippleUpdates`, `markStaleForSource`, `clearStaleFlag` enhanced with full Python parity.
- **Observability alerting** (P3-10) — Health watchdog now sends Discord webhook notifications (via `DISCORD_WEBHOOK_URL` env var) on CRITICAL and RECOVERY events for embedder and Tantivy sidecars.

## 0.5.0 (unreleased)

### ACL Model — Admin Bypass & Management

- **Admin identity bypass** — `check_space_access()` now grants implicit owner
  access to all workspaces for admin accounts. Removes the need for explicit
  permission grants per workspace.
- **Admin management reducers** — `promote_admin()`, `demote_admin()`,
  `set_initial_admin()`, `list_admins()` with full validation (last-admin
  protection, self-demote prevention, duplicate detection).
- **Permission-gated workspace CRUD** — `update_workspace()` and
  `delete_workspace()` now require owner access. `grant_space_access()` and
  `revoke_space_access()` now also accept admins as grantors. Deleting a
  workspace cleans up associated `space_permission` records.
- **`stmem admin` CLI** — `promote`, `demote`, `init`, `list` subcommands.
- **7 integration tests** — admin bypass, grant/revoke, promote/demote,
  list, update/delete, user delete restrictions.

### Backup & Restore

- **5 integration tests** — backup structure, roundtrip with data, default
  output path, invalid path handling, partial table restore.

### Observability

- **`request_id`** — 8-hex-char unique identifier on every `Client` instance.
- **Structured JSON logging** — `JSONFormatter` class and `configure_logging()`
  helper for newline-delimited JSON or plain-text output to stderr or file.
- **Prometheus metrics export** — `MetricsCollector.prometheus_text()` method
  and `stmem metrics prometheus` CLI command exposing endpoint call counts,
  latency, error rates, memory item counts, and embedder errors in Prometheus
  exposition format.
- **Identity token auto-capture** — `Client` now captures the
  `spacetime-identity-token` from the server on first anonymous call and
  reuses it, ensuring consistent identity across requests without a JWT.
- **10 unit tests** — JSONFormatter, Client request_id, Prometheus text
  format edge cases, logging configuration.

## 0.4.0 (unreleased)

### Drop-in Adapters

- **Graphiti-compatible adapter** — `spacetime_memory.sdks.graphiti.Graphiti`
  — `add_triplet()`, `add_episode()`, `search()`, `search_()`,
  `get_entity_edge_summary()`, `remove_episode()`, `build_communities()`.
  Maps Graphiti's entity-node/entity-edge API onto StmDB's knowledge graph
  (kg_node/kg_edge tables) with label-based dedup. 15 integration tests.

- **LangChain/LangGraph BaseStore adapter** — `spacetime_memory.sdks.langchain`
  — `StmemStore` implements LangGraph's `BaseStore` (get/put/delete/search/
  list_namespaces/batch) with namespace→workspace mapping and hybrid search.
  `StmemMemoryStore` implements LangChain's `BaseStore` (mget/mset/mdelete/
  yield_keys). 17 integration tests. Optional `[langchain]` extras.

- **Zep-compatible adapter** — `spacetime_memory.sdks.zep.Zep`
  — Session-based memory API: `add()`, `get()`, `delete()`, session CRUD,
  search, messages, facts. 18 integration tests.

### SDK & Packaging

- **PyPI packaging** — setup.py version bumped to 0.4.0. Added `[langchain]`
  and `[all]` extras for optional LangChain/LangGraph dependencies.
- **All 4 planned adapters shipped** — Mem0 (existing), Graphiti, LangChain,
  Zep. Full drop-in coverage of the most-used memory library APIs.

## 0.2.0 (unreleased)

### Features

- **Memory tier escalation** — automatic promotion/demotion between L0 (critical), L1 (normal), and L2 (archival) tiers based on access patterns and relevance scores.
- **Knowledge graph** — PageRank, Leiden community detection, shortest-path traversal, node/edge CRUD with confidence tagging.
- **Agent orchestrator** — session-aware agent state management, CoT/tool-call/context step tracking, session sharing and collaborative context.
- **Plugin system** — PluginManager with load/discover/unload workflow, sandbox support (restrict_network/filesystem/imports), and hookpoints for lifecycle events.
- **Bi-directional replication** — push+pull daemon with conflict resolution, peer-level sync of memory entries.
- **Connector framework** — 9 connector types (RSS, GitHub, Twitter/X, Slack, Discord, Notion, Webhook, Telegram, Orgmode) + ConnectorRegistry + runner script.
- **Org-mode sync** — live bidirectional sync between Org-mode files and Spacetime Memory notes, with conflict detection.
- **ACL & spaces** — PBKDF2-HMAC-SHA256 auth, `require_auth` guard on all write reducers, ACL enforcement via `check_space_access("editor")`, workspace + space permission model.
- **Backup & restore** — Rust-native backup/restore reducers, cron-integrated backup script.
- **Feedback system** — 1–5 graded ratings + binary helpful/unhelpful, feedback-driven memory reinforcement.
- **MCP server** — Model Context Protocol tools for AI agents: store, search, get, list, graph query, profile, facts, sessions, with optional API key auth.
- **Hermes plugin** — native Hermes Agent skill, cron memory consolidation/decay, structured knowledge lookup.
- **Frontend (23 pages)** — Dashboard, Memory Browser, Search, Knowledge Graph, GraphViz (D3 force-directed), Block Graph, Trust Dashboard, Sessions, Session Reasoning, Smart Query, Merge Candidates, Code Explorer, Trajectory Viz, Directory Browser, Daily Notes, Notes, Notes Graph, Tours, Auth, Settings, Peers, Documents, Knowledge Graph viewer.

### Infrastructure

- **Multi-stage Docker build** — embedder + WASM module + frontend + runtime in a single image, with `docker-compose.yml` for one-command startup.
- **CI pipeline** — GitHub Actions: `cargo check` (Rust), `pytest` (Python unit tests), `tsc && vite build` (frontend).
- **Release pipeline** — GitHub Actions: tags trigger Docker build + push and PyPI publish.
- **CONFIG.md** — full environment variable reference (17 vars documented).
- **.dockerignore** — build context excludes node_modules, target, venv, .onnx.

### SDK

- **Python SDK** (`spacetime-memory` on PyPI) — Client for SpacetimeDB operations, memory CRUD, semantic/keyword search, embeddings, graph queries, session management, profile/facts, and directory tree navigation.
- **CLI** (`stmem`) — 17 command groups via Click + Rich: workspace/space/peer/memory/directory/profile/facts/graph/notes/sessions/ingest/knowledge/codex/explorer/summarize/backup/feedback.
- **Drop-in SDK adapters** — Mem0, Hindsight, and Honcho API-compatible adapters.
- **CLI output modes** — `--output json|csv|table`, `--quiet`, `--no-header`, `--compact-json`, `--verbose`, `--watch`.

### Acknowledgments

Drop-in adapter targets: Mem0, Hindsight (Vectorize), Honcho, LangGraph, Zep, Graphiti.
Concept inspiration: Graphify, Understand Anything, Supermemory, CLI-Anything, OpenViking, RetainDB, Holographic, ByteRover, LiteLLM, Orgy.
