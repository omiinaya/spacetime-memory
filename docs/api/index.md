# API Reference

This section contains auto-generated API documentation extracted from Python docstrings.

## SDK Modules

- `spacetime_memory` — Client, metrics, logging
- `spacetime_memory.sdks.mem0` — Mem0 adapter
- `spacetime_memory.sdks.honcho` — Honcho adapter
- `spacetime_memory.sdks.hindsight` — Hindsight adapter
- `spacetime_memory.sdks.graphiti` — Graphiti adapter
- `spacetime_memory.sdks.langchain` — LangChain/LangGraph adapter
- `spacetime_memory.sdks.zep` — Zep adapter

## CLI

- `stmem` — CLI entry point (click-based)

## Server

- `server/mcp/main.py` — MCP server (stdio transport)

!!! note "Build docs with mkdocstrings"
    To generate full API docs from docstrings, run:

    ```bash
    pip install mkdocs mkdocs-material mkdocstrings
    mkdocs serve
    ```

    Then visit the auto-generated pages under `api/`.
