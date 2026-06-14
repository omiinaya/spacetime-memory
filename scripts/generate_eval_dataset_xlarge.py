#!/usr/bin/env python3
"""Generate XL labeled eval dataset — 200+ memories, all 55 original + 20 new queries.

Extends `generate_eval_dataset_large.py` with additional clusters:
  - Pricing & Plans (12 memories)
  - Partnerships & Ecosystem (14 memories)
  - Future Roadmap (10 memories)
  - Internal Operations (12 memories)
  - Expanded negative (8 office/perk memories) — now 36 total negative
  - +6 new cross-cluster/specific queries

Total: 128 + 56 = 184 memories. If mem count < 200, expand existing clusters.
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
    "c200f381695ed98be9b3fa689dd298cddff6212d35c46ae2a01999f921b88c82",
)

# ── Original 128 memories (indices 0–127) ────────────────────────────────

MEMORIES_ORIG = [
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
    ("The company was in Y Combinator's Winter 2023 batch alongside 200 other startups.", "world_fact"),
    ("Seed round of $3M was raised in March 2023 from YC, a16z scout, and angel investors.", "world_fact"),
    ("ARR reached $22M in Q1 2026, up from $8M in Q1 2025.", "world_fact"),
    ("Monthly recurring revenue is $1.9M with 98% gross dollar retention.", "world_fact"),
    ("The company has 340 paying customers across Free, Pro, and Enterprise plans.", "world_fact"),
    ("Average contract value is $65K for Pro and $350K for Enterprise.", "world_fact"),
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
    ("The ML team fine-tunes Llama 3 and Mistral models using LoRA on 8×A100 nodes.", "world_fact"),
    ("Acme AI open-sourced their workflow parser library under MIT license.", "world_fact"),
    ("Database tier: PostgreSQL (primary), Redis (cache), S3 (blob), SpacetimeDB (real-time).", "world_fact"),
    ("They run a custom Rust-based feature flag service handling 5M evaluations per second.", "world_fact"),
    ("All services emit OpenTelemetry traces sampled at 10% with Honeycomb for analysis.", "world_fact"),
    ("The infrastructure runs across us-east-1 and eu-west-1 for multi-region resilience.", "world_fact"),
    ("PagerDuty is configured with 5-minute acknowledgement SLAs for critical services.", "world_fact"),
    ("Secrets management uses HashiCorp Vault with automatic rotation every 30 days.", "world_fact"),
    ("Load testing with k6 runs nightly against staging, targeting 2× peak prod traffic.", "world_fact"),

    # ── Cluster 4: Customers & Case Studies (indices 60–75) ──
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

    # ── Cluster 5: Market & Competition (indices 76–89) ──
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

    # ── Cluster 6: Security & Compliance (indices 90–99) ──
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

    # ── Cluster 7: Negative/Unrelated (indices 100–127) ──
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
    ("The office has standing desks from Fully and Herman Miller Aeron chairs.", "world_fact"),
    ("There is a meditation room on the 2nd floor with a noise machine.", "world_fact"),
    ("The company Slack has a #pets channel with 200+ employee pet photos.", "world_fact"),
    ("Tuesday mornings have an optional yoga class in the common area.", "world_fact"),
    ("The snack selection rotates quarterly based on an employee survey.", "world_fact"),
    ("Every new hire gets a branded hoodie, water bottle, and notebook kit.", "world_fact"),
    ("The office playlist is curated by a different team each week on Spotify.", "world_fact"),
    ("There's an annual chili cook-off with a traveling trophy.", "world_fact"),
    ("The engineering team plays Magic: The Gathering on Thursday evenings.", "world_fact"),
    ("Acme AI has a running club that meets Wednesdays at 7am along the Embarcadero.", "world_fact"),
    ("The coffee machine is a La Marzocco Linea Mini with beans from Four Barrel.", "world_fact"),
    ("Desk plants are provided by the company — each employee gets a succulent on day one.", "world_fact"),
    ("The office has a library corner curated by the book club each month.", "world_fact"),
    ("Friday afternoons have a demo hour where teams show what they shipped that week.", "world_fact"),
    ("There is a ping pong table in the break room that sees fierce competition.", "world_fact"),
    ("Acme AI's fantasy football league has 40 participants across three divisions.", "world_fact"),
    ("The company Slack has a #food channel for sharing lunch spot recommendations.", "world_fact"),
    ("A company-wide hackathon runs twice a year with prizes for top projects.", "world_fact"),
]

# ── NEW: Cluster 8: Pricing & Plans (indices 128–139) ──
MEMORIES_NEW_PRICING = [
    ("FlowForge pricing: Free plan includes 100 automation steps/month and 5 connectors.", "world_fact"),
    ("FlowForge Pro plan costs $49/user/month with unlimited steps and 50 connectors.", "world_fact"),
    ("FlowForge Enterprise plan starts at $5K/month for custom connectors and dedicated support.", "world_fact"),
    ("The Free-to-Pro conversion funnel has a 12% conversion rate within 90 days.", "world_fact"),
    ("Enterprise plan includes a dedicated customer success manager and 99.9% uptime SLA.", "world_fact"),
    ("Volume discounts are available for 50+ seats on the Pro plan at 20% off.", "world_fact"),
    ("Annual billing on Pro saves 17% compared to monthly billing.", "world_fact"),
    ("The Enterprise plan includes SSO, audit logs, and custom data retention policies.", "world_fact"),
    ("A new Startup plan at $19/user/month launched in Q1 2026 for companies under 20 employees.", "world_fact"),
    ("FlowForge offers a 30-day free trial of the Pro plan with no credit card required.", "world_fact"),
    ("Enterprise plan pricing is usage-based above 10K automation steps per day.", "world_fact"),
    ("Non-profit organizations receive a 50% discount on all FlowForge plans.", "world_fact"),
]

# ── NEW: Cluster 9: Partnerships & Ecosystem (indices 140–153) ──
MEMORIES_NEW_PARTNERSHIPS = [
    ("Acme AI partners with AWS as an Advanced Technology Partner in the APN.", "world_fact"),
    ("A strategic partnership with Snowflake enables FlowForge to trigger workflows from data pipelines.", "world_fact"),
    ("Datadog partnership provides native FlowForge dashboards for monitoring automation health.", "world_fact"),
    ("The company has a reseller agreement with CDW for government and education sectors.", "world_fact"),
    ("Acme AI joined the Microsoft for Startups program with $150K in Azure credits.", "world_fact"),
    ("A partnership with Okta enables seamless SSO provisioning for enterprise customers.", "world_fact"),
    ("The Zapier integration is bidirectional — FlowForge can both trigger and be triggered by Zaps.", "world_fact"),
    ("Acme AI sponsors the AI Engineer Summit and React Conf annually.", "world_fact"),
    ("A technology alliance with Anthropic provides early access to Claude models for FlowForge AI features.", "world_fact"),
    ("The company has 15 certified implementation partners across North America and Europe.", "world_fact"),
    ("System integrator partners include Accenture, Deloitte Digital, and Slalom.", "world_fact"),
    ("A developer advocacy program with 200+ community ambassadors drives grassroots adoption.", "world_fact"),
    ("Acme AI contributes to the OpenAPI, CloudEvents, and AsyncAPI open standards.", "world_fact"),
    ("The company co-hosts a monthly webinar series with AWS on enterprise automation patterns.", "world_fact"),
]

# ── NEW: Cluster 10: Future Roadmap (indices 154–163) ──
MEMORIES_NEW_ROADMAP = [
    ("FlowForge Q3 2026 roadmap includes a visual canvas editor with drag-and-drop workflow building.", "world_fact"),
    ("Planned Q4 2026: multi-agent AI workflows where multiple LLM agents collaborate on automation tasks.", "world_fact"),
    ("Acme AI is exploring a FlowForge Marketplace for community-built connector plugins.", "world_fact"),
    ("The company plans to open a London office in 2027 to serve EMEA enterprise customers.", "world_fact"),
    ("FlowForge mobile app is planned for general availability in Q3 2026 on iOS and Android.", "world_fact"),
    ("Acme AI is researching RAG-based workflows that can ingest enterprise documents for context-aware automation.", "world_fact"),
    ("A planned acquisition of a small AI observability startup will add ML monitoring to FlowForge.", "world_fact"),
    ("The engineering team is evaluating WebAssembly runtime support for custom connector sandboxing.", "world_fact"),
    ("A FlowForge CLI tool for CI/CD pipeline integration is on the 2027 roadmap.", "world_fact"),
    ("The company is exploring a HIPAA-compliant dedicated hosting option for healthcare customers.", "world_fact"),
]

# ── NEW: Cluster 11: Internal Operations (indices 164–175) ──
MEMORIES_NEW_OPS = [
    ("Acme AI uses Rippling for HRIS, payroll, and device management across 120 employees.", "world_fact"),
    ("The finance team uses Brex for corporate cards and Mercury for business banking.", "world_fact"),
    ("Internal documentation lives in Notion with a mandatory RFC process for architectural decisions.", "world_fact"),
    ("The recruiting pipeline sources 60% of engineering hires from employee referrals.", "world_fact"),
    ("Acme AI has a formal leveling framework with levels E1 through E7 for engineering.", "world_fact"),
    ("The engineering onboarding program is 4 weeks with a dedicated mentor and starter project.", "world_fact"),
    ("Performance reviews happen twice yearly with 360-degree feedback from peers and reports.", "world_fact"),
    ("All-company meetings are every Monday at 9am Pacific with remote dial-in via Zoom.", "world_fact"),
    ("The company uses Linear for issue tracking and Notion for product specs.", "world_fact"),
    ("Engineering compensation includes base salary, equity (4-year vest, 1-year cliff), and performance bonuses.", "world_fact"),
    ("Diversity stats: 42% women in leadership, 35% underrepresented minorities in engineering.", "world_fact"),
    ("Acme AI has an internal mobility program allowing engineers to rotate teams every 12 months.", "world_fact"),
]

# ── NEW: Expanded negative (indices 176–183) ──
MEMORIES_NEW_NEGATIVE = [
    ("The office dog policy allows employees to bring well-behaved dogs on Wednesdays and Fridays.", "world_fact"),
    ("There is a rooftop garden where employees grow tomatoes, basil, and peppers in raised beds.", "world_fact"),
    ("The company sponsors a local Little League team called the Acme Automators.", "world_fact"),
    ("Every Halloween the office holds a costume contest with categories for best group and most creative.", "world_fact"),
    ("The kitchen has three types of oat milk: Oatly, Califia, and Minor Figures.", "world_fact"),
    ("There's a weekly chess club that meets in the library corner on Wednesday lunch breaks.", "world_fact"),
    ("Employees can expense up to $50/month for books related to their professional development.", "world_fact"),
    ("The office has a nap pod room with two zero-gravity chairs and blackout curtains.", "world_fact"),
]

# ── Assemble all memories ─────────────────────────────────────────────────

MEMORIES = MEMORIES_ORIG + MEMORIES_NEW_PRICING + MEMORIES_NEW_PARTNERSHIPS + \
           MEMORIES_NEW_ROADMAP + MEMORIES_NEW_OPS + MEMORIES_NEW_NEGATIVE

# ── All 55 original queries ───────────────────────────────────────────────

QUERIES = [
    # ── CEO / Leadership ──
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

    # ── Negative queries ──
    {"query": "office amenities perks", "description": "Office perks (negative)", "relevant_indices": [100, 105, 111, 118]},
    {"query": "team events culture activities", "description": "Culture (negative)", "relevant_indices": [103, 104, 112, 115, 120]},
    {"query": "coffee espresso machine office", "description": "Coffee (negative)", "relevant_indices": [100, 117]},
    {"query": "employee wellness gym stipend", "description": "Wellness (negative)", "relevant_indices": [104, 110, 118]},
    {"query": "holiday party napa winery", "description": "Party (negative)", "relevant_indices": [107]},

    # ── Synthesis / cross-cluster ──
    {"query": "Acme AI complete company overview", "description": "Full overview", "relevant_indices": [0, 7, 12, 22, 28, 60, 77]},
    {"query": "Acme AI from founding to Series B timeline", "description": "Company timeline", "relevant_indices": [7, 12, 13, 14, 15, 20]},
    {"query": "Acme AI product FlowForge technical architecture", "description": "Architecture deep dive", "relevant_indices": [30, 31, 33, 35, 44, 45, 46, 52]},
    {"query": "Acme AI enterprise sales motion and go-to-market", "description": "GTM", "relevant_indices": [64, 67, 82, 83, 84]},
    {"query": "Acme AI engineering team structure and practices", "description": "Engineering org", "relevant_indices": [1, 3, 9, 45, 46, 48, 49]},
]

# ── NEW: 20 additional queries ─────────────────────────────────────────────

QUERIES_NEW = [
    # Pricing
    {"query": "FlowForge pricing plans cost per user", "description": "Pricing plans", "relevant_indices": [128, 129, 130]},
    {"query": "FlowForge startup plan discount non-profit", "description": "Startup/nonprofit pricing", "relevant_indices": [136, 139]},
    {"query": "FlowForge Pro plan features limits", "description": "Pro plan details", "relevant_indices": [129, 131, 134]},
    {"query": "FlowForge Enterprise plan SLA contract", "description": "Enterprise details", "relevant_indices": [130, 132, 135, 138]},

    # Partnerships
    {"query": "Acme AI partners AWS Datadog Snowflake", "description": "Tech partners", "relevant_indices": [140, 141, 142]},
    {"query": "Acme AI system integrators implementation partners", "description": "SI partners", "relevant_indices": [147, 148]},
    {"query": "Acme AI Okta Microsoft startups program", "description": "Platform partners", "relevant_indices": [143, 144]},
    {"query": "Acme AI developer community advocacy program", "description": "Dev advocacy", "relevant_indices": [149, 150, 151]},

    # Roadmap
    {"query": "FlowForge future roadmap planned features", "description": "Product roadmap", "relevant_indices": [154, 155, 156]},
    {"query": "FlowForge marketplace connector plugins community", "description": "Marketplace", "relevant_indices": [156]},
    {"query": "Acme AI London office expansion 2027", "description": "International expansion", "relevant_indices": [157]},
    {"query": "FlowForge WebAssembly WASM sandbox custom runtime", "description": "WASM sandbox", "relevant_indices": [161]},

    # Operations
    {"query": "Acme AI internal tools systems HR finance", "description": "Internal tools", "relevant_indices": [164, 165, 166]},
    {"query": "Acme AI recruiting engineering hiring pipeline", "description": "Recruiting", "relevant_indices": [167, 170]},
    {"query": "Acme AI performance review leveling compensation", "description": "People ops", "relevant_indices": [168, 169, 171, 173]},
    {"query": "Acme AI diversity stats women leadership minorities", "description": "DEI stats", "relevant_indices": [174]},

    # Cross-cluster new
    {"query": "Acme AI pricing enterprise features compliance SSO", "description": "Enterprise value prop", "relevant_indices": [130, 132, 135, 41]},
    {"query": "Acme AI ecosystem partnerships resellers technology alliances", "description": "Ecosystem overview", "relevant_indices": [140, 141, 145, 146, 147, 148]},
    {"query": "Acme AI future plans expansion roadmap 2026 2027", "description": "Future overview", "relevant_indices": [154, 155, 157, 160, 162]},
    {"query": "Acme AI internal culture compensation benefits", "description": "Culture + comp", "relevant_indices": [173, 174, 175, 11, 104]},
]

QUERIES_ALL = QUERIES + QUERIES_NEW


# ── Main ────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate XL labeled eval dataset (200+ memories)")
    parser.add_argument("--workspace-id", default=None, help="Existing workspace ID")
    parser.add_argument("--output", default="/tmp/eval_queries_xlarge.jsonl", help="Output JSONL path")
    parser.add_argument("--populate", action="store_true", help="Store memories into workspace")
    parser.add_argument("--skip-populate", action="store_true", help="Skip populate, generate placeholders")
    args = parser.parse_args()

    client = Client(host=HOST, port=PORT, database=DB)

    try:
        client._call("register", ["eval_generator", "Eval Generator", "evalpass"])
    except RuntimeError:
        # Already registered — try logging in
        try:
            client._call("login", ["eval_generator", "evalpass"])
        except RuntimeError:
            # Login failed too — use a fresh identity
            uid = uuid.uuid4().hex[:8]
            try:
                client._call("register", [f"eval_{uid}", "Eval Generator", "evalpass"])
            except RuntimeError:
                pass

    ws_id = args.workspace_id
    if not ws_id:
        ws_id = f"eval-xlarge-{uuid.uuid4().hex[:8]}"
        try:
            client._call("create_workspace", ["eval_benchmark_xlarge", "auto", ws_id])
        except RuntimeError:
            pass

    print(f"Total memories: {len(MEMORIES)}")
    print(f"Total queries: {len(QUERIES_ALL)}")

    memory_ids: list[str] = []
    if args.populate and not args.skip_populate:
        print(f"Populating workspace {ws_id} with {len(MEMORIES)} memories...")
        for i, (text, mtype) in enumerate(MEMORIES):
            try:
                client.store(workspace_id=ws_id, content=text, memory_type=mtype, peer_id="eval_generator")
            except Exception as e:
                print(f"  [{i}] store FAILED: {e}")
                memory_ids.append("")
                continue

            try:
                mems = client._query("memory", workspace_id=ws_id, filter_dict={}, columns=["id", "content"])
                matched = None
                for m in mems:
                    if m.get("content", "")[:60] == text[:60]:
                        matched = m["id"]
                        break
                if matched:
                    memory_ids.append(matched)
                else:
                    memory_ids.append("")
            except Exception:
                memory_ids.append("")
        print(f"  Stored {len([m for m in memory_ids if m])}/{len(MEMORIES)} memories")
    else:
        print("Skipping population (use --populate).")
        memory_ids = [f"mem-{i:03d}" for i in range(len(MEMORIES))]

    queries = []
    for q in QUERIES_ALL:
        relevant_ids = [
            memory_ids[i] for i in q["relevant_indices"]
            if i < len(memory_ids) and memory_ids[i]
        ]
        queries.append({
            "query": q["query"],
            "description": q["description"],
            "relevant_ids": relevant_ids,
        })

    with open(args.output, "w") as f:
        for q in queries:
            f.write(json.dumps(q) + "\n")

    print(f"Wrote {len(queries)} queries to {args.output}")
    print(f"Workspace ID: {ws_id}")

    id_path = args.output.replace(".jsonl", "_workspace_id.txt")
    with open(id_path, "w") as f:
        f.write(ws_id)

    if args.populate and not args.skip_populate:
        print(f"\nRun eval with:")
        print(f"  python3 scripts/eval_harness.py --workspace-id {ws_id} --queries-file {args.output}")


if __name__ == "__main__":
    main()
