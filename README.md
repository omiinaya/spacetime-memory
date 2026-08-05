<div align="center">
  <h1>Spacetime Memory</h1>
  <p><strong>Multi-layer memory infrastructure for AI agents — on SpacetimeDB</strong></p>
</div>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow" alt="License: MIT"></a>
  <a href="server/spacetimedb"><img src="https://img.shields.io/badge/SpacetimeDB-v2.7-blue" alt="SpacetimeDB v2.7"></a>
  <a href="client"><img src="https://img.shields.io/badge/Frontend-React%20%2B%20shadcn-61DAFB" alt="Frontend"></a>
</p>

---

**Spacetime Memory** is a unified memory layer for AI agents with **drop-in adapters** for the most popular memory library APIs.

## Documentation

| Guide | What It Covers |
|-------|----------------|
| **[AGENTS.md](AGENTS.md)** | **Agent wiki schema + development guide.** Tells agents how to use the memory system (ingestion workflows, CLI commands, MCP tools) AND how to develop the project (workspace layout, build/test commands, code conventions, task-to-file mapping). Start here. |
| **[CLAUDE.md](CLAUDE.md)** | Signpost for AI agent IDE/tooling integration. One-line setup, critical rules, key file references. |
| **[CONTRIBUTING.md](CONTRIBUTING.md)** | Contribution guide with AI Agent Contributors section. PR process, coding standards, what agents should/shouldn't do. |
| **[DEPLOYMENT.md](DEPLOYMENT.md)** | Production deployment: Docker, native, Kubernetes, upgrades, backup/restore, monitoring, JWT key rotation, hardening. |
| **[README.md](README.md)** | This file — project overview, quick start, architecture, setup, features. |
| **[ROADMAP.md](ROADMAP.md)** | Honest project assessment, competitive positioning, strategic priorities. |
|| **`docs/usage/connectors.md`** | Connector setup guide — how to obtain API keys and configure every built-in connector (Discord, Notion, GitHub, Slack, Twitter/X, RSS, webhooks, org-mode). |
|| **`docs/development.md`** | Developer setup guide (legacy, maintained for consistency with AGENTS.md). |
|| **`docs/getting-started.md`** | Python SDK examples and walkthroughs. |

## Quick Start

If you already have a SpacetimeDB instance with the memory module published (see [Setup](#setup) if you don't):

```bash
pip install spacetime-memory
```

```python
from spacetime_memory import Client

c = Client(host="127.0.0.1", port="3001", database="your-db")
ws = c.create_workspace("my-app")
c.store(ws["id"], "AI agents need persistent memory", peer_id="me")
results = c.search(ws["id"], "AI agents", semantic=True)
```

Or use any drop-in adapter:

```python
from spacetime_memory.sdks.mem0 import Memory
m = Memory(config={"host": "127.0.0.1", "port": "3001"})
m.add("I like pizza", user_id="alice")
```

Newer adapters are equally drop-in — LangMem tools, Cognee cognify, Letta blocks, QMD search, and Mnemosyne SM-2 cards all map to the same native store:

```python
from spacetime_memory.sdks.langmem import create_manage_memory_tool
tool = create_manage_memory_tool(namespace=("memories", "alice"))
tool.invoke({"content": "Alice likes pizza", "action": "create"})

import asyncio
from spacetime_memory.sdks.cognee import add, search
asyncio.run(add("Pizza is Alice's favorite food", dataset_name="prefs"))
results = asyncio.run(search("what does Alice like?", datasets=["prefs"]))

from spacetime_memory.sdks.mnemosyne import Mnemosyne
mn = Mnemosyne()
mn.create_card("general", "Favorite food?", "Pizza", grade=5)
```

All 11 Python adapters are native — no upstream package required at runtime.

## Drop-in Adapters

These adapters aim to match the public API of their upstream library. In most cases you can swap the import path and keep existing code, but each adapter has known gaps — see the Quality column and the **Adapter Caveats** section below for details.

| Project | Adapter | Tests (live STDB) | Quality |
|---------|---------|:-----------------:|---------|
| [LangGraph](https://langchain-ai.github.io/langgraph/) / [LangChain](https://python.langchain.com/) | `sdks.langchain.StmemStore` / `StmemMemoryStore` | 16/17 | **~92%** — True `BaseStore` inheritance; `batch()` works except a `refresh_ttl` attribute edge case |
| [Mem0](https://github.com/mem0ai/mem0) (v2.0.5) | `sdks.mem0.Memory` | **26/26** | **~100%** — Full CRUD + search + history + graph/entity_store + `create_memory_tool` + chat; config-style diffs only. TypeScript port: `typescript/mem0.ts` |
| [Hindsight](https://github.com/vectorize-io/hindsight) (v0.8.1) | `sdks.hindsight.Hindsight` | Shape tests pass | **~95%** — Full retain/recall/reflect + batch + files + async; documents/entities/operations/monitoring are real (table/sidecar-backed); **webhooks are real** (create/list/update/delete/fire over `webhook`+`webhook_delivery` tables with a Rust delivery sidecar — verified E2E). TypeScript port: `typescript/hindsight.ts` |
| [Zep](https://www.getzep.com/) (v2.0.2) | `sdks.zep.Zep` | **26/26 + 16/16 graph** | **~100%** — v2 API: `.memory`/`.user`/`.graph` sub-clients, `AsyncZep`, `ZepClient` alias. Graph namespace is real (add/search/node/edge/episode/triplet) with LLM fact rating wired. TypeScript port: `typescript/zep.ts` |
| [Graphiti](https://github.com/getzep/graphiti) (v0.29.2) | `sdks.graphiti.Graphiti` | **20/20** | **~92%** — Entities, edges, episodes, communities. **Bi-temporal search is real** (`invalid_at` filters honored — Graphiti `SearchFilters` parity, `valid_at`/`invalid_at` field comparisons + as-of snapshots; verified with mock tests). Constructor params differ (Neo4j vs STDB); return types are plain classes, not Pydantic. TypeScript port: `typescript/graphiti.ts` |
| [Honcho](https://github.com/plastic-labs/honcho) | `sdks.honcho.Honcho` | **14/14** | **~95%** — Workspace/peer/session/message/search + `.aio` async accessor; **`working_representation` is real** (LLM-generated, session-scoped; integration-tested). TypeScript port: `typescript/honcho.ts` |
| [QMD](https://github.com/tobi/qmd) | `sdks.qmd.QmdClient` | 31/31 | **~98%** — BM25+vector+hybrid search ✅, query AST ✅, collections/context ✅, fuzzy get ✅, glob multi-get ✅, status ✅ |
| [Cognee](https://github.com/topoteretes/cognee) | `sdks.cognee` (`add`/`cognify`/`search`/`delete`) | 39/39 | **~90%** — dataset-scoped KG, memory entries (QA/trace/feedback/skill_run), agent memory context, recall scopes; cloud-only features not applicable |
| [LangMem](https://github.com/langchain-ai/langmem) | `sdks.langmem` (tools + managers) | 33/33 | **~92%** — `create_manage_memory_tool`/`create_search_memory_tool`, LLM memory manager/searcher/thread-extractor, `ReflectionExecutor`, prompt optimizers — all over the LangGraph `BaseStore` interface (`StmemStore`) |
| [Letta](https://github.com/letta-ai/letta) | `sdks.letta.LettaMemory` | 28/28 | **~90%** — core memory blocks (persona/human), archival passages with semantic search, recall messages, full memory bundle |
| [Mnemosyne](https://github.com/AxDSan/mnemosyne) | `sdks.mnemosyne.Mnemosyne` | 31/31 | **~95%** — faithful SM-2 scheduling (easiness/interval/reps/lapses), decks, due cards, review history, sync log |
| Mem0 (TypeScript) | `typescript/mem0.ts` | 30/30 | **~88%** — Same API surface as Python Mem0 adapter; full CRUD + search + history on SpacetimeDB backend |
| Graphiti (TypeScript) | `typescript/graphiti.ts` | 12/12 | **~85%** — Entity, edge, episode, community types; search + CRUD; same parity gap as Python variant |

Additional features inspired by many projects (data model, schedules, CLI design — see Data Model table below).
### Adapter Caveats

While all adapters pass their test suites on a live SpacetimeDB instance, the following specific gaps exist:

**All 13 adapters (11 Python + 2 TypeScript)**
- **Cross-language parity:** Most Python adapters have a corresponding TypeScript implementation. The TypeScript adapters (`mem0.ts`, `zep.ts`, `graphiti.ts`, `hindsight.ts`, `honcho.ts`) mirror their Python counterparts against the same SpacetimeDB backend.
- All adapters require a running SpacetimeDB instance with the memory module published — a fundamentally heavier dependency than the upstream libraries (many of which work with local-only or cloud-hosted backends).
- The 5 newest adapters (LangMem, Cognee, Letta, QMD, Mnemosyne) are **native** — they use only the Spacetime-Memory SDK plus standard-library/pydantic, with zero runtime dependency on the upstream package (LangMem even degrades gracefully when `langchain-core` is absent).

**Mem0 (~100% coverage)**
- `entity_store` is implemented — vector-backed entity persistence over the `kg_node` table (alias for `.graph`, Mem0 v2 parity)
- `create_memory_tool()` returns real OpenAI-style function-calling tool schemas bound to the client's user/agent scope
- Exception types differ: the adapter raises generic `ValueError`/`RuntimeError`, not mem0's custom exception hierarchy (upstream v2.0.5 also uses generic exceptions; no `BaseMemoryException`)
- Configuration object differs: the adapter accepts a plain `config` dict instead of mem0's `MemoryConfig` type
- LLM conversation extraction uses the SDK's built-in LLM client, not mem0's provider config pattern

**Zep (~100% coverage)**
- The **graph namespace is real**: `graph.add`, `graph.search` (with `nodes`/`edges`/`episodes` scopes), `graph.node.get`/`get_by_user_id`, `graph.edge.get`, `graph.episode.get`, **`graph.add_triplet`** (source→edge→target with optional fact/rating), plus a full async mirror — all backed by the SpacetimeDB KG (16/16 graph tests pass)
- **LLM fact rating** is wired (`fact_rating_instruction` on add/init surfaces)
- Exception types match when `zep_python` is installed (raises real `NotFoundError`/`BadRequestError`/`ApiError`); fallback subclasses of `RuntimeError` are used when `zep_python` is not present
- The adapter replaces Zep's server entirely (Zep's Python SDK is a thin client to a proprietary server; ours replaces the server with SpacetimeDB)

**Graphiti (~92% coverage)**
- Constructor parameters differ significantly: our adapter takes SpacetimeDB connection params (`host`, `port`, `database`, `token`), while upstream expects Neo4j/`graph_driver` params — these are fundamentally different backends
- `add_triplet()` accepts an extra `group_id` parameter (SpacetimeDB namespace isolation)
- `search()` accepts extra `**kwargs` for SpacetimeDB-specific filter options
- Return types are plain Python classes rather than upstream's Pydantic models — this affects serialization, validation, and downstream type inference (`EntityNode` upstream is a Pydantic model with auto-validation; ours is a plain dataclass with the same fields)
- Bi-temporal edges are real (`valid_at`/`invalid_at` fields plus edge temporal versioning via `edge_group_id`), and bi-temporal *search* now honors `invalid_at` (Graphiti `SearchFilters` parity): `valid_at_after`/`valid_at_before`/`invalid_at_after`/`invalid_at_before` are independent field comparisons, never-invalidated edges handled correctly, and combined as-of snapshots work (13 mock tests)
- Search recipes are ported: `search_()` accepts `SearchConfig`-shaped configs with `cross_encoder` (local ONNX rerank) and `mmr_strength` (Maximal Marginal Relevance), both real in the underlying client search

**Hindsight (~95% coverage)**
- `documents`, `entities`, `operations`, and `monitoring` are real — backed by the `document`/`doc_chunk`, `kg_node`, and `change_event` tables plus the sidecar health endpoints (embedder :9090, Tantivy :9091)
- `webhooks` are **real and verified E2E** — `create`/`list`/`update`/`delete`/`fire` over the public `webhook` + `webhook_delivery` tables, with a Rust delivery sidecar (`server/webhook-sidecar`) polling pending deliveries, POSTing with HMAC-SHA256 signatures and exponential-backoff retries
- The real `hindsight_client` is not on PyPI — this adapter *is* the only Python SDK for Hindsight

**Honcho (~95% coverage)**
- `working_representation` is implemented (LLM-generated representation scoped to a session's messages; accepts `Session` object or raw session id) and integration-tested
- `Peer.sessions()` returns an empty page — no peer→session mapping exists in SpacetimeDB
- The real `honcho` is not on PyPI (the PyPI `honcho` package is a Procfile manager)

**LangGraph (~92% coverage)**
- `batch()` works across `GetOp`/`PutOp`/`SearchOp`/`ListNamespacesOp`, tolerating missing `refresh_ttl` via `getattr` default — no shape mismatch in practice

**LangMem (~92% coverage)**
- Tools/managers run against `StmemStore` (the LangGraph `BaseStore` implementation) — the LLM-driven extraction paths use the SDK's built-in LLM client (OpenAI-compatible, configurable via `LLM_BASE_URL`), not langmem's provider config
- When `langchain-core` is installed, tools are real `StructuredTool`s; without it, plain-callable fallbacks with `.invoke`/`.ainvoke` parity

**Cognee (~90% coverage)**
- Cloud-only features (managed data sources, cloud embeddings) are not applicable; dataset-scoped KG, memory entries, and recall are fully native
- `cognify()` runs the extraction pipeline synchronously over the local graph — no background worker model

**Letta (~90% coverage)**
- Core memory blocks, archival passages, and recall messages map to Spacetime-Memory's native stores; the agent-server/API surface (REST endpoints, tool-use loop) is out of scope for a memory-backend adapter

**QMD (~98% coverage)**
- Search is native hybrid (BM25 + embeddings) over Spacetime-Memory's tantivy/embedder sidecars — no separate QMD server process

**Mnemosyne (~95% coverage)**
- SM-2 scheduling is faithful to the SuperMemo-2 algorithm with the same DB fields (grade, next_rep, last_rep, easiness, acq_reps, ret_reps, lapses, active); the C-extension-backed core of upstream is reimplemented natively in Python

The percentages reflect test-pass rate against the upstream API shape, not feature-completeness — some gaps (like Qdrant-backed entity stores or Neo4j graph drivers) are fundamental architecture differences that cannot be bridged.


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
│  ┌──────────────────────────────────────────────┐  ┌──────────────┐  │
│  │  Embedder Sidecar (:9090)                    │  │  Tantivy     │  │
│  │  (ONNX — bge-m3 ONNX, 1024d)                │  │  Sidecar     │  │
│  │                                              │  │  (:9091)     │  │
│  │  /health  /metrics  /embed  /v1/embeddings   │  │  BM25 full-  │  │
│  └──────────────────────────────────────────────┘  │  text search │  │
│                                                    └──────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

> **Architecture (July 2026):** Two Rust sidecars provide embeddings and full-text search alongside the SpacetimeDB module: the **embedder sidecar** (`:9090`) serves ONNX embeddings (bge-m3, 1024d) via `/embed` and `/v1/embeddings`, and the **tantivy sidecar** (`:9091`) provides BM25 inverted-index search with lazy workspace opening, TTL-based idle eviction, and persistent HNSW vector graphs. Both are included in `docker compose`. The Python SDK has been restructured from a single monolithic `client.py` (4,643 lines) into a modular `client/` package with **28 domain-specific modules** — workspaces, memories, search, tags, documents, directory, history, stats, sessions, notes, embed, KG, admin, insights, rerank, export/import, task queue, pipeline, RBAC, skills/modules, ontology, checkpoint, dreaming, mental models, session search, query AST, and base/schemas/utils. The compounder was similarly split into modular workflows (core, export, graph, knowledge, ripple, search). Legacy monoliths preserved as `_client_legacy.py` and `_compounder_legacy.py`.

### New SDK Modules

The modular SDK introduces several new domain-specific modules for advanced workflows:

| Module | File | Purpose |
|--------|------|---------|
| Export/Import | `_export_import.py` | Export/import memories, notes, KG data in JSON, CSV, or markdown formats |
| Task Queue | `_task_queue.py` | Async task queue for deferred memory operations with monitoring |
| Pipeline | `_pipeline.py` | Configurable multi-stage pipelines (search → classify → summarize → store) |
| RBAC | `_rbac.py` | Role-based access control with roles, permissions, and user management |
| Skills/Modules | `_skills.py` | Skills and mods system with built-in catalog and lifecycle management |
| Ontology | `_ontology.py` | Entity types, relation types, and search recipe configuration |
| Checkpoint | `_checkpoint.py` | Memory checkpoint/restore for experiment reproducibility |
| Dreaming | `_dreaming.py` | Autonomous memory synthesis and pattern inference |
| Mental Models | `_mental_models.py` | Structured mental models for agent reasoning and decision-making |
| Session Search | `_session_search.py` | Full-text and semantic search across conversation sessions |

```python
# Quick-start examples for new SDK modules
from spacetime_memory import Client

c = Client(host="127.0.0.1", port="3001", database="your-db")
ws = c.create_workspace("my-app")

# Export/Import — dump memories as JSON
c.export_memories(ws["id"], format="json")

# Pipeline — multi-stage memory processing
pipe = c.create_pipeline(ws["id"], "ingest")
pipe.add_stage("search", query="AI agents")
pipe.add_stage("classify", categories=["tech", "philosophy"])
pipe.add_stage("summarize", max_tokens=200)
results = pipe.run()

# RBAC — manage roles and permissions
c.create_role(ws["id"], "editor", permissions=["read", "write", "delete"])
c.assign_role(ws["id"], "editor", user_id="user_abc")

# Task Queue — enqueue deferred operations
task = c.enqueue_task(ws["id"], "consolidate", params={"strategy": "dedup"})
status = c.get_task_status(ws["id"], task["id"])
```

### Frontend Architecture

The web frontend (`client/`) is built with **React 18 + TypeScript + Vite + shadcn/ui + Tailwind CSS** and provides **42 route-level pages** across 8 component directories:

**Page modules (42 pages in `client/src/pages/`):**

| Category | Pages |
|----------|-------|
| **Auth & Workspace** | AuthPage, Dashboard, Settings, Peers |
| **Memory** | MemoryBrowser, MemoryMetaEditor, MergeCandidates, TrustDashboard |
| **Knowledge Graph** | KnowledgeGraph, GraphViz, BlockGraph, Tours |
| **Notes & Content** | NoteEditor, NotesList, DailyNotes, NoteGraph |
| **Search & Query** | Search, SmartQuery, ContextTreeEditor, DirectoryBrowser |
| **Sessions & Agents** | Sessions, SessionReasoning, TrajectoryViz |
| **New SDK Modules** | ExportImportPage, TaskQueuePage, PipelinePage, RBACPage, SkillsModsPage, OntologyPage |
| **System & Monitoring** | Documents, AlertsPanel, ObservationsPage, CodeExplorer, ProxyMetricsDashboard, ReviewPage, WebhooksPage |

All pages use the `callReducer`/`executeSql` pattern for SpacetimeDB interaction, `Card`/`Input`/`Button`/`Badge`/`Tabs` shadcn components, and follow loading/empty/error state conventions.

```bash
# Start frontend dev server
cd client
npm install
npm run dev    # → http://localhost:5173
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

The module exposes **270+ reducers** covering full CRUD plus special operations:

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

**All 10 adapters** live in `sdk/python/spacetime_memory/sdks/` and are importable as drop-in replacements:

```python
# Mem0
from spacetime_memory.sdks import Mem0Memory
m = Mem0Memory(config={"host": "127.0.0.1", "port": "3001"})
m.add("I like pizza", user_id="alice")

# Hindsight
from spacetime_memory.sdks import Hindsight
h = Hindsight(base_url="http://127.0.0.1:3001", api_key="optional")
h.retain("my_bank", "I like pizza")

# Honcho
from spacetime_memory.sdks import Honcho
honcho = Honcho(workspace_id="my_workspace")
p = honcho.peer("alice")
s = honcho.session("my_session")
s.add_messages([{"role": "user", "content": "I like pizza"}])
```

## Setup

Two paths depending on your situation:

### Quick Start (I have a running SpacetimeDB)

If you already have a SpacetimeDB instance with the memory module published:

```bash
pip install spacetime-memory
```

```python
from spacetime_memory import Client

c = Client(host="127.0.0.1", port="3001", database="your-db")
ws = c.create_workspace("my-app")
c.store(ws["id"], "AI agents need persistent memory", peer_id="me")

# Search across all strategies
results = c.search(ws["id"], "AI agents", semantic=True)
```

Or use any of the **7 drop-in adapters** with the same import API you already know:

```python
from spacetime_memory.sdks.mem0 import Memory   # Mem0 API
from spacetime_memory.sdks.hindsight import Hindsight  # Hindsight API
from spacetime_memory.sdks.zep import Zep       # Zep API
from spacetime_memory.sdks.graphiti import Graphiti  # Graphiti API
from spacetime_memory.sdks.honcho import Honcho  # Honcho API
from spacetime_memory.sdks.langchain import StmemStore  # LangGraph BaseStore
from spacetime_memory.sdks.cognee import CogneeMemory  # Cognee KG-native
```

See `docs/getting-started.md` for more SDK examples.

### Full Stack Setup (from scratch — need to run STDB)

If you're setting up a SpacetimeDB instance for the first time:

**Prerequisites:**
- Rust toolchain (`cargo`, `rustup`)
- SpacetimeDB CLI v2.6+ (`spacetime version upgrade`)
- Python 3.10+ (for SDK/CLI/MCP)

**1. Clone & enter the repo:**
```bash
git clone https://github.com/omiinaya/spacetime-memory.git
cd spacetime-memory
```

**2. Start SpacetimeDB:**
```bash
spacetime start --listen-addr 0.0.0.0:3001 &
```

**3. Build & publish the Rust module:**
```bash
cd server/spacetimedb
cargo build --target wasm32-unknown-unknown
spacetime publish spacetime-memory -p ./ --yes
```

**4. Install Python SDK & CLI:**
```bash
cd sdk/python
pip install -e .
# CLI available as `stmem`:
stmem --help
```

**5. Configure embeddings (optional — needed for semantic search):**
```bash
export OPENAI_API_KEY=<your-key>
export OPENAI_BASE_URL=http://127.0.0.1:4000/v1
export EMBEDDING_MODEL=bge-m3
```
The embedding proxy at `127.0.0.1:4000` forwards to NVIDIA NIM (bge-m3, 1024-dim). See [CONFIG.md](CONFIG.md) for all env vars.

**6. Start MCP server (optional — for agent integration):**
```bash
stmem serve                  # stdio transport (local LLM integration)
stmem serve --transport sse  # HTTP SSE transport
```

**7. Start frontend (optional):**
```bash
cd client
npm install
cp .env.example .env
npm run dev                  # opens on 127.0.0.1:5173
```

Now jump back to [Quick Start](#quick-start-i-have-a-running-spacetimedb) above to use the Python SDK.

### CLI Commands

All compounder SDK methods have terminal equivalents via `stmem`. Key commands:

| SDK Method / Module | CLI Command |
|--------------------|-------------|
| `compounder.store_answer()` | `stmem store-answer --query "..." --answer "..."` |
| `compounder.cross_link()` | `stmem cross-link --workspace <id>` |
| `compounder.lint_workspace()` | `stmem lint --workspace <id>` |
| `compounder.export_workspace()` | `stmem export markdown ./path/ --workspace <id>` |
| `compounder.ingest_source()` | `stmem ingest file --path article.txt` |
| `compounder.create_entity_page()` | `stmem entity-page --name "..." --description "..."` |
| **Export/Import** | `stmem export memories --format json --workspace <id>` |
| | `stmem import memories --file ./data.json --workspace <id>` |
| **Task Queue** | `stmem task enqueue --type consolidate --workspace <id>` |
| | `stmem task list --workspace <id>` |
| | `stmem task status <task-id> --workspace <id>` |
| **Pipeline** | `stmem pipeline create --name "ingest" --workspace <id>` |
| | `stmem pipeline run <pipeline-id> --workspace <id>` |
| **RBAC** | `stmem rbac create-role --name editor --permissions read,write` |
| | `stmem rbac assign-role --role editor --user <user-id>` |
| **Skills/Mods** | `stmem skills list` |
| | `stmem skills install <skill-name>` |
| **Knowledge Graph** | `stmem kg node create --label "Entity" --type concept` |
| | `stmem kg edge create --src <id> --tgt <id> --relation "informed_by"` |
| **Ontology** | `stmem ontology entity-types` |
| | `stmem ontology relation-types` |
| **Checkpoint** | `stmem checkpoint create --name "pre-experiment"` |
| | `stmem checkpoint restore <checkpoint-id>` |
| **Session Search** | `stmem session search --query "conversation about X"` |
| Tantivy status | `stmem tantivy status` |
| Tantivy evict workspace | `stmem tantivy evict <workspace-id>` |
| Tantivy reindex | `stmem tantivy reindex` |

All CLI commands support `--output json` for machine-readable output.

See `stmem --help` for the full command list. There are **30+ CLI command groups** covering workspaces, peers, sessions, memories, notes, KG, documents, connectors, context, replication, decay, mental models, plugins, metrics, auth, and more.

### Running Tests

```bash
# Unit tests only — no STDB needed (~30s)
cd sdk/python && python -m pytest tests/ -m unit -v

# Full suite (unit + integration) — needs STDB on :3001
make test

# Integration tests only — auto-builds module, auto-publishes
make test-integration

# Run specific test file
cd sdk/python && python -m pytest tests/test_memories.py -v

# Run tests matching a keyword (e.g., all pipeline tests)
cd sdk/python && python -m pytest tests/ -k "pipeline" -v

# Run specific adapter test suite
cd sdk/python && python -m pytest tests/ -k "mem0 or zep or graphiti" -v

# Rust module tests
make test-rust

# TypeScript SDK tests
cd sdk/typescript && npx vitest run

# Frontend tests (vitest)
make test-frontend

# End-to-end smoke test
make smoke
```
The integration tests auto-publish the module via HTTP API. If no STDB is running, they skip cleanly.

**Current test counts:**
| Suite | Count | Status |
|-------|-------|--------|
| Rust (STDB module) | **859** ✅ | 0 failed, 0 compiler warnings |
| TypeScript SDK | **334** ✅ | 15 files, 0 failed |
| Frontend (Vitest) | **97** ✅ | 34 files covering all 42 pages |
| Python SDK (unit) | **604+** ✅ | 7,664 test functions across 237 files |

### Configuration Reference

All env vars are documented in [CONFIG.md](CONFIG.md). Key ones:

| Variable | Default | Purpose |
|----------|---------|---------|
| `SPACETIMEDB_HOST` | `127.0.0.1` | STDB server address |
| `SPACETIMEDB_PORT` | `3001` | STDB HTTP port |
| `SPACETIMEDB_DB` | `spacetime-memory` | Database identity hex |
| `OPENAI_API_KEY` | *(none)* | API key for embeddings + LLM |
| `OPENAI_BASE_URL` | `http://127.0.0.1:4000/v1` | OpenAI-compatible endpoint |
| `EMBEDDING_MODEL` | `bge-m3` | Embedding model name |

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

### Tiered Memory (Veracity Tiers)

Memories auto-escalate through 5 veracity tiers based on **Bayesian confidence scoring**:

| Tier | Label | Requirement |
|------|-------|-------------|
| **CERTAIN** | Confirmed | confidence > 0.90 AND evidence >= 10 |
| **HIGH** | High | confidence > 0.80 AND evidence >= 3 |
| **MEDIUM** | Medium | confidence > 0.60 AND evidence >=3 |
| **LOW** | Low | confidence > 0.40 |
| **SPECULATIVE** | Speculative | Anything below |

Confidence is computed from a Beta(α, β) posterior: `confidence = α / (α + β)`, starting from a uniform Beta(1,1) prior. Each observation updates the posterior — positive evidence increases α, contradictory evidence increases β. Compound veracity on every search hit (small α+0.05 boost) so frequently accessed memories automatically gain confidence.

Trust scores weigh search results. Strength decays over time via `effective_strength = strength · e^(−λ·Δt)`.

### Zero-Scheduler Maintenance

No cron, no scheduled reducers, no external timer — maintenance happens on the read/write path: **lazy expiration** (expired memories simply stop appearing), **lazy decay** (`effective_strength` computed at query time, written back on touch), **dedup-on-write** (near-duplicates reinforce the existing memory instead of accumulating), and **amortized compaction** (every 50th store runs a bounded maintenance slice). The admin reducers (`consolidate_memories`, `decay_weak_memories`, `expire_memories`) remain for explicit operator use via SDK/CLI.

### Anomaly Detection

Statistical outlier detection for memory quality monitoring. The `detect_anomalies` reducer computes z-scores across three metrics:

- **Confidence outliers**: memories with confidence > 3σ from workspace mean
- **Length outliers**: unusually short or long content (>3σ)
- **Entity outliers**: unusually many or few entity references (>3σ)

Results stored in the `anomaly_result` table for frontend display or automated review. Accessible via `client.detect_anomalies(workspace_id)`.

### Query Cache with TTL

Hybrid search results are cached by `(workspace_id, query_hash)` with configurable TTL (`cache_ttl_ms`). When fresh results exist (all rows newer than `now - cache_ttl_ms`), the full search pipeline is skipped entirely. Stale cache entries are deleted before re-computation.
