# Benchmark Results — Baseline (2026-07-18)

## LongMemEval (Split S, 5 Questions)
- Recall@All@5: **100.0%** (5/5)
- Avg latency: 24.6s/question (includes seeding + indexing)
- Model: BAAI/bge-m3
- Reference: Mnemosyne 98.9%, Mempalace 96.6%

## BEAM — Belief-based Evaluation for Artificial Memory
### Standalone Mode (BM25-only, 3 scenarios, 9 queries)
- IE (Information Extraction): 100.0% (3/3) — 0ms
- MR (Memory Retrieval): 100.0% (3/3) — 0ms  
- TR (Temporal Reasoning): 100.0% (3/3) — 0ms
- **Total: 100.0% (9/9) — 0ms avg latency**

### SDK Mode (SpacetimeDB, IE scenario only)
- IE (Information Extraction): 100.0% (3/3) — 60ms avg latency
- Architecture: SDK → Tantivy BM25 sidecar + semantic embedding

## LoCoMo (Quick test — 1 conversation)
- Ingested conversation conv-26
- Workspace created: e8e840b0bd8b4dc79eb086133c956004
- Benchmarking requires auth fix for workspace operations

## Environment
- Server: localhost:3001 (SpacetimeDB)
- Embedder: BAAI/bge-m3 (localhost:9090)
- Search: Tantivy BM25 sidecar (localhost:9091)
- Database: c200800163bb0d77375095a75a8f2fbc93c93e13f8c3c8735ed94ef8e6d348ed (longmemeval-bench)
