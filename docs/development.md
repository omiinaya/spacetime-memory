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
├── scripts/                  # Utility scripts (replication_daemon, mental_model_synthesis, etc.)
├── plugins/                  # Plugin system
└── docs/                     # Documentation
    ├── development.md        # This file
    ├── replication.md        # Replication setup guide
    └── adapter-authoring-guide.md  # How to write drop-in adapters
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

### Writing Tests

- **Unit tests:** Mock `httpx.Client` to avoid real network calls.
  See `tests/test_client.py` for examples.
- **Integration tests:** Require `spacetime start` (standalone).  Use the
  `pytest.mark.integration` decorator.
- Place adapter tests in `tests/test_adapters/` — one file per adapter.

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

- **Python:** Follow [PEP 8](https://peps.python.org/pep-0008/) with type hints.
  The SDK uses `from __future__ import annotations` throughout.
- **Rust:** Follow standard Rust formatting (`rustfmt`).  Run `cargo fmt`
  before committing.
- **Frontend:** TypeScript with React and shadcn/ui components.
- **Documentation:** Markdown files in `docs/`.  Use `mkdocs` for the
  rendered site (see below).

### Python Style Conventions

- Type-annotate all function signatures and public module-level variables.
- Use `def _private()` for internal helpers.
- Docstrings: Google-style with `Args:`, `Returns:`, `Example::` sections.
- Prefer `pathlib.Path` over `os.path` in new code.
- Group imports: standard library → third-party → local.

## Adding a New Adapter

See the **[Adapter Authoring Guide](adapter-authoring-guide.md)** for a
detailed walkthrough.

Quick checklist:
1. Create `sdk/python/spacetime_memory/sdks/<name>.py`
2. Subclass or wrap the target library's API surface
3. Export it in `sdk/python/spacetime_memory/sdks/__init__.py`
4. Add tests in `sdk/python/tests/`
5. Document the adapter in `docs/adapter-authoring-guide.md`

## Adding a New Reducer (Server-Side)

1. Define the reducer function in the appropriate server Rust file
   (e.g. `server/spacetimedb/src/memory.rs`).
2. Annotate with `#[reducer]`.
3. Add a corresponding method in the Python `Client` class
   (`sdk/python/spacetime_memory/client.py`).
4. Wire up a CLI command in `cli/stmem.py` using `client._call()`.
5. Test via `pytest` (unit mock for the reducer call).

## Building Documentation

```bash
pip install mkdocs mkdocs-material mkdocstrings

# Preview
mkdocs serve    # http://localhost:8000

# Build static site
mkdocs build    # Output to site/
```

### Documentation Conventions

- Each major subsystem gets its own `.md` file in `docs/`.
- CLI commands are documented with their full `stmem` invocation.
- Reducer tables and methods use Markdown tables for quick reference.
- Code examples use fenced code blocks with language tags.

## Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-change`)
3. Write tests for any new functionality
4. Ensure all tests pass (`pytest`)
5. Run the linter: `ruff check .` (Python), `cargo clippy` (Rust)
6. Update documentation if needed
7. Open a pull request against `main`
8. Ensure CI passes (GitHub Actions)

### Commit Message Style

```
<area>: <short description>

<optional body explaining what and why, not how>
```

Examples:
- `cli: add replication add-peer command`
- `sdk(client): add get_memory_history method`
- `server(replication): handle conflict resolution on insert`

## CI / GitHub Actions

The project uses GitHub Actions for:

| Workflow | Trigger | What it does |
|----------|---------|-------------|
| Python SDK tests | PR, push to main | Runs `pytest` (unit + integration markers) |
| Rust build | PR, push to main | Builds the SpacetimeDB module + embedder |
| Lint | PR, push to main | `ruff check`, `cargo fmt --check`, `cargo clippy` |
| Docs build | PR, push to main | `mkdocs build` — verifies no broken links |

## Release Process

1. Update version in `sdk/python/pyproject.toml` and `cli/stmem.py`
2. Run full test suite
3. Tag the release: `git tag v0.x.x`
4. Push tag: `git push origin v0.x.x`
   - GitHub Actions builds and publishes the Python package to PyPI
5. Write release notes summarising changes since last tag
