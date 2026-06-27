# Getting Started

## Prerequisites

- Rust toolchain (`cargo`, `rustup`)
- SpacetimeDB CLI v2.6+ (`spacetime version upgrade`)
- Node.js 18+ and npm
- Python 3.10+ (for SDK/CLI/MCP)

## 1. Clone & Setup

```bash
git clone https://github.com/omiinaya/spacetime-memory.git
cd spacetime-memory
```

## 2. Start SpacetimeDB

```bash
spacetime start --listen-addr 0.0.0.0:3001 &

# Or via Make:
make start-stdb
```

## 3. Build & Publish Module

The conftest auto-publishes via HTTP API, but you can also build manually:

```bash
cd server/spacetimedb
cargo build --target wasm32-unknown-unknown --release

# Or via Make:
make build-module
```

The test suite publishes automatically when it detects a running SpacetimeDB.

## 4. Install Python SDK & CLI

```bash
cd sdk/python
pip install -e .

# Or via Make:
make install-sdk

# CLI available as `stmem`:
stmem --help
```

## 5. Start Embedder Sidecar (optional — needed for semantic search)

```bash
# The embedder is a compiled Rust binary (tract + all-MiniLM-L6-v2)
# It's pre-built at server/embedder/target/release/embedder
# Or build from source:
cd server/embedder && cargo build --release
./target/release/embedder   # Listens on :9090
```

## 6. Start MCP Server (optional)

```bash
python server/mcp/main.py  # stdio transport for LLM agents
```

## 7. Start Frontend (optional)

```bash
cd client
npm install
cp .env.example .env       # configure host/db
npm run dev                 # opens on localhost:5173
```

## 8. Login (First Run)

Open the frontend. On first launch, register as the admin user. Subsequent launches will prompt for login. All note operations are auth-gated.

## Running Tests

The test suite has two tiers:

```bash
# Unit tests only — no SpacetimeDB needed (~30s)
cd sdk/python && python -m pytest tests/ -m unit -v

# Full suite (unit + integration) — needs SpacetimeDB on :3001
make test

# Integration tests only — auto-builds module, auto-publishes
make test-integration
```

The integration tests auto-publish the module via HTTP API. If no SpacetimeDB is running, they skip cleanly.

## Quick Start Using the Python SDK

### Using the Low-Level Client

```python
from spacetime_memory import Client

client = Client(host="localhost", port="3001", database="your-db")

# Create a workspace
ws = client.create_workspace("my-app")
ws_id = ws["id"]

# Store a memory
client.store(ws_id, "I like pizza", peer_id="alice")

# Search memories
results = client.search(ws_id, "food preferences", semantic=True)
print(results)
```

### Using the Mem0 Adapter

```python
from spacetime_memory.sdks import Mem0Memory

m = Mem0Memory(config={"host": "localhost", "port": "3001"})
m.add("I like pizza", user_id="alice")
results = m.search("food preferences", user_id="alice")
```

### Using the Hindsight Adapter

```python
from spacetime_memory.sdks import Hindsight

h = Hindsight(base_url="http://localhost:3001", api_key="optional")
h.retain("my_bank", "I like pizza")
results = h.recall("my_bank", "food preferences")
```

### Using the Honcho Adapter

```python
from spacetime_memory.sdks import Honcho

honcho = Honcho(workspace_id="my_workspace")
p = honcho.peer("alice")
s = honcho.session("my_session")
s.add_messages([{"role": "user", "content": "I like pizza"}])
results = honcho.search("pizza")
print(results)
```

### Using the LangGraph Adapter

```python
from spacetime_memory.sdks import StmemStore

store = StmemStore(host="localhost", port="3001")
store.put(("memories", "alice"), {"data": "I like pizza"})
items = store.search(("memories", "alice"), query="pizza")
```
