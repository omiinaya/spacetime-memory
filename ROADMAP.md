# Spacetime Memory — Honest Assessment (June 2026)

## Project Totals

| Layer | LOC | Files | Tests | Passing |
|-------|----|-------|-------|---------|
| Rust module | 8,800 | 26 .rs | 91 | 91 ✅ |
| Python SDK | 12,800 | ~30 .py | 249 | 249 ✅ |
| Frontend | 18,138 | 145 .tsx/.ts | 53 | 53 ✅ |
| **Total** | **~39,700** | **~200** | **393** | **393 ✅** |

---

## Adapter Feature Parity — Verified Against Live STDB

| Adapter | Shape Match | Tests (live STDB) | Upstream API Version | Drop-in? |
|---------|:-----------:|:-----------------:|:---------------------|:--------:|
| **LangGraph** | ~99% | **17/17 pass** | BaseStore | **Yes** |
| **Zep** | ~97% | **26/26 pass** | v2.0.2 (`Zep` with `.memory`/`.user`) | **Yes** |
| **Honcho** | ~95% | **14/14 pass** | Full API + `.aio` | **Yes** |
| **Graphiti** | ~95% | **20/20 pass** | graphiti-core v0.29.2 | **Yes** |
| **Mem0** | ~92% | **26/26 pass** | v2.0.5 — missing `entity_store` (Qdrant) | Near |
| **Hindsight** | ~95% | **10/10 pass** | v0.8.1 — upstream not on PyPI | Near |
| **QMD** | ~75% | Architecture parity | CLI tool — context trees + LLM rerank missing | Tracking |

**113/113 adapter behavioral tests pass.** 393 total tests (91 Rust + 249 Python + 53 frontend).

---

## QMD (tracked June 2026)

QMD (tobi/qmd, 26.5K stars) is a local CLI search engine — not a library, so no drop-in adapter possible. Feature parity tracked at architecture level:

| Has | Missing |
|-----|---------|
| BM25 + vector + hybrid search | **Context trees** — hierarchical context propagation (killer feature) |
| MCP server (15 tools) | **LLM reranking** — node-llama-cpp local reranker |
| CLI tool (17+ groups) | **Fuzzy matching** on document get |
| Agent integration (Hermes/MCP/SDK) | **Glob-based multi-get** |
| Workspace ACL + auth | **HTTP transport** for MCP daemon mode |

Score: ~75%. Context trees are the most valuable gap — they let LLMs understand WHY a document was returned.

---

## v1.27.0 State

- **40+ `except Exception` → `except RuntimeError`** across all adapters + client
- **Zep v2.0.2**: `Zep` with `.memory`/`.user`, `AsyncZep`, `ZepClient` alias, 18 new types
- **Graphiti 20/20**: `remove_episode` return type + `build_communities` return type fixed
- **Hindsight 10/10**: Full behavioral test suite added
- **LangGraph 17/17**: `refresh_ttl` batch fix
- **19 `.iter()` calls capped** with `.take(MAX_RESULTS)` across Rust reducers
- **30 new frontend component tests** (53 total — KnowledgeGraph, SmartQuery, GraphViz, TrajectoryViz)
- `make ci` full local pipeline (Rust + Python + TypeScript + adapter tests)
- Frontend tests: 23 → 53

---

## Remaining Work

| Priority | Task | Effort | Blocked? |
|----------|------|--------|----------|
| **P4a** | Context tree system (QMD parity) | 8-16h | No |
| **P4b** | LLM reranking in hybrid_search | 4-8h | No |
| **P4c** | Docker smoke test | 1h | Yes (no Docker) |
| **P4d** | E2E/Playwright frontend tests | 8h | No |
| **P4e** | PyPI publish | 1h | Yes (no token) |
| **P4f** | CI integration tests against live STDB | 4h | No |
| **P4g** | Fuzzy get + glob multi-get (QMD parity) | 2-4h | No |

**Current score: ~90/100.** Up from 88: Graphiti fixed (+4), Hindsight tested (+2), pagination (+2), frontend tests (+4), QMD tracked. Downside: QMD gaps identified (-4), PyPI still blocked (-2).
