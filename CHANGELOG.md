# Changelog

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
- **Connector framework** — 7 connector types (RSS, GitHub, Twitter/X, Slack, Discord, Notion, Webhook) + ConnectorRegistry + runner script.
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
