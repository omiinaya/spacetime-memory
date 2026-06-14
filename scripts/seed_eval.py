#!/usr/bin/env python3
"""Full eval pipeline: seed + label + run."""
import json, os, sys, time, uuid
sys.path.insert(0, "/home/user/spacetime-memory/sdk/python")
from spacetime_memory import Client
from spacetime_memory.auth import generate_token

HOST, PORT = "localhost", 3001
DB = "c2007f52296c94e0c7fb057d3cca532ce42a97a15b4820e0c60476a956be95ff"
token = generate_token("/tmp/stdb-data/jwt_priv_pk8.pem")
c = Client(host=HOST, port=PORT, database=DB, token=token)
c._call("login", ["seed_eval", "seedpass123"])

# Create fresh workspace
ws_id = f"eval_{uuid.uuid4().hex[:8]}"
c._call("create_workspace", ["Eval Workspace", "Labeled eval", ws_id])
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

stored = {}
for idx, (content, user) in enumerate(memories):
    args = [ws_id, user, "", "experience", content, content[:200], "{}", 0.5, "", ""]
    try:
        c._call("store_memory", args)
        time.sleep(0.4)
        results = c.search(ws_id, query=content[:80], limit=1, semantic=False)
        if results:
            mem_id = results[0].get("entity_id", "") or results[0].get("id", "")
            stored[f"mem_{idx}"] = mem_id
            print(f"  mem_{idx}: {mem_id[:16]}...")
    except Exception as e:
        print(f"  mem_{idx} FAIL: {e}")

# Retry missing
for idx in range(len(memories)):
    if f"mem_{idx}" not in stored:
        content = memories[idx][0]
        results = c.search(ws_id, query=content[:80], limit=1, semantic=False)
        if results:
            mem_id = results[0].get("entity_id", "") or results[0].get("id", "")
            stored[f"mem_{idx}"] = mem_id

print(f"\nStored: {len(stored)}/{len(memories)}")

# Labeled queries
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

qpath = "/home/user/spacetime-memory/data/eval_queries_labeled.jsonl"
with open(qpath, "w") as f:
    for q in queries:
        f.write(json.dumps(q) + "\n")

with open("/home/user/spacetime-memory/data/eval_workspace_id.txt", "w") as f:
    f.write(ws_id)

print(f"Queries: {qpath} ({len(queries)} labeled)")
print(f"Workspace: {ws_id}")

# ── Run eval harness ──
print("\n" + "="*60)
print("RUNNING EVAL HARNESS")
print("="*60)
