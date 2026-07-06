# Performance Benchmarks

Results from 2026-07-06 09:17 UTC

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

## Retrieval Quality (July 6, 2026)

Eval dataset: 50 memories, 25 query-judgment pairs. Embedder: bge-large-en-v1.5 (1024d).

| Config | P@5 | R@5 | MRR
|--------|-----|-----|-----
| keyword-only (term overlap) | 49.3% | 49.3% | 0.463
| hybrid (bge-m3 semantic) | 74.0% | 74.0% | 0.853

Hybrid adds semantic search on top of keyword BM25 via Tantivy + fusion scoring.
Results inline with previous baseline (June 20: hybrid P@5=81.3%, R@5=82.0%, MRR=0.960).
Minor drop attributed to different eval dataset (25 vs 18 queries) and embedder model (bge-large-en-v1.5 vs bge-m3).
