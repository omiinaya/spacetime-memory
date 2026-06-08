# Spacetime Memory — Production Roadmap

**Current state:** v0.6.0. 181 tests passing. All core CRUD works against real SpacetimeDB. ACL with anonymous bypass + JWT support. Hermes Agent plugin functional but untested e2e.

**Target:** Verified, deployed, Hermes-integrated memory backend.

---

## Current Reality — June 8, 2026

| Area | Verdict | Reality |
|---|---|---|
| **STDB module** | ✅ Solid | 27 source files, 138 public reducers, 0 `todo!()` macros. No dead code flags. |
| **Tests** | ✅ 181 passing | 74 unit + 21 integration + adapter suites. Mock-based, runs in CI. |
| **Frontend** | 🟡 21/23 pages real | 21 pages fetch live data. 11 pages still have hardcoded arrays mixed in (BlockGraph, SmartQuery, GraphViz, TrajectoryViz worst). Dashboard is empty shell. |
| **Adapters** | 🟡 4 built, source scattered | Mem0 adapter at `sdk/adapters/mem0/`. LangChain, Graphiti, Zep adapter source files missing from `sdk/adapters/` — tests exist at `sdk/python/tests/` but source location unclear. |
| **Hermes plugin** | 🟡 Fixed but untested | 703 lines, 32 methods, 5 tools (`spacetime_search`, `spacetime_store`, `spacetime_notes`, `spacetime_kg`, `spacetime_profile`). `is_available()` fixed. Never tested e2e against running STDB. |
| **Docker** | 🟡 Untested | Dockerfile + compose exist, never verified. Multi-stage build (embedder + module + frontend). JWT key generation at build time. `.dockerignore` fixed. |
| **Embedder** | ✅ Working | ONNX all-MiniLM-L6-v2 (384d). Health check at :9090/health. Error logging added. Model downloaded at Docker build time. |
| **Python SDK** | ✅ Solid | Retry with backoff, JWT auth, structured logging. Full CRUD for all table types. LIKE workaround (client-side filter). |
| **ACL** | ✅ Functional | Anonymous bypass for unauthenticated peers. JWT-based identity for authenticated. `create_workspace` auto-grants owner. Graceful permission model. |
| **Replication** | ✅ Built | Cross-instance sync: `ReplicationPeer` table, mutation log, Python daemon. CLI commands. |
| **Backup/Restore** | ✅ Built | `export_backup` + `restore_backup` reducers. CLI: `export <ws> [--output]`, `import <ws> <file>`. Cron wrapper for auto-cleanup. |
| **Connectors** | ✅ Built | Plugin-style framework: `RssFeedConnector`, `GitHubConnector`, `TwitterConnector`, `WebhookConnector`. `ConnectorRegistry` with polling. |
| **Plugin system** | ✅ Built | `PluginManager` with lifecycle hooks, discovery, dependency auto-install. CLI: `stmem plugin list|load|unload|reload`. |

---

## Prioritized Next Steps

### Q0 — Wire What's Already Built (1-2 hours)

| # | Task | Problem | Effort |
|---|------|---------|--------|
| Q0a | **Hermes plugin e2e validation** | Plugin is "fixed" but never tested against live STDB. Fire all 5 tools, verify round-trips. | 30 min |
| Q0b | **Locate adapter source files** | LangChain/Graphiti/Zep tests reference adapter classes. Sources not in `sdk/adapters/`. Find and consolidate. | 20 min |
| Q0c | **Dashboard → live data** | Dashboard.tsx has 0 fetches. Wire to tables that already exist: workspace count, peer count, memory count, session count. | 30 min |

### Q1 — Frontend Polish (1-2 days)

| # | Task | Problem | Effort |
|---|------|---------|--------|
| 1a | **Hardcoded data scrub** | 11 pages mix real fetches with hardcoded arrays. Replace with `useTable` subscriptions or fetches. Priority: BlockGraph (6), SmartQuery (5), GraphViz (4), TrajectoryViz (4). | 4 hr |
| 1b | **Observability dashboard** | No way to see memory stats. Add: total memories, embeddings, searches/day, kg nodes/edges, session count. Tables already exist. | 2 hr |
| 1c | **Spaces/ACL UI** | Permission table exists. No UI to manage workspace members. Add member management to Settings. | 3 hr |

### Q2 — Integration & Deployment (2-3 days)

| # | Task | Problem | Effort |
|---|------|---------|--------|
| 2a | **Docker build verification** | Dockerfile + compose exist, never built. Verify `docker compose up --build` works, passes smoke test. | 2 hr |
| 2b | **Integration tests against real STDB** | 181 tests are all mocked. Add 5 E2E tests: store+search, auth+ACL, connector→memory, plugin→STDB, backup→restore. | 1 day |
| 2c | **CI Docker job** | Add Docker build + smoke test to CI. Catches regressions. | 1 hr |

### Q3 — Hermes Deep Integration (1 week)

| # | Task | Problem | Effort |
|---|------|---------|--------|
| 3a | **Plugin sync_turn verification** | `sync_turn()` stores conversation turns as memories. Verify with real Hermes session. Check content, metadata, timestamps. | 2 hr |
| 3b | **Plugin prefetch → context injection** | `prefetch()` searches for relevant memories before each LLM call. Verify results appear in system prompt. | 2 hr |
| 3c | **Multi-workspace isolation** | Hermes uses per-session workspaces. Verify different sessions don't leak memories. | 2 hr |
| 3d | **Cron consolidation integration** | The `consolidate.py` cron script (30m interval) should run against the same STDB Hermes uses. Wire and verify. | 2 hr |

---

## Effort Summary

| Phase | Wall Time | Delivers |
|-------|-----------|----------|
| **Q0 — Wire** | 1-2 hr | Hermes plugin verified, adapters located, dashboard lit |
| **Q1 — Polish** | 1-2 days | No hardcoded data, observability dashboard, ACL UI |
| **Q2 — Deployment** | 2-3 days | Docker verified, E2E tests, CI Docker job |
| **Q3 — Hermes** | 1 week | Full memory lifecycle verified in Hermes Agent |

---

*Last updated: June 8, 2026. Replaces ROADMAP-PRODUCTION.md (now superseded).*
