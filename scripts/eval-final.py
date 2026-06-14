#!/usr/bin/env python3
"""Full pipeline eval with proper entity-ID labels and LLM reranker."""
import json, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sdk", "python"))

import httpx
from spacetime_memory import Client

# Load reranker creds from Hermes .env
_hermes_env = os.path.expanduser("~/.hermes/.env")
if os.path.exists(_hermes_env):
    with open(_hermes_env) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line.startswith("LITELLM_MASTER_KEY="):
                _, _key = _line.split("=", 1)
                os.environ.setdefault("LLM_RERANK_API_KEY", _key.strip().strip('"').strip("'"))
                break
os.environ.setdefault("LLM_RERANK_ENDPOINT", "http://192.168.1.111:4000/v1")
os.environ.setdefault("LLM_RERANK_MODEL", "ds-deepseek-v4-flash")

DB = "c200bd2c4073807f98d79813c26afd931482f2f422a3a860d78d91298ddaa816"
EMB = os.environ.get("EMBEDDER_URL", "http://localhost:9092")
TANTIVY = "http://localhost:9091"

# Single identity
resp = httpx.get(f"http://localhost:3001/v1/database/{DB}", timeout=5)
token = resp.headers.get("spacetime-identity-token", "")
identity = resp.headers.get("spacetime-identity", "")
c = Client(database=DB, embedder_url=EMB, token=token)
try:
    import uuid as _uuid
    c._call("register", [f"eval-{_uuid.uuid4().hex[:8]}", "eval123456", identity])
except Exception:
    pass  # may already be registered from prior run

http = httpx.Client(timeout=10)

# ── Seed with ID tracking ──
ws_name = f"eval-{os.urandom(4).hex()}"
ws = c.create_workspace(ws_name, "Final eval")
WS = ws["id"]
c._call("set_workspace_visibility", [WS, True])

memories = {
    "mem_alice_ceo": "Alice Chen is the CEO and co-founder of Acme AI, previously Engineering Director at Stripe.",
    "mem_bob_cto": "Bob Kumar is the CTO of Acme AI, former Google Brain researcher with 15 years in distributed systems.",
    "mem_funding": "Acme AI raised $45M Series A in March 2025 led by a16z with Sequoia and Greylock.",
    "mem_founded": "Acme AI was founded in January 2024 by Alice Chen and Bob Kumar in San Francisco.",
    "mem_headcount": "The company has 47 employees, 32 in engineering and 15 in GTM.",
    "mem_product": "Acme AI platform provides real-time LLM observability, monitoring latency, token usage, and accuracy across GPT-4, Claude, and Gemini.",
    "mem_integrations": "The product integrates with Datadog, PagerDuty, Slack, and custom webhooks.",
    "mem_scale": "Acme AI processes over 500M inference requests per day with p99 latency under 200ms.",
    "mem_nps": "NPS score is 72 with 94% customer retention and 200+ paying customers.",
    "mem_accuracy": "Acme AI model accuracy shows 23% improvement over competitors on MMLU and HumanEval.",
    "mem_techstack": "The tech stack runs on Kubernetes with Rust inference proxy, PostgreSQL, and ClickHouse.",
    "mem_alice_awards": "Alice Chen won Forbes 30 Under 30 in 2025 and gave a TEDx talk on AI safety.",
    "mem_bob_history": "Bob Kumar worked at Google Brain on TensorFlow Serving for 7 years.",
    "mem_inference_design": "The distributed inference system was designed by Bob Kumar and 4 senior engineers.",
    "mem_customers": "Acme AI customers include Stripe, Notion, Vercel, and 200+ startups.",
    "mem_hiring": "The company is hiring Senior Rust engineer, ML infrastructure engineer, and 3 full-stack roles.",
    "mem_competitor_flowforge": "FlowForge is a competitor with open-source model deployment and weaker observability.",
    "mem_ipaas_market": "iPaaS automation market is $12B by 2027 with 28% CAGR per Gartner.",
    "mem_gdpr": "GDPR data residency is handled via EU ClickHouse clusters for European customers.",
    "mem_flowforge_certs": "FlowForge holds SOC 2 Type II and ISO 27001, Acme AI pursuing SOC 2 in Q3 2025.",
    "mem_latency": "Acme AI guarantees p99 latency of 200ms with 99.95% uptime SLA for enterprise customers.",
    "mem_competitor_comparison": "Compared to competitors, Acme AI offers real-time monitoring, 23% better accuracy, and faster integration.",
    "mem_alice_previous": "Before Acme AI, Alice Chen spent 5 years at Stripe leading ML infrastructure and 3 years at Google.",
    "mem_bob_papers": "Bob Kumar has published 12 papers on distributed inference systems and holds 3 patents.",
    "mem_customer_logos": "Key customers using Acme AI include Stripe (50B tokens/day), Notion, Vercel, and Replit.",
    "mem_market_size": "The LLM observability market is projected to reach $8.4B by 2028 according to industry analysts.",
    "mem_open_source": "Acme AI open-sourced their latency benchmarking toolkit with 2.3K GitHub stars.",
    "mem_office": "Acme AI is headquartered in San Francisco with a satellite office in London for EU operations.",
    "mem_gdpr_detail": "All EU customer data stays in Frankfurt and Dublin ClickHouse clusters for GDPR compliance.",
    "mem_soc2_timeline": "Acme AI's SOC 2 Type II audit is scheduled for completion in September 2025.",
}

# Store and track entity IDs
entity_ids = {}
for key, content in memories.items():
    c.store(workspace_id=WS, content=content, memory_type="world_fact",
            peer_id="eval-final", confidence=0.9)
    # Pull the entity ID by content match
    mems = c._query("memory", workspace_id=WS, columns=["id", "content"])
    for m in reversed(mems):
        if m.get("content") == content:
            entity_ids[key] = m["id"]
            # Index into Tantivy
            http.post(f"{TANTIVY}/index", json={
                "workspace_id": WS, "entity_id": m["id"],
                "content": content, "entity_type": "memory"
            })
            break

print(f"Seeded {len(entity_ids)} memories")

# ── Labeled queries using tracked entity IDs ──
labeled_queries = [
    ("who is the CEO of Acme AI",          ["mem_alice_ceo", "mem_alice_previous"]),
    ("CTO background Google Brain",        ["mem_bob_cto", "mem_bob_history", "mem_bob_papers"]),
    ("funding Series A how much raised",   ["mem_funding"]),
    ("when was Acme AI founded",           ["mem_founded"]),
    ("how many employees headcount",        ["mem_headcount"]),
    ("what does the product monitor",      ["mem_product", "mem_competitor_comparison"]),
    ("what integrations does Acme support", ["mem_integrations"]),
    ("how many requests per day scale",     ["mem_scale"]),
    ("NPS customer satisfaction retention", ["mem_nps"]),
    ("tech stack backend infrastructure",   ["mem_techstack"]),
    ("Alice Chen awards recognition",       ["mem_alice_awards"]),
    ("who are Acme AI customers",           ["mem_customers", "mem_customer_logos"]),
    ("FlowForge security certifications",   ["mem_flowforge_certs"]),
    ("GDPR data residency requirements",    ["mem_gdpr", "mem_gdpr_detail"]),
    ("Bob hiring engineering roles",        ["mem_hiring"]),
    ("iPaaS automation market size",        ["mem_ipaas_market", "mem_market_size"]),
    ("model accuracy compared to competitors", ["mem_accuracy", "mem_competitor_comparison"]),
    ("latency SLA performance p99",         ["mem_latency", "mem_scale"]),
    ("why is Acme better than competitors", ["mem_competitor_comparison", "mem_accuracy", "mem_product"]),
    ("who designed distributed inference system", ["mem_inference_design", "mem_bob_cto"]),
    ("Bob Kumar patents and publications",  ["mem_bob_papers", "mem_bob_cto", "mem_bob_history"]),
    ("Acme AI open source projects",        ["mem_open_source"]),
    ("where is Acme AI headquartered",       ["mem_office", "mem_gdpr_detail"]),
    ("GDPR EU data storage location",        ["mem_gdpr", "mem_gdpr_detail"]),
    ("SOC 2 compliance timeline",            ["mem_soc2_timeline", "mem_flowforge_certs"]),
]

# ── Run eval: no rerank vs rerank ──
def eval_run(queries, rerank):
    p_vals, mrr_vals, times = [], [], []
    details = []
    for query_text, label_keys in queries:
        relevant = {entity_ids[k] for k in label_keys if k in entity_ids}
        t0 = time.time()
        results = c.search(WS, query=query_text, limit=5, semantic=True, rerank=rerank)
        elapsed = time.time() - t0

        retrieved = [r.get("entity_id", r.get("id", "")) for r in results[:5]]
        hits = sum(1 for eid in retrieved if eid in relevant)
        p5 = hits / min(5, max(len(results), 1))
        p_vals.append(p5)

        mrr = 0.0
        for i, eid in enumerate(retrieved, 1):
            if eid in relevant:
                mrr = 1.0 / i
                break
        mrr_vals.append(mrr)
        times.append(elapsed)

        details.append({
            "query": query_text,
            "P@5": round(p5, 2),
            "MRR": round(mrr, 2),
            "relevant": len(relevant),
            "retrieved": hits,
            "time_ms": round(elapsed * 1000),
            "top_3_eids": [e[:12] for e in retrieved[:3]],
        })

    return {
        "P@5": sum(p_vals) / len(p_vals),
        "MRR": sum(mrr_vals) / len(mrr_vals),
        "avg_ms": sum(times) / len(times) * 1000,
        "zero_score": sum(1 for p in p_vals if p == 0),
        "details": details,
    }

r_no = eval_run(labeled_queries, rerank=False)
r_yes = eval_run(labeled_queries, rerank=True)

print(f"\n{'='*65}")
print(f"FINAL EVAL — {len(labeled_queries)} queries, {len(entity_ids)} docs")
print(f"  Embedder: bge-large-en-v1.5 (1024d)")
print(f"  Keyword:  Tantivy Okapi BM25")
print(f"  Fusion:   semantic:0.65, keyword:0.25, graph:0.05, temporal:0.05")
print(f"\n{'Metric':<12} {'No rerank':>10} {'Rerank':>10} {'Delta':>10}")
print(f"{'─'*12} {'─'*10} {'─'*10} {'─'*10}")
print(f"{'P@5':<12} {r_no['P@5']:>9.1%} {r_yes['P@5']:>9.1%} {(r_yes['P@5']-r_no['P@5']):>+9.1%}")
print(f"{'MRR':<12} {r_no['MRR']:>10.3f} {r_yes['MRR']:>10.3f} {(r_yes['MRR']-r_no['MRR']):>+10.3f}")
print(f"{'Latency':<12} {r_no['avg_ms']:>9.0f}ms {r_yes['avg_ms']:>9.0f}ms")
print(f"{'Zero-score':<12} {r_no['zero_score']:>10} {r_yes['zero_score']:>10}")

# Show worst performers
print(f"\nQueries scoring 0% (no rerank):")
for d in r_no["details"]:
    if d["P@5"] == 0:
        print(f"  ✗ {d['query'][:60]}")
print(f"\nQueries scoring 0% (rerank):")
for d in r_yes["details"]:
    if d["P@5"] == 0:
        print(f"  ✗ {d['query'][:60]}")

# Save
result = {
    "config": {
        "embedder": "bge-large-en-v1.5 (1024d)",
        "keyword": "Tantivy Okapi BM25",
        "fusion": "semantic:0.65, keyword:0.25, graph:0.05, temporal:0.05",
        "docs": len(entity_ids),
        "queries": len(labeled_queries),
    },
    "no_rerank": {"P@5": r_no["P@5"], "MRR": r_no["MRR"], "details": r_no["details"]},
    "with_rerank": {"P@5": r_yes["P@5"], "MRR": r_yes["MRR"], "details": r_yes["details"]},
}
with open("/tmp/eval_final.json", "w") as f:
    json.dump(result, f, indent=2)
print(f"\nSaved to /tmp/eval_final.json")
