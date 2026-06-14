#!/usr/bin/env python3
"""Seed + eval in one script — single identity throughout."""
import json, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sdk", "python"))

import httpx
from spacetime_memory import Client

DB = "c200bd2c4073807f98d79813c26afd931482f2f422a3a860d78d91298ddaa816"
EMB = os.environ.get("EMBEDDER_URL", "http://localhost:9092")
TANTIVY = "http://localhost:9091"

# Single identity for everything
resp = httpx.get(f"http://localhost:3001/v1/database/{DB}", timeout=5)
token = resp.headers.get("spacetime-identity-token", "")
identity = resp.headers.get("spacetime-identity", "")
c = Client(database=DB, embedder_url=EMB, token=token)
try:
    c._call("register", ["eval-all", "eval123456", identity])
except Exception:
    pass

# ── Seed ──
ws_name = f"eval-{os.urandom(4).hex()}"
ws = c.create_workspace(ws_name, "Eval workspace")
WS = ws["id"]
print(f"Workspace: {WS[:16]}...")

# Make public so searches work without ownership
c._call("set_workspace_visibility", [WS, True])

memories = [
    "Alice Chen is the CEO and co-founder of Acme AI, previously Engineering Director at Stripe.",
    "Bob Kumar is the CTO of Acme AI, former Google Brain researcher with 15 years in distributed systems.",
    "Acme AI raised $45M Series A in March 2025 led by a16z with Sequoia and Greylock.",
    "Acme AI was founded in January 2024 by Alice Chen and Bob Kumar in San Francisco.",
    "The company has 47 employees, 32 in engineering and 15 in GTM.",
    "Acme AI platform provides real-time LLM observability, monitoring latency, token usage, and accuracy across GPT-4, Claude, and Gemini.",
    "The product integrates with Datadog, PagerDuty, Slack, and custom webhooks.",
    "Acme AI processes over 500M inference requests per day with p99 latency under 200ms.",
    "NPS score is 72 with 94% customer retention and 200+ paying customers.",
    "Acme AI model accuracy shows 23% improvement over competitors on MMLU and HumanEval.",
    "The tech stack runs on Kubernetes with Rust inference proxy, PostgreSQL, and ClickHouse.",
    "Alice Chen won Forbes 30 Under 30 in 2025 and gave a TEDx talk on AI safety.",
    "Bob Kumar worked at Google Brain on TensorFlow Serving for 7 years.",
    "The distributed inference system was designed by Bob Kumar and 4 senior engineers.",
    "Acme AI customers include Stripe, Notion, Vercel, and 200+ startups.",
    "The company is hiring Senior Rust engineer, ML infrastructure engineer, and 3 full-stack roles.",
    "FlowForge is a competitor with open-source model deployment and weaker observability.",
    "iPaaS automation market is $12B by 2027 with 28% CAGR per Gartner.",
    "GDPR data residency is handled via EU ClickHouse clusters for European customers.",
    "FlowForge holds SOC 2 Type II and ISO 27001, Acme AI pursuing SOC 2 in Q3 2025.",
]

http = httpx.Client(timeout=10)
mem_ids = []
for i, content in enumerate(memories):
    r = c.store(workspace_id=WS, content=content, memory_type="world_fact",
                peer_id="eval-all", confidence=0.9)
    # Pull the memory ID
    mems = c._query("memory", workspace_id=WS, columns=["id", "content"])
    for m in reversed(mems):
        if m.get("content") == content:
            mem_ids.append(m["id"])
            # Index into Tantivy
            http.post(f"{TANTIVY}/index", json={
                "workspace_id": WS, "entity_id": m["id"],
                "content": content, "entity_type": "memory"
            })
            break
    if (i + 1) % 5 == 0:
        print(f"  Seeded {i+1}/{len(memories)}")

print(f"\nSeeded {len(mem_ids)} memories")

# ── Eval ──
queries = [
    ("who is the CEO of Acme AI", ["Alice Chen"]),
    ("CTO background at Google", ["Bob Kumar", "Google Brain"]),
    ("funding Series A amount raised", ["$45M", "Series A"]),
    ("Acme AI founded when year", ["January 2024"]),
    ("how many employees headcount", ["47 employees"]),
    ("what does the product monitor", ["LLM observability", "latency", "token usage"]),
    ("what integrations does the product support", ["Datadog", "PagerDuty", "Slack"]),
    ("how many requests per day scale", ["500M", "inference requests"]),
    ("NPS score customer satisfaction", ["NPS", "72", "94%"]),
    ("tech stack backend infrastructure", ["Kubernetes", "Rust", "PostgreSQL", "ClickHouse"]),
    ("Alice awards recognition", ["Forbes 30 Under 30", "TEDx"]),
    ("who are the customers of Acme", ["Stripe", "Notion", "Vercel"]),
    ("FlowForge security certifications", ["SOC 2", "ISO 27001"]),
    ("GDPR data residency requirements", ["EU", "ClickHouse"]),
    ("Bob hiring what engineering roles", ["Senior Rust", "ML infrastructure", "full-stack"]),
    ("iPaaS automation market size", ["$12B", "Gartner"]),
    ("model accuracy compared to competitors", ["23%", "MMLU", "HumanEval"]),
    ("latency SLA performance p99", ["p99", "200ms"]),
    ("why is Acme better than competitors", ["23% improvement", "real-time"]),
    ("who designed the distributed inference system", ["Bob Kumar", "distributed inference"]),
]

p_at_5 = []
mrr_vals = []
total_time = 0
details = []

for query_text, expected_terms in queries:
    t0 = time.time()
    results = c.search(WS, query=query_text, limit=5, semantic=True, rerank=False, cross_encoder=False)
    elapsed = time.time() - t0
    total_time += elapsed

    hits = 0
    top_content = []
    for r in results[:5]:
        content = r.get("memory_content", r.get("content", ""))
        top_content.append(content[:80])
        for term in expected_terms:
            if term.lower() in content.lower():
                hits += 1
                break

    p5 = hits / min(5, max(len(results), 1))
    p_at_5.append(p5)

    mrr = 0.0
    for i, r in enumerate(results, 1):
        content = r.get("memory_content", r.get("content", ""))
        if any(t.lower() in content.lower() for t in expected_terms):
            mrr = 1.0 / i
            break
    mrr_vals.append(mrr)

    details.append({
        "query": query_text,
        "P@5": round(p5, 2),
        "MRR": round(mrr, 2),
        "top_hit": top_content[0] if top_content else "",
        "time_ms": round(elapsed * 1000),
    })

avg_p5 = sum(p_at_5) / len(p_at_5)
avg_mrr = sum(mrr_vals) / len(mrr_vals)
avg_time = total_time / len(queries)

print(f"\n{'='*60}")
print(f"Eval Results ({len(queries)} queries, no rerank)")
print(f"  P@5:  {avg_p5:.1%}")
print(f"  MRR:  {avg_mrr:.3f}")
print(f"  Avg latency: {avg_time*1000:.0f}ms")
print(f"\nPer-query:")
for d in details:
    s = "✓" if d["P@5"] > 0 else "✗"
    print(f"  {s} P@5={d['P@5']:.0%} MRR={d['MRR']:.2f} | {d['query'][:55]}")

with open("/tmp/eval_tantivy_bge.json", "w") as f:
    json.dump({
        "config": {
            "embedder": "bge-large-en-v1.5 (1024d)",
            "keyword": "Tantivy Okapi BM25",
            "fusion": "semantic:0.65, keyword:0.25, graph:0.05, temporal:0.05",
        },
        "summary": {"P@5": round(avg_p5, 3), "MRR": round(avg_mrr, 3)},
        "details": details,
    }, f, indent=2)
print(f"\nSaved to /tmp/eval_tantivy_bge.json")
