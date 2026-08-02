# Self-Hosted Deployment

Deploy Spacetime Memory using Docker for a fully containerized setup.

## Quick Start

```bash
docker compose up --build
```

This starts everything:

- **SpacetimeDB** on port `3001`
- **ONNX Embedder** on port `9090`
- **Frontend** on port `5173`

Open [http://localhost:5173](http://localhost:5173) after startup completes.

## Docker Compose Configuration

```yaml
# docker-compose.yml
version: "3.8"

services:
  spacetime-memory:
    build: .
    ports:
      - "3001:3001"   # SpacetimeDB
      - "9090:9090"   # ONNX Embedder
      - "5173:5173"   # Frontend (static HTTP server)
    volumes:
      - spacetime-data:/app/data  # Persist SpacetimeDB data
    environment:
      - RUST_LOG=info
      - SPACETIMEDB_HOST=0.0.0.0
      - SPACETIMEDB_PORT=3001
      - SPACETIMEDB_DB=spacetime-memory
      - EMBEDDER_MODEL_PATH=/app/model/all-MiniLM-L6-v2.onnx

volumes:
  spacetime-data:
```

## Dockerfile Structure

The multi-stage Docker build (`Dockerfile`) consists of four stages:

1. **Embedder Builder** — Compiles the Rust ONNX embedder sidecar
2. **Module Builder** — Builds the SpacetimeDB WASM module
3. **Frontend Builder** — Builds the Vite + React + TypeScript frontend
4. **Runtime** — Python 3.11-slim base with all components

### What the Runtime Includes

- SpacetimeDB CLI v2.6 standalone binary
- Python SDK installed as an editable package
- Python CLI (`stmem`)
- Rust ONNX embedder binary (all-MiniLM-L6-v2, 384d)
- ONNX embedding model (auto-downloaded at build time)
- SpacetimeDB WASM module
- Frontend static build (served by a simple HTTP server)
- JWT key generation (auto-generated if not present)
- Configurable logging via `config.toml`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SPACETIMEDB_HOST` | `0.0.0.0` | SpacetimeDB listen address |
| `SPACETIMEDB_PORT` | `3001` | SpacetimeDB port |
| `SPACETIMEDB_DB` | `spacetime-memory` | Database identity |
| `EMBEDDER_MODEL_PATH` | `/app/model/all-MiniLM-L6-v2.onnx` | Path to embedding model |
| `RUST_LOG` | `info` | Rust logging level |

## Data Persistence

SpacetimeDB data persists to the `spacetime-data` Docker volume mounted at `/app/data`. This includes:

- Database files
- JWT signing keys (`id_ecdsa_pkcs8.pem`, `id_ecdsa.pub`)
- Configuration (`config.toml`)

## Manual Deployment

If you prefer not to use Docker, follow the [Getting Started](../getting-started.md) guide for a manual setup.
