#!/usr/bin/env python3
"""Quick seed data into spacetime-memory for eval."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sdk", "python"))

import httpx
from spacetime_memory import Client

DB = "c200bd2c4073807f98d79813c26afd931482f2f422a3a860d78d91298ddaa816"
EMB = os.environ.get("EMBEDDER_URL", "http://localhost:9092")

# Get fresh identity token and register
resp = httpx.get(f"http://localhost:3001/v1/database/{DB}", timeout=5)
identity = resp.headers.get("spacetime-identity", "")
token = resp.headers.get("spacetime-identity-token", "")

c = Client(database=DB, embedder_url=EMB, token=token)

# Register this identity (idempotent — fails if already registered)
try:
    c._call("register", ["eval-seeder", "eval123456", identity])
except Exception:
    pass  # Already registered from prior run

# Create or get workspace
try:
    ws = c.create_workspace("acme-ai-seed", "Acme AI seed data")
    ws_id = ws["id"]
    print(f"Created workspace: {ws_id[:16]}...")
except Exception:
    workspaces = c.list_workspaces()
    acme = [w for w in workspaces if w.get("name") == "acme-ai-seed"]
    ws_id = acme[0]["id"] if acme else workspaces[0]["id"]
    print(f"Using workspace: {ws_id[:16]}...")

memories = [
    "Alice Chen is the CEO and co-founder of Acme AI, previously Engineering Director at Stripe where she led ML infrastructure.",
    "Bob Kumar is the CTO of Acme AI, former Google Brain researcher with 15 years in distributed systems.",
    "Acme AI raised $45M Series A in March 2025 led by a16z with Sequoia and Greylock participating.",
    "Acme AI was founded in January 2024 by Alice Chen and Bob Kumar in San Francisco.",
    "The company has 47 employees as of June 2025, with 32 in engineering and 15 in GTM.",
    "Acme AI platform provides real-time LLM observability, monitoring latency, token usage, and accuracy across GPT-4, Claude, and Gemini.",
    "The product integrates with Datadog, PagerDuty, Slack, and supports custom webhooks for alerting.",
    "Acme AI processes over 500M inference requests per day with p99 latency under 200ms.",
    "NPS score is 72 as of Q2 2025, with 94% customer retention rate and 200+ paying customers.",
    "Acme AI model accuracy benchmark shows 23% improvement over competitors on MMLU and HumanEval.",
    "The tech stack runs on Kubernetes with a Rust-based inference proxy, PostgreSQL for metadata, and ClickHouse for telemetry.",
    "Alice Chen won Forbes 30 Under 30 in 2025 and gave a TEDx talk on AI safety.",
    "Bob Kumar previously worked at Google Brain on TensorFlow Serving for 7 years.",
    "The distributed inference system was designed by Bob Kumar and a team of 4 senior systems engineers.",
    "Acme AI customers include Stripe, Notion, Vercel, and 200+ startups using the platform for LLM monitoring.",
    "The company is hiring Senior Rust engineer, ML infrastructure engineer, and 3 full-stack engineers.",
    "FlowForge is a competitor focused on open-source model deployment, with weaker observability features.",
    "iPaaS automation market estimated at $12B by 2027 with 28% CAGR per Gartner.",
    "GDPR data residency handled via EU-based ClickHouse clusters for European customers.",
    "FlowForge holds SOC 2 Type II and ISO 27001, Acme AI pursuing SOC 2 as of Q3 2025.",
]

for i, content in enumerate(memories):
    try:
        c.store(
            workspace_id=ws_id,
            content=content,
            memory_type="world_fact",
            peer_id="eval-seeder",
            confidence=0.9,
        )
    except Exception as e:
        print(f"  Error {i}: {e}")
    if (i + 1) % 5 == 0:
        print(f"  {i+1}/{len(memories)}")

print(f"\nSeeded {len(memories)} memories into {ws_id}")
print(f"SPACETIMEDB_DB={DB}")
print(f"WORKSPACE_ID={ws_id}")
