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
  ✓ Mem0.Memory constructor 1 common params
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
  ✓ Mem0.add shared keyword params: {'agent_id', 'memory_type', 'user_id', 'infer', 'metadata', 'prompt', 'run_id'}
  ✓ Mem0.add returns dict with 'results' key
  ✓ Our Mem0 has .graph property
  ℹ mem0 v2 uses generic exception handling (no BaseMemoryException)
  ✓ mem0 exceptions exist
  ℹ Our Mem0 uses ValueError: 9x, RuntimeError: 24x
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
  ✓ Zep: NotFoundError exists
  ✓ Zep: BadRequestError exists
  ✓ Zep: add_session() exists
  ✓ Zep: update_session() exists
  ✓ Zep: search_sessions() exists
  ℹ Our Zep uses generic exceptions (RuntimeError/ValueError)

── 4/6  Graphiti (graphiti-core) parity ─────────────────────────
  ✓ Graphiti class exists (real)
  ✓ Graphiti class exists (ours)
  ℹ Graphiti has extra params: {'port', 'database', 'client', 'embedder_type', 'token', 'embedder_url', 'host'}
  ℹ real Graphiti has extra params: {'graph_driver', 'tracer', 'password', 'user', 'cross_encoder', 'uri', 'max_coroutines', 'trace_span_prefix', 'store_raw_episode_content'}
  ✗ Graphiti constructor 0 common params
  ✓ EntityNode exists (real)
  ✓ EntityNode exists (ours)
  ℹ Real EntityNode fields: ['uuid', 'name', 'group_id', 'labels', 'created_at', 'name_embedding', 'summary', 'attributes']
  ℹ Our EntityNode dataclass fields: ['group_id', 'name', 'name_embedding', 'summary']
  ℹ Our EntityNode __dataclass_fields__: ['uuid', 'name', 'name_embedding', 'summary', 'group_id', 'labels', 'attributes', 'created_at']
  ✓ EntityNode fields match upstream (8/8)
  ✓ EntityEdge exists (real)
  ✓ EntityEdge exists (ours)
  ℹ Real EntityEdge fields: ['uuid', 'group_id', 'source_node_uuid', 'target_node_uuid', 'created_at', 'name', 'fact', 'fact_embedding', 'episodes', 'expired_at', 'valid_at', 'invalid_at', 'reference_time', 'attributes']
  ℹ Our EntityEdge __dataclass_fields__: ['uuid', 'name', 'fact', 'fact_embedding', 'source_node_uuid', 'target_node_uuid', 'group_id', 'episodes', 'valid_at', 'invalid_at', 'expired_at', 'attributes', 'created_at', 'version', 'edge_group_id', 'reference_time']
  ✓ EntityEdge fields match upstream (14/14)
  ✓ Graphiti.add_triplet exists (real)
  ✓ Graphiti.add_triplet exists (ours)
  ✓ Graphiti.search exists (real)
  ✓ Graphiti.search exists (ours)
  ✓ Graphiti.add_episode exists (real)
  ✓ Graphiti.add_episode exists (ours)
  ✓ Graphiti.build_communities exists (real)
  ✓ Graphiti.build_communities exists (ours)
  ✗ Graphiti.add_triplet params differ  ours=['source_node', 'edge', 'target_node', 'group_id'] vs real=['source_node', 'edge', 'target_node']
  ✗ Graphiti.search params differ  ours=['query', 'center_node_uuid', 'group_ids', 'num_results', 'search_filter', 'driver', 'kwargs'] vs real=['query', 'center_node_uuid', 'group_ids', 'num_results', 'search_filter', 'driver']
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
  ✓ Hindsight: no obsolete params (matching real API)
  ℹ Methods: ['aclose', 'acreate_bank', 'acreate_directive', 'acreate_mental_model', 'adelete_bank', 'alist_memories', 'arecall', 'areflect', 'aretain', 'aretain_batch', 'close', 'create_bank', 'create_directive', 'create_mental_model', 'delete_bank', 'list_memories', 'recall', 'reflect', 'retain', 'retain_batch', 'retain_files']
  ✓ Hindsight: retain/recall/reflect methods exist
  ✓ Hindsight: async variants exist
  ✓ Hindsight: retain_batch/retain_files exist
  ✗ Hindsight: no stale methods (forget, export_template, etc.)
  ✓ Hindsight.retain() has bank_id param
  ✓ Hindsight.retain() has context param
  ✓ Hindsight.retain() has entities/tags
  ✓ Hindsight.recall() has max_tokens param
  ✓ Hindsight.recall() has budget param
  ✓ Hindsight.reflect() has budget param
  ✓ Hindsight.reflect() has response_schema param
  ✓ Hindsight.reflect() has include_facts param
  ✓ RetainResponse is Pydantic model
  ✓ RecallResponse is Pydantic model
  ✓ ReflectResponse is Pydantic model
  ✓ RecallResult has score field
  ℹ Old adapter return types (dicts) replaced with typed Pydantic models
  ℹ No forget(), export_template(), import_template(), list_all(), stats(), reset() methods

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
  ℹ === OUR ADAPTER (now matches upstream API shape) ===
  ℹ Import: from spacetime_memory.sdks.honcho import Honcho
  ℹ Honcho(workspace_id='...', base_url=None, stdb_host=..., stdb_port=...)
  ℹ peer(id, *, metadata, configuration) → Peer
  ℹ session(id, *, metadata, configuration, peers) → Session
  ℹ search(query, filters, limit) → list[Message]
  ℹ Peer.message(), Peer.chat(), Peer.search()
  ℹ Session.add_peers(), Session.add_messages(), Session.context()
  ℹ
  ℹ Methods: ['close', 'delete_workspace', 'get_configuration', 'get_metadata', 'peer', 'peers', 'queue_status', 'refresh', 'schedule_dream', 'search', 'session', 'sessions', 'set_configuration', 'set_metadata', 'workspaces']
  ✓ Honcho: peer/session/search methods exist
  ✓ Honcho: workspaces/delete_workspace exist
  ✗ Honcho: no stale methods (create_user, create_session, etc.)
  ✓ Honcho.peer() has id param
  ✓ Honcho.peer() has metadata param
  ✓ Honcho.session() has id param
  ✓ Honcho.session() has configuration param
  ✓ Honcho.search() has limit param
  ✓ Peer has message() method
  ✓ Peer has chat() method
  ✓ Peer has search() method
  ✓ Session has add_peers() method
  ✓ Session has add_messages() method
  ✓ Session has context() method
  ℹ Honcho adapter now matches plastic-labs/honcho API shape

── Summary ──────────────────────────────────────────────────────
```

## Notes

- Mem0 signature differences are expected — ours uses user/agent/run_id as kwargs,
-   real mem0 also uses user_id/agent_id/run_id as kwargs. Ours adds SpacetimeDB
-   specific: host/port/db passed via config dict, real mem0 uses MemoryConfig.
- mem0 v2 uses generic exception handling (no BaseMemoryException)
- Our Mem0 uses ValueError: 9x, RuntimeError: 24x
- Our Zep uses generic exceptions (RuntimeError/ValueError)
- Graphiti has extra params: {'port', 'database', 'client', 'embedder_type', 'token', 'embedder_url', 'host'}
- real Graphiti has extra params: {'graph_driver', 'tracer', 'password', 'user', 'cross_encoder', 'uri', 'max_coroutines', 'trace_span_prefix', 'store_raw_episode_content'}
- Real EntityNode fields: ['uuid', 'name', 'group_id', 'labels', 'created_at', 'name_embedding', 'summary', 'attributes']
- Our EntityNode dataclass fields: ['group_id', 'name', 'name_embedding', 'summary']
- Our EntityNode __dataclass_fields__: ['uuid', 'name', 'name_embedding', 'summary', 'group_id', 'labels', 'attributes', 'created_at']
- Real EntityEdge fields: ['uuid', 'group_id', 'source_node_uuid', 'target_node_uuid', 'created_at', 'name', 'fact', 'fact_embedding', 'episodes', 'expired_at', 'valid_at', 'invalid_at', 'reference_time', 'attributes']
- Our EntityEdge __dataclass_fields__: ['uuid', 'name', 'fact', 'fact_embedding', 'source_node_uuid', 'target_node_uuid', 'group_id', 'episodes', 'valid_at', 'invalid_at', 'expired_at', 'attributes', 'created_at', 'version', 'edge_group_id', 'reference_time']
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
- Methods: ['aclose', 'acreate_bank', 'acreate_directive', 'acreate_mental_model', 'adelete_bank', 'alist_memories', 'arecall', 'areflect', 'aretain', 'aretain_batch', 'close', 'create_bank', 'create_directive', 'create_mental_model', 'delete_bank', 'list_memories', 'recall', 'reflect', 'retain', 'retain_batch', 'retain_files']
- Old adapter return types (dicts) replaced with typed Pydantic models
- No forget(), export_template(), import_template(), list_all(), stats(), reset() methods
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
- === OUR ADAPTER (now matches upstream API shape) ===
- Import: from spacetime_memory.sdks.honcho import Honcho
- Honcho(workspace_id='...', base_url=None, stdb_host=..., stdb_port=...)
- peer(id, *, metadata, configuration) → Peer
- session(id, *, metadata, configuration, peers) → Session
- search(query, filters, limit) → list[Message]
- Peer.message(), Peer.chat(), Peer.search()
- Session.add_peers(), Session.add_messages(), Session.context()
-
- Methods: ['close', 'delete_workspace', 'get_configuration', 'get_metadata', 'peer', 'peers', 'queue_status', 'refresh', 'schedule_dream', 'search', 'session', 'sessions', 'set_configuration', 'set_metadata', 'workspaces']
- Honcho adapter now matches plastic-labs/honcho API shape
