"""MCP tools — Mental Model tools."""

from __future__ import annotations

import json
from typing import Any

from server.mcp.tools.app import get_client, mcp, require_api_key
# Mental Model tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def synthesize_mental_models(workspace_id: str, memory_ids_json: str) -> str:
    """Request synthesis of a mental model from a set of source memories.

    Creates a pending MentalModel record. Run mental_model_synthesis.py
    to generate actual LLM content.
    """
    client = get_client()
    client.synthesize_mental_models(workspace_id, json.loads(memory_ids_json))
    return f"Mental model synthesis requested for workspace {workspace_id[:16]}..."


@mcp.tool()
@require_api_key
def get_mental_model(id: str) -> str:
    """Get a single mental model by its ID."""
    client = get_client()
    rows = client._sql_param(
        "SELECT * FROM mental_model WHERE id = ?",
        id,
    )
    return json.dumps(rows, default=str)


@mcp.tool()
@require_api_key
def list_mental_models(workspace_id: str, status: str = "") -> str:
    """List mental models for a workspace, optionally filtered by status.

    Args:
        workspace_id: The workspace ID
        status: Optional filter: "pending", "completed", "failed", or empty for all
    """
    client = get_client()
    if status:
        rows = client._sql_param(
            "SELECT * FROM mental_model WHERE "
            "workspace_id = ? AND status = ? "
            "ORDER BY created_at DESC",
            workspace_id, status,
        )
    else:
        rows = client._sql_param(
            "SELECT * FROM mental_model WHERE "
            "workspace_id = ? "
            "ORDER BY created_at DESC",
            workspace_id,
        )
    return json.dumps(rows, default=str)


@mcp.tool()
@require_api_key
def delete_mental_model(model_id: str) -> str:
    """Delete a mental model by its ID.

    Args:
        model_id: The UUID of the mental model to delete.
    """
    get_client().delete_mental_model(model_id)
    return f"Mental model {model_id[:16]}... deleted."


@mcp.tool()
@require_api_key
def update_mental_model(
    model_id: str,
    content: str,
    confidence: float = 0.5,
    status: str = "completed",
) -> str:
    """Update the content, confidence, and status of an existing mental model.

    Args:
        model_id: The UUID of the mental model.
        content: The new synthesized content.
        confidence: Confidence score (0.0–1.0). Default 0.5.
        status: Status: "pending", "completed", or "failed". Default "completed".
    """
    get_client().update_mental_model(model_id, content, confidence, status)
    return f"Mental model {model_id[:16]}... updated."


# -------------------------------------------------------------------------
# Fact tools
