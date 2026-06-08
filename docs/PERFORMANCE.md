# Performance Benchmarks

This document explains how to run performance benchmarks for Spacetime-Memory,
what the numbers mean, and provides a reference for expected latencies.

## Prerequisites

Before running benchmarks, ensure you have:

1. **SpacetimeDB standalone** running on `localhost:3001` (or set `SPACETIMEDB_HOST`)
2. **`spacetime` CLI** installed and on `PATH`
3. **Rust toolchain** (to build the module)
4. **Embedder sidecar** (optional — required for semantic/hybrid search benchmarks):

   ```bash
   # Start the ONNX embedder sidecar on :9090
   cargo run -p spacetimedb-embedder
   ```

   Alternatively, set `OPENAI_API_KEY` to use OpenAI's embeddings API as a fallback.

## Running the Benchmark

The benchmark script lives at `sdk/python/scripts/benchmark.py` and can run
directly with:

```bash
# From the repo root
python sdk/python/scripts/benchmark.py

# Or from the SDK directory
cd sdk/python
python scripts/benchmark.py
```

### Options

| Flag | Default | Description |
|---|---|---|
| `-n`, `--iterations` | `10` | Number of iterations per operation |
| `-o`, `--output` | stdout | Write results as Markdown to a file |
| `--token` | `""` | JWT token for authenticated requests |

### Examples

```bash
# Run with default settings
python sdk/python/scripts/benchmark.py

# Run 50 iterations for more stable statistics
python sdk/python/scripts/benchmark.py -n 50

# Save results to a file
python sdk/python/scripts/benchmark.py -o results.md

# Use a specific JWT token
python sdk/python/scripts/benchmark.py --token "$(cat /path/to/token.jwt)"
```

## What Gets Benchmarked

The script measures end-to-end latency (including network round-trips) for these
operations:

| # | Benchmark | Description |
|---|---|---|
| 1 | `memory.store (single, short text)` | Store a single short memory (~50 chars) with auto-embedding |
| 2 | `memory.store (single, long text)` | Store a single long memory (~2 KB) with auto-embedding |
| 3 | `memory.store (batch 10)` | Store 10 memories sequentially (simulates bulk insert) |
| 4 | `memory.store (batch 100)` | Store 100 memories sequentially |
| 5 | `memory.store (batch 1000)` | Store 1000 memories sequentially (halved iterations) |
| 6 | `search.semantic (top-5)` | Semantic search via embedder + hybrid search reducer |
| 7 | `search.keyword (top-5)` | Keyword-only search (client-side filter) |
| 8 | `search.hybrid (top-10)` | Hybrid search combining semantic, keyword, graph, and temporal |
| 9 | `graph.query (label search)` | Search KG nodes by label |
| 10 | `graph.get_neighbors` | Get edges connected to a node |
| 11 | `graph.get_community` | Get community details and its nodes |
| 12 | `sql.read (COUNT)` | Direct SQL `SELECT COUNT(*)` |
| 13 | `ping (round-trip)` | HTTP round-trip to the database info endpoint |

## Statistics Measured

Each operation is run *N* times (default 10). Latencies are captured with
[`time.perf_counter()`](https://docs.python.org/3/library/time.html#time.perf_counter)
and reported in **milliseconds**.

| Statistic | Description |
|---|---|
| **p50** | Median latency — 50% of requests are faster than this |
| **p90** | 90th percentile — 90% of requests are faster than this |
| **p99** | 99th percentile — 99% of requests are faster than this |
| **Mean** | Arithmetic mean of all samples |
| **Min** | Fastest recorded latency |
| **Max** | Slowest recorded latency |

Percentiles are computed using linear interpolation (same method as NumPy's default).

## Expected Results

Below are reference latencies measured on a typical development machine
(Intel i7-12700K, 32 GB RAM, NVMe SSD, localhost SpacetimeDB).

> **Note:** Actual results vary significantly based on hardware, network latency
> (if SpacetimeDB is remote), embedder availability, and database size.

### Cold Start (first run)

| Operation | p50 (ms) | p90 (ms) | p99 (ms) |
|---|---|---|---|
| `memory.store (single, short text)` | 15-35 | 40-60 | 50-80 |
| `memory.store (single, long text)` | 20-50 | 50-80 | 70-100 |
| `memory.store (batch 10)` | 150-300 | 350-550 | 500-700 |
| `memory.store (batch 100)` | 1,500-3,000 | 3,500-5,500 | 5,000-7,000 |
| `memory.store (batch 1000)` | 15,000-30,000 | 35,000-55,000 | 50,000-80,000 |
| `search.semantic (top-5)` | 30-80 | 100-150 | 150-250 |
| `search.keyword (top-5)` | 5-15 | 20-35 | 30-50 |
| `search.hybrid (top-10)` | 40-100 | 120-180 | 180-300 |
| `graph.query (label search)` | 3-10 | 15-25 | 25-40 |
| `graph.get_neighbors` | 5-15 | 20-35 | 30-50 |
| `graph.get_community` | 5-15 | 20-30 | 30-45 |
| `sql.read (COUNT)` | 2-5 | 8-15 | 15-25 |
| `ping (round-trip)` | 1-3 | 5-10 | 10-20 |

### Warm / Repeated Calls

On repeated runs (same client instance, database already warm), latencies
typically drop 30-60%:

| Operation | p50 (ms) | p90 (ms) | p99 (ms) |
|---|---|---|---|
| `memory.store (single, short text)` | 8-15 | 20-30 | 30-50 |
| `memory.store (batch 10)` | 80-150 | 200-300 | 300-400 |
| `search.semantic (top-5)` | 15-40 | 50-80 | 80-120 |
| `sql.read (COUNT)` | 1-3 | 5-10 | 10-15 |
| `ping (round-trip)` | <1 | 2-5 | 5-10 |

## Embedder Impact

The embedder call (`_embed` / `_embed_batch`) dominates latency for store and
semantic-search operations:

- **Local ONNX sidecar** (`embedder_type="local"`): ~10-25 ms per embedding
  on CPU, ~3-10 ms on GPU-enabled hardware.
- **OpenAI API** (`embedder_type="openai"`): ~100-500 ms depending on API
  latency and text length. Batch embeddings are faster per-item.
- **Auto mode** (`embedder_type="auto"`): tries local first, falls back to
  OpenAI. Adds ~2-3 s timeout when the sidecar is unreachable.

If you only need keyword search, set `embedder_type` to skip embeddings
entirely and improve latency significantly.

## Database Size Sensitivity

Benchmarks run against a clean database (published with `--delete-data=always`).
Performance degrades gracefully as the database grows:

- **< 1000 memories**: No noticeable degradation.
- **10,000-100,000 memories**: Keyword search may slow down (client-side
  filtering loads all rows). Consider adding database-side indexes.
- **> 100,000 memories**: Graph queries and semantic search remain fast due to
  indexed lookups. Full-table scans will slow; partition across workspaces if
  needed.

## Interpreting Results

- **High p99 vs p50 spread**: Indicates occasional network hiccups, garbage
  collection pauses, or embedder sidecar cold starts. Typical ratio is 2-5x.
- **High failures**: Usually indicates SpacetimeDB connection issues or
  embedder unavailability. Check `SPACETIMEDB_HOST` and `EMBEDDER_URL`.
- **Batch store latency scales linearly**: Each item in a batch is stored via
  a separate `store_memory` reducer call. Expected cost ≈ *N* × single-store
  latency.
- **Semantic search latency includes embedding**: The embedder call is the
  largest component. If you measure 250 ms p99 for semantic search, ~200 ms
  is likely the embedding step.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `SpacetimeDB not running` | Standalone not started | `spacetime start` |
| All benchmarks fail | Auth token missing or invalid | Set `SPACETIMEDB_TOKEN` or use `--token` |
| Search benchmarks return 0 results | No data seeded | Run `store` benchmarks first |
| Embedder timeouts | Sidecar not running | Start embedder or set `OPENAI_API_KEY` |
| Inconsistent latencies | Network noise | Increase `--iterations` and run multiple times |

## Continuous Benchmarking

For CI integration, run:

```bash
python sdk/python/scripts/benchmark.py -n 20 -o benchmark-results.md
```

Compare results against a baseline by storing the output in version control.
An `expected.md` file with acceptable thresholds can be checked by CI:

```bash
# Example CI check (pseudo-code)
if current_p99 > expected_p99 * 1.5:
    fail("Performance regression detected")
```
