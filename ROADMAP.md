# Spacetime Memory — Roadmap v2

**Goal:** production-grade unified memory backend with honest drop-in adapters.
**Last updated:** June 9, 2026 — Phase IV complete.

---

## Status

**Phase I–III (First session, 9 lanes):** ✅ Complete
**Phase IV (This session):** ✅ Complete

### What got done

| Item | Before | After | 
|------|--------|-------|
| **README claims** | Listed `forget()`, `create_user()`, `get_user_memories()` — methods that don't exist | Fixed. Adapter table now shows runtime quality, not stale method names. "Inspired by" split from "Drop-in" |
| **Bootstrappable from clone** | No Makefile, no setup automation | `Makefile` with `make test`, `make test-unit`, `make test-all`. Full 237-test suite runs with one command |
| **Rust test coverage** | 66 tests in 3/26 files. 0 tests in auth.rs, knowledge_graph.rs, memory.rs, replication.rs, etc. | 77 tests (+11 in auth.rs). Added PBKDF2 + salt tests. Remaining modules are pure reducer functions (need SpacetimeDB runtime — covered by Python integration suite) |
| **Frontend tests** | 0 tests, 145 TSX files, 18K LOC | vitest + happy-dom setup. 12 passing tests (utils, wikilink parsing). `npm test` entry added |
| **Docs (getting-started.md)** | Stale adapter examples (create_user, forget) | Fixed. Accurate examples for all 6 adapters. Test section added |

### Honest scorecard

| Adapter | Shape | Runtime | Prod Ready? | 
|---------|-------|---------|-------------|
| LangGraph | 100% | ✅ Proper BaseStore | **Yes** |
| Mem0 | 98% | ⚠️ Good, stubby `chat()` | Nearly |
| Hindsight | 95% | ⚠️ Sync wrappers need care | Near |
| Zep | 90% | ⚠️ No async, methods limited | No |
| Huncho | 85% | ⚠️ No `.aio`, empty peer→session | No |
| Graphiti | 85% | ⚠️ Dataclass vs Pydantic, extra `group_id` | No |

### What's still true

- **Python tests:** 223 pass, 14 skip (ACL needs JWT key, backup needs DB env, 3 Honcho edge cases)
- **Rust tests:** 77 pass, 0 fail. Most untested modules are reducers — only testable via SpacetimeDB runtime (handled by the Python integration tests)
- **Frontend:** 12 vitest tests + production build compiles clean
- **PyPI:** Not published (user deferred)

### What would be next (if you circle back)

| Item | Effort | Why |
|------|--------|-----|
| Fix 14 skipped Python tests | 1-2h | ACL JWT key mismatch, backup config, 3 Honcho edge cases |
| PyPI publishing | 2h | Need setup.py/pyproject.toml audit then `twine upload` |
| Rust integration tests (`#[spacetimedb::test]`) | 4-8h | Would test reducers end-to-end in Rust. Requires SDK test harness |
| Frontend component tests (React Testing Library) | 4h+ | Render + assert key pages don't crash. Needs SpacetimeDB connection mocking |
| Honcho `.aio` async accessor | 3h | Phase IV gap |
| Zep async support | 3h | Phase IV gap |
| Graphiti LLM extraction in `add_episode` | 4h | Phase IV gap |
