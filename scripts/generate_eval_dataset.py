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

for prefix in (".", "..", "/home/user/spacetime-memory"):
    sdk_path = os.path.join(prefix, "sdk/python")
    if os.path.isdir(sdk_path):
        sys.path.insert(0, sdk_path)
        break

from spacetime_memory import Client

HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get(
    "SPACETIMEDB_DB",
    "c200f8da0f062b67001165d9379b9e2125dd73a7be4a0b1a1e4374d00cbcc079",
)

# ── Test data: 50 memories across 5 topic clusters ──────────────────────

MEMORIES = [
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

QUERIES = [
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
    args = parser.parse_args()

    client = Client(host=HOST, port=PORT, database=DB)

    # Register if needed
    try:
        client._call("register", ["eval_generator", "Eval Generator", "evalpass"])
    except RuntimeError:
        pass

    ws_id = args.workspace_id
    if not ws_id:
        ws_id = f"eval-{uuid.uuid4().hex[:12]}"
        try:
            client._call("create_workspace", ["eval_benchmark", "auto", ws_id])
        except RuntimeError:
            pass

    memory_ids: list[str] = []
    if args.populate and not args.skip_populate:
        print(f"Populating workspace {ws_id[:16]}... with {len(MEMORIES)} memories")
        for text, mtype in MEMORIES:
            result = client.store(
                workspace_id=ws_id,
                content=text,
                memory_type=mtype,
                peer_id="eval_generator",
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
    if args.populate and not args.skip_populate:
        print(f"\nRun eval with:")
        print(f"  python3 scripts/eval_harness.py --workspace-id {ws_id} --queries-file {args.output}")


if __name__ == "__main__":
    main()
