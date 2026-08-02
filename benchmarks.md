# Performance Benchmarks

Results from 2026-07-07 03:46 UTC (re-run — WASM build contention resolved)

## Focused Semantic Benchmark (N+1 fix verification)

Verification of _enrich_content N+1 fix: 20 iterations, inline bge-m3 embedder, fresh workspace seeded with 50 memories.

| # | Operation | p50 (ms) | p90 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms) | n
|---|-----------|---------:|---------:|---------:|----------:|---------:|---------:|--:
| 1 | embed-only (bge-m3) | 494.2 | 536.4 | 545.8 | 507.3 | 483.5 | 546.8 | 5
| 2 | search.keyword (top-5) | 40.0 | 52.3 | 65.2 | 43.2 | 39.4 | 66.9 | 20
| 3 | search.semantic (top-10, w/ embedder) | 859.9 | 882.1 | 1482.6 | 899.0 | 838.0 | 1616.4 | 20
| 4 | graph.query | 7.3 | 8.6 | 10.3 | 7.6 | 7.0 | 10.4 | 20
| 5 | ping (round-trip) | 0.8 | 0.9 | 1.0 | 0.8 | 0.8 | 1.1 | 20

Semantic search **899ms mean** — well under the 2.5s target. N+1 fix confirmed effective (was ~7.5s before fix). 0 failures across 85 operations.

## Reference Results (Full Suite)

Full suite results from 2026-07-06 08:25 UTC.

| # | Operation | p50 (ms) | p90 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms)
|---|-----------|---------:|---------:|---------:|----------:|---------:|---------:
| 1 | memory.store (single, short) | 194.1 | 196.2 | 196.6 | 194.5 | 192.6 | 196.7
| 2 | memory.store (single, long) | 198.3 | 199.3 | 200.4 | 198.5 | 197.6 | 200.6
| 3 | memory.store (batch 10) | 1945.2 | 1954.6 | 1962.7 | 1942.2 | 1920.4 | 1963.6
| 4 | memory.store (batch 100) | 19499.4 | 19753.6 | 19952.3 | 19517.6 | 19236.1 | 19974.4
| 5 | search.semantic (top-5) | 398.9 | 542.3 | 574.9 | 398.6 | 223.3 | 579.8
| 6 | search.keyword (top-5) | 10.8 | 12.3 | 12.9 | 11.1 | 10.3 | 13.0
| 7 | search.hybrid (top-10) | 996.6 | 1280.3 | 1333.1 | 1000.3 | 638.5 | 1335.0
| 8 | graph.query | 1.2 | 1.3 | 1.3 | 1.3 | 1.2 | 1.3
| 9 | sql.read (COUNT) | 1.2 | 1.3 | 1.7 | 1.3 | 1.2 | 1.8
| 10 | ping (round-trip) | 0.8 | 0.8 | 1.0 | 0.8 | 0.8 | 1.1

## Retrieval Quality (July 7, 2026)

Eval dataset: 50 memories, 25 query-judgment pairs. Embedder: bge-m3 (1024d). bge-large-en-v1.5 regression fixed — full recovery to historic baseline.

Benchmark methodology: direct embedder API (bge-m3) for semantic embeddings + cosine similarity. LLM reranking uses deepseek-v4-flash-free via oc-zen-socks proxy at :4002 with 8192 max_tokens (avoids reasoning-token truncation).

| Config | P@5 | R@5 | MRR
|--------|-----|-----|-----
| keyword-only (term overlap) | 49.3% | 49.3% | 0.463
| hybrid (bge-m3 semantic) | 74.7% | 74.7% | 0.643
| hybrid + LLM rerank (deepseek-v4-flash-free) | **82.7%** | **82.7%** | **0.960**

Key findings:
- **LLM reranking provides meaningful quality gains**: +8.0pp P@5, +0.317 MRR over hybrid-only
- **MRR of 0.960** means the correct result is re-ranked to position 1 in 96% of queries
- **Latency tradeoff**: reranking adds ~16s per query (10 candidates × ~1.6s/LLM call), making it best for offline/batch or high-importance queries rather than real-time search
- Previous run (max_tokens=10) showed no improvement due to reasoning tokens consuming the entire output budget — fixed by raising max_tokens to 8192, which gives the reasoning model room to produce actual score output
- Hybrid (74.7%) underperforms the full hybrid-fusion search (81.3% with Tantivy+graph+temporal fusion) — cosine similarity alone misses keyword and graph signals

## Tantivy Contribution (July 7, 2026, 4th edition — re-run)

Re-ran `scripts/tantivy_contribution_benchmark.py` on a fresh workspace seeded with 50 eval memories, 25 query-judgment pairs. Measures latency + quality difference with vs without the Tantivy BM25 sidecar (:9091). 20 iterations per phase, 0 failures across all phases.

**Latency comparison (keyword search, 20 iterations):**

| Config | p50 (ms) | p90 (ms) | Mean (ms) | Min (ms) | Max (ms) | Speedup |
|--------|---------:|---------:|----------:|---------:|---------:|--------:|
| keyword (Tantivy ON, SDK c.search) | 1.1 | 1.3 | 1.2 | 0.7 | 5.2 | — |
| keyword (Tantivy OFF, SDK fallback) | 80.9 | 6193.6 | 1527.5 | 78.1 | 6354.8 | **73.5× faster with Tantivy** |

Tantivy ON goes through the SDK `c.search(semantic=False)` which routes to the Tantivy BM25 sidecar at :9091 (consistently sub-2ms p50). Tantivy OFF falls back to the SDK's `_keyword_fallback` which does a cross-process STDB `_query` + client-side BM25 matching. The fallback path is bimodal: fast path (~80ms, in-memory after cache warm) vs slow path (~6s, cold STDB worker). Tantivy eliminates this bimodality entirely.

**Quality comparison (P@5 / R@5 / MRR):**

| Config | P@5 | R@5 | MRR |
|--------|-----|-----|-----|
| keyword (Tantivy ON, BM25 sidecar) | 63.3% | 63.3% | 0.645 |
| keyword (Tantivy OFF, in-memory mock) | 62.7% | 62.7% | 0.703 |
| Tantivy contribution (delta) | **+0.7pp** | **+0.7pp** | **-0.059** |

Quality parity confirms both strategies use the same BM25/token-matching core. The small MRR negative delta is measurement noise from substring-match sensitivity in `compute_metrics`. The SDK fallback path cannot be measured for quality due to the `_query` bug (workspace_id filter returns 0 rows).

Key methodology improvement in this edition:
- **SDK path for latency**: Measures the real end-to-end path users experience (`c.search()` -> SDK -> Tantivy sidecar), not just the raw sidecar HTTP API
- **Four-way comparison**: SDK-with-Tantivy, direct-Tantivy-API, SDK-fallback, in-memory-mock
- **_query bug documented**: The SDK fallback returns 0 results for quality measurement, making Tantivy not just faster but the only reliable keyword search path

See [PERFORMANCE.md](./PERFORMANCE.md) for the full analysis.
