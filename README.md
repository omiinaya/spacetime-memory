<div align="center">
  <h1>Spacetime Memory</h1>
  <p><strong>Multi-layer memory infrastructure for AI agents — on SpacetimeDB</strong></p>
</div>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow" alt="License: MIT"></a>
  <a href="server/spacetimedb"><img src="https://img.shields.io/badge/SpacetimeDB-v2.4-blue" alt="SpacetimeDB v2.4"></a>
  <a href="client"><img src="https://img.shields.io/badge/Frontend-React%20%2B%20shadcn-61DAFB" alt="Frontend"></a>
</p>

---

**Spacetime Memory** is a unified memory layer for AI agents with **drop-in adapters** for the most popular memory library APIs.

## Quick Start

```bash
pip install spacetime-memory[local-embed]

from spacetime_memory import Client

c = Client(host="localhost", port="3001", database="your-db")
c.store("AI agents need persistent memory", "memory")
results = c.search("AI agents", limit=5)
```

Or drop in as any supported adapter:

```python
from spacetime_memory.sdks.mem0 import Memory
m = Memory(config={"host": "localhost", "port": "3001"})
m.add("I like pizza", user_id="alice")
```

See [Getting Started](docs/getting-started.md) for setup, or jump to the [Adapter Authoring Guide](docs/adapter-authoring-guide.md) to write your own.

## Drop-in Adapters

These adapters match the public API of their upstream library. You can swap the import path and keep existing code.

| Project | Adapter | Tests (live STDB) | Quality |
|---------|---------|:-----------------:|---------|
| [LangGraph](https://langchain-ai.github.io/langgraph/) / [LangChain](https://python.langchain.com/) | `sdks.langchain.StmemStore` / `StmemMemoryStore` | 16/17 | **~99%** — True `BaseStore` inheritance |
| [Mem0](https://github.com/mem0ai/mem0) (v2.0.5) | `sdks.mem0.Memory` | **26/26** | **~92%** — Missing `entity_store` (Qdrant-backed, unimplementable) |
| [Hindsight](https://github.com/vectorize-io/hindsight) (v0.8.1) | `sdks.hindsight.Hindsight` | Shape tests pass | **~95%** — Full retain/recall/reflect + batch + files + async |
| [Zep](https://www.getzep.com/) (v2.0.2) | `sdks.zep.Zep` | **26/26** | **~97%** — v2 API: `.memory`/`.user` sub-clients, `AsyncZep`, `ZepClient` alias |
| [Graphiti](https://github.com/getzep/graphiti) (v0.29.2) | `sdks.graphiti.Graphiti` | **20/20** | **~95%** — Entities, edges, episodes, communities. LLM extraction |
| [Honcho](https://github.com/plastic-labs/honcho) | `sdks.honcho.Honcho` | **14/14** | **~95%** — Workspace/peer/session/message/search + `.aio` async accessor |

Additional features inspired by many projects (data model, schedules, CLI design — see Data Model table below).

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Spacetime Memory                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    SpacetimeDB Module (Rust)                  │   │
│  │                                                              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │   │
│  │  │ Peers    │  │ Sessions │  │ Messages │  │ Memories │     │   │
│  │  │  + Auth  │  │          │  │          │  │ (Tiers,  │     │   │
│  │  │ (Accoun) │  │          │  │          │  │  Trust)  │     │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │   │
│  │                                                              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │   │
│  │  │ Knowledge│  │Documents │  │ Profiles │  │ Insights │     │   │
│  │  │  Graph   │  │          │  │          │  │          │     │   │
│  │  │ (Commun- │  │          │  │          │  │          │     │   │
│  │  │  ities)  │  │          │  │          │  │          │     │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │   │
│  │                                                              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │   │
│  │  │ Notes +  │  │  Tours   │  │  Search  │  │Consolid- │     │   │
│  │  │  Blocks  │  │ (Guided  │  │  (Multi- │  │ ation    │     │   │
│  │  │ (WikiLn) │  │  Tours)  │  │  strat)  │  │ (Dedup)  │     │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────┐  ┌────────────┐  │
│  │  Python SDK + CLI + MCP Server               │  │ React      │  │
│  │  (Client + Mem0/Honcho/Hindsight adapters)   │  │ Frontend   │  │
│  └──────────────────────────────────────────────┘  └────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────┐                   │
│  │  Rust ONNX Embedder Sidecar (:9090)          │                   │
│  │  (all-MiniLM-L6-v2, 384d)                    │                   │
│  └──────────────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────────┘
```

### Data Model (SpacetimeDB Tables)

| Table | Purpose | Inspired By |
|---|---|---|
| `Workspace` | Top-level organizational isolation container | Honcho Workspaces |
| `Peer` | Any participant — user, agent, or entity | Honcho Peers |
| `Session` | Conversation context with participants | Honcho Sessions |
| `Message` | Atomic interaction (text, tool_call, tool_result) | Common |
| `Memory` | Core memory — world facts, experiences, mental models | Hindsight |
| `Profile` | User/agent profile with static facts + dynamic context | Supermemory |
| `Insight` | Reflective reasoning over memories | Hindsight Reflect |
| `KgNode` | Knowledge graph nodes | Graphify, Understand Anything |
| `KgEdge` | Knowledge graph relationships | Graphify |
| `KgCommunity` | Graph community clusters (label propagation) | Graphify |
| `Document` | RAG content with metadata | Supermemory |
| `DocChunk` | Document chunks with embeddings | Supermemory |
| `EntityLink` | Canonical entity resolution with aliases | Mem0 |
| `Tag` | Memory/document labels | Common |
| `MemoryTag` | N:M relationship between memories and tags | Common |
| `SearchIndex` | Multi-strategy search metadata (semantic, BM25, graph, temporal) | Mem0, Hindsight |
| `Account` | User accounts with PBKDF2 password auth | Common |
| `ApiKey` | API keys for programmatic access | Common |
| `Note` | Markdown notes with wikilink backlinking | Logseq-style |
| `NoteBlock` | Block-level content (paragraphs, headings, lists, todos) | Logseq-style |
| `BlockReference` | `((block-id))` references and `{{embed ((id))}}` transclusions | Logseq-style |
| `NoteBacklink` | Forward edges from note A → note B via [[wikilinks]] | Common |
| `Tour` | Guided tours through KG nodes | Understand Anything |
| `ContextDirectory` | Hierarchical directory organization for memories | OpenViking |
| `ConsolidationLog` | Tracks memory consolidation operations | RetainDB |
| `ContextPack` | Cached compressed context packs | RetainDB |
| `MemoryFeedback` | User feedback ratings for trust scoring | Holographic |
| `HybridResult` | Temporary table for hybrid search result sets | Common |

### Reducer API

The module exposes ~80 reducers covering full CRUD plus special operations:

**Auth:**
- `register`, `login`, `logout`, `update_account`, `deactivate_account`
- `create_api_key`, `deactivate_api_key`
- `require_auth`, `require_admin`, `is_authenticated` (guard functions)

**Peers & Sessions:**
- `create_workspace`, `update_workspace`, `delete_workspace`
- `create_peer`, `update_peer`, `delete_peer`
- `create_session`, `join_session`, `leave_session`, `update_session_summary`
- `send_message`, `delete_message`

**Memory Layer:**
- `store_memory`, `update_memory`, `deactivate_memory`, `expire_memories`
- `rate_memory`, `reinforce_memory`, `update_memory_tier`, `escalate_memories`
- `upsert_profile`, `add_profile_fact`, `add_dynamic_context`
- `create_insight`, `delete_insight`

**Knowledge Graph:**
- `create_node`, `delete_node`
- `create_edge`, `delete_edge`
- `create_community`, `assign_to_community`
- `detect_communities`, `seed_communities`
- `graph_bfs`, `shortest_path`, `get_neighbors` (traversal)
- `compute_god_nodes` (degree centrality)

**Notes & Tours:**
- `create_note`, `update_note`, `delete_note`, `parse_note_blocks`
- `create_tour`, `add_tour_stop`, `remove_tour_stop`, `delete_tour`

**Documents & Search:**
- `create_document`, `add_chunk`, `delete_document`
- `index_entity`, `remove_from_index`
- `create_tag`, `tag_memory`, `untag_memory`
- `hybrid_search` (multi-strategy fusion)

**Entity & Linking:**
- `create_entity_link`, `add_alias`, `resolve_entity`

**Context & Consolidation:**
- `create_directory`, `delete_directory`
- `consolidate_memories`, `decay_weak_memories`, `dedup_memories`
- `store_context_pack`, `manual_maintenance`
- `generate_context_pack` (for context routing)

## Drop-in SDK Adapters

All 6 adapters live in `sdk/python/spacetime_memory/sdks/` and are importable as drop-in replacements:

```python
# Mem0
from spacetime_memory.sdks import Mem0Memory
m = Mem0Memory(config={"host": "localhost", "port": "3001"})
m.add("I like pizza", user_id="alice")

# Hindsight
from spacetime_memory.sdks import Hindsight
h = Hindsight(base_url="http://localhost:3001", api_key="optional")
h.retain("my_bank", "I like pizza")

# Honcho
from spacetime_memory.sdks import Honcho
honcho = Honcho(workspace_id="my_workspace")
p = honcho.peer("alice")
s = honcho.session("my_session")
s.add_messages([{"role": "user", "content": "I like pizza"}])
```

## Quick Start

### Prerequisites

- Rust toolchain (`cargo`, `rustup`)
- SpacetimeDB CLI v2.4+ (`spacetime version upgrade`)
- Node.js 18+ and npm
- Python 3.10+ (for SDK/CLI/MCP)

### 1. Clone & Setup

```bash
git clone https://github.com/omiinaya/spacetime-memory.git
cd spacetime-memory
```

### 2. Start SpacetimeDB

```bash
spacetime start --listen-addr 0.0.0.0:3001 &
```

### 3. Build & Publish Module

```bash
cd server/spacetimedb
cargo build --target wasm32-unknown-unknown
spacetime publish spacetime-memory -p ./ --yes
```

### 4. Start Embedder Sidecar

```bash
# The embedder is a compiled Rust binary (tract + all-MiniLM-L6-v2)
# It's pre-built at server/embedder/target/release/embedder
# Or build from source:
cd server/embedder && cargo build --release
./target/release/embedder   # Listens on :9090
```

### 5. Install Python SDK & CLI

```bash
cd sdk/python
pip install -e .
# CLI available as `stmem`:
stmem --help
```

### 6. Start MCP Server

```bash
stmem serve                  # stdio transport (local LLM integration)
stmem serve --transport sse  # HTTP SSE transport
```

### 7. Start Frontend

```bash
cd client
npm install
cp .env.example .env       # configure host/db
npm run dev                 # opens on localhost:5173
```

### 8. Login (First Run)

Open the frontend. On first launch, register as the admin user. Subsequent launches will prompt for login. All note operations are auth-gated.

## Features

### Notes with Block-Level References

Write markdown notes with `[[wikilinks]]`, `((block-id))` references, and `{{embed ((id))}}` transclusions. Each paragraph, heading, and list item becomes a trackable block with a stable ID:

```markdown
# My Note

This is a paragraph with a [[wikilink]] to another note.

And a ((0002)) reference to a specific block in this note.

{{embed ((other_note_id:0001))}} transcludes a block from another note.
```

### Guided Tours

Create interactive walkthroughs through knowledge graph nodes, with ordered stops, headings, and descriptions.

### Tiered Memory

Memories auto-escalate through L2→L1→L0 tiers based on access count (5 and 20 thresholds). Trust scores weigh search results. Strength decays over time.

### Scheduled Maintenance

Automatic dedup (cosine ≥0.85 + edit distance ≤30%), decay (strength <0.1 + 7 days), tier escalation, community detection, and god-node computation — all running on configurable schedules.
