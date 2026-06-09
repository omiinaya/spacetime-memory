# Spacetime Memory — Roadmap

**Goal:** production-grade unified memory backend with genuine drop-in adapter parity.
**Last updated:** June 9, 2026 — revised after upstream source comparison against all 6 real libraries.

---

## Drop-in Fidelity Scorecard

| Adapter | Current Score | Target | Verdict |
|---------|:------------:|:------:|---------|
| LangGraph | 100% | 100% | ✅ Already a true drop-in (inherits `BaseStore`) |
| Mem0 | 95% | 100% | ✅ API-compatible, init pattern differs trivially |
| Zep | 80% | 100% | ⚠️ Exception types, missing methods |
| Graphiti | 75% | 100% | ⚠️ EntityNode/Edge missing fields, Pydantic gap |
| Hindsight | 20% | 100% | ❌ **Complete API mismatch** — real is REST client |
| Honcho | 10% | 100% | ❌ **Complete API mismatch** — real is workspace/peer SDK |

---

## Roadmap

| Phase | Theme | Lanes | Effort |
|-------|-------|-------|--------|
| I | Fix Wrong Adapters | 1–3 | 2–3 weeks |
| II | Polish Close Adapters | 4–6 | 1–2 weeks |
| III | Ship It | 7–10 | 1 week |
| IV | Ecosystem | 11–14 | ongoing |

---

## Phase I — Fix Wrong Adapters

### Lane 1 — Hindsight: rewrite to match `hindsight_client`

**Why:** Our adapter claims to match `hindsight.Hindsight` but that doesn't exist on PyPI. The real library is `hindsight_client.Hindsight` (v0.8.1) from `vectorize-io/hindsight`. It's an HTTP client to a REST API, not an embedded SDK. We need to either:
  (a) Wrap it as an HTTP client that talks to our SpacetimeDB backend via a REST API, or
  (b) Create a compatible API surface that matches the real client's method signatures exactly

**Real API reference (from source at `hindsight-clients/python/hindsight_client/hindsight_client.py`):**

```
Hindsight(base_url, api_key=None, timeout=300.0, user_agent=None)
    retain(bank_id, content, *, timestamp, context, document_id, metadata,
           entities, tags, update_mode, retain_async) → RetainResponse
    retain_batch(bank_id, items, *, document_id, document_tags, retain_async) → RetainResponse
    recall(bank_id, query, *, types, max_tokens=4096, budget="mid", trace=False,
           query_timestamp, include_entities, max_entity_tokens, include_chunks,
           max_chunk_tokens, include_source_facts, max_source_facts_tokens,
           tags, tags_match, tag_groups) → RecallResponse
    reflect(bank_id, query, *, budget="low", context, max_tokens, response_schema,
            tags, tags_match, include_facts, include_tool_calls,
            include_tool_call_output, tag_groups, fact_types,
            exclude_mental_models, exclude_mental_model_ids) → ReflectResponse
    retain_files(bank_id, files, *, context, files_metadata) → FileRetainResponse
    close() / aclose()
    __enter__ / __exit__     # context manager
```

**Also async variants for all:** `aretain`, `arecall`, `areflect`, `aretain_batch`, `aretain_files`, `aclose`.

**No `forget()` method at the high level.** The low-level `memory_api.delete_memory()` "resets" observations, it doesn't delete.

**Return types are typed Pydantic models:** `RetainResponse`, `RecallResponse`, `RecallResult`, `ReflectResponse`, `ReflectFact`, `BankProfileResponse`, `FileRetainResponse`, `ListMemoryUnitsResponse`.

**Breakdown of work:**

| Item | Effort | Notes |
|------|--------|-------|
| Read and model real return types | 1 hr | Copy Pydantic models from `hindsight_client_api.models` |
| Rewrite `__init__` to match `Hindsight(base_url, api_key, ...)` | 1 hr | Accept base_url pointing to our SpacetimeDB gateway |
| Implement `retain(bank_id, content, ...)` | 1 hr | Map bank_id → workspace, content → store_memory |
| Implement `retain_batch(bank_id, items, ...)` | 1 hr | Bulk store via existing batch reducer |
| Implement `recall(bank_id, query, ...)` with full param set | 2 hr | Map to search with all filters (tags, types, budget, etc.) |
| Implement `reflect(bank_id, query, ...)` with full param set | 2 hr | Map to create_insight/LLM pathway |
| Implement `retain_files(bank_id, files, ...)` | 1 hr | File content → text → retain |
| Async variants (`aretain`, `arecall`, etc.) | 1 hr | async wrapper pattern |
| Context manager (`__enter__`/`__exit__`) | 30 min | |
| Remove `forget()` or map to low-level memory reset | 30 min | |
| Return typed Pydantic models instead of dicts | 2 hr | Model all 7 response types |
| Update comparison harness | 30 min | Re-run 5/6 comparison with accurate sigs |
| Write integration tests | 2 hr | Test against mock or real SpacetimeDB |

**Total:** ~14 hours

### Lane 2 — Honcho: rewrite to match `plastic-labs/honcho`

**Why:** Our adapter claims to match `honcho.Honcho` but the PyPI `honcho` is a Procfile manager. The real library is `honcho.Honcho` from `plastic-labs/honcho` (SDK at `sdks/python/src/honcho/client.py`). It's a workspace/peer/session-oriented API, not user/session.

**Real API reference (from source on GitHub):**

```
Honcho(workspace_id, base_url=None, *, environment="local" or "production",
       http_config=...) — workspace-scoped
    peer(id) → Peer                    # get or create peer by ID
    peers() → SyncPage[Peer]           # list peers in workspace
    session(id) → Session              # get or create session by ID
    sessions() → SyncPage[Session]     # list sessions
    workspaces() → SyncPage[str]       # list workspace IDs
    delete_workspace()                 # delete current workspace
    search(query) → SyncPage[SessionSearchResult]
    queue_status() → QueueStatusResponse
    schedule_dream(config)

    # Async via .aio accessor:
    .aio.peer(id) → PeerAio
    .aio.search(query) → AsyncPage

    # Metadata config:
    metadata, configuration, get_configuration(), set_configuration(...)

Peer:
    metadata, messages(), chat(query, session, ...), sessions()

Session:
    metadata, peers(), add_peers([Peer]), messages(), 
    chat(query, ...), context() → SessionContext,
    configuration, get/set_configuration()
```

**Key differences from our adapter:**
- No `create_user(name)` — use `peer(id)` to get or create
- No `create_session(user_id, location)` — use `session(id)` to get or create
- No `add(session_id, content)` — add messages via `peer.message()` or `session.add_messages()`
- Return types are typed Pydantic models
- `.aio` accessor for async operations
- Workspace-scoped with metadata/config management
- Real Honcho is a cloud service — our adapter would need to emulate the API

| Item | Effort | Notes |
|------|--------|-------|
| Model all real types (Peer, Session, Message, SessionContext, etc.) | 2 hr | From `honcho.api_types` |
| Rewrite `__init__` to match `Honcho(workspace_id, ...)` | 1 hr | workspace_id maps to our database identity |
| Implement `peer(id)` → Peer | 1 hr | get-or-create pattern |
| Implement `peers()` → SyncPage[Peer] | 1 hr | Paginated list |
| Implement `session(id)` → Session | 1 hr | get-or-create pattern |
| Implement `sessions()` → SyncPage[Session] | 1 hr | Paginated list |
| Implement Peer.message(), Peer.chat() | 2 hr | Message storage + LLM query |
| Implement Session.add_peers(), Session.messages(), Session.chat() | 2 hr | |
| Implement `search(query)` | 1 hr | Cross-session search |
| Implement `.aio` async accessor | 2 hr | Async wrappers for all methods |
| Workspace metadata/config management | 1 hr | |
| Return typed Pydantic models | 2 hr | |
| Remove existing API methods (create_user, create_session, add) | 30 min | |
| Update comparison harness | 30 min | |
| Write integration tests | 2 hr | |

**Total:** ~20 hours

### Lane 3 — Quick wins before Phase II (common to all adapters)

| Item | Effort |
|------|--------|
| Fix adapter docstrings that incorrectly claim "Matches the real XYZ SDK API" | 30 min |
| Audit and fix all 6 adapter `__init__` signatures for upstream compat | 1 hr |
| Standardise error handling pattern across all adapters (typed exceptions where upstream has them) | 2 hr |
| Standardise return types — use dataclasses/Pydantic where upstream does | 3 hr |
| Update comparison harness (`scripts/compare-upstream.py`) to test the RIGHT upstream APIs | 1 hr |
| Run full comparison suite and document remaining gaps | 1 hr |

**Total:** ~8 hours

---

## Phase II — Polish Close Adapters

### Lane 4 — Mem0: 95% → 100%

**Checking against real `mem0.Memory` (from `mem0ai` v2.0.4):**

Already shared 7 keyword params on `add()`, return dict matches. Remaining gaps:

| Item | Effort | Notes |
|------|--------|-------|
| Accept `MemoryConfig` in constructor alongside dict | 1 hr | Both `MemoryConfig` object and `dict` should work |
| Verify `graph.add/search/get_all/delete` match upstream mem0 graph API | 1 hr | Graph API might differ from real mem0 |
| Add `create_memory_tool()` for LangChain integration | 1 hr | Real mem0 has this |
| Metadata dedup across adds (mem0 re-uses existing memories) | 2 hr | Complex — requires content hashing |
| Fix return types to match upstream exactly | 1 hr | Compare field names/structures |
| Update comparison harness | 30 min | |

**Total:** ~7 hours

### Lane 5 — Zep: 80% → 100%

**Checking against real `zep_python.client.MemoryClient` (from `zep-python` v2.0.2):**

| Item | Effort | Notes |
|------|--------|-------|
| Import and raise typed Zep exceptions (`NotFoundError`, `BadRequestError`, `ApiError`) | 1 hr | Our adapter currently uses generic RuntimeError/ValueError |
| Add `add_session()` / `get_session()` methods | 2 hr | Real Zep has full session lifecycle |
| Add fact support (`add_fact`, `list_facts`, `delete_fact`) | 2 hr | Required for feature parity |
| Fix `search_memory()` to accept real Zep params | 1 hr | Real uses `min_score`, `lastn`, etc. |
| Fix `get_memory()` to return typed `Memory` model | 1 hr | Pydantic model from real Zep |
| Add `update_session()` / `list_sessions()` | 1 hr | |
| Async variants where needed | 1 hr | |
| Write integration tests | 2 hr | |

**Total:** ~11 hours

### Lane 6 — Graphiti: 75% → 100%

**Checking against real `graphiti_core.Graphiti` (from `graphiti-core` v0.29.2):**

| Item | Effort | Notes |
|------|--------|-------|
| Convert `EntityNode` to Pydantic model matching `graphiti_core.nodes.EntityNode` | 2 hr | Adding `uuid`, `labels`, `created_at`, `attributes` |
| Convert `EntityEdge` to Pydantic model matching `graphiti_core.edges.EntityEdge` | 2 hr | Adding `uuid`, `episodes`, `reference_time` |
| Remove extra `group_id` from `add_triplet` (make optional kwarg if kept) | 30 min | |
| Add `search_filter` and `driver` params to `search()` | 30 min | |
| Convert `AddTripletResults` to Pydantic model | 1 hr | |
| Convert `AddEpisodeResults` to Pydantic model | 1 hr | |
| Map `add_episode` LLM entity extraction (optional — real does it internally) | 4 hr | Complex LLM pipeline |
| Write integration tests | 2 hr | |

**Total:** ~13 hours

---

### LangGraph

No further work needed — already a true drop-in at 100%. Type hint cosmetics (`Sequence[Any]` → `Iterable[Op]`) are optional.

---

## Phase III — Ship It

### Lane 7 — Test infrastructure

From old roadmap Lane 1 (unchanged, still valid):
- [ ] `pytest` fixture that calls `spacetime publish` before integration tests
- [ ] Clean data dir per test run
- [ ] CI pipeline: Rust build + publish + pytest
- [ ] CI on push to main + PRs

### Lane 8 — Version pinning & dependency hardening

From old roadmap Lane 2:
- [ ] `.spacetime-version` file
- [ ] `scripts/check-version.py`
- [ ] Rust `rust-toolchain.toml`
- [ ] Python lockfile

### Lane 9 — Adapter compatibility matrix

From old roadmap Lane 3 (update with accurate data):
- [ ] Create `ADAPTER_COMPAT.md` with real per-method status per adapter
- [ ] Add status badges per adapter to README
- [ ] Enforce via tests

### Lane 10 — Performance & benchmarks

From old roadmap Lane 12 (update with adapter-specific benchmarks):
- [ ] Benchmark each adapter's core methods
- [ ] Publish results for CI tracking

---

## Phase IV — Ecosystem

From old roadmap:
- Lane 16 — Connector polish (✅ done)
- Lane 17 — In-process embedder (✅ done)
- Lane 18 — Replication & HA (✅ done)
- Lane 19 — Community docs (✅ done)
- PyPI publishing (deferred by user)

---

## Effort Estimate

| Phase | Lanes | Effort | Parallelizable |
|-------|-------|--------|----------------|
| I — Fix Wrong Adapters | 1–3 | 42 hours | Partially (hindsight + honcho in parallel) |
| II — Polish Close Adapters | 4–6 | 31 hours | Yes — each adapter is independent |
| III — Ship It | 7–10 | 1 week | Mostly parallel |
| IV — Ecosystem | — | Ongoing | Independent |

**Total to true 100% drop-in across all 6 adapters:** ~73 hours of work.

---

## Priority Order (recommended execution)

1. **Lane 3 (quick wins)** — fix docstrings, standardise error handling/return types across all adapters. Gets us credibility fast.
2. **Lane 1 (hindsight rewrite)** — biggest gap, highest visibility. The real library is a REST client — once we accept that, rewrite is straightforward.
3. **Lane 2 (honcho rewrite)** — second biggest gap. Same pattern: accept the real API shape and build it.
4. **Lane 5 (zep)** — exception types first (quick win), then facts + session methods.
5. **Lane 6 (graphiti)** — Pydantic models for EntityNode/Edge, add missing fields.
6. **Lane 4 (mem0)** — MemoryConfig acceptance, graph API verification.
7. **Lanes 7–10** — infrastructure, CI, benchmarks.
