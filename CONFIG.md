# Configuration Reference

All configuration is done via environment variables. There is no configuration
file — set these in your shell, Docker `--env`, or `.env` file.

## Connection

| Variable | Default | Description |
|----------|---------|-------------|
| `SPACETIMEDB_HOST` | `localhost` | SpacetimeDB hostname or IP |
| `SPACETIMEDB_PORT` | `3001` | SpacetimeDB HTTP port |
| `SPACETIMEDB_DB` | `spacetime-memory` | Database name/identity hex |
| `STMEM_HOST` | `SPACETIMEDB_HOST` fallback | CLI-specific host override |
| `STMEM_PORT` | `SPACETIMEDB_PORT` fallback | CLI-specific port override |
| `STMEM_DB` | `SPACETIMEDB_DB` fallback | CLI-specific database override |

The `STMEM_*` vars take priority over `SPACETIMEDB_*` in the CLI (`stmem`).
The SDK (`Client()`) only reads `SPACETIMEDB_*` vars.

## Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `SPACETIMEDB_TOKEN` | *(none)* | JWT Bearer token for authenticated requests. Passed as `Authorization: Bearer <token>` header. Generate with `spacetime_memory.auth.generate_token()`. |

Without a token, SpacetimeDB assigns ephemeral HTTP identities per request
— persistent identity requires JWT.

## Embedder (Semantic Search)

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDER_URL` | `http://localhost:4000` | URL of the spacetime-llm proxy (health check) |
| `OPENAI_API_KEY` | *(none)* | API key for proxy embedding and LLM calls |
| `OPENAI_BASE_URL` | `http://localhost:4000/v1` | OpenAI-compatible API endpoint (local proxy) |
| `EMBEDDING_MODEL` | `baai/bge-m3` | Embedding model name (routed through proxy → NVIDIA NIM) |

The proxy at `localhost:4000` forwards embedding requests to NVIDIA NIM (bge-m3, 1024-dim).
Set `OPENAI_API_KEY` to authenticate with the proxy.

## Retry & Resilience

| Variable | Default | Description |
|----------|---------|-------------|
| `STMEM_MAX_RETRIES` | `3` | Max retry attempts for connection/timeout/5xx errors. Exponential backoff (0.5s, 1s, 2s, …). SpacetimeDB 530 (application error) is NOT retried. |

## LLM (Mental Model Synthesis & Context Agent)

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | *(none)* | Required for LLM calls (mental model synthesis, context agent). |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL. Set to a local proxy or self-hosted endpoint. |
| `LLM_MODEL` | `gpt-4o-mini` | Model name for synthesis/agent LLM calls. |

## Backup

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKUP_S3_BUCKET` | `my-bucket` | S3 bucket for cloud backup (`scripts/backup.py`). |
| `BACKUP_S3_PREFIX` | `spacetime-backups` | S3 key prefix for cloud backup. |

## Plugin System

| Variable | Default | Description |
|----------|---------|-------------|
| `STMEM_PLUGIN_DIR` | `~/.stmem/plugins/` | Directory for plugin discovery (CLI only). |

## Hermes Integration Plugin

| Variable | Default | Description |
|----------|---------|-------------|
| `SPACETIMEDB_HOST` | `localhost` | Same as above — Hermes plugin reads from SDK defaults. |
| `SPACETIMEDB_PORT` | `3001` | |
| `SPACETIMEDB_DB` | `spacetime-memory` | |
| `EMBEDDER_URL` | `http://localhost:9090` | |

## SDK Client Constructor

All env vars can be overridden by passing constructor arguments to `Client()`:

```python
from spacetime_memory import Client

client = Client(
    host="127.0.0.1",
    port=3001,
    database="my-db",
    embedder_url="http://127.0.0.1:9090",
    embedder_type="local",
    token="eyJ...",
    verbose=True,
)
```

## Quick Start

```bash
# Minimal (local SpacetimeDB, no auth)
export SPACETIMEDB_HOST=localhost
export SPACETIMEDB_PORT=3001

# With JWT auth
export SPACETIMEDB_TOKEN=$(python -c "
from spacetime_memory.auth import generate_token
print(generate_token('data/id_ecdsa_pkcs8.pem'))
")

# With embedder
export EMBEDDER_URL=http://localhost:9090
export EMBEDDER_TYPE=auto
export OPENAI_API_KEY=sk-...
```
