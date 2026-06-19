#!/usr/bin/env python3
"""Weight tuning — with per-query timeout and progress."""
from __future__ import annotations
import json, os, sys, time, uuid as _uuid, signal

for prefix in (".", "..", "/home/user/spacetime-memory"):
    sdk_path = os.path.join(prefix, "sdk/python")
    if os.path.isdir(sdk_path): sys.path.insert(0, sdk_path); break

os.environ.pop("OPENAI_API_KEY", None)
os.environ["OPENAI_API_KEY"] = "REDACTED"
os.environ["OPENAI_BASE_URL"] = "http://localhost:4000/v1"
os.environ["EMBEDDING_MODEL"] = "baai/bge-m3"
os.environ["EMBEDDER_TYPE"] = "openai"
os.environ["SPACETIMEDB_DB"] = "c2009d7ae8134a11f47e174100dc882cb05310b12575614fed28b6e608fd6cec"
os.environ["STMEM_MAX_RETRIES"] = "1"
os.environ["STMEM_CIRCUIT_RESET_SECS"] = "5"

from spacetime_memory import Client
import httpx

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

def compute_metrics(queries, results_by_query, memories_by_id):
    p, r, mrr, n = [], [], [], 0
    for q in queries:
        relevant_ids = set(q["relevant_ids"])
        relevant_contents = []
        for rid in relevant_ids:
            if rid in memories_by_id:
                relevant_contents.append(memories_by_id[rid]["content"].lower())
        if not relevant_contents: continue
        n += 1
        top5 = results_by_query.get(q["query"], [])[:5]
        hits = 0
        for rank, result in enumerate(top5, 1):
            res_content = result.get("content", "").lower()
            is_relevant = any(
                rc[:40] in res_content or res_content[:40] in rc
                for rc in relevant_contents
            )
            if is_relevant:
                hits += 1
                if hits == 1: mrr.append(1.0 / rank)
        p.append(hits / min(5, len(relevant_contents)))
        r.append(hits / len(relevant_contents))
    while len(mrr) < n: mrr.append(0.0)
    if n == 0: return {"P@5": 0, "R@5": 0, "MRR": 0}
    return {"P@5": sum(p)/n, "R@5": sum(r)/n, "MRR": sum(mrr)/n}

with open(os.path.join(DATA_DIR, "eval_memories_50.json")) as f:
    memories = json.load(f)
with open(os.path.join(DATA_DIR, "eval_queries_25.json")) as f:
    queries = json.load(f)
memories_by_id = {m["id"]: m for m in memories}

print(f"Dataset: {len(memories)} memories, {len(queries)} queries", flush=True)
print()

c = Client()
user = f"wt_{_uuid.uuid4().hex[:8]}"
c._call("register", [user, "T", "tunepass1234"])
c._call("login", [user, "tunepass1234"])
ws = f"wt_{_uuid.uuid4().hex[:8]}"
c._call("create_workspace", ["W", "W", ws])

print(f"Seeding {len(memories)} memories...", flush=True)
t0 = time.time()
for m in memories:
    c._call("store_memory", [ws, "", "", m.get("type","experience"), m["content"], "", "[]", 0.8, "", ""])
print(f"  Seeded in {time.time()-t0:.1f}s. Waiting 5s...", flush=True)
time.sleep(5)

weight_configs = [
    ("default  0.65/0.25/0.05/0/0.05", {"semantic": 0.65, "keyword": 0.25, "binary": 0.05, "graph": 0.00, "temporal": 0.05}),
    ("s-heavy  0.80/0.10/0.05/0/0.05", {"semantic": 0.80, "keyword": 0.10, "binary": 0.05, "graph": 0.00, "temporal": 0.05}),
    ("balanced 0.50/0.35/0.10/0/0.05", {"semantic": 0.50, "keyword": 0.35, "binary": 0.10, "graph": 0.00, "temporal": 0.05}),
    ("kw-light 0.70/0.20/0.05/0/0.05", {"semantic": 0.70, "keyword": 0.20, "binary": 0.05, "graph": 0.00, "temporal": 0.05}),
    ("kw-boost 0.55/0.30/0.10/0/0.05", {"semantic": 0.55, "keyword": 0.30, "binary": 0.10, "graph": 0.00, "temporal": 0.05}),
    ("temp+    0.55/0.25/0.05/0/0.15", {"semantic": 0.55, "keyword": 0.25, "binary": 0.05, "graph": 0.00, "temporal": 0.15}),
    ("s-max    0.90/0.05/0.02/0/0.03", {"semantic": 0.90, "keyword": 0.05, "binary": 0.02, "graph": 0.00, "temporal": 0.03}),
    ("even     0.40/0.40/0.10/0/0.10", {"semantic": 0.40, "keyword": 0.40, "binary": 0.10, "graph": 0.00, "temporal": 0.10}),
    ("kw-dom   0.30/0.55/0.10/0/0.05", {"semantic": 0.30, "keyword": 0.55, "binary": 0.10, "graph": 0.00, "temporal": 0.05}),
    ("s-kw-eq  0.45/0.45/0.05/0/0.05", {"semantic": 0.45, "keyword": 0.45, "binary": 0.05, "graph": 0.00, "temporal": 0.05}),
]

print(f"Running {len(queries)} queries × {len(weight_configs)} configs...", flush=True)
results_table = []
for idx, (label, weights) in enumerate(weight_configs):
    results = {}
    for qi, q in enumerate(queries):
        try:
            with httpx.Client(timeout=10.0) as hc:
                r = c.search(ws, q["query"], limit=20, semantic=True, fusion_weights=weights)
            results[q["query"]] = r
        except (httpx.TimeoutException, httpx.ConnectError, RuntimeError) as e:
            results[q["query"]] = []
        except Exception as e:
            print(f"  Query fail [{qi}]: {str(e)[:60]}", flush=True)
            results[q["query"]] = []
    m = compute_metrics(queries, results, memories_by_id)
    results_table.append((label, m))
    print(f"  [{idx+1}/{len(weight_configs)}] {label:<38} P@5={m['P@5']:.1%}  MRR={m['MRR']:.3f}", flush=True)

print(flush=True)
results_table.sort(key=lambda x: x[1]["P@5"], reverse=True)
print("=" * 62, flush=True)
print("RANKING:", flush=True)
for i, (label, m) in enumerate(results_table, 1):
    print(f"  {i:2d}. {label:<38} P@5={m['P@5']:.1%}  MRR={m['MRR']:.3f}", flush=True)
print(flush=True)
