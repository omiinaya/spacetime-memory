# Performance Benchmarks

This document provides reference latency data for Spacetime-Memory operations
measured against a live SpacetimeDB v2.6 standalone.

## Quick Start

```bash
# From repo root — publish module first
spacetime publish spacetime-memory -p server/spacetimedb/ --yes

# Run benchmarks
SPACETIMEDB_DB=$(spacetime list | grep spacetime-memory | awk '{print $NF}') make bench
```

## Reference Results

**System:** 127.0.0.1:3001 | **DB:** fresh publish (`c2001997...`)
**Date:** 2026-07-01 02:02 UTC | **Embedder:** N/A (not running) | **Iterations:** 10 per op

| # | Operation | p50 (ms) | p90 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms) | Fails |
|---|-----------|---------:|---------:|---------:|----------:|---------:|---------:|------:|
| 1 | memory.store (single, short) | 2.5 | 2.8 | 2.9 | 2.3 | 1.6 | 2.9 | 0 |
| 2 | memory.store (single, long) | 2.4 | 3.1 | 3.3 | 2.5 | 1.6 | 3.3 | 0 |
| 3 | memory.store (batch 10) | 20.5 | 22.7 | 23.8 | 20.6 | 18.3 | 23.9 | 0 |
| 4 | memory.store (batch 100) | 219.7 | 240.7 | 245.8 | 219.8 | 191.0 | 246.3 | 0 |
| 5 | search.keyword (top-5) | 52.4 | 74.5 | 109.7 | 58.6 | 38.1 | 113.6 | 0 |
| 6 | search.semantic (top-5) | 11202.8† | 13392.3† | 13427.6† | 10856.3† | 7383.9† | 13431.5† | 0 |
| 7 | search.hybrid (top-10) | 12505.5† | 18707.7† | 26746.1† | 14283.9† | 10590.5† | 27639.2† | 0 |
| 8 | graph.query | 12.7 | 26.0 | 36.2 | 16.5 | 7.7 | 37.3 | 0 |
| 9 | ping (round-trip) | 2.3 | 3.8 | 7.5 | 3.0 | 1.8 | 7.9 | 0 |

† Semantic search includes 3 exponential-backoff retries against the embedder sidecar
(Connection refused on :9090). Real cost with a live embedder is ~400ms, not 11s.

## Key Takeaways

**Store latency is <3ms without embedding.** The reducer itself (WASM → SQL insert)
takes ~2.5ms. Without an embedder sidecar or API key, no embedding is computed.
With live all-MiniLM-L6-v2 ONNX sidecar, previous measurements show ~194ms (185ms
embedding + 9ms reducer).

**Keyword search is ~52ms** for fresh database with <100 memories. Uses BM25
inverted index (term_index table). Will degrade as the index grows — this is the
first operation that needs optimization at scale.

**Semantic search is the expensive path.** At ~400ms with a live embedder (historical
reference), it requires: HTTP call to embedder → WASM query → result fusion.
Without an embedder, the SDK retries 3 times (~11s total) before falling back
to keyword-only.

**Graph queries are fast.** At ~13ms p50, `query_graph` operates entirely in WASM
memory. No external calls, no embedding.

**Ping is ~2.3ms.** Pure STDB round-trip.

## Historical Reference (June 9, 2026)

From the previous benchmark run with all-MiniLM-L6-v2 ONNX sidecar live:

| Operation | p50 (ms) | Note |
|-----------|---------:|------|
| memory.store (single) | 194.1 | Embedding dominates (185ms) |
| search.keyword | 10.8 | Faster than current — smaller index |
| search.semantic | 398.9 | Live embedder, no retries |
| search.hybrid | 996.6 | Full multi-strategy fusion |
| graph.query | 1.2 | Older dataset, smaller graph |
| ping | 0.8 | Different network path |

The ~2x difference on search.keyword and graph.query between June 9 and July 1
reflects: (a) larger default database on the fresh publish (more tables), (b) the
July 1 run was against `127.0.0.1:3001` instead of `localhost:3001`.

## Embedder Impact

| Embedder State | store (ms) | semantic search (ms) |
|----------------|-----------:|---------------------:|
| ONNX sidecar (:9090) | ~194 | ~400 |
| No embedder, no API key | ~2.5 | Falls to keyword (~52ms) |
| OpenAI API key set | ~194 | ~400 (via proxy) |

## Database Size Impact

Measured against a clean database. At 10K+ memories, keyword search may slow
(client-side filtering loads all rows). Semantic search and graph queries
remain stable due to indexed lookups.
