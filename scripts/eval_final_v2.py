#!/usr/bin/env python3
"""Final eval: Baseline vs Cross-encoder on both Acme AI and Logseq.

LLM features (rerank, query expansion) disabled — DeepSeek via proxy
returns unparseable JSON. Cross-encoder is local ONNX, no API dependency.
"""
import os, sys, time, json, uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))
import httpx
from spacetime_memory import Client

DB = open(os.path.join(os.path.dirname(__file__), "..", "data", "database_identity")).read().strip()
EMB = os.environ.get("EMBEDDER_URL", "http://localhost:9092")
TANTIVY = "http://localhost:9091"

ACME_MEMORIES = {
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

ACME_LABELED = [
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

LOGSEQ_QUERIES = [
    ("Chappy stealth browser backlog", ["Chappy", "backlog"]),
    ("spacetime memory roadmap", ["spacetime", "roadmap"]),
    ("authentication roadmap spacetime", ["Auth Roadmap"]),
    ("CIS benchmarks download", ["CIS", "benchmark"]),
    ("admin dashboard consolidation", ["dashboard"]),
    ("CDP bridge extension", ["CDP Bridge"]),
    ("CLI reference", ["CLI Reference"]),
    ("Auth0 configuration", ["Auth0"]),
    ("Azure self-hosted VMs", ["Azure", "VMs"]),
    ("C Sharp quickstart", ["C#", "Quickstart"]),
    ("browser quickstart guide", ["Browser Quickstart"]),
    ("SpacetimeDB column types", ["Column Types"]),
    ("automatic migrations", ["Automatic Migrations"]),
    ("cheat sheet", ["Cheat Sheet"]),
    ("Clerk authentication", ["Clerk"]),
    ("ask AI chat", ["Ask AI"]),
    ("angular quickstart", ["Angular Quickstart"]),
    ("astro quickstart", ["Astro Quickstart"]),
    ("bun quickstart", ["Bun Quickstart"]),
    ("C++ quickstart", ["C++ Quickstart"]),
]


def run_eval(c, ws, queries, cross_encoder, entity_ids=None, label=""):
    pv, mv, tm, zd = [], [], [], 0
    details = []
    for item in queries:
        if entity_ids:
            query_text, label_keys = item
            relevant = {entity_ids[k] for k in label_keys if k in entity_ids}
        else:
            query_text, terms = item
            relevant = None

        t0 = time.time()
        res = c.search(ws, query=query_text, limit=5, semantic=True,
                      rerank=False, cross_encoder=cross_encoder)
        elapsed = time.time() - t0
        tm.append(elapsed)

        if entity_ids:
            retrieved = [r.get("entity_id", "") for r in res[:5]]
            hits = sum(1 for eid in retrieved if eid in relevant)
        else:
            hits = sum(1 for r in res[:5]
                      if any(t.lower() in r.get("memory_content", "").lower() for t in terms))

        pv.append(hits / min(5, max(len(res), 1)))

        mr = 0.0
        for j, r in enumerate(res):
            matched = False
            if entity_ids:
                matched = r.get("entity_id", "") in relevant
            else:
                matched = any(t.lower() in r.get("memory_content", "").lower() for t in terms)
            if matched:
                mr = 1.0 / (j + 1)
                break
        mv.append(mr)
        if hits == 0:
            zd += 1
            details.append({
                "query": query_text,
                "top3": [r.get("memory_content", "")[:80] for r in res[:3]],
            })

    return {
        "P@5": sum(pv) / len(pv) if pv else 0,
        "MRR": sum(mv) / len(mv) if mv else 0,
        "avg_ms": sum(tm) / len(tm) * 1000 if tm else 0,
        "zeros": zd,
        "total": len(queries),
        "details": details,
    }


def main():
    # Verify CE
    print("Testing cross-encoder...", flush=True)
    from spacetime_memory.cross_encoder import CrossEncoderReranker
    r = CrossEncoderReranker()
    s = r._score_pair("test query", "test passage")
    print(f"  CE OK (score={s:.4f})", flush=True)

    resp = httpx.get(f"http://localhost:3001/v1/database/{DB}", timeout=5)
    token = resp.headers.get("spacetime-identity-token", "")
    identity = resp.headers.get("spacetime-identity", "")
    c = Client(database=DB, embedder_url=EMB, token=token)
    http = httpx.Client(timeout=10)

    peer = f"eval-{uuid.uuid4().hex[:8]}"
    try:
        c._call("register", [peer, "eval123", identity])
    except Exception:
        pass

    all_results = {"config": {"embedder": "bge-large-en-v1.5 (1024d)", "keyword": "Tantivy Okapi BM25", "fusion": "semantic:0.75, keyword:0.25"}}

    # ── Acme AI ──
    print("\n" + "=" * 60)
    print("ACME AI — 30 synthetic docs, 25 labeled queries")
    print("=" * 60)

    ws_name = f"eval-{uuid.uuid4().hex[:6]}"
    ws = c.create_workspace(ws_name, "Acme eval")
    WS_ACME = ws["id"]
    c._call("set_workspace_visibility", [WS_ACME, True])
    eids = {}
    for key, content in ACME_MEMORIES.items():
        c.store(workspace_id=WS_ACME, content=content, memory_type="world_fact", peer_id=peer, confidence=0.9)
        mems = c._query("memory", workspace_id=WS_ACME, columns=["id", "content"])
        for m in reversed(mems):
            if m.get("content") == content:
                eids[key] = m["id"]
                http.post(f"{TANTIVY}/index", json={"workspace_id": WS_ACME, "entity_id": m["id"], "content": content, "entity_type": "memory"})
                break
    print(f"  Seeded {len(eids)} docs", flush=True)

    for ce in [False, True]:
        label = "Cross-encoder" if ce else "Baseline"
        print(f"\n  [{label}]", flush=True)
        r = run_eval(c, WS_ACME, ACME_LABELED, cross_encoder=ce, entity_ids=eids, label=label)
        print(f"    P@5={r['P@5']:.1%}  MRR={r['MRR']:.3f}  {r['avg_ms']:.0f}ms  zeros={r['zeros']}", flush=True)
        if not ce:
            print(f"    Zero-score: {[d['query'] for d in r.get('details', [])]}", flush=True)
    all_results["acme"] = [r]

    # ── Logseq ──
    print("\n" + "=" * 60)
    print("LOGSEQ — 166 real docs, 20 real queries")
    print("=" * 60)

    WS_LOGSEQ = open("/tmp/logseq_workspace_id.txt").read().strip()
    mems = c._query("memory", workspace_id=WS_LOGSEQ, columns=["id"])
    print(f"  {len(mems)} docs in workspace", flush=True)

    logseq_results = {}
    for ce in [False, True]:
        label = "Cross-encoder" if ce else "Baseline"
        print(f"\n  [{label}]", flush=True)
        r = run_eval(c, WS_LOGSEQ, LOGSEQ_QUERIES, cross_encoder=ce, label=label)
        print(f"    P@5={r['P@5']:.1%}  MRR={r['MRR']:.3f}  {r['avg_ms']:.0f}ms  zeros={r['zeros']}", flush=True)
        if not ce:
            print(f"    Zero-score queries:", flush=True)
            for d in r.get("details", []):
                top = d.get("top3", ["N/A"])[0]
                print(f"      ✗ {d['query'][:50]}")
                print(f"        → top: {top[:90]}", flush=True)
        logseq_results[label] = r
    all_results["logseq"] = logseq_results

    # ── Summary ──
    print(f"\n{'='*60}")
    print("FINAL SUMMARY")
    print(f"{'='*60}")
    print(f"  {'Dataset':<25} {'Config':<15} {'P@5':>7} {'MRR':>7} {'Latency':>9} {'Zeros':>5}")
    print(f"  {'─'*25} {'─'*15} {'─'*7} {'─'*7} {'─'*9} {'─'*5}")

    # We'd need to track both acme runs — let me redo this cleanly
    print(f"\nAcme AI (30 docs, 25 queries):")
    for ce in [False, True]:
        label = "Cross-encoder" if ce else "Baseline"
        r = run_eval(c, WS_ACME, ACME_LABELED, cross_encoder=ce, entity_ids=eids, label=label)
        print(f"  {label:<15} {r['P@5']:>6.1%} {r['MRR']:>7.3f} {r['avg_ms']:>8.0f}ms {r['zeros']:>4}")

    print(f"\nLogseq ({len(mems)} docs, 20 queries):")
    for ce in [False, True]:
        label = "Cross-encoder" if ce else "Baseline"
        r = run_eval(c, WS_LOGSEQ, LOGSEQ_QUERIES, cross_encoder=ce, label=label)
        print(f"  {label:<15} {r['P@5']:>6.1%} {r['MRR']:>7.3f} {r['avg_ms']:>8.0f}ms {r['zeros']:>4}")
        if not ce:
            print(f"\n  Zero-score queries (Baseline):")
            for d in r.get("details", []):
                print(f"    ✗ {d['query'][:55]}")
                if d.get("top3"):
                    print(f"      → {d['top3'][0][:90]}")

    with open("/tmp/eval_final_v2.json", "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved to /tmp/eval_final_v2.json")


if __name__ == "__main__":
    main()
