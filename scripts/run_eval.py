#!/usr/bin/env python3
"""Eval harness for labeled dataset."""
import json, os, sys, time
sys.path.insert(0, "/home/user/spacetime-memory/sdk/python")
from spacetime_memory import Client
from spacetime_memory.auth import generate_token

DB = "c2007f52296c94e0c7fb057d3cca532ce42a97a15b4820e0c60476a956be95ff"
token = generate_token("/tmp/stdb-data/jwt_priv_pk8.pem")
c = Client(host="localhost", port=3001, database=DB, token=token)
c._call("login", ["seed_eval", "seedpass123"])

# Load workspace and queries
with open("data/eval_workspace_id.txt") as f:
    ws_id = f.read().strip()
with open("data/eval_queries_labeled.jsonl") as f:
    raw = [json.loads(line) for line in f if line.strip()]
queries = [q for q in raw if q.get("relevant_ids")]

print(f"Workspace: {ws_id}")
print(f"Queries: {len(queries)}")
print()

# Run each query and compute metrics
p_at_5s = []
r_at_5s = []
rr_vals = []
details = []

for qi, q in enumerate(queries):
    query_text = q["query"]
    relevant = set(q["relevant_ids"])
    
    try:
        results = c.search(ws_id, query=query_text, limit=5, semantic=False)
    except Exception as e:
        print(f"  Q{qi}: SEARCH ERROR: {e}")
        continue
    
    retrieved_ids = [r.get("entity_id", "") or r.get("id", "") for r in results[:5]]
    retrieved_set = set(retrieved_ids)
    
    # P@5: fraction of top-5 that are relevant
    hits = len(retrieved_set & relevant)
    p5 = hits / max(len(retrieved_set), 1) if retrieved_set else 0.0
    p_at_5s.append(p5)
    
    # R@5: fraction of all relevant found in top-5
    r5 = hits / max(len(relevant), 1)
    r_at_5s.append(r5)
    
    # MRR: 1/rank of first relevant result
    rr = 0.0
    for rank, rid in enumerate(retrieved_ids, 1):
        if rid in relevant:
            rr = 1.0 / rank
            break
    rr_vals.append(rr)
    
    status = f"P@5={p5:.2f} R@5={r5:.2f} RR={rr:.2f}"
    print(f"  Q{qi:02d}: {query_text[:50]:50s} | {status}")
    details.append({"query": query_text, "p5": p5, "r5": r5, "rr": rr, 
                    "retrieved": retrieved_ids[:3], "relevant": list(relevant)})

# Summary
avg_p5 = sum(p_at_5s) / len(p_at_5s) if p_at_5s else 0.0
avg_r5 = sum(r_at_5s) / len(r_at_5s) if r_at_5s else 0.0
avg_rr = sum(rr_vals) / len(rr_vals) if rr_vals else 0.0

# Count perfect queries
perfect = sum(1 for p, r in zip(p_at_5s, r_at_5s) if p >= 1.0)
zero = sum(1 for p in p_at_5s if p == 0.0)

print()
print("=" * 60)
print(f"RESULTS ({len(queries)} queries, 25 memories)")
print(f"  P@5:  {avg_p5:.3f} ({avg_p5*100:.1f}%)")
print(f"  R@5:  {avg_r5:.3f} ({avg_r5*100:.1f}%)")
print(f"  MRR:  {avg_rr:.3f}")
print(f"  Perfect queries: {perfect}/{len(queries)}")
print(f"  Zero-hit queries: {zero}/{len(queries)}")
print()
print("Reference: GBrain P@5=49.1%, R@5=97.9% (146K pages)")
print("=" * 60)

# Save detailed results
with open("data/eval_results.json", "w") as f:
    json.dump({
        "workspace_id": ws_id,
        "num_queries": len(queries),
        "num_memories": 25,
        "metrics": {"P@5": avg_p5, "R@5": avg_r5, "MRR": avg_rr},
        "details": details,
    }, f, indent=2)
print("\nSaved: data/eval_results.json")
