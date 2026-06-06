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

**Spacetime Memory** is a unified memory layer for AI agents inspired by:

| Project | Features Incorporated |
|---|---|
| [Mem0](https://github.com/mem0ai/mem0) | Multi-level memory (user/session/agent), entity linking, temporal reasoning, hybrid retrieval |
| [Hindsight](https://github.com/vectorize-io/hindsight) | Biomimetic memory model (world facts, experiences, mental models), retain/recall/reflect operations, multi-strategy retrieval |
| [Honcho](https://github.com/plastic-labs/honcho) | Peer-centric entity model, session context, reasoning-first memory, multi-peer perspectives |
| [Graphify](https://github.com/safishamsi/graphify) | Knowledge graphs with community detection, god nodes, edge confidence tagging |
| [Understand Anything](https://github.com/Lum1104/Understand-Anything) | Codebase knowledge graph, interactive dashboard, diff impact analysis, guided tours |
| [Supermemory](https://github.com/supermemoryai/supermemory) | User profiles with static/dynamic facts, hybrid search (RAG + memory), connectors, MCP server |
| [Logseq](https://github.com/logseq/logseq) | Graph-based knowledge management, block-level referencing, backlinks |
| [CLI-Anything](https://github.com/HKUDS/CLI-Anything) | CLI harness patterns for agent-native interfaces |
| [Obsidian](https://obsidian.md) | Graph view, plugins, daily notes, canvas, backlinks |

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
│  │  │ (Users,  │  │ (Conver- │  │ (Text,   │  │ (World,  │     │   │
│  │  │  Agents) │  │  sations)│  │  Tools)  │  │  Exper.) │     │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │   │
│  │                                                              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │   │
│  │  │ Knowledge│  │Documents │  │ Profiles │  │ Insights │     │   │
│  │  │  Graph   │  │ (RAG)    │  │ (Static+ │  │ (Reflect)│     │   │
│  │  │ (Nodes,  │  │ (Chunks, │  │  Dynamic)│  │ (Memory  │     │   │
│  │  │  Edges)  │  │  Files)  │  │          │  │  Reason) │     │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │   │
│  │                                                              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │   │
│  │  │ Entity   │  │  Tags    │  │  Search  │  │  Auth    │     │   │
│  │  │ Linking  │  │ (Collec- │  │  Index   │  │  (API    │     │   │
│  │  │ (Canon.) │  │  tions)  │  │  (Multi- │  │   Keys)  │     │   │
│  │  └──────────┘  └──────────┘  │  strat)  │  └──────────┘     │   │
│  │                              └──────────┘                    │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │         React Frontend (Vite + shadcn + Lucide)              │   │
│  │  Dashboard │ Peers │ Sessions │ KG │ Memories │ Docs │ Search │   │
│  └──────────────────────────────────────────────────────────────┘   │
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
| `KgCommunity` | Graph community clusters (Leiden) | Graphify |
| `Document` | RAG content with metadata | Supermemory |
| `DocChunk` | Document chunks with embeddings | Supermemory |
| `EntityLink` | Canonical entity resolution with aliases | Mem0 |
| `Tag` | Memory/document labels | Common |
| `MemoryTag` | N:M relationship between memories and tags | Common |
| `SearchIndex` | Multi-strategy search metadata (semantic, BM25, graph, temporal) | Mem0, Hindsight |
| `ApiKey` | API keys for programmatic access | Common |
| `AuthSession` | Identity-based session tokens | Common |

### Reducer API

The module exposes ~40 reducers covering full CRUD for all entity types plus special operations:

**Peers & Sessions:**
- `create_workspace`, `update_workspace`, `delete_workspace`
- `create_peer`, `update_peer`, `delete_peer`
- `create_session`, `join_session`, `leave_session`, `update_session_summary`
- `send_message`, `delete_message`

**Memory Layer:**
- `store_memory`, `update_memory`, `deactivate_memory`, `expire_memories`
- `upsert_profile`, `add_profile_fact`, `add_dynamic_context`
- `create_insight`, `delete_insight`

**Knowledge Graph:**
- `create_node`, `delete_node`
- `create_edge`, `delete_edge`
- `create_community`, `assign_to_community`

**Documents & Search:**
- `create_document`, `add_chunk`, `delete_document`
- `index_entity`, `remove_from_index`
- `create_tag`, `tag_memory`, `untag_memory`

**Entity & Auth:**
- `create_entity_link`, `add_alias`, `resolve_entity`
- `create_api_key`, `deactivate_api_key`
- `create_auth_session`, `revoke_auth_session`, `cleanup_expired_sessions`

## Quick Start

### Prerequisites

- Rust toolchain (`cargo`, `rustup`)
- SpacetimeDB CLI v2.4+ (`spacetime version upgrade`)
- Node.js 18+ and npm

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

### 4. Start Frontend

```bash
cd client
npm install
npm run dev
```

The dashboard will be available at `http://localhost:5173`.

## Feature Reference

### Memory Types (Biomimetic)

```
┌──────────────────┐
│  World Facts     │  "The stove is hot" — declarative knowledge
├──────────────────┤
│  Experiences     │  "I touched the stove and it hurt" — episodic
├──────────────────┤
│  Mental Models   │  "Stoves are dangerous when hot" — learned patterns
└──────────────────┘
```

### Retrieval Strategies

| Strategy | Description |
|---|---|
| **Semantic** | Vector similarity search via embeddings |
| **BM25** | Keyword exact matching on content |
| **Graph** | Entity/temporal/causal link traversal |
| **Temporal** | Time-range filtering and recency ranking |
| **Hybrid Fusion** | Combined ranking via reciprocal rank fusion |

### User Profiles (Supermemory-style)

```typescript
const profile = {
  static: ["Senior engineer at Acme", "Prefers dark mode", "Uses Vim"],
  dynamic: ["Working on auth migration", "Debugging rate limits"]
};
```

### Knowledge Graph (Graphify-style)

Nodes have types (`code`, `concept`, `entity`, `document`, `topic`) and are organized into communities. Edges have confidence levels:

- **EXTRACTED** — Directly observed (e.g., AST analysis)
- **INFERRED** — Deduced from context
- **AMBIGUOUS** — Uncertain

### Entity Resolution (Mem0-style)

Canonical entity names with alias tracking. Entities are linked across memories for retrieval boosting.

## Project Structure

```
spacetime-memory/
├── server/
│   └── spacetimedb/          # SpacetimeDB Rust module
│       ├── Cargo.toml
│       └── src/
│           ├── lib.rs        # Module entry, helpers (uuid_v4, now_micros)
│           ├── workspace.rs  # Workspace entity
│           ├── peer.rs       # Peers (users, agents, entities)
│           ├── session.rs    # Sessions and participants
│           ├── message.rs    # Messages
│           ├── memory.rs     # Core memory (world facts, experiences, mental models)
│           ├── profile.rs    # User profiles (static + dynamic)
│           ├── insight.rs    # Reasoning/reflection over memories
│           ├── knowledge_graph.rs  # KG nodes, edges, communities
│           ├── document.rs   # Documents and chunks
│           ├── entity_linking.rs   # Entity resolution with aliases
│           ├── tag.rs        # Tags and memory-tag associations
│           ├── retrieval.rs  # Search index for multi-strategy retrieval
│           └── auth.rs       # API keys and auth sessions
├── client/                   # React frontend
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── index.css
│   │   ├── lib/utils.ts
│   │   ├── components/ui/    # shadcn components
│   │   └── pages/            # Dashboard, KG, Memories, etc.
│   ├── package.json
│   └── vite.config.ts
└── README.md
```

## License

MIT
