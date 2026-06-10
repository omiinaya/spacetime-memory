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
  ✓ Mem0.add shared keyword params: {'memory_type', 'prompt', 'user_id', 'infer', 'metadata', 'run_id', 'agent_id'}
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
  ℹ Graphiti has extra params: {'embedder_type', 'embedder_url', 'port', 'database', 'token', 'client', 'host'}
  ℹ real Graphiti has extra params: {'uri', 'store_raw_episode_content', 'tracer', 'cross_encoder', 'trace_span_prefix', 'user', 'password', 'max_coroutines', 'graph_driver'}
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
  ℹ === REAL HINDSIGHT API (from vectorize-io/hindsight v0.8.1 source) ===
  ℹ Import: from hindsight_client import Hindsight
  ℹ __init__(self, base_url: str, api_key: str | None = None, timeout: float = 300.0, user_agent: str | None = None)
  ℹ retain(self, bank_id: str, content: str, *, timestamp, context, document_id,
  ℹ        metadata, entities, tags, update_mode, retain_async=False) → RetainResponse
  ℹ recall(self, bank_id: str, query: str, *, types, max_tokens=4096, budget='mid',
  ℹ        trace, query_timestamp, include_entities, include_chunks, tags, ...) → RecallResponse
  ℹ reflect(self, bank_id: str, query: str, *, budget='low', context, max_tokens,
  ℹ         response_schema, tags, include_facts, include_tool_calls, ...) → ReflectResponse
  ℹ No forget() method. Also: retain_batch(), retain_files(), a* async variants
  ℹ 
  ℹ === OUR ADAPTER (hugely incompatible — different API entirely) ===
  ℹ Import: from spacetime_memory.sdks.hindsight import Hindsight
  ℹ __init__(self, config: dict | None = None, ...)
  ℹ retain(self, content: str, source: str = '', metadata=None)
  ℹ recall(self, query: str, limit: int = 20, threshold: float = 0.0)
  ℹ reflect(self, prompt: str = '...', context=None, tags=None, max_tokens=None, response_schema=None)
  ℹ forget(self, memory_id: str)
  ℹ 
  ✗ Hindsight: NOT a drop-in replacement  complete API mismatch — REST client vs embedded SDK
  ℹ Our Hindsight methods: ['batch_retain', 'export_template', 'forget', 'get_reflect_mission', 'import_template', 'list_all', 'recall', 'reflect', 'reset', 'retain', 'set_reflect_mission', 'stats']

── 6/6  Honcho parity ───────────────────────────────────────────
  ℹ === REAL HONCHO API (from plastic-labs/honcho SDK source on GitHub) ===
  ℹ Import: from honcho import Honcho
  ℹ __init__(self, workspace_id: str, base_url: str | None = None, *, environment='local' | 'production', ...)
  ℹ peer(self, id: str) → Peer            # get or create by ID
  ℹ peers(self) → SyncPage[Peer]          # list peers in workspace
  ℹ session(self, id: str) → Session      # get or create by ID
  ℹ sessions(self) → SyncPage[Session]    # list sessions
  ℹ search(self, query: str) → SyncPage[SessionSearchResult]
  ℹ workspaces(self) → SyncPage[str]      # list workspace IDs
  ℹ delete_workspace() → None
  ℹ Also: queue_status(), schedule_dream(), .aio accessor for async
  ℹ 
  ℹ === OUR ADAPTER (completely incompatible — different abstraction) ===
  ℹ Import: from spacetime_memory.sdks.honcho import Honcho
  ℹ __init__(self, config: dict | None = None, client=None)
  ℹ create_user(self, name: str, metadata=None) → User
  ℹ create_session(self, user_id: str, location: str = '', metadata=None) → Session
  ℹ add(self, session_id: str, content: str, metadata=None) → dict
  ℹ search(self, session_id: str, query: str, limit: int = 20) → list[dict]
  ℹ 
  ✗ Honcho: NOT a drop-in replacement  complete API mismatch — workspace/peer vs user/session model
  ℹ Our Honcho methods: ['add', 'create_session', 'create_user', 'get_or_create_session', 'get_or_create_user', 'get_session', 'get_user', 'search']

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
- Graphiti has extra params: {'embedder_type', 'embedder_url', 'port', 'database', 'token', 'client', 'host'}
- real Graphiti has extra params: {'uri', 'store_raw_episode_content', 'tracer', 'cross_encoder', 'trace_span_prefix', 'user', 'password', 'max_coroutines', 'graph_driver'}
- Real EntityNode fields: ['uuid', 'name', 'group_id', 'labels', 'created_at', 'name_embedding', 'summary', 'attributes']
- Our EntityNode attrs: ['from_stmem', 'group_id', 'name', 'name_embedding', 'summary']
- Real EntityEdge fields: ['uuid', 'group_id', 'source_node_uuid', 'target_node_uuid', 'created_at', 'name', 'fact', 'fact_embedding', 'episodes', 'expired_at', 'valid_at', 'invalid_at', 'reference_time', 'attributes']
- Our EntityEdge attrs: ['edge_group_id', 'expired_at', 'fact', 'fact_embedding', 'from_stmem', 'group_id', 'invalid_at', 'name', 'source_node_uuid', 'target_node_uuid', 'valid_at', 'version']
- Real Graphiti return types are Pydantic models; ours are plain classes
- Real EntityNode: Pydantic model; Our EntityNode: plain object
- This affects serialization, validation, and type inference
- === REAL HINDSIGHT API (from vectorize-io/hindsight v0.8.1 source) ===
- Import: from hindsight_client import Hindsight
- __init__(self, base_url: str, api_key: str | None = None, timeout: float = 300.0, user_agent: str | None = None)
- retain(self, bank_id: str, content: str, *, timestamp, context, document_id,
-        metadata, entities, tags, update_mode, retain_async=False) → RetainResponse
- recall(self, bank_id: str, query: str, *, types, max_tokens=4096, budget='mid',
-        trace, query_timestamp, include_entities, include_chunks, tags, ...) → RecallResponse
- reflect(self, bank_id: str, query: str, *, budget='low', context, max_tokens,
-         response_schema, tags, include_facts, include_tool_calls, ...) → ReflectResponse
- No forget() method. Also: retain_batch(), retain_files(), a* async variants
- 
- === OUR ADAPTER (hugely incompatible — different API entirely) ===
- Import: from spacetime_memory.sdks.hindsight import Hindsight
- __init__(self, config: dict | None = None, ...)
- retain(self, content: str, source: str = '', metadata=None)
- recall(self, query: str, limit: int = 20, threshold: float = 0.0)
- reflect(self, prompt: str = '...', context=None, tags=None, max_tokens=None, response_schema=None)
- forget(self, memory_id: str)
- 
- Our Hindsight methods: ['batch_retain', 'export_template', 'forget', 'get_reflect_mission', 'import_template', 'list_all', 'recall', 'reflect', 'reset', 'retain', 'set_reflect_mission', 'stats']
- === REAL HONCHO API (from plastic-labs/honcho SDK source on GitHub) ===
- Import: from honcho import Honcho
- __init__(self, workspace_id: str, base_url: str | None = None, *, environment='local' | 'production', ...)
- peer(self, id: str) → Peer            # get or create by ID
- peers(self) → SyncPage[Peer]          # list peers in workspace
- session(self, id: str) → Session      # get or create by ID
- sessions(self) → SyncPage[Session]    # list sessions
- search(self, query: str) → SyncPage[SessionSearchResult]
- workspaces(self) → SyncPage[str]      # list workspace IDs
- delete_workspace() → None
- Also: queue_status(), schedule_dream(), .aio accessor for async
- 
- === OUR ADAPTER (completely incompatible — different abstraction) ===
- Import: from spacetime_memory.sdks.honcho import Honcho
- __init__(self, config: dict | None = None, client=None)
- create_user(self, name: str, metadata=None) → User
- create_session(self, user_id: str, location: str = '', metadata=None) → Session
- add(self, session_id: str, content: str, metadata=None) → dict
- search(self, session_id: str, query: str, limit: int = 20) → list[dict]
- 
- Our Honcho methods: ['add', 'create_session', 'create_user', 'get_or_create_session', 'get_or_create_user', 'get_session', 'get_user', 'search']
