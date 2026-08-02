"""MCP tools — Tour tools."""

from __future__ import annotations

from typing import Any

from server.mcp.tools.app import get_client, mcp, require_api_key
# Tour tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def create_tour(workspace_id: str, title: str, description: str = "") -> str:
    """Create a new guided tour through KG nodes."""
    get_client().create_tour(workspace_id, title, description)
    return f"Tour '{title}' created."


@mcp.tool()
@require_api_key
def add_tour_stop(tour_id: str, node_id: str, heading: str, description: str = "") -> str:
    """Add a stop to an existing tour."""
    get_client().add_tour_stop(tour_id, node_id, heading, description)
    return f"Stop '{heading}' added to tour."


@mcp.tool()
@require_api_key
def delete_tour(tour_id: str) -> str:
    """Delete a guided tour and all its stops.

    Args:
        tour_id: The ID of the tour to delete.

    Returns:
        Confirmation message.
    """
    get_client().delete_tour(tour_id)
    return f"Tour {tour_id[:16]}... deleted."


@mcp.tool()
@require_api_key
def delete_tour_stop(stop_id: str) -> str:
    """Remove a single stop from a guided tour.

    Args:
        stop_id: The ID of the tour stop to remove.

    Returns:
        Confirmation message.
    """
    get_client().delete_tour_stop(stop_id)
    return f"Tour stop {stop_id[:16]}... deleted."


# ---------------------------------------------------------------------------
