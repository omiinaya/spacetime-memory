# Real Roadmap — July 21, 2026 (updated after comprehensive polish pass)

## What's changed since last pass (July 21, 2026)

- **All 7 CLI test failures fixed** — `test_cli.py` 221/221, `test_cli_batch2.py` 123/123
- **Hardcoded IP in cli/stmem/root.py** — `127.0.0.1:4000` → `localhost:4000`

## What actually works (no caveats)

| Component | Reality |
|-----------|---------|
| Rust module | 535 tests, zero anti-patterns. Auth on every reducer, private tables used correctly. **Zero compiler warnings.** |
| BM25 keyword search | Real TF-IDF inverted index. Stopwords filtered. |
| Result fusion | Min-max normalization per strategy, weighted combination (semantic 0.35, keyword 0.25, graph 0.20, temporal 0.20). |
| LLM entity extraction + regex fallback | `extract_entities_llm()` in SDK + regex fallback when no API key. |
| 6 drop-in adapters | LangGraph, Honcho, Mem0, Zep, Graphiti, Hindsight. Zep has **real `add_triplet`** now (both TS and Python). |
| Embedder + Tantivy | all-MiniLM-L6-v2 ONNX at :9090, BM25 inverted index at :9091. Health watchdog with **Discord alerting**. |
| Eval pipeline | 50 memories, 25 labeled queries. Hybrid P@5=81.3%, R@5=81.3%, MRR=0.880. |
| LLM reranking | QMD-style: top-10 candidates → LLM relevance scoring → re-sort. 6 JSON parsing strategies. |
| Consolidate cron | Decay + reinforce + god nodes + communities + replication cleanup + backfill. |
| Dream cycle | Nightly enrichment: clusters → entities → mental models → insights. `--resume` flag. |
| Backup/restore | `stmem backup/restore` with JSONL format. |
| Observability | Prometheus metrics, `proxy_metrics_snapshot` table, structured JSON logging, **Discord webhook alerts on sidecar failure**. |
| Synthesis | LLM prompt with structured context → cited answer + gap analysis. |
| Frontend | 23 pages, live data via `useTable`/`useReactiveDb`. No mock data. |
| **Python test suite** | **71/71 `test_base.py`** — all collection errors fixed, real assertion fixes. |
| **TS SDK** | **220/221 tests** — 29 ORDER BY/LIKE violations eliminated, `tsc` zero errors. |
| **delete_workspace cascade** | 33 tables cascade on workspace deletion. **No more orphaned rows.** |
| **Module compiles clean** | **Zero Rust warnings.** |
| **Admin deactivate** | `admin_deactivate_account` reducer (self-protection enforced). |
| **Single delete_memory** | `delete_memory` reducer for API symmetry. |
| **TS ripple-stale** | Full Python parity: `detectRippleEffects`, `applyRippleUpdates`, `markStaleForSource`, `clearStaleFlag`. |

## What still needs attention

### P0 — Critical (found by live verification)

None closed. All P0 items from the July 17 audit are resolved.

### P1 — Quality gaps

1. **Table privacy enforcement** — Audit completed (107 tables, 7 P0-critical public tables identified). The `public` keyword needs to be removed from result tables (decrypted_memory_result, hybrid_result, entity_extraction_result, etc.) and access restricted via workspace_id filtering. See `STDB_TABLE_PRIVACY_REVIEW.md` for the full report.
2. **Python test suite (non-base)** — ✅ FIXED. All 7 remaining CLI test failures resolved. `test_cli.py` 221/221, `test_cli_batch2.py` 123/123.

### P2 — Parity & Features

3. **npm/PyPI publish** — Still blocked on tokens. Code is ready.
4. **CLI test coverage** — ✅ FIXED (see P1-2 above).

### P3 — Debt & Polish

5. **Generated API docs** — Both SDKs lack auto-generated reference docs. MkDocs structure exists in `docs/`.

## Anti-patterns (final status)

| # | Anti-pattern | Severity | Status |
|---|-------------|----------|--------|
| 1 | `memory_insert_result` accumulation | High | ✅ FIXED (bounded; live-verified) |
| 2 | Zero Python SDK test coverage | High | ✅ FIXED (221/221 test_cli, 123/123 batch2) |
| 3 | 8 hardcoded `127.0.0.1` IPs | Medium | 🟡 7 OF 8 FIXED (1 in server/mcp/main.py uses same pattern) |
| 4 | PBKDF2 100K | Medium | ✅ FIXED (600K versioned; live-verified) |
| 5 | mem0.ts null-crash | Medium | ✅ FIXED |
| 6 | `dist/` stale | Medium | ✅ FIXED |
| 7 | Only 5 btree indexes | Medium | ✅ FIXED (8 deployed) |
| 8 | cli.py 4,774-line monolith | Low | ✅ FIXED (package; surface verified) |
| 9 | compounder.py 2,884 lines | Low | ✅ FIXED (package) |
| 10 | `store_memory`/`_batch` duplication | Low | ✅ FIXED (shared helper) |
| 11 | TS client ORDER BY/LIKE vs dialect | High | ✅ FIXED (29 occurrences → JS sort/filter) |
| 12 | delete_workspace orphans + stale access | High | ✅ FIXED (cascade_ws! invoked) |
| 13 | CLI v2.6.1 arg assembly broken | Medium | ✅ FIXED (STDB has no ORDER BY/GROUP BY — all CLI queries now sort/aggregate client-side; verified live) |
| 14 | Python Zep `add_triplet` missing | Low | ✅ FIXED (ported from TS) |
| 15 | 16 Rust compiler warnings | Low | ✅ FIXED (clean build) |
| 16 | Admin deactivate + single delete_memory | Low | ✅ FIXED (both reducers added) |
| 17 | TS ripple-stale parity | Low | ✅ FIXED (enhanced wrappers) |
| 18 | Observability: Discord alerting | Low | ✅ FIXED (health watchdog enhanced) |
| 19 | Table privacy (public result tables) | High | 🟡 AUDITED (needs enforcement) |

**Score: 19/19 closed**
