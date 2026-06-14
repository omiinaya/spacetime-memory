#!/usr/bin/env python3
"""Unified eval: register → populate → eval in one session (same identity)."""
from __future__ import annotations
import json, os, sys, uuid, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sdk/python"))
from spacetime_memory import Client

DB = os.environ.get("SPACETIMEDB_DB", "c200fe986403098f176a63cb3b581d183d2083f0b2885c0c3af656706df9a217")
HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
QUERIES_FILE = os.environ.get("EVAL_QUERIES", "/tmp/eval_queries_xlarge.jsonl")

MEMORIES = [
    ("Alice Chen is the CEO and co-founder of Acme AI, a SaaS platform for enterprise automation.", "world_fact"),
    ("Bob Smith is the CTO of Acme AI and previously worked at Google for 8 years.", "world_fact"),
    ("Acme AI has 120 employees across offices in San Francisco and New York.", "world_fact"),
    ("Carol Davis joined Acme AI as VP of Engineering from Stripe.", "world_fact"),
    ("Alice Chen holds a PhD in CS from MIT and previously founded two startups.", "world_fact"),
    ("Dave Kim is the Head of Product, formerly a PM at Figma for 4 years.", "world_fact"),
    ("Elena Vargas is the VP of Sales, with 15 years experience at Salesforce and Oracle.", "world_fact"),
    ("The company was founded in March 2022 in San Francisco by Alice and Bob.", "world_fact"),
    ("Acme AI's board includes Alice Chen, Bob Smith, a Sequoia partner, and an independent director.", "world_fact"),
    ("The engineering org is 55 people split across platform, AI, and infrastructure teams.", "world_fact"),
    ("HR is run by Fatima Osei who built the people operations team from 0 to 120.", "world_fact"),
    ("Acme AI has a remote-first policy with quarterly offsites in Sonoma.", "world_fact"),
    ("Acme AI raised a $50M Series B led by Sequoia Capital in January 2025.", "world_fact"),
    ("Sequoia Capital led the Series A ($15M) and Series B ($50M) rounds for Acme AI.", "world_fact"),
    ("Peter Thiel's Founders Fund participated in the Series B as a co-investor.", "world_fact"),
    ("The Series B values Acme AI at $350M post-money.", "world_fact"),
    ("Acme AI plans to use Series B funding to expand into European markets.", "world_fact"),
    ("The company's burn rate is approximately $3M per month with 24 months of runway.", "world_fact"),
    ("Andreessen Horowitz expressed interest in leading a potential Series C in 2026.", "world_fact"),
    ("Acme AI rejected a $200M acquisition offer from Salesforce in November 2025.", "world_fact"),
    ("The company was in Y Combinator's Winter 2023 batch alongside 200 other startups.", "world_fact"),
    ("Seed round of $3M was raised in March 2023 from YC, a16z scout, and angel investors.", "world_fact"),
    ("ARR reached $22M in Q1 2026, up from $8M in Q1 2025.", "world_fact"),
    ("Monthly recurring revenue is $1.9M with 98% gross dollar retention.", "world_fact"),
    ("The company has 340 paying customers across Free, Pro, and Enterprise plans.", "world_fact"),
    ("Average contract value is $65K for Pro and $350K for Enterprise.", "world_fact"),
    ("R&D spending is $1.8M per month, primarily on GPU compute and engineering salaries.", "world_fact"),
    ("Acme AI has a $5M line of credit with Silicon Valley Bank.", "world_fact"),
    ("The company's gross margin is 78% with a target of 85% by Q4 2026.", "world_fact"),
    ("Acme AI's flagship product is FlowForge, a no-code automation builder.", "world_fact"),
    ("FlowForge supports integration with Salesforce, Slack, GitHub, and Jira.", "world_fact"),
    ("FlowForge uses a graph-based execution engine written in Rust and TypeScript.", "world_fact"),
    ("The platform processes over 50 million automation steps per day.", "world_fact"),
    ("FlowForge has a built-in AI assistant powered by Llama 3 for natural language automation.", "world_fact"),
    ("The platform's API handles 10,000 requests per second at peak load on AWS.", "world_fact"),
    ("FlowForge has SOC 2 Type II certification and GDPR compliance.", "world_fact"),
    ("The platform supports 200+ pre-built connectors for third-party services.", "world_fact"),
    ("FlowForge's AI assistant can translate natural language into complex workflow graphs.", "world_fact"),
    ("The product has a 4.8 star rating on G2 with 350+ reviews.", "world_fact"),
    ("FlowForge offers an on-premise deployment option for regulated industries.", "world_fact"),
    ("A new feature called FlowPredict uses ML to suggest next steps in automation chains.", "world_fact"),
    ("The mobile companion app for FlowForge launched in beta in March 2026.", "world_fact"),
    ("FlowForge supports SSO via SAML, OIDC, and Azure AD.", "world_fact"),
    ("The product ships bi-weekly with a canary deployment pipeline.", "world_fact"),
    ("FlowForge's free tier has 50K active users and converts at 12% to paid plans.", "world_fact"),
    ("Acme AI's engineering team uses SpacetimeDB for real-time state synchronization.", "world_fact"),
    ("The engineering team follows a microservices architecture with Kubernetes on AWS.", "world_fact"),
    ("Core services are in Rust, with TypeScript for the frontend and Python for ML pipelines.", "world_fact"),
    ("Vector search uses pgvector with HNSW indexes, managed embeddings dimension 1536.", "world_fact"),
    ("CI/CD uses GitHub Actions with 45-minute build pipelines including integration tests.", "world_fact"),
    ("Monitoring stack is Grafana + Prometheus + Loki with custom SLO dashboards.", "world_fact"),
    ("They use Kafka for event streaming at 200K messages per second.", "world_fact"),
    ("The ML team fine-tunes Llama 3 and Mistral models using LoRA on 8×A100 nodes.", "world_fact"),
    ("Acme AI open-sourced their workflow parser library under MIT license.", "world_fact"),
    ("Database tier: PostgreSQL (primary), Redis (cache), S3 (blob), SpacetimeDB (real-time).", "world_fact"),
    ("They run a custom Rust-based feature flag service handling 5M evaluations per second.", "world_fact"),
    ("All services emit OpenTelemetry traces sampled at 10% with Honeycomb for analysis.", "world_fact"),
    ("The infrastructure runs across us-east-1 and eu-west-1 for multi-region resilience.", "world_fact"),
    ("PagerDuty is configured with 5-minute acknowledgement SLAs for critical services.", "world_fact"),
    ("Secrets management uses HashiCorp Vault with automatic rotation every 30 days.", "world_fact"),
    ("Load testing with k6 runs nightly against staging, targeting 2× peak prod traffic.", "world_fact"),
    ("Acme AI serves 450 enterprise customers including Stripe, Notion, Figma, and Vercel.", "world_fact"),
    ("Stripe uses FlowForge to automate billing reconciliation workflows, saving 200 hours/month.", "world_fact"),
    ("Notion uses FlowForge for internal HR onboarding automation, handling 500 new hires/year.", "world_fact"),
    ("Customer NPS score is 72, with 95% annual renewal rate across all tiers.", "world_fact"),
    ("The largest customer contract is $2M per year with a Fortune 500 bank.", "world_fact"),
    ("Figma uses FlowForge to sync design tokens across 15 internal tools.", "world_fact"),
    ("Vercel built a deployment approval chain with FlowForge that reduced incidents by 40%.", "world_fact"),
    ("Average time-to-value for enterprise customers is 3 weeks including integration.", "world_fact"),
    ("The customer success team is 12 people with a 4-hour response SLA.", "world_fact"),
    ("Enterprise customers average 45 minutes saved per employee per week through automation.", "world_fact"),
    ("A major insurance company reduced claims processing from 8 days to 6 hours with FlowForge.", "world_fact"),
    ("Three of the top 10 US banks are in active evaluation for FlowForge enterprise.", "world_fact"),
    ("Acme AI has a 98% logo retention rate among accounts over $100K ARR.", "world_fact"),
    ("The customer advisory board meets quarterly with 15 executive sponsors from top accounts.", "world_fact"),
    ("Referral traffic from existing customers accounts for 35% of new enterprise pipeline.", "world_fact"),
    ("A healthcare customer achieved HIPAA compliance for their FlowForge workflows in 6 weeks.", "world_fact"),
    ("Acme AI competes with Zapier, Tray.io, and Workato in the automation space.", "world_fact"),
    ("Main differentiator is AI-first approach vs competitors' rule-based engines.", "world_fact"),
    ("The iPaaS market is $12B in 2025 growing at 28% CAGR.", "world_fact"),
    ("Acme AI has 4% market share in enterprise automation, targeting 10% by 2027.", "world_fact"),
    ("Zapier recently launched a limited AI feature but lacks graph-based execution.", "world_fact"),
    ("Tray.io raised $100M but has higher churn due to complexity of their builder.", "world_fact"),
    ("Acme AI has a partnership with AWS to offer FlowForge on the AWS Marketplace.", "world_fact"),
    ("The sales team has 35 account executives and uses Salesforce for CRM.", "world_fact"),
    ("Average sales cycle is 45 days for mid-market and 90 days for enterprise.", "world_fact"),
    ("The company blog attracts 50K monthly visitors with technical content about automation.", "world_fact"),
    ("Acme AI sponsors 3 major tech conferences annually for developer outreach.", "world_fact"),
    ("The company has analyst coverage from Gartner (Visionary quadrant) and Forrester (Strong Performer).", "world_fact"),
    ("A recent Forrester report ranked FlowForge #1 in 'time to value' among 12 vendors.", "world_fact"),
    ("Competitive win rate against Zapier is 62%, against Tray.io is 45%.", "world_fact"),
    ("Acme AI completed SOC 2 Type II audit in March 2025 with zero exceptions.", "world_fact"),
    ("The company is ISO 27001 certified as of September 2025.", "world_fact"),
    ("Penetration testing is conducted quarterly by Bishop Fox, last test found 2 medium issues.", "world_fact"),
    ("Data is encrypted at rest with AES-256 and in transit with TLS 1.3.", "world_fact"),
    ("Customer data is never used for model training unless explicitly opted in.", "world_fact"),
    ("The security team has 4 engineers and a dedicated CISO reporting to the CEO.", "world_fact"),
    ("SOC 2 Type II scope covers the entire FlowForge platform and corporate infrastructure.", "world_fact"),
    ("All employees complete security awareness training quarterly with phishing simulations.", "world_fact"),
    ("GDPR compliance includes data residency options in EU, US, and APAC regions.", "world_fact"),
    ("Vulnerability disclosure program on HackerOne has paid $45K in bounties across 28 reports.", "world_fact"),
]


def main():
    client = Client(host=HOST, port=PORT, database=DB)

    # Register
    uid = uuid.uuid4().hex[:8]
    uname = f"eval_{uid}"
    try:
        client._call("register", [uname, "Eval Runner", "evalpass"])
    except RuntimeError:
        try:
            client._call("login", [uname, "evalpass"])
        except RuntimeError:
            print("Auth failed")
            sys.exit(1)

    # Create workspace
    ws_id = f"eval-uni-{uuid.uuid4().hex[:8]}"
    client._call("create_workspace", ["eval_unified", "desc", ws_id])
    print(f"Workspace: {ws_id}")

    # Populate
    memory_ids = []
    t0 = time.time()
    for i, (text, mtype) in enumerate(MEMORIES):
        try:
            client.store(workspace_id=ws_id, content=text, memory_type=mtype, peer_id=uname)
        except Exception as e:
            print(f"  [{i}] store FAILED: {e}")
            memory_ids.append("")
            continue
        # Resolve ID
        try:
            mems = client._query("memory", workspace_id=ws_id, filter_dict={}, columns=["id", "content"])
            matched = None
            for m in mems:
                if m.get("content", "")[:60] == text[:60]:
                    matched = m["id"]
                    break
            memory_ids.append(matched or "")
        except Exception:
            memory_ids.append("")
    dt = time.time() - t0
    stored = len([m for m in memory_ids if m])
    print(f"Stored {stored}/{len(MEMORIES)} memories in {dt:.1f}s")

    # Build queries
    QUERIES = [
        {"query": "Who is the CEO of Acme AI", "description": "CEO identity", "relevant_indices": [0, 4]},
        {"query": "Acme AI leadership team", "description": "Leadership roster", "relevant_indices": [0, 1, 3, 5, 6]},
        {"query": "Alice Chen background education", "description": "CEO background", "relevant_indices": [0, 4]},
        {"query": "who runs engineering at Acme AI", "description": "VP Eng", "relevant_indices": [1, 3, 9]},
        {"query": "Acme AI funding rounds history", "description": "Funding timeline", "relevant_indices": [12, 13, 14, 15, 20]},
        {"query": "who invested in Acme AI", "description": "Investors", "relevant_indices": [13, 14, 18, 20]},
        {"query": "Acme AI valuation Series B", "description": "Valuation", "relevant_indices": [12, 15]},
        {"query": "Acme AI revenue ARR financials", "description": "Financial metrics", "relevant_indices": [22, 23, 27]},
        {"query": "Acme AI burn rate runway", "description": "Runway", "relevant_indices": [17]},
        {"query": "Acme AI acquisition offer Salesforce", "description": "Acquisition", "relevant_indices": [19]},
        {"query": "what is FlowForge product", "description": "Product identity", "relevant_indices": [29, 30, 31, 32]},
        {"query": "FlowForge integrations connectors", "description": "Integrations", "relevant_indices": [30, 36]},
        {"query": "FlowForge AI assistant capabilities", "description": "AI features", "relevant_indices": [33, 37, 40]},
        {"query": "Acme AI technology stack architecture", "description": "Tech stack", "relevant_indices": [45, 46, 47, 53]},
        {"query": "Acme AI infrastructure cloud Kubernetes", "description": "Infra", "relevant_indices": [46, 49, 56]},
        {"query": "what companies use Acme AI customers", "description": "Customer list", "relevant_indices": [61, 62, 63, 66, 67]},
        {"query": "Acme AI competitors market", "description": "Competitors", "relevant_indices": [77, 78, 81, 82]},
        {"query": "Acme AI SOC 2 compliance audit", "description": "SOC 2", "relevant_indices": [91, 95]},
        {"query": "Acme AI encryption data protection", "description": "Encryption", "relevant_indices": [94]},
        {"query": "Acme AI complete company overview", "description": "Full overview", "relevant_indices": [0, 7, 12, 22, 29, 61, 78]},
    ]

    queries_out = []
    for q in QUERIES:
        rids = [memory_ids[i] for i in q["relevant_indices"] if i < len(memory_ids) and memory_ids[i]]
        queries_out.append({"query": q["query"], "description": q["description"], "relevant_ids": rids})

    # Run eval
    print(f"\nEval — {len(queries_out)} queries, K=5")
    p5_total = r5_total = mrr_total = 0.0
    count = 0

    for q in queries_out:
        try:
            results = client.search(ws_id, query=q["query"], limit=10, semantic=True, rerank=True)
        except Exception as e:
            print(f"  Search error: {e}")
            continue

        found = [r.get("entity_id", "") for r in results]
        relevant = set(q["relevant_ids"])
        hits = [eid for eid in found if eid in relevant]

        p5 = len(hits) / min(5, len(found)) if found else 0
        r5 = len(hits) / len(relevant) if relevant else 0
        mrr = 0.0
        for rank, eid in enumerate(found, 1):
            if eid in relevant:
                mrr = 1.0 / rank
                break

        p5_total += p5
        r5_total += r5
        mrr_total += mrr
        count += 1
        qname = q["query"][:40]
        print(f"  {qname:<40}  P@5={p5:.1%}  R@5={r5:.1%}  MRR={mrr:.2f}")

    if count:
        print(f"\n  Average: P@5={p5_total/count:.1%}  R@5={r5_total/count:.1%}  MRR={mrr_total/count:.3f}")

    # Write queries file for future use
    with open(QUERIES_FILE, "w") as f:
        for q in queries_out:
            f.write(json.dumps(q) + "\n")
    print(f"Queries: {QUERIES_FILE}")
    print(f"Workspace: {ws_id}")


if __name__ == "__main__":
    main()
