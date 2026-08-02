# SpacetimeDB Hermes Memory Plugin

Replaces Hermes built-in memory with the spacetime-memory module — a
SpacetimeDB-backed distributed memory system with:

- **Hybrid search** — semantic (vector) + keyword + temporal + graph
- **Knowledge graphs** — entity linking, communities, god nodes
- **Markdown notes** — wikilink backlinks, daily notes, full editor UI
- **User profiles** — static facts + dynamic context + preferences
- **Durable storage** — SpacetimeDB v2.6 with WASM reducers

## Requirements

- A running spacetime-memory SpacetimeDB module (`:3001`)
- The Rust ONNX embedder sidecar (`:9090`)

## Installation

```bash
# Link the plugin into Hermes
mkdir -p ~/.hermes/plugins
ln -s /path/to/spacetime-memory/plugins/hermes ~/.hermes/plugins/spacetime

# Set as active provider
hermes config set memory.provider spacetime

# (Optional) override defaults
hermes config set memory.spacetime_host otherhost
hermes config set memory.spacetime_port 3001
```

## Config

| Env var | Default | Description |
|---------|---------|-------------|
| `SPACETIMEDB_HOST` | localhost | SpacetimeDB host |
| `SPACETIMEDB_PORT` | 3001 | SpacetimeDB port |
| `SPACETIMEDB_DB` | spacetime-memory | Database name |
| `EMBEDDER_URL` | http://localhost:9090 | Embedder sidecar |

## Tools

- `spacetime_search` — semantic + keyword search across memories, notes, KG nodes
- `spacetime_store` — store durable facts with auto-embedding
- `spacetime_notes` — browse/search markdown notes with backlinks
- `spacetime_kg` — query knowledge graph nodes and edges
- `spacetime_profile` — get/set user profile with facts and preferences
