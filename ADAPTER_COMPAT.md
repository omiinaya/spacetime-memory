# Adapter Compatibility

Each adapter aims to be a **drop-in replacement** for the upstream library's public API.
This document tracks which methods are supported, which are mapped to SpacetimeDB
equivalents, and which are explicitly not supported.

## Key

| Icon | Meaning |
|------|---------|
| ✅ | Directly implemented |
| 🔄 | Mapped (different backend, same result shape) |
| ⚠️ | Partial (works for common inputs, edge cases may differ) |
| ❌ | Not supported |

---

## Mem0

Reference: [github.com/mem0ai/mem0](https://github.com/mem0ai/mem0) — `Memory` class.

Adapter: `spacetime_memory.sdks.mem0.Memory` (604 lines, 16 public methods)

| Method | Status | Notes |
|--------|--------|-------|
| `__init__(config, token_refresh_callback)` | ✅ | Accepts standard Mem0 config dict |
| `add(data, user_id, agent_id, run_id, metadata)` | ✅ | `data` → `store_memory`, maps `user_id` → workspace |
| `get(memory_id)` | ✅ | SQL lookup by ID |
| `search(query, user_id, agent_id, limit, ...)` | ✅ | → `hybrid_search`, supports Mem0 filter shape + v2 `filters` dict |
| `get_all(user_id, agent_id, limit)` | ✅ | SQL query with workspace filter, supports v2 `filters` + `top_k` |
| `update(memory_id, data)` | ✅ | → `update_memory`, accepts `metadata` param |
| `delete(memory_id)` | ✅ | → `deactivate_memory` |
| `delete_all(user_id, agent_id)` | ✅ | Workspace-scoped deletion, supports v2 `filters` dict |
| `history(memory_id)` | ✅ | Returns memory version history |
| `reset()` | ✅ | Clear all cached workspace mappings |
| `from_config(config_dict)` | ✅ | Classmethod (Mem0 v2+ compat) |
| `close()` | ✅ | No-op (HTTP client is long-lived) |
| `batch_update(memories)` | ❌ | Removed from Mem0 v2 API; not applicable |
| `create_memory_tool()` | ❌ | Removed from Mem0 v2 API; not applicable |
| Memory merging (v1.1+) | ✅ | `infer=True` uses LLM for fact extraction (via `LLMClient`) + basic merge fallback |
| Graph memory | ✅ | Entity persistence via `kg_node` table. Access via `m.graph.add/search/get_all/delete`. `add()` with `infer=True` creates KG nodes from LLM-extracted facts |
| Custom LLM per user | ✅ | `m.set_llm_config(user_id, {"model": ..., "api_key": ...})` — per-user model overrides |
| `chat()` | ✅ | RAG + LLM response pipeline. Stores queries, searches memories, generates via LLMClient. Gracefully degrades without OPENAI_API_KEY |

**Coverage: ~95%.** Graph memory, custom LLM per user, and chat now implemented. Remaining gap: `create_memory_tool()` (removed from Mem0 v2 API).

---

## Zep

Reference: [github.com/getzep/zep-python](https://github.com/getzep/zep-python) — `ZepClient`.

Adapter: `spacetime_memory.sdks.zep.ZepClient` (500 lines, 10 public methods)

| Method | Status | Notes |
|--------|--------|-------|
| `__init__(host, port, ...)` | ✅ | Standard Zep-compatible init |
| `add_memory(session_id, messages)` | ✅ | → `store_memory` for each message |
| `get_memory(session_id, lastn, ...)` | ✅ | Now includes `facts` + `relevant_facts` in response |
| `delete_memory(session_id)` | ✅ | → `deactivate_memory` by session |
| `search_memory(session_id, query, limit, metadata)` | ✅ | → `hybrid_search` scoped to session |
| `list_sessions()` | ✅ | SQL query listing all workspaces |
| `get_session(session_id)` | ✅ | Returns workspace metadata |
| `close()` | ✅ | No-op (HTTP client is long-lived) |
| `add_fact(session_id, fact)` | ✅ | → `store_memory` with `memory_type="fact"` |
| `list_facts(session_id)` | ✅ | → `list_memories` filtered to `memory_type="fact"` |
| `delete_fact(session_id, fact_id)` | ✅ | → `deactivate_memory` by fact ID |
| `update_memory(session_id, memory_id, ...)` | ✅ | → `update_memory` reducer |
| `search_memory` with `min_score` | ✅ | Accepted as alias for `score_threshold` |
| `summarize_memory(session_id)` | ✅ | LLM-powered via `LLMClient` (requires OPENAI_API_KEY) |
| `search_memory` with `search_scope` | ❌ | Zep Cloud feature |

**Coverage: ~93%.** Facts API + LLM summarization implemented. Remaining gap is Cloud-only.

---

## Graphiti

Reference: [github.com/getzep/graphiti](https://github.com/getzep/graphiti) — `Graphiti` class.

Adapter: `spacetime_memory.sdks.graphiti.Graphiti` (915 lines, 15 public methods)

| Method | Status | Notes |
|--------|--------|-------|
| `__init__(...)` | ✅ | Standard init |
| `close()` | ✅ | No-op |
| `add_triplet(group_id, triplet, ...)` | ✅ | → KG node/edge creation |
| `add_episode(group_id, episode_body, ...)` | ✅ | → memory + KG with time context |
| `search(group_id, query, limit, ...)` | ✅ | → `hybrid_search` |
| `search_(group_id, query, ...)` | ✅ | Alternative search interface |
| `get_entity_edge_summary(group_id, entity_name)` | ✅ | Returns edge summary for entity |
| `build_communities(group_id)` | ✅ | → `detect_communities` |
| `remove_episode(episode_uuid)` | ✅ | → memory deactivation |
| `build_indices_and_constraints(...)` | ✅ | Ensures DB state |
| `get_nodes_and_edges_by_episode(uuid)` | ✅ | Returns KG subgraph for episode |
| `update_edge(edge_id, relation, ...)` | ✅ | → `update_edge` reducer (temporal versioning) |
| `get_edge_history(edge_id)` | ✅ | Returns all temporal versions of an edge |
| Temporal edge diff tracking | ✅ | Edge versions linked by `edge_group_id` with `valid_at`/`invalid_at` |
| Entity dedup during `add_triplet` | ⚠️ | Fuzzy name matching (case-insensitive + difflib >0.85) without LLM |
| Community summary text | ✅ | LLM-generated via `LLMClient` when OPENAI_API_KEY set |
| Time-range-filtered search | ✅ | `valid_at_after`/`valid_at_before` kwargs in search()/search_() |

**Coverage: ~90%.** Temporal edge tracking + time-range filters + fuzzy entity dedup + LLM community summaries.

---

## Hindsight

Reference: [github.com/vectorize-io/hindsight](https://github.com/vectorize-io/hindsight) — `Hindsight` class.

Adapter: `spacetime_memory.sdks.hindsight.Hindsight` (415 lines, 11 public methods)

| Method | Status | Notes |
|--------|--------|-------|
| `__init__(config, ...)` | ✅ | Standard init |
| `retain(content, source, metadata, ...)` | ✅ | → `store_memory` |
| `recall(query, limit, ...)` | ✅ | → `hybrid_search` |
| `reflect(prompt)` | ✅ | → `create_insight`, LLM-powered |
| `forget(memory_id)` | ✅ | → `deactivate_memory` |
| `batch_retain(items)` | ✅ | Batch memory storage |
| `list_all(limit)` | ✅ | Lists all memories |
| `stats()` | ✅ | Returns aggregate stats |
| `reset()` | ✅ | Clears cached state |
| Custom prompt templates for `reflect` | ✅ | Template-based with `reflect_mission` config + `export_template()`/`import_template()` |
| `reflect()` with `context` param | ✅ | Extra context alongside the prompt |
| `reflect()` with `tags` param | ✅ | Client-side memory filter |
| `reflect()` with `max_tokens` param | ✅ | Overrides default LLM token limit |
| `reflect()` with `response_schema` param | ✅ | Structured JSON output |
| `export_template(workspace_id)` | ✅ | Serializes reflect config |
| `import_template(data)` | ✅ | Loads reflect config from dict |
|| `batch_retain` dedup | ✅ | Content-hash dedup within batch |

**Coverage: ~90%.** Template-based reflect + batch dedup fully implemented.

---

## Honcho

Reference: [github.com/plastic-labs/honcho](https://github.com/plastic-labs/honcho) — `Honcho` class.

Adapter: `spacetime_memory.sdks.honcho.Honcho` (579 lines, 21 public methods)

| Method | Status | Notes |
|--------|--------|-------|
| `create_user(name, metadata)` | ✅ | → `create_peer` |
| `get_user(name)` | ✅ | Peer lookup |
| `get_or_create_user(name)` | ✅ | Compound operation |
| `create_session(user, location, ...)` | ✅ | → `create_session` |
| `get_session(session_id)` | ✅ | Session lookup |
| `get_or_create_session(user, session_id, ...)` | ✅ | Compound operation |
| `add(user, content, session_id, ...)` | ✅ | → `store_memory` |
| `search(user, query, limit, ...)` | ✅ | → `hybrid_search` |
| `get_user_memories(user, limit)` | ✅ | → memory list by user |
| `User.set_metadata(metadata)` | ✅ | → `update_workspace` (stored as description) |
| `User.get_metadata()` | ✅ | Returns metadata from workspace description |
| `Session.create_memory(...)` | ✅ | Session-scoped memory creation |
| `Session.search(...)` | ✅ | Session-scoped search |
| `Session.get_memories(limit)` | ✅ | Session memory list |
| Session-level memory visibility | ✅ | Memory store/search/list scoped by `source_session_id` |
| `Session.get_metadata()` | ✅ | Returns locally-cached session metadata |
| `Session.set_metadata(metadata)` | ✅ | Persists session metadata via memory record |
| `Session.refresh()` | ✅ | Re-fetches session metadata from backend |
| `metadata` param in `create_session` | ✅ | Now actually forwarded to Session constructor |

**Coverage: ~88%.** Session metadata API fully implemented.

---

## LangChain

Reference: [python.langchain.com](https://python.langchain.com/) — `BaseStore`, `BaseVectorStore`.

Adapter: `spacetime_memory.sdks.langchain` (778 lines, 16 public methods)

| Method | Status | Notes |
|--------|--------|-------|
| **StmemStore (BaseStore)** | | |
| `mget(keys)` | ✅ | Multi-get by key |
| `mset(key_value_pairs)` | ✅ | Multi-set |
| `mdelete(keys)` | ✅ | Multi-delete |
| `yield_keys(prefix)` | ✅ | Key iteration |
| **StmemMemoryStore (BaseMemoryStore)** | | |
| `get(namespace, key)` | ✅ | Get by namespace + key |
| `put(namespace, key_value_pairs)` | ✅ | Put by namespace |
| `delete(namespace, key)` | ✅ | Delete by namespace + key |
| `search(namespace, query, limit, ...)` | ✅ | → `hybrid_search` with embedding |
| `list_namespaces()` | ✅ | Namespace listing |
| `batch(ops)` | ✅ | Batch operations |
| **Additional** | | |
| `StmemChatMessageHistory` | ✅ | `BaseChatMessageHistory` implementation — stores messages as memory records |
| `AIMessage` content dedup | ✅ | Dedup by type + content in `add_messages` |

**Coverage: ~88%.** Core stores fully implemented. Chat message history with dedup.

---

## Summary

| Adapter | Lines | Methods | Coverage |
|---------|-------|---------|----------|
| Mem0 | ~700 | 17 | ~95% |
| Zep | 647 | 15 | ~93% |
| Graphiti | ~960 | 17 | ~90% |
| Hindsight | 415 | 11 | ~90% |
| Honcho | 637 | 23 | ~90% |
| LangChain | 778 | 16 | ~88% |

**Overall: ~91% coverage across all adapters.**

Core CRUD operations are fully supported for all adapters. The remaining gaps
are generally advanced capabilities of the upstream projects.
