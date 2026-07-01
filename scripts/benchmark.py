#!/usr/bin/env python3
"""Unified benchmark runner — latency + retrieval + KG.

Usage:
  SPACETIMEDB_DB=<identity> python3 scripts/benchmark.py

Alternatively, with a freshly published module on localhost:3001:
  python3 scripts/benchmark.py --auto

Output: /tmp/benchmark-report.json + stdout.
"""
import json, os, statistics, sys, time, uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk", "python"))
from spacetime_memory import Client

HOST = os.environ.get("SPACETIMEDB_HOST", "127.0.0.1")
PORT = int(os.environ.get("SPACETIMEDB_PORT", 3001))
DB = os.environ.get("SPACETIMEDB_DB", "")
N_LATENCY = int(os.environ.get("BENCH_ITERATIONS", "10"))

if not DB:
    print("ERROR: set SPACETIMEDB_DB or pass --auto")
    sys.exit(1)

print(f"Spacetime-Memory Benchmark Suite")
print(f"{'='*60}")
print(f"Host: {HOST}:{PORT}")
print(f"DB:   {DB[:20]}...")
print(f"Date: {time.strftime('%Y-%m-%d %H:%M UTC')}")
print()

# ---------------------------------------------------------------------------
# 1. LATENCY BENCHMARKS
# ---------------------------------------------------------------------------
print("[1/3] Latency benchmarks")
print("-" * 60)

c = Client(host=HOST, port=PORT, database=DB)

# Register/login for full auth
for reducer, args in [("register", ["bench_user", "Bench User", "benchpass123"]),
                       ("login", ["bench_user", "benchpass123"])]:
    try:
        c._call(reducer, args)
    except RuntimeError:
        pass
try:
    c._call("login", ["bench_user", "benchpass123"])
except RuntimeError:
    pass

print(f"Identity: {c._whoami()}")

# Create workspace
ws_name = f"bench-{int(time.time())}"
try:
    c.create_workspace(name=ws_name)
except RuntimeError:
    pass
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

# Verify
c.store(ws_id, "probe", "experience")
r = c.search(ws_id, "probe", limit=1, semantic=False)
print(f"Sanity check: store+search OK ({len(r)} results)")
print()

def measure(label, fn, n=N_LATENCY):
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
        f = int(k); c = k-f
        return lats[f]*(1-c) + lats[min(f+1,len(lats)-1)]*c
    return {
        "label": label, "n": len(lats), "fails": fails,
        "p50": round(pct(50),1), "p90": round(pct(90),1),
        "p99": round(pct(99),1), "mean": round(statistics.mean(lats),1),
        "min": round(lats[0],1), "max": round(lats[-1],1),
    }

latency_results = []
def run(label, fn, n=N_LATENCY):
    r = measure(label, fn, n=n)
    latency_results.append(r)
    print(f"  {label:40s}  p50={r['p50']:>6.1f}ms  p90={r['p90']:>6.1f}ms  (n={r['n']}, fails={r['fails']})")

run("memory.store (single)", lambda: c.store(ws_id, "Short test memory", "experience"))
run("search.keyword (top-5)", lambda: c.search(ws_id, "test", limit=5, semantic=False))
run("graph.query", lambda: c.query_graph(ws_id, "test"))
run("ping (round-trip)", lambda: c._whoami())

print()

# ---------------------------------------------------------------------------
# 2. RETRIEVAL QUALITY
# ---------------------------------------------------------------------------
print("[2/3] Retrieval quality (keyword+graph+temporal)")
print("-" * 60)

# Seed 10 memories with specific content
seed_memories = [
    ("The CEO of Acme Corp is Alice Johnson, who founded the company in 2018.", "world_fact"),
    ("Bob Smith is the CTO and leads the engineering team at Acme Corp.", "world_fact"),
    ("Carol Davis is a senior engineer working on the backend systems.", "world_fact"),
    ("Dave Wilson is a senior engineer focused on infrastructure.", "world_fact"),
    ("Eve Martin is the lead designer at Acme Corp.", "world_fact"),
    ("The company headquarters is located at 123 Main Street, San Francisco.", "world_fact"),
    ("Acme Corp's main product is a SaaS platform for project management.", "world_fact"),
    ("The company has 250 employees across 3 offices worldwide.", "world_fact"),
    ("Annual revenue for Acme Corp was $50M in fiscal year 2025.", "world_fact"),
    ("The engineering team uses Rust, TypeScript, and Python for development.", "world_fact"),
]

ws2 = f"eval-{_uuid.uuid4().hex[:8]}"
c.create_workspace(name=ws2)
ws2_list = c._query("workspace", workspace_id="", columns=["id", "name"])
ws2_id = None
for w in ws2_list:
    if w.get("name") == ws2:
        ws2_id = w.get("id")
        break
if not ws2_id:
    print("ERROR: Cannot create eval workspace")
    sys.exit(1)

for content, mtype in seed_memories:
    c.store(workspace_id=ws2_id, content=content, memory_type=mtype)
time.sleep(2)

# Define queries with expected substrings
queries = [
    ("Who is the CEO of Acme?", ["Alice", "CEO"]),
    ("Who leads engineering?", ["Bob", "CTO"]),
    ("What tech stack does engineering use?", ["Rust", "TypeScript", "Python"]),
    ("Where is Acme headquarters?", ["San Francisco", "123 Main"]),
    ("What is Acme's revenue?", ["$50M", "50M"]),
    ("Who works on backend?", ["Carol", "backend"]),
    ("How many employees does Acme have?", ["250"]),
    ("Who is the lead designer?", ["Eve", "Martin"]),
]

hits = 0
total_checks = 0
for query, expected_terms in queries:
    results = c.search(workspace_id=ws2_id, query=query, limit=5, semantic=False)
    found_text = " ".join(r.get("content", "") + " " + r.get("summary", "") for r in results).lower()
    for term in expected_terms:
        total_checks += 1
        if term.lower() in found_text:
            hits += 1
    matched = sum(1 for t in expected_terms if t.lower() in found_text)
    print(f"  '{query[:45]}' -> {matched}/{len(expected_terms)} terms matched")

recall_at_5 = round(hits / max(total_checks, 1), 4)
print(f"  Recall@5 (term match): {recall_at_5:.1%}")
print()

# ---------------------------------------------------------------------------
# 3. KG OPERATIONS
# ---------------------------------------------------------------------------
print("[3/3] Knowledge graph operations")
print("-" * 60)

kg_ws = f"kg-eval-{_uuid.uuid4().hex[:8]}"
c.create_workspace(name=kg_ws)
kg_list = c._query("workspace", workspace_id="", columns=["id", "name"])
kg_ws_id = None
for w in kg_list:
    if w.get("name") == kg_ws:
        kg_ws_id = w.get("id")
        break

# Create nodes
node_labels = ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank"]
for label in node_labels:
    try:
        c.create_node(workspace_id=kg_ws_id, label=label, node_type="entity", summary=f"{label} is a team member")
    except RuntimeError as e:
        print(f"  WARN: create_node({label}): {e}")

# Measure latency
t0 = time.perf_counter()
q_result = c.query_graph(kg_ws_id, "Alice")
graph_latency = (time.perf_counter() - t0) * 1000

nodes_found = len(q_result)
t0 = time.perf_counter()
for _ in range(5):
    c.query_graph(kg_ws_id, "team")
graph_batch_latency = ((time.perf_counter() - t0) * 1000) / 5

print(f"  query_graph ('Alice'):     {graph_latency:.1f}ms ({nodes_found} results)")
print(f"  query_graph avg (5 runs):  {graph_batch_latency:.1f}ms")
print()

# ---------------------------------------------------------------------------
# REPORT
# ---------------------------------------------------------------------------
print("=" * 60)
print("BENCHMARK SUMMARY")
print("=" * 60)

total_latency_ops = sum(r["n"] for r in latency_results)
total_latency_fails = sum(r["fails"] for r in latency_results)

report = {
    "meta": {
        "host": f"{HOST}:{PORT}",
        "database": DB[:20],
        "date": time.strftime('%Y-%m-%d %H:%M UTC'),
    },
    "latency": [
        {"operation": r["label"], "p50_ms": r["p50"], "p90_ms": r["p90"],
         "p99_ms": r["p99"], "mean_ms": r["mean"], "n": r["n"], "fails": r["fails"]}
        for r in latency_results
    ],
    "retrieval": {
        "memory_count": len(seed_memories),
        "query_count": len(queries),
        "recall_at_5_term_match": recall_at_5,
        "notes": "Keyword-only (no embedder). Term-match is stricter than semantic relevance.",
    },
    "kg": {
        "nodes_created": len(node_labels),
        "query_graph_latency_ms": round(graph_latency, 1),
        "query_graph_avg_latency_ms": round(graph_batch_latency, 1),
    },
    "success_rate": {
        "total_ops": total_latency_ops,
        "total_fails": total_latency_fails,
        "rate": f"{(total_latency_ops - total_latency_fails) / max(total_latency_ops, 1):.1%}",
    },
}

with open("/tmp/benchmark-report.json", "w") as f:
    json.dump(report, f, indent=2)

print(f"\nLatency: {total_latency_ops - total_latency_fails}/{total_latency_ops} ops OK")
print(f"Retrieval: Recall@5={recall_at_5:.1%} (10 memories, {len(queries)} queries)")
print(f"KG: query_graph ~{graph_batch_latency:.1f}ms avg")
print(f"\nReport: /tmp/benchmark-report.json")
