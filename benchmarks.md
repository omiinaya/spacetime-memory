# Performance Benchmarks

Results from 2026-06-09 00:55 UTC

## Reference Results

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
