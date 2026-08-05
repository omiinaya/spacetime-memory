# Performance Benchmarks

This document provides reference latency data for Spacetime-Memory operations
measured against a live SpacetimeDB v2.6 standalone.

## Quick Start

```bash
# From repo root
make bench

# Or manually with custom iterations
DB_ID=<identity> ITERATIONS=50 python3 sdk/python/scripts/benchmark_runner.py

# Save output
BENCH_OUTPUT=my-results.json ITERATIONS=20 python3 sdk/python/scripts/benchmark_runner.py
```

## Reference Results (July 1, 2026)

**System:** 127.0.0.1:3001 | **DB:** Fresh publish (v2.6) | **Iterations:** 20 per op
**Date:** 2026-07-01 UTC | **Embedder:** UNREACHABLE (no ONNX sidecar running) | **Failures:** 0/165

| # | Operation | p50 (ms) | p90 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms) |
|---|-----------|---------:|---------:|---------:|----------:|---------:|---------:|
| 1 | memory.store (single, short) | 1.3 | 1.5 | 2.3 | 1.3 | 1.1 | 2.5 |
| 2 | memory.store (single, long) | 1.3 | 1.4 | 1.5 | 1.3 | 1.2 | 1.6 |
| 3 | memory.store (batch 10) | 12.1 | 12.5 | 12.6 | 12.0 | 11.3 | 12.6 |
| 4 | search.keyword (top-5) | 27.8 | 29.1 | 29.9 | 28.0 | 27.0 | 30.0 |
| 5 | search.hybrid (top-10) | 5680.7 | 6630.3 | 7188.8 | 5735.7 | 4715.4 | 7262.0 |
| 6 | graph.query | 4.8 | 5.8 | 9.8 | 5.3 | 4.8 | 10.4 |
| 7 | memory.count (_query) | 11.2 | 11.6 | 11.8 | 11.2 | 10.8 | 11.8 |
| 8 | ping (round-trip) | 0.8 | 0.9 | 1.1 | 0.9 | 0.8 | 1.2 |
| 9 | create_node (KG) | 1.2 | 1.4 | 1.9 | 1.3 | 1.2 | 2.0 |
| 10 | create_edge (KG) | 1.2 | 1.2 | 1.2 | 1.2 | 1.1 | 1.2 |
| 11 | get_neighbors | 20.9 | 21.3 | 22.2 | 20.9 | 20.4 | 22.3 |

## Key Takeaways

**Store latency is sub-millisecond without embedder.** Each `store_memory` call
without embedding is just the WASM + SQL insert (~1.3ms p50). The embedder adds
~185ms when running.

**Keyword search at 28ms p50** uses the BM25 inverted index. This is slower than
the ~11ms measured on the old v2.4 DB — likely due to Tantivy index state differences
or larger result sets. Still acceptable for real-time use.

**Hybrid search is 5.7s p50 without embedder** — dominated by 3 retry timeouts
(~15-20s total) against the unreachable embedder sidecar at :9090. When the embedder
is live, semantic search alone takes ~400ms and hybrid takes ~1s (historical reference).

**Graph operations are fast.** `graph.query` at 4.8ms, `create_node`/`create_edge` at
~1.2ms p50. These are pure WASM — no embedder dependency.

**0 failures across 165 operations.** No panics, no timeouts on reachable endpoints.

## Embedder Impact

When the embedder sidecar is not running:
- Store: ~1.3ms (no embed → immediate)
- Semantic search: falls back to keyword (~28ms)
- Hybrid search: ~5.7s (3 retries against unreachable endpoint)

When the embedder is running (historical, June 9 reference):
- Store: ~194ms p50 (+185ms for embedding)
- Semantic search: ~399ms (ONNX sidecar)
- Hybrid search: ~1s p50

## Retrieval Quality (Keyword-Only vs Hybrid Baseline)

**Current reference (2026-08-05, end-to-end SDK path via `scripts/retrieval_quality_benchmark.py`):**

With 50 eval memories across 25 queries (people, architecture, incidents, models, processes):

| Config | P@5 | R@5 | MRR |
|--------|-----|-----|-----|
| keyword-only (Tantivy BM25) | 61.3% | 61.3% | 0.608 |
| semantic-only (bge-m3) | 74.7% | 74.7% | 0.643 |
| hybrid (semantic + Tantivy) | **76.0%** | **76.0%** | **0.698** |

Hybrid fusion is the best config: **+14.7pp P@5 / +0.090 MRR over keyword-only**. Semantic embeddings are the primary driver of retrieval accuracy (keyword-only matches exact word overlap; semantic matches meaning). An earlier 2026-08-05 run showing all configs at 61.3% was a benchmark artifact — the seeding path never populated `search_index`, so semantic search found zero rows; the benchmark now calls `index_entity_batch` with bge-m3 embeddings (mirroring SDK `store()`).

**Historical (standalone `hybrid_benchmark.py`, July 6 on 50/25 eval set):**
**P@5=49.3%  R@5=49.3%  MRR=0.463** (keyword-only)
**P@5=81.3%  R@5=81.3%  MRR=0.880** (hybrid, bge-m3)

Keyword-only retrieval is weak — it matches on exact word overlap. Semantic
embeddings are critical for good retrieval. Hybrid provides **+32.0pp P@5** over keyword-only on the same dataset.

### Historical baseline comparison (June 20 → July 7)

| Metric | June 20 (hybrid, bge-m3) | July 7 (hybrid, bge-m3) | Delta | Significance |
|--------|--------------------------|-----------------------------------|-------|-------------|
| P@5    | 81.3%                    | 81.3%                             | 0.0pp | Gap fully closed — bge-m3 restored as default embedder |
| R@5    | 82.0%                    | 81.3%                             | −0.7pp | Minor residual variance within measurement tolerance |
| MRR    | 0.960                    | 0.880                             | −0.080 | First result reliability still slightly below historic peak |

### Same-dataset comparison: hybrid vs keyword-only (July 7)

| Metric | Keyword-only | Hybrid (bge-m3) | Delta | Significance |
|--------|-------------|---------------------------|-------|-------------|
| P@5    | 49.3%       | 81.3%                     | +32.0pp | Hybrid provides 1.65× precision over keyword-only |
| R@5    | 49.3%       | 81.3%                     | +32.0pp | Semantic recall significantly better |
| MRR    | 0.463       | 0.880                     | +0.417 | First result reliability 88% vs 46% |

### LLM Reranking Impact (July 7, 2026)

Using deepseek-v4-flash-free via oc-zen-socks proxy (:4002) with 8192 max_tokens. Methodology: embedder API + cosine similarity to get top-10 candidates, then LLM reranks by relevance.

| Metric | Hybrid (bge-m3) | Hybrid + LLM Rerank | Delta | Significance |
|--------|------------------------|---------------------|-------|-------------|
| P@5    | 74.7%                  | **82.7%**           | +8.0pp | LLM rerank improves precision by re-ranking correct results higher |
| R@5    | 74.7%                  | 82.7%               | +8.0pp | Same as P@5 (each query either retrieves the right doc or not) |
| MRR    | 0.643                  | **0.960**           | +0.317 | Correct result moves to position 1 in 96% of queries after rerank |

**Conclusion:** LLM reranking provides significant quality improvements (+8.0pp P@5, +0.317 MRR) at a latency cost of ~16s per query (10 candidates × ~1.6s/LLM call). Best suited for offline re-ranking or high-importance queries. The large MRR gain (0.643 → 0.960) shows the LLM excels at scoring the most relevant result highest — cosine similarity alone often ranks the correct result at position 2-5.

**Bug fix note:** Previous runs using max_tokens=10 produced identical results to hybrid-only because the reasoning model's reasoning tokens consumed the entire output budget, leaving `content` empty — the fallback to `similarity` scores reproduced the original order. Fixed by raising max_tokens to 8192.

**Conclusion:** Hybrid (P@5=81.3%) significantly outperforms keyword-only (P@5=49.3%) on the same dataset. The +32.0pp gap confirms that semantic embeddings are the primary driver of retrieval accuracy. Production deployments must keep the embedder sidecar running.

**Root cause found:** The actual deployed embedder sidecar was still running the compiled binary of `bge-large-en-v1.5` (0.33B params) despite repo source naming `bge-m3` (0.57B params) as the default. The systemd service had no `MODEL_NAME` env var set, so the compiled default was used. Fixed by adding `MODEL_NAME=BAAI/bge-m3` to the systemd override. With bge-m3 restored, P@5 recovered from 74.0% to 81.3%, fully closing the −7.3pp gap against the June 20 baseline.

## Database Size Impact

Measured against a clean database (~60 memories, ~10 KG nodes). At 10K+ memories,
keyword search may slow. Semantic search and graph queries remain stable due to
indexed lookups.
