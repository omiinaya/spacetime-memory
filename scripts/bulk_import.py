#!/usr/bin/env python3
"""Bulk import memories with retries, skipping auto-index to survive embedder crashes."""
import json, os, sys, uuid, time

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk", "python"))
from spacetime_memory.client import Client

HOST, PORT = "localhost", "3001"
DB = "c2007f52296c94e0c7fb057d3cca532ce42a97a15b4820e0c60476a956be95ff"

MEMORIES = [
    ("Alice Chen is the CEO and co-founder of Acme AI, an iPaaS company based in San Francisco", "fact"),
    ("Bob Martinez is the CTO of Acme AI, previously Engineering Director at Google Cloud", "fact"),
    ("Carol Wu is the VP of Engineering at Acme AI, leading the 15-person eng team", "fact"),
    ("David Kim is the Head of Product at Acme AI, formerly at Stripe", "fact"),
    ("Acme AI was founded in 2019 by Alice Chen and two co-founders from Stanford", "fact"),
    ("Acme AI is an enterprise integration-platform-as-a-service (iPaaS) company", "fact"),
    ("Acme AI's product is called FlowForge, a visual workflow automation platform", "fact"),
    ("FlowForge competes with Zapier, Make, and Tray.io in the iPaaS market", "fact"),
    ("Acme AI has grown to 45 employees as of 2024", "fact"),
    ("Acme AI's annual recurring revenue reached $3.2M in 2023", "fact"),
    ("Alice Chen has a background in computer science from Stanford and previously worked at Palantir", "fact"),
    ("Acme AI raised a $2M seed round led by Y Combinator in 2020", "fact"),
    ("Acme AI raised a $12M Series A round led by Andreessen Horowitz (a16z) in 2022", "fact"),
    ("Acme AI raised a $45M Series B round led by Sequoia Capital at a $350M valuation in 2024", "fact"),
    ("Acme AI has raised a total of $59M across seed, Series A, and Series B rounds", "fact"),
    ("Acme AI's monthly burn rate is approximately $350K", "fact"),
    ("Acme AI has about 14 months of runway at current burn rate", "fact"),
    ("Acme AI received an acquisition offer from Salesforce for $250M in 2024, but declined", "fact"),
    ("Y Combinator invested in Acme AI during the W20 batch", "fact"),
    ("Acme AI was named a Gartner Cool Vendor in iPaaS for 2023", "fact"),
    ("Acme AI targets a gross margin of 75% on their enterprise tier", "fact"),
    ("FlowForge is built on a microservices architecture using Kubernetes and AWS", "fact"),
    ("FlowForge supports over 200 pre-built connectors including Salesforce, Stripe, and Shopify", "fact"),
    ("FlowForge includes an AI assistant powered by GPT-4 for workflow generation", "fact"),
    ("FlowForge uses PostgreSQL as its primary database with Redis for caching", "fact"),
    ("Acme AI's infrastructure runs on AWS with Kubernetes (EKS) for orchestration", "fact"),
    ("FlowForge uses Kafka for event streaming between microservices", "fact"),
    ("FlowForge integrates natively with Salesforce CRM for customer data sync", "fact"),
    ("FlowForge offers a visual drag-and-drop workflow builder for non-technical users", "fact"),
    ("Acme AI uses Terraform for infrastructure-as-code and GitHub Actions for CI/CD", "fact"),
    ("FlowForge includes AI-powered data transformation and mapping suggestions", "fact"),
    ("Stripe is the largest FlowForge customer, using it for payment workflow automation", "fact"),
    ("Shopify uses FlowForge for order fulfillment automation across their marketplace", "fact"),
    ("Figma uses FlowForge to sync design tokens with their component library", "fact"),
    ("Acme AI's largest enterprise contract is with Stripe at $450K/year", "fact"),
    ("Enterprise customers report 60% faster integration development with FlowForge", "fact"),
    ("Acme AI has an AWS partnership and is listed on the AWS Marketplace", "fact"),
    ("Acme AI is hiring for senior engineers, with competitive compensation including equity", "fact"),
    ("Acme AI achieved SOC 2 Type II compliance in 2024", "fact"),
    ("Acme AI's customer NPS score is 72 as of Q3 2024", "fact"),
    ("Enterprise customer time-to-value with FlowForge averages 4 weeks for full deployment", "fact"),
    ("Acme AI offers stock options, daily catered lunch, and a gym stipend", "fact"),
    ("The Acme AI office has a cold brew coffee machine and weekly happy hours", "fact"),
    ("Acme AI's annual holiday party was held at a winery in Napa Valley", "fact"),
    ("Acme AI holds quarterly team offsites for engineering planning", "fact"),
    ("The office has standing desks, dual monitors, and a nap room", "fact"),
    ("Acme AI provides a $500 annual wellness stipend for gym memberships or fitness classes", "fact"),
    ("Acme AI has a pet-friendly office with dedicated dog areas", "fact"),
    ("Acme AI offers unlimited PTO and remote work flexibility", "fact"),
    ("The Acme AI office is located in the SoMa district of San Francisco near Caltrain", "fact"),
]

c = Client(host=HOST, port=PORT, database=DB)

# Register
ident = f"bulk_import_{uuid.uuid4().hex[:8]}"
resp = httpx.post(
    f"http://{HOST}:{PORT}/v1/database/{DB}/call/register",
    content=json.dumps([ident, "Bulk Import", "importpass"]),
    headers={"Content-Type": "application/json"},
    timeout=10.0,
)
token = resp.headers.get("spacetime-identity-token", "")
if not token:
    print("FATAL: Could not register")
    sys.exit(1)
c._identity_token = token
c._identity_established = True

# Create workspace
ws_id = f"eval-{uuid.uuid4().hex[:12]}"
c._call("create_workspace", ["eval_benchmark", "auto", ws_id])
print(f"Workspace: {ws_id}")

# Store all memories — skip auto-index by calling store_memory directly
stored = 0
for i, (content, mtype) in enumerate(MEMORIES):
    for attempt in range(3):
        try:
            c._call("store_memory", [
                ws_id, ident, ident, mtype, content, "",
                "[]", 0.85, "", "",
                "",  # images_json
            ])
            stored += 1
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                print(f"  FAIL [{i}]: {e}")

print(f"Stored {stored}/{len(MEMORIES)}")

# Now batch index — with retries for embedder crashes
for i in range(stored):
    # Find the memory by content
    mems = c._query("memory", workspace_id=ws_id, filter_dict={}, columns=["id", "content"])
    if i >= len(mems):
        break
    mem = mems[i]
    content = mem.get("content", "")
    mem_id = mem.get("id", "")
    if not mem_id:
        continue

    for attempt in range(5):
        try:
            emb = c._embed(content)
            if emb:
                c._call("index_entity", [
                    ws_id, "memory", mem_id, content,
                    json.dumps(emb)
                ])
                c._call("index_terms", [
                    ws_id, "memory", mem_id, content
                ])
            break
        except Exception as e:
            wait = 2 ** attempt
            if attempt < 4:
                print(f"  Index retry {attempt+1} for {mem_id[:8]} in {wait}s: {e}")
                time.sleep(wait)
            else:
                print(f"  Index FAIL for {mem_id[:8]} after 5 attempts: {e}")

print(f"Workspace: {ws_id}")
print(f"Memories: {stored}")
with open("/tmp/eval_workspace.txt", "w") as f:
    f.write(ws_id)
with open("/tmp/eval_queries.jsonl", "w") as f:
    pass
print("Done")
