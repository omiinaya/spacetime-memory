"""MCP resource and prompt definitions for the spacetime-memory MCP server.

Resources
----------
- ``info://server`` — server configuration summary (host, port, db, embedder)
- ``info://workspace/{workspace_id}`` — workspace metadata (requires client)

Prompts
-------
- ``summarize-workspace`` — generate a summarization prompt for a workspace
- ``memory-search-query`` — produce an optimised search query from a natural
  language question
"""
from __future__ import annotations

import json
import logging
from typing import Any

from server.mcp.tools.app import get_client, mcp

logger = logging.getLogger(__name__)


# =========================================================================
# Resources
# =========================================================================


@mcp.resource(
    "info://server",
    title="Server Info",
    description="Current server configuration (host, port, database, embedder)",
)
def server_info() -> str:
    """Return a JSON summary of the server configuration."""
    from server.mcp.tools.app import HOST, PORT, DB, EMBEDDER_URL, TANTIVY_URL

    info = {
        "host": HOST,
        "port": int(PORT),
        "database": DB,
        "embedder_url": EMBEDDER_URL,
        "tantivy_url": TANTIVY_URL,
    }
    return json.dumps(info, indent=2)


@mcp.resource(
    "info://workspace/{workspace_id}",
    title="Workspace Info",
    description="Metadata about a specific workspace",
)
def workspace_info(workspace_id: str) -> str:
    """Look up workspace metadata via the SDK client."""
    try:
        client = get_client()
        members = client.list_space_members(workspace_id)
    except Exception as exc:
        return json.dumps({"error": str(exc), "workspace_id": workspace_id})

    info = {
        "workspace_id": workspace_id,
        "member_count": len(members),
        "members": [
            {"peer_id": m.get("peer_id", ""), "permission": m.get("permission", "")}
            for m in members
        ],
    }
    return json.dumps(info, indent=2)


# =========================================================================
# Prompts
# =========================================================================


@mcp.prompt(
    name="summarize-workspace",
    title="Summarize Workspace",
    description="Generate a prompt to summarise workspace content",
)
def summarize_workspace(workspace_id: str, focus: str = "general") -> list[dict[str, Any]]:
    """Return a prompt message that asks an LLM to summarise a workspace."""
    return [
        {
            "role": "user",
            "content": (
                f"Please summarise workspace '{workspace_id}' "
                f"with a focus on: {focus}.\n\n"
                "Include the following sections:\n"
                "- Overview\n- Key Topics\n- Notable Items"
            ),
        }
    ]


@mcp.prompt(
    name="memory-search-query",
    title="Memory Search Query",
    description="Produce an optimised search query from a natural language question",
)
def memory_search_query(question: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Return a prompt message that optimises a search query."""
    return [
        {
            "role": "user",
            "content": (
                f"Given the following question, generate an optimised search query "
                f"for a memory store:\n\nQuestion: {question}\n\n"
                f"Max results: {max_results}\n\n"
                "Return only the search query string, nothing else."
            ),
        }
    ]
