# Adapter Compatibility

Each adapter aims to be a **drop-in replacement** for the upstream library's public API.
This document tracks which methods are supported, which are mapped to SpacetimeDB
equivalents, and which are explicitly not supported.

**WARNING:** These adapters share a single SpacetimeDB backend. Shape parity is high
but runtime quality varies — see the "Runtime Notes" section for each adapter.

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

Adapter: `spacetime_memory.sdks.langchain.StmemStore` / `StmemMemoryStore`

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
| `batch(ops)` | ✅ | Batch operations |
| `abatch(ops)` | ✅ | Async batch |
| `aput` / `aget` / `adelete` / `asearch` | ✅ | All async variants |
| `GetOp` / `PutOp` / `SearchOp` / `ListNamespacesOp` | ✅ | Op type parity |
| `supports_ttl` | ✅ |  |

**Runtime quality:** ✅ True drop-in. Inherits `BaseStore` from upstream.
**Coverage: 100%**

---

## Mem0

Reference: [mem0ai/mem0](https://github.com/mem0ai/mem0) — `Memory` class.

Adapter: `spacetime_memory.sdks.mem0.Memory` (1119 lines, 16 public methods)

| Method | Status | Notes |
|--------|--------|-------|
| `__init__(config, ...)` | ✅ | Accepts dict or `MemoryConfig` |
| `add(data, user_id, agent_id, ...)` | ✅ | → `store_memory`, accepts all shared keyword params (`infer`, `memory_type`, `run_id`, `metadata`, `prompt`) |
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
| `chat()` | ✅ | RAG + LLM pipeline |
| `create_memory_tool()` | ❌ | Removed from Mem0 v2 API |

**Runtime notes:**
- Constructor accepts both `dict` and `MemoryConfig` Pydantic model
- Error swallowing was fixed in v1.14.0 (3 sites now log warnings instead of `pass`)
- LLM extraction gracefully degrades without `OPENAI_API_KEY`
- Graph API search returns empty list on failure (logged)
- `ValueError` used for validation (9 sites), `RuntimeError` for backend errors (17 sites)

**Coverage: ~98%**

---

## Zep

Reference: [getzep/zep-python](https://github.com/getzep/zep-python) — `ZepClient`.

Adapter: `spacetime_memory.sdks.zep.ZepClient` (892 lines, 15 public methods)

| Method | Status | Notes |
|--------|--------|-------|
| `__init__(host, port, ...)` | ✅ | Standard Zep-compatible init |
| `add_memory(session_id, messages)` | ✅ | → `store_memory` per message |
| `get_memory(session_id, ...)` | ✅ | Returns messages + facts + relevant_facts |
| `delete_memory(session_id)` | ✅ | → `deactivate_memory` by session |
| `search_memory(session_id, query, ...)` | ✅ | → `hybrid_search` with `min_score` alias |
| `list_sessions()` | ✅ | Workspace listing |
| `get_session(session_id)` | ✅ | Returns workspace metadata |
| `add_session(session_id, ...)` | ✅ | Creates workspace |
| `update_session(session_id, ...)` | ✅ | Updates workspace metadata |
| `search_sessions(query, ...)` | ✅ | Search across sessions |
| `add_fact(session_id, fact)` | ✅ | → `store_memory` with `memory_type="fact"` |
| `list_facts(session_id)` | ✅ | → `list_memories` filtered to facts |
| `delete_fact(session_id, fact_id)` | ✅ | → `deactivate_memory` |
| `update_memory(session_id, ...)` | ✅ | → `update_memory` reducer |
| `summarize_memory(session_id)` | ✅ | LLM-powered via `LLMClient` |
| `close()` | ✅ | No-op |

**Runtime notes:**
- Typed exceptions: `NotFoundError`, `BadRequestError`, `ApiError` (from imported `zep_python` or local fallback)
- Missing: async support (upstream Zep has async endpoints)
- `search_sessions()` results are limited — SpacetimeDB doesn't have a cross-workspace search index
- Error paths: `NotFoundError` raised for missing sessions, `RuntimeError` for DB failures

**Coverage: ~90%**

---

## Graphiti

Reference: [getzep/graphiti](https://github.com/getzep/graphiti) — `Graphiti` class.

Adapter: `spacetime_memory.sdks.graphiti.Graphiti` (1190 lines, 17 public methods)

| Method | Status | Notes |
|--------|--------|-------|
| `__init__(...)` | ✅ | Standard init |
| `close()` | ✅ | No-op |
| `add_triplet(source_node, edge, target_node, *, group_id)` | ✅ | → KG node/edge creation |
| `add_episode(episode_body, ...)` | ✅ | → memory + KG with time context |
| `search(query, center_node_uuid, ...)` | ✅ | → `hybrid_search` with `search_filter`/`driver` params |
| `search_(...)` | ✅ | → `SearchResults` with nodes + edges |
| `get_entity_edge_summary(entity_uuid)` | ✅ | Returns edge summary |
| `build_communities(group_id)` | ✅ | → `detect_communities` |
| `remove_episode(episode_uuid)` | ✅ | → memory deactivation |
| `build_indices_and_constraints(...)` | ✅ | Ensures DB state |
| `get_nodes_and_edges_by_episode(uuid)` | ✅ | KG subgraph for episode |
| `update_edge(edge_id, relation, ...)` | ✅ | Temporal versioning |
| `get_edge_history(edge_id)` | ✅ | All temporal versions |
| Temporal edge diff tracking | ✅ | Edge versions linked by `edge_group_id` |
| Entity dedup | ⚠️ | Fuzzy name matching (case-insensitive + difflib >0.85) without LLM |
| Community summary text | ✅ | LLM-generated when `OPENAI_API_KEY` set |
| Time-range-filtered search | ✅ | `valid_at_after`/`valid_at_before` kwargs |

**Runtime notes:**
- `EntityNode` and `EntityEdge` are dataclasses, not Pydantic models (upstream uses Pydantic)
- All upstream fields present: `EntityNode` 8/8, `EntityEdge` 14/14 (plus extras: `version`, `edge_group_id`)
- Constructor params differ upstream (`uri`, `password`, `graph_driver` → Neo4j) vs ours (`host`, `port`, `database` → SpacetimeDB) — unavoidable
- `group_id` is keyword-only in `add_triplet` (extra vs upstream)
- `search()` accepts `**kwargs` for forward compat
- Error paths: warnings logged, empty results on failure

**Coverage: ~85%** (shape match). Runtime quality: best of the rewritten adapters.

---

## Hindsight

Reference: [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight) — `Hindsight` class (v0.8.1).

Adapter: `spacetime_memory.sdks.hindsight.Hindsight` (670 lines, 13 public methods)

| Method | Status | Notes |
|--------|--------|-------|
| `__init__(base_url, api_key, timeout, user_agent, *stdb_*)` | ✅ | Accepts Hindsight-standard args + SpacetimeDB extras |
| `retain(bank_id, content, *, timestamp, context, ...)` | ✅ | Full param set including `entities`, `tags`, `update_mode`, `retain_async` |
| `retain_batch(bank_id, items, ...)` | ✅ | Batch store |
| `retain_files(bank_id, files, ...)` | ✅ | File content ingest |
| `recall(bank_id, query, *, types, max_tokens, budget, ...)` | ✅ | Full param set |
| `reflect(bank_id, query, *, budget, context, max_tokens, ...)` | ✅ | Full param set (`response_schema`, `include_facts`, `include_tool_calls`, etc.) |
| `aretain()` / `arecall()` / `areflect()` / `aretain_batch()` | ✅ | All async variants |
| `close()` / `aclose()` | ✅ | |
| Context manager (`__enter__` / `__exit__`) | ✅ | |

**Runtime notes:**
- **All response types are Pydantic models** matching upstream (`RetainResponse`, `RecallResponse`, `ReflectResponse`, `FileRetainResponse`, etc.)
- **No stale methods:** no `forget()`, `export_template()`, `import_template()`, `list_all()`, `stats()`, `reset()`
- Sync wrappers (`retain`, `recall`, `reflect`) use `_run_async()` which raises `RuntimeError` in running event loops — use the async variants directly in async contexts
- Error swallowing was fixed in v1.14.0 (5 sites now log warnings)
- The real `hindsight_client` is not on PyPI — this adapter is the only Python SDK for Hindsight

**Coverage: ~95%**

---

## Honcho

Reference: [plastic-labs/honcho](https://github.com/plastic-labs/honcho) — `Honcho` class.

Adapter: `spacetime_memory.sdks.honcho.Honcho` (833 lines, 21 public methods)

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
| `Peer.sessions(...)` | ✅ | `SyncPage[SessionResponse, Session]` |
| `Session.add_peers(peers)` | ✅ | |
| `Session.add_messages(messages)` | ✅ | Bulk store |
| `Session.messages(filters, ...)` | ✅ | `SyncPage[MessageResponse, Message]` |
| `Session.search(query, ...)` | ✅ | Session-scoped search |
| `Session.context(*, summary, tokens)` | ✅ | Returns `SessionContext` |
| `Session.summaries()` | ✅ | Returns `SessionSummaries` |
| `Session.delete()` | ✅ | |
| `Peer.sessions()` | ⚠️ | Returns empty page — no peer→session mapping in SpacetimeDB |

**Runtime notes:**
- 30+ Pydantic models matching upstream (`WorkspaceResponse`, `PeerResponse`, `SessionResponse`, `MessageResponse`, `SyncPage`, etc.)
- `Peer.sessions()` returns empty — SpacetimeDB has no direct peer→session index
- Error swallowing was fixed in v1.14.0 (prev: 5 sites returned `None`/`[]` silently, now logged)
- `Session.add_messages()` skips items that fail to store (logged), continues with rest
- No `.aio` async accessor (upstream has this — planned)
- The real `honcho` is not on PyPI (the PyPI `honcho` is a Procfile manager)

**Coverage: ~85%** (shape match). Runtime: improved in v1.14.0.

---

## Summary

| Adapter | Lines | Methods | Shape Match | Runtime Quality | Prod Ready? |
|---------|------:|--------:|:-----------:|:---------------:|:-----------:|
| **LangGraph** | 778 | 16 | **100%** | ✅ True inheritance | **Yes** |
| **Mem0** | 1119 | 17 | **98%** | ⚠️ Good — warnings on errors | **No** |
| **Hindsight** | 670 | 13 | **95%** | ⚠️ Good — `_run_async()` requires care in async ctx | **No** |
| **Zep** | 892 | 15 | **90%** | ⚠️ OK — missing async support | **No** |
| **Graphiti** | 1190 | 17 | **85%** | ⚠️ Best of rewritten — dataclass vs Pydantic, extra `group_id` | **No** |
| **Honcho** | 833 | 21 | **85%** | ⚠️ Improved — `Peer.sessions()` empty, no `.aio` | **No** |

**Overall shape match: ~92%.** Runtime quality: improving but not production-ready for 5/6 adapters.

LangGraph is the only one you should consider production today. The rest need Phase II (behavioral tests) and Phase III (reliability infrastructure) from ROADMAP.md before they're safe to use in production.
