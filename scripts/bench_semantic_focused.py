#!/usr/bin/env python3
"""Focused 20-iteration semantic search latency benchmark.

Measures the specific operations affected by the _enrich_content N+1 fix:
- search.semantic (top-10) — the async hybrid search with embedder + enrichment

Usage:
  cd ~/spacetime-memory && set -a && source .env && set +a && python3 scripts/bench_semantic_focused.py

Environment: .env file at repo root expected.
"""
import os, json, logging, statistics, sys, time

logging.getLogger("spacetime_memory").setLevel(logging.ERROR)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk", "python"))

# Load .env
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

os.environ.pop("OPENAI_API_KEY", None)
os.environ["OPENAI_API_KEY"] = "sk-no-auth-needed"
os.environ["OPENAI_BASE_URL"] = "http://localhost:9090/v1"
os.environ["EMBEDDING_MODEL"] = "bge-m3"

from spacetime_memory import Client

HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = int(os.environ.get("SPACETIMEDB_PORT", 3001))
DB = os.environ.get("SPACETIMEDB_DB", "")
N = int(os.environ.get("BENCH_ITERATIONS", "20"))

if not DB:
    print("FATAL: Set SPACETIMEDB_DB in .env or environment")
    sys.exit(1)

print("=" * 60)
print("Semantic Search Latency Benchmark")
print("=" * 60)
print(f"Host: {HOST}:{PORT}")
print(f"DB:   {DB[:20]}...")
print(f"Date: {time.strftime('%Y-%m-%d %H:%M UTC')}")
print()

c = Client(host=HOST, port=PORT, database=DB, token=None)
c._call("login", ["bench_user", "benchpass123"])
print(f"Identity: {c._whoami()}")

ws_name = f"bench-{int(time.time())}"
c.create_workspace(name=ws_name)
r = c._query("workspace", workspace_id="", columns=["id", "name"])
ws_id = None
for w in r:
    if w.get("name") == ws_name:
        ws_id = w["id"]
        break
if not ws_id:
    print("ERROR: Cannot create workspace")
    sys.exit(1)
print(f"Workspace: {ws_id}")

# Seed 50 memories
print("Seeding 50 memories...")
for i in range(50):
    c._call("store_memory", [
        ws_id, "", "", "experience",
        f"Benchmark test memory number {i} for keyword and semantic searches. Testing retrieval quality verification.",
        "", "[]", 0.8, "", ""
    ])
    if (i + 1) % 10 == 0:
        print(f"  {i + 1}/50 stored")

# Embed and index
print("  Indexing embeddings...")
mems = c._query("memory", workspace_id=ws_id, columns=["id", "content"])
for m in mems:
    mid = m["id"]
    content = m.get("content", "")
    if not content:
        continue
    emb = c._embed(content)
    if emb:
        try:
            c._call("index_entity", [ws_id, "memory", mid, content, json.dumps(emb)])
            c._call("index_terms", [ws_id, "memory", mid, content])
        except RuntimeError as e:
            pass
    time.sleep(0.01)
print("  Done.")

time.sleep(2)  # Let Tantivy catch up

# Benchmark framework
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
    return {"label": label, "n": len(lats), "fails": fails,
            "p50": round(pct(50),1), "p90": round(pct(90),1),
            "p99": round(pct(99),1), "mean": round(statistics.mean(lats),1),
            "min": round(lats[0],1), "max": round(lats[-1],1)}

results = []
def run(label, fn, n=N):
    r = measure(label, fn, n=n)
    results.append(r)
    print(f"  [{len(results):2d}] {label:40s}  p50={r['p50']:>7.1f}ms  p90={r['p90']:>7.1f}ms  mean={r['mean']:>7.1f}ms  (n={r['n']}, fails={r['fails']})")

print("\nRunning benchmarks...")

# 1. Embed-only
run("embed-only (bge-m3)", lambda: c._embed("test query for benchmark verification " * 3), n=min(N, 5))

# 2. Keyword-only search
run("search.keyword (top-5)", lambda: c.search(ws_id, "test memory retrieval", limit=5, semantic=False), n=N)

# 3. Semantic search — THE key metric
run("search.semantic (top-10, w/ embedder)", lambda: c.search(ws_id, "test memory retrieval quality verification", limit=10, semantic=True), n=N)

# 4. Graph query
run("graph.query", lambda: c.query_graph(ws_id, "memory"), n=N)

# 5. Ping
run("ping (round-trip)", lambda: c._whoami(), n=N)

print()
print("=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"| # | Operation | p50 (ms) | p90 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms) | n")
print(f"|---|--------:|--------:|--------:|---------:|----------:|---------:|---------:|--:")
for r in results:
    print(f"| {results.index(r)+1} | {r['label']} | {r['p50']} | {r['p90']} | {r['p99']} | {r['mean']} | {r['min']} | {r['max']} | {r['n']}")
total_fails = sum(r['fails'] for r in results)
total_n = sum(r['n'] for r in results)
print(f"Failures: {total_fails}/{total_n} ({round(total_fails/max(total_n,1)*100,1)}%)")
semantic = [r for r in results if "semantic" in r["label"]]
if semantic:
    s = semantic[0]
    verdict = "PASS" if s["p50"] < 3500 else "WARN"
    print(f"Semantic search: p50={s['p50']}ms (target <3500ms) — {verdict}")

# Save
report = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
          "host": HOST, "port": PORT, "database": DB[:20],
          "workspace_id": ws_id, "iterations": N, "embedder_available": True,
          "latency": results}
with open("benchmark_results_latest.json", "w") as f:
    json.dump(report, f, indent=2)
print(f"Results saved to benchmark_results_latest.json")
