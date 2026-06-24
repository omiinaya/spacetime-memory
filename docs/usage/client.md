# Low-Level Client API

The `Client` class provides a direct interface to the SpacetimeDB HTTP SQL and reducer APIs. It is the foundation that all SDK adapters build on.

## Creating a Client

```python
from spacetime_memory import Client

# Minimal — uses defaults (localhost:3001)
client = Client()

# Custom configuration
client = Client(
    host="127.0.0.10",
    port=3001,
    database="my-db",
    embedder_url="http://localhost:9090",
    embedder_type="auto",  # "local", "openai", or "auto"
    timeout=30.0,
    verbose=True,
    token="<jwt-token>",  # or set SPACETIMEDB_TOKEN env var
)
```

The default database identity is derived from the SpacetimeDB module address. Override with the `database` parameter or the `SPACETIMEDB_DB` environment variable.

### Embedder Types

| Type | Description |
|------|-------------|
| `"local"` | Use the Rust ONNX sidecar (default if no `OPENAI_API_KEY`) |
| `"openai"` | Use OpenAI's embeddings API directly |
| `"auto"` | Try local sidecar first, fall back to OpenAI if unavailable |

Set `OPENAI_API_KEY` in your environment for OpenAI fallback or direct OpenAI usage.

## Authentication

Clients authenticate via:

1. **Anonymous identity** — auto-captured on first request via the `spacetime-identity` header
2. **JWT token** — passed via `token` param or `SPACETIMEDB_TOKEN` env var

To use JWT auth:

```python
# From a token file
client = Client.from_token_file("/path/to/token.jwt")

# Or pass the token directly
client = Client(token="<your-jwt-token>")
```

Generate a token:

```bash
python -c "from spacetime_memory.auth import generate_token; \
    print(generate_token('data/id_ecdsa_pkcs8.pem'))" > /path/to/token.jwt
```

## Workspace Management

```python
# Create
ws = client.create_workspace("my-app", description="My app workspace")

# List
workspaces = client.list_workspaces()

# Delete (via reducer)
client._call("delete_workspace", [ws_id])
```

## Peer Management

```python
# Create a peer (user, agent, or entity)
client.create_peer(workspace_id=ws_id, name="alice", peer_type="user")

# List peers in a workspace
peers = client.list_peers(ws_id)
```

## Memory Operations

```python
# Store a memory
result = client.store(
    workspace_id=ws_id,
    content="I like pizza",
    summary="Food preference",
    memory_type="experience",  # "world_fact", "experience", "mental_model"
    peer_id=peer_id,
    observer_id="",
    entities_json='[{"name": "pizza", "type": "food"}]',
    confidence=0.9,
    source_session_id="",
    source_message_id="",
    tier="L1",  # "L0", "L1", "L2"
)

# Search memories
results = client.search(
    workspace_id=ws_id,
    query="food preferences",
    memory_type="",
    tier="",
    limit=50,
    semantic=True,  # use embedding search
)
```

## Knowledge Graph

```python
# Create a node
client._call("create_node", [ws_id, "Alice", "person", "{}"])

# Create an edge
client._call("create_edge", [ws_id, "node-1", "node-2", "likes", 0.9])

# Graph traversal
results = client._call("graph_bfs", [ws_id, "node-1", 3])

# Shortest path
results = client._call("shortest_path", [ws_id, "node-1", "node-3"])
```

## Sessions & Messages

```python
# Create a session
client._call("create_session", [ws_id, "session-1"])

# Send a message
client._call("send_message", [ws_id, session_id, peer_id, "Hello!"])

# List sessions (via SQL)
sessions = client._sql("SELECT * FROM session WHERE workspace_id = '...'")
```

## Raw SQL Queries

For advanced use cases, run any SQL query:

```python
results = client._sql("SELECT * FROM memory WHERE workspace_id = 'ws-1' ORDER BY confidence DESC LIMIT 10")
```

## Direct Reducer Calls

Any reducer can be called directly:

```python
client._call("reducer_name", [arg1, arg2, ...])
```

See the [full list of reducers](../index.md#reducer-api) for available operations.

## Configuration via Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SPACETIMEDB_HOST` | `localhost` | SpacetimeDB host |
| `SPACETIMEDB_PORT` | `3001` | SpacetimeDB port |
| `SPACETIMEDB_DB` | (module address) | Database identity |
| `SPACETIMEDB_TOKEN` | — | JWT auth token |
| `EMBEDDER_URL` | `http://localhost:9090` | Embedder sidecar URL |
| `OPENAI_API_KEY` | — | OpenAI API key for embeddings |
| `STMEM_MAX_RETRIES` | `3` | Max HTTP retries |

## Error Handling

The client provides human-friendly error messages:

```python
from spacetime_memory import EmbedderUnavailableError

try:
    client.store(ws_id, "test", peer_id=peer_id)
except RuntimeError as e:
    print(f"Operation failed: {e}")
except EmbedderUnavailableError as e:
    print(f"Embedding unavailable: {e}")
```

## Metrics

Attach a metrics collector to track request performance:

```python
from spacetime_memory import MetricsCollector

collector = MetricsCollector()
client.set_metrics_collector(collector)

# Later: export metrics
metrics = client.get_metrics()
```

## Logging

```python
from spacetime_memory import configure_logging

configure_logging(level="DEBUG", json_format=True, log_file="/tmp/stmem.log")
```
