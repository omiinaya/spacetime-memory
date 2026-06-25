# Spacetime Memory — Agent Schema

> *How an agent maintains a persistent, compounding wiki using Spacetime Memory.*

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
- `node_type` — one of: `person`, `org`, `concept`, `product`, `location`, `event`, `topic`
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
| Concept page | `compounder.create_concept_page(concept, definition, ...)` | Concept definition with [[wiki-links]] |
| Comparison page | `compounder.create_comparison_page(title, items, ...)` | Markdown comparison table |

---

## Tips

- **Git** — the wiki is just data in a database, but notes can be exported to markdown files for Obsidian / git version control
- **Obsidian** — the graph view is the best way to see the shape of your wiki: hubs, orphans, clusters
- **Dataview** — if notes have YAML frontmatter, Dataview can generate dynamic tables and lists in Obsidian
- **Marp** — markdown slide decks can be generated directly from wiki pages

---

> *The tedious part of maintaining a knowledge base is the bookkeeping. LLMs don't get bored, don't forget to update a cross-reference, and can touch 15 files in one pass. The wiki stays maintained because the cost of maintenance is near zero.*
