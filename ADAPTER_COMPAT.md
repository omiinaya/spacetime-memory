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

Adapter: `spacetime_memory.sdks.mem0.Memory` (469 lines, 12 public methods)

| Method | Status | Notes |
|--------|--------|-------|
| `__init__(config, token_refresh_callback)` | ✅ | Accepts standard Mem0 config dict |
| `add(data, user_id, agent_id, run_id, metadata)` | ✅ | `data` → `store_memory`, maps `user_id` → workspace |
| `get(memory_id)` | ✅ | SQL lookup by ID |
| `search(query, user_id, agent_id, limit, ...)` | ✅ | → `hybrid_search`, supports Mem0 filter shape |
| `get_all(user_id, agent_id, limit)` | ✅ | SQL query with workspace filter |
| `update(memory_id, data)` | ✅ | → `update_memory` |
| `delete(memory_id)` | ✅ | → `deactivate_memory` |
| `delete_all(user_id, agent_id)` | ✅ | Workspace-scoped deletion |
| `history(memory_id)` | ✅ | Returns memory version history |
| `reset()` | ✅ | Clear all cached workspace mappings |
| `batch_update(memories)` | ❌ | Not implemented |
| `create_memory_tool()` | ❌ | LangChain tool integration |
| Memory merging (v1.1+) | ❌ | Mem0 merges similar memories |
| Graph memory | ❌ | Mem0's knowledge graph integration |
| Custom LLM per user | ❌ | Mem0 allows per-user model config |
| Memory recommendation | ❌ | `recommend()` method |

**Coverage: ~65%.** Covers core CRUD. Missing advanced Mem0 features (merging, graph memory, custom LLM configs).

---

## Zep

Reference: [github.com/getzep/zep-python](https://github.com/getzep/zep-python) — `ZepClient`.

Adapter: `spacetime_memory.sdks.zep.ZepClient` (500 lines, 10 public methods)

| Method | Status | Notes |
|--------|--------|-------|
| `__init__(host, port, ...)` | ✅ | Standard Zep-compatible init |
| `add_memory(session_id, messages)` | ✅ | → `store_memory` for each message |
| `get_memory(session_id, lastn, ...)` | ✅ | Returns recent messages for session |
| `delete_memory(session_id)` | ✅ | → `deactivate_memory` by session |
| `search_memory(session_id, query, limit, metadata)` | ✅ | → `hybrid_search` scoped to session |
| `list_sessions()` | ✅ | SQL query listing all workspaces |
| `get_session(session_id)` | ✅ | Returns workspace metadata |
| `close()` | ✅ | No-op (HTTP client is long-lived) |
| `add_fact(session_id, fact)` | ❌ | Zep Facts API not implemented |
| `list_facts(session_id)` | ❌ | Facts listing not implemented |
| `update_memory(session_id, memory_id, ...)` | ❌ | Zep memory update not implemented |
| `summarize_memory(session_id)` | ❌ | Zep Cloud feature |
| `search_memory` with `min_score`, `search_scope` | ⚠️ | Filter params partially supported |

**Coverage: ~50%.** Missing facts API which is one of Zep's core features.

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
| Temporal edge diff tracking | ❌ | Graphiti tracks edge evolution over time |
| `node_expansion()` | ❌ | Returns expanded node context |
| Entity dedup during `add_triplet` | ❌ | Graphiti deduplicates entities |
| Community summary text | ❌ | LLM-generated summary per community |
| Time-range-filtered search | ⚠️ | Basic temporal support |

**Coverage: ~75%.** Best adapter. Maps well to SpacetimeDB's KG module.

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
| Custom prompt templates for `reflect` | ⚠️ | Basic support, not full template system |
| `batch_retain` dedup | ❌ | No automatic dedup within batch |

**Coverage: ~85%.** Hindsight's simpler API means better coverage.

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
| `Session.create_memory(...)` | ✅ | Session-scoped memory creation |
| `Session.search(...)` | ✅ | Session-scoped search |
| `Session.get_memories(limit)` | ✅ | Session memory list |
| User metadata update | ❌ | Honcho stores user metadata |
| Session-level memory visibility | ⚠️ | Basic support |

**Coverage: ~80%.** Honcho's workspace model maps naturally to SpacetimeDB workspaces.

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
| `BaseChatMemory` wrapper | ❌ | Chat history helper not implemented |
| `AIMessage` content dedup | ❌ | Edge case, not critical |

**Coverage: ~85%.** Solid for both BaseStore and BaseVectorStore interfaces.

---

## Summary

| Adapter | Lines | Methods | Coverage |
|---------|-------|---------|----------|
| Mem0 | 469 | 12 | ~65% |
| Zep | 500 | 10 | ~50% |
| Graphiti | 915 | 15 | ~75% |
| Hindsight | 415 | 11 | ~85% |
| Honcho | 579 | 21 | ~80% |
| LangChain | 778 | 16 | ~85% |

**Overall: ~73% coverage across all adapters.**

Core CRUD operations are fully supported for all adapters. Missing features are
generally advanced capabilities of the upstream projects — graph memory,
custom LLM configs, temporal edge tracking, facts APIs.

**Priority for improvement:**
1. Zep facts API (largest gap)
2. Mem0 memory merging + batch_update (second largest)
3. Graphiti temporal edge tracking
