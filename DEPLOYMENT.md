# Deployment Guide

> **Spacetime Memory** — running in production: Docker, native, Kubernetes, and operations reference.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Quick Start (Docker)](#quick-start-docker)
3. [Quick Start (One-Command Setup)](#quick-start-one-command-setup)
4. [Quick Start (Python SDK)](#quick-start-python-sdk)
5. [Native Installation](#native-installation)
6. [Safe Module Publishing](#safe-module-publishing)
7. [MCP Server Deployment](#mcp-server-deployment)
8. [Connector Daemon Deployment](#connector-daemon-deployment)
9. [CI/CD & Testing](#cicd--testing)
10. [What the Entrypoint Does](#what-the-entrypoint-does)
11. [Configuration Reference](#configuration-reference)
12. [Docker Compose Files](#docker-compose-files)
13. [Production Hardening](#production-hardening)
14. [Kubernetes Deployment](#kubernetes-deployment)
15. [Upgrades & Migrations](#upgrades--migrations)
16. [Backup & Restore](#backup--restore)
17. [Monitoring & Health](#monitoring--health)
18. [JWT Key Rotation](#jwt-key-rotation)
19. [Network & Ports](#network--ports)
20. [Resource Requirements](#resource-requirements)
21. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌─────────────────────┐      ┌───────────────────┐
│   AI Agent (MCP)    │      │ User (CLI/Web UI) │
├─────────────────────┤      ├───────────────────┤
│ MCP tools via       │      │ stmem CLI /       │
│ stdio / HTTP/SSE    │      │ React Dashboard   │
└────────┬────────────┘      └────────┬──────────┘
         │                            │
         ▼                            ▼
┌───────────────────────────────────────────────────────────┐
│              Spacetime Memory (App Server)                 │
│  ┌──────────┐  ┌────────┐  ┌──────────────┐  ┌────────┐  │
│  │  Python  │  │  CLI   │  │  Connectors  │  │  MCP   │  │
│  │   SDK    │  │ (stmem)│  │  RSS/GitHub/ │  │ Server │  │
│  │          │  │        │  │  Slack/etc.  │  │ (:4001)│  │
│  └────┬─────┘  └────────┘  └──────────────┘  └────────┘  │
└───────┼───────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│              SpacetimeDB (:3001) — Rust/WASM                 │
│  memories · graph · sessions · profiles · facts · notes     │
│  directories · auth · RBAC · change history · replication    │
├──────────────────────────────────────────────────────────────┤
│  Sidecar: Embedder (:9090) — ONNX bge-m3 (1024d) │
│  Sidecar: Tantivy BM25 (:9091) — inverted-index keyword     │
│  Sidecar: spacetime-llm proxy (:4000) — bge-m3 → NVIDIA NIM │
└──────────────────────────────────────────────────────────────┘
```

The container starts **four services** in order:

| Order | Service | Port | Purpose |
|-------|---------|------|---------|
| 1 | SpacetimeDB standalone | 3001 | Core persistence engine (Rust/WASM) |
| 2 | Module publish | — | Publishes WASM module to STDB (if not already present) |
| 3 | ONNX Embedder | 9090 | Semantic embedding (bge-m3, 1024d) |
| 4 | Tantivy BM25 | 9091 | Keyword search with BM25 scoring |
| 5 | Frontend (static) | 5173 | React dashboard served via Python HTTP |

---

## Quick Start (One-Command Setup)

The repo includes a self-contained setup script that checks prerequisites,
starts SpacetimeDB (via Docker or native), publishes the module, installs the
SDK, and runs a health check:

```bash
# From the repo root:
bash scripts/setup.sh

# Or directly from GitHub:
curl -fsSL https://raw.githubusercontent.com/omiinaya/spacetime-memory/main/scripts/setup.sh | bash
```

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

---

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

This starts all services inside a single container (monolithic Docker image).
Data persists in named Docker volumes across restarts.

### Upgrade

```bash
git pull
docker compose up --build -d
```

See [Upgrades & Migrations](#upgrades--migrations) for version-sensitive upgrades.

---

## Native Installation

### Prerequisites

- Python 3.11+
- Rust toolchain with `wasm32-unknown-unknown` target
- Node.js 20+
- SpacetimeDB CLI v2.4+ (see `.spacetime-version`)

### 1. Install SpacetimeDB CLI

```bash
curl -fsSL https://github.com/clockworklabs/SpacetimeDB/releases/download/v2.6.1/spacetime-x86_64-unknown-linux-gnu.tgz \
  | tar xz -C /usr/local/bin/
spacetime version
```

### 2. Check `.spacetime-version` for the expected version

The file `.spacetime-version` at the repo root pins the expected STDB version.
Always match your CLI to this version to avoid schema compatibility issues.

### 3. Start STDB and publish the module

```bash
spacetime start --listen-addr 0.0.0.0:3001 --data-dir data/ &
cd server/spacetimedb
spacetime publish --project-path . spacetime-memory
```

### 4. Install Python SDK + CLI

```bash
pip install -e sdk/python
pip install -e cli
```

### 5. Start the Embedder (sidecar)

```bash
# Build the embedder
cd server/embedder && cargo build --release
./target/release/embedder &

# Or use the spacetime-llm proxy instead:
#   Ensure proxy is running with bge-m3 registered
#   Set env: EMBEDDER_URL=http://localhost:4000
```

### 6. Start Tantivy BM25 (sidecar)

```bash
# Build and start
cd server/tantivy-sidecar && cargo build --release
./target/release/tantivy-sidecar --warmup &

# The sidecar auto-reindexes via reindex-tantivy.py on startup
```

### 7. Build and serve the frontend

```bash
cd client
npm install
npm run build
python3 -m http.server 5173 --directory dist/ &
```

### 8. Configure

```bash
cp .env.example .env
# Edit .env with your settings
stmem --help
```

### 9. Safe Module Publishing (Recommended)

The repo includes `scripts/publish.sh` — a safe wrapper around `spacetime publish`
that **never deletes data**:

```bash
# Auto-detect STDB host and publish
./scripts/publish.sh

# Custom database name
./scripts/publish.sh my-production-db

# Custom host
STDB_HOST=127.0.0.1:3001 ./scripts/publish.sh
```

Key safety guarantees:
- **`--delete-data=never` hardcoded** — production data can never be accidentally dropped
- **Auto-detects STDB server** — finds the running `spacetimedb-standalone` process and its port
- **Builds WASM if missing** — no pre-built artifact required
- **Refuses to run with `DELETE_DATA` env var** — deliberate design to prevent script misuse

For native upgrades:
```bash
cd server/spacetimedb
cargo build --target wasm32-unknown-unknown --release
./scripts/publish.sh
```

### 10. Deploy the MCP Server

Spacetime Memory provides an MCP (Model Context Protocol) server at `server/mcp/main.py`
for AI agent integration. It is Python-based and uses the FastMCP framework:

```bash
# Install MCP server dependencies
pip install -r server/mcp/requirements.txt

# Install (if not already done)
pip install -e sdk/python

# Start with stdio transport (recommended for agent environments)
python server/mcp/main.py

# Start with SSE transport (requires MCP_API_KEY env var)
MCP_API_KEY=your-secret-key python server/mcp/main.py --transport sse --host 0.0.0.0 --port 8099
```

**Transport selection:**

| Transport | CLI flag | Use Case | Auth |
|-----------|----------|----------|------|
| stdio | --transport stdio (default) | Claude Code, Copilot, code editors | None (local) |
| SSE | --transport sse | Remote agents, multi-agent systems | MCP_API_KEY env var |
| Streamable HTTP | --transport streamable-http | HTTP-based agent integration | MCP_API_KEY env var |

The MCP server exposes SDK operations as tools: search, store, graph
management, workspace CRUD, and connector management.

### 11. Connector Daemon Deployment

Spacetime Memory includes a connector daemon (`scripts/run_connectors.py`) that
syncs external services (Discord, Notion, GitHub, Slack, X/Twitter, RSS,
webhooks) into the memory store. This is optional but useful for continuous
ingestion.

```bash
# Install connector dependencies
pip install -e "sdk/python[connectors]"

# Run all configured connectors (reads .env for API keys)
python scripts/run_connectors.py

# Run as a systemd service
# /etc/systemd/system/stmem-connectors.service
[Unit]
Description=Spacetime Memory Connector Daemon
After=network.target

[Service]
Type=simple
User=nobody
WorkingDirectory=/opt/spacetime-memory
ExecStart=/usr/bin/python3 /opt/spacetime-memory/scripts/run_connectors.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Connector configuration is documented in `docs/usage/connectors.md`.

### 12. CI/CD & Testing

**Pre-deployment Validation**

Before deploying a new version to production, run the full CI suite:

```bash
# Full local CI (Rust + Python + TypeScript + adapters)
make ci

# Run all Python tests (needs live STDB on :3001)
make test-all

# Run Rust unit tests (no STDB needed)
make test-rust

# Run frontend vitest
make test-frontend

# Run Playwright E2E tests (needs dev server running)
make test-e2e
```

**Version Pin Verification**

```bash
# Check that .spacetime-version matches the deployed STDB server
python scripts/check-version.py

# Expected output:
#   ✓ .spacetime-version = 2.6.1
#   ✓ Running STDB version = 2.6.1
```

**Performance Benchmarks**

Benchmarks are run against a live STDB instance. Results are captured in
`benchmarks.md` with JSON data in `benchmark_results_*.json`.

```bash
# Run the full benchmark suite
make bench
```

---

## What the Entrypoint Does

The Docker entrypoint (`scripts/docker-entrypoint.sh`) orchestrates a precise startup sequence:

1. **Start SpacetimeDB standalone** — launches the STDB server in the background
2. **Wait for STDB readiness** — polls TCP port 3001 (up to 30s)
3. **Publish the WASM module** — checks if the database already exists via `POST /v1/database/<name>`; if not found, publishes using `spacetimedb-cli publish` with the pre-built WASM at `/app/module/spacetime_memory.wasm`
4. **Start ONNX Embedder** — launches the embedder sidecar, waits for `/health` on port 9090 (up to 15s)
5. **Start Tantivy BM25** — launches the BM25 sidecar, waits for `/health` on port 9091 (up to 10s)
6. **Start Frontend** — serves the React build from `/app/frontend` on port 5173 (if index.html exists)
7. **Signal traps** — catches SIGTERM/SIGINT and shuts down in reverse order

Key property: **the module is only published if the database doesn't already exist**. This means restarting the container is safe — data is preserved in the volume.

---

## Configuration Reference

All configuration uses environment variables. Below is the complete mapping; see [CONFIG.md](CONFIG.md) for detailed descriptions.

### Core Connection

| Variable | Default | Description |
|----------|---------|-------------|
| `SPACETIMEDB_HOST` | `localhost` | SpacetimeDB hostname |
| `SPACETIMEDB_PORT` | `3001` | SpacetimeDB HTTP port |
| `SPACETIMEDB_DB` | `spacetime-memory` | Database identity |
| `STMEM_HOST` | `SPACETIMEDB_HOST` fallback | CLI-specific host override |
| `STMEM_PORT` | `SPACETIMEDB_PORT` fallback | CLI-specific port override |
| `STMEM_DB` | `SPACETIMEDB_DB` fallback | CLI-specific database override |
| `SPACETIMEDB_TOKEN` | *(none)* | JWT Bearer token for authenticated requests |

### Embedding

The embedding pipeline routes through the spacetime-llm proxy (to NVIDIA NIM).

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDER_URL` | `http://localhost:9090` | Embedder endpoint (local ONNX embedder or proxy) |
| `EMBEDDER_MODEL_PATH` | `/app/model/all-MiniLM-L6-v2.onnx` | Local ONNX model path (Docker) |
| `EMBEDDING_MODEL` | `bge-m3` | Model name for proxy-based embedding |
| `OPENAI_BASE_URL` | `http://localhost:4000/v1` | OpenAI-compatible API endpoint |
| `OPENAI_API_KEY` | *(none)* | API key for proxy/LLM |

### LLM

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_MODEL` | `gpt-4o-mini` | Model for synthesis/agent LLM calls |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | LLM endpoint |
| `OPENAI_API_KEY` | *(none)* | Required for LLM features |

### Frontend (Vite)

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_SPACETIMEDB_WS` | `ws://localhost:3001` | WebSocket endpoint for STDB |
| `VITE_SPACETIMEDB_HOST` | `localhost:3001` | HTTP host for dashboard |
| `VITE_SPACETIMEDB_DB` | `spacetime-memory` | Database for dashboard |

### Auth & Security

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_API_KEY` | *(none)* | Required for MCP HTTP/SSE transport auth |
| `SPACETIMEDB_TOKEN` | *(none)* | JWT for persistent HTTP identity |

### Backup

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKUP_S3_BUCKET` | `my-bucket` | S3 bucket for cloud backup |
| `BACKUP_S3_PREFIX` | `spacetime-backups` | S3 key prefix |

### Resilience

| Variable | Default | Description |
|----------|---------|-------------|
| `STMEM_MAX_RETRIES` | `3` | Max retries for connection/5xx errors (exponential backoff) |

### Docker-Specific

| Variable | Default | Description |
|----------|---------|-------------|
| `SPACETIMEDB_VERSION` | `2.6.1` | SpacetimeDB Docker image version |
| `SPACETIMEDB_PORT` | `3001` | Host port mapping |
| `SPACETIMEDB_DATA_DIR` | `/app/data` | Data directory inside container |

---

## Docker Compose Files

The repo contains **two** Compose files:

### `compose.yaml` (recommended)

Modern Compose format (v2.x). Single service with healthcheck, named volumes,
and env_file support. **Use this one for new deployments.**

```bash
docker compose up -d
```

Key features:
- Named volume `stmem-data` for database persistence
- Named volume `stmem-models` for ONNX model cache
- Healthcheck pings TCP port 3001
- `SPACETIMEDB_PORT` env var maps both container and host ports
- Frontend `VITE_*` env vars passed at runtime (overrides the build-time defaults)
- Exposes all four ports: 3001 (STDB), 9090 (embedder), 9091 (Tantivy), 5173 (frontend)

### `docker-compose.yml` (legacy)

Older v3.8 format from an earlier iteration. Exposes three ports (3001, 9090, 5173)
and uses a different model path. Kept for backward compatibility with deployments
that pinned this format.

**Migration:** Move to `compose.yaml` by copying your `.env` and volume names.
The data volume path structure is compatible.

---

## Production Hardening

### 1. Dedicated SpacetimeDB

For production, run SpacetimeDB as a **dedicated service** separate from the app:

```yaml
# docker-compose.prod.yml
services:
  spacetimedb:
    image: clockworklabs/spacetimedb:v2.6.1
    ports: ["3001:3001"]
    volumes: ["spacetime-data:/var/lib/spacetimedb"]
    command: ["start", "--listen-addr", "0.0.0.0:3001"]
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: "2"

  embedder:
    build:
      context: .
      dockerfile: Dockerfile
      target: embedder
    ports: ["9090:9090"]
    volumes: ["model-data:/app/model"]
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: "1"

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
    restart: unless-stopped
```

### 2. Persistent Volumes with Bind Mounts

For predictable data locations:

```yaml
volumes:
  spacetime-data:
    driver: local
    driver_opts:
      type: none
      device: /data/spacetime-memory
      o: bind
```

### 3. Reverse Proxy (TLS)

```nginx
# /etc/nginx/sites-available/spacetime-memory
server {
    listen 443 ssl;
    server_name memory.example.com;

    ssl_certificate /etc/letsencrypt/live/memory.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/memory.example.com/privkey.pem;

    # Frontend
    location / {
        proxy_pass http://127.0.0.1:5173;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket for SpacetimeDB
    location /ws/ {
        proxy_pass http://127.0.0.1:3001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }

    # STDB HTTP API
    location /api/ {
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

# HTTP → HTTPS redirect
server {
    listen 80;
    server_name memory.example.com;
    return 301 https://$host$request_uri;
}
```

### 4. Environment Security

- **Never commit `.env` files** with real credentials.
- Use a secrets manager (Vault, 1Password CLI, Docker secrets) for API keys.
- Rotate `MCP_API_KEY` regularly.
- Run the MCP server on stdio transport (not HTTP) inside agent environments.
- Restrict STDB port 3001 to internal network — never expose directly to the internet.

### 5. Firewall Rules

| Source | Dest Port | Purpose | Restrict To |
|--------|-----------|---------|-------------|
| Internet | 443 (nginx) | HTTPS dashboard | — |
| Internal | 3001 | STDB HTTP/WS API | App server, agents |
| Internal | 9090 | Embedder API | App server only |
| Internal | 9091 | Tantivy BM25 API | App server only |
| Internal | 5173 | Frontend | Reverse proxy only |
| Internal | 4000 | spacetime-llm proxy | App server only |

### 6. Container Restart Policies

```yaml
services:
  spacetimedb:
    restart: unless-stopped  # survives host reboots
  app:
    restart: on-failure:3    # retry 3 times on crash
```

### 7. Logging

Configure Docker logging driver for production:

```yaml
services:
  spacetimedb:
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

---

## Kubernetes Deployment

### Prerequisites

- Kubernetes 1.24+
- kubectl configured with cluster access
- PersistentVolume provisioner (for STDB data)

### Minimal Deployment

```yaml
# k8s-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: spacetime-memory
  labels:
    app: spacetime-memory
spec:
  replicas: 1
  selector:
    matchLabels:
      app: spacetime-memory
  template:
    metadata:
      labels:
        app: spacetime-memory
    spec:
      containers:
      - name: spacetime-memory
        image: spacetime-memory:latest
        imagePullPolicy: IfNotPresent
        ports:
        - containerPort: 3001
          name: stdb
        - containerPort: 9090
          name: embedder
        - containerPort: 9091
          name: tantivy
        - containerPort: 5173
          name: frontend
        env:
        - name: SPACETIMEDB_HOST
          value: "0.0.0.0"
        - name: SPACETIMEDB_PORT
          value: "3001"
        - name: SPACETIMEDB_DB
          value: "spacetime-memory"
        livenessProbe:
          tcpSocket:
            port: 3001
          initialDelaySeconds: 30
          periodSeconds: 15
        readinessProbe:
          tcpSocket:
            port: 3001
          initialDelaySeconds: 10
          periodSeconds: 10
        volumeMounts:
        - name: data
          mountPath: /app/data
        - name: models
          mountPath: /app/model
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: stmem-data
      - name: models
        persistentVolumeClaim:
          claimName: stmem-models
---
apiVersion: v1
kind: Service
metadata:
  name: spacetime-memory
spec:
  selector:
    app: spacetime-memory
  ports:
  - name: stdb
    port: 3001
    targetPort: 3001
  - name: embedder
    port: 9090
    targetPort: 9090
  - name: tantivy
    port: 9091
    targetPort: 9091
  - name: frontend
    port: 5173
    targetPort: 5173
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: stmem-data
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 10Gi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: stmem-models
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 2Gi
```

### Apply

```bash
kubectl apply -f k8s-deployment.yaml
```

### Ingress (TLS)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: spacetime-memory
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  ingressClassName: nginx
  tls:
  - hosts: [memory.example.com]
    secretName: stmem-tls
  rules:
  - host: memory.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: spacetime-memory
            port:
              number: 5173
```

---

## Upgrades & Migrations

### Schema Migration (safe)

When you update the WASM module with new tables or reducers:

1. **Back up data first** (see [Backup & Restore](#backup--restore))
2. Publish with `--delete-data=never`:

```bash
# Via Docker (re-build and restart — entrypoint skips publish if DB exists)
docker compose up --build -d

# Force re-publish if schema changed:
docker compose exec spacetime-memory \
  spacetimedb-cli publish --delete-data=never \
  -b /app/module/spacetime_memory.wasm spacetime-memory
```

3. Verify with `stmem doctor`

### STDB Version Upgrade

When upgrading the SpacetimeDB server version:

1. **Back up data** (export all workspaces)
2. Update `.spacetime-version` to the new version
3. Update version references in `Dockerfile`, `compose.yaml`, and `docker-compose.yml`
4. Stop the running STDB container/process
5. Start the new version — STDB handles internal data format migration automatically
6. Re-publish the WASM module (which must also be updated to match)

### Breaking Schema Changes

If the Rust module has incompatible schema changes (renamed tables, removed columns):

```bash
# WARNING: This deletes all data
cd server/spacetimedb
spacetime publish --delete-data=on-conflict spacetime-memory

# For unconditional wipe (disaster recovery):
spacetime publish --delete-data=always spacetime-memory
```

---

## Backup & Restore

### Automated Backup (Cron)

The repo includes a backup cron script:

```bash
# Daily backup at 2am (via systemd or crontab)
0 2 * * * /path/to/spacetime-memory/scripts/backup-cron.sh <workspace_id>
```

This:
- Exports workspace data to JSON in `data/backups/`
- Keeps only the last 7 backups
- Logs to a file for monitoring

### Manual Backup

```bash
# Export a single workspace
python scripts/backup.py export <workspace_id> --output backup.json

# Upload to S3
python scripts/backup.py s3-upload backup.json \
  --bucket my-bucket \
  --prefix spacetime-backups
```

### Restore

```bash
# Restore a workspace from backup
python scripts/backup.py import <workspace_id> backup.json

# The import replays create_note, create_node, create_edge calls
# to reconstruct the workspace. Existing data with the same IDs
# is silently updated.
```

### Full Disaster Recovery

For a complete system restore (new STDB server):

1. Start SpacetimeDB and publish the module
2. Install the SDK
3. For each workspace, run `backup.py import`
4. Run `stmem doctor` to verify all systems
5. Verify with `stmem cross-link --workspace <id>` to rebuild graph edges

### Backup Retention Policy

| Tier | Retention | Frequency | Location |
|------|-----------|-----------|----------|
| Local | 7 days | Daily | `data/backups/` |
| S3 | 30 days | Daily | Configurable bucket |
| Snapshot | Monthly | Manual | Volume snapshot |

---

## Monitoring & Health

### Health Endpoints

| Service | Endpoint | Expected Response |
|---------|----------|-------------------|
| SpacetimeDB | `GET /` on port 3001 | 200 (no body) |
| Embedder | `GET /health` on port 9090 | `{"status": "ok"}` |
| Tantivy BM25 | `GET /health` on port 9091 | `{"status": "ok"}` |
| Docker container | TCP port 3001 | Connection accepted |

### CLI Health Check

```bash
# Full system diagnostic
stmem doctor

Expected output:
  [✓] SpacetimeDB connectivity (localhost:3001)
  [✓] Database 'spacetime-memory' is published
  [✓] Embedder reachable (http://localhost:9090)
  [✓] Tantivy reachable (http://localhost:9091)
```

### Logs

```bash
# Docker
docker compose logs -f

# Native
tail -f /tmp/stdb.log            # SpacetimeDB
# Embedder and Tantivy log to their own stdout

# Verbose SDK logging
export VERBOSE=true
```

### Metrics

- **Docker**: `docker stats` for real-time resource usage
- **Native**: Use `htop`, `nvidia-smi` (if GPU), `ss -tlnp` for port checks
- **Production**: Integrate with Prometheus/node_exporter
- **SDK**: Set `VERBOSE=true` to see all HTTP requests with timing

### Alert Conditions

| Condition | Severity | Action |
|-----------|----------|--------|
| STDB port 3001 unreachable | Critical | Restart container/process |
| Embedder /health fails | High | Restart embedder sidecar |
| Tantivy /health fails | High | Restart tantivy-sidecar |
| Disk usage > 85% | Warning | Review retention, expand volume |
| Backup age > 48h | Warning | Check cron/systemd timers |

### Automated Alerting

A sidecar health watchdog is available at `scripts/sidecar_watchdog.py`:

```bash
# Quick check (exit code 0 = healthy, 1 = degraded)
python3 scripts/sidecar_watchdog.py

# JSON output (for programmatic consumption)
python3 scripts/sidecar_watchdog.py --json

# Verbose mode (includes success info)
python3 scripts/sidecar_watchdog.py --verbose
```

The watchdog checks `/health` on the embedder (port 9090) and Tantivy (port 9091).
Failure messages are written to **both stdout** (for cron/no-agent delivery) and
**stderr** (for systemd journal capture).

**Setup options:**

<details>
<summary><b>Hermes cronjob (recommended for Hermes users)</b></summary>

```bash
hermes cron create \
  --name "sidecar-watchdog" \
  --schedule "every 5m" \
  --script /path/to/spacetime-memory/scripts/sidecar_watchdog.py \
  --no-agent
```

- Healthy → empty stdout → silent (nothing sent)
- Sidecar down → stdout has failure message → delivered as alert
- Non-zero exit → error alert sent as fallback
</details>

<details>
<summary><b>Systemd timer (standalone deployment)</b></summary>

Create `/etc/systemd/system/spacetimememory-watchdog.service`:

```ini
[Unit]
Description=Spacetime Memory sidecar health watchdog
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/spacetime-memory/scripts/sidecar_watchdog.py
StandardOutput=journal
StandardError=journal
```

And `/etc/systemd/system/spacetimememory-watchdog.timer`:

```ini
[Unit]
Description=Run sidecar watchdog every 5 minutes
Requires=spacetimememory-watchdog.service

[Timer]
OnCalendar=*:0/5
Persistent=true

[Install]
WantedBy=timers.target
```

Enable: `systemctl enable --now spacetimememory-watchdog.timer`
</details>

<details>
<summary><b>Classic cron (any deployment)</b></summary>

```cron
*/5 * * * * /usr/bin/python3 /opt/spacetimemory/scripts/sidecar_watchdog.py || logger -t sidecar-watchdog "Sidecar health check FAILED"
```
</details>

---

## JWT Key Rotation

Spacetime Memory supports JWT key rotation for zero-downtime credential
rollover. The `scripts/rotate-keys.py` tool manages the full lifecycle.

### Generate a New Key

```bash
python scripts/rotate-keys.py generate --name "ecdsa-p256-2026-rotation-1"
```

This creates a new ECDSA P-256 key pair and registers it with the WASM module.

### List Registered Keys

```bash
python scripts/rotate-keys.py list
```

### Automated Rotation (Recommended)

```bash
python scripts/rotate-keys.py rotate --name "ecdsa-p256-2026-rotation-2"
```

The `rotate` command combines generate, register, and config update in one step.
Old keys remain trusted for token verification until explicitly revoked.

### Revoke a Compromised Key

```bash
python scripts/rotate-keys.py revoke <key_id>
```

### Purge Expired Keys

```bash
python scripts/rotate-keys.py purge
```

### Generating Tokens with a Specific Key

```python
from spacetime_memory.auth import generate_token
token = generate_token('data/id_ecdsa_pkcs8_<kid>.pem', key_id='<kid>')
```

The `kid` header in the JWT allows SpacetimeDB to identify which signing key
was used.

|---

## Connector Daemon Deployment

Spacetime Memory includes a connector daemon (`scripts/run_connectors.py`) that
syncs external services (Discord, Notion, GitHub, Slack, X/Twitter, RSS,
webhooks) into the memory store. This is optional but useful for continuous
ingestion.

```bash
# Install connector dependencies
pip install -e "sdk/python[connectors]"

# Run all configured connectors (reads .env for API keys)
python scripts/run_connectors.py

# Run as a systemd service
# /etc/systemd/system/stmem-connectors.service
[Unit]
Description=Spacetime Memory Connector Daemon
After=network.target

[Service]
Type=simple
User=nobody
WorkingDirectory=/opt/spacetime-memory
ExecStart=/usr/bin/python3 /opt/spacetime-memory/scripts/run_connectors.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Connector configuration is documented in `docs/usage/connectors.md`.

---

## CI/CD & Testing

### Pre-deployment Validation

Before deploying a new version to production, run the full CI suite:

```bash
# Full local CI (Rust + Python + TypeScript + adapters)
make ci

# Run all Python tests (needs live STDB on :3001)
make test-all

# Run Rust unit tests (no STDB needed)
make test-rust

# Run frontend vitest
make test-frontend

# Run Playwright E2E tests (needs dev server running)
make test-e2e
```

### Version Pin Verification

```bash
# Check that .spacetime-version matches the deployed STDB server
python scripts/check-version.py

# Expected output:
#   ✓ .spacetime-version = 2.6.1
#   ✓ Running STDB version = 2.6.1
```

### Performance Benchmarks

Benchmarks are run against a live STDB instance. Results are captured in
`benchmarks.md` with JSON data in `benchmark_results_*.json`.

```bash
# Run the full benchmark suite
make bench
```

---

## Network & Ports

### Complete Port Map

| Port | Service | Protocol | Exposed by Default | TLS Required |
|------|---------|----------|-------------------|--------------|
| 3001 | SpacetimeDB | HTTP + WebSocket | Yes | Recommended |
| 4000 | spacetime-llm proxy | HTTP | No | If external |
| 8099 | MCP Server (SSE) | HTTP + SSE | No | If external |
| 5173 | Frontend (static) | HTTP | Yes | Required |
| 9090 | ONNX Embedder | HTTP | Yes | Internal only |
| 9091 | Tantivy BM25 | HTTP | Yes | Internal only |
| 9092 | Prometheus metrics | HTTP | No | Internal only |

### Firewall Zones

```
Internet → [443] → nginx → [5173] Frontend
                        ↳ [3001] STDB (API)
                        ↳ [8099] MCP (agent API, optional)
Internal → [3001] STDB (agents)
Internal → [4000] spacetime-llm proxy (agents)
Internal → [8099] MCP (agents, internal)
Internal → [9090] Embedder (app only)
Internal → [9091] Tantivy (app only)
Internal → [9092] Prometheus (monitoring)
```

---

## Resource Requirements

### Docker (single container)

| Resource | Minimum | Recommended | Production |
|----------|---------|-------------|------------|
| CPU | 2 cores | 4 cores | 8 cores |
| RAM | 2 GB | 4 GB | 8 GB |
| Disk | 5 GB | 10 GB | 50 GB+ |

### Per-Component Breakdown

| Component | CPU | RAM | Disk | Notes |
|-----------|-----|-----|------|-------|
| SpacetimeDB | 1-2 cores | 1-2 GB | 1 GB + workspace data | Scales with memory count |
| ONNX Embedder | 1 core | 256-512 MB | 500 MB (model) | CPU-only by default |
| Tantivy BM25 | 0.5 core | 128-256 MB | 200 MB (index) | Scales with document count |
| Frontend | 0.1 core | 64 MB | 10 MB (static) | Stateless, negligible |
| spacetime-llm proxy | 0.5 core | 256 MB | 50 MB | Only if used instead of embedder |

### Storage Growth

| Data Type | Growth Rate (estimated) | Notes |
|-----------|-------------------------|-------|
| Memory entries | ~1 KB each | Scales with usage |
| Graph nodes | ~500 B each | Plus edges (~200 B each) |
| Tantivy index | ~2x raw text | Rebuilt on reindex |
| Backups | ~workspace size / day | 7-day local retention |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Connection refused: localhost:3001` | SpacetimeDB not running | Start it: `spacetime start --listen-addr 0.0.0.0:3001` or `docker compose up -d` |
| Embedder returns 500 | ONNX model not found | Run `bash scripts/download-model.sh` or check `EMBEDDER_MODEL_PATH` |
| Tantivy returns 500 | Index not initialized | Restart tantivy-sidecar with `--warmup` flag |
| `No module named 'spacetime_memory'` | SDK not installed | `pip install -e sdk/python` |
| Frontend shows blank page | Backend not reachable | Check `VITE_SPACETIMEDB_WS` in `.env` matches your STDB host |
| Authentication errors | `MCP_API_KEY` mismatch | Check key matches between client and server config |
| Memory search returns 0 results | Embedder down or model not loaded | Check `curl http://localhost:9090/health` |
| Module publish fails | STDB version mismatch | Verify `.spacetime-version` matches your STDB server version |
| Container exits immediately | Startup health check timed out | Check `docker logs` — one of 4 services failed to start |
| `POST /v1/database` returns 404 | Wrong STDB API version | Use `spacetimedb-cli publish` instead of direct API calls |
| WASM module not found | Docker build incomplete | Rebuild with `docker compose build --no-cache` |
| High memory usage | 4 services in one container | Split into dedicated services (see production hardening) |
| Backup script fails | Missing SDK deps | Activate venv: `source sdk/python/venv/bin/activate` |

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
│     Sidecar: Embedder (:9090)                │
│     ONNX bge-m3 (1024d)           │
├──────────────────────────────────────────────┤
│     Sidecar: Tantivy BM25 (:9091)            │
│     Inverted-index keyword search            │
├──────────────────────────────────────────────┤
│     Proxy: spacetime-llm (:4000)             │
│     bge-m3 → NVIDIA NIM (1024d)              │
└──────────────────────────────────────────────┘
```
