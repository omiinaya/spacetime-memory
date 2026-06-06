# spacetime-memory MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that exposes
[spacetime-memory](https://github.com/nousresearch/spacetime-memory) as MCP tools
for any MCP-compatible agent (Claude Code, Codex, Cline, etc.).

## Architecture

```
┌──────────────┐    stdio     ┌──────────────┐    HTTP     ┌────────────────┐
│  MCP Client  │ ──────────►  │  MCP Server  │ ──────────► │  SpacetimeDB   │
│  (Agent)     │ ◄──────────  │  (this tool) │ ◄────────── │  (v2.4, WASM)  │
└──────────────┘              └──────────────┘              └────────────────┘
```

The MCP server translates tool calls into SQL queries and reducer calls against
the SpacetimeDB HTTP API (`/v1/database/{db}/sql` and `/v1/database/{db}/call/{reducer}`).

## Configuration

Set these environment variables (or accept defaults):

| Variable | Default | Description |
|---|---|---|
| `SPACETIMEDB_HOST` | `localhost` | SpacetimeDB hostname |
| `SPACETIMEDB_PORT` | `3001` | SpacetimeDB HTTP port |
| `SPACETIMEDB_DB` | `spacetime-memory` | Database name |

## Tools

### Workspace

| Tool | Description | Parameters |
|---|---|---|
| `create_workspace` | Create a new workspace | `name`, `description` |
| `list_workspaces` | List all workspaces | _(none)_ |

### Memory

| Tool | Description | Parameters |
|---|---|---|
| `store_memory` | Store a new memory | `workspace_id`, `peer_id`, `observer_id`, `memory_type`, `content`, `summary`, `entities_json`, `confidence`, `source_session_id`, `source_message_id`, `tier` |
| `search_memories` | Search memories with filters | `workspace_id`, `query_text`, `memory_type`, `tier`, `limit` |
| `get_memory` | Get a memory by ID | `id` |
| `reinforce_memory` | Reinforce a memory (bump access+strength) | `memory_id` |
| `rate_memory` | Rate a memory helpful/unhelpful | `memory_id`, `rating`, `peer_id` |

### Profile

| Tool | Description | Parameters |
|---|---|---|
| `get_profile` | Get a peer's profile | `peer_id` |
| `upsert_profile` | Create or update a peer profile | `peer_id`, `static_facts_json`, `dynamic_context_json`, `preferences_json`, `tags_json` |

### Knowledge Graph

| Tool | Description | Parameters |
|---|---|---|
| `query_graph` | Search KG nodes by label | `workspace_id`, `query` |
| `get_node` | Get a KG node by ID | `id` |
| `get_neighbors` | Get edges for a node (with labels) | `node_id` |
| `get_community` | Get community + its nodes | `community_id` |

### Session

| Tool | Description | Parameters |
|---|---|---|
| `get_peer_sessions` | List sessions for a peer | `peer_id` |
| `get_session_messages` | Get messages for a session | `session_id` |

## Running

```bash
# Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run (stdio transport)
python3 main.py
```

For testing with an MCP client:

```bash
# Check the server starts and prints its capabilities
python3 -c "import json, subprocess; p=subprocess.run(['python3','main.py'], input=json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'test','version':'0.1.0'}}})+'\n", capture_output=True, text=True); print(p.stdout[:2000]); print(p.stderr[:500])"
```

## Requirements

- Python 3.10+
- `mcp` (MCP SDK)
- `httpx` (HTTP client)
- A running SpacetimeDB instance with the spacetime-memory module published
