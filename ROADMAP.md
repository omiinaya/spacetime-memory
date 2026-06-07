# Spacetime Memory — Production Roadmap

**Current state:** ~90% to polished drop-in. All features exist, but integration is untested and the Docker build is broken.

**Target:** 99% — verified, deployed, documented.

---

## Q0 — Critical Fixes (breaks on first touch)

| # | Gap | Problem | Fix | Effort |
|---|-----|---------|-----|--------|
| Qa | **Docker build broken** | `COPY server/embedder/model/` fails because model is gitignored. No `.dockerignore` — sends GBs of build context. | Add `.dockerignore`, add model download step to Dockerfile, verify `docker build` passes | 2 hr |
| Qb | **CI has never run** | Workflows exist but are unverified. `wasm32-unknown-unknown` target may fail. pytest paths may be wrong. | Trigger CI on a branch, fix failures until green | 2 hr |
| Qc | **sdk/python/stmem.py duplicate CLI** | Test artifact CLI confuses `cli/stmem.py` (real) vs `sdk/python/stmem.py` (test). Both installable. | Remove the test CLI stub, point tests to the real CLI | 30 min |

## Q1 — Untested Code (works in theory, not in practice)

| # | Gap | Problem | Fix | Effort |
|---|-----|---------|-----|--------|
| 1a | **AgentOrchestrator untested** | 503-line brand-new class. 2 `except: pass` blocks. CoT tracking, tool calls, context assembly never exercised. | Add tests for all 5 public methods. Fix error swallowing. | 1 day |
| 1b | **Spaces have no frontend UI** | Permission table and ACL exist. No way for users to manage space members from the UI. | Add member management UI to Settings page. | 1 day |
| 1c | **`ingest.py` error swallows** | 5 bare `except Exception: pass` blocks. Code ingestion silently fails on every step. | Replace `pass` with `logger.warning()`. Add error stats to return value. | 2 hr |
| 1d | **`get_search_results` placeholder label** | Labeled "(placeholder)" in source. Rename or remove the label. | Remove the `(placeholder)` comment. It's functional. | 5 min |

## Q2 — Integration Testing (prove it works end-to-end)

| # | Gap | Problem | Fix | Effort |
|---|-----|---------|-----|--------|
| 2a | **Zero integration tests** | 126 unit tests, all mocked. Never tested against a real SpacetimeDB. | Write 3 integration tests: (1) store + search, (2) auth + ACL, (3) connector poll → memory | 2 days |
| 2b | **Performance: full-table subscriptions** | Frontend does `SELECT * FROM memory`. Unknown at scale. | Add LIMIT + pagination to table subscriptions. Test at 10K rows. | 1 day |
| 2c | **Docker CI build verified** | Release workflow builds Docker image but Dockerfile is broken. | Fix Dockerfile model issue, run `docker build` in CI | 4 hr |

## Q3 — Production Hardening

| # | Gap | Problem | Fix | Effort |
|---|-----|---------|-----|--------|
| 3a | **No health endpoint** | No way to check if the whole stack is alive. | Add `/health` endpoint to MCP server that checks embedder + DB | 1 hr |
| 3b | **No metrics** | No way to monitor memory counts, errors, latency. | Add basic prometheus-style counters to the SDK | 1 day |
| 3c | **No configuration reference** | All config is env vars in different files. No single source of truth. | Write a CONFIG.md with every env var, default, and description | 1 hr |

---

**Total remaining:** ~8-9 days of focused work.
