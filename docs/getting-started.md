# Getting Started

## Prerequisites

- Rust toolchain (`cargo`, `rustup`)
- SpacetimeDB CLI v2.4+ (`spacetime version upgrade`)
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
```

## 3. Build & Publish Module

```bash
cd server/spacetimedb
cargo build --target wasm32-unknown-unknown
spacetime publish spacetime-memory -p ./ --yes
```

## 4. Start Embedder Sidecar

```bash
# The embedder is a compiled Rust binary (tract + all-MiniLM-L6-v2)
# It's pre-built at server/embedder/target/release/embedder
# Or build from source:
cd server/embedder && cargo build --release
./target/release/embedder   # Listens on :9090
```

## 5. Install Python SDK & CLI

```bash
cd sdk/python
pip install -e .

# CLI available as `stmem`:
stmem --help
```

## 6. Start MCP Server

```bash
python server/mcp/main.py  # stdio transport for LLM agents
```

## 7. Start Frontend

```bash
cd client
npm install
cp .env.example .env       # configure host/db
npm run dev                 # opens on localhost:5173
```

## 8. Login (First Run)

Open the frontend. On first launch, register as the admin user. Subsequent launches will prompt for login. All note operations are auth-gated.

## Quick Start Using the Python SDK

### Using the Low-Level Client

```python
from spacetime_memory import Client

client = Client()

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

m = Mem0Memory()
m.add("I like pizza", user_id="alice")
results = m.search("food preferences", user_id="alice")
```

### Using the Hindsight Adapter

```python
from spacetime_memory.sdks import Hindsight

h = Hindsight()
h.retain("I like pizza", source="chat")
results = h.recall("food preferences")
```

### Using the Honcho Adapter

```python
from spacetime_memory.sdks import Honcho

honcho = Honcho()
user = honcho.create_user(name="alice")
session = honcho.create_session(user_id=user["id"])
honcho.add("I like pizza", session_id=session["id"])
results = honcho.search("food", session_id=session["id"])
```
