#!/usr/bin/env python3
"""Generate labeled eval dataset.

Populates a workspace with known memories and writes a JSONL file
with queries and their relevant memory IDs for benchmark evaluation.

Usage:
    python3 scripts/generate_eval_dataset.py [--workspace-id <id>] [--output /tmp/queries.jsonl]
"""

from __future__ import annotations

import json
import os
import sys
import uuid

import httpx

for prefix in (".", "..", os.path.expanduser("~/spacetime-memory")):
    sdk_path = os.path.join(prefix, "sdk/python")
    if os.path.isdir(sdk_path):
        sys.path.insert(0, sdk_path)
        break

from spacetime_memory import Client

HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get(
    "SPACETIMEDB_DB",
    "c2007f52296c94e0c7fb057d3cca532ce42a97a15b4820e0c60476a956be95ff",
)

# ── Test data: 50 memories across 5 topic clusters ──────────────────────

MEMORIES_SMALL = [
    # Cluster: Company/People
    ("Alice Chen is the CEO and co-founder of Acme AI, a SaaS platform for enterprise automation.", "world_fact"),
    ("Bob Smith is the CTO of Acme AI and previously worked at Google for 8 years.", "world_fact"),
    ("Acme AI raised a $50M Series B led by Sequoia Capital in January 2025.", "world_fact"),
    ("Acme AI has 120 employees across offices in San Francisco and New York.", "world_fact"),
    ("Carol Davis joined Acme AI as VP of Engineering from Stripe.", "world_fact"),
    ("Acme AI's flagship product is FlowForge, a no-code automation builder.", "world_fact"),
    ("FlowForge supports integration with Salesforce, Slack, and GitHub.", "world_fact"),
    ("Acme AI competes with Zapier and Tray.io in the automation space.", "world_fact"),
    ("The company's revenue grew 300% year-over-year to $12M ARR.", "world_fact"),
    ("Alice Chen holds a PhD in Computer Science from MIT and previously founded two startups.", "world_fact"),

    # Cluster: Funding/Investors
    ("Sequoia Capital led the Series A ($15M) and Series B ($50M) rounds for Acme AI.", "world_fact"),
    ("Peter Thiel's Founders Fund participated in the Series B as a co-investor.", "world_fact"),
    ("The Series B values Acme AI at $350M post-money.", "world_fact"),
    ("Acme AI plans to use the Series B funding to expand into European markets.", "world_fact"),
    ("The company's burn rate is approximately $3M per month with 24 months of runway.", "world_fact"),
    ("Andreessen Horowitz expressed interest in leading a potential Series C in 2026.", "world_fact"),
    ("Acme AI rejected a $200M acquisition offer from Salesforce in November 2025.", "world_fact"),
    ("Y Combinator was Acme AI's first investor in the W23 batch.", "world_fact"),
    ("The company has 4 board seats: 2 founders, 1 Sequoia, 1 independent.", "world_fact"),
    ("Revenue growth is primarily driven by enterprise contracts over $100K annually.", "world_fact"),

    # Cluster: Product/Technology
    ("FlowForge uses a graph-based execution engine written in Rust and TypeScript.", "world_fact"),
    ("The platform processes over 50 million automation steps per day.", "world_fact"),
    ("FlowForge has a built-in AI assistant powered by Llama 3 for natural language automation.", "world_fact"),
    ("The platform's API handles 10,000 requests per second at peak load.", "world_fact"),
    ("Acme AI's engineering team uses SpacetimeDB for real-time state synchronization.", "world_fact"),
    ("FlowForge has SOC 2 Type II certification and GDPR compliance.", "world_fact"),
    ("The platform supports 200+ pre-built connectors for third-party services.", "world_fact"),
    ("Acme AI open-sourced their workflow parser library under MIT license.", "world_fact"),
    ("The engineering team follows a microservices architecture with Kubernetes on AWS.", "world_fact"),
    ("FlowForge's AI assistant can translate natural language into complex workflow graphs.", "world_fact"),

    # Cluster: Customer/Market
    ("Acme AI serves 450 enterprise customers including Stripe, Notion, and Figma.", "world_fact"),
    ("Stripe uses FlowForge to automate billing reconciliation workflows.", "world_fact"),
    ("Notion uses FlowForge for internal HR onboarding automation.", "world_fact"),
    ("Customer NPS score is 72, with 95% annual renewal rate.", "world_fact"),
    ("The largest customer contract is $2M per year with a Fortune 500 bank.", "world_fact"),
    ("Acme AI has a partnership with AWS to offer FlowForge on the AWS Marketplace.", "world_fact"),
    ("The sales team has 35 account executives and uses Salesforce for CRM.", "world_fact"),
    ("Average sales cycle is 45 days for mid-market and 90 days for enterprise.", "world_fact"),
    ("Acme AI sponsors 3 major tech conferences annually for developer outreach.", "world_fact"),
    ("The company blog attracts 50K monthly visitors with technical content about automation.", "world_fact"),

    # Cluster: General/Unrelated (negative examples for precision testing)
    ("The office has an espresso machine in the kitchen on the 3rd floor.", "world_fact"),
    ("Team lunch is every Friday at the Italian restaurant across the street.", "world_fact"),
    ("The San Francisco office has a rooftop terrace with a view of the Bay Bridge.", "world_fact"),
    ("Monthly team building events include bowling, hiking, and board game nights.", "world_fact"),
    ("The company provides a $100 monthly wellness stipend for gym memberships.", "world_fact"),
    ("Free snacks and drinks are available in all office kitchens.", "world_fact"),
    ("The engineering team prefers VS Code over IntelliJ for TypeScript development.", "world_fact"),
    ("Acme AI's mascot is a robotic fox named Flux.", "world_fact"),
    ("The company holiday party is in December at a winery in Napa Valley.", "world_fact"),
    ("Parking is free for employees at both office locations.", "world_fact"),
]

# ── Labeled queries: query → list of relevant memory indices ─────────────

QUERIES_SMALL = [
    # CEO / leadership queries
    {
        "query": "Who is the CEO of Acme AI?",
        "description": "CEO identity",
        "relevant_indices": [0, 9],  # Alice Chen CEO + PhD
    },
    {
        "query": "Acme AI leadership team",
        "description": "Leadership composition",
        "relevant_indices": [0, 1, 4],  # Alice, Bob, Carol
    },
    {
        "query": "What is Alice Chen's background?",
        "description": "CEO background",
        "relevant_indices": [0, 9],
    },

    # Funding queries
    {
        "query": "Acme AI funding rounds",
        "description": "Funding history",
        "relevant_indices": [2, 11, 12, 13],
    },
    {
        "query": "Who invested in Acme AI?",
        "description": "Investors",
        "relevant_indices": [11, 12, 18],
    },
    {
        "query": "What is Acme AI's valuation?",
        "description": "Valuation",
        "relevant_indices": [2, 13],
    },
    {
        "query": "Acme AI revenue and financials",
        "description": "Financial info",
        "relevant_indices": [9, 15, 20],
    },

    # Product queries
    {
        "query": "What is FlowForge?",
        "description": "Product identity",
        "relevant_indices": [6, 7, 21, 22],
    },
    {
        "query": "FlowForge AI assistant capabilities",
        "description": "AI features",
        "relevant_indices": [23, 30],
    },
    {
        "query": "FlowForge integrations and connectors",
        "description": "Integrations",
        "relevant_indices": [7, 27],
    },

    # Technology queries
    {
        "query": "Acme AI technology stack",
        "description": "Tech stack",
        "relevant_indices": [21, 25, 29],
    },

    # Customer queries
    {
        "query": "What companies use Acme AI?",
        "description": "Customer list",
        "relevant_indices": [31, 32, 33],
    },
    {
        "query": "Acme AI enterprise customers",
        "description": "Enterprise customers",
        "relevant_indices": [31, 35],
    },

    # Cross-cutting queries
    {
        "query": "Acme AI company overview",
        "description": "Company summary",
        "relevant_indices": [0, 2, 3, 6, 31],
    },
    {
        "query": "Acme AI growth and scale",
        "description": "Growth metrics",
        "relevant_indices": [8, 9, 22, 31],
    },

    # Negative queries (should not match company data)
    {
        "query": "office amenities",
        "description": "Office perks (negative)",
        "relevant_indices": [41, 45, 46],
    },
    {
        "query": "team events and culture",
        "description": "Culture (negative)",
        "relevant_indices": [42, 43, 44],
    },

    # Entity-specific queries
    {
        "query": "Bob Smith role at Acme AI",
        "description": "CTO identity",
        "relevant_indices": [1],
    },
    {
        "query": "Carol Davis previous company",
        "description": "VP Eng background",
        "relevant_indices": [4],
    },
    {
        "query": "Acme AI Salesforce relationship",
        "description": "Competition/partnership",
        "relevant_indices": [7, 17, 37],
    },
    {
        "query": "Acme AI AWS partnership",
        "description": "Cloud partnership",
        "relevant_indices": [36],
    },
    {
        "query": "Y Combinator Acme AI",
        "description": "YC history",
        "relevant_indices": [18],
    },
    {
        "query": "Stripe connection to Acme AI",
        "description": "Stripe relationship",
        "relevant_indices": [4, 31, 32],
    },
    {
        "query": "Acme AI competitors",
        "description": "Competitors",
        "relevant_indices": [8],
    },

    # Synthesis queries (require multiple sources)
    {
        "query": "Acme AI complete funding history from seed to Series B",
        "description": "Full funding timeline",
        "relevant_indices": [2, 11, 12, 13, 18],
    },
    {
        "query": "Acme AI team and hiring",
        "description": "Team composition",
        "relevant_indices": [0, 1, 3, 4, 37],
    },
    {
        "query": "FlowForge technical architecture",
        "description": "Architecture",
        "relevant_indices": [21, 22, 24, 25, 29],
    },
]

# ── 128 memories across 8 topic clusters (large profile) ─────────────────

MEMORIES_LARGE = [
    # ── Cluster 0: Company/People (indices 0–11) ──
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

    # ── Cluster 1: Funding/Financials (indices 12–27) ──
    ("Acme AI raised a $50M Series B led by Sequoia Capital in January 2025.", "world_fact"),
    ("Sequoia Capital led the Series A ($15M) and Series B ($50M) rounds for Acme AI.", "world_fact"),
    ("Peter Thiel's Founders Fund participated in the Series B as a co-investor.", "world_fact"),
    ("The Series B values Acme AI at $350M post-money.", "world_fact"),
    ("Acme AI plans to use Series B funding to expand into European markets.", "world_fact"),
    ("The company's burn rate is approximately $3M per month with 24 months of runway.", "world_fact"),
    ("Andreessen Horowitz expressed interest in leading a potential Series C in 2026.", "world_fact"),
    ("Acme AI rejected a $200M acquisition offer from Salesforce in November 2025.", "world_fact"),
    ("Y Combinator was Acme AI's first investor in the W23 batch.", "world_fact"),
    ("Revenue growth is primarily driven by enterprise contracts over $100K annually.", "world_fact"),
    ("The company's revenue grew 300% year-over-year to $12M ARR.", "world_fact"),
    ("Acme AI achieved cash-flow positivity in Q4 2025, two quarters ahead of plan.", "world_fact"),
    ("The finance team uses Mercury and QuickBooks for treasury and accounting.", "world_fact"),
    ("R&D spending is $1.8M per month, primarily on GPU compute and engineering salaries.", "world_fact"),
    ("Acme AI has a $5M line of credit with Silicon Valley Bank.", "world_fact"),
    ("The company's gross margin is 78% with a target of 85% by Q4 2026.", "world_fact"),

    # ── Cluster 2: Product (indices 28–43) ──
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

    # ── Cluster 3: Technology (indices 44–59) ──
    ("Acme AI's engineering team uses SpacetimeDB for real-time state synchronization.", "world_fact"),
    ("The engineering team follows a microservices architecture with Kubernetes on AWS.", "world_fact"),
    ("Core services are in Rust, with TypeScript for the frontend and Python for ML pipelines.", "world_fact"),
    ("Vector search uses pgvector with HNSW indexes, managed embeddings dimension 1536.", "world_fact"),
    ("CI/CD uses GitHub Actions with 45-minute build pipelines including integration tests.", "world_fact"),
    ("Monitoring stack is Grafana + Prometheus + Loki with custom SLO dashboards.", "world_fact"),
    ("They use Kafka for event streaming at 200K messages per second.", "world_fact"),
    ("The ML team fine-tunes Llama 3 and Mistral models using LoRA on 8x100A nodes.", "world_fact"),
    ("Acme AI open-sourced their workflow parser library under MIT license.", "world_fact"),
    ("Database tier: PostgreSQL (primary), Redis (cache), S3 (blob), SpacetimeDB (real-time).", "world_fact"),
    ("They run a custom Rust-based feature flag service handling 5M evaluations per second.", "world_fact"),
    ("All services emit OpenTelemetry traces sampled at 10% with Honeycomb for analysis.", "world_fact"),
    ("The infrastructure runs across us-east-1 and eu-west-1 for multi-region resilience.", "world_fact"),
    ("PagerDuty is configured with 5-minute acknowledgement SLAs for critical services.", "world_fact"),
    ("Secrets management uses HashiCorp Vault with automatic rotation every 30 days.", "world_fact"),
    ("Load testing with k6 runs nightly against staging, targeting 2x peak prod traffic.", "world_fact"),
]

# ── 55 labeled queries (large profile) ──────────────────────────────────

QUERIES_LARGE = [
    {"query": "Who is the CEO of Acme AI", "description": "CEO identity", "relevant_indices": [0, 4]},
    {"query": "Acme AI leadership team", "description": "Leadership roster", "relevant_indices": [0, 1, 3, 5, 6]},
    {"query": "Alice Chen background education", "description": "CEO background", "relevant_indices": [0, 4]},
    {"query": "who runs engineering at Acme AI", "description": "VP Eng", "relevant_indices": [1, 3, 9]},

    # ── Funding ──
    {"query": "Acme AI funding rounds history", "description": "Funding timeline", "relevant_indices": [12, 13, 14, 15, 20]},
    {"query": "who invested in Acme AI", "description": "Investors", "relevant_indices": [13, 14, 18, 20]},
    {"query": "Acme AI valuation Series B", "description": "Valuation", "relevant_indices": [12, 15]},
    {"query": "Acme AI revenue ARR financials", "description": "Financial metrics", "relevant_indices": [22, 23, 27]},
    {"query": "Acme AI burn rate runway", "description": "Runway", "relevant_indices": [17]},
    {"query": "Acme AI acquisition offer Salesforce", "description": "Acquisition", "relevant_indices": [19]},
    {"query": "Acme AI gross margin target", "description": "Margins", "relevant_indices": [27]},
    {"query": "Y Combinator Acme AI batch", "description": "YC history", "relevant_indices": [20]},

    # ── Product ──
    {"query": "what is FlowForge product", "description": "Product identity", "relevant_indices": [28, 29, 30, 31]},
    {"query": "FlowForge integrations connectors", "description": "Integrations", "relevant_indices": [29, 35]},
    {"query": "FlowForge AI assistant capabilities", "description": "AI features", "relevant_indices": [32, 36, 39]},
    {"query": "FlowForge security certifications compliance", "description": "Compliance", "relevant_indices": [34, 38, 41]},
    {"query": "FlowForge free tier users conversion", "description": "Free tier", "relevant_indices": [43]},
    {"query": "FlowForge G2 rating reviews", "description": "Reviews", "relevant_indices": [37]},
    {"query": "FlowForge mobile app beta", "description": "Mobile", "relevant_indices": [40]},

    # ── Technology ──
    {"query": "Acme AI technology stack architecture", "description": "Tech stack", "relevant_indices": [44, 45, 46, 52]},
    {"query": "Acme AI infrastructure cloud Kubernetes", "description": "Infra", "relevant_indices": [45, 48, 55]},
    {"query": "Acme AI ML models training fine-tuning", "description": "ML", "relevant_indices": [47, 51]},
    {"query": "Acme AI monitoring observability", "description": "Observability", "relevant_indices": [49, 54]},
    {"query": "Acme AI database tier storage", "description": "Databases", "relevant_indices": [52, 47]},
    {"query": "Acme AI open source MIT license", "description": "OSS", "relevant_indices": [48]},
    {"query": "Acme AI secrets management Vault", "description": "Secrets", "relevant_indices": [55]},
    {"query": "Acme AI load testing k6 staging", "description": "Load testing", "relevant_indices": [56]},

    # ── Customers ──
    {"query": "what companies use Acme AI customers", "description": "Customer list", "relevant_indices": [60, 61, 62, 65, 66]},
    {"query": "Stripe FlowForge use case billing", "description": "Stripe case study", "relevant_indices": [61]},
    {"query": "Acme AI largest customer contract", "description": "Largest deal", "relevant_indices": [64]},
    {"query": "Acme AI customer NPS renewal rate", "description": "Satisfaction", "relevant_indices": [63, 73]},
    {"query": "enterprise customer time to value onboarding", "description": "Onboarding", "relevant_indices": [67, 68]},
    {"query": "Figma FlowForge design tokens", "description": "Figma case study", "relevant_indices": [65]},
    {"query": "Acme AI healthcare HIPAA customer", "description": "Healthcare", "relevant_indices": [75]},
    {"query": "insurance claims processing FlowForge", "description": "Insurance case study", "relevant_indices": [70]},

    # ── Competition ──
    {"query": "Acme AI competitors market", "description": "Competitors", "relevant_indices": [76, 77, 80, 81]},
    {"query": "Acme AI competitive win rate", "description": "Win rates", "relevant_indices": [87]},
    {"query": "iPaaS automation market size growth", "description": "Market size", "relevant_indices": [78, 79]},
    {"query": "Forrester Gartner analyst ranking FlowForge", "description": "Analyst", "relevant_indices": [85, 86]},
    {"query": "Acme AI AWS partnership marketplace", "description": "AWS partnership", "relevant_indices": [82]},

    # ── Security ──
    {"query": "Acme AI SOC 2 compliance audit", "description": "SOC 2", "relevant_indices": [90, 94]},
    {"query": "Acme AI penetration testing security", "description": "Pentest", "relevant_indices": [92]},
    {"query": "Acme AI encryption data protection", "description": "Encryption", "relevant_indices": [93]},
    {"query": "Acme AI GDPR data residency", "description": "GDPR", "relevant_indices": [96]},
    {"query": "Acme AI HackerOne bug bounty", "description": "Bug bounty", "relevant_indices": [97]},

    # ── Negative ──
    {"query": "office amenities perks", "description": "Office perks (negative)", "relevant_indices": [100, 105, 111, 118]},
    {"query": "team events culture activities", "description": "Culture (negative)", "relevant_indices": [103, 104, 112, 115, 120]},
    {"query": "coffee espresso machine office", "description": "Coffee (negative)", "relevant_indices": [100, 117]},
    {"query": "employee wellness gym stipend", "description": "Wellness (negative)", "relevant_indices": [104, 110, 118]},
    {"query": "holiday party napa winery", "description": "Party (negative)", "relevant_indices": [107]},

    # ── Synthesis ──
    {"query": "Acme AI complete company overview", "description": "Full overview", "relevant_indices": [0, 7, 12, 22, 28, 60, 77]},
    {"query": "Acme AI from founding to Series B timeline", "description": "Company timeline", "relevant_indices": [7, 12, 13, 14, 15, 20]},
    {"query": "Acme AI product FlowForge technical architecture", "description": "Architecture deep dive", "relevant_indices": [30, 31, 33, 35, 44, 45, 46, 52]},
    {"query": "Acme AI enterprise sales motion and go-to-market", "description": "GTM", "relevant_indices": [64, 67, 82, 83, 84]},
    {"query": "Acme AI engineering team structure and practices", "description": "Engineering org", "relevant_indices": [1, 3, 9, 45, 46, 48, 49]},
]

# ── Main ────────────────────────────────────────────────────────────────


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Generate labeled eval dataset for retrieval benchmark",
    )
    parser.add_argument(
        "--workspace-id",
        default=None,
        help="Existing workspace ID (random if omitted)",
    )
    parser.add_argument(
        "--output",
        default="/tmp/eval_queries.jsonl",
        help="Output JSONL path",
    )
    parser.add_argument(
        "--populate",
        action="store_true",
        help="Store memories into the workspace (requires running STDB)",
    )
    parser.add_argument(
        "--skip-populate",
        action="store_true",
        help="Skip populating — just generate query file with empty relevant_ids",
    )
    parser.add_argument(
        "--size",
        choices=["small", "large"],
        default="small",
        help="Dataset size: small (50 memories, 25 queries) or large (128 memories, 55 queries)",
    )
    args = parser.parse_args()

    MEMORIES = MEMORIES_LARGE if args.size == "large" else MEMORIES_SMALL
    QUERIES = QUERIES_LARGE if args.size == "large" else QUERIES_SMALL

    client = Client(host=HOST, port=PORT, database=DB)

    # Register with a unique identity — capture token from response
    ident = f"eval_gen_{uuid.uuid4().hex[:8]}"
    token_ok = False
    try:
        resp = httpx.post(
            f"http://{HOST}:{PORT}/v1/database/{DB}/call/register",
            content=json.dumps([ident, "Eval Generator", "evalpass"]),
            headers={"Content-Type": "application/json"},
            timeout=10.0,
        )
        token = resp.headers.get("spacetime-identity-token", "")
        if token:
            client._identity_token = token
            client._identity_established = True
            token_ok = True
    except (OSError, json.JSONDecodeError):
        pass

    if not token_ok:
        print("ERROR: Could not register identity")
        sys.exit(1)

    # Save identity token so eval harness can reuse it
    _token_file = os.getenv("CRON_IDENTITY_TOKEN_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cron_identity_token"))
    with open(_token_file, "w") as f:
        f.write(token)

    ws_id = args.workspace_id
    if not ws_id:
        ws_id = f"eval-{uuid.uuid4().hex[:12]}"
    # Always create fresh workspace with this identity
    client._call("create_workspace", ["eval_benchmark", "auto", ws_id])

    memory_ids: list[str] = []
    if args.populate and not args.skip_populate:
        print(f"Populating workspace {ws_id[:16]}... with {len(MEMORIES)} memories")
        for text, mtype in MEMORIES:
            result = client.store(
                workspace_id=ws_id,
                content=text,
                memory_type=mtype,
                peer_id=ident,
            )
            # Get the memory ID from the stored result
            mems = client._query("memory", workspace_id=ws_id,
                                 filter_dict={"content": text[:60]},
                                 columns=["id"])
            if mems:
                memory_ids.append(mems[-1]["id"])
            else:
                memory_ids.append("")
        print(f"  Stored {len([m for m in memory_ids if m])} memories")
    else:
        print("Skipping population (use --populate to store data).")
        print("Generating queries with placeholder relevant_ids.")
        memory_ids = [f"mem-{i:03d}" for i in range(len(MEMORIES))]

    # Build queries with actual/placeholder IDs
    queries = []
    for q in QUERIES:
        relevant_ids = [
            memory_ids[i]
            for i in q["relevant_indices"]
            if i < len(memory_ids) and memory_ids[i]
        ]
        queries.append({
            "query": q["query"],
            "description": q["description"],
            "relevant_ids": relevant_ids,
        })

    # Write JSONL
    with open(args.output, "w") as f:
        for q in queries:
            f.write(json.dumps(q) + "\n")

    print(f"Wrote {len(queries)} queries to {args.output}")
    print(f"Workspace ID: {ws_id}")
    # Save workspace ID so eval harness can auto-detect
    with open("/tmp/eval_workspace.txt", "w") as f:
        f.write(ws_id)
    if args.populate and not args.skip_populate:
        print(f"\nRun eval with:")
        print(f"  python3 scripts/eval_unified.py --workspace-id {ws_id} --queries-file {args.output}")


if __name__ == "__main__":
    main()
