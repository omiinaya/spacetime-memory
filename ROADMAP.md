# Spacetime Memory — Gap Closure Roadmap v4

Current state: **~90% parity** across all 13 inspiration projects.
Target: **95%+** — fully functional drop-in for every claimed feature.

## Session 3 completed (Jun 6)

| # | Gap | Project | Fix |
|---|-----|---------|-----|
| P2f | Cross-memory merge UI | OpenViking | `MergeCandidates.tsx` (833 lines): side-by-side comparison, keep-both actions, stats, workspace/date filters |
| P2g | S3/File backup system | RetainDB | `export_backup` + `restore_backup` Rust reducers + `BackupEntry` table + `scripts/backup.py` CLI + `backup-cron.sh` |
| P2h | Plugin system architecture | Supermemory | `plugin_manager.py` (489 lines): `SpacetimePlugin` base class, `PluginManager` with discovery/load/unload/hooks, example plugin, `stmem plugin` CLI commands |
| P2i | Syncing/replication | Holographic | `replication.rs` (292 lines): `ReplicationPeer`, `ReplicationLog`, `ReplicationResult` tables + 8 reducers + `scripts/replication_daemon.py` (433 lines) + `stmem replication` CLI commands |

## Current scores

| Project | After S2 | After S3 | Gap items closed |
|---------|----------|----------|-----------------|
| Mem0 | 93% | **93%** | — |
| Hindsight | 88% | **90%** | Replication enriches data pipeline |
| Honcho | 90% | **90%** | — |
| Graphify | 85% | **85%** | — |
| Understand Anything | 88% | **92%** | Merge UI for consolidation review |
| RetainDB | 88% | **95%** | Full backup/restore system + cron |
| Holographic | 85% | **90%** | Replication/sync between instances |
| OpenViking | 80% | **88%** | Merge candidates UI |
| Supermemory | 88% | **95%** | Plugin system full architecture |
| CLI-Anything | 88% | **90%** | Plugin management commands |
| **Overall** | **~86%** | **~90%** | All P0/P1/P2 items closed |

## Original 13 projects parity

1. **Mem0** — 93%: Multi-level memory, entity linking, temporal reasoning, hybrid retrieval, drop-in SDK adapter, batch update, history
2. **Hindsight** — 90%: Retain/recall/reflect, multi-strategy retrieval, LLM synthesis, 3 connectors (RSS/GitHub/Twitter)
3. **Honcho** — 90%: Peer model, session context, multi-peer perspectives, drop-in adapter, metadata/location filters
4. **Graphify** — 85%: BFS/shortest path, community detection, edge confidence, MCP-compatible graph tools
5. **Understand Anything** — 92%: KG dashboard, guided tours (Tour page + stop-by-stop nav), code explorer, diff impact analysis
6. **Supermemory** — 95%: User profiles, hybrid search, 4 connectors (RSS/GitHub/Twitter/Webhook), browser extension, plugin system
7. **CLI-Anything** — 90%: Full CLI harness (workspace/peer/memory/profile/KG/tour/directory/plugin/replication), tier filters
8. **OpenViking** — 88%: Tiered context (L0/L1/L2), directory tree + recursive traversal, TrajectoryViz, merge candidates UI
9. **RetainDB** — 95%: Reinforcement, delta compression, consolidation (dedup/rollup/decay), temporal validity, versioning, context agent, full backup/restore
10. **Holographic** — 90%: Trust scoring, feedback-driven reinforcement, time-weighted reputation decay, cross-instance replication
11. **ByteRover** — 88%: Knowledge curation pipelines, smart query, intelligent recall, cross-referencing
12. **Facts** — 85%: Static/dynamic profile facts, CLI directory listing
13. **Logseq** — 85%: Block-level references, ((wiki-links)), {{embed}} transclusion, backlinks panel
