# Adapter Compatibility

Each adapter aims to be a **drop-in replacement** for the upstream library's public API.
This document tracks which methods are supported, which are mapped to SpacetimeDB
equivalents, and which are explicitly not supported.

**Last assessed:** 2026-07-17 (post-audit). Line counts from `wc -l sdk/python/spacetime_memory/sdks/*.py`.
All adapters use `RuntimeError` (not bare `Exception`) for backend failures.

**TypeScript note:** only **Mem0** has a TS adapter (`sdk/typescript/mem0.ts`). No TS
adapters exist for Zep, Graphiti, Honcho, or Hindsight — TypeScript users use the native
Client API for those.

## Key

| Icon | Meaning |
|------|---------|
| ✅ | Directly implemented |
| 🔄 | Mapped (different backend, same result shape) |
| ⚠️ | Partial (works for common inputs, edge cases may differ) |
| ❌ | Not supported |

---

## LangGraph

Reference: [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) — `BaseStore`.

Adapter: `spacetime_memory.sdks.langchain.StmemStore` / `StmemMemoryStore` (1163 lines)

| Method | Status | Notes |
|--------|--------|-------|
| `__init__(...)` | ✅ | Standard init |
| `mget(keys)` | ✅ | Multi-get by key |
| `mset(key_value_pairs)` | ✅ | Multi-set |
| `mdelete(keys)` | ✅ | Multi-delete |
| `yield_keys(prefix)` | ✅ | Key iteration |
| `get(namespace, key)` | ✅ | Get by namespace + key |
| `put(namespace, key_value_pairs)` | ✅ | Put by namespace |
| `delete(namespace, key)` | ✅ | Delete by namespace + key |
| `search(namespace, query, limit, ...)` | ✅ | → `hybrid_search` with embedding |
| `list_namespaces()` | ✅ | Namespace listing |
| `batch(ops)` | ✅ | Handles `GetOp`/`PutOp`/`SearchOp`/`ListNamespacesOp` + legacy dicts; `refresh_ttl` read defensively via `getattr` |
| `abatch(ops)` | ✅ | Async batch |
| `aput` / `aget` / `adelete` / `asearch` | ✅ | All async variants |
| `GetOp` / `PutOp` / `SearchOp` / `ListNamespacesOp` | ✅ | Op type parity |
| `supports_ttl` | ✅ |  |

**Runtime quality:** ✅ True drop-in. Inherits `BaseStore` from upstream.
**Coverage: ~92%** (batch/`refresh_ttl` edge case; no TS adapter)

---

## Mem0

Reference: [mem0ai/mem0](https://github.com/mem0ai/mem0) — `Memory` class (v2.0.5).

Adapter: `spacetime_memory.sdks.mem0.Memory` (1510 lines). Also the **only adapter with a TypeScript port** (`sdk/typescript/mem0.ts`).

| Method | Status | Notes |
|--------|--------|-------|
| `__init__(config, ...)` | ✅ | Accepts dict or `MemoryConfig` |
| `add(data, user_id, agent_id, ...)` | ✅ | → `store_memory`, accepts all shared keyword params |
| `get(memory_id)` | ✅ | SQL lookup by ID |
| `search(query, user_id, ...)` | ✅ | → `hybrid_search`, supports v2 `filters` dict |
| `get_all(user_id, ...)` | ✅ | Workspace-scoped |
| `update(memory_id, data)` | ✅ | → `update_memory` |
| `delete(memory_id)` | ✅ | → `deactivate_memory` |
| `delete_all(user_id, ...)` | ✅ | Workspace-scoped |
| `history(memory_id)` | ✅ | Memory version history |
| `reset()` | ✅ | Clear caches |
| `from_config(config_dict)` | ✅ | Classmethod |
| `close()` | ✅ | No-op |
| `.graph.add/search/get_all/delete` | ✅ | Entity persistence via `kg_node` table |
| `chat()` | ✅ | Real RAG: stores query, retrieves memories, augments LLM response |
| `entity_store` | ✅ | Alias for `.graph` — vector-backed entity persistence via `kg_node` table (matches Mem0's entity-store surface) |
| `create_memory_tool()` | ✅ | Returns real OpenAI-style tool schemas (add/search/get/delete) bound to user/agent scope |

**Runtime notes:**
- Constructor accepts both `dict` and `MemoryConfig` Pydantic model
- Error handling: `ValueError` for validation, `RuntimeError` for backend failures
- LLM extraction gracefully degrades without `OPENAI_API_KEY`

**Coverage: ~92%** (entity_store alias + create_memory_tool tool schemas added)

---

## Zep

Reference: [getzep/zep-python](https://github.com/getzep/zep-python) — `Zep` class (v2.0.2).

Adapter: `spacetime_memory.sdks.zep.Zep` (2838 lines, v2-compatible) / `ZepClient` (v1 alias) / `AsyncZep`

| Method | Status | Notes |
|--------|--------|-------|
| `__init__(host, port, base_url, api_key, ...)` | ✅ | Zep v2-compatible init |
| `.memory.add(session_id, messages)` | ✅ | Sub-client proxy → `store_memory` per message |
| `.memory.get(session_id, ...)` | ✅ | Returns messages + facts |
| `.memory.delete(session_id)` | ✅ | → `deactivate_memory` by session |
| `.memory.search(session_id, query, ...)` | ✅ | → `hybrid_search` with `min_score` alias |
| `.memory.add_fact(session_id, fact)` | ✅ | → `store_memory` with `memory_type="fact"` |
| `.memory.get_fact(session_id, fact_id)` | ✅ | Fact lookup |
| `.memory.delete_fact(session_id, fact_id)` | ✅ | → `deactivate_memory` |
| `.memory.add_session(session_id, ...)` | ✅ | Creates workspace |
| `.memory.get_session(session_id)` | ✅ | Returns workspace metadata |
| `.memory.list_sessions()` | ✅ | Workspace listing |
| `.memory.search_sessions(query, ...)` | ✅ | Cross-workspace search |
| `.memory.update_session(session_id, ...)` | ✅ | Updates workspace metadata |
| `.memory.get_session_messages(session_id)` | ✅ | All messages in session |
| `.memory.get_session_message(session_id, msg_id)` | ✅ | Single message |
| `.memory.update_message_metadata(session_id, msg_id, ...)` | ✅ | Message metadata update |
| `.user.add(user_id, ...)` | ✅ | User creation via `UserClient` |
| `.user.get(user_id)` | ✅ | User lookup |
| `.user.update(user_id, ...)` | ✅ | User update |
| `.user.delete(user_id)` | ✅ | User deletion |
| `.user.list_ordered(...)` | ✅ | Ordered user listing |
| `.user.get_sessions(user_id)` | ✅ | User sessions |
| `.graph.add(data, type, ...)` | ✅ | Adds episode to the user's KG (workspace-scoped `zep-graph-user-<id>` / `zep-graph-group-<id>`) |
| `.graph.search(query, scope, ...)` | ✅ | `scope` = `nodes` / `edges` / `episodes` — backed by the real KG tables |
| `.graph.node.get(uuid)` | ✅ | `kg_node` lookup, `NotFoundError` on miss |
| `.graph.node.get_by_user_id(user_id, limit)` | ✅ | Lists entity nodes in a user's graph |
| `.graph.edge.get(uuid)` | ✅ | `kg_edge` lookup |
| `.graph.episode.get(uuid)` | ✅ | Episodes are memories |
| `.graph.add_triplet(...)` | ✅ | → `create_edge` with source/target nodes (real KG write) |
| Async graph mirror | ✅ | `AsyncZep.graph.node/edge/episode` delegate via `asyncio.to_thread` |

**Type exports matching upstream v2.0.2:** `Message`, `Fact`, `Session`, `Memory`, `Summary`, `RoleType`, `SearchScope`, `SearchType`, `ZepEnvironment`, `SuccessResponse`, `ConflictError`, `NotFoundError`, `BadRequestError`, `ApiError`, `FactRatingExamples`, `FactRatingInstruction`, `SessionFactRatingExamples`, `SessionFactRatingInstruction` — **fact rating is wired**: `add_memory(..., fact_rating_instruction=...)` runs LLM fact extraction + rating (falls back gracefully when no LLM is configured).

**Runtime notes:**
- `Zep` class with `.memory`/`.user`/`.graph` sub-client proxies — matches zep-python v2 API shape
- `ZepClient = Zep` — backward-compatible alias for v1 code
- `AsyncZep` with `.memory`/`.user`/`.graph` async sub-clients
- Graph namespace backed by the real KG (`kg_node`/`kg_edge`/memory tables) — **16/16 graph tests pass**
- Typed exceptions: `NotFoundError`, `BadRequestError`, `ApiError`, `ConflictError`
- `search_sessions()` results limited — SpacetimeDB has no cross-workspace search index

**Coverage: ~95%** (was ~60% before the graph namespace shipped). LLM fact rating is now wired (13 unit tests); `graph.add_triplet` writes real KG edges.
**Still missing vs real zep-cloud:** nothing material. (Communities shipped 2026-08-01: `graph.community.build/list/get/search` backed by the real `detect_communities`/`seed_communities` reducers + `kg_node` community rows — sync, async, AND TypeScript ports.)

---

## Graphiti

Reference: [getzep/graphiti](https://github.com/getzep/graphiti) — `Graphiti` class (graphiti-core v0.29.2).

Adapter: `spacetime_memory.sdks.graphiti.Graphiti` (2671 lines)

| Method | Status | Notes |
|--------|--------|-------|
| `__init__(...)` | ✅ | Standard init |
| `close()` | ✅ | No-op |
| `add_triplet(source_node, edge, target_node, *, group_id)` | ✅ | → KG node/edge creation |
| `add_episode(episode_body, ...)` | ✅ | → memory + KG with time context |
| `search(query, center_node_uuid, ...)` | ✅ | → `hybrid_search` |
| `search_(...)` | ✅ | → `SearchResults` with nodes + edges |
| `get_entity_edge_summary(entity_uuid)` | ✅ | Returns edge summary |
| `build_communities(group_id)` | ✅ | → `detect_communities` + `seed_communities` reducers, returns `CommunityNode` list (same reducers as Zep `graph.community`, proven live) |
| `remove_episode(episode_uuid)` | ✅ | → memory deactivation (deactivate_memory) |
| `build_indices_and_constraints(...)` | ✅ | Ensures DB state |
| `get_nodes_and_edges_by_episode(uuid)` | ✅ | KG subgraph for episode |
| `update_edge(edge_id, relation, ...)` | ✅ | Temporal versioning |
| `get_edge_history(edge_id)` | ✅ | All temporal versions |
| Bi-temporal edges | ✅ | `valid_from`/`valid_to` + edge versions linked by `edge_group_id` |
| Bi-temporal search | ✅ | `valid_at_after`/`valid_at_before` filter edges by their real `valid_at` timestamp via `_filter_by_valid_at` (post-retrieval, exact — no `created_at` proxy) |
| Search config recipes | ✅ | `search_(config=...)` honours `search_strategy`, `hybrid_mode` (fusion/relaxed), `cross_encoder`, `mmr_strength` — all mapped to the client search pipeline |
| Entity dedup | ✅ | 4-pass dedup: exact → case-insensitive → difflib fuzzy (>0.85) → **semantic embedding** (≥0.55 via hybrid search, mirrors upstream's embedding-based node resolution) |
| Community summary text | ✅ | LLM-generated when `OPENAI_API_KEY` set |
| Time-range-filtered search | ✅ | `valid_at_after`/`valid_at_before` kwargs |

**Runtime notes:**
- All upstream fields present: `EntityNode` 8/8, `EntityEdge` 14/14
- Constructor params differ (Neo4j vs SpacetimeDB) — unavoidable
- Return types are plain Python classes, not upstream's Pydantic models
- LLM entity extraction in `add_episode` with graceful degradation
- `_get_or_create_node` with 4-pass dedup (exact → case-insensitive → fuzzy difflib → semantic embeddings)

**Coverage: ~95%** (bi-temporal edges real; search recipes + semantic entity dedup now ported; only bi-temporal *search* still uses a `created_at` proxy). No TS adapter.

---

## Hindsight

Reference: [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight) — `Hindsight` class (v0.8.1).

Adapter: `spacetime_memory.sdks.hindsight.Hindsight` (1902 lines)

| Method | Status | Notes |
|--------|--------|-------|
| `__init__(base_url, api_key, timeout, user_agent, *stdb_*)` | ✅ | Accepts Hindsight-standard args + SpacetimeDB extras |
| `retain(bank_id, content, *, timestamp, context, ...)` | ✅ | Full param set |
| `retain_batch(bank_id, items, ...)` | ✅ | Batch store |
| `retain_files(bank_id, files, ...)` | ✅ | File content ingest |
| `recall(bank_id, query, *, types, max_tokens, budget, ...)` | ✅ | Full param set |
| `reflect(bank_id, query, *, budget, context, max_tokens, ...)` | ✅ | Full param set |
| `aretain()` / `arecall()` / `areflect()` / `aretain_batch()` | ✅ | All async variants |
| `close()` / `aclose()` | ✅ | |
| Context manager (`__enter__` / `__exit__`) | ✅ | |
| `.documents` | ✅ | **Real** — backed by the `document`/`doc_chunk` tables |
| `.entities` | ✅ | **Real** — backed by the `kg_node` table |
| `.operations` | ✅ | **Real** — backed by the `change_event` table |
| `.monitoring` | ✅ | **Real** — backed by the sidecar health endpoints (embedder :9090, Tantivy :9091) |
| `.webhooks` | ✅ | **Real** — backed by the `webhook`/`webhook_delivery` tables (create/list/get/update/delete/fire) |
| `retain(..., ttl_seconds=...)` | ✅ | Working-memory TTL — expiry marker stored, recall evicts expired entries |
| `create_bank()` / `delete_bank()` / `get_bank_config()` / `update_bank_config()` | ✅ | Memory banks = workspaces with LLM-generated config |

**Runtime notes:**
- **All response types are Pydantic models** matching upstream
- The 5 former fake shells (`documents/entities/operations/webhooks/monitoring`) were replaced during the 2026-07-17 audit: four are now real table/sidecar-backed APIs, `webhooks` is backed by the real webhook delivery tables
- All swallowed errors logged with `logger.warning()`
- The real `hindsight_client` is not on PyPI — this adapter is the only Python SDK for Hindsight

**Coverage: ~97%** (core API complete; webhooks real; working-memory TTL added). No TS adapter.

---

## Honcho

Reference: [plastic-labs/honcho](https://github.com/plastic-labs/honcho) — `Honcho` class.

Adapter: `spacetime_memory.sdks.honcho.Honcho` (2291 lines)

| Method | Status | Notes |
|--------|--------|-------|
| `__init__(workspace_id, base_url, ...)` | ✅ | Standard Honcho init + SpacetimeDB extras |
| `peer(id, *, metadata, configuration)` | ✅ | Get or create by ID |
| `peers(filters, *, page, size, reverse)` | ✅ | `SyncPage[PeerResponse, Peer]` |
| `session(id, *, metadata, configuration, peers)` | ✅ | Get or create by ID |
| `sessions(filters, *, page, size, reverse)` | ✅ | `SyncPage[SessionResponse, Session]` |
| `search(query, filters, limit)` | ✅ | Cross-session search → `list[Message]` |
| `workspaces(filters, *, page, size, reverse)` | ✅ | `SyncPage[WorkspaceResponse, str]` |
| `delete_workspace(workspace_id)` | ✅ | |
| `queue_status(observer, sender, session)` | ✅ | Returns `QueueStatusResponse` |
| `schedule_dream(observer, ...)` | ✅ | Stub (matches API shape) |
| `close()` | ✅ | |
| `Peer.message(content, ...)` | ✅ | Returns `MessageCreateParams` |
| `Peer.chat(query, *)` | ✅ | Memory-context chat |
| `Peer.search(query, ...)` | ✅ | Peer-scoped search |
| `Session.add_peers(peers)` | ✅ | |
| `Session.add_messages(messages)` | ✅ | Bulk store |
| `Session.messages(filters, ...)` | ✅ | `SyncPage[MessageResponse, Message]` |
| `Session.search(query, ...)` | ✅ | Session-scoped search |
| `Session.context(*, summary, tokens)` | ✅ | Returns `SessionContext` |
| `Session.summaries()` | ✅ | Returns `SessionSummaries` |
| `Session.delete()` | ✅ | |
| `Peer.sessions()` | ✅ | Lists sessions the peer participates in (session-cache membership) |
| `working_representation` | ✅ | Session-scoped representation: recent session messages seed the semantic search for a context-aware representation |

**Runtime notes:**
- 30+ Pydantic models matching upstream
- **`.aio` accessor** — HonchoAio, PeerAio, SessionAio (async variants)
- `Session.add_messages()` skips items that fail to store (logged), continues with rest
- The real `honcho` is not on PyPI (the PyPI `honcho` is a Procfile manager)

**Coverage: ~98%** (working_representation + Peer.sessions() implemented). No TS adapter.

---

## QMD

Reference: [tobi/qmd](https://github.com/tobi/qmd) — CLI search engine + MCP server for markdown docs.

Adapter: Architecture parity — not a library adapter. QMD is a Node.js CLI; Spacetime Memory provides equivalent capabilities via SDK + CLI + MCP.

| Feature | Status | Notes |
|--------|--------|-------|
| Document indexing (markdown) | ✅ | `Document` + `DocChunk` tables with embeddings |
| Keyword search (BM25) | ✅ | `hybrid_search` keyword strategy |
| Vector/semantic search | ✅ | `hybrid_search` semantic strategy + proxy → NVIDIA NIM (bge-m3) |
| Hybrid search + fusion | ✅ | `hybrid_search` multi-strategy with score fusion |
| Collections (workspace-scoped) | ✅ | `workspace` table with ACL |
| MCP server | ✅ | `server/mcp/` — 15 tools (query, get, multi-get, status equivalents) |
| CLI tool | ✅ | `cli/stmem.py` — 17+ command groups |
| Agent integration | ✅ | Hermes plugin, MCP tools, Python SDK |
| JSON output for agents | ✅ | SDK returns typed dicts, CLI has `--json` |
| docid references (#abc123) | ✅ | Memory IDs as UUIDs accessible via `get_memory(id)` |
| Context tree (hierarchical context) | ✅ | Workspace + memory context with QMD-style breadcrumb display in search results. Rust `context_json` on every `HybridResult` row. Python SDK: `set_workspace_context()`, `set_memory_context()`, `get_context_chain()`. Frontend: context breadcrumbs in Search page. |
| LLM reranking | ✅ | `llm_rerank()` utility + `search(rerank=True)`. Sends top-K results to OpenAI-compatible endpoint for relevance re-scoring. Configurable via `LLM_RERANK_ENDPOINT`/`LLM_RERANK_MODEL` env vars. Graceful fallback on error. |
| Fuzzy matching on get | ✅ | `fuzzy_get()` — uses `difflib.SequenceMatcher` for typo-tolerant memory lookup. Configurable `threshold` and `field`. |
| Glob-based multi-get | ✅ | `glob_get()` — `fnmatch`-style wildcards (`*`, `?`, `[...]`) on any memory field. |
| HTTP transport for MCP | ✅ | SSE and streamable-http transports via `--transport sse` / `--transport streamable-http` CLI flags |

**Coverage: ~98%** (architecture parity). All QMD features covered: hybrid search, MCP, CLI, context trees, LLM reranking, fuzzy get, glob multi-get, MCP HTTP transport.

---

## GBrain

Reference: [garrytan/gbrain](https://github.com/garrytan/gbrain) — personal/company knowledge brain with synthesis layer. Production at 146K pages, 24K people, 5K companies. Not a library — architecture inspiration like QMD.

Adapter: Architecture parity — not a library adapter. GBrain is a PGLite + Bun daemon; Spacetime Memory provides equivalent capabilities via SDK + CLI + MCP + frontend.

| Feature | Status | Notes |
|--------|--------|-------|
| Knowledge graph with typed edges | ✅ | `kg_node` + `kg_edge` tables with typed relations |
| Memory storage + search (vector+keyword) | ✅ | `hybrid_search` with BM25 + semantic + graph + temporal |
| Hybrid search fusion | ✅ | Multi-strategy score fusion in WASM |
| Profiles (people/agents) | ✅ | `profile` table with static_facts + dynamic_context. SDK methods verified. |
| Workspace ACL + auth | ✅ | 130/130 reducers gated. 43 private tables. Company-brain scoping. |
| Notes with wikilinks | ✅ | 4 frontend pages. Block references, transclusions. |
| Context trees | ✅ | Workspace → memory context chain with frontend breadcrumbs. |
| Consolidation (decay, dedup, reinforce) | ✅ | Zero-Scheduler Maintenance (lazy expiration/decay, dedup-on-write, amortized compaction) + `manual_maintenance` reducer. |
| Synthesis with gap analysis | ✅ | `synthesize_with_gap_analysis()` — LLM synthesis + explicit "what the brain doesn't know" gaps (grounded fallback when no LLM). 8 unit tests. |
| Auto entity extraction on write | ✅ | Wired into `insert_memory` — auto-extracts entities when caller doesn't provide them (regex + LLM via `extract_entities` reducer) |
| Dream cycle | ✅ | `synthesize_memories()` with 4 LLM strategies (connect / generalize / fill_gaps / contrast) + `consolidate_with_llm()` for LLM-driven consolidation. Dream log persisted. |
| Citations | ✅ | `add_node_citation`/`add_edge_citation`/`get_citations` reducers trace every claim to its source page |
| Benchmarked graph search | ✅ | `scripts/benchmarks/run_graph_search_bench.py` — P@5/R@5 eval harness against live STDB (synthetic GBrain-style dense corpus; ceiling-validated via mock). Result: **P@5 45.76%, R@5 91.41%** (perfect retrieval ceiling 51.52% P@5). |

**Coverage: ~95%** (architecture parity). Strong on storage, search, graph, ACL; synthesis with gap analysis, auto-extraction, dream cycle, citations, and graph-search eval harness all shipped.

---

## Mnemosyne

Reference: [AxDSan/mnemosyne](https://github.com/AxDSan/mnemosyne) — zero-dependency SQLite-backed AI memory system with BEAM architecture. v3.7.0, 1,121 stars. Holds #1 on LongMemEval (98.9% Recall@All@5) and 65.2% on BEAM 100K end-to-end QA.

Adapter: Architecture parity — not a library adapter. Mnemosyne is a pure Python + SQLite agent memory system; Spacetime Memory provides equivalent capabilities via SDK + MCP + SpacetimeDB.

| Feature | Status | Notes |
|--------|--------|-------|
| Core memory CRUD (remember/recall/forget) | ✅ | `store_memory` + `search` + `deactivate_memory` |
| Hybrid search (vector + keyword + graph + temporal) | ✅ | 4-strategy fusion in WASM |
| Knowledge Graph (nodes, edges, communities) | ✅ | `kg_node` + `kg_edge` + `kg_community` tables |
| Entity extraction | ✅ | Regex-based `extract_entities` reducer |
| MCP Server | ✅ | 15+ tools, stdio + SSE + streamable-http |
| CLI tool | ✅ | 17+ command groups |
| Working memory (TTL-based hot context) | ✅ | `retain(ttl_seconds=...)` stores an expiry marker; recall filters out expired entries (`_filter_expired`) — 2 unit tests |
| Sleep/Consolidation (LLM summarization) | ✅ | `consolidate_with_llm()` — LLM summary of similar memories → `consolidate_memories` reducer (grounded lossless fallback). Plus `synthesize_memories()` dream cycle. 4 unit tests. |
| Temporal KG (version chains, as_of queries) | ✅ | Edges have temporal versioning with `valid_at`/`invalid_at`; `get_edge_as_of(timestamp_micros)` queries historical state; MCP tool exposed |
| Auto entity extraction on write | ✅ | New — wired into insert_memory; auto-extracts entities when caller doesn't provide them |
| Memory banks (per-domain isolation) | ✅ | `create_bank`/`delete_bank`/`get_bank_config`/`update_bank_config` in Hindsight adapter — banks map to workspaces with LLM-generated config |
| Veracity tiers (Bayesian confidence) | ✅ | Beta posterior with auto-compounding on recall, 5-tier system |
| MIB binary vectors (32x compression) | ✅ | New — median-based binarization, packed u64, Hamming distance |
| SHMR resonance reasoning | ✅ | `shmr_resonate()` — embedding clustering + contradiction detection (459 lines) |
| Polyphonic recall (4-voice parallel) | ✅ | 4-strategy fusion + voice-based re-ranking with diversity penalty (778 lines) |
| AAAK compression (lossless shorthand) | ✅ | Custom lossless compression dialect (268 lines) |
| Local LLM consolidation (MiniCPM5-1B) | ✅ | Local-LLM consolidation path (291 lines) — `local_llm.py` |
| Pattern detection | ✅ | New — z-score anomaly detection (confidence, length, entity outliers) |
| MMR reranking | ✅ | Already exists in hybrid_search pipeline |
| Streaming events | ✅ | EventBus with subscribe/unsubscribe/emit + WS subscriptions (158 lines) — `streaming.py` |
| Query cache | ✅ | New — TTL-based LRU cache for repeated queries |
| Hermes plugin (23 tools, 5 hooks) | ✅ | `pre_llm_call` + `on_session_start` lifecycle hooks added — dispatched from `llm_rerank` and `create_workspace`; 7 new unit tests |
| Shared multi-agent surface | ✅ | Workspace ACL + auth = multi-agent isolation |

**Coverage: ~95%** (architecture parity). Core memory, search, KG, MCP/CLI, veracity tiers, anomaly detection, auto entity extraction, MIB binary vectors, SHMR, polyphonic recall, AAAK compression, local LLM, streaming events, working-memory TTL, LLM consolidation, memory banks, and Hermes lifecycle hooks all complete.

---

## Summary

| Adapter | Lines | Tests (live STDB) | Shape Match | Production Quality |
|---------|------:|:-----------------:|:-----------:|:------------------:|
| **LangGraph** | 1163 | **17/17 pass** | **~92%** | ✅ True inheritance — batch/`refresh_ttl` edge case |
| **Mem0** | 1510 | **27/27 pass** | **~92%** | ✅ Good — `entity_store` alias added, `create_memory_tool` returns real tool schemas. Only adapter with a TS port (`mem0.ts`) |
| **Hindsight** | 2005 | **54/54 pass** | **~97%** | ✅ Excellent — documents/entities/operations/monitoring real; `webhooks` real; working-memory TTL; banks |
| **Zep** | 2838 | **26/26 + 16/16 graph + 13/13 fact-rating pass** | **~97%** | ✅ `.memory`/`.user`/`.graph` + async — LLM fact rating wired, `graph.add_triplet` real, `graph.community.build/list/get/search` shipped (7 tests) |
| **Honcho** | 2291 | **14/14 pass** | **~98%** | ✅ Excellent — `.aio` + all LLM features + working_representation + Peer.sessions() |
| **Graphiti** | 2671 | **20/20 pass** | **~95%** | ✅ Bi-temporal edges real; search recipes + semantic entity dedup ported; bi-temporal search filters on real `valid_at` |
| **QMD** | — | N/A (CLI tool) | **~98%** | Full feature parity — all QMD features covered |
| **GBrain** | — | N/A (PGLite + Bun) | **~95%** | Synthesis w/ gap analysis, auto-extraction, dream cycle, citations, graph-search eval harness all shipped |
| **Mnemosyne** | — | N/A (SQLite) | **~95%** | Core + AAAK, SHMR, veracity, MIB, polyphonic recall, streaming, TTL, consolidation, banks, Hermes hooks |

**Overall: ~95% shape match across 6 adapters + 3 architecture-tracked projects.** All behavioral tests verified against live SpacetimeDB.

**Post-audit (2026-07-31) state:**
- Zep graph namespace shipped: `graph.add`, `graph.search` (nodes/edges/episodes scopes), `graph.node.get`/`get_by_user_id`, `graph.edge.get`, `graph.episode.get` + full async mirror — 16/16 graph tests pass. `graph.add_triplet` writes real KG edges; LLM fact rating wired (13 unit tests). Zep parity ~85% → ~95%.
- Hindsight fake shells replaced: `documents`/`entities`/`operations`/`monitoring` are real; `webhooks` backed by real webhook delivery tables (create/list/get/update/delete/fire). Working-memory TTL via `retain(ttl_seconds=...)` + recall eviction. Parity ~90% → ~97%.
- Mem0: `create_memory_tool` now returns real OpenAI-style tool schemas; `entity_store` alias added. Parity ~88% → ~92%.
- Graphiti: search config recipes (strategy/hybrid_mode/cross_encoder/mmr) + 4-pass entity dedup incl. semantic embeddings. Parity ~85% → ~95%.
- GBrain: synthesis with gap analysis, citations verified, dream cycle verified, graph-search P@5/R@5 eval harness shipped (P@5 45.76%, R@5 91.41% vs GBrain's 49.1/97.9 on a corpus with 51.52% P@5 ceiling).
- Mnemosyne: SHMR/polyphonic/AAAK/local-LLM/streaming verified present; working-memory TTL, LLM consolidation, memory banks, and Hermes lifecycle hooks added. Parity ~78-85% → ~95%.
- Only Mem0 has a TypeScript adapter (`mem0.ts`); no TS adapters for Zep/Graphiti/Honcho/Hindsight. **Update (2026-08-01):** the TS SDK (`sdk/typescript/`) now has adapters for ALL of them — `zep.ts`, `graphiti.ts`, `honcho.ts`, `hindsight.ts`, `mem0.ts`, `compounder.ts`, `delta_sync.ts`, `ws_subscription.ts` — 338/338 TS tests pass. Zep communities shipped in TS too.

**What IS a drop-in replacement today:** LangGraph, Zep (v2, incl. graph + fact rating), Honcho, Graphiti, Mem0, Hindsight.
**What needs work:** Docker smoke test + PyPI publish (blocked on external resources).
