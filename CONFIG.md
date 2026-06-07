# Spacetime Memory — Configuration Reference

This document describes all environment variables used by the Spacetime Memory
system.  Variables are grouped by subsystem.

---

## Environment Variables

### SpacetimeDB Connection

| Variable | Default | Description |
|----------|---------|-------------|
| `SPACETIMEDB_HOST` | `localhost` | SpacetimeDB hostname |
| `SPACETIMEDB_PORT` | `3001` | SpacetimeDB HTTP port |
| `SPACETIMEDB_DB` | `spacetime-memory` *(auto)* | Database identity hex string (auto-detected in the SDK if omitted) |

### Embedder

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDER_URL` | `http://localhost:9090` | Embedder sidecar URL (Rust ONNX inference) |
| `EMBEDDER_TYPE` | `auto` | Embedder mode: `local`, `openai`, or `auto` (try local first, then fall back to OpenAI) |
| `EMBEDDER_MODEL_PATH` | `/app/model/all-MiniLM-L6-v2.onnx` | Path to ONNX model file (used in Docker) |
| `MODEL_PATH` | *(none)* | Alternative path to ONNX model file (local / non-Docker) |

### LLM Integration

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | *(none)* | OpenAI API key for LLM features and OpenAI embedder fallback |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible API endpoint (use for proxies / local LLMs) |
| `LLM_MODEL` | `gpt-4o-mini` | Model identifier for LLM synthesis features |

### Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_API_KEY` | *(none)* | API key for MCP server authentication (HTTP / SSE transport).  Not required for stdio transport.  When set, tools require `Authorization: Bearer <key>` on HTTP requests. |

### CLI Overrides

| Variable | Default | Description |
|----------|---------|-------------|
| `STMEM_HOST` | *(same as `SPACETIMEDB_HOST`)* | CLI-specific host override |
| `STMEM_PORT` | *(same as `SPACETIMEDB_PORT`)* | CLI-specific port override |
| `STMEM_DB` | *(same as `SPACETIMEDB_DB`)* | CLI-specific database override |
| `STMEM_PLUGIN_DIR` | *(see CLI)* | Directory for CLI plugins |

### Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `RUST_LOG` | `info` | Rust module log level (SpacetimeDB, embedder sidecar) |
| `LOG_LEVEL` | `WARNING` | Python SDK log level |

### Frontend (Vite)

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_SPACETIMEDB_WS` | `ws://localhost:3001` | WebSocket URL for SpacetimeDB (frontend) |
| `VITE_SPACETIMEDB_HOST` | `localhost:3001` | HTTP host:port for SpacetimeDB (frontend) |
| `VITE_SPACETIMEDB_DB` | *(same as `SPACETIMEDB_DB`)* | Database identity hex string (frontend) |

---

## Docker

One-command startup:

```bash
docker compose up --build
```

Services exposed on the host:

| Port | Service |
|------|---------|
| `3001` | SpacetimeDB |
| `9090` | Embedder (ONNX sidecar) |
| `5173` | Frontend (static HTTP server) |

Environment variables can be set in `docker-compose.yml` under the `environment:`
key, or via a `.env` file in the project root (see `.env.example`).

### Default Docker overrides

When running inside the Docker image, the following defaults differ from the
Python SDK defaults:

| Variable | Docker default | SDK default |
|----------|---------------|-------------|
| `SPACETIMEDB_HOST` | `0.0.0.0` | `localhost` |
| `EMBEDDER_MODEL_PATH` | `/app/model/all-MiniLM-L6-v2.onnx` | *(not set)* |

---

## Example `.env` file

```bash
# SpacetimeDB connection
SPACETIMEDB_HOST=localhost
SPACETIMEDB_PORT=3001
SPACETIMEDB_DB=c200f381695ed98be9b3fa689dd298cddff6212d35c46ae2a01999f921b88c82
EMBEDDER_URL=http://localhost:9090

# LLM / Embedder
OPENAI_API_KEY=sk-...
EMBEDDER_TYPE=auto

# MCP auth (optional — for HTTP transport)
MCP_API_KEY=my-secret-key

# Frontend
VITE_SPACETIMEDB_WS=ws://localhost:3001
VITE_SPACETIMEDB_HOST=localhost:3001
VITE_SPACETIMEDB_DB=c200f381695ed98be9b3fa689dd298cddff6212d35c46ae2a01999f921b88c82
```
