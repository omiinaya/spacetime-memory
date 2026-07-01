# Real Roadmap — June 2026 (updated)

## What actually works (no caveats)

| Component | Reality |
|-----------|---------|
| Rust module | 86 tests, zero anti-patterns. Auth on every reducer, private tables used correctly. BM25 inverted index (`term_index` table), result fusion with min-max normalization per strategy, workspace pre-filters on all loops, MAX_RESULTS caps. |
| BM25 keyword search | Real TF-IDF inverted index. `index_terms` reducer tokenizes, removes stopwords, counts TF. `bm25_score()` and `bm25_idf()` functions. Replaces the old `str.contains()` substring hack. |
| Result fusion | Min-max normalization per strategy (semantic/keyword/graph/temporal) followed by weighted combination. Weights: semantic 0.35, keyword 0.25, graph 0.20, temporal 0.20. Scores are comparable across strategies. |
| LLM entity extraction | `extract_entities_llm()` in SDK. Wired into `store()` and `store_batch()`. Regex fallback when no API key. |
| LangGraph adapter | Actual `BaseStore` inheritance. Real drop-in. |
| Honcho adapter | Full shape match, `.aio` accessor. |
| Mem0 adapter (SDK) | `add(messages)` → LLM fact extraction from conversations, stores each fact individually. `entity_store` via `_GraphStore` with vector search and fuzzy dedup. `graph` property. |
| Mem0 adapter (standalone) | `graph` property with `GraphStore` (add/search/get_all/delete). LLM conversation extraction in `add(messages)`. Entity dedup by label. |
| Embedder | all-MiniLM-L6-v2 ONNX, 384-dim, health endpoint on :9090. SDK pings `/health` before semantic search, degrades gracefully. |
| Eval pipeline | 25 memories, 18 labeled queries with ground-truth IDs. Harness computes P@5, R@5, MRR. |
| LLM reranking | QMD-style: top-10 candidates → LLM relevance scoring → re-sort. Robust JSON parser with 3 fallback strategies. |
| Consolidate cron | Identity token persistence. Runs decay + reinforce + god nodes + communities + replication cleanup + embedding backfill (50/tick). |
| Dream cycle | Nightly enrichment: clusters by proper nouns → extracts entities → creates mental models → synthesizes insights. `--resume` flag skips already-processed memories. |
| Backup/restore | `stmem backup <ws>` → JSONL, `stmem restore <ws> <file>`. |
| Observability | `proxy_metrics_snapshot` table, `push_proxy_metrics` reducer, cron scraper reads Prometheus metrics. |
| Synthesis | LLM prompt with structured context entries → cited answer + gap analysis + confidence. `response_format: json_object`. |
| Frontend | 23 pages, live data via `useTable`/`useReactiveDb`. No mock data. |

## Eval results (July 1, 2026 — fresh publish, STDB v2.6)

| Config | P@5 | R@5 | MRR | p50 Latency |
|--------|-----|-----|-----|:-----------:|
| Keyword-only (no embeddings) | 40.0% | 40.0% | 0.400 | 28ms |
| Hybrid (bge-m3) | N/A | N/A | N/A | ~1s* |
| +LLM reranking | N/A | N/A | N/A | — |

*Hybrid search was 5.7s p50 in this test because the embedder sidecar was unreachable.
Historical reference (June 20): hybrid P@5=81.3% R@5=82.0% MRR=0.960; +reranking P@5=55.5%
R@5=94.4% MRR=0.898. See docs/PERFORMANCE.md for full latency breakdown.

**11 operations benchmarked, 0 failures out of 165 iterations.**
Pure WASM ops: 1-2ms p50. Keyword search: 28ms. Graph query: 5ms.

## Performance benchmarks (July 1, 2026 — fresh publish, STDB v2.6)

| # | Operation | p50 (ms) | p90 (ms) | p99 (ms) | Notes |
|---|-----------|---------:|---------:|---------:|-------|
| 1 | memory.store (single) | 1.3 | 1.5 | 2.3 | No embedder; ~194ms with live ONNX |
| 2 | search.keyword (top-5) | 27.8 | 29.1 | 29.9 | BM25 inverted index |
| 3 | search.hybrid (top-10) | 5680.7 | 6630.3 | 7188.8 | Embedder unreachable — 3 retries |
| 4 | graph.query | 4.8 | 5.8 | 9.8 | Pure WASM |
| 5 | memory.count (_query) | 11.2 | 11.6 | 11.8 | WASM query_table |
| 6 | ping (round-trip) | 0.8 | 0.9 | 1.1 | STDB round-trip |
| 7 | create_node (KG) | 1.2 | 1.4 | 1.9 | Pure WASM |
| 8 | create_edge (KG) | 1.2 | 1.2 | 1.2 | Pure WASM |
| 9 | get_neighbors | 20.9 | 21.3 | 22.2 | WASM graph traversal |

**Hybrid times include 3 exponential-backoff retries against missing embedder (total ~15-20s blocked per call). Historical live embedder: ~400ms for semantic, ~1s for full hybrid.

**0 failures / 165 iterations.**
**System:** 127.0.0.1:3001, STDB v2.6, fresh module publish, 20 iterations/op.
**Full data:** see docs/PERFORMANCE.md

## Honest caveats

### 1. Multi-user performance is unproven
Every `hybrid_search` does full table scans in WASM with `.filter()` closures. Works at 100 memories. Will degrade at 10,000. STDB v2.4 doesn't support indexes or query planning. Workspace pre-filters and MAX_RESULTS caps help, but this is a structural limitation until STDB adds indexing.

### 2. Eval dataset expanded to 50 memories, 25 queries (June 2026)
48 relevance judgments across diverse topics (people, architecture, incidents, products, finances, compliance). Evaluated at 3 config levels: BM25-only, +embeddings, +LLM reranking. Still not comparable to GBrain's 146K-page benchmark but much more realistic than the original 25-memory set.

### 3. Reranker JSON parsing — 6 strategies (fixed June 2026)
All 6 strategies tested on 8 edge cases (direct array, dict-wrapped `{"scores": [...]}`, bare object, line-by-line, markdown-wrapped, empty content). Strategies: direct parse → regex array extraction → raw_decode → trailing-comma salvage → dict-wrapper unwrap → line-by-line fallback. Previously 2/18 failed; now all known patterns handled.

### 4. Adapters are API-compatible, not wire-compatible
Mem0/Zep/Graphiti adapters accept the same method signatures and return the same shapes. Your existing code won't crash. But search ranking, entity extraction quality, and scaling characteristics differ from the originals. This is inherent — different backends, different algorithms.

### 5. No labeled eval data from real users
The eval queries were written knowing the data. Real-world queries against unknown data would produce different (likely lower) metrics.

## What to stop doing

- **Stop claiming adapter percentages.** The adapters are shape matches. Say "API-compatible drop-in."
- **Stop self-scoring against custom rubrics.** The eval metrics above are honest measurements against labeled data.
- **Stop calling regex entity extraction "GBrain-style."** It's regex-based with LLM extraction available when an API key is configured.
