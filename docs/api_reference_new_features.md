# API Reference — New Features

## Graph Community Detection

Module: `spacetime_memory.community_detection`

| Function | Description |
|----------|-------------|
| `detect_communities(client, workspace_id, ...)` | Louvain-like modularity-optimizing community detection on knowledge graphs |
| `summarize_communities(client, workspace_id, communities, llm_client=None)` | Generate LLM narrative summaries for detected communities |
| `persist_communities(client, workspace_id, communities)` | Store communities back to STDB (kg_community + assignments) |

**Parameters (detect_communities):**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_iterations` | int | 50 | Max Louvain refinement passes |
| `resolution` | float | 1.0 | Modularity resolution (>1.0 = more/smaller communities) |
| `min_community_size` | int | 2 | Merge communities smaller than this |

## Agent Self-Editing

Module: `spacetime_memory.self_editing`

| Function | Description |
|----------|-------------|
| `merge_similar_memories(client, workspace_id, threshold=0.7, ...)` | Merge similar memories using heuristic or LLM similarity |
| `detect_contradictions(client, workspace_id, ...)` | Find semantic contradictions among memories |
| `rewrite_memory(client, workspace_id, memory_id, new_content, ...)` | Rewrite a memory with LLM merge or heuristic dedup |
| `resolve_entities(client, workspace_id, ...)` | Merge duplicate KG entities with edge migration |

All functions support `dry_run=True` for preview without mutation, and `llm_func` vs. heuristic modes.

## Auto-Summarization Pipeline

Module: `spacetime_memory.auto_summarization`

| Function | Description |
|----------|-------------|
| `summarize_memories(memories, llm_func=None)` | Abstractive batch summarization (LLM or extractive fallback) |
| `extractive_compress(text, max_sentences=5)` | Heuristic sentence extraction (keyword/position/entity scoring) |
| `tier_summarize(memories, tier, llm_func=None)` | Tier-aware: L0=detailed, L1=balanced, L2=compressed |
| `check_trigger_summarization(client, workspace_id, threshold=50)` | Check if enough new memories for summarization |
| `store_summary(client, workspace_id, summary_text, ...)` | Persist summary as a note with metadata |
| `batch_summarize_and_store(client, workspace_id, ...)` | End-to-end: trigger → fetch → summarize → store |

## Memory Hierarchy

Module: `spacetime_memory.memory_hierarchy`

| Function | Description |
|----------|-------------|
| `track_access(client, workspace_id, memory_id)` | Record memory access for promotion analysis |
| `compute_lifecycle(client, workspace_id, memory_id)` | Compute lifecycle metrics (age, recency, frequency) |
| `promote_memory(client, workspace_id, memory_id, target_tier)` | Promote/demote a single memory between L0/L1/L2 |
| `auto_promote(client, workspace_id, ...)` | Scan and auto-promote eligible memories |
| `evict_from_working(client, workspace_id, max_l0_size=50)` | Evict idle/low-importance L0 memories to L1 |
| `tier_aware_search(client, workspace_id, query, tier, ...)` | Search with tier filtering |
| `run_memory_lifecycle(client, workspace_id, ...)` | Run full lifecycle: promote + evict in one call |

## Entity Store (Mem0 parity)

Module: `spacetime_memory.entity_store`

| Function | Description |
|----------|-------------|
| `extract_entities(text, llm_func=None)` | Extract named entities from text (regex or LLM) |
| `store_entities(client, workspace_id, entities, ...)` | Store entities as KG nodes with dedup |
| `search_entities(client, workspace_id, query, type=None)` | Client-side entity search by label/summary |
| `get_entity_graph(client, workspace_id, entity_id)` | Get entity's sub-graph (edges + neighbors) |

Or use the class-based API:

```python
from spacetime_memory.entity_store import EntityStore

store = EntityStore(client, workspace_id, llm_func=my_llm)
store.extract_and_store("Some text with entities...")
results = store.search("Python")
```

## Zep Adapter — add_triplet with Rating

```python
# Sync
zep_client.graph.add_triplet("Python", "influenced_by", "JavaScript", rating=0.85)

# Async
await async_zep_client.graph.add_triplet("Python", "influenced_by", "JavaScript", rating=0.85)
```

The `rating` parameter (0.0-1.0) is stored as the edge's `weight` in the KG, representing confidence/importance of the fact.
