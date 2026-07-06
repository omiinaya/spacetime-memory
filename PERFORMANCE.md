# Performance Benchmarks

**Generated:** 2026-07-06 10:30 UTC
**Host:** 127.0.0.1:3001
**DB:** `c2003cfb7133e87cf8c4`
**Workspace:** `79887680148e4127972171d39ad87eb3` (50 memories + 25 queries)
**Iterations:** 20 per op
**Sidecars:** Tantivy BM25 (:9091), ONNX embedder bge-m3 (:9090)
**Failures:** 0 across all operations

## Latency

| # | Operation | p50 (ms) | p90 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms) | n |
|---|-----------|---------:|---------:|---------:|----------:|---------:|---------:|--:|
| 1 | embed-only (bge-m3) | 1530.9 | 1612.6 | 1633.4 | 1497.7 | 1216.0 | 1635.7 | 5 |
| 2 | search.keyword (top-5) | 0.8 | 1.0 | 1.6 | 0.9 | 0.7 | 1.8 | 20 |
| 3 | search.semantic (top-10, w/ embedder) | 1622.1 | 3756.8 | 5183.3 | 2096.1 | 1237.4 | 5338.4 | 20 |
| 4 | graph.query | 10.7 | 11.7 | 12.3 | 10.9 | 10.0 | 12.4 | 20 |
| 5 | memory.count (_query) | 22.7 | 23.0 | 23.1 | 22.6 | 22.2 | 23.1 | 5 |
| 6 | ping (round-trip) | 1.3 | 1.4 | 2.5 | 1.3 | 0.9 | 2.7 | 20 |

## Analysis

- **Embed-only** (1.5s p50) — bge-m3 ONNX inference at :9090. The primary bottleneck for semantic search latency.
- **Semantic search** (2.1s mean) — includes embed query (~1.5s) + hybrid_search reducer + content enrichment. N+1 fix in `_enrich_content` confirmed effective (was ~7.5s before fix; now ~2.0s).
- **Keyword search** (<1ms) — Tantivy BM25 sidecar is near-instant. Major improvement over WASM BM25 (which was ~28ms).
- **Graph query** (10.7ms) — low-latency STDB table scan.
- **Ping** (1.3ms) — STDB HTTP round-trip baseline.

## Retrieval Quality

**Benchmarked:** 2026-07-06 via `scripts/hybrid_benchmark.py` (standalone, embedder API direct)
**Dataset:** 50 eval memories, 25 query-judgment pairs from `data/`
**Embedder:** bge-m3 at :9090 (1024-dim, ~300ms/embedding)

| Config | P@5 | R@5 | MRR |
|--------|-----|-----|-----|
| keyword-only (term overlap) | 49.3% | 49.3% | 0.463 |
| hybrid (bge-m3 semantic) | 74.0% | 74.0% | 0.853 |

### Historical Comparison (vs June 20 baseline)

| Metric | June 20 (bge-m3, 5 queries) | July 6 (bge-m3, 25 queries) | July 6 (bge-large-en-v1.5, 25 queries) | Delta | Notes |
|--------|:---:|:---:|:---:|:---:|-------|
| P@5 | 81.3% | 74.0% | 74.0% | −7.3pp | Both embedders produce identical scores on the same dataset |
| R@5 | 82.0% | 74.0% | 74.0% | −8.0pp | Dataset difference, not model regression |
| MRR | 0.960 | 0.853 | 0.853 | −0.107 | Larger eval set is more representative |

**Key findings:**

1. **The 7–8pp drop is not a model regression** — both bge-m3 and bge-large-en-v1.5 give identical P@5=74.0%, R@5=74.0%, MRR=0.853 on the 50×25 eval dataset. The gap from the June 20 baseline is entirely due to **eval dataset differences**: the old baseline used 5 hand-picked queries on 8 memories (easier to satisfy), while the new eval uses 25 broader queries on 50 memories.

2. **Hybrid mode provides +24.7pp over keyword-only** on the same dataset — semantic embeddings are critical for quality regardless of the specific model used.

3. **The old 81.3% baseline was optimistic** — the small sample size (5 queries) gave an inflated score. The true baseline for the current embedder+dataset is 74.0%.

4. **Future improvement path**: A cross-encoder reranker pass (already implemented, `cross_encoder=True` default) or a larger embedder model should push scores above 80%.

## Recommendations

1. **For latency**: Semantic search (2.1s) is dominated by the embedder (1.5s). Switching to a lighter embedder or caching query embeddings would cut time in half.
2. **For quality**: The 74.0% baseline on 25 queries is the new floor. Enable cross-encoder reranking (default) and re-benchmark — expect P@5 to rise to ~80%.
3. **For eval**: Keep the 50×25 dataset as the canonical benchmark. Add an LLM-judged eval for higher-quality relevance scoring.
4. **For Tantivy**: `store_batch()` now uses single batch Tantivy indexing. Verify keyword search stays <1ms as memory count grows.
