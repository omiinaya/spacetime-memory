# Spacetime Memory — Polished Drop-in Roadmap

**Current state:** Functional prototype with broad coverage (~87% real, ~0% shippable).
**Target:** Polished, tested, deployable drop-in for all 13 projects.

---

## P0 — Ship Blockers (must fix before anyone else can run this)

| # | Gap | Why it's a blocker | Effort |
|---|-----|--------------------|--------|
| 0a | **Test suite: zero tests** | Cannot merge PRs, cannot refactor, cannot prove anything works. Single biggest signal this is a prototype. | 3-5 days |
| 0b | **Docker / one-command startup** | Requires SpacetimeDB CLI + Rust toolchain + Node + Python + embedder binary. 5 separate runtimes. No one will try this. | 1-2 days |
| 0c | **Embedder silent failure** | `_embed()` catches all exceptions and returns `[]`. Semantic search silently returns empty results when the sidecar is down. The error is eaten. Users get blank pages with no indication anything is wrong. | 2 hours |
| 0d | **CI/CD pipeline** | No build verification, no lint, no test run. Code compiles locally today; breaks tomorrow. | 1 day |

**Total P0:** ~6-9 days

---

## P1 — Reliability (makes it actually work for real use)

| # | Gap | Current behavior | Target | Effort |
|---|-----|------------------|--------|--------|
| 1a | **Block parsing not automatic** | Must call `parse_note_blocks` manually after saving a note. Blocks are stale until explicitly re-parsed. | Auto-parse on `update_note`, with `parse_note_blocks_inner` called at the end of the reducer. | 1 day |
| 1b | **Feedback: binary only** | `rate_memory` accepts only "helpful" or "unhelpful". No graded trust scoring. | Add 1-5 scale. Convert existing binary ratings to 1 or 5. Use weighted Bayesian average for trust scores instead of multiplication. | 1 day |
| 1c | **Decay requires manual trigger** | `apply_reputation_decay` and `manual_decay` won't run unless explicitly called. No cron registration. | Register decay in the consolidation cron (alongside dedup/rollup). | 4 hours |
| 1d | **SDK adapter API audit** | Adapters cover main methods but break on exotic kwargs. Parameter names differ from originals. Return type mismatches. | Run the actual Mem0/Hindsight/Honcho Python SDK test suites against our adapters. Fix every mismatch. | 2-3 days |
| 1e | **Replication: push-only** | Daemon pushes local mutations to remotes. No pull, no conflict resolution. | Add `pull_from_peer` reducer + daemon mode. Add last-write-wins conflict resolution. Add bi-directional sync mode. | 2 days |
| 1f | **Tier escalation thresholds hardcoded** | L2→L1 at 5 accesses, L1→L0 at 20. Not configurable. | Move thresholds to `WorkspaceConfig` table. Add `--l2-to-l1` and `--l1-to-l0` params to `escalate_memories`. | 4 hours |

**Total P1:** ~7-9 days

---

## P2 — Polish (makes it not look like a prototype)

| # | Gap | Current state | Target | Effort |
|---|-----|---------------|--------|--------|
| 2a | **Thin frontend pages** | Peers.tsx (82 lines), Sessions.tsx (90 lines), Documents.tsx (80 lines) — bare table views with no detail panels, no actions, no loading states. | Full pages matching the quality of NoteEditor/SessionReasoning: detail views, inline actions, create forms, loading/empty/error states. | 1-2 days |
| 2b | **Loading/error/empty state audit** | Some pages have skeletons, some don't. Error states are inconsistent. Empty states are hit-or-miss. | Audit all 23 pages. Every page must have: loading skeleton, error card with retry, empty state with CTA. | 1 day |
| 2c | **Plugin security sandbox** | Plugins run with full Python runtime access. No restrictions. | Use `importlib` + restricted Python execution. Block filesystem write access, network access, subprocess calls by default. Opt-in via manifest. | 2 days |
| 2d | **Embedder model fallback** | Only all-MiniLM-L6-v2 (384d). No option for other models. | Add configurable model path. Support `text-embedding-ada-002` via OpenAI API as fallback when ONNX model isn't available. | 1 day |
| 2e | **CLI: missing polish flags** | No `--quiet`, no `--no-header` for CSV, no `--compact-json`. | Add CLI UX flags. Consistent formatting across all commands. | 4 hours |
| 2f | **Error messages: cryptic** | SQL errors pass through raw: `SQL error (HTTP 400): ...`. Reducer errors are opaque. Human-readable error messages in most places are an afterthought. | Map common SQL errors to human messages. Add `display_name` and `hint` fields to error responses. Add `--verbose` flag for raw errors. | 1 day |
| 2g | **MCP server: no auth** | All MCP tools are unauthenticated. Anyone who can reach the port can read/write all data. | Add optional API key check. Read from env var `MCP_API_KEY`. | 4 hours |

**Total P2:** ~6-8 days

---

## P3 — Deep Parity (real feature gaps left unaddressed)

| # | Gap | Project | Why it matters | Effort |
|---|------|---------|----------------|--------|
| 3a | **PageRank / eigenvector centrality** | Graphify | God nodes = degree centrality (count of edges). No PageRank or eigenvector centrality for actual importance ranking. | 2 days |
| 3b | **Mem0: user-level isolation** | Mem0 | Our isolation is workspace-based. Mem0 isolates by user_id + agent_id. Cross-user data leaks in shared workspaces. | 1 day |
| 3c | **Automatic merge suggestion** | OpenViking | Merge candidates exist but no auto-suggestion — user must browse and decide. Dedup suggests nothing. | 2 days |
| 3d | **Org-mode live sync** | Logseq | Org-mode parser is a one-shot file reader. No file watcher, no bidirectional sync, no journal integration. | 2-3 days |
| 3e | **Hierarchical community dendrogram** | Graphify | Community detection is flat label propagation. No hierarchy, no sub-communities, no zoom-in/zoom-out. | 2 days |
| 3f | **Supermemory: spaces** | Supermemory | Our workspaces ≈ Supermemory spaces, but spaces have sharing/collaboration features we don't. | 2-3 days |
| 3g | **Agent orchestration hooks** | Honcho | Honcho's "reasoning-first memory" is an agent framework. We have the data model but no agent loop, no chain-of-thought tracking, no tool-use memory integration. | 4-5 days |
| 3h | **Collaboration / multi-user** | Supermemory | Single-user (even with auth). No shared workspaces, no real-time collaboration, no permission model per-peer. | 3-5 days |

**Total P3:** ~17-22 days

---

## Summary

| Phase | Focus | Effort | Impact |
|-------|-------|--------|--------|
| P0 | Ship blockers (tests, Docker, CI) | 6-9 days | Prototype → shippable |
| P1 | Reliability (auto parse, graded feedback, decay, adapter audit, bi-directional sync) | 7-9 days | Works for real use |
| P2 | Polish (frontend, errors, plugin sandbox, embedder fallback) | 6-8 days | Doesn't look like a prototype |
| P3 | Deep parity (PageRank, user isolation, merge suggestion, live sync) | 17-22 days | 95%+ true parity |

**Total to polished drop-in:** ~36-48 days of focused work.

**Where to start:** P0a (tests). Nothing else matters if you can't prove the code works.
