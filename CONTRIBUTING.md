# Contributing to Spacetime Memory

Thank you for your interest in contributing to Spacetime Memory! This project is a multi-layer memory infrastructure for AI agents built on SpacetimeDB.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How to Contribute](#how-to-contribute)
- [Development Setup](#development-setup)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [AI Agent Contributors](#ai-agent-contributors)
- [Getting Help](#getting-help)

## Code of Conduct

This project adheres to a simple principle: **be excellent to each other.** All contributors, whether human or AI, are expected to:

- Use welcoming and inclusive language
- Be respectful of differing viewpoints and experiences
- Accept constructive criticism gracefully
- Focus on what is best for the project
- Show empathy towards other community members

## How to Contribute

### Reporting Bugs

1. Check the [GitHub Issues](https://github.com/omiinaya/spacetime-memory/issues) for existing reports
2. Use the bug report template
3. Include: environment details (Python version, Rust version, SpacetimeDB version), steps to reproduce, expected vs actual behavior, logs if available

### Suggesting Features

1. Open a [feature request](https://github.com/omiinaya/spacetime-memory/issues/new)
2. Describe the problem you're solving, not just your proposed solution
3. Reference existing adapters or patterns if applicable

### Submitting Changes

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-change`)
3. Make your changes (see [Development Setup](#development-setup))
4. Write or update tests
5. Run the test suite
6. Run linters
7. Open a pull request against `main`

## Development Setup

### Prerequisites

- **Rust toolchain** (`cargo`, `rustup`) — install via [rustup.rs](https://rustup.rs/)
- **SpacetimeDB CLI v2.6+** — install via `spacetime version upgrade` or download from [releases](https://github.com/clockworklabs/SpacetimeDB/releases)
- **Python 3.10+** — check with `python --version`
- **Node.js 18+** (optional, for frontend development)

### Quick Start

```bash
git clone https://github.com/omiinaya/spacetime-memory.git
cd spacetime-memory
make setup                                            # Install SDK + build Rust module
spacetime start --listen-addr 0.0.0.0:3001 &         # Start SpacetimeDB
spacetime publish spacetime-memory -p server/spacetimedb/ --yes  # Deploy module
make test-unit                                        # Verify setup
```

For detailed development instructions, see [AGENTS.md](AGENTS.md) (Development Guide section) or [`docs/development.md`](docs/development.md).

### Available Make Targets

| Target | Description |
|--------|-------------|
| `make help` | List all targets |
| `make install-sdk` | Install Python SDK in editable mode |
| `make build-module` | Build Rust WASM module |
| `make start-stdb` | Start SpacetimeDB standalone (background) |
| `make test-unit` | Run unit tests (no STDB needed) |
| `make test` | Run full test suite (unit + integration) |
| `make test-rust` | Run Rust unit tests |
| `make test-frontend` | Run frontend vitest tests |
| `make ci` | Run full local CI pipeline |
| `make clean` | Clean build artifacts |
| `make smoke` | Run end-to-end smoke test |

## Pull Request Process

1. **Ensure tests pass** — `make test-unit` at minimum. Run `make test` or `make ci` if you have a live SpacetimeDB.
2. **Lint your code** — `ruff check .` for Python, `cargo fmt --check && cargo clippy` for Rust.
3. **Update documentation** — update `AGENTS.md` (agent schema/development guide), `docs/`, or `README.md` as appropriate.
4. **Add a CHANGELOG entry** (if applicable) — see `CHANGELOG.md` for format.
5. **Open the PR** against `main` with a clear title and description:
   - What does this change do?
   - Why is it needed?
   - How was it tested?
   - Are there any breaking changes?
6. **Address CI feedback** — the project runs 4 CI workflows (Rust, Rust Integration, Python SDK, Python Integration). Ensure all pass before requesting review.

## Coding Standards

### Python

- **PEP 8** enforced via [ruff](https://docs.astral.sh/ruff/) (line length 100, double quotes)
- **Type hints** on all function signatures (`from __future__ import annotations`)
- **Google-style docstrings** with `Args:`, `Returns:`, `Raises:`, `Example:`
- **Import order**: standard library → third-party → local, one blank line between groups
- **No bare `except:`** — catch specific exceptions
- **No `print()` in production** — use structured logging via `configure_logging()`

Configuration is in `sdk/python/pyproject.toml`.

### Rust

- **rustfmt** for formatting (`cargo fmt`)
- **clippy** for linting (`cargo clippy`)
- **All writes through reducers** — no raw SQL DML
- **All reads through `query_table` reducer** for private tables
- Use `ctx.timestamp` and `ctx.rng()` (not `SystemTime::now()` or `OsRng`)
- Return `Result<(), String>` from all reducers

### Commit Messages

```
<area>: <short imperative description>

<optional body explaining what and why, not how>
```

Area prefixes: `cli`, `sdk(client)`, `sdk(compounder)`, `server(replication)`, `server(knowledge_graph)`, `docs`, `ci`, `docker`, etc.

## AI Agent Contributors

> *Spacetime Memory is designed for AI agents — it only makes sense that AI agents help build it too.*

### Guidelines for AI Agents

1. **Read AGENTS.md first.** It contains both the wiki/schema conventions and the full development guide. It's the single source of truth for agent-accessible documentation.

2. **CLAUDE.md is a signpost only.** For detailed instructions, always refer to `AGENTS.md`. The CLAUDE.md file exists for IDE/agent tooling integration and contains critical rules and file references.

3. **Be honest about what works.** If you cannot run tests because no SpacetimeDB instance is available, say so. If the Rust module doesn't compile, report the errors. Never fabricate build or test output.

4. **Append to AGENTS.md, don't replace.** The development section is additive — it supplements the existing wiki/schema content. Both are essential.

5. **Use `make` targets** for build, test, and CI operations. The Makefile is the single source of truth for these workflows.

6. **Check CI first** before touching a file that has CI enforcement. The `.github/workflows/ci.yml` defines what gets validated on every PR.

7. **Update documentation as you go.** If you add a new CLI command, document it in `cli/stmem.py`'s help text and in `AGENTS.md`'s CLI Tools table. If you add a new reducer, document the corresponding Python method.

8. **Respect the adapter parity model.** When modifying a drop-in adapter, run `scripts/compare-upstream.py` (if available) to verify signature parity against the upstream library.

### What AI Agents Should NOT Do

- **Do not delete or restructure existing wiki/schema content in AGENTS.md** — the user-facing wiki documentation and the development guide serve different audiences. Append, don't restructure.
- **Do not modify CI workflows** without explicitly validating the YAML syntax and understanding the full pipeline.
- **Do not add dependencies** without updating `pyproject.toml`, `Cargo.toml`, or `setup.py` as appropriate.
- **Do not commit generated/build artifacts** — anything in `target/`, `__pycache__/`, `*.egg-info/`, `node_modules/` should be in `.gitignore`.

## Getting Help

- **GitHub Issues** — bug reports and feature requests
- **[AGENTS.md](AGENTS.md)** — agent wiki schema + development guide
- **[README.md](README.md)** — project overview and quick start
- **`docs/development.md`** — developer setup guide
- **`Makefile`** — all available build/test targets

---

*By contributing, you agree that your contributions will be licensed under the MIT License.*
