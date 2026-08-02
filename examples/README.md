# Spacetime Memory — Example Projects

This directory contains self-contained example projects that demonstrate
spacetime-memory's key features. Each example is a single `main.py` that
you can run after completing setup.

## Prerequisites

Before running any example, ensure SpacetimeMemory is set up:

```bash
bash scripts/setup.sh
# or
stmem doctor  # verify connectivity
```

## Examples

### 1. Mem0 Switch — Drop-in Adapter Demo

**`examples/mem0-switch/main.py`**

Demonstrates the project's killer feature: write code against Mem0's API,
then switch to spacetime-memory's Mem0 adapter by changing one import line.

```bash
python examples/mem0-switch/main.py
```

Try switching the import from `spacetime_memory.sdks.mem0` to `mem0` to see
the code run identically against either backend.

### 2. RAG Chatbot — Search + Document Retrieval

**`examples/rag-chatbot/main.py`**

Demonstrates storing documents, semantic + keyword hybrid search, and
LLM-synthesized answers grounded in your data.

```bash
python examples/rag-chatbot/main.py
```

Set `OPENAI_API_KEY` for LLM-powered answer synthesis (search works without it).

### 3. Knowledge Graph Explorer

**`examples/kg-explorer/main.py`**

Demonstrates entity creation, typed relationship edges, graph traversal,
cross-linking, and workspace linting — the full knowledge graph stack.

```bash
python examples/kg-explorer/main.py
```

### 4. LLM Wiki — Knowledge Compounder Pattern

**`examples/llm-wiki/main.py`**

Demonstrates the full AGENTS.md wiki pattern: ingest a source article,
auto-extract entities, create KG nodes with edges, cross-link pages,
run contradiction checks, and generate a workspace overview.

```bash
python examples/llm-wiki/main.py
```

Requires `OPENAI_API_KEY` for LLM-powered entity extraction (falls back
to manual mode without it).

## Workspace Cleanup

Each example creates a new workspace (`mem0-demo`, `rag-demo`, `kg-demo`,
`llm-wiki-demo`). To clean up after running:

```bash
python -c "from spacetime_memory import Client; c = Client(); c.delete_workspace('workspace-id')"
# Find workspace IDs: python cli/stmem.py list-workspaces
```

Or delete via the CLI: `stmem delete-workspace <id>`.
