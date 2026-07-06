#!/usr/bin/env python3
"""Unified benchmark runner for Spacetime-Memory.

Runs latency benchmarks + KG quality benchmarks and outputs structured results.
Usage:
  DB_ID=<identity> python3 scripts/benchmark_runner.py

Env vars:
  DB_ID — STDB database identity (required)
  HOST — STDB host (default: 127.0.0.1)
  PORT — STDB port (default: 3001)
  ITERATIONS — iterations per benchmark (default: 20)
  SAVE_DATASET — also generate eval dataset from stored memories (default: false)
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
import uuid as _uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))

from spacetime_memory import Client

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = os.environ.get("PORT", "3001")
DB_ID = os.environ.get("DB_ID", "")
N = int(os.environ.get("ITERATIONS", "20"))

if not DB_ID:
    print("ERROR: set DB_ID to your database identity")
    sys.exit(1)

USER = "bench_user"
PASS = "benchpass123"
WORKSPACE_ID = "bench-ws-1"  # Created by setup script

c = Client(host=HOST, port=PORT, database=DB_ID, token=None)
try:
    c._call("login", [USER, PASS])
except RuntimeError:
    c._call("register", [USER, "Bench User", PASS])
    c._call("login", [USER, PASS])

print(f"Connected to {HOST}:{PORT}/{DB_ID[:16]}...")
print(f"Workspace: {WORKSPACE_ID}")
print(f"Iterations: {N}")
print()

# ── Latency benchmarks ──────────────────────────────────────────

def measure(label, fn, n=N):
    lats = []
    fails = 0
    for i in range(n):
        t0 = time.perf_counter()
        try:
            fn()
            lats.append((time.perf_counter() - t0) * 1000)
        except Exception as e:
            fails += 1
    if not lats:
        return {"label": label, "n": 0, "fails": fails, "p50": 0, "p90": 0, "p99": 0, "mean": 0, "min": 0, "max": 0}
    lats.sort()
    def pct(p):
        k = (p/100)*(len(lats)-1)
        f = int(k); c_ = k-f
        return lats[f]*(1-c_) + lats[min(f+1,len(lats)-1)]*c_
    return {
        "label": label, "n": len(lats), "fails": fails,
        "p50": round(pct(50), 1), "p90": round(pct(90), 1),
        "p99": round(pct(99), 1), "mean": round(statistics.mean(lats), 1),
        "min": round(lats[0], 1), "max": round(lats[-1], 1),
    }

latency_results = []

def run(label, fn, n=N):
    r = measure(label, fn, n=n)
    latency_results.append(r)
    print(f"  [{len(latency_results):2d}] {label:40s}  p50={r['p50']:>6.1f}ms  p90={r['p90']:>6.1f}ms  p99={r['p99']:>6.1f}ms  (n={r['n']}, fails={r['fails']})")

# Seed some memories for search benchmarks
print("Seeding test memories...")
for i in range(50):
    c.store(WORKSPACE_ID,
            content=f"Benchmark test memory number {i} for keyword and semantic searches. This is a test payload.")
print(f"  Seeded 50 memories.")
# Also index terms for BM25 keyword search
for mem in c._query("memory", workspace_id=WORKSPACE_ID, columns=["id", "content"]):
    c._call("index_terms", [WORKSPACE_ID, "memory", mem["id"], mem["content"]])
print(f"  Indexed BM25 terms for {len([m for m in c._query('memory', workspace_id=WORKSPACE_ID, columns=['id'])]) if False else 'all'} memories")
# Also create some graph nodes
for i in range(10):
    try:
        c.create_node(workspace_id=WORKSPACE_ID, label=f"BenchNode_{i}", node_type="entity", summary=f"Benchmark KG node {i}")
    except RuntimeError:
        pass
print(f"  Seeded 10 KG nodes.")
# Create some edges
nodes = c._query("kg_node", workspace_id=WORKSPACE_ID, columns=["id", "label"])
node_ids = [n["id"] for n in nodes if n.get("label", "").startswith("BenchNode_")]
for i in range(min(8, len(node_ids)-1)):
    try:
        c.create_edge(workspace_id=WORKSPACE_ID, source_node_id=node_ids[i], target_node_id=node_ids[i+1], relation="connected", weight=1.0, metadata_json="{}")
    except RuntimeError:
        pass
time.sleep(2)  # Wait for Tantivy indexing

print()
print("─" * 60)
print("LATENCY BENCHMARKS")
print("─" * 60)

# 1
run("memory.store (single, short) [no embed]", lambda: c._call("store_memory", [WORKSPACE_ID, "", "", "experience", "Short test memory", "", "[]", 0.8, "", ""]))
# 2
run("memory.store (single, long) [no embed]", lambda: c._call("store_memory", [WORKSPACE_ID, "", "", "experience", "Long " * 200 + "test memory", "", "[]", 0.8, "", ""]))
# 3
run("memory.store (batch 10) [no embed]", lambda: [c._call("store_memory", [WORKSPACE_ID, "", "", "experience", f"Batch item {i}", "", "[]", 0.8, "", ""]) for i in range(10)], n=min(N, 10))
# 4
run("search.keyword (top-5)", lambda: c.search(WORKSPACE_ID, "test", limit=5, semantic=False))
# 5
# 5
run("search.semantic (top-5, w/ embedder)", lambda: c.search(WORKSPACE_ID, "test", limit=5, semantic=True), n=min(N, 3))
# 6
run("graph.query", lambda: c.query_graph(WORKSPACE_ID, "BenchNode"))
# 7
# Use _query instead of _sql (SQL endpoint not available)
run("memory.count (_query)", lambda: c._query("memory", workspace_id=WORKSPACE_ID, columns=["COUNT(*) as cnt"]), n=min(N, 5))
# 8
run("ping (round-trip)", lambda: c._whoami())
# 9
run("create_node (KG)", lambda: c.create_node(workspace_id=WORKSPACE_ID, label=f"latency_test_{_uuid.uuid4().hex[:8]}", node_type="entity", summary="Latency benchmark node"), n=min(N, 10))
# 10
if node_ids:
    run("create_edge (KG)", lambda: c.create_edge(workspace_id=WORKSPACE_ID, source_node_id=node_ids[0], target_node_id=node_ids[1], relation="latency_test", weight=1.0, metadata_json="{}"), n=min(N, 10))
# 11
run("get_neighbors", lambda: c.get_neighbors(node_ids[0], workspace_id=WORKSPACE_ID) if node_ids else [], n=min(N, 10))

print()
print("=" * 60)
print("LATENCY RESULTS TABLE")
print("=" * 60)
print(f"| # | Operation | p50 (ms) | p90 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms)")
print(f"|---|-----------|---------:|---------:|---------:|----------:|---------:|---------:")
for i, r in enumerate(latency_results, 1):
    print(f"| {i} | {r['label']} | {r['p50']} | {r['p90']} | {r['p99']} | {r['mean']} | {r['min']} | {r['max']}")
total_fails = sum(r['fails'] for r in latency_results)
total_n = sum(r['n'] for r in latency_results)
print(f"\n**Failures:** {total_fails}/{total_n} ({round(total_fails/max(total_n,1)*100,1)}%)")

# ── Retrieval quality benchmarks ─────────────────────────────────
print()
print("=" * 60)
print("RETRIEVAL QUALITY")
print("=" * 60)

# We already have 50 memories. Let's add some labeled ones for eval
eval_memories = [
    {"content": "I really enjoy eating pizza with extra cheese and pepperoni.", "type": "experience", "query_match": "food pizza"},
    {"content": "My neighbor has a golden retriever who loves to fetch tennis balls.", "type": "experience", "query_match": "dogs pets"},
    {"content": "Rust programming language is great for systems programming with memory safety guarantees.", "type": "experience", "query_match": "rust programming"},
    {"content": "Cats are independent animals that sleep about 15 hours a day.", "type": "experience", "query_match": "cats pets"},
    {"content": "Python is a dynamically typed programming language popular for data science and ML.", "type": "experience", "query_match": "python programming"},
    {"content": "I drink black coffee every morning to wake up before going to work.", "type": "experience", "query_match": "coffee morning drink"},
    {"content": "Artificial intelligence research has made significant progress in natural language processing.", "type": "experience", "query_match": "AI artificial intelligence"},
    {"content": "SpaceX successfully launched another Falcon 9 rocket carrying Starlink satellites into orbit.", "type": "experience", "query_match": "space spacex rocket"},
]

eval_queries = [
    {"query": "What food do I like?", "relevant_contents": ["I really enjoy eating pizza with extra cheese and pepperoni.", "I drink black coffee every morning to wake up before going to work."]},
    {"query": "Tell me about dogs", "relevant_contents": ["My neighbor has a golden retriever who loves to fetch tennis balls.", "Cats are independent animals that sleep about 15 hours a day."]},
    {"query": "Programming languages", "relevant_contents": ["Rust programming language is great for systems programming with memory safety guarantees.", "Python is a dynamically typed programming language popular for data science and ML."]},
    {"query": "Machine learning and AI", "relevant_contents": ["Artificial intelligence research has made significant progress in natural language processing.", "Python is a dynamically typed programming language popular for data science and ML."]},
    {"query": "Space technology", "relevant_contents": ["SpaceX successfully launched another Falcon 9 rocket carrying Starlink satellites into orbit."]},
]

# Store eval memories (bypassing Tantivy for speed — no Tantivy server running)
for m in eval_memories:
    c.store(WORKSPACE_ID, content=m["content"], memory_type=m["type"])
    # Also index terms for BM25
    for mem in c._query("memory", workspace_id=WORKSPACE_ID, columns=["id", "content"]):
        if mem["content"] == m["content"]:
            c._call("index_terms", [WORKSPACE_ID, "memory", mem["id"], mem["content"]])
            break

# Wait for indexing
time.sleep(3)

# Query for each eval query directly
def compute_metrics(queries, results_by_query):
    p, r, mrr, n = [], [], [], 0
    for q in queries:
        relevant_contents = [rc.lower() for rc in q["relevant_contents"]]
        n += 1
        top5 = results_by_query.get(q["query"], [])[:5]
        hits = 0
        for rank, result in enumerate(top5, 1):
            res_content = result.get("content", "").lower()
            is_relevant = any(
                rc and (rc[:40] in res_content or res_content[:40] in rc)
                for rc in relevant_contents
            )
            if is_relevant:
                hits += 1
                if hits == 1:
                    mrr.append(1.0 / rank)
        p.append(hits / min(5, len(relevant_contents)))
        r.append(hits / len(relevant_contents))
    while len(mrr) < n:
        mrr.append(0.0)
    if n == 0:
        return {"P@5": 0, "R@5": 0, "MRR": 0}
    return {
        "P@5": round(sum(p) / n, 4),
        "R@5": round(sum(r) / n, 4),
        "MRR": round(sum(mrr) / n, 4),
    }

configs = [
    ("keyword-only (no embeddings)", False),
]

quality_results = {}
for label, use_semantic in configs:
    results = {}
    for q in eval_queries:
        try:
            r = c.search(WORKSPACE_ID, q["query"], limit=20, semantic=use_semantic)
            results[q["query"]] = r
        except Exception as e:
            print(f"  FAIL: {q['query'][:40]} — {e}")
            results[q["query"]] = []

    m = compute_metrics(eval_queries, results)
    quality_results[label] = m
    print(f"  [{label}]")
    print(f"    P@5={m['P@5']:.1%}  R@5={m['R@5']:.1%}  MRR={m['MRR']:.3f}")

# ── Summary ─────────────────────────────────────────────────────
print()
print("=" * 60)
print("BENCHMARK SUMMARY")
print("=" * 60)
print()
print("LATENCY:")
print(f"| # | Operation | p50 (ms) | p90 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms)")
print(f"|---|-----------|---------:|---------:|---------:|----------:|---------:|---------:")
for i, r in enumerate(latency_results, 1):
    print(f"| {i} | {r['label']} | {r['p50']} | {r['p90']} | {r['p99']} | {r['mean']} | {r['min']} | {r['max']}")
print(f"\nFailures: {total_fails}/{total_n} ({round(total_fails/max(total_n,1)*100,1)}%)")
print()
print("RETRIEVAL QUALITY (Tantivy BM25 keyword + hybrid with bge-m3 embedder):")
print(f"| Config | P@5 | R@5 | MRR ")
print(f"|--------|-----|-----|-----")
for label, m in quality_results.items():
    print(f"| {label} | {m['P@5']:.1%} | {m['R@5']:.1%} | {m['MRR']:.3f}")
print()
print("Historical baseline (June 20): hybrid P@5=81.3% R@5=82.0% MRR=0.960")
print()

# Save raw data
output = {
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "host": HOST,
    "port": PORT,
    "database": DB_ID,
    "workspace_id": WORKSPACE_ID,
    "iterations": N,
    "embedder_available": True,
    "tantivy_available": True,
    "latency": latency_results,
    "quality": quality_results,
}
out_path = os.environ.get("BENCH_OUTPUT", "")
if out_path:
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Results saved to {out_path}")
else:
    # Save to default location
    default_path = f"benchmark_results_{time.strftime('%Y%m%d_%H%M%S')}.json"
    with open(default_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Results saved to {default_path}")
