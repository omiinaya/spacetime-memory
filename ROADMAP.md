# Spacetime Memory — Gap Closure Roadmap v3

Current state: **~86% parity** across all 13 inspiration projects.
Target: **95%+** — fully functional drop-in for every claimed feature.

## Session 2 completed (Jun 6)

| # | Gap | Project | Fix |
|---|-----|---------|-----|
| P1a | Directory recursive traversal | OpenViking | `get_children`, `traverse_recursive` Rust reducers + `DirectoryMemoryLink` table |
| P1b | CLI `memory list --tier`, `memory update`, `directory` commands | CLI-Anything | `--tier L2`, `--directory`, `--recursive` flags; `memory update`, `memory history`, `memory batch-update` |
| P1c | Connectors: Twitter/X, GitHub, Webhook | Supermemory | `TwitterConnector`, `GitHubConnector`, `WebhookConnector` classes + `ConnectorRegistry` |
| P1d | Browser extension | Supermemory | Chrome MV3 extension: popup, context menu, keyboard shortcut, notification |
| P2a | Holographic reputation decay | Holographic | `apply_reputation_decay` + `manual_decay` reducers + `WorkspaceConfig` table |
| P2b | Code Explorer frontend page | Understand Anything | Tree view, node details, edge connections, search for `node_type='code'` KG nodes |
| P2c | TrajectoryViz frontend page | OpenViking | Tiered layout (L0/L1/L2), SVG trajectory lines, stats bar, filter bar |
| P2d | SDK: batch_update, get_history, metadata/location filters | Mem0, Honcho | `batch_update_memories`, `get_memory_history`, `search_with_filters` |
| P2e | MCP directory tools | Supermemory | `create_directory`, `traverse_directory`, `list_directory` MCP tools |

## Current scores

| Project | Before | After | Gap items closed |
|---------|--------|-------|-----------------|
| Mem0 | 90% | **93%** | `get_history()`, `batch_update()` SDK methods |
| Hindsight | 85% | **88%** | Connectors enrich data pipeline |
| Honcho | 85% | **90%** | Metadata/location search filters |
| Graphify | 85% | **85%** | — |
| Understand Anything | 75% | **88%** | Code Explorer UI (tree + graph + search) |
| RetainDB | 85% | **88%** | Directory-backed tiered retrieval |
| Holographic | 70% | **85%** | `apply_reputation_decay` time-weighted decay |
| OpenViking | 65% | **80%** | Directory traversal (`traverse_recursive`) + TrajectoryViz UI |
| Supermemory | 75% | **88%** | Browser extension + Twitter/GitHub/Webhook connectors |
| CLI-Anything | 80% | **88%** | `memory list --tier`, `memory update`, `directory` commands |

## Remaining gaps (<95% target)

### P2 — Still open

| Gap | Project | Effort | Fix |
|-----|---------|--------|-----|
| Cross-memory merge UI | OpenViking | ~200 LOC | Frontend page showing merge candidates + confirm merge button |
| S3/File backup system | RetainDB | ~300 LOC | Backup script + restore reducer |
| Plugin system architecture | Supermemory | ~400 LOC | Plugin loader in Python SDK + registry |
| Syncing/replication | Holographic | ~500 LOC | P2P sync between SpacetimeDB instances |
