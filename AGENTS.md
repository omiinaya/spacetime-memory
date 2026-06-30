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

1|# Spacetime Memory — Agent Schema
2|
3|> *How an agent maintains a persistent, compounding wiki using Spacetime Memory.*
4|
5|For Claude Code specifically, also see [CLAUDE.md](./CLAUDE.md).
6|
7|This document is the **schema layer** from the [LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
8|It tells the agent how the wiki is structured, what conventions to follow, and
9|what workflows to use when ingesting sources, answering questions, or maintaining
10|the knowledge base.
11|
12|---
13|
14|## Three Layers
15|
16|| Layer | What | Who writes | Who reads |
17||-------|------|-----------|-----------|
18|| **Raw sources** | Immutable source documents (`raw/` directory). Articles, papers, transcripts, data files. | You (curator) | Agent |
19|| **The wiki** | SpacetimeDB notes + knowledge graph. Markdown notes, LLM-written summaries, entity pages, concept pages, comparisons, overviews. | Agent | You |
20|| **Schema** | This file — conventions, workflows, page formats. | You + Agent (co-evolved) | Agent |
21|
22|---
23|
24|## How the wiki is stored
25|
26|Two parallel stores in SpacetimeDB:
27|
28|### Notes (`create_note`, `update_note`, `_query("note", ...)`)
29|Rich markdown pages. Every page has:
30|- `title` — concise, human-readable
31|- `content` — markdown body with `[[wiki-links]]` to other notes where relevant
32|- `embed` — true for semantic searchability
33|
34|### Knowledge Graph (`create_node`, `create_edge`, `_query("kg_node", ...)`)
35|Entities extracted from sources and notes. Every node has:
36|- `label` — entity name
37|- `node_type` — one of: `person`, `org`, `concept`, `product`, `location`, `event`, `topic`
38|- `summary` — 2-3 sentence LLM-written description, kept up to date via ripple updates
39|
40|Edges connect nodes with typed relations: `informed_by`, `related_to`, `contradicts`, `supports`, `part_of`.
41|
42|### System pages
43|- `_index` — catalog of all wiki pages, grouped by category
44|- `_log` — chronological record of what happened and when
45|
46|---
47|
48|## Conventions
49|
50|### Note titles
51|- Title case for entity/concept pages: `"Reinforcement Learning from Human Feedback"`
52|- Question form for answer pages: `"What is RLHF?"`
53|- System pages prefixed with underscore: `_index`, `_log`
54|
55|### Markdown style
56|- Use `##` for section headers within pages
57|- Use `[[Wiki Links]]` to cross-reference other notes — the agent should parse these when they appear in existing notes and create edges
58|- Include a `---` separator before the auto-generated footer
59|- YAML frontmatter is optional but encouraged for Dataview compatibility:
60|
61|```yaml
62|---
63|type: entity | concept | comparison | synthesis | source-summary
64|tags: [topic1, topic2]
65|sources: [note_id_1, note_id_2]
66|created: 2026-06-22
67|---
68|```
69|
70|### Log entries
71|Use parseable prefix: `## [YYYY-MM-DD HH:MM UTC] event_type | detail`
72|This makes the log grep-able with unix tools.
73|
74|### Index entries
75|Each entry: `- [Title](note_id) — one-line summary`
76|
77|---
78|
79|## Workflows
80|
81|### 1. Ingest a Source (`client.compounder.ingest_source()`)
82|
83|When you add a new source document (article, paper, transcript):
84|
85|1. **Read** the source document
86|2. **Summarize** — create a source-summary note
87|3. **Extract entities** — find all named entities and create KG nodes for new ones
88|4. **Link** — connect entities to the source summary with `informed_by` edges
89|5. **Ripple update** — if existing entities gained new information, merge it into their node summaries
90|6. **Cross-reference** — check if the new source contradicts existing knowledge (proactive contradiction check)
91|7. **Index** — append to `_index`
92|8. **Log** — append to `_log`
93|
94|### 2. Answer a Query
95|
96|1. **Search** — `client.search()` or `spacetime_search()` to find relevant memories, notes, and KG nodes
97|2. **Synthesize** — read the matched pages and compose an answer with citations
98|3. **File answers** — if the answer is valuable (analysis, comparison, connection), call `compounder.store_answer()` to persist it as a new wiki page
99|4. **Log** — append to `_log`
100|
101|### 3. Health-Check / Lint
102|
103|Run `compounder.lint_workspace()` periodically (weekly or after every ~10 ingests):
104|- **Orphans** — KG nodes with no edges, candidates for linking or cleanup
105|- **Missing cross-refs** — notes mentioning entities but lacking KG edges
106|- **Contradictions** — (LLM-powered) pairs of semantically similar memories with conflicting claims
107|
108|### 4. Maintain
109|
110|- **Ripple updates** — when new information arrives for an existing entity, merge it into the node summary rather than replacing
111|- **Cross-link** — `compounder.cross_link()` finds related but unconnected memories and creates edges
112|- **Suggest connections** — `compounder.suggest_connections()` identifies node pairs that share neighbours but aren't directly linked
113|
114|---
115|
116|## CLI Tools
117|
118|### Available via the client SDK
119|
120|| Operation | Method | Description |
121||-----------|--------|-------------|
122|| Store answer | `compounder.store_answer(query, answer, ...)` | Persist an LLM synthesis as a wiki page |
123|| Cross-link | `compounder.cross_link(workspace_id)` | Auto-link related but unconnected memories |
124|| Suggest connections | `compounder.suggest_connections(workspace_id)` | Find node pairs that should be linked |
125|| Lint | `compounder.lint_workspace(workspace_id, ...)` | Health-check: orphans, crossrefs, contradictions |
126|| Export | `compounder.export_workspace(output_dir, ...)` | Export wiki as markdown files for Obsidian/git |
127|| Overview | `compounder.generate_overview_page(workspace_id)` | Generate _overview with stats, entities, activity |
128|| Search | `client.search(workspace_id, query, ...)` | Semantic + keyword search across all stores |
129|| Create note | `client.create_note(workspace_id, title, content, ...)` | Add a wiki page |
130|| Create node | `client.create_node(workspace_id, label, node_type, ...)` | Add a KG entity |
131|| Create edge | `client._call("create_edge", [workspace_id, src, tgt, ...])` | Link two nodes |
132|| Entity page | `compounder.create_entity_page(name, description, ...)` | Structured entity wiki page + KG node |
133|| Update entity page | `compounder.update_entity_page(name, ...)` | Update existing entity wiki page + KG node |
134|| Concept page | `compounder.create_concept_page(concept, definition, ...)` | Concept definition with [[wiki-links]] |
135|| Comparison page | `compounder.create_comparison_page(title, items, ...)` | Markdown comparison table |
136|
137|### Available via CLI
138|
139|All compounder SDK methods have terminal equivalents via `stmem`:
140|
141|| SDK Method | CLI Command |
142||-----------|-------------|
143|| `compounder.store_answer()` | `stmem store-answer --query "..." --answer "..."` |
144|| `compounder.cross_link()` | `stmem cross-link --workspace <id>` |
145|| `compounder.suggest_connections()` | `stmem suggest-connections --workspace <id>` |
146|| `compounder.lint_workspace()` | `stmem lint --workspace <id>` |
147|| `compounder.export_workspace()` | `stmem export markdown ./path/ --workspace <id>` |
148|| `compounder.generate_overview_page()` | `stmem overview --workspace <id>` |
149|| `compounder.ingest_source()` | `stmem ingest file --path article.txt` |
150|| `compounder.create_entity_page()` | `stmem entity-page --name "..." --description "..."` |
151|| `compounder.update_entity_page()` | `stmem update-entity-page --name "..." --description "..."` |
152|| `compounder.create_concept_page()` | `stmem concept-page --concept "..." --definition "..."` |
153|| `compounder.create_comparison_page()` | `stmem comparison-page --title "..." --items "a,b"` |
154|| `compounder.search_entities()` | `stmem search-entities --label "..." --type concept --query "..."` |
155|
156|All CLI commands support `--output json` for machine-readable output.
157|
158|### Available via MCP tools
159|
160|When the agent is connected via MCP (``stmem serve``), these tools are
161|automatically available without importing the SDK:
162|
163|| Tool | What it does |
164||------|-------------|
165|| `ingest_source` | Full LLM Wiki ingest: summarize, extract entities, create KG nodes, link, ripple, check contradictions |
166|| `create_entity_page` | Create entity wiki page + KG node with YAML frontmatter |
167|| `update_entity_page` | Update existing entity wiki page + KG node |
168|| `create_concept_page` | Create concept definition page with [[wiki-links]] |
169|| `create_comparison_page` | Create comparison page with markdown table |
170|| `lint_workspace` | Health-check: orphans, missing crossrefs, contradictions |
171|| `generate_overview` | Generate workspace overview/synthesis page |
172|| `store_answer` | Persist an LLM answer as a wiki page |
173|| `search_entities` | Search KG entities by label, type, or semantic query |
174|
175|---
176|
177|## Tips
178|
179|- **Git** — the wiki is just data in a database, but notes can be exported to markdown files for Obsidian / git version control
180|- **Obsidian** — the graph view is the best way to see the shape of your wiki: hubs, orphans, clusters
181|- **Dataview** — if notes have YAML frontmatter, Dataview can generate dynamic tables and lists in Obsidian
182|- **Marp** — markdown slide decks can be generated directly from wiki pages
183|
184|---
185|
186|> *The tedious part of maintaining a knowledge base is the bookkeeping. LLMs don't get bored, don't forget to update a cross-reference, and can touch 15 files in one pass. The wiki stays maintained because the cost of maintenance is near zero.*
187|
188|---
189|
190|# Development Guide for Agent Contributors
191|
192|> *This section tells AI agents how to develop, build, test, and contribute to the Spacetime Memory project itself — not how to use the wiki.*
193|
194|## Workspace Layout
195|
196|```
197|spacetime-memory/
198|├── server/
199|│   ├── spacetimedb/              # SpacetimeDB Rust WASM module
200|│   │   ├── src/lib.rs            # Module entrypoint, ~162 reducers
201|│   │   ├── src/memory.rs         # Memory CRUD reducers
202|│   │   ├── src/knowledge_graph.rs # KG node/edge/community reducers
203|│   │   ├── src/note.rs           # Note/wikilink reducers
204|│   │   ├── src/query.rs          # Search and query reducers
205|│   │   ├── src/hybrid_query.rs   # Multi-strategy search fusion
206|│   │   ├── src/replication.rs    # CDC / delta sync
207|│   │   ├── src/consolidation.rs  # Dedup, decay, maintenance
208|│   │   ├── src/change_event.rs   # Change tracking
209|│   │   ├── src/retrieval.rs      # Retrieval helpers
210|│   │   └── Cargo.toml            # Rust deps (spacetimedb v2.6, serde, sha2, etc.)
211|│   ├── tantivy-sidecar/          # BM25 full-text search sidecar (Rust, port 9091)
212|│   └── mcp/                      # MCP server (Python, 133+ tools)
213|├── sdk/
214|│   └── python/                   # Python SDK + CLI + MCP
215|│       ├── spacetime_memory/
216|│       │   ├── client.py         # Core Client (~247 unit tests, 2488+ lines)
217|│       │   ├── compounder.py     # Knowledge Compounder (LLM Wiki ingestion)
218|│       │   ├── sdks/             # 6 drop-in adapters (mem0, zep, graphiti, etc.)
219|│       │   ├── agent_orchestrator.py
220|│       │   └── metrics.py / tracer.py  # Observability
221|│       ├── tests/                # ~3,319 collected tests
222|│       ├── pyproject.toml        # Build config, ruff/pytest settings
223|│       └── setup.py              # Legacy setup (kept for compat)
224|├── cli/
225|│   └── stmem.py                  # CLI tool (37 subcommands, 3509 lines)
226|├── client/                       # React frontend (optional)
227|├── scripts/                      # Benchmarks, eval, replication daemon
228|├── docs/                         # Documentation (development.md, api/, usage/)
229|├── tests/                        # Top-level integration tests
230|└── data/                         # Runtime data (tantivy indexes, eval data)
231|```
232|
233|## Build Commands
234|
235|| Command | What | When |
236||---------|------|------|
237|| `make build-module` | Build Rust WASM module (release) | After changing `server/spacetimedb/src/` |
238|| `make install-sdk` | `pip install -e sdk/python` | First setup, after pulling new deps |
239|| `make setup` | install-sdk + build-module | Fresh clone setup |
240|| `spacetime publish <name> -p server/spacetimedb/ --yes --delete-data=never` | Deploy module to STDB | After a successful build |
> **⚠️ DATA SAFETY:** Always use `--delete-data=never`. The script `./scripts/publish.sh` enforces this automatically. Never use `--delete-data=on-conflict` — it silently wipes production data on schema changes. Never use `--delete-data=always` unless you've verified a backup exists and explicitly intend to reset.
241|| `cd server/spacetimedb && cargo build --target wasm32-unknown-unknown --release` | Raw cargo build | Debugging Rust compilation |
242|| `cd sdk/python && pip install -e ".[dev]"` | Install dev extras (pytest, ruff) | Before running tests/lint |
243|
244|## Test Commands
245|
246|| Command | Scope | Requires STDB? |
247||---------|-------|:--------------:|
248|| `make test-unit` | Python unit tests (`-m unit`) | ❌ No |
249|| `make test` | Full suite (unit + integration) | ✅ Yes (:3001) |
250|| `make test-integration` | Integration tests only | ✅ Yes (:3001) |
251|| `make test-rust` | Rust `cargo test --lib` | ❌ No (host target) |
252|| `make test-all` | ALL Python tests (no filter) | ✅ Yes |
253|| `make test-frontend` | Frontend vitest | ❌ No |
254|| `make test-e2e` | Playwright E2E | ✅ Yes |
255|| `make smoke` | E2E smoke test | ✅ Yes (:3001) |
256|| `make ci` | Full local CI (Rust + Python + TS) | Varies |
257|| `make bench` | Performance benchmark | ✅ Yes (+ embedder) |
258|| `pytest -m unit -v` | Quick unit test pass | ❌ No |
259|
260|**Test markers** (defined in `sdk/python/pyproject.toml`):
261|- `unit` — Mocks HTTP, no SpacetimeDB needed
262|- `integration` — Requires a running SpacetimeDB on `localhost:3001`
263|- `embedder` — Also needs the embedding sidecar on `:9090`
264|
265|## Code Conventions
266|
267|### Python
268|- **PEP 8** with ruff formatter (line length 100, double quotes)
269|- **Type hints** on every function signature (`from __future__ import annotations`)
270|- **Google-style docstrings** with `Args:`, `Returns:`, `Raises:`, `Example:` sections
271|- **Imports**: stdlib → third-party → local, one blank line between groups
272|- **Prefer** `pathlib.Path` over `os.path`
273|- **Private helpers** use `def _name()` convention
274|- **No bare `except:`** — catch specific exceptions or use `except Exception:`
275|- **No `print()`** in production — use `logger` from `configure_logging()`
276|
277|### Rust
278|- Standard `rustfmt` formatting — run `cargo fmt` before committing
279|- Run `cargo clippy` for lint
280|- Writes through reducers only (no raw SQL DML)
281|- Reads through `query_table` reducer for private tables
282|- Use `ctx.timestamp` (not `SystemTime::now()`), `ctx.rng()` (not `OsRng`)
283|- Return `Result<(), String>` from all reducers
284|
285|### Commit Messages
286|```
287|<area>: <short imperative description>
288|
289|<optional body explaining what and why, not how>
290|```
291|Examples: `cli: add replication add-peer command`, `sdk(client): add get_memory_history method`, `server(replication): handle conflict resolution on insert`
292|
293|## Developer Workflow
294|
295|### Adding a New Reducer (Server-Side)
296|1. Define the `#[reducer]` function in the appropriate Rust file (e.g. `memory.rs`)
297|2. Build: `make build-module`
298|3. Publish: `spacetime publish <name> -p server/spacetimedb/ --yes --delete-data=never`
299|4. Add a corresponding Python method in `client.py` using `self._call()`
300|5. Wire a CLI command in `stmem.py` if user-facing
301|6. Write pytest unit test (mock the HTTP call) and integration test
302|
303|### Adding a New Python SDK Method
304|1. Add method to `Client` class in `client.py`
305|2. If it's an LLM Wiki operation, also add to `Compounder` in `compounder.py`
306|3. Add unit test in `tests/test_client.py` or `tests/test_compounder.py`
307|4. Add CLI command in `cli/stmem.py`
308|5. Verify via `make test-unit`
309|
310|### Adding a New Drop-in Adapter
311|1. Create `sdk/python/spacetime_memory/sdks/<name>.py`
312|2. Subclass or wrap the target library's API surface
313|3. Export in `sdk/python/spacetime_memory/sdks/__init__.py`
314|4. Add tests in `sdk/python/tests/`
315|5. Run `compare-upstream.py` to verify signature parity
316|
317|### Before Opening a PR
318|- [ ] `make test-unit` passes
319|- [ ] `cd sdk/python && ruff check .` passes (no errors)
320|- [ ] `cd server/spacetimedb && cargo fmt --check && cargo clippy` (no new warnings)
321|- [ ] `cd sdk/python && python -m compileall spacetime_memory/` (no syntax errors)
322|- [ ] Documentation updated (AGENTS.md, docs/development.md, or README.md as appropriate)
323|- [ ] Run `make smoke` if a live STDB is available
324|
325|## Task-to-File Mapping
326|
327|| What you want to change | Files to edit |
328||-------------------------|--------------|
329|| **SpacetimeDB schema / new table** | `server/spacetimedb/src/lib.rs` (table struct + reducer), plus relevant domain file (`memory.rs`, `note.rs`, etc.) |
330|| **Rust reducer logic** | `server/spacetimedb/src/<domain>.rs` (e.g. `memory.rs` for store/update/delete memories) |
331|| **Search behavior** | `server/spacetimedb/src/hybrid_query.rs` (fusion logic), `server/spacetimedb/src/query.rs` (query routing), `server/spacetimedb/src/retrieval.rs` (helpers) |
332|| **Python SDK client API** | `sdk/python/spacetime_memory/client.py` |
333|| **Knowledge Compounder / LLM Wiki** | `sdk/python/spacetime_memory/compounder.py` |
334|| **Drop-in adapter** | `sdk/python/spacetime_memory/sdks/<name>.py` |
335|| **CLI command** | `cli/stmem.py` |
336|| **MCP tool** | `server/mcp/main.py` |
337|| **Agent wiki schema / workflow** | `AGENTS.md` |
338|| **Documentation** | `docs/development.md`, `docs/usage/*.md`, or `README.md` |
339|| **CI / GitHub Actions** | `.github/workflows/ci.yml`, `.github/workflows/publish.yml` |
340|| **Docker / deployment** | `Dockerfile`, `docker-compose.yml`, `DEPLOYMENT.md` |
341|| **Python dependencies** | `sdk/python/pyproject.toml` |
342|| **Rust dependencies** | `server/spacetimedb/Cargo.toml` |
343|| **Benchmarks** | `scripts/retrieval_benchmark.py`, `scripts/weight_tune.py` |
344|| **Smoke test** | `sdk/python/tests/smoke_test.py` |
345|
346|## CI Pipeline
347|
348|The project runs **4 CI workflows** on every PR/push to `main`:
349|
350|| Workflow | What it does | Runs on |
351||----------|-------------|---------|
352|| **Rust** | `cargo build --release` + `cargo test` | Host target (x86_64) |
353|| **Rust Integration** | Build WASM + integration tests against live in-memory STDB | wasm32 + x86_64 |
354|| **Python SDK** | Ruff lint + format check + compileall + unit tests on Python 3.11/3.12 | No STDB needed |
355|| **Python Integration** | Build WASM + run `-m integration` and concurrency tests | Live STDB |
356|
357|To simulate CI locally: `make ci`
358|
359|## Quick Start for New Contributors
360|
361|```bash
362|git clone https://github.com/omiinaya/spacetime-memory.git
363|cd spacetime-memory
364|make setup                                            # install SDK + build module
365|spacetime start --listen-addr 0.0.0.0:3001 &         # start STDB
366|spacetime publish spacetime-memory -p server/spacetimedb/ --yes --delete-data=never  # deploy module (NEVER wipe data)
367|make test-unit                                        # verify setup (no STDB needed)
368|pip install -e "sdk/python[dev]"                      # dev deps (ruff, pytest)
369|cd sdk/python && ruff check .                         # lint check
370|```
371|