#!/usr/bin/env python3
"""One-shot benchmark for Spacetime-Memory.

Runs 13 operations against a live SpacetimeDB, outputs markdown.
Usage:
  SPACETIMEDB_DB=<identity> python3 scripts/quick-bench.py
"""
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))
from spacetime_memory import Client

HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get("SPACETIMEDB_DB", "")
N = int(os.environ.get("BENCH_ITERATIONS", "20"))

if not DB:
    print("ERROR: set SPACETIMEDB_DB to your database identity")
    sys.exit(1)

c = Client(host=HOST, port=PORT, database=DB)

# Resolve a writable workspace (use UUID from list, not name)
ws_id = f"bench-{int(time.time())}"
try:
    c.create_workspace(ws_id)
except RuntimeError:
    pass
# Find the UUID from list
ws_list = c.list_workspaces()
resolved = None
for w in ws_list:
    if w.get("name") == ws_id:
        resolved = w.get("id")
        break
if not resolved:
    # Fallback: try to use name directly
    resolved = ws_id

ws_id = resolved
print(f"Workspace: {ws_id}")

# Verify access
try:
    c.store(ws_id, "probe", "experience")
    c.search(ws_id, "probe", limit=1, semantic=False)
except Exception as e:
    print(f"ERROR: Cannot access workspace: {e}")
    sys.exit(1)

print(f"\nBenchmarking {HOST}:{PORT}/{DB[:16]}  ({N} iterations each)\n")

def measure(label, fn, n=N):
    lats = []
    fails = 0
    for i in range(n):
        t0 = time.perf_counter()
        try:
            fn()
            lats.append((time.perf_counter() - t0) * 1000)
        except Exception:
            fails += 1
    if not lats:
        return {"label": label, "n": 0, "fails": fails,
                "p50": 0, "p90": 0, "p99": 0, "mean": 0, "min": 0, "max": 0}
    lats.sort()
    def pct(p):
        k = (p/100)*(len(lats)-1)
        f = int(k); c = k-f
        return lats[f]*(1-c) + lats[min(f+1,len(lats)-1)]*c
    return {
        "label": label, "n": len(lats), "fails": fails,
        "p50": round(pct(50),1), "p90": round(pct(90),1),
        "p99": round(pct(99),1), "mean": round(statistics.mean(lats),1),
        "min": round(lats[0],1), "max": round(lats[-1],1),
    }

results = []
def run(label, fn, n=N):
    r = measure(label, fn, n=n)
    results.append(r)
    print(f"  [{len(results):2d}] {label:40s}  p50={r['p50']:>6.1f}ms  p90={r['p90']:>6.1f}ms  p99={r['p99']:>6.1f}ms  (n={r['n']}, fails={r['fails']})")

# 1
run("memory.store (single, short)", lambda: c.store(ws_id, "Short test memory", "experience"))
# 2
run("memory.store (single, long)", lambda: c.store(ws_id, "Long " * 200 + "test memory", "experience"))
# 3
run("memory.store (batch 10)", lambda: [c.store(ws_id, f"Batch item {i}", "experience") for i in range(10)], n=min(N,10))
# 4
run("memory.store (batch 100)", lambda: [c.store(ws_id, f"Big batch {i}", "experience") for i in range(100)], n=min(N,10))
# 5
run("search.semantic (top-5)", lambda: c.search(ws_id, "memory", limit=5, semantic=True))
# 6
run("search.keyword (top-5)", lambda: c.search(ws_id, "test", limit=5, semantic=False))
# 7
run("search.hybrid (top-10)", lambda: c.search(ws_id, "memory", limit=10, semantic=True))
# 8
run("graph.query", lambda: c.query_graph(ws_id, "test"))
# 9
run("sql.read (COUNT)", lambda: c._sql(f"SELECT COUNT(*) as cnt FROM memory WHERE workspace_id = '{ws_id}'"))
# 10
run("ping (round-trip)", lambda: c._whoami())

# Markdown output
print("\n\n## Benchmarks\n")
print(f"**Host:** {HOST}:{PORT}  **DB:** `{DB[:20]}...`  **Iterations:** {N}  **Workspace:** {ws_id}")
print(f"**Date:** {time.strftime('%Y-%m-%d %H:%M UTC')}\n")
print("| # | Operation | p50 (ms) | p90 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms)")
print("|---|-----------|---------:|---------:|---------:|----------:|---------:|---------:")
for i, r in enumerate(results, 1):
    print(f"| {i} | {r['label']} | {r['p50']} | {r['p90']} | {r['p99']} | {r['mean']} | {r['min']} | {r['max']}")
fails = sum(r['fails'] for r in results)
print(f"\n**Failures:** {fails}/{sum(r['n'] for r in results)} ({round(fails/max(sum(r['n'] for r in results),1)*100,1)}%)")

# Save to file
out = os.environ.get("BENCH_OUTPUT", "")
if out:
    with open(out, "w") as f:
        f.write("# Performance Benchmarks\n\n")
        f.write(f"Results from {time.strftime('%Y-%m-%d %H:%M UTC')}\n\n")
        f.write("## Reference Results\n\n")
        f.write("| # | Operation | p50 (ms) | p90 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms)\n")
        f.write("|---|-----------|---------:|---------:|---------:|----------:|---------:|---------:\n")
        for i, r in enumerate(results, 1):
            f.write(f"| {i} | {r['label']} | {r['p50']} | {r['p90']} | {r['p99']} | {r['mean']} | {r['min']} | {r['max']}\n")
    print(f"\nResults saved to {out}")
