# Spacetime Memory — Roadmap

**Goal:** production-grade unified memory backend with *genuine* drop-in adapter parity.
**Last updated:** June 9, 2026 (revised — honest assessment, runtime quality focus)

---

## Current Reality v1.13.0

The adapters have **shape parity** — method names, parameter lists, return types mostly match upstream. But shape ≠ behavior. The runtime quality isn't there yet for production drop-in use.

### Drop-in Readiness

| Adapter | Shape Match | Runtime Quality | Prod Ready? | Blockers |
|---------|:-----------:|:---------------:|:-----------:|----------|
| LangGraph | 100% | ✅ Full `BaseStore` inheritance | **Yes** | None |
| Graphiti | 85% | ⚠️ Best quality of the "rewritten" 5, minor sig diffs | **No** | extra `group_id` in `add_triplet`, `**kwargs` in `search` |
| Zep | 90% | ⚠️ OK, missing async support | **No** | stub `search_sessions`, limited `update_session` |
| Mem0 | 98% | ⚠️ Silent error swallowing in graph API | **No** | `except Exception: pass` in 3 graph methods |
| Hindsight | 95% | ❌ `_run_async()` broken in async envs, silent errors | **No** | bug in sync wrapper, error swallowing |
| Honcho | 85% | ❌ Heavy `except Exception: pass` (6+ sites), tests fail on import | **No** | broken test discovery, silent None/[] returns |

---

## Phase I — Fix Runtime Quality (urgency: immediate)

### Lane 1 — Fix stale test imports
**Time:** 5 minutes
**Why:** Tests can't even be discovered. `test_honcho_adapter.py` imports `User` which doesn't exist post-rewrite.

- [ ] Remove `User` import from honcho test
- [ ] Run test suite, verify discovery works
- [ ] Fix any other import issues

### Lane 2 — Fix `except Exception: pass` everywhere
**Time:** 2 hours
**Why:** Silent swallowing is the #1 production blocker. Multiple adapters return `None`, `[]`, or empty responses instead of propagating errors.

Files to audit:
- `honcho.py` — `Peer.chat()`, `Peer.search()`, `Peer.sessions()`, `Session.add_messages()`, `Session.messages()`, `Honcho.search()` (6+ sites)
- `hindsight.py` — `retain_files()` (swallows on line 366)
- `mem0.py` — `_GraphStore.search()`, `_GraphStore.get_all()`, `search()` method

**Fix pattern:** At minimum log the error. Ideally wrap in typed adapter exceptions.

- [ ] Add `logging` to each module (some don't have it)
- [ ] Replace `except Exception: pass` with `logger.warning()` or re-raise as typed exceptions
- [ ] Files: `sdks/honcho.py`, `sdks/hindsight.py`, `sdks/mem0.py`

### Lane 3 — Fix `_run_async()` in hindsight
**Time:** 30 minutes
**Why:** Crashes in Jupyter, FastAPI, async frameworks. Uses `asyncio.get_event_loop()` which is deprecated and raises in Python 3.12+ when no loop is set. When it does set a new loop, it can trample running loops.

Fix: Use `asyncio.get_running_loop()` detection. If no loop running, create new + run. If loop running, raise clear error or offer native async path.

- [ ] Rewrite `_run_async()` to detect running loop
- [ ] Add runtime check for async context
- [ ] Prefer `asyncio.run()` pattern when safe
- [ ] Add docstring explaining the sync/async split

### Lane 4 — Tag missing releases
**Time:** 5 minutes
**Why:** v1.9.0 through v1.13.0 exist only in commit messages. No tags. Version pinning doesn't work.

- [ ] git tag v1.9.0 (hindsight rewrite commit)
- [ ] git tag v1.10.0 (honcho rewrite)
- [ ] git tag v1.11.0 (zep polish)
- [ ] git tag v1.12.0 (graphiti polish)
- [ ] git tag v1.13.0 (mem0 polish)

**Total Phase I:** ~3 hours

---

## Phase II — Documentation & Verification (urgency: 1 week)

### Lane 5 — Rewrite ADAPTER_COMPAT.md
**Time:** 1 hour
**Why:** Currently documents methods that don't exist anymore (`create_user`, `get_user`, `forget`, `list_all`, `stats`, `reset`, `export_template`, `import_template`). Coverage numbers are wrong.

- [ ] Audit each adapter's actual method list
- [ ] Remove stale entries
- [ ] Update coverage percentages to match compare-results.md
- [ ] Add row for "runtime quality" alongside "method coverage"

### Lane 6 — True behavioral tests (replace comparison harness)
**Time:** 8 hours
**Why:** The comparison harness tests shape (method names, param lists). It doesn't test behavior (write → read → verify, error paths, edge cases). Real drop-in replacement requires behavioral parity.

- [ ] For each adapter: write → read back → verify content matches
- [ ] Test error paths: SpacetimeDB down, invalid inputs, missing IDs
- [ ] Test that exceptions match upstream types (where applicable)
- [ ] Test concurrent access patterns
- [ ] Replace `scripts/comparison-harness.py` with real `pytest` tests

**Total Phase II:** ~9 hours

---

## Phase III — Reliability Infrastructure (urgency: 2 weeks)

### Lane 7 — Client retry + circuit breaker
**Time:** 3 hours
**Why:** The `Client` class has `max_retries=3` but it's a simple counter — no exponential backoff, no jitter, no circuit breaker. SpacetimeDB transient failures cause silent data loss (compounded by Lane 2 issues).

- [ ] Add `httpx.Transport(retries=...)` or manual retry with exponential backoff + jitter
- [ ] Add circuit breaker: if N consecutive failures, stop trying and raise clearly
- [ ] Add connection timeout configuration (currently hardcoded in `__init__`)
- [ ] Add pool limits (httpx defaults to 10 connections, document it)

### Lane 8 — Consistent error contracts
**Time:** 2 hours
**Why:** Each adapter handles errors differently. Some raise `ValueError`, some raise `RuntimeError`, some return `None`, some return `[]`. No documented contract for what happens when SpacetimeDB fails.

- [ ] Define per-adapter error contract (what exceptions, when)
- [ ] All "not found" cases raise `NotFoundError` (or equivalent)
- [ ] All "SpacetimeDB unavailable" cases raise `ApiError` (or equivalent)
- [ ] No silent `None`/`[]`/empty returns on real errors
- [ ] Document contracts in each adapter's module docstring

### Lane 9 — CI pipeline
**Time:** 4 hours
**Why:** Zero CI. No automated test runs, no linting, no type checking.

- [ ] GitHub Actions workflow: build Rust module
- [ ] Start SpacetimeDB standalone
- [ ] Run pytest suite
- [ ] Run comparison harness
- [ ] Run type checker (pyright/mypy) on adapters
- [ ] Lint check (ruff)

**Total Phase III:** ~9 hours

---

## Phase IV — Advanced Gaps

| Item | Effort | Notes |
|------|--------|-------|
| Hindsight async variants actually work (not wrappers around sync) | 2h | `aretain`, `arecall`, `areflect` currently use `_run_async()` too? Check |
| Honcho `.aio` async accessor | 3h | Upstream has `.aio.peer()`, `.aio.search()` |
| Zep async support (real Zep has async endpoints) | 3h | Currently sync-only for methods that are async upstream |
| Graphiti LLM extraction in `add_episode` | 4h | Real Graphiti extracts entities from raw text |
| Mem0 `create_memory_tool()` for LangChain | 1h | Real mem0 has this |
| PyPI publishing | 2h | User deferred |

---

## Effort Summary

| Phase | Focus | Effort | Ship |
|-------|-------|--------|------|
| I | Runtime quality | 3 hours | 1 day |
| II | Docs & verification | 9 hours | 1 week |
| III | Reliability infra | 9 hours | 2 weeks |
| IV | Advanced gaps | 15 hours | ongoing |

**To actually call these production drop-in replacements: ~21 hours of real work.**
Phase I alone (3h) removes the blockers that make them *dangerous* to use today.

---

## Priority Order

1. **Lane 1** — fix test discovery (5min, unblocks everything else)
2. **Lane 2** — fix error swallowing (2h, #1 prod blocker)
3. **Lane 3** — fix `_run_async()` (30min, real bug)
4. **Lane 4** — tag releases (5min, version sanity)
5. **Lane 5** — fix ADAPTER_COMPAT.md (1h, docs truth)
6. **Lane 6** — behavioral tests (8h, verification)
7. **Lane 7** — client retry (3h, reliability)
8. **Lane 8** — error contracts (2h, consistency)
9. **Lane 9** — CI pipeline (4h, automation)
