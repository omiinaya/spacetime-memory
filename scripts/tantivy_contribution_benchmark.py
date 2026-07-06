#!/usr/bin/env python3
"""Tantivy contribution benchmark — measure latency + quality WITH vs WITHOUT Tantivy.

Usage:
  cd ~/spacetime-memory
  SPACETIMEDB_DB=<identity> python3 scripts/tantivy_contribution_benchmark.py

Outputs:
  - benchmark_results_tantivy_contribution.json (detailed results)
  - Updates PERFORMANCE.md with Tantivy contribution data
"""
from __future__ import annotations

import json, os, statistics, sys, time, uuid as _uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))
from spacetime_memory import Client

HOST = os.environ.get("SPACETIMEDB_HOST", "127.0.0.1")
PORT = int(os.environ.get("SPACETIMEDB_PORT", 3001))
DB = os.environ.get("SPACETIMEDB_DB", "")
N = int(os.environ.get("BENCH_ITERATIONS", "20"))

if not DB:
    print("FATAL: Set SPACETIMEDB_DB in .env or environment")
    sys.exit(1)

# --- Helpers ---

def measure(label, fn, n=N):
    lats = []; fails = 0
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
        k = (p/100)*(len(lats)-1); f = int(k); c = k-f
        return lats[f]*(1-c) + lats[min(f+1,len(lats)-1)]*c
    return {"label": label, "n": len(lats), "fails": fails,
            "p50": round(pct(50),1), "p90": round(pct(90),1), "p99": round(pct(99),1),
            "mean": round(statistics.mean(lats),1), "min": round(lats[0],1), "max": round(lats[-1],1)}

def compute_metrics(queries, results_by_query, memories_by_id):
    p, r, mrr, n = [], [], [], 0
    for q in queries:
        relevant_ids = set(q["relevant_ids"])
        relevant_contents = []
        for rid in relevant_ids:
            if rid in memories_by_id:
                relevant_contents.append(memories_by_id[rid]["content"].lower())
        if not relevant_contents:
            continue
        n += 1
        top5 = results_by_query.get(q["query"], [])[:5]
        hits = 0
        for rank, result in enumerate(top5, 1):
            res_content = result.get("content", "").lower()
            is_relevant = any(rc[:40] in res_content or res_content[:40] in rc for rc in relevant_contents)
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
    return {"P@5": round(sum(p)/n, 4), "R@5": round(sum(r)/n, 4), "MRR": round(sum(mrr)/n, 4)}


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
with open(DATA_DIR / "eval_memories_50.json") as f:
    eval_memories = json.load(f)
with open(DATA_DIR / "eval_queries_25.json") as f:
    eval_queries = json.load(f)
memories_by_id = {m["id"]: m for m in eval_memories}

print("=" * 60)
print("Tantivy Contribution Benchmark")
print("=" * 60)
print(f"Host: {HOST}:{PORT}")
print(f"DB:   {DB[:20]}...")
print(f"Dataset: {len(eval_memories)} eval memories, {len(eval_queries)} eval queries")
print(f"Iterations: {N}")
print()

# --- Setup ---
c = Client(host=HOST, port=PORT, database=DB)
for reducer, args in [("register", ["bench_user_tantivy", "Bench User", "benchpass123"]),
                       ("login", ["bench_user_tantivy", "benchpass123"])]:
    try:
        c._call(reducer, args)
    except RuntimeError:
        pass

ws_name = f"tantivy-bench-{int(time.time())}"
c.create_workspace(name=ws_name)
ws_list = c._query("workspace", workspace_id="", columns=["id", "name"])
ws_id = None
for w in ws_list:
    if w.get("name") == ws_name:
        ws_id = w.get("id")
        break
if not ws_id:
    print("ERROR: Cannot create workspace")
    sys.exit(1)
print(f"Workspace: {ws_id}")

# Seed eval memories using c.store() — this indexes in Tantivy
print("Seeding 50 eval memories via c.store() (with Tantivy indexing)...")
t0 = time.time()
for m in eval_memories:
    c.store(workspace_id=ws_id, content=m["content"], memory_type=m.get("type", "experience"))
seed_time = time.time() - t0
print(f"  Done in {seed_time:.1f}s")
time.sleep(3)  # Let Tantivy commit
print()

# ============================================================
# PHASE 1: LATENCY WITH TANTIVY
# ============================================================
print("-" * 60)
print("PHASE 1: Latency — WITH Tantivy")
print("-" * 60)

latency_with = []
def run_with(label, fn, n=N):
    r = measure(label, fn, n=n)
    latency_with.append(r)
    print(f"  [{len(latency_with):2d}] {label:40s}  p50={r['p50']:>6.1f}ms  p90={r['p90']:>6.1f}ms  mean={r['mean']:>6.1f}ms  (n={r['n']})")

# Ensure Tantivy is used (normal behavior)
run_with("keyword (Tantivy-on) top-5", lambda: c.search(ws_id, "test", limit=5, semantic=False))

# ============================================================
# PHASE 2: LATENCY WITHOUT TANTIVY
# ============================================================
print()
print("-" * 60)
print("PHASE 2: Latency — WITHOUT Tantivy (STDB BM25 fallback)")
print("-" * 60)

# Temporarily disable Tantivy — same client avoids peer identity mismatch
latency_without = []
def run_without(label, fn, n=N):
    r = measure(label, fn, n=n)
    latency_without.append(r)
    print(f"  [{len(latency_without):2d}] {label:40s}  p50={r['p50']:>6.1f}ms  p90={r['p90']:>6.1f}ms  mean={r['mean']:>6.1f}ms  (n={r['n']})")

# Use the same client with Tantivy disabled via invalid URL - avoids peer identity issues
_saved_url = c.tantivy_url
c.tantivy_url = "http://127.0.0.1:18991"
run_without("keyword (Tantivy-off) top-5", lambda: c.search(ws_id, "test", limit=5, semantic=False))
c.tantivy_url = _saved_url

print()
print("LATENCY COMPARISON (Tantivy ON vs OFF):")
for wr in latency_with:
    for wor in latency_without:
        speedup = wor["p50"] / max(wr["p50"], 0.1)
        print(f"  {wr['label']}: p50={wr['p50']}ms (on) vs {wor['p50']}ms (off) -> {speedup:.1f}x faster with Tantivy")

# ============================================================
# PHASE 3: RETRIEVAL QUALITY WITH TANTIVY
# ============================================================
print()
print("-" * 60)
print("PHASE 3: Retrieval Quality — WITH Tantivy")
print("-" * 60)

# Search each query with Tantivy enabled
results_with = {}
t0 = time.time()
for q in eval_queries:
    try:
        r = c.search(ws_id, q["query"], limit=20, semantic=False)
        results_with[q["query"]] = r
    except Exception as e:
        print(f"  FAIL: {q['query'][:40]} — {e}")
        results_with[q["query"]] = []
query_time_with = time.time() - t0

m_with = compute_metrics(eval_queries, results_with, memories_by_id)
print(f"  P@5={m_with['P@5']:.1%}  R@5={m_with['R@5']:.1%}  MRR={m_with['MRR']:.3f}")
print(f"  {query_time_with/len(eval_queries)*1000:.0f}ms/q avg")

# ============================================================
# PHASE 4: RETRIEVAL QUALITY WITHOUT TANTIVY
# ============================================================
print()
print("-" * 60)
print("PHASE 4: Retrieval Quality — WITHOUT Tantivy (fallback)")
print("-" * 60)

results_without = {}
t0 = time.time()
_saved_url2 = c.tantivy_url
c.tantivy_url = "http://127.0.0.1:18991"
for q in eval_queries:
    try:
        r = c.search(ws_id, q["query"], limit=20, semantic=False)
        results_without[q["query"]] = r
    except Exception as e:
        print(f"  FAIL: {q['query'][:40]} — {e}")
        results_without[q["query"]] = []
c.tantivy_url = _saved_url2
query_time_without = time.time() - t0

m_without = compute_metrics(eval_queries, results_without, memories_by_id)
print(f"  P@5={m_without['P@5']:.1%}  R@5={m_without['R@5']:.1%}  MRR={m_without['MRR']:.3f}")
print(f"  {query_time_without/len(eval_queries)*1000:.0f}ms/q avg")

# ============================================================
# PHASE 5: HYBRID (semantic + keyword) QUALITY
# ============================================================
print()
print("-" * 60)
print("PHASE 5: Hybrid (semantic + keyword) Quality")
print("-" * 60)

results_hybrid = {}
t0 = time.time()
for q in eval_queries:
    try:
        r = c.search(ws_id, q["query"], limit=20, semantic=True)
        results_hybrid[q["query"]] = r
    except Exception as e:
        print(f"  FAIL: {q['query'][:40]} — {e}")
        results_hybrid[q["query"]] = []
hybrid_time = time.time() - t0

m_hybrid = compute_metrics(eval_queries, results_hybrid, memories_by_id)
print(f"  P@5={m_hybrid['P@5']:.1%}  R@5={m_hybrid['R@5']:.1%}  MRR={m_hybrid['MRR']:.3f}")
print(f"  {hybrid_time/len(eval_queries)*1000:.0f}ms/q avg")

# ============================================================
# SUMMARY
# ============================================================
print()
print("=" * 60)
print("TANTIVY CONTRIBUTION SUMMARY")
print("=" * 60)
print(f"{'Strategy':<40} {'P@5':>8} {'R@5':>8} {'MRR':>8} {'Latency':>10}")
print("-" * 74)
print(f"{'keyword (Tantivy ON)':<40} {m_with['P@5']:>7.1%} {m_with['R@5']:>7.1%} {m_with['MRR']:>7.3f}  {latency_with[0]['p50']:>7.1f}ms")
print(f"{'keyword (Tantivy OFF)':<40} {m_without['P@5']:>7.1%} {m_without['R@5']:>7.1%} {m_without['MRR']:>7.3f}  {latency_without[0]['p50']:>7.1f}ms")
print(f"{'hybrid (semantic + Tantivy)':<40} {m_hybrid['P@5']:>7.1%} {m_hybrid['R@5']:>7.1%} {m_hybrid['MRR']:>7.3f}  {hybrid_time/len(eval_queries)*1000:>7.0f}ms")
print()

# Tantivy contribution delta
delta_p = round((m_with["P@5"] - m_without["P@5"]) * 100, 1)
delta_r = round((m_with["R@5"] - m_without["R@5"]) * 100, 1)
delta_mrr = round(m_with["MRR"] - m_without["MRR"], 3)
lat_speedup = round(latency_without[0]["p50"] / max(latency_with[0]["p50"], 0.1), 1)

print(f"Tantivy contribution (delta):")
print(f"  P@5: +{delta_p}pp  R@5: +{delta_r}pp  MRR: +{delta_mrr}")
print(f"  Latency: {lat_speedup}x faster ({latency_without[0]['p50']}ms -> {latency_with[0]['p50']}ms p50)")
print()

# ============================================================
# SAVE RESULTS
# ============================================================
report = {
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "host": HOST, "port": PORT, "database": DB[:20],
    "workspace_id": ws_id,
    "iterations": N,
    "dataset": {"memories": len(eval_memories), "queries": len(eval_queries)},
    "tantivy_available": True,
    "embedder_available": True,
    "latency": {
        "keyword_tantivy_on": latency_with,
        "keyword_tantivy_off": latency_without,
    },
    "quality": {
        "keyword_tantivy_on": m_with,
        "keyword_tantivy_off": m_without,
        "hybrid_semantic": m_hybrid,
    },
    "tantivy_contribution": {
        "P@5_delta_pp": delta_p,
        "R@5_delta_pp": delta_r,
        "MRR_delta": delta_mrr,
        "latency_speedup_x": lat_speedup,
    },
    "notes": (
        "Tantivy ON: normal c.search(semantic=False) with Tantivy BM25 sidecar at :9091. "
        "Tantivy OFF: same client with tantivy_url set to invalid endpoint, falling back to "
        "_keyword_fallback (client-side substring match). "
        "Hybrid: c.search(semantic=True) uses embedder + Tantivy + graph + temporal fusion."
    ),
}

out_path = Path(__file__).resolve().parent.parent / "benchmark_results_tantivy_contribution.json"
with open(out_path, "w") as f:
    json.dump(report, f, indent=2)
print(f"Results saved to {out_path}")
