#!/usr/bin/env python3
"""Fast eval — keyword-only, no embeddings. BM25 + graph + temporal."""
from __future__ import annotations
import json, os, sys, time

for prefix in (".", "..", "/home/user/spacetime-memory"):
    sdk_path = os.path.join(prefix, "sdk/python")
    if os.path.isdir(sdk_path): sys.path.insert(0, sdk_path); break

from spacetime_memory import Client
import uuid as _uuid

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

def compute_metrics(queries, results_by_query, memories_by_id):
    """Match by content since STDB generates UUIDs, not our dataset IDs."""
    p, r, mrr, n = 0.0, 0.0, 0.0, 0
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
            # Check if this result matches any relevant memory by content
            is_relevant = any(
                rc[:40] in res_content or res_content[:40] in rc
                for rc in relevant_contents
            )
            if is_relevant:
                hits += 1
                if hits == 1:  # First relevant = reciprocal rank
                    mrr += 1.0 / rank
        p += hits / min(5, len(relevant_contents))
        r += hits / len(relevant_contents)
    if n == 0: return {"P@5": 0, "R@5": 0, "MRR": 0}
    return {"P@5": round(p/n, 4), "R@5": round(r/n, 4), "MRR": round(mrr/n, 4)}

with open(os.path.join(DATA_DIR, "eval_memories_50.json")) as f: memories = json.load(f)
with open(os.path.join(DATA_DIR, "eval_queries_25.json")) as f: queries = json.load(f)

print(f"Dataset: {len(memories)} memories, {len(queries)} queries")

# Skip LLM extraction during seeding (adds ~60s per store when API unreachable)
import os as _os
_os.environ.pop("OPENAI_API_KEY", None)
_os.environ.pop("LITELLM_MASTER_KEY", None)
_os.environ.pop("LLM_RERANK_API_KEY", None)

c = Client()
user = f"eval_{_uuid.uuid4().hex[:8]}"
for reducer, args in [("register", [user, "Eval", "evalpass123"]), ("login", [user, "evalpass123"])]:
    try: c._call(reducer, args)
    except RuntimeError: pass

ws = f"eval-{_uuid.uuid4().hex[:8]}"
c.create_workspace("Fast Eval", "keyword-only benchmark", id=ws)

# Seed (skip embeddings — just store content)
print(f"Seeding {len(memories)} memories (no embeddings)...")
for i, m in enumerate(memories):
    c.store(workspace_id=ws, content=m["content"], memory_type=m.get("type", "experience"))
print(f"Seeded. Waiting 3s for indexing...")
time.sleep(3)

print(f"Running {len(queries)} queries (keyword-only)...")
results = {}
for i, q in enumerate(queries):
    try:
        r = c.search(workspace_id=ws, query=q["query"], limit=20, semantic=False)
        results[q["query"]] = r
        if i == 0:
            print(f"  DEBUG first query '{q['query']}': got {len(r)} results")
            for rr in r[:3]:
                print(f"    id={rr.get('id','?')} content={rr.get('content','')[:60]}")
    except Exception as e:
        print(f"  FAIL: {q['query'][:40]} — {e}")
        results[q["query"]] = []

# Also verify memories were stored
mem_check = c._query('memory', workspace_id=ws)
print(f"\nVerification: {len(mem_check)} memories in workspace")
if mem_check:
    print(f"  First: id={mem_check[0].get('id','?')} content={mem_check[0].get('content','')[:60]}")
    # Manual keyword check
    q = 'CTO'
    hits = [m for m in mem_check if q.lower() in m.get('content','').lower()]
    print(f"  Manual 'CTO' matches: {len(hits)}")

m = compute_metrics(queries, results, {m["id"]: m for m in memories})
print(f"\nKeyword-only (BM25+graph+temporal):")
print(f"  P@5={m['P@5']:.1%}  R@5={m['R@5']:.1%}  MRR={m['MRR']:.3f}")
print(f"\nGBrain reference: P@5=49.1%, R@5=97.9% (146K pages)")
print(f"Our previous:     P@5=19.0%, R@5=72.2%, MRR=0.206 (25 memories, no embeddings)")
