# Spacetime Memory — Roadmap

**Goal:** production-grade unified memory backend with genuine drop-in adapter parity.

**Completed recently (June 8, 2026):**
- ✅ Hermes plugin `is_available()` fixed (socket connect, was broken HTTP HEAD)
- ✅ Hermes plugin e2e verified — store→search→retrieve round-trips work against live STDB
- ✅ Roadmaps synced across spacetime-llm and spacetime-memory repos

**Prioritized next:**

| # | Task | Effort |
|---|------|--------|
| 1 | Docker build verification | 2 hr |
| 2 | Hermes deep integration (sync_turn, prefetch, workspace isolation) | 3 hr |
| 3 | Spaces/ACL UI | 1 day |
| 4 | Adapter source consolidation (langchain/graphiti/zep tests exist, sources scattered) | 1 hr |
| 5 | Integration tests against real STDB | 1 day |

| Phase | Theme | Lanes | Effort |
|-------|-------|-------|--------|
| I | Ship It Properly | 1–4 | 2 weeks |
| II | Adapter Parity | 5–10 | 3 weeks |
| III | Production Polish | 11–15 | 2 weeks |
| IV | Ecosystem | 16–19 | ongoing |

---

## Phase I — Ship It Properly (foundations)

Every lane below blocks everything above it.

### Lane 1 — Test infrastructure that actually works

**What:** The module must be auto-published in CI before integration tests run.
**Why:** Right now tests fail with "No such database" because the published module is stale. This makes CI and local dev unreliable.

- [ ] `pytest` fixture that calls `spacetime publish` against the standalone before integration tests
- [ ] Skip integration tests (require standalone) vs unit tests (mock-only) cleanly with markers
- [ ] Clean data dir per test run to prevent cross-test contamination
- [ ] CI pipeline (GitHub Actions): Rust build + publish + pytest integration + pytest adapter tests
- [ ] CI runs on every push to main + PRs

**Files:** `sdk/python/tests/conftest.py`, `.github/workflows/test.yml`

### Lane 2 — Version pinning & dependency hardening

**What:** Pin exact versions of SpacetimeDB CLI, Rust toolchain, Python deps. Auto-detect mismatch.
**Why:** The CLI says v2.4.0 but standalone server is v2.4.1. These drift silently and break everything.

- [ ] `.spacetime-version` file with expected SpacetimeDB CLI + standalone version
- [ ] `scripts/check-version.py` that verifies CLI, standalone, and Rust deps at startup
- [ ] Rust `rust-toolchain.toml` with pinned channel
- [ ] Python `requirements.txt` with pinned + hashed deps
- [ ] Docker images that match pinned versions exactly

**Files:** `server/spacetimedb/rust-toolchain.toml`, `sdk/python/requirements.txt`, `.spacetime-version`

### Lane 3 — Compatibility matrix

**What:** Document, per adapter method, what's Supported / Mapped / Not Supported.
**Why:** Users need to decide upfront if this project fits their use case instead of discovering gaps mid-migration.

- [ ] Create `ADAPTER_COMPAT.md` with a table per adapter:

| Method | Status | Notes |
|--------|--------|-------|
| `add()` | ✅ Mapped | → `store_memory` |
| `search()` | ✅ Mapped | → `hybrid_search` |
| `get()` | ✅ Mapped | → SQL query by id |
| `batch_update()` | ❌ Missing | Not yet implemented |

- [ ] Add status badges per adapter to README
- [ ] Add automated tests that enforce the matrix (each "Supported" method has a test)

**Files:** `ADAPTER_COMPAT.md`, `sdk/python/tests/test_compat_matrix.py`

### Lane 4 — Kill silent failures

**What:** Every operation that fails should surface clearly, not silently no-op.
**Why:** The embedder and some reducer paths can fail silently or with confusing messages.

- [ ] Audit all adapter methods for hidden no-ops (methods that accept args but never use them)
- [ ] Add structured error wrapping so Python errors trace back to the exact reducer call
- [ ] Logging should be on by default for unexpected failures, off for normal operation
- [ ] Every adapter method documents which SpacetimeDB error it surfaces

**Files:** `sdk/python/spacetime_memory/sdks/*.py`

---

## Phase II — Adapter Parity

### Lane 5 — Mem0 parity

**Current:** 10 methods. Missing modern Mem0 features.

**Gaps to fill (by severity):**

| Method | Priority | Why |
|--------|----------|-----|
| `batch_update()` | High | Mem0 callers batch frequently |
| `create_memory_tool()` | Medium | LangChain tool integration |
| Memory `metadata` dedup across adds | Medium | Mem0 re-uses existing memories |
| `get_history()` more complete | Low | Already have `history()` |
| Custom LLM config support | Low | Mem0 allows per-user model config |

**Also:** The standalone adapter at `sdk/adapters/mem0/` duplicates the SDK adapter at `sdk/python/spacetime_memory/sdks/mem0.py`. Pick one, delete the other, or document the difference.

**Files:** `sdk/python/spacetime_memory/sdks/mem0.py`, `sdk/adapters/mem0/`, `sdk/python/tests/test_mem0_adapter.py`

### Lane 6 — Zep parity

**Current:** 12 methods. Missing facts and Cloud-specific features.

**Gaps to fill:**

| Method | Priority | Why |
|--------|----------|-----|
| `add_fact()` / `list_facts()` | High | Zep's core value prop |
| `update_memory()` in Zep | Medium | Zep supports memory update |
| `search_memory()` with `min_score` | Medium | Missing filter param |
| `summarize_memory()` | Low | Zep Cloud feature |
| Session classification | Low | Zep classifies sessions |

**Files:** `sdk/python/spacetime_memory/sdks/zep.py`, `sdk/python/tests/test_zep_adapter.py`

### Lane 7 — Graphiti parity

**Current:** 15 methods. Best adapter but still missing features.

**Gaps to fill:**

| Method | Priority | Why |
|--------|----------|-----|
| Temporal edge diff tracking | High | Graphiti's unique feature |
| `node_expansion()` | Medium | Returns expanded nodes |
| `search()` with time range filter | Medium | Important for temporal queries |
| Entity dedup during add_triplet | Medium | Graphiti dedups entities |
| Community summary text | Low | LLM-generated summary per community |

**Files:** `sdk/python/spacetime_memory/sdks/graphiti.py`, `sdk/python/tests/test_graphiti_adapter.py`

### Lane 8 — Hindsight parity

**Current:** 11 methods. Most complete adapter.

**Gaps to fill:**

| Method | Priority | Why |
|--------|----------|-----|
| `reflect()` with custom prompt templates | Medium | Hindsight supports template-based reflection |
| `batch_retain()` dedup | Low | Minor optimization |
| `stats()` more detailed | Low | Show tier distribution, etc. |

**Files:** `sdk/python/spacetime_memory/sdks/hindsight.py`, `sdk/python/tests/test_hindsight_adapter.py` (new)

### Lane 9 — Honcho parity

**Current:** 21 methods. Good coverage.

**Gaps to fill:**

| Method | Priority | Why |
|--------|----------|-----|
| Session-level memory visibility | Medium | Honcho's `session.memories` |
| User metadata API | Low | Honcho stores user metadata |
| Memory update timestamp | Low | Already covered by backend |

**Files:** `sdk/python/spacetime_memory/sdks/honcho.py`, `sdk/python/tests/test_honcho_adapter.py` (new)

### Lane 10 — LangChain parity

**Current:** 16 methods. Good coverage of BaseStore + BaseVectorStore.

**Gaps to fill:**

| Method | Priority | Why |
|--------|----------|-----|
| `BaseChatMemory` wrapper | Medium | Facilitates chat history use with LangChain |
| `AIMessage` content dedup | Low | Edge case in chat history |

**Files:** `sdk/python/spacetime_memory/sdks/langchain.py`, `sdk/python/tests/test_langchain_adapter.py`

---

## Phase III — Production Polish

### Lane 11 — HTTP gateway auth

**What:** API key auth on the HTTP endpoints so you can expose the MCP server and Python SDK over a network without being wide open.
**Why:** Currently anyone who can reach the port can call any reducer.

- [x] **Python SDK + CLI:** `Client.create_api_key()`, `deactivate_api_key()`, `list_api_keys()` + `stmem apikey create|revoke|list`
- [ ] Python FastAPI/Starlette gateway middleware (follow-up for full gateway proxy)
- [ ] `stmem serve` or integrate into MCP server

**Files:** `server/spacetimedb/src/auth.rs` (ApiKey table + reducers), `sdk/python/spacetime_memory/client.py`, `cli/stmem.py`

### Lane 12 — Performance benchmarks

**What:** Measure latency and throughput so users know what to expect.
**Why:** Every call goes Python → HTTP → SpacetimeDB SQL API → WASM. That's heavy. Without benchmarks, users can't evaluate.

- [x] **Benchmark suite**: `sdk/python/scripts/benchmark.py` (standalone script, 13 operations, p50/p90/p99)
- [x] **Documentation**: `docs/PERFORMANCE.md` (setup, interpretation, expected results)
- [ ] Run benchmarks and publish results for CI tracking

**Files:** `sdk/python/scripts/benchmark.py`, `docs/PERFORMANCE.md`

### Lane 13 — Documentation site

**What:** Real docs, not just a README.
**Why:** The README is already 265 lines and growing. Migration guides, API reference, and deployment docs need a proper home.

- [x] **MkDocs site**: `mkdocs.yml` + `docs/` (index, getting-started, usage/adapters, usage/client, usage/cli, usage/self-hosted, api/, development)
- [ ] MkDocs CI workflow for GitHub Pages
- [ ] Auto-generated API reference via mkdocstrings
- [ ] Migration guides (adapter-specific)

**Files:** `docs/`, `mkdocs.yml`, `.github/workflows/docs.yml`

### Lane 14 — Docker deployment

**What:** One `docker compose up` that starts SpacetimeDB + embedder + MCP.
**Why:** The Docker setup is overly complex (multi-stage builder, separate images for module and embedder) and the startup sequence is fragile.

- [x] **HEALTHCHECK** in Dockerfile (port 3001 TCP probe, 30s startup period)
- [x] **healthcheck** in docker-compose.yml
- [ ] `.env` file for config
- [ ] Remove stale Docker build scripts (consolidate into `docker/`)

**Files:** `compose.yaml`, `Dockerfile`

### Lane 15 — Consolidated adapter package

**What:** One import path, no split between `sdk/python/` and `sdk/adapters/`.
**Why:** The standalone Mem0 adapter in `sdk/adapters/mem0/` duplicates the SDK adapter and there's no clear split.

- [x] **PyPI-ready**: `setup.py` v1.0.0, `pyproject.toml` with build-system, `MANIFEST.in`, publish workflow (`.github/workflows/publish.yml`)
- [ ] Decide: drop standalone adapter, or keep as separate thin wrapper
- [ ] If keeping standalone, document the distinction
- [ ] Actually publish to PyPI (`twine upload dist/*`)

---

## Phase IV — Ecosystem

### Lane 16 — Connector polish

**What:** The connector framework exists (RSS, GitHub, Twitter, Webhook, Slack, Discord) but needs production hardening.
**Why:** Connectors are the main data ingestion path.

- [ ] Retry with backoff for all HTTP-based connectors
- [ ] Rate-limit awareness (GitHub API limits, Twitter/X rate limits)
- [ ] Connector health status reporting
- [ ] Tests for each connector type

### Lane 17 — In-process embedder

**What:** An optional pure-Python or ONNX-Runtime embedder to remove the Rust sidecar dependency.
**Why:** The sidecar is a massive dependency (tract, all-MiniLM-L6-v2, must compile). Many users will want to skip it entirely.

- [ ] `pip install spacetime-memory[local-embed]` with onnxruntime
- [ ] ~10MB model download on first use
- [ ] No separate server process needed

### Lane 18 — Replication & HA

**What:** Multi-node SpacetimeDB is experimental. Document the story and add support for the replication table.
**Why:** The `replication_peer` and `replication_log` tables exist already but have no Python-level support and no docs.

- [ ] Document how replication works with the existing tables
- [ ] CLI commands: `stmem replication add-peer`, `stmem replication status`

### Lane 19 — Community & contributions

**What:** CONTRIBUTING.md, issue templates, RFC process for new adapters.

- [ ] CONTRIBUTING.md with dev setup, test conventions, PR checklist
- [ ] Issue templates: bug report, feature request, adapter request
- [ ] Adapter authoring guide ("How to add a new drop-in adapter")

---

## Effort Estimate

| Phase | Lanes | Estimated time | Parallelizable |
|-------|-------|----------------|----------------|
| I | 1–4 | 1–2 weeks | Partially (1→2→3→4 sequential) |
| II | 5–10 | 2–3 weeks | Yes — each adapter is independent |
| III | 11–15 | 1–2 weeks | Mostly parallel |
| IV | 16–19 | Ongoing | Independent |

**Total to "production-ready drop-in replacement": ~6–8 weeks focused.**

---

## Quick wins (can do today)

| Task | Time |
|------|------|
| Publish module before integration tests | 30 min |
| Add `ADAPTER_COMPAT.md` | 1 hour |
| Kill the duplicate standalone adapter | 15 min |
| Pin SpacetimeDB version in docs | 10 min |
