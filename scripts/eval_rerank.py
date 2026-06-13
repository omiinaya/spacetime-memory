#!/usr/bin/env python3
import json, os, sys, yaml, time
sys.path.insert(0, "/home/user/spacetime-memory/sdk/python")
from spacetime_memory import Client
from spacetime_memory.auth import generate_token

with open(os.path.expanduser("~/.hermes/config.yaml")) as f:
    config = yaml.safe_load(f)
prov = config["custom_providers"][0]

os.environ["LLM_RERANK_ENDPOINT"] = prov["base_url"]
os.environ["LLM_RERANK_API_KEY"] = prov["api_key"]
os.environ["LLM_RERANK_MODEL"] = "go-deepseek-v4-flash"

token = generate_token("/tmp/stdb-data/jwt_priv_pk8.pem")
c = Client(host="localhost", port=3001, database="c20012b2679f860fd6caf3f6fc1274e8552ed2e8f99084eefad95516b61d1f72", token=token)
c._call("login", ["seed_eval", "seedpass123"])

with open("data/eval_workspace_id.txt") as f:
    ws_id = f.read().strip()
with open("data/eval_queries_labeled.jsonl") as f:
    queries = [json.loads(line) for line in f if line.strip()]

print(f"Queries: {len(queries)}")
print()

p_at_5s = []
r_at_5s = []
rr_vals = []
total_time = 0

for qi, q in enumerate(queries):
    query_text = q["query"]
    relevant = set(q["relevant_ids"])
    
    t0 = time.time()
    results = c.search(ws_id, query=query_text, limit=5, semantic=True, rerank=True)
    elapsed = time.time() - t0
    total_time += elapsed
    
    retrieved_ids = [r.get("entity_id", "") or r.get("id", "") for r in results[:5]]
    retrieved_set = set(retrieved_ids)
    
    hits = len(retrieved_set & relevant)
    p5 = hits / max(len(retrieved_set), 1) if retrieved_set else 0.0
    r5 = hits / max(len(relevant), 1)
    
    rr = 0.0
    for rank, rid in enumerate(retrieved_ids, 1):
        if rid in relevant:
            rr = 1.0 / rank
            break
    
    p_at_5s.append(p5)
    r_at_5s.append(r5)
    rr_vals.append(rr)
    
    top_reason = results[0].get("rerank_reason", "N/A")[:60] if results else "N/A"
    print(f"  Q{qi:02d}: {query_text[:48]:48s} | P5={p5:.2f} R5={r5:.2f} RR={rr:.2f} | {elapsed:.1f}s | {top_reason}")

avg_p5 = sum(p_at_5s) / len(p_at_5s) if p_at_5s else 0.0
avg_r5 = sum(r_at_5s) / len(r_at_5s) if r_at_5s else 0.0
avg_rr = sum(rr_vals) / len(rr_vals) if rr_vals else 0.0
perfect = sum(1 for p in p_at_5s if p >= 1.0)

print()
print("=" * 60)
print(f"P@5={avg_p5*100:.1f}%  R@5={avg_r5*100:.1f}%  MRR={avg_rr:.3f}  Perfect={perfect}/{len(queries)}")
print(f"Total time: {total_time:.0f}s ({total_time/len(queries):.1f}s/query)")
print("Pipeline: semantic + BM25 + graph + temporal + fusion + LLM rerank")
print("=" * 60)
