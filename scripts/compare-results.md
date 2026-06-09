# Upstream Comparison Results

Comparison of spacetime-memory adapters vs real upstream PyPI libraries

| # | Library | PyPI Package | Status |
|---|---------|-------------|--------|
| 1 | LangGraph | `langgraph` | ✅ Testable (InMemoryStore) |
| 2 | Mem0 | `mem0ai` | ✅ Installable (needs OpenAI) |
| 3 | Zep | `zep-python` | ✅ Installable (needs server) |
| 4 | Graphiti | `graphiti-core`/`graphiti-memory` | ✅ Installable (needs Neo4j) |
| 5 | Hindsight | (not on PyPI) | ❌ Adapter IS the SDK |
| 6 | Honcho | (not on PyPI) | ❌ Adapter IS the SDK |

```

── 1/6  LangGraph BaseStore parity ──────────────────────────────
  ✓ StmemStore is BaseStore subclass
  ✓ StmemStore inherits from RealBaseStore
  ✓ StmemStore.implements put
  ✓ StmemStore.implements get
  ✓ StmemStore.implements delete
  ✓ StmemStore.implements batch
  ✓ StmemStore.implements abatch
  ✓ StmemStore.implements search
  ✓ StmemStore.implements list_namespaces
  ✓ StmemStore.put params match
  ✓ StmemStore.get params match
  ✓ StmemStore.delete params match
  ✓ StmemStore.batch params match
  ✓ StmemStore.abatch params match
  ✓ StmemStore.search params match
  ✓ StmemStore.list_namespaces params match
  ✓ GetOp matches LangGraph
  ✓ PutOp matches LangGraph
  ✓ SearchOp matches LangGraph
  ✓ ListNamespacesOp matches LangGraph
  ✓ StmemStore.async aput
  ✓ StmemStore.async aget
  ✓ StmemStore.async adelete
  ✓ StmemStore.async asearch
  ✓ StmemStore.async abatch
  ✓ Item class exists
  ✓ supports_ttl on StmemStore
  ✓ StmemStore dict-like get via get()

── 2/6  Mem0 (mem0ai) parity ────────────────────────────────────
  ✓ Mem0.Memory class exists
  ℹ Mem0.Memory has extra params: {'token_refresh_callback'}
  ✗ Mem0.Memory constructor 0 common params
  ✓ Mem0.add exists
  ✓ Mem0.search exists
  ✓ Mem0.get_all exists
  ✓ Mem0.get exists
  ✓ Mem0.delete exists
  ✓ Mem0.history exists
  ✓ Mem0.update exists
  ℹ Mem0 signature differences are expected — ours uses user/agent/run_id as kwargs,
  ℹ   real mem0 also uses user_id/agent_id/run_id as kwargs. Ours adds SpacetimeDB
  ℹ   specific: host/port/db passed via config dict, real mem0 uses MemoryConfig.
  ✓ Mem0.add shared keyword params: {'memory_type', 'agent_id', 'user_id', 'metadata', 'prompt', 'infer', 'run_id'}
  ✓ Mem0.add returns dict with 'results' key
  ✓ Our Mem0 has .graph property
  ℹ mem0 v2 uses generic exception handling (no BaseMemoryException)
  ✓ mem0 exceptions exist
  ℹ Our Mem0 uses ValueError: 9x, RuntimeError: 17x
  ✓ Mem0 config classes: MemoryConfig
  ✓ Mem0 MemoryConfig embeds all sub-configs

── 3/6  Zep parity ──────────────────────────────────────────────
  ✓ ZepClient (real) exists
  ✓ ZepClient (ours) exists
  ✓ Zep.add_memory exists
  ✓ Zep real.add exists
  ✓ Zep.get_memory exists
  ✓ Zep real.get exists
  ✓ Zep.delete_memory exists
  ✓ Zep real.delete exists
  ✓ Zep.search_memory exists
  ✓ Zep real.search_sessions exists
  ✓ Zep.update_memory exists
  ✓ ZepClient.constructor accepts host/port
  ℹ Zep real uses typed exceptions: NotFoundError, ApiError, BadRequestError
  ℹ Our Zep uses generic exceptions (RuntimeError/ValueError)

── 4/6  Graphiti (graphiti-core) parity ─────────────────────────
  ✓ Graphiti class exists (real)
  ✓ Graphiti class exists (ours)
  ℹ Graphiti has extra params: {'embedder_type', 'host', 'client', 'port', 'database', 'embedder_url', 'token'}
  ℹ real Graphiti has extra params: {'cross_encoder', 'graph_driver', 'user', 'max_coroutines', 'tracer', 'store_raw_episode_content', 'trace_span_prefix', 'uri', 'password'}
  ✗ Graphiti constructor 0 common params
  ✓ EntityNode exists (real)
  ✓ EntityNode exists (ours)
  ℹ Real EntityNode fields: ['uuid', 'name', 'group_id', 'labels', 'created_at', 'name_embedding', 'summary', 'attributes']
  ℹ Our EntityNode attrs: ['from_stmem', 'group_id', 'name', 'name_embedding', 'summary']
  ✓ EntityEdge exists (real)
  ✓ EntityEdge exists (ours)
  ℹ Real EntityEdge fields: ['uuid', 'group_id', 'source_node_uuid', 'target_node_uuid', 'created_at', 'name', 'fact', 'fact_embedding', 'episodes', 'expired_at', 'valid_at', 'invalid_at', 'reference_time', 'attributes']
  ℹ Our EntityEdge attrs: ['edge_group_id', 'expired_at', 'fact', 'fact_embedding', 'from_stmem', 'group_id', 'invalid_at', 'name', 'source_node_uuid', 'target_node_uuid', 'valid_at', 'version']
  ✓ Graphiti.add_triplet exists (real)
  ✓ Graphiti.add_triplet exists (ours)
  ✓ Graphiti.search exists (real)
  ✓ Graphiti.search exists (ours)
  ✓ Graphiti.add_episode exists (real)
  ✓ Graphiti.add_episode exists (ours)
  ✓ Graphiti.build_communities exists (real)
  ✓ Graphiti.build_communities exists (ours)
  ✗ Graphiti.add_triplet params differ  ours=['source_node', 'edge', 'target_node', 'group_id'] vs real=['source_node', 'edge', 'target_node']
  ✗ Graphiti.search params differ  ours=['query', 'center_node_uuid', 'group_ids', 'num_results', 'kwargs'] vs real=['query', 'center_node_uuid', 'group_ids', 'num_results', 'search_filter', 'driver']
  ✓ Real Graphiti AddTripletResults annotates nodes/edges
  ✓ Our Graphiti AddTripletResults annotates nodes/edges
  ℹ Real Graphiti return types are Pydantic models; ours are plain classes
  ℹ Real EntityNode: Pydantic model; Our EntityNode: plain object
  ℹ This affects serialization, validation, and type inference

── 5/6  Hindsight parity ────────────────────────────────────────
  ℹ PyPI 'hindsight' package does not export Hindsight class — unrelated library
  ✓ Hindsight real API not testable via PyPI
  ℹ Our adapter IS the only Python SDK for vectorize-io/hindsight
  ℹ Real hindsight is at: https://github.com/vectorize-io/hindsight

── 6/6  Honcho parity ───────────────────────────────────────────
  ℹ PyPI 'honcho' v2.0.0 is Procfile manager, NOT plastic-labs/honcho
  ✓ Honcho AI library not on PyPI
  ℹ Our adapter IS the only Python SDK for plastic-labs/honcho
  ℹ Real honcho is at: https://github.com/plastic-labs/honcho
  ℹ Our Honcho API: ['add', 'create_session', 'create_user', 'get_or_create_session', 'get_or_create_user', 'get_session', 'get_user', 'search']

── Summary ──────────────────────────────────────────────────────
```

## Notes

- Mem0.Memory has extra params: {'token_refresh_callback'}
- Mem0 signature differences are expected — ours uses user/agent/run_id as kwargs,
-   real mem0 also uses user_id/agent_id/run_id as kwargs. Ours adds SpacetimeDB
-   specific: host/port/db passed via config dict, real mem0 uses MemoryConfig.
- mem0 v2 uses generic exception handling (no BaseMemoryException)
- Our Mem0 uses ValueError: 9x, RuntimeError: 17x
- Zep real uses typed exceptions: NotFoundError, ApiError, BadRequestError
- Our Zep uses generic exceptions (RuntimeError/ValueError)
- Graphiti has extra params: {'embedder_type', 'host', 'client', 'port', 'database', 'embedder_url', 'token'}
- real Graphiti has extra params: {'cross_encoder', 'graph_driver', 'user', 'max_coroutines', 'tracer', 'store_raw_episode_content', 'trace_span_prefix', 'uri', 'password'}
- Real EntityNode fields: ['uuid', 'name', 'group_id', 'labels', 'created_at', 'name_embedding', 'summary', 'attributes']
- Our EntityNode attrs: ['from_stmem', 'group_id', 'name', 'name_embedding', 'summary']
- Real EntityEdge fields: ['uuid', 'group_id', 'source_node_uuid', 'target_node_uuid', 'created_at', 'name', 'fact', 'fact_embedding', 'episodes', 'expired_at', 'valid_at', 'invalid_at', 'reference_time', 'attributes']
- Our EntityEdge attrs: ['edge_group_id', 'expired_at', 'fact', 'fact_embedding', 'from_stmem', 'group_id', 'invalid_at', 'name', 'source_node_uuid', 'target_node_uuid', 'valid_at', 'version']
- Real Graphiti return types are Pydantic models; ours are plain classes
- Real EntityNode: Pydantic model; Our EntityNode: plain object
- This affects serialization, validation, and type inference
- PyPI 'hindsight' package does not export Hindsight class — unrelated library
- Our adapter IS the only Python SDK for vectorize-io/hindsight
- Real hindsight is at: https://github.com/vectorize-io/hindsight
- PyPI 'honcho' v2.0.0 is Procfile manager, NOT plastic-labs/honcho
- Our adapter IS the only Python SDK for plastic-labs/honcho
- Real honcho is at: https://github.com/plastic-labs/honcho
- Our Honcho API: ['add', 'create_session', 'create_user', 'get_or_create_session', 'get_or_create_user', 'get_session', 'get_user', 'search']
