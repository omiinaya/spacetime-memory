#!/usr/bin/env python3
"""Clean seed: no markers, retrieve all IDs, match by content hash."""
import json, os, sys, time, uuid, hashlib
sys.path.insert(0, "/home/user/spacetime-memory/sdk/python")
from spacetime_memory import Client
from spacetime_memory.auth import generate_token

DB = "c20012b2679f860fd6caf3f6fc1274e8552ed2e8f99084eefad95516b61d1f72"
token = generate_token("/tmp/stdb-data/jwt_priv_pk8.pem")
c = Client(host="localhost", port=3001, database=DB, token=token)
c._call("login", ["seed_eval", "seedpass123"])

ws_id = f"eval_{uuid.uuid4().hex[:8]}"
c._call("create_workspace", ["Eval", "Labeled eval", ws_id])
print(f"Workspace: {ws_id}")

memories = [
    ("Alice Chen is the CEO and co-founder of Acme AI, a Y Combinator graduate.", "alice"),
    ("Alice previously worked at Google as a Senior ML Engineer for 6 years.", "alice"),
    ("Bob Martinez is the CTO of Acme AI and leads the engineering team of 25 people.", "alice"),
    ("Bob was previously VP of Engineering at Stripe for 4 years.", "alice"),
    ("Acme AI is building an enterprise AI platform for automated customer support.", "alice"),
    ("The company was founded in March 2022 in San Francisco.", "alice"),
    ("Acme AI has raised $12M in Series A funding led by Andreessen Horowitz.", "alice"),
    ("They previously raised a $3M seed round from Y Combinator and SV Angel.", "alice"),
    ("The company has 35 employees as of June 2026.", "alice"),
    ("The platform uses GPT-4 and custom fine-tuned models for intent classification.", "alice"),
    ("Customers include Stripe, Notion, and Vercel.", "alice"),
    ("The product integrates with Zendesk, Intercom, and Salesforce.", "alice"),
    ("Acme AI NPS score is 72 and they have 98 percent customer retention.", "alice"),
    ("Main competitors are Ada, Intercom Fin, and Zendesk AI.", "alice"),
    ("Acme differentiates through multi-language support covering 40 plus languages.", "alice"),
    ("Their accuracy rate on intent classification is 94.3 percent compared to Ada 87 percent.", "alice"),
    ("The backend runs on Kubernetes with services in Rust, Python, and TypeScript.", "alice"),
    ("They process over 2 million customer interactions per day.", "alice"),
    ("Latency SLA is 200ms p99 for classification requests.", "alice"),
    ("Bob designed the distributed inference system that handles model serving.", "bob"),
    ("He wrote a blog post about scaling ML inference that got 50K views.", "bob"),
    ("Bob is hiring for 3 senior Rust backend engineers.", "bob"),
    ("Alice gave a TEDx talk about AI and customer experience in 2025.", "alice"),
    ("She was named to Forbes 30 Under 30 in 2024.", "alice"),
    ("Alice is also an angel investor in 5 other AI startups.", "alice"),
]

# Store all memories
for idx, (content, user) in enumerate(memories):
    args = [ws_id, user, "", "experience", content, content[:200], "{}", 0.5, "", ""]
    c._call("store_memory", args)

time.sleep(1)

# Retrieve ALL memory IDs by listing the workspace
# Use search with a broad query to get all results
all_results = c.search(ws_id, query="Acme AI Alice Bob Stripe Google Kubernetes Forbes TEDx", limit=50, semantic=True)
print(f"Retrieved {len(all_results)} results from broad search")

# Build content → ID map
content_map = {}
for r in all_results:
    content = r.get("content", "")
    mem_id = r.get("entity_id", "") or r.get("id", "")
    # Use first 80 chars as key (memories are unique enough at this length)
    key = content[:80]
    if key not in content_map:
        content_map[key] = mem_id

print(f"Unique content keys: {len(content_map)}")

# Match stored memories by content
stored = {}
for idx, (content, user) in enumerate(memories):
    key = content[:80]
    if key in content_map:
        mem_id = content_map[key]
        stored[f"mem_{idx}"] = mem_id
        # Index terms for BM25
        try:
            c._call("index_terms", [ws_id, "memory", mem_id, content])
        except:
            pass
    else:
        print(f"  mem_{idx}: NOT FOUND in search results")

print(f"Matched: {len(stored)}/{len(memories)}")

# Build labeled queries
label_map = [
    ("who is the CEO of Acme AI", [0]),
    ("CTO background at Stripe", [3]),
    ("funding series A how much raised", [6,7]),
    ("who are the customers of Acme", [10]),
    ("what integrations does the product support", [11]),
    ("why is Acme better than competitors", [14,15]),
    ("tech stack backend infrastructure", [16]),
    ("how many requests per day scale", [17]),
    ("latency SLA performance p99", [18]),
    ("Bob hiring what engineering roles", [21]),
    ("Alice awards recognition Forbes TEDx", [22,23]),
    ("company founded when year", [5]),
    ("how many employees headcount", [8]),
    ("Alice previous work experience Google", [1]),
    ("model accuracy compared to Ada competitors", [15]),
    ("NPS score customer retention", [12]),
    ("GPT-4 models used in platform", [9]),
    ("who designed the distributed inference system", [19]),
]

queries = []
for query, rel_indices in label_map:
    rels = [stored.get(f"mem_{i}", "") for i in rel_indices]
    rels = [r for r in rels if r]
    if rels:
        queries.append({"query": query, "relevant_ids": rels})

with open("data/eval_queries_labeled.jsonl", "w") as f:
    for q in queries:
        f.write(json.dumps(q) + "\n")
with open("data/eval_workspace_id.txt", "w") as f:
    f.write(ws_id)

# ── EVAL ──
print(f"\nQueries: {len(queries)}")
print("=" * 60)

p_at_5s = []
r_at_5s = []
rr_vals = []
for qi, q in enumerate(queries):
    query_text = q["query"]
    relevant = set(q["relevant_ids"])
    
    results = c.search(ws_id, query=query_text, limit=5, semantic=True)
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
    print(f"  Q{qi:02d}: {query_text[:48]:48s} | P5={p5:.2f} R5={r5:.2f} RR={rr:.2f}")

avg_p5 = sum(p_at_5s) / len(p_at_5s) if p_at_5s else 0.0
avg_r5 = sum(r_at_5s) / len(r_at_5s) if r_at_5s else 0.0
avg_rr = sum(rr_vals) / len(rr_vals) if rr_vals else 0.0
perfect = sum(1 for p in p_at_5s if p >= 1.0)

print("=" * 60)
print(f"P@5={avg_p5*100:.1f}%  R@5={avg_r5*100:.1f}%  MRR={avg_rr:.3f}  Perfect={perfect}/{len(queries)}")
print(f"With semantic embeddings (384-dim, all-MiniLM-L6-v2)")
