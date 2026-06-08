# Changelog

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

Inspired by: Mem0, Hindsight (Vectorize), Honcho, Graphify, Understand Anything, Supermemory, CLI-Anything, OpenViking, RetainDB, Holographic, ByteRover, Litellm, and Orgy.
