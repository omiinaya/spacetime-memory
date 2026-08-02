"""MCP tools — Entity Resolution tools."""

from __future__ import annotations

from typing import Any

from server.mcp.tools.app import get_client, mcp, require_api_key
# Entity Resolution tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def resolve_entity(workspace_id: str, name: str) -> str:
    """Resolve an entity name within a workspace.

    Uses the STDB entity resolution reducer to find the canonical entity
    for a given name, taking into account aliases and entity links.

    Args:
        workspace_id: The workspace ID to search in.
        name: The entity name or alias to resolve.

    Returns:
        Confirmation message with the resolved entity result.
    """
    get_client().resolve_entity(workspace_id, name)
    return f"Entity '{name}' resolved in workspace {workspace_id[:16]}..."


@mcp.tool()
@require_api_key
def add_alias(entity_link_id: str, alias: str) -> str:
    """Add an alias to an existing entity link.

    Complements ``resolve_entity`` by allowing agents to register
    aliases for entity name resolution.

    Args:
        entity_link_id: The entity link ID to add an alias to.
        alias: The alias to add (e.g. a display name, username, or
            common alternative identifier).

    Returns:
        Confirmation message.
    """
    get_client().add_alias(entity_link_id, alias)
    return f"Alias '{alias}' added to entity link {entity_link_id[:16]}..."


@mcp.tool()
@require_api_key
def create_entity_link(
    workspace_id: str,
    canonical_name: str,
    entity_type: str,
    description: str = "",
) -> str:
    """Create a canonical entity link for Mem0-style entity resolution.

    Entity links map names to canonical entities within a workspace,
    enabling resolution of aliases and nicknames. Useful for name
    disambiguation in multi-agent systems.

    Args:
        workspace_id: The workspace to create the entity link in.
        canonical_name: The canonical (preferred) name for this entity.
        entity_type: The entity type (e.g. ``"person"``, ``"org"``,
            ``"concept"``, ``"product"``).
        description: Optional human-readable description of this entity.

    Returns:
        Confirmation message.
    """
    get_client().create_entity_link(workspace_id, canonical_name, entity_type, description)
    return f"Entity link '{canonical_name}' created in workspace {workspace_id[:16]}..."


# ---------------------------------------------------------------------------
