# Development Guide

## Project Layout

```
spacetime-memory/
├── server/
│   ├── spacetimedb/          # SpacetimeDB Rust module
│   ├── embedder/             # Rust ONNX embedder sidecar
│   └── mcp/                  # MCP server (Python)
├── sdk/
│   └── python/               # Python SDK
│       ├── spacetime_memory/
│       │   ├── client.py     # Low-level Client
│       │   ├── sdks/         # Drop-in adapters
│       │   │   ├── mem0.py
│       │   │   ├── honcho.py
│       │   │   ├── hindsight.py
│       │   │   ├── graphiti.py
│       │   │   ├── langchain.py
│       │   │   └── zep.py
│       │   └── ...
│       └── tests/            # Python test suite
├── cli/                      # Python CLI (stmem)
├── client/                   # React frontend
├── scripts/                  # Utility scripts
├── plugins/                  # Plugin system
└── docs/                     # Documentation
```

## Prerequisites for Development

- Rust toolchain (`cargo`, `rustup`)
- SpacetimeDB CLI v2.4+
- Python 3.10+
- Node.js 18+ (for frontend)

## Setting Up for Development

```bash
git clone https://github.com/omiinaya/spacetime-memory.git
cd spacetime-memory

# Install Python SDK in editable mode
pip install -e sdk/python

# Install dev dependencies
pip install pytest pytest-asyncio httpx
```

## Running Tests

```bash
cd sdk/python

# Run unit tests (no SpacetimeDB required)
pytest -m unit

# Run integration tests (requires SpacetimeDB)
pytest -m integration

# Run all tests
pytest
```

Test markers:

| Marker | Description |
|--------|-------------|
| `unit` | Tests that mock HTTP — no SpacetimeDB required |
| `integration` | Tests that need a running SpacetimeDB standalone |
| `embedder` | Tests that also need the ONNX embedder sidecar on :9090 |

## Building the SpacetimeDB Module

```bash
cd server/spacetimedb
cargo build --target wasm32-unknown-unknown
spacetime publish spacetime-memory -p ./ --yes
```

## Building the Embedder

```bash
cd server/embedder
cargo build --release
./target/release/embedder  # Listens on :9090
```

## Building the Frontend

```bash
cd client
npm install
cp .env.example .env
npm run dev
```

## Code Style

- Python: Follow [PEP 8](https://peps.python.org/pep-0008/) with type hints
- Rust: Follow standard Rust formatting (`rustfmt`)
- Frontend: TypeScript with React and shadcn/ui components

## Adding a New Adapter

1. Create `sdk/python/spacetime_memory/sdks/<name>.py`
2. Implement the adapter class matching the target library's API surface
3. Export it in `sdk/python/spacetime_memory/sdks/__init__.py`
4. Add tests in `sdk/python/tests/`
5. Document the adapter in `docs/usage/adapters.md`

## Building Documentation

```bash
pip install mkdocs mkdocs-material mkdocstrings
mkdocs serve    # Preview at http://localhost:8000
mkdocs build    # Build static site to site/
```

## Pull Request Process

1. Fork the repository
2. Create a feature branch
3. Write tests for any new functionality
4. Ensure all tests pass
5. Update documentation if needed
6. Open a pull request
