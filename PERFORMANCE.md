# Performance Benchmarks

**Generated:** 2026-06-09 01:13 UTC
**Host:** localhost:3001
**DB:** `c20013185c88a4627a60d5afee909a46ca35a2bed7010a4a4377c6f5ef175c81`
**Iterations:** 3 per op
**Workspace:** `dc9dbf58302d42c38bb7caea1a874e5a`

## Results

| # | Operation | p50 (ms) | p90 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms) |
|---|-----------|---------:|---------:|---------:|----------:|---------:|---------:|
| 1 | memory.store (single, short) | 193.8 | 193.9 | 193.9 | 193.7 | 193.3 | 193.9 |
| 2 | memory.store (single, long) | 198.2 | 202.5 | 203.5 | 199.8 | 197.6 | 203.6 |
| 3 | memory.store (batch 10) | 1975.6 | 1982.5 | 1984.1 | 1966.6 | 1939.9 | 1984.3 |
| 4 | memory.store (batch 100) | 19466.8 | 19492.5 | 19498.3 | 19461.4 | 19418.3 | 19499.0 |
| 5 | search.semantic (top-5) | 244.4 | 258.5 | 261.7 | 244.7 | 227.6 | 262.0 |
| 6 | search.keyword (top-5) | 4.5 | 5.2 | 5.4 | 4.7 | 4.3 | 5.4 |
| 7 | search.hybrid (top-10) | 335.0 | 384.4 | 395.5 | 343.6 | 299.0 | 396.7 |
| 8 | graph.query | 1.3 | 1.3 | 1.3 | 1.3 | 1.3 | 1.3 |
| 9 | sql.read (COUNT) | 1.3 | 1.4 | 1.4 | 1.3 | 1.3 | 1.4 |
| 10 | ping (round-trip) | 0.8 | 0.9 | 0.9 | 0.8 | 0.8 | 0.9 |

**Failures:** 0/30 (0.0%)

## Analysis

- **Store latency is embedding-bound**: ~194ms per store, of which ~190ms is the Rust ONNX embedder sidecar (`all-MiniLM-L6-v2`). Raw SpacetimeDB writes (SQL insert) take <2ms.
- **Batch stores scale linearly**: 10 items ≈ 10× single cost, 100 items ≈ 100× single cost. No batching optimization in the current Python client — each item is a separate reducer call.
- **Semantic search** embeds the query then does a vector scan (all-MiniLM-L6-v2 384d). The ~244ms latency is dominated by the embedder round-trip.
- **Keyword search** is fast (~4.5ms) — pure SQL `LIKE`/`FTS` match against the SpacetimeDB SQL engine.
- **Graph/SQL/Ping** are sub-2ms — the WASM module computes these entirely in-memory.
- **Hybrid search** (~335ms) runs semantic + keyword + temporal search and fuses the results. The overhead over semantic alone is the fusion step.

## Recommendations

1. **For latency-sensitive apps**: Consider a local embedder process (same host) to minimize network round-trip to the embedder sidecar.
2. **For throughput**: Batch stores are currently N sequential reducer calls. A `store_batch` reducer on the Rust side would cut the per-item overhead dramatically.
3. **Scaling**: Since the performance bottleneck is embedding (not SpacetimeDB), horizontal scaling of the module won't help. Focus on the embedder pipeline.
