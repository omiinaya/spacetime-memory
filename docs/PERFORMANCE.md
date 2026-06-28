# Performance Benchmarks

This document provides reference latency data for Spacetime-Memory operations
measured against a live SpacetimeDB v2.6 standalone with the ONNX embedder
sidecar running on 127.0.0.1:9090.

## Quick Start

```bash
# From repo root
python scripts/quick-bench.py

# With custom iterations and output file
BENCH_ITERATIONS=50 BENCH_OUTPUT=my-results.md python scripts/quick-bench.py
```

See `scripts/README.md` for detailed usage.

## Reference Results

**System:** 127.0.0.1:3001 | **DB:** fresh publish | **Iterations:** 20 per op
**Date:** 2026-06-09 00:55 UTC | **Embedder:** all-MiniLM-L6-v2 (ONNX sidecar) | **Failures:** 0/180

| # | Operation | p50 (ms) | p90 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms) |
|---|-----------|---------:|---------:|---------:|----------:|---------:|---------:|
| 1 | memory.store (single, short) | 194.1 | 196.2 | 196.6 | 194.5 | 192.6 | 196.7 |
| 2 | memory.store (single, long) | 198.3 | 199.3 | 200.4 | 198.5 | 197.6 | 200.6 |
| 3 | memory.store (batch 10) | 1945.2 | 1954.6 | 1962.7 | 1942.2 | 1920.4 | 1963.6 |
| 4 | memory.store (batch 100) | 19499.4 | 19753.6 | 19952.3 | 19517.6 | 19236.1 | 19974.4 |
| 5 | search.semantic (top-5) | 398.9 | 542.3 | 574.9 | 398.6 | 223.3 | 579.8 |
| 6 | search.keyword (top-5) | 10.8 | 12.3 | 12.9 | 11.1 | 10.3 | 13.0 |
| 7 | search.hybrid (top-10) | 996.6 | 1280.3 | 1333.1 | 1000.3 | 638.5 | 1335.0 |
| 8 | graph.query | 1.2 | 1.3 | 1.3 | 1.3 | 1.2 | 1.3 |
| 9 | sql.read (COUNT) | 1.2 | 1.3 | 1.7 | 1.3 | 1.2 | 1.8 |
| 10 | ping (round-trip) | 0.8 | 0.8 | 1.0 | 0.8 | 0.8 | 1.1 |

## Key Takeaways

**Store latency is dominated by embedding.** Each `store_memory` call sends the
content to the embedder sidecar (ONNX all-MiniLM-L6-v2, HTTP localhost). The
embedding adds ~185ms per call. The reducer itself (WASM → SQL insert) takes
~8-12ms. Batch store scales linearly because each item is stored independently.

**Raw SQL and graph queries are fast.** Under 2ms p99 for `COUNT(*)`,
`graph.query`, and `ping`. These operations bypass the embedder entirely.

**Hybrid search is expensive.** At ~1s p50, it runs semantic search (embedder)
+ BM25 keyword (client-side) + temporal query + graph cross-referencing. The
semantic component accounts for ~400ms of that.

**Keyword search is 40x cheaper than semantic.** At ~11ms vs ~400ms, use
`semantic=False` when you just need exact matches.

## Embedder Impact

When the embedder sidecar is not running, operations fall back exponentially:
- Store: ~8-12ms (no embed → immediate)
- Semantic search: falls back to keyword (~11ms)
- Hybrid search: ~15ms (no semantic component)

## Database Size Impact

Measured against a clean database. At 10K+ memories, keyword search may slow
(client-side filtering loads all rows). Semantic search and graph queries
remain stable due to indexed lookups.
