# Performance Benchmarks

**Generated:** 2026-07-01 04:12 UTC
**Host:** 127.0.0.1:3001
**DB:** `c200199768b8fc59738604c1b9e9dbbf89014d2f39a8993f5836f194f5dfe68b`
**Iterations:** 20 per op (3 for semantic — expensive)
**Workspace:** `bench-ws-1` (50 seeded memories + 10 KG nodes + 8 eval memories)
**Sidecars:** Tantivy BM25 (:9091), ONNX embedder bge-large-en-v1.5 (:9090)
**Failures:** 0/148 (0.0%)

## Results

| # | Operation | p50 (ms) | p90 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms) |
|---|-----------|---------:|---------:|---------:|----------:|---------:|---------:|
| 1 | memory.store (single, short) | 1.2 | 1.4 | 2.0 | 1.3 | 1.1 | 2.0 |
| 2 | memory.store (single, long) | 1.2 | 1.4 | 8.8 | 1.7 | 1.1 | 10.5 |
| 3 | memory.store (batch 10) | 11.8 | 13.1 | 14.9 | 12.3 | 11.4 | 15.1 |
| 4 | search.keyword (top-5) | 122.5 | 127.0 | 150.7 | 124.3 | 119.4 | 155.9 |
| 5 | search.semantic (top-5, w/ embedder) | 2529.4 | 2530.1 | 2530.3 | 2486.8 | 2400.8 | 2530.3 |
| 6 | graph.query | 33.7 | 34.5 | 46.4 | 33.3 | 29.4 | 49.2 |
| 7 | memory.count (_query) | 38.5 | 39.6 | 40.1 | 38.2 | 35.5 | 40.1 |
| 8 | ping (round-trip) | 1.2 | 1.3 | 1.3 | 1.2 | 1.2 | 1.3 |
| 9 | create_node (KG) | 523.2 | 554.9 | 556.6 | 517.6 | 465.6 | 556.8 |
| 10 | create_edge (KG) | 1.2 | 1.4 | 1.5 | 1.2 | 1.1 | 1.5 |
| 11 | get_neighbors | 189.0 | 210.1 | 216.2 | 193.9 | 186.3 | 216.9 |

## Analysis

- **Store is pure WASM** (<2ms) — no embedder cost like the old benchmark (194ms, which was embedding-bound). The `_call("store_memory", ...)` doesn't embed.
- **Semantic search** dropped from **7.5s → 2.5s** with the N+1 fix in `_enrich_content`. Breakdown:
  - Embed query (0.4s) — bge-large-en-v1.5 at :9090
  - hybrid_search reducer (1.5s) — WASM BM25 + graph + temporal search
  - SQL read + Tantivy + fusion (0.2s)
  - Content enrichment (0.4s) — single batch confidence query
- **Keyword search** (122ms) — client-side BM25 fallback over STDB. Tantivy sidecar is fast (1ms) but the benchmark bypasses it by using `_call("store_memory", ...)`.
- **Graph operations** — edges are fast (1.2ms), nodes are slow (523ms) because `create_node` includes entity extraction.
- **Ping** (1.2ms) — STDB HTTP round-trip.

## Retrieval Quality (keyword-only, no semantic embeddings)

| Config | P@5 | R@5 | MRR |
|--------|-----|-----|-----|
| keyword-only (no embeddings) | 40.0% | 40.0% | 0.400 |

## Recommendations

1. **For faster semantic search**: The remaining bottleneck is the 1.5s WASM `hybrid_search` reducer. A keyword-only index in Tantivy with the search done client-side would bypass this entirely.
2. **For Tantivy integration**: Ensure `c.store()` is called instead of `_call("store_memory", ...)` — Tantivy indexing happens in `c.store()` and is transparent.
3. **For embedder**: bge-large-en-v1.5 (1024-dim) at :9090 works well. 250ms per embedding. No issues.
4. **Batch stores**: Currently N sequential reducer calls. A `store_batch` reducer on the Rust side would cut overhead.
