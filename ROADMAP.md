# Spacetime Memory — Honest Assessment (June 9, 2026)

## Project Totals

| Layer | LOC | Files | Tests | Passing |
|-------|----|-------|-------|---------|
| Rust module | 8,706 | 26 .rs | 77 | 77 ✅ |
| Python SDK | 12,773 | ~30 .py | 239 | 239 ✅ |
| Frontend | 18,138 | 145 .tsx/.ts | 12 | 12 ✅ |
| **Total** | **~39,600** | **~200** | **328** | **328 ✅** |

## Rust Module — Assessment: 60/100

### What works (✅)
- Compiles clean for SpacetimeDB v2.4 WASM target
- 26 semantically organized modules (workspace, peer, memory, graph, etc.)
- All reducers use `Result<(), String>` — no `unwrap()` in production paths
- PBKDF2 password hashing with `require_auth`/`require_admin` guards on critical paths
- Space permission ACL (`check_space_access`) with owner/editor/viewer hierarchy
- Admin bypass for admin users
- 77 unit tests passing
- No dead code, no TODO/FIXME left in production code

### What's concerning (⚠️)

**1. 90% of reducers have no auth guard (CRITICAL)**
130 reducers total. Only 40 (31%) check `require_auth`, `require_admin`, or `check_space_access`.
The remaining 90 (69%) can be called by ANY SpacetimeDB client with zero authentication:
- `store_memory`, `delete_memory`, `update_memory` — data mutation
- `send_message`, `delete_message` — message ops
- `create_workspace`, `update_workspace`, `delete_workspace` — workspace ops
- `export_backup`, `restore_backup` — data export
- `replicate_incoming` — data injection from external peers
- `grant_space_access`, `revoke_space_access` — permission management

SpacetimeDB has identity-level auth (every anonymous client has a stable identity),
but the module itself doesn't enforce registration or permission checks on most reducers.
This means ANY SpacetimeDB client on the same database can read/write/delete everything.

**2. `.iter()` without pagination or limit (PERFORMANCE CRITICAL)**
Every reducer that reads data uses `.iter()` which scans ALL rows in the table.
SpacetimeDB doesn't have query optimization — `.iter()` returns every row:

| File | `.iter()` calls | With filter/limit |
|------|:-------------:|:-----------------:|
| knowledge_graph.rs | 25 | 0 |
| consolidation.rs | 23 | 7 |
| hybrid_query.rs | 14 | 1 |
| profile_query.rs | 14 | 0 |
| replication.rs | 11 | 0 |
| note.rs | 10 | 0 |
| graph_traversal.rs | 9 | 0 |

With >10K rows, most of these operations will time out or OOM.

**3. Custom UUID isn't RFC-compliant**
`uuid_v4()` in lib.rs generates unique IDs but doesn't set the RFC 4122 version/variant bits.
This is fine for internal use but these IDs won't be recognized as UUIDv4 by external systems.

**4. JSON manipulation via string concatenation**
`entity_linking.rs:65`, `profile.rs:77`, `profile.rs:120` build JSON arrays using
`format!("{}, {}]", ...)` instead of `serde_json::Value` — fragile, can produce invalid JSON
if input contains special characters.

**5. PBKDF2 at only 100K iterations**
OWASP 2026 recommends 600K+ for PBKDF2-HMAC-SHA256. At 100K, password hashing is
~6x weaker than recommended. (Trade-off: WASM is single-threaded and slow.)

### What's missing (❌)
- No `[dev-dependencies]` in Cargo.toml — can't add test frameworks
- No Rust-side integration tests for reducers (no `#[spacetimedb::test]` usage)
- No pagination in any reducer that reads lists

---

## Python SDK — Assessment: 70/100

### What works (✅)
- 239 tests all passing
- Client has circuit breaker, exponential backoff with jitter, error contracts
- All 6 adapters pass behavioral tests
- Clean `__init__.py` re-exports for all adapters
- Proper typed exceptions (`SpacetimeDBError`, `NotFoundError`, `ApiError`)
- Metrics collector with Prometheus export
- MCP server for LLM integration
- Structured JSON logging

### What's concerning (⚠️)

**1. Adapter feature parity gaps (noted per adapter below)**
- **Graphiti**: `add_episode()` requires pre-extracted nodes/edges. The real Graphiti
  uses LLM to extract entities from raw text. Without this, Graphiti adapter is just
  "store text + link manually" — missing the core feature.
- **Mem0**: `chat()` is an LLM completion call, not real RAG. Real Mem0 manages
  conversation history, retrieves relevant memories, and augments the response.
- **Zep**: No async support (Zep's upstream SDK has async endpoints).
- **Honcho**: No `.aio` async accessor (upstream Honcho has `.aio.peer()`, etc.)

**2. Type hints coverage is moderate**

| File | Typed methods |
|------|:------------:|
| hindsight.py | 1/10 (10%) |
| graphiti.py | 7/18 (39%) |
| mem0.py | 14/29 (48%) |
| zep.py | 13/29 (45%) |
| langchain.py | 15/23 (65%) |
| honcho.py | 24/47 (51%) |

Overall ~45% of methods have return type hints.

**3. Async wrappers are fragile**
- `Hindsight._run_async()` raises `RuntimeError` in running event loops
- No `.aio` accessor on Honcho adapter
- Zep adapter is entirely sync (upstream has both sync and async)

**4. `connectors.py` is monolithic (2,200+ lines)**
7 connector types (RSS, GitHub, Twitter/X, Webhook, Slack, Discord, Notion) plus
OrgMode parser and daemon. Should be split per connector.

---

## Adapter Feature Parity — Honest Assessment

| Adapter | Shape Match | Runtime Quality | Feature Gaps vs Upstream | Prod Ready? |
|---------|:-----------:|:---------------:|--------------------------|:----------:|
| **LangGraph** | 100% | ✅ True `BaseStore` | None | **Yes** |
| **Mem0** | 98% | ⚠️ Good | `chat()` is basic LLM, not real RAG. No `create_memory_tool()` | No |
| **Hindsight** | 95% | ⚠️ Good | Sync wrappers break in async ctx. No `forget()` (removed upstream too) | Near |
| **Zep** | 90% | ⚠️ OK | No async endpoints. Limited `search_sessions` | No |
| **Honcho** | 85% | ⚠️ OK | No `.aio`. `Peer.sessions()` always empty (no peer→session mapping in StDB) | No |
| **Graphiti** | 85% | ⚠️ OK | **No LLM extraction in `add_episode`** — requires pre-extracted entities. Dataclass vs Pydantic | No |

### What parity means vs doesn't mean

For Mem0, Hindsight, Honcho, Zep, Graphiti:
- **Shape parity**: method names, parameter lists, and return types mostly match ✅
- **Behavioral parity**: normal create/read/delete operations work against SpacetimeDB ✅
- **Feature parity**: LLM-powered features (entity extraction, memory-augmented chat, async I/O) are NOT replicated ❌

These adapters are "SpacetimeDB backend that speaks the same API" — they're NOT
"replacements that do everything upstream does." The gap is in the features that
require OpenAI/LLM integration or async infrastructure.

---

## Tests — Assessment: 75/100

### Python tests: 239 total (239 pass)

| Test Group | Count | Type | What they test |
|-----------|-------|------|----------------|
| Adapter tests | 91 | Hybrid shape + behavior | Each adapter method called against real StDB or mock |
| Unit tests | 100 | Unit | Client, metrics, logging, connectors, agent orchestrator |
| Integration | 48 | Integration | End-to-end with live SpacetimeDB. ACL, backup, error handling, data flow |

**Gaps:**
- Adapter tests verify that methods execute without error, but don't deeply verify
  that the stored data matches upstream's data shape
- No load/fuzz tests
- No network partition or SpacetimeDB outage tests
- The "integration" tests run against a standalone instance — no multi-node scenario

### Rust tests: 77 total (77 pass)
- 3/26 files have tests (note.rs, hybrid_query.rs, consolidation.rs, auth.rs)
- All test pure utility functions — no reducer-level tests
- Reducer logic is only tested via Python integration tests (2nd hand)

### Frontend tests: 12 total (12 pass)
- `cn()` utility + wikilink parsing — minimal
- 0 component rendering tests
- 0 E2E tests (no playwright)

---

## Frontend — Assessment: 65/100

- 23 routes, builds clean with no TS errors
- Uses SpacetimeDB's npm SDK for real-time subscriptions
- React.lazy code splitting on all pages
- Tailwind + shadcn UI — looks professional
- **0 component tests** — any runtime regression requires manual testing
- No type-safe reducer bindings (uses generic `callReducer(name, args)`)
- Several large pages (KnowledgeGraph, SmartQuery, TrajectoryViz) with complex rendering logic untested

---

## Overall Project Scores

| Dimension | Score | Notes |
|-----------|:-----:|-------|
| **Core functionality** (StDB module) | 60/100 | Functions but 90% auth gap and no pagination are blockers |
| **Adapter parity** | 70/100 | Shapes match, behavior works, but LLM features are missing |
| **Testing** | 75/100 | 328 tests pass, but no reducer-level Rust tests, minimal frontend tests |
| **Code quality** | 75/100 | Clean Rust error handling, moderate Python type hints, some bad patterns |
| **Security** | 30/100 | 90/130 reducers have no auth. Unauthenticated data access on every path |
| **Performance** | 40/100 | Full table scans on every read. Will fail > few thousand rows |
| **Docs/claims** | 85/100 | Fixed in v1.14. README is now honest |
| **Bootstrap** | 80/100 | Makefile + auto-publish conftest. PyPI not published |
| **CI** | 75/100 | 4 workflows exist. No integration test in CI (needs SpacetimeDB server) |

**Overall: ~65/100** — Working prototype with proven adapter compatibility,
but significant security and performance issues before production.

---

## Priority Remediation

### P0 — Fix auth gap (8-12h)
Add `require_auth` or `check_space_access` to the 90 unprotected reducers.
Without this, anyone on the network can read/write/delete all data.

### P1 — Add pagination/limits on iter() (4-6h)
Replace unlimited `.iter()` calls with paginated patterns or at least `.take(N)` limits
on user-facing queries (search, list, graph traversal).

### P2 — Feature parity (8-12h total)
- Graphiti `add_episode` LLM extraction (4h)
- Honcho `.aio` accessor (3h)
- Zep async support (3h)
- Mem0 `chat()` real RAG (4h)

### P3 — Critical infra (6-8h total)
- PyPI publishing (2h)
- Rust `#[spacetimedb::test]` integration tests (4h)
- Frontend rendering tests (4h)
