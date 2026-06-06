"""
MCP (Model Context Protocol) server for spacetime-memory.

Connects to a SpacetimeDB instance via its HTTP API and exposes ~15 MCP tools
covering workspaces, memories, profiles, knowledge graph, sessions, and search.
Uses stdio transport for integration with MCP-compatible clients.

Configuration via environment variables:
  SPACETIMEDB_HOST   (default: localhost)
  SPACETIMEDB_PORT   (default: 3001)
  SPACETIMEDB_DB     (default: spacetime-memory)
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get("SPACETIMEDB_DB", "spacetime-memory")
BASE_URL = f"http://{HOST}:{PORT}"

SQL_URL = f"{BASE_URL}/v1/database/{DB}/sql"
REDUCER_URL = f"{BASE_URL}/v1/database/{DB}/call"

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("spacetime-memory", log_level="WARNING")

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_client: httpx.Client | None = None


def get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=30.0)
    return _client


def _sql(query: str) -> list[dict[str, Any]]:
    """Execute a SQL SELECT / read query and return parsed dicts.

    SpacetimeDB returns a positional-array format:
      [{ "schema": { "elements": [ {"name": {"some": "col"}, ...} ] },
         "rows": [ [val, ...], ... ] }]
    """
    resp = get_client().post(SQL_URL, content=query, headers={"Content-Type": "text/plain"})
    if resp.status_code >= 400:
        body = resp.text[:2000]
        raise RuntimeError(f"SQL error (HTTP {resp.status_code}): {body}")

    data: list[dict] = resp.json()
    if not data:
        return []

    results: list[dict[str, Any]] = []
    for table in data:
        schema = table.get("schema", {})
        elements = schema.get("elements", [])
        col_names: list[str] = []
        for el in elements:
            name_container = el.get("name", {})
            # name is {"some": "column_name"} or {"none": null}
            if isinstance(name_container, dict) and "some" in name_container:
                col_names.append(name_container["some"])
            else:
                col_names.append("?col?")

        rows = table.get("rows", [])
        for row in rows:
            row_dict = {}
            for i, val in enumerate(row):
                key = col_names[i] if i < len(col_names) else f"col{i}"
                row_dict[key] = val
            results.append(row_dict)

    return results


def _call(reducer: str, args: list[Any]) -> dict[str, Any]:
    """Call a SpacetimeDB reducer with the given positional arguments."""
    resp = get_client().post(
        f"{REDUCER_URL}/{reducer}",
        content=json.dumps(args),
        headers={"Content-Type": "application/json"},
    )
    if resp.status_code >= 400:
        body = resp.text[:2000]
        raise RuntimeError(f"Reducer error (HTTP {resp.status_code}): {body}")
    # On success SpacetimeDB returns 200 with empty body for reducers
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Workspace tools
# ---------------------------------------------------------------------------


@mcp.tool()
def create_workspace(name: str, description: str = "") -> dict[str, Any]:
    """Create a new workspace."""
    return _call("create_workspace", [name, description])


@mcp.tool()
def list_workspaces() -> list[dict[str, Any]]:
    """List all workspaces with their metadata."""
    return _sql("SELECT * FROM workspace ORDER BY created_at DESC")


# ---------------------------------------------------------------------------
# Memory tools
# ---------------------------------------------------------------------------


@mcp.tool()
def store_memory(
    workspace_id: str,
    peer_id: str,
    observer_id: str = "",
    memory_type: str = "experience",
    content: str = "",
    summary: str = "",
    entities_json: str = "[]",
    confidence: float = 0.8,
    source_session_id: str = "",
    source_message_id: str = "",
    tier: str = "",
) -> dict[str, Any]:
    """Store a new memory in the database.

    Supported memory_type values: world_fact, experience, mental_model.
    Tier (optional): L0=critical, L1=normal, L2=archival.  If provided,
    updates the tier after storing.
    """
    result = _call("store_memory", [
        workspace_id, peer_id, observer_id,
        memory_type, content, summary, entities_json,
        confidence, source_session_id, source_message_id,
    ])
    # If tier is specified, update it after creation
    if tier and tier in ("L0", "L1", "L2"):
        # The store_memory reducer returns ok but doesn't give back the id.
        # Find the most recent memory for this workspace+peer to get the id.
        mems = _sql(
            f"SELECT id FROM memory WHERE workspace_id = '{_esc(workspace_id)}' "
            f"AND peer_id = '{_esc(peer_id)}' ORDER BY created_at DESC LIMIT 1"
        )
        if mems:
            _call("update_memory_tier", [mems[0]["id"], tier])
    return result


@mcp.tool()
def search_memories(
    workspace_id: str,
    query_text: str = "",
    memory_type: str = "",
    tier: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search memories in a workspace.

    Supports optional full-text filtering via LIKE, optional memory_type
    and tier filters.
    """
    clauses = [f"workspace_id = '{_esc(workspace_id)}'"]
    if query_text:
        escaped = _esc(query_text)
        clauses.append(f"(content LIKE '%{escaped}%' OR summary LIKE '%{escaped}%')")
    if memory_type:
        clauses.append(f"memory_type = '{_esc(memory_type)}'")
    if tier:
        clauses.append(f"tier = '{_esc(tier)}'")

    where = " AND ".join(clauses) if clauses else "1=1"
    return _sql(
        f"SELECT * FROM memory WHERE {where} ORDER BY created_at DESC LIMIT {int(limit)}"
    )


@mcp.tool()
def get_memory(id: str) -> list[dict[str, Any]]:
    """Retrieve a single memory by its ID."""
    return _sql(f"SELECT * FROM memory WHERE id = '{_esc(id)}'")


@mcp.tool()
def reinforce_memory(memory_id: str) -> dict[str, Any]:
    """Reinforce a memory: increment access_count and bump strength."""
    return _call("reinforce_memory", [memory_id])


@mcp.tool()
def rate_memory(memory_id: str, rating: str, peer_id: str) -> dict[str, Any]:
    """Rate a memory as 'helpful' or 'unhelpful' to adjust its trust score."""
    return _call("rate_memory", [memory_id, rating, peer_id])


# ---------------------------------------------------------------------------
# Profile tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_profile(peer_id: str) -> list[dict[str, Any]]:
    """Retrieve the profile for a peer, including static_facts, dynamic_context, and preferences.

    The returned fields (static_facts_json, dynamic_context_json,
    preferences_json) are JSON strings.  Parse them as needed.
    """
    return _sql(f"SELECT * FROM profile WHERE peer_id = '{_esc(peer_id)}'")


@mcp.tool()
def upsert_profile(
    peer_id: str,
    static_facts_json: str = "[]",
    dynamic_context_json: str = "[]",
    preferences_json: str = "{}",
    tags_json: str = "[]",
) -> dict[str, Any]:
    """Create or update a peer profile.

    All JSON parameters must be valid JSON strings (arrays for
    static_facts/dynamic_context/tags, object for preferences).
    """
    return _call("upsert_profile", [
        peer_id, static_facts_json, dynamic_context_json,
        preferences_json, tags_json,
    ])


# ---------------------------------------------------------------------------
# Knowledge Graph tools
# ---------------------------------------------------------------------------


@mcp.tool()
def query_graph(workspace_id: str, query: str = "") -> list[dict[str, Any]]:
    """Search knowledge graph nodes by label within a workspace."""
    if query:
        escaped = _esc(query)
        return _sql(
            f"SELECT * FROM kg_node WHERE workspace_id = '{_esc(workspace_id)}' "
            f"AND label LIKE '%{escaped}%' ORDER BY created_at DESC"
        )
    return _sql(
        f"SELECT * FROM kg_node WHERE workspace_id = '{_esc(workspace_id)}' "
        f"ORDER BY created_at DESC"
    )


@mcp.tool()
def get_node(id: str) -> list[dict[str, Any]]:
    """Retrieve a knowledge graph node by its ID."""
    return _sql(f"SELECT * FROM kg_node WHERE id = '{_esc(id)}'")


@mcp.tool()
def get_neighbors(node_id: str) -> list[dict[str, Any]]:
    """Get all edges (neighbors) connected to a node.

    Returns both outgoing and incoming edges with node labels.
    """
    return _sql(
        f"SELECT e.*, "
        f"  src.label AS source_label, tgt.label AS target_label "
        f"FROM kg_edge e "
        f"LEFT JOIN kg_node src ON e.source_node_id = src.id "
        f"LEFT JOIN kg_node tgt ON e.target_node_id = tgt.id "
        f"WHERE e.source_node_id = '{_esc(node_id)}' "
        f"   OR e.target_node_id = '{_esc(node_id)}' "
        f"ORDER BY e.weight DESC"
    )


@mcp.tool()
def get_community(community_id: int) -> dict[str, Any]:
    """Get community details and list all nodes in that community."""
    community = _sql(f"SELECT * FROM kg_community WHERE id = {int(community_id)}")
    nodes = _sql(f"SELECT * FROM kg_node WHERE community_id = {int(community_id)}")
    return {
        "community": community[0] if community else None,
        "nodes": nodes,
    }


# ---------------------------------------------------------------------------
# Session tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_peer_sessions(peer_id: str) -> list[dict[str, Any]]:
    """List all sessions a peer has participated in."""
    return _sql(
        f"SELECT s.*, sp.role, sp.joined_at "
        f"FROM session s "
        f"INNER JOIN session_participant sp ON s.id = sp.session_id "
        f"WHERE sp.peer_id = '{_esc(peer_id)}' "
        f"ORDER BY sp.joined_at DESC"
    )


@mcp.tool()
def get_session_messages(session_id: str) -> list[dict[str, Any]]:
    """Retrieve all messages for a session, ordered by creation time."""
    return _sql(
        f"SELECT * FROM message WHERE session_id = '{_esc(session_id)}' "
        f"ORDER BY created_at ASC"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _esc(val: str) -> str:
    """Basic SQL string escaping for single-quoted string literals."""
    return val.replace("'", "''")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server using stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
