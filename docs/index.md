# Spacetime Memory

**Multi-layer memory infrastructure for AI agents — on SpacetimeDB.**

Spacetime Memory is a unified memory layer for AI agents with **drop-in adapters** for the most popular memory library APIs.

| Project | Adapter | API Surface |
|---------|---------|------------|
| [Mem0](https://github.com/mem0ai/mem0) | `sdks.mem0.Memory` | `add()`, `search()`, `get()`, `get_all()`, `update()`, `delete()`, `delete_all()`, `history()` |
| [Graphiti](https://github.com/getzep/graphiti) | `sdks.graphiti.Graphiti` | `add_triplet()`, `add_episode()`, `search()`, `search_()`, `get_entity_edge_summary()`, `remove_episode()`, `build_communities()` |
| [LangGraph](https://langchain-ai.github.io/langgraph/) / [LangChain](https://python.langchain.com/) | `sdks.langchain.StmemStore` / `StmemMemoryStore` | `get/put/delete/search/list_namespaces/batch` (LangGraph BaseStore), `mget/mset/mdelete/yield_keys` (LangChain BaseStore) |
| [Zep](https://www.getzep.com/) | `sdks.zep.Zep` | `add()`, `get()`, `delete()`, sessions CRUD, search, messages, facts |
| [Hindsight](https://github.com/vectorize-io/hindsight) | `sdks.hindsight.Hindsight` | `retain()`, `recall()`, `reflect()`, `forget()` |
| [Honcho](https://github.com/plastic-labs/honcho) | `sdks.honcho.Honcho` | `create_user()`, `create_session()`, `add()`, `search()`, `get_user_memories()` |

Plus native features inspired by many projects (see below).

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
│  │  (Client + 6 drop-in adapters)               │  │ Frontend   │  │
│  └──────────────────────────────────────────────┘  └────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────┐  ┌──────────────┐│
│  │  spacetime-llm proxy (:4000) — Embeddings     │  │ Tantivy     ││
│  │  (baai/bge-m3 → NVIDIA NIM, 1024d)            │  │ BM25 (:9091)││
│  └──────────────────────────────────────────────┘  └──────────────┘│
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

### Features

- **Notes with Block-Level References** — Write markdown notes with `[[wikilinks]]`, `((block-id))` references, and `{{embed ((id))}}` transclusions.
- **Guided Tours** — Create interactive walkthroughs through knowledge graph nodes.
- **Tiered Memory** — Memories auto-escalate through L2→L1→L0 tiers based on access count. Trust scores weigh search results. Strength decays over time.
- **Scheduled Maintenance** — Automatic dedup, decay, tier escalation, community detection, and god-node computation on configurable schedules.
