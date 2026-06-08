# Production Roadmap: Polished Prototype → Deployable Memory System

> **Current state:** 95 tests passing (74 unit + 21 integration). All core CRUD works against real SpacetimeDB. ACL functional but fragile. Docker/CI never verified. Zero auth or observability.

**Goal:** A system you can deploy, trust, and depend on for a single-agent or small multi-agent setup.

**Tech constraints:** SpacetimeDB v2.4.1, Python SDK, Rust WASM module, ONNX embedder sidecar.

---

## Phase 0 — Housekeeping (1 hour)

Tasks blocked only by committing and tagging.

| # | Task | Files | Effort |
|---|------|-------|--------|
| 0.1 | Commit current fixes to `main` | `client.py`, `test_integration.py`, `workspace.rs` | 5 min |
| 0.2 | Tag `v0.3.0` + push | — | 2 min |
| 0.3 | Trigger CI pipeline (push triggers `main`) | `.github/workflows/ci.yml` | 5 min |
| 0.4 | Fix any CI failures | varies | ~30 min |

**Done when:** CI shows green on the `v0.3.0` commit.

---

## Phase 1 — Ship Integrity (2-3 hours)

The gaps that make "deploy and trust" impossible today.

### 1.1 Docker Build Verification

**Problem:** Dockerfile and compose exist, have never been built. The `.dockerignore` excludes `*.onnx` but the Dockerfile downloads the model at build time — this needs verification. The current compose exposes all ports on the same service which is wrong (SpacetimeDB, embedder, and frontend should be separate services or properly layered).

**Deliverable:** `docker compose up --build` produces a running stack that passes integration tests.

**Tasks:**
1. Fix compose to split SpacetimeDB standalone + embedder into separate services with health checks
2. Fix Dockerfile — verify the WASM module is embedded correctly, model downloads
3. Build the image locally (if Docker available) or document the expected workflow
4. Write a one-line smoke test script

### 1.2 JWT Auth in Client SDK

**Problem:** Every HTTP request from the SDK gets a different SpacetimeDB anonymous identity. The ACL bypass (allow if caller has zero permission records) hides this at the Rust level, but it's wrong — the SDK should authenticate as a specific identity for all calls.

**Deliverable:** SDK sends `Authorization: Bearer <jwt>` header on all reducer and SQL calls. The JWT key pair already exists at `data/id_ecdsa*`.

**Tasks:**
1. Add `token` parameter to `Client.__init__`
2. Send `Authorization: Bearer` header on every `_sql()` and `_call()` request
3. Add `login()` method that accepts token or generates one
4. Update integration tests to use JWT auth
5. Re-run tests — ACL bypass should still work, but now tests are authenticated properly

### 1.3 Embedder Error Propagation

**Problem:** When the ONNX sidecar is down, `_embed()` returns `[]` silently. This means semantic search degrades to empty results with no indication to the caller.

**Deliverable:** Controlled failure — raise a clear `EmbedderUnavailableError` when the sidecar is unreachable, with a middleware option for silent fallback.

**Tasks:**
1. Define `EmbedderUnavailableError` (or reuse `ConnectionError`)
2. Raise it in `_embed_local()` when the sidecar is down (instead of returning `[]`)
3. Keep `_embed_openai()` fallback working
4. Update `search()` to catch the error and fall back to keyword-only mode
5. Add integration test for embedder-down scenario

### 1.4 CI Pipeline Verification

**Problem:** The CI workflow exists but has never run. TypeScript job references a `client/` directory. Need to verify the actual project layout.

**Deliverable:** All CI jobs pass on `main`.

**Tasks:**
1. Remove the TypeScript job if `client/` doesn't exist (it's a stub)
2. Fix Docker job smoke test (current test sleeps 10s and curls `/health` — SpacetimeDB doesn't have a `/health` on the default port)
3. Push and verify the action runs

---

## Phase 2 — Production Hardening (1-2 weeks)

### 2.1 Full ACL Model

**Problem:** The bypass ("allow if caller has zero permission records") is a leaky abstraction. One `grant_space_access` call anywhere flips it off for that peer permanently.

**Deliverable:** A proper ACL model where:
- Anonymous (unauthenticated) callers have read-only access to public workspaces
- Authenticated callers have the permissions they've been granted
- Workspace creators always have owner access
- Admin identity can manage all workspaces

**Tasks:**
1. Add `public` flag to `Workspace` (public workspaces readable by anyone)
2. Change `check_space_access` to: authenticated + permitted = pass; unauthenticated + public workspace = read-only pass; else deny
3. Add admin identity config
4. Migrate existing workspace records (default to private)

### 2.2 Backup & Restore

**Problem:** DEPLOYMENT.md mentions backup but no process exists.

**Deliverable:** A `stmem backup` and `stmem restore` CLI command.

**Tasks:**
1. Implement backup — snapshot all tables via SQL, write to JSON
2. Implement restore — read JSON, insert into fresh database
3. Integration test for backup/restore round-trip

### 2.3 Basic Observability

**Problem:** No metrics, no structured logging from the Python SDK, no way to know what's happening without reading SpacetimeDB server logs.

**Deliverable:** Structured logging in the SDK, health endpoint on the embedder, basic metrics (request count, latency, error rate).

**Tasks:**
1. Add `structlog` or standard `logging` with structured format to SDK
2. Add `request_id` to each SDK call for traceability
3. Verify embedder `/health` endpoint works
4. Add a readiness check script for Docker health checks

### 2.4 Graceful Degradation

**Problem:** If SpacetimeDB goes down, the SDK throws unhelpful connection errors.

**Deliverable:** Retry with backoff on connection failures, configurable timeout, clear error messages.

**Tasks:**
1. Add retry logic (3 attempts, exponential backoff) to `_call()` and `_sql()`
2. Add configurable `max_retries` parameter to Client
3. Improve error messages to distinguish "SpacetimeDB down" from "invalid query"

---

## Phase 3 — Adapter Layer (2-3 weeks, optional)

If the goal is "drop-in replacement" for other projects, this is what it takes.

| Adapter | Effort | Value |
|---------|--------|-------|
| Mem0-compatible API (`add()`, `search()`, `get()`) | 3-5 days | Highest — most requested |
| Zep-compatible GraphQL wrapper | 5-7 days | Medium — niche but loyal |
| Graphiti-compatible `add_triple()` | 2-3 days | Low — small community |
| LangChain/LangMem integration | 2-3 days | Medium — ecosystem access |

**Approach for each:** Write a thin adapter class that translates the target API to `Client` calls. No need to change the core SDK. Each adapter gets its own package (e.g., `stmem-adapter-mem0`).

---

## Effort Summary

| Phase | Wall Time | Who |
|-------|-----------|-----|
| **Phase 0** — Housekeeping | 1 hour | You or me |
| **Phase 1** — Ship Integrity | 2-3 hours | Me, in one focused session |
| **Phase 2** — Hardening | 1-2 weeks | You (or me on direction) |
| **Phase 3** — Adapters | 2-3 weeks | Optional, per-need |

## Decision Point

After Phase 1, you'll have a JWT-authenticated, Docker-deployable, CI-verified system. That clears the "polished prototype" stage and gets you to a deployable memory server.

**I can execute Phase 0 + Phase 1 right now** — commit the fixes, wire up JWT, verify Docker build docs, fix CI. It's a single focused session.

After that, Phase 2 needs a decision on how deep to go with ACL vs just documenting the known limitations, and whether backup/observability are blocking concerns for your actual use case.

Want me to start with Phase 0 + 1?

---

*Generated from the `writing-plans` skill. Plan saved to `ROADMAP-PRODUCTION.md`.*
