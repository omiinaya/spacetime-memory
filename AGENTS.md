---
name: SpacetimeMemory
description: "Multi-layer memory infrastructure for AI agents on SpacetimeDB — knowledge graphs, vector memory, user profiles, hybrid retrieval"
stack: [rust, python]
ports:
  stdb: 3001
  prometheus: 9090
deps: [cargo, python3, wasm32, spacetime]
stdb: true
---

# Spacetime Memory — Agent Schema

> *How an agent maintains a persistent, compounding wiki using Spacetime Memory.*

For Claude Code specifically, also see [CLAUDE.md](./CLAUDE.md).

This document is the **schema layer** from the [LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
It tells the agent how the wiki is structured, what conventions to follow, and
what workflows to use when ingesting sources, answering questions, or maintaining
the knowledge base.

---

## Three Layers

| Layer | What | Who writes | Who reads |
|-------|------|-----------|-----------|
| **Raw sources** | Immutable source documents (`raw/` directory). Articles, papers, transcripts, data files. | You (curator) | Agent |
| **The wiki** | SpacetimeDB notes + knowledge graph. Markdown notes, LLM-written summaries, entity pages, concept pages, comparisons, overviews. | Agent | You |
| **Schema** | This file — conventions, workflows, page formats. | You + Agent (co-evolved) | Agent |

---

## How the wiki is stored

Two parallel stores in SpacetimeDB:

### Notes (`create_note`, `update_note`, `_query("note", ...)`)
Rich markdown pages. Every page has:
- `title` — concise, human-readable
- `content` — markdown body with `[[wiki-links]]` to other notes where relevant
- `embed` — true for semantic searchability

### Knowledge Graph (`create_node`, `create_edge`, `_query("kg_node", ...)`)
Entities extracted from sources and notes. Every node has:
- `label` — entity name
- `node_type` — one of: `code`, `concept`, `entity`, `document`, `topic` (the module **only** accepts these five values — verified via reducer error message; do not use `person`/`org`/`product`/`location`/`event`)
- `summary` — 2-3 sentence LLM-written description, kept up to date via ripple updates

Edges connect nodes with typed relations: `informed_by`, `related_to`, `contradicts`, `supports`, `part_of`.

### System pages
- `_index` — catalog of all wiki pages, grouped by category
- `_log` — chronological record of what happened and when

---

## Conventions

### Note titles
- Title case for entity/concept pages: `"Reinforcement Learning from Human Feedback"`
- Question form for answer pages: `"What is RLHF?"`
- System pages prefixed with underscore: `_index`, `_log`

### Markdown style
- Use `##` for section headers within pages
- Use `[[Wiki Links]]` to cross-reference other notes — the agent should parse these when they appear in existing notes and create edges
- Include a `---` separator before the auto-generated footer
- YAML frontmatter is optional but encouraged for Dataview compatibility:

```yaml
---
type: entity | concept | comparison | synthesis | source-summary
tags: [topic1, topic2]
sources: [note_id_1, note_id_2]
created: 2026-06-22
---
```

### Log entries
Use parseable prefix: `## [YYYY-MM-DD HH:MM UTC] event_type | detail`
This makes the log grep-able with unix tools.

### Index entries
Each entry: `- [Title](note_id) — one-line summary`

---

## Workflows

### 1. Ingest a Source (`client.compounder.ingest_source()`)

When you add a new source document (article, paper, transcript):

1. **Read** the source document
2. **Summarize** — create a source-summary note
3. **Extract entities** — find all named entities and create KG nodes for new ones
4. **Link** — connect entities to the source summary with `informed_by` edges
5. **Ripple update** — if existing entities gained new information, merge it into their node summaries
6. **Cross-reference** — check if the new source contradicts existing knowledge (proactive contradiction check)
7. **Index** — append to `_index`
8. **Log** — append to `_log`

### 2. Answer a Query

1. **Search** — `client.search()` or `spacetime_search()` to find relevant memories, notes, and KG nodes
2. **Synthesize** — read the matched pages and compose an answer with citations
3. **File answers** — if the answer is valuable (analysis, comparison, connection), call `compounder.store_answer()` to persist it as a new wiki page
4. **Log** — append to `_log`

### 3. Health-Check / Lint

Run `compounder.lint_workspace()` periodically (weekly or after every ~10 ingests):
- **Orphans** — KG nodes with no edges, candidates for linking or cleanup
- **Missing cross-refs** — notes mentioning entities but lacking KG edges
- **Contradictions** — (LLM-powered) pairs of semantically similar memories with conflicting claims

### 4. Maintain

- **Ripple updates** — when new information arrives for an existing entity, merge it into the node summary rather than replacing
- **Cross-link** — `compounder.cross_link()` finds related but unconnected memories and creates edges
- **Suggest connections** — `compounder.suggest_connections()` identifies node pairs that share neighbours but aren't directly linked

---

## CLI Tools

### Available via the client SDK

| Operation | Method | Description |
|-----------|--------|-------------|
| Store answer | `compounder.store_answer(query, answer, ...)` | Persist an LLM synthesis as a wiki page |
| Cross-link | `compounder.cross_link(workspace_id)` | Auto-link related but unconnected memories |
| Suggest connections | `compounder.suggest_connections(workspace_id)` | Find node pairs that should be linked |
| Lint | `compounder.lint_workspace(workspace_id, ...)` | Health-check: orphans, crossrefs, contradictions |
| Export | `compounder.export_workspace(output_dir, ...)` | Export wiki as markdown files for Obsidian/git |
| Overview | `compounder.generate_overview_page(workspace_id)` | Generate _overview with stats, entities, activity |
| Search | `client.search(workspace_id, query, ...)` | Semantic + keyword search across all stores |
| Create note | `client.create_note(workspace_id, title, content, ...)` | Add a wiki page |
| Create node | `client.create_node(workspace_id, label, node_type, ...)` | Add a KG entity |
| Create edge | `client._call("create_edge", [workspace_id, src, tgt, ...])` | Link two nodes |
| Entity page | `compounder.create_entity_page(name, description, ...)` | Structured entity wiki page + KG node |
| Update entity page | `compounder.update_entity_page(name, ...)` | Update existing entity wiki page + KG node |
| Concept page | `compounder.create_concept_page(concept, definition, ...)` | Concept definition with [[wiki-links]] |
| Comparison page | `compounder.create_comparison_page(title, items, ...)` | Markdown comparison table |

### Available via CLI

All compounder SDK methods have terminal equivalents via `stmem`:

| SDK Method | CLI Command |
|-----------|-------------|
| `compounder.store_answer()` | `stmem store-answer --query "..." --answer "..."` |
| `compounder.cross_link()` | `stmem cross-link --workspace <id>` |
| `compounder.suggest_connections()` | `stmem suggest-connections --workspace <id>` |
| `compounder.lint_workspace()` | `stmem lint --workspace <id>` |
| `compounder.export_workspace()` | `stmem export markdown ./path/ --workspace <id>` |
| `compounder.generate_overview_page()` | `stmem overview --workspace <id>` |
| `compounder.ingest_source()` | `stmem ingest file --path article.txt` |
| `compounder.create_entity_page()` | `stmem entity-page --name "..." --description "..."` |
| `compounder.update_entity_page()` | `stmem update-entity-page --name "..." --description "..."` |
| `compounder.create_concept_page()` | `stmem concept-page --concept "..." --definition "..."` |
| `compounder.create_comparison_page()` | `stmem comparison-page --title "..." --items "a,b"` |
| `compounder.search_entities()` | `stmem search-entities --label "..." --type concept --query "..."` |

All CLI commands support `--output json` for machine-readable output.

### Available via MCP tools

When the agent is connected via MCP (``stmem serve``), these tools are
automatically available without importing the SDK:

| Tool | What it does |
|------|-------------|
| `ingest_source` | Full LLM Wiki ingest: summarize, extract entities, create KG nodes, link, ripple, check contradictions |
| `create_entity_page` | Create entity wiki page + KG node with YAML frontmatter |
| `update_entity_page` | Update existing entity wiki page + KG node |
| `create_concept_page` | Create concept definition page with [[wiki-links]] |
| `create_comparison_page` | Create comparison page with markdown table |
| `lint_workspace` | Health-check: orphans, missing crossrefs, contradictions |
| `generate_overview` | Generate workspace overview/synthesis page |
| `store_answer` | Persist an LLM answer as a wiki page |
| `search_entities` | Search KG entities by label, type, or semantic query |

---

## Tips

- **Git** — the wiki is just data in a database, but notes can be exported to markdown files for Obsidian / git version control
- **Obsidian** — the graph view is the best way to see the shape of your wiki: hubs, orphans, clusters
- **Dataview** — if notes have YAML frontmatter, Dataview can generate dynamic tables and lists in Obsidian
- **Marp** — markdown slide decks can be generated directly from wiki pages

---

> *The tedious part of maintaining a knowledge base is the bookkeeping. LLMs don't get bored, don't forget to update a cross-reference, and can touch 15 files in one pass. The wiki stays maintained because the cost of maintenance is near zero.*

---

# Development Guide for Agent Contributors

> *This section tells AI agents how to develop, build, test, and contribute to the Spacetime Memory project itself — not how to use the wiki.*

## Workspace Layout

```
spacetime-memory/
├── server/
│   ├── spacetimedb/              # SpacetimeDB Rust WASM module
│   │   ├── src/lib.rs            # Module entrypoint, ~162 reducers
│   │   ├── src/memory.rs         # Memory CRUD reducers
│   │   ├── src/knowledge_graph.rs # KG node/edge/community reducers
│   │   ├── src/note.rs           # Note/wikilink reducers
│   │   ├── src/query.rs          # Search and query reducers
│   │   ├── src/hybrid_query.rs   # Multi-strategy search fusion
│   │   ├── src/replication.rs    # CDC / delta sync
│   │   ├── src/consolidation.rs  # Dedup, decay, maintenance
│   │   ├── src/change_event.rs   # Change tracking
│   │   ├── src/retrieval.rs      # Retrieval helpers
│   │   └── Cargo.toml            # Rust deps (spacetimedb v2.6, serde, sha2, etc.)
│   ├── tantivy-sidecar/          # BM25 full-text search sidecar (Rust, port 9091)
│   └── mcp/                      # MCP server (Python, 133+ tools)
├── sdk/
│   └── python/                   # Python SDK + CLI + MCP
│       ├── spacetime_memory/
│       │   ├── client.py         # Core Client (~247 unit tests, 2488+ lines)
│       │   ├── compounder.py     # Knowledge Compounder (LLM Wiki ingestion)
│       │   ├── sdks/             # 6 drop-in adapters (mem0, zep, graphiti, etc.)
│       │   ├── agent_orchestrator.py
│       │   └── metrics.py / tracer.py  # Observability
│       ├── tests/                # ~3,319 collected tests
│       ├── pyproject.toml        # Build config, ruff/pytest settings
│       └── setup.py              # Legacy setup (kept for compat)
├── cli/
│   └── stmem.py                  # CLI tool (37 subcommands, 3509 lines)
├── client/                       # React frontend (optional)
├── scripts/                      # Benchmarks, eval, replication daemon
├── docs/                         # Documentation (development.md, api/, usage/)
├── tests/                        # Top-level integration tests
└── data/                         # Runtime data (tantivy indexes, eval data)
```

## Build Commands

| Command | What | When |
|---------|------|------|
| `make build-module` | Build Rust WASM module (release) | After changing `server/spacetimedb/src/` |
| `make install-sdk` | `pip install -e sdk/python` | First setup, after pulling new deps |
| `make setup` | install-sdk + build-module | Fresh clone setup |
| `spacetime publish <name> -p server/spacetimedb/ --yes --delete-data=never` | Deploy module to STDB | After a successful build |
> **⚠️ DATA SAFETY:** Always use `--delete-data=never`. The script `./scripts/publish.sh` enforces this automatically. Never use `--delete-data=on-conflict` — it silently wipes production data on schema changes. Never use `--delete-data=always` unless you've verified a backup exists and explicitly intend to reset. Schema changes are governed by [SCHEMA_EVOLUTION_POLICY.md](SCHEMA_EVOLUTION_POLICY.md) — additive fields with reducer-level defaults, **no migrations** (see the policy's 5-step rule and its Related Documents).
| `cd server/spacetimedb && cargo build --target wasm32-unknown-unknown --release` | Raw cargo build | Debugging Rust compilation |
| `cd sdk/python && pip install -e ".[dev]"` | Install dev extras (pytest, ruff) | Before running tests/lint |

## Test Commands

| Command | Scope | Requires STDB? |
|---------|-------|:--------------:|
| `make test-unit` | Python unit tests (`-m unit`) | ❌ No |
| `make test` | Full suite (unit + integration) | ✅ Yes (:3001) |
| `make test-integration` | Integration tests only | ✅ Yes (:3001) |
| `make test-rust` | Rust `cargo test --lib` | ❌ No (host target) |
| `make test-all` | ALL Python tests (no filter) | ✅ Yes |
| `make test-frontend` | Frontend vitest | ❌ No |
| `make test-e2e` | Playwright E2E | ✅ Yes |
| `make smoke` | E2E smoke test | ✅ Yes (:3001) |
| `make ci` | Full local CI (Rust + Python + TS) | Varies |
| `make bench` | Performance benchmark | ✅ Yes (+ embedder) |
| `pytest -m unit -v` | Quick unit test pass | ❌ No |

**Test markers** (defined in `sdk/python/pyproject.toml`):
- `unit` — Mocks HTTP, no SpacetimeDB needed
- `integration` — Requires a running SpacetimeDB on `localhost:3001`
- `embedder` — Also needs the embedding sidecar on `:9090`

## Code Conventions

### Python
- **PEP 8** with ruff formatter (line length 100, double quotes)
- **Type hints** on every function signature (`from __future__ import annotations`)
- **Google-style docstrings** with `Args:`, `Returns:`, `Raises:`, `Example:` sections
- **Imports**: stdlib → third-party → local, one blank line between groups
- **Prefer** `pathlib.Path` over `os.path`
- **Private helpers** use `def _name()` convention
- **No bare `except:`** — catch specific exceptions or use `except Exception:`
- **No `print()`** in production — use `logger` from `configure_logging()`

### Rust
- Standard `rustfmt` formatting — run `cargo fmt` before committing
- Run `cargo clippy` for lint
- Writes through reducers only (no raw SQL DML)
- Reads through `query_table` reducer for private tables
- Use `ctx.timestamp` (not `SystemTime::now()`), `ctx.rng()` (not `OsRng`)
- Return `Result<(), String>` from all reducers

### Commit Messages
```
<area>: <short imperative description>

<optional body explaining what and why, not how>
```
Examples: `cli: add replication add-peer command`, `sdk(client): add get_memory_history method`, `server(replication): handle conflict resolution on insert`

## Developer Workflow

### Adding a New Reducer (Server-Side)
1. Define the `#[reducer]` function in the appropriate Rust file (e.g. `memory.rs`)
2. Build: `make build-module`
3. Publish: `spacetime publish <name> -p server/spacetimedb/ --yes --delete-data=never`
4. Add a corresponding Python method in `client.py` using `self._call()`
5. Wire a CLI command in `stmem.py` if user-facing
6. Write pytest unit test (mock the HTTP call) and integration test

### Adding a New Python SDK Method
1. Add method to `Client` class in `client.py`
2. If it's an LLM Wiki operation, also add to `Compounder` in `compounder.py`
3. Add unit test in `tests/test_client.py` or `tests/test_compounder.py`
4. Add CLI command in `cli/stmem.py`
5. Verify via `make test-unit`

### Adding a New Drop-in Adapter
1. Create `sdk/python/spacetime_memory/sdks/<name>.py`
2. Subclass or wrap the target library's API surface
3. Export in `sdk/python/spacetime_memory/sdks/__init__.py`
4. Add tests in `sdk/python/tests/`
5. Run `compare-upstream.py` to verify signature parity

### Before Opening a PR
- [ ] `make test-unit` passes
- [ ] `cd sdk/python && ruff check .` passes (no errors)
- [ ] `cd server/spacetimedb && cargo fmt --check && cargo clippy` (no new warnings)
- [ ] `cd sdk/python && python -m compileall spacetime_memory/` (no syntax errors)
- [ ] Documentation updated (AGENTS.md, docs/development.md, or README.md as appropriate)
- [ ] Run `make smoke` if a live STDB is available

## Task-to-File Mapping

| What you want to change | Files to edit |
|-------------------------|--------------|
| **SpacetimeDB schema / new table** | `server/spacetimedb/src/lib.rs` (table struct + reducer), plus relevant domain file (`memory.rs`, `note.rs`, etc.) |
| **Rust reducer logic** | `server/spacetimedb/src/<domain>.rs` (e.g. `memory.rs` for store/update/delete memories) |
| **Search behavior** | `server/spacetimedb/src/hybrid_query.rs` (fusion logic), `server/spacetimedb/src/query.rs` (query routing), `server/spacetimedb/src/retrieval.rs` (helpers) |
| **Python SDK client API** | `sdk/python/spacetime_memory/client.py` |
| **Knowledge Compounder / LLM Wiki** | `sdk/python/spacetime_memory/compounder.py` |
| **Drop-in adapter** | `sdk/python/spacetime_memory/sdks/<name>.py` |
| **CLI command** | `cli/stmem.py` |
| **MCP tool** | `server/mcp/main.py` |
| **Agent wiki schema / workflow** | `AGENTS.md` |
| **Documentation** | `docs/development.md`, `docs/usage/*.md`, or `README.md` |
| **CI / GitHub Actions** | `.github/workflows/ci.yml`, `.github/workflows/publish.yml` |
| **Docker / deployment** | `Dockerfile`, `docker-compose.yml`, `DEPLOYMENT.md` |
| **Python dependencies** | `sdk/python/pyproject.toml` |
| **Rust dependencies** | `server/spacetimedb/Cargo.toml` |
| **Benchmarks** | `scripts/retrieval_benchmark.py`, `scripts/weight_tune.py` |
| **Smoke test** | `sdk/python/tests/smoke_test.py` |

## CI Pipeline

The project runs **4 CI workflows** on every PR/push to `main`:

| Workflow | What it does | Runs on |
|----------|-------------|---------|
| **Rust** | `cargo build --release` + `cargo test` | Host target (x86_64) |
| **Rust Integration** | Build WASM + integration tests against live in-memory STDB | wasm32 + x86_64 |
| **Python SDK** | Ruff lint + format check + compileall + unit tests on Python 3.11/3.12 | No STDB needed |
| **Python Integration** | Build WASM + run `-m integration` and concurrency tests | Live STDB |

To simulate CI locally: `make ci`

## Quick Start for New Contributors

```bash
git clone https://github.com/omiinaya/spacetime-memory.git
cd spacetime-memory
make setup                                            # install SDK + build module
spacetime start --listen-addr 0.0.0.0:3001 &         # start STDB
spacetime publish spacetime-memory -p server/spacetimedb/ --yes --delete-data=never  # deploy module (NEVER wipe data)
make test-unit                                        # verify setup (no STDB needed)
pip install -e "sdk/python[dev]"                      # dev deps (ruff, pytest)
cd sdk/python && ruff check .                         # lint check
```
