# Spacetime Memory — CLAUDE.md

> *Signpost for AI agents working on this project.*

## One-Line Setup

```bash
git clone https://github.com/omiinaya/spacetime-memory.git && cd spacetime-memory && make setup
```

## Read This First

**[AGENTS.md](AGENTS.md)** is the authoritative guide for this project. It covers:
- Wiki/schema layer — how to use the memory system as an agent
- Development guide — workspace layout, build/test commands, code conventions, workflows, task-to-file mapping, CI pipeline

All agent-accessible documentation lives at:
- `AGENTS.md` — Agent schema + development guide (primary, always up to date)
- `docs/development.md` — Developer setup guide (legacy, maintained for consistency)
- `Makefile` — Build/test/CI targets (single source of truth for commands)
- `README.md` — Project overview, setup, feature docs
- `ROADMAP.md` — Honest project assessment and strategic planning

## Critical Rules

1. **Never fabricate test results or compilation status.** The Rust module may not compile against SpacetimeDB v2.6 API changes — report reality.
2. **Always run `make test-unit`** before opening a PR. Skip integration tests if no live STDB is available.
3. **Lint before committing:** `ruff check .` (Python), `cargo fmt --check && cargo clippy` (Rust).
4. **Append to AGENTS.md, don't replace.** The wiki/schema content and development sections are both essential — keep them together.
5. **Use `make` targets** for build/test/CI rather than raw commands unless you need a specific flag.
6. **CI is defined in `.github/workflows/ci.yml`** — 4 workflows (Rust, Rust Integration, Python SDK, Python Integration).

## Key Files

| File | Purpose |
|------|---------|
| `sdk/python/spacetime_memory/client.py` | Core Python SDK (~247 unit tests) |
| `sdk/python/spacetime_memory/compounder.py` | Knowledge Compounder (LLM Wiki ingestion) |
| `cli/stmem.py` | CLI tool (37 subcommands) |
| `server/spacetimedb/src/lib.rs` | Rust module entrypoint (~162 reducers) |
| `server/mcp/main.py` | MCP server (133+ tools) |
| `AGENTS.md` | **This file** — agent wiki schema + development guide |
| `Makefile` | Build/test/CI targets |
