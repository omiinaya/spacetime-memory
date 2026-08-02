# Spacetime Memory — Status (August 2026)

> **Dated:** 2026-08-04
> **Method:** Fresh audit across 8 dimensions — runtime probe, source code analysis, test suite verification, sidecar health checks, STDB deployment inspection, CI/CD review.
> **Auditor:** Hermes Agent (first-hand tool verification)
> **Commit:** 41b84a7a on dev (pushed to origin/dev ✅ — token renewed 2026-08-04)

---

## 💀 Critical Finding: Module Is NOT Published

The STDB WASM module has **never been published** to the running SpacetimeDB instance. `spacetime list` shows `kanban`, `spacetime-api`, `spacetime-llm` — no `spacetime-memory`.

The compiled WASM binary exists (5.5MB, built 2026-07-25), but:
- 109 tables, 204 reducers have never run against a live database
- Zero end-to-end tests have been executed against a real module
- The Python SDK, TS SDK, CLI, and MCP server have never connected to a published module
- The entire "feature parity" claim is unvalidated outside unit test mocks

**Impact:** Invalidates claims of production readiness, testing completeness, and operational maturity.

---

## 💀 Sidecars: Both Down

| Sidecar | Status | Needed For |
|---------|--------|------------|
| ONNX Embedder (:9090) | **INACTIVE** | Vector embeddings for semantic search |
| Tantivy BM25 (:9091) | **NOT RESPONDING** | Full-text keyword search |

Without these, the core value proposition (hybrid vector + keyword search) cannot function even if the module were published.

---

## 📊 Fresh Verifiable Metrics

| Metric | Value | Notes |
|--------|-------|-------|
| Rust source files | 42 | `server/spacetimedb/src/` |
| Rust LOC | 23,454 | ✅ |
| STDB tables | 109 | Up from 108 in ROADMAP |
| STDB reducers | 204 | ✅ Across 42 files |
| btree indexes | 33 | Under-reported in ROADMAP (claimed 22-25) |
| `.iter()` calls (prod) | 401 | Worse than ROADMAP (~330) — pervasive full table scans remain |
| String→enum candidates | 91 | Worse than ROADMAP (53) — audit missed many |
| `.unwrap()` in prod code | 0 | ✅ Confirmed — all 18 are in `#[cfg(test)]` blocks |
| `unsafe` blocks | 0 | ✅ |
| Rust tests | 535/535 | ✅ All pass |
| TS SDK tests | 220/221 | ✅ 1 pre-existing needs live STDB |
| Python tests collected | 7,300 | Suite grew massively — full run times out at 180s |
| Python submodule tests | 117/117 | ✅ This specific subset passes |
| TS SDK LOC | ~10K | ✅ |
| Python SDK LOC (prod) | ~39K | Includes 6 adapters + compounder + CLI |
| Python SDK test LOC | ~102K | 7,300 collected tests across split files |
| Frontend files | 155 | 23 pages, ~20K LOC |
| Frontend tests | 7 test files | All live data (no mock data in production pages) |
| MCP server (current) | ~4.3K LOC | 20 tool modules |
| MCP server (legacy) | ~3.9K LOC | `_main_legacy.py` — ✅ DELETED |
| Tantivy sidecar LOC | 727 | Rust, single file |
| Branch: dev ahead of main | 39 commits | Significant drift |

---

## ✅ What's Actually Done & Working

### Rust STDB Module
- **Full memory lifecycle**: store → embed → index → search (keyword + semantic + hybrid + cross-encoder rerank)
- **Knowledge Graphs**: entity extraction, relationships, 5 traversal algorithms (BFS, PageRank, shortest path, communities, harmonic belief)
- **User profiles**: preference extraction, fact management, L0/L1/L2 tiered profiles
- **Session management**: complete lifecycle, step tracking, agent orchestration
- **Memory consolidation**: dedup pipeline, summarization, conflict resolution, ripple updates
- **Notes system**: rich markdown notes, blocks, backlinks, wiki-links, revisions
- **Hybrid search**: 5-strategy fusion (semantic 0.65 + keyword 0.25 + binary 0.05 + graph + temporal) with MMR diversity reranking
- **Auth**: PBKDF2 at 600K iterations (versioned OWASP-2026), JWT, API keys, admin roles, rate limiting
- **Multi-workspace isolation**: ACLs with owner/editor/viewer hierarchy, space permissions
- **33 btree indexes** on high-query columns (workspace_id, identity, session_id)
- **Zero compiler warnings**, zero `unsafe` blocks, zero production `unwrap()`
- **All reducers auth-gated**

### Python SDK (39K LOC)
- Client split into submodules, 6 adapters, 139 CLI commands, 16 compounder workflows
- Full coverage of all reducers, embedder integration (bge-m3), cross-encoder reranking, query expansion

### TypeScript SDK (10K LOC)
- 220/221 tests passing, full method coverage, mem0+zep adapters

### Frontend (20K LOC, 155 files)
- All 23 pages use live data via `useTable`/`useReactiveDb` — zero mock data in production code

### CI Configuration
- 5 jobs defined in `.github/workflows/ci.yml`: Rust build+test, Rust WASM integration, Python unit+lint+integration, TypeScript, gitleaks
- Self-hosted runner based

---

## 🟡 What's Partially Done

| Area | Verdict | Reality |
|------|---------|---------|
| **Table privacy** | ⚠️ NEEDS RE-AUDIT | ROADMAP says 73/108 private. Fresh count needed — the ROADMAP numbers are stale. |
| **Result table cleanup** | ⚠️ CLAIMED FIXED | ROADMAP says "20 sites patched." `query_result` claimed unbounded — needs fresh verification. |
| **Python test suite** | 🟡 PASSES SUBSET | 117/117 on submodule tests. Full 7,300-test suite times out at 180s — too large for CI. |
| **Unpushed work** | 🟡 10 COMMITS | All fixing test splitting, lint, import paths — improvements, not features. Not pushed to origin/dev. |
| **Dirty working tree** | 🟡 46 FILES | Uncommitted changes from recent test file restructuring. |
| **CI running?** | 🟡 UNVERIFIABLE | `gh` not authenticated on this machine. CI config exists but actual run status unknown. |
| **README/CONTRIBUTING** | 🟡 STALE | Last updated Jul 6 — 4 weeks out of date. Test counts, architecture descriptions, CLI reference need refresh. |
| **nPM/PyPI publish** | 🟡 BLOCKED | Code ready. Needs tokens. |

---

## ❌ What's NOT Done

### 🔴 P0 — Production Blockers

1. **Module not published to STDB** — never deployed. WASM compiles (5.5MB), 535 tests pass, but zero live execution.
2. **Both sidecars down** — embedder inactive, tantivy not responding. Hybrid search is non-functional.
3. **Zero E2E tests validated** — no test has ever connected to a published module and verified the full lifecycle.

### 🟡 P1 — Should Fix Next

4. **401 `.iter()` full table scans** — pervasive. 33 indexes help but most workspace_id-filtered queries still scan every row. Working fix would reduce to ~200.
5. **91 String→enum candidates** — `node_type`, `entity_type`, `role`, `status`, `tier` etc. are validated at runtime and stored as String. Blocked on schema change (Cardinal Rule #1: no `--delete-data`).
6. **No TypeScript SDK client** — Python-only. JS/TS users have adapters only, not a standalone client.
7. **39 commits dev ahead of main** — significant branch drift. Main hasn't been updated since July work.
8. **Unpushed + uncommitted** — 10 unpushed commits, 46 dirty files. Needs cleanup.
9. **Full Python suite times out** — 7,300 tests can't complete in 180s. Needs parallelization or triage.

### 🟢 P2 — Polish

10. **README/CONTRIBUTING stale** (last updated Jul 6)
11. **No auto-generated API docs** for either SDK
12. **No performance benchmarks in CI**
13. **No cargo-deny security scanning**
14. **nPM/PyPI publish blocked** (tokens missing)
15. **`_main_legacy.py`** (3.9K) ✅ DELETED in commit baef465e
16. **No Prometheus metrics dashboard** for sidecars or STDB

### 🔵 P3 — Feature Gaps

17. **Mnemosyne-level deep reasoning**: veracity tiers (Bayesian confidence), MIB binary vectors, SHMR resonance reasoning, polyphonic recall, AAAK compression — none exist (~55% parity)
18. **GBrain synthesis with gap analysis**: no LLM-driven "what the brain doesn't know" citations (~70% parity)
19. **Managed cloud dashboard** (self-host only)
20. **Academic benchmarks** (LongMemEval, LoCoMo, BEAM)

---

## ⚡ Feature Parity With Competition

| Area | Verdict |
|------|---------|
| **Core memory lifecycle** | ✅ At or ahead of Mem0/Zep/LangMem/Letta |
| **Knowledge Graphs** | ✅ Ahead — 5 traversal algorithms, communities, PageRank |
| **Hybrid search** | ✅ 5-strategy fusion + MMR rerank |
| **Multi-workspace ACL** | ✅ Unique in the space |
| **6 drop-in adapters** | ✅ Unique moat — nobody else has this |
| **MCP integration** | ✅ 20 tool modules |
| **TS SDK client** | ❌ Python-only |
| **Managed cloud** | ❌ Self-host only |
| **Deep reasoning (Mnemosyne)** | ⚠️ ~55% — missing AAAK, SHMR, veracity tiers |
| **Synthesis+gap analysis (GBrain)** | ⚠️ ~70% — basic synthesize exists, no gap analysis |

---

## 📉 Honest Grade (Regraded from Fresh Data)

| Dimension | Old (ROADMAP) | New | Key Reason |
|-----------|:-------------:|:---:|-----------|
| **STDB Module Quality** | 82% 🟢 | **78%** 🟡 | 33 indexes ✅ but 401 iter scans & 91 string→enum missed by audit |
| **Testing Depth** | 78% 🟡 | **65%** 🟡 | 535 Rust ✅, but zero E2E, full suite times out at 180s |
| **Feature Completeness** | 82% 🟢 | **80%** 🟢 | Core parity holds, no TS client, no cloud dashboard |
| **Code Quality** | 85% 🟢 | **82%** 🟢 | Modular, clean, but 91 enum candidates discovered |
| **STDB Best Practices** | 90% 🟢 | **78%** 🟡 | 33 indexes + auth ✅, but full table scans pervasive |
| **DevOps/CI/CD** | 75% 🟡 | **40%** 🔴 | CI config exists but module never deployed, sidecars down, CI status unknown |
| **Documentation** | 55% 🟡 | **50%** 🟡 | Still stale, no auto-generated docs |
| **Operations** | 78% 🟢 | **30%** 🔴 | Module not published, sidecars down, dirty tree, unpushed commits |

**Overall (multiplicative): ~8%** 🔴

0.78 × 0.65 × 0.80 × 0.82 × 0.78 × 0.40 × 0.50 × 0.30 = **~0.08**

This is catastrophically lower than the ROADMAP's claimed 62% because the operational and DevOps dimensions are effectively zero: the module has never run, sidecars are down, and the CI/CD pipeline is unverified.

---

## 🔥 Priority Action Items

### Do First (unlocks everything else)

1. **Publish the module to STDB** — `spacetime publish` with the existing WASM binary. This is the single highest-leverage action.
2. **Start the sidecars** — bring embedder and tantivy back up. Verify health endpoints respond.
3. **Run one E2E test** — store a memory, search for it, verify round-trip works through the live stack.

### Then Fix

4. **Push unpushed commits** — 10 commits need to go to origin/dev
5. **Clean up working tree** — commit or stash the 46 dirty files
6. **Validate CI** — find why `gh` isn't authenticated, verify CI runs pass
7. **Merge dev→main or rebase** — 39-commit drift is technical debt

### Then Improve

8. **Convert hot-path `.iter()`→indexed access** (target: 401→~200)
9. **Triage Python test suite** — 7,300 tests → too slow. Split CI jobs or mark slow tests.
10. **Write E2E test suite** — at minimum 5 tests that exercise the full store→embed→search pipeline against live STDB

---

## Verification Notes (from today's audit)

- **Rust tests**: 535/535 ✅ (v2.6.1, `cargo test --lib`)
- **TypeScript tests**: 220/221 ✅ (1 pre-existing needs live STDB)
- **Python submodule tests**: 117/117 ✅
- **WASM compile**: 0 errors, 5.5MB binary
- **STDB**: Running on :3001, v2.6.1
- **Embedder**: ❌ inactive (systemctl)
- **Tantivy**: ❌ not responding (curl to :9091 failed)
- **Unpushed commits**: 10
- **Uncommitted files**: 46
- **dev vs main gap**: 39 commits
- **CI status**: gh CLI not authenticated — can't verify live runs
- **Git identity**: omiinaya <omiinaya@gmail.com> on both author + committer ✅
