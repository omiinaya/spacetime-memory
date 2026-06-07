"""
MCP (Model Context Protocol) server for spacetime-memory.

Uses the spacetime-memory Python SDK client. No raw SQL.

Configuration via environment variables:
  SPACETIMEDB_HOST (default: localhost)
  SPACETIMEDB_PORT (default: 3001)
  SPACETIMEDB_DB (default: spacetime-memory)
  EMBEDDER_URL (default: http://localhost:9090)
"""

from __future__ import annotations

import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from spacetime_memory import Client

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get("SPACETIMEDB_DB", "spacetime-memory")
EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://localhost:9090")

# ---------------------------------------------------------------------------
# MCP server + SDK Client
# ---------------------------------------------------------------------------

mcp = FastMCP("spacetime-memory", log_level="WARNING")

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(
            host=HOST,
            port=PORT,
            database=DB,
            embedder_url=EMBEDDER_URL,
        )
    return _client


# Embedder helpers (also available via Client, re-exported for convenience)


def _embed(text: str) -> list[float]:
    return get_client()._embed(text)


def _embed_batch(texts: list[str]) -> list[list[float]]:
    return get_client()._embed_batch(texts)


# ---------------------------------------------------------------------------
# Workspace tools
# ---------------------------------------------------------------------------


@mcp.tool()
def create_workspace(name: str, description: str = "") -> dict[str, Any]:
    """Create a new workspace."""
    return get_client().create_workspace(name, description)


@mcp.tool()
def list_workspaces() -> list[dict[str, Any]]:
    """List all workspaces."""
    return get_client().list_workspaces()


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
    """Store a new memory with optional tier override."""
    return get_client().store(
        workspace_id=workspace_id,
        content=content,
        summary=summary,
        memory_type=memory_type,
        peer_id=peer_id,
        observer_id=observer_id,
        entities_json=entities_json,
        confidence=confidence,
        source_session_id=source_session_id,
        source_message_id=source_message_id,
        tier=tier,
    )


@mcp.tool()
def search_memories(
    workspace_id: str,
    query_text: str = "",
    memory_type: str = "",
    tier: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search memories via keyword with optional filters."""
    return get_client().search(
        workspace_id=workspace_id,
        query=query_text,
        memory_type=memory_type,
        tier=tier,
        limit=limit,
        semantic=True,
    )


@mcp.tool()
def hybrid_search(
    workspace_id: str,
    query_text: str,
    memory_type: str = "",
    tier: str = "",
    limit: int = 20,
    strategies: str = "semantic,keyword,graph,temporal",
) -> list[dict[str, Any]]:
    """Multi-strategy hybrid search across memories, KG nodes, and temporal data."""
    return get_client().search(
        workspace_id=workspace_id,
        query=query_text,
        memory_type=memory_type,
        tier=tier,
        limit=limit,
        semantic=True,
    )


@mcp.tool()
def get_memory(id: str) -> list[dict[str, Any]]:
    """Retrieve a single memory by its ID. Auto-reinforces on read."""
    return get_client().get_memory(id)


@mcp.tool()
def reinforce_memory(memory_id: str) -> dict[str, Any]:
    """Reinforce a memory: increment access_count and bump strength."""
    return get_client().reinforce(memory_id)


@mcp.tool()
def rate_memory(memory_id: str, rating: str, peer_id: str) -> dict[str, Any]:
    """Rate a memory as 'helpful' or 'unhelpful' to adjust its trust score."""
    return get_client()._call("rate_memory", [memory_id, rating, peer_id])


@mcp.tool()
def escalate_memories(workspace_id: str, l2_to_l1: int = 5, l1_to_l0: int = 20) -> str:
    """Batch-escalate memory tiers: L2→L1 at l2_to_l1 accesses, L1→L0 at l1_to_l0."""
    get_client()._call("escalate_memories", [workspace_id, l2_to_l1, l1_to_l0])
    return f"Tier escalation triggered for workspace {workspace_id[:16]}..."


# ---------------------------------------------------------------------------
# Profile tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_profile(peer_id: str) -> list[dict[str, Any]]:
    """Retrieve a peer's profile."""
    return get_client().get_profile(peer_id)


@mcp.tool()
def upsert_profile(
    peer_id: str,
    static_facts_json: str = "[]",
    dynamic_context_json: str = "[]",
    preferences_json: str = "{}",
    tags_json: str = "[]",
) -> dict[str, Any]:
    """Create or update a peer profile."""
    return get_client().upsert_profile(
        peer_id, static_facts_json, dynamic_context_json,
        preferences_json, tags_json,
    )


# ---------------------------------------------------------------------------
# Knowledge Graph tools
# ---------------------------------------------------------------------------


@mcp.tool()
def create_node(
    workspace_id: str,
    label: str,
    node_type: str,
    summary: str = "",
    metadata_json: str = "{}",
) -> dict[str, Any]:
    """Create a knowledge graph node and index it for semantic search."""
    return get_client().create_node(workspace_id, label, node_type, summary, metadata_json)


@mcp.tool()
def query_graph(workspace_id: str, query: str = "") -> list[dict[str, Any]]:
    """Search knowledge graph nodes by label within a workspace."""
    return get_client().query_graph(workspace_id, query)


@mcp.tool()
def get_node(id: str) -> list[dict[str, Any]]:
    """Retrieve a knowledge graph node by its ID."""
    return get_client().get_node(id)


@mcp.tool()
def get_neighbors(node_id: str) -> list[dict[str, Any]]:
    """Get all edges (neighbors) connected to a node."""
    return get_client().get_neighbors(node_id)


@mcp.tool()
def get_community(community_id: int) -> dict[str, Any]:
    """Get community details and list all nodes in that community."""
    return get_client().get_community(community_id)


# ---------------------------------------------------------------------------
# Session tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_peer_sessions(peer_id: str) -> list[dict[str, Any]]:
    """List all sessions a peer has participated in."""
    return get_client().get_peer_sessions(peer_id)


@mcp.tool()
def get_session_messages(session_id: str) -> list[dict[str, Any]]:
    """Retrieve all messages for a session."""
    return get_client().get_session_messages(session_id)


# ---------------------------------------------------------------------------
# KG Graph Traversal tools
# ---------------------------------------------------------------------------


@mcp.tool()
def graph_bfs(workspace_id: str, start_node_id: str, max_depth: int = 3) -> str:
    """BFS traverse the knowledge graph from a node. Results in graph_traversal_result table."""
    get_client().graph_bfs(workspace_id, start_node_id, max_depth)
    return f"BFS from {start_node_id} up to depth {max_depth} completed. Read via SQL on graph_traversal_result."


@mcp.tool()
def shortest_path(workspace_id: str, source_id: str, target_id: str, max_hops: int = 6) -> str:
    """Find shortest path between two KG nodes. Results in shortest_path_result table."""
    get_client().shortest_path(workspace_id, source_id, target_id, max_hops)
    return f"Shortest path computed. Read via SQL on shortest_path_result."


# ---------------------------------------------------------------------------
# Tour tools
# ---------------------------------------------------------------------------


@mcp.tool()
def create_tour(workspace_id: str, title: str, description: str = "") -> str:
    """Create a new guided tour through KG nodes."""
    get_client().create_tour(workspace_id, title, description)
    return f"Tour '{title}' created."


@mcp.tool()
def add_tour_stop(tour_id: str, node_id: str, heading: str, description: str = "") -> str:
    """Add a stop to an existing tour."""
    get_client().add_tour_stop(tour_id, node_id, heading, description)
    return f"Stop '{heading}' added to tour."


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
