#!/usr/bin/env python3
"""Run retrieval eval with labeled queries."""
import json, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sdk", "python"))

import httpx
from spacetime_memory import Client

DB = "c200bd2c4073807f98d79813c26afd931482f2f422a3a860d78d91298ddaa816"
WS = "91808a58e6cd42c8abd1854b55ce6ba7"
EMB = os.environ.get("EMBEDDER_URL", "http://localhost:9092")

# Auth
resp = httpx.get(f"http://localhost:3001/v1/database/{DB}", timeout=5)
token = resp.headers.get("spacetime-identity-token", "")
identity = resp.headers.get("spacetime-identity", "")
c = Client(database=DB, embedder_url=EMB, token=token)
try:
    c._call("register", ["eval-runner", "eval123", identity])
except Exception:
    pass

# Labeled queries — each query with terms that SHOULD appear in top results
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
    ("GDPR data residency requirements", ["EU", "ClickHouse", "data residency"]),
    ("Bob hiring what engineering roles", ["Senior Rust", "ML infrastructure", "full-stack"]),
    ("iPaaS automation market size", ["$12B", "2027", "Gartner"]),
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

    # Score: does the content contain expected terms?
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

    # MRR
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

print(f"\n=== Eval Results ({len(queries)} queries, no rerank) ===")
print(f"P@5:  {avg_p5:.1%}")
print(f"MRR:  {avg_mrr:.3f}")
print(f"Avg latency: {avg_time*1000:.0f}ms")
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
print("\nSaved to /tmp/eval_tantivy_bge.json")
