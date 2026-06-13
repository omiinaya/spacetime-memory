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

## Eval results

| Config | P@5 | R@5 | MRR |
|--------|-----|-----|-----|
| BM25+graph+temporal (no embeddings) | 19.0% | 72.2% | 0.206 |
| + semantic embeddings (all-MiniLM-L6-v2) | 25.6% | 97.2% | 0.549 |
| + LLM reranking (go-deepseek-v4-flash, 10 candidates) | **55.5%** | 94.4% | **0.898** |

Dataset: 25 memories, 18 labeled queries. GBrain reference: P@5=49.1%, R@5=97.9% (146K pages).

## Honest caveats

### 1. Multi-user performance is unproven
Every `hybrid_search` does full table scans in WASM with `.filter()` closures. Works at 100 memories. Will degrade at 10,000. STDB v2.4 doesn't support indexes or query planning. Workspace pre-filters and MAX_RESULTS caps help, but this is a structural limitation until STDB adds indexing.

### 2. Eval dataset is tiny
25 memories, 18 queries. The metrics are directionally correct but not comparable to GBrain's 146K-page benchmark. Need 100+ memories with diverse content for realistic measurement.

### 3. Reranker JSON parsing is 90% reliable
2 out of 18 rerank calls still fail on JSON edge cases (unterminated strings, empty responses). The 3-strategy parser catches most but not all. The failures fall back to fusion scores gracefully.

### 4. Adapters are API-compatible, not wire-compatible
Mem0/Zep/Graphiti adapters accept the same method signatures and return the same shapes. Your existing code won't crash. But search ranking, entity extraction quality, and scaling characteristics differ from the originals. This is inherent — different backends, different algorithms.

### 5. No labeled eval data from real users
The eval queries were written knowing the data. Real-world queries against unknown data would produce different (likely lower) metrics.

## What to stop doing

- **Stop claiming adapter percentages.** The adapters are shape matches. Say "API-compatible drop-in."
- **Stop self-scoring against custom rubrics.** The eval metrics above are honest measurements against labeled data.
- **Stop calling regex entity extraction "GBrain-style."** It's regex-based with LLM extraction available when an API key is configured.
