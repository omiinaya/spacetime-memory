# Deployment Guide

> **Spacetime Memory** — running in production: Docker, native, and production considerations.

---

## Table of Contents

1. [Quick Start (Docker)](#quick-start-docker)
2. [Native Installation](#native-installation)
3. [Configuration](#configuration)
4. [Production Hardening](#production-hardening)
5. [Monitoring & Health](#monitoring--health)
6. [Troubleshooting](#troubleshooting)

---

## Quick Start (Python SDK)

```bash
# Install from PyPI
pip install spacetime-memory

# With LangChain/LangGraph support
pip install "spacetime-memory[langchain]"

# All extras
pip install "spacetime-memory[all]"
```

### Running

You need a running SpacetimeDB instance with the module published.
The quickest way is Docker (see below).

```python
from spacetime_memory import Client

client = Client()
ws_id = client.create_workspace("my-workspace")["id"]
client.store(ws_id, "Hello, world!")

# Use drop-in adapters
from spacetime_memory.sdks.mem0 import Memory as Mem0Memory
m = Mem0Memory()
m.add("I like pizza", user_id="alice")
```

## Quick Start (Docker)

**Prerequisites:** Docker Engine 24+ and Docker Compose v2.

```bash
# Clone the repo
git clone https://github.com/omiinaya/spacetime-memory
cd spacetime-memory

# Start everything
docker compose up --build -d

# Check logs
docker compose logs -f

# Open the dashboard
open http://localhost:5173
```

This starts:
- **SpacetimeDB** (port 3001) — the core persistence engine
- **ONNX embedder** (port 9090) — vector embeddings for semantic search
- **Frontend** (port 5173) — React dashboard

### Upgrade

```bash
git pull
docker compose up --build -d
```

Data persists in a Docker volume (`spacetime-data`) across restarts.

---

## Native Installation

### Prerequisites

- Python 3.11+
- Rust toolchain with `wasm32-unknown-unknown` target
- Node.js 20+
- SpacetimeDB CLI v2.4.1

### 1. Install SpacetimeDB CLI

```bash
curl -fsSL https://github.com/clockworklabs/SpacetimeDB/releases/download/v2.4.1/spacetime-linux-x86_64.tgz \
  | tar xz -C /usr/local/bin/
spacetime version
```

### 2. Download the embedding model

```bash
pip install huggingface-hub
bash scripts/download-model.sh
```

### 3. Build the embedder sidecar

```bash
cd server/embedder
cargo build --release
cp target/release/embedder /usr/local/bin/
```

### 4. Publish the SpacetimeDB module

```bash
spacetime start --listen-addr 0.0.0.0:3001 --data-dir data/ &
cd server/spacetimedb
spacetime publish --project-path . spacetime-memory
```

### 5. Install Python SDK + CLI

```bash
pip install -e sdk/python
pip install -e cli
```

### 6. Start the embedder

```bash
export MODEL_PATH=server/embedder/model/all-MiniLM-L6-v2.onnx
embedder &
```

### 7. Build and serve the frontend

```bash
cd client
npm install
npm run build
python3 -m http.server 5173 --directory dist/ &
```

### 8. Configure and run

```bash
cp .env.example .env
# Edit .env with your settings
stmem --help
```

---

## Configuration

All configuration uses environment variables. See [CONFIG.md](CONFIG.md) for the full reference.

### Required vars

| Variable | Default | Description |
|----------|---------|-------------|
| `SPACETIMEDB_HOST` | `localhost` | SpacetimeDB hostname |
| `SPACETIMEDB_PORT` | `3001` | SpacetimeDB HTTP port |
| `SPACETIMEDB_DB` | `spacetime-memory` | Database identity |

### OpenAI embedding fallback (recommended)

The system uses a local ONNX embedder by default (`all-MiniLM-L6-v2`, 384d). For higher quality or as fallback:

```env
EMBEDDER_TYPE=auto
OPENAI_API_KEY=sk-...
```

With `EMBEDDER_TYPE=auto`, the system tries the local embedder first, then falls back to OpenAI `text-embedding-3-small` if the local one is unavailable.

### Authentication

```env
MCP_API_KEY=your-api-key-here
```

When set, the MCP server requires `Authorization: Bearer <key>` on HTTP/SSE transport. Not required for stdio transport.

---

## Production Hardening

### 1. Dedicated SpacetimeDB

For production, run SpacetimeDB as a dedicated service rather than inside the container:

```yaml
# docker-compose.prod.yml
services:
  spacetimedb:
    image: clockworklabs/spacetimedb:v2.4.1
    ports: ["3001:3001"]
    volumes: ["spacetime-data:/var/lib/spacetimedb"]
    command: ["start", "--listen-addr", "0.0.0.0:3001"]

  embedder:
    build:
      context: .
      dockerfile: Dockerfile
      target: embedder
    ports: ["9090:9090"]
    volumes: ["model-data:/app/model"]

  app:
    build:
      context: .
      dockerfile: Dockerfile
      target: runtime
    ports: ["5173:5173"]
    depends_on: [spacetimedb, embedder]
    environment:
      SPACETIMEDB_HOST: spacetimedb
      SPACETIMEDB_PORT: "3001"
      EMBEDDER_URL: http://embedder:9090
```

### 2. Resource limits

```yaml
services:
  spacetimedb:
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: "2"
  embedder:
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: "1"
```

### 3. Persistent volumes

```yaml
volumes:
  spacetime-data:
    driver: local
    driver_opts:
      type: none
      device: /data/spacetime-memory
      o: bind
```

### 4. Reverse proxy (TLS)

```nginx
# /etc/nginx/sites-available/spacetime-memory
server {
    listen 443 ssl;
    server_name memory.example.com;

    ssl_certificate /etc/letsencrypt/live/memory.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/memory.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5173;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 5. Environment security

- **Never commit `.env` files** with real credentials.
- Use a secrets manager (Vault, 1Password CLI, `docker secret`) for API keys.
- Rotate `MCP_API_KEY` regularly.
- Run the MCP server on stdio transport (not HTTP) inside agent environments.

### 6. Backup

The included backup script creates periodic snapshots:

```bash
# Manual backup
python scripts/backup.py

# Cron (daily at 2am)
0 2 * * * cd /path/to/spacetime-memory && python scripts/backup.py >> /var/log/stmem-backup.log 2>&1
```

Backups include: all memories, workspaces, graph data, profiles, facts, sessions, and directory structure.

---

## Monitoring & Health

### Health checks

SpacetimeDB exposes health at `/` (GET) — returns 200 when ready.

The embedder exposes `/health` (GET) — returns `{"status": "ok"}` when ready.

### Logs

- SpacetimeDB logs via `spacetime start` → stdout.
- The Docker entrypoint logs all service startup/shutdown events.
- Set `RUST_LOG=spacetimedb=debug` for verbose SpacetimeDB logging.

### Metrics

- Python SDK: set `VERBOSE=true` to see all HTTP requests.
- Use `docker stats` to monitor resource usage.
- For production, integrate with your existing monitoring stack (Prometheus/node_exporter, Datadog, etc.).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Connection refused: localhost:3001` | SpacetimeDB not running | Start it: `spacetime start --listen-addr 0.0.0.0:3001` |
| Embedder returns 500 | ONNX model not found | Run `bash scripts/download-model.sh` |
| `No module named 'spacetime_memory'` | SDK not installed | `pip install -e sdk/python` |
| Frontend shows blank page | Backend not reachable | Check VITE_SPACETIMEDB_WS in .env matches your SpacetimeDB host |
| Authentication errors | MCP_API_KEY mismatch | Check MCP_API_KEY matches between client and server |
| Memory search returns 0 results | Embedder down or model not loaded | Check `curl http://localhost:9090/health` |

---

## Architecture

```
┌─────────────────────┐      ┌───────────────────┐
│   AI Agent (MCP)    │      │ User (CLI/Web UI) │
├─────────────────────┤      ├───────────────────┤
│ MCP tools via       │      │ stmem CLI /       │
│ stdio / HTTP/SSE    │      │ React Dashboard   │
└────────┬────────────┘      └────────┬──────────┘
         │                            │
         ▼                            ▼
┌──────────────────────────────────────────────┐
│          Spacetime Memory (App Server)       │
│  ┌──────────┐  ┌────────┐  ┌──────────────┐  │
│  │  Python  │  │  CLI   │  │  Connectors  │  │
│  │   SDK    │  │ (stmem)│  │  RSS/GitHub/ │  │
│  │          │  │        │  │  Slack/etc.  │  │
│  └────┬─────┘  └────────┘  └──────────────┘  │
└───────┼──────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────┐
│          SpacetimeDB (Rust/WASM)             │
│  memories · graph · sessions · profiles      │
│  facts · notes · directories · auth          │
├──────────────────────────────────────────────┤
│          ONNX Embedder (:9090)               │
│          all-MiniLM-L6-v2 → 384d vectors     │
└──────────────────────────────────────────────┘
```
