# Getting Started

This guide covers SDK usage examples. For setup instructions (installing SpacetimeDB, building the module, configuring embeddings), see the **[Setup section in README.md](../README.md#setup)** which has two paths:

- [Quick Start (I have a running SpacetimeDB)](../README.md#quick-start-i-have-a-running-spacetimedb) — just `pip install` and go
- [Full Stack Setup (from scratch)](../README.md#full-stack-setup-from-scratch--need-to-run-stdb) — set up STDB for the first time

## Using the Low-Level Client

```python
from spacetime_memory import Client

client = Client(host="127.0.0.1", port="3001", database="your-db")

# Create a workspace
ws = client.create_workspace("my-app")
ws_id = ws["id"]

# Store a memory
client.store(ws_id, "I like pizza", peer_id="alice")

# Search memories
results = client.search(ws_id, "food preferences", semantic=True)
print(results)
```

## Using the Mem0 Adapter

```python
from spacetime_memory.sdks import Mem0Memory

m = Mem0Memory(config={"host": "127.0.0.1", "port": "3001"})
m.add("I like pizza", user_id="alice")
results = m.search("food preferences", user_id="alice")
```

## Using the Hindsight Adapter

```python
from spacetime_memory.sdks import Hindsight

h = Hindsight(base_url="http://127.0.0.1:3001", api_key="optional")
h.retain("my_bank", "I like pizza")
results = h.recall("my_bank", "food preferences")
```

## Using the Honcho Adapter

```python
from spacetime_memory.sdks import Honcho

honcho = Honcho(workspace_id="my_workspace")
p = honcho.peer("alice")
s = honcho.session("my_session")
s.add_messages([{"role": "user", "content": "I like pizza"}])
results = honcho.search("pizza")
print(results)
```

## Using the LangGraph Adapter

```python
from spacetime_memory.sdks import StmemStore

store = StmemStore(host="127.0.0.1", port="3001")
store.put(("memories", "alice"), {"data": "I like pizza"})
items = store.search(("memories", "alice"), query="pizza")
```

## Using the CLI

```bash
# stmem is installed via pip install -e sdk/python
stmem --help

# Store a memory
stmem store --workspace <ws_id> --content "I like pizza" --peer alice

# Search
stmem search --workspace <ws_id> --query "food"

# See all CLI commands
stmem --help
```

## Running Tests

```bash
# Unit tests only — no STDB needed (~30s)
cd sdk/python && python -m pytest tests/ -m unit -v

# Full suite (unit + integration) — needs STDB on :3001
make test

# Integration tests only — auto-builds module, auto-publishes
make test-integration
```

## Working with the LLM Wiki

Spacetime Memory includes a full **LLM Wiki / Knowledge Compounder** layer — a pattern for agents to build and maintain a persistent, compounding knowledge base. See **[AGENTS.md](../AGENTS.md)** for the complete schema and workflow:

- **Ingest sources** → auto-summarize, extract entities, link to knowledge graph
- **Wiki pages** → notes with `[[wiki-links]]`, YAML frontmatter, backlinks
- **Knowledge graph** → typed entity nodes, communities, contradiction checking
- **Ripple updates** → new info merges into existing entity summaries
- **Health checks** → lint for orphans, missing cross-refs, contradictions

```python
from spacetime_memory import Client
from spacetime_memory.compounder import KnowledgeCompounder

client = Client()
compounder = KnowledgeCompounder(client, workspace_id="my-wiki")

# Ingest a source — auto-summarize, extract entities, create KG
compounder.ingest_source("path/to/article.txt")

# Store an LLM answer as a wiki page
compounder.store_answer(
    query="What is RLHF?",
    answer="Reinforcement Learning from Human Feedback is...",
    tags=["alignment", "rlhf"],
)

# Health-check: find orphans and missing cross-refs
report = compounder.lint_workspace()
print(report)
```
