"""MCP tools — Knowledge Graph tools."""

from __future__ import annotations

from typing import Any

from server.mcp.tools.app import get_client, mcp, require_api_key
import json
# Knowledge Graph tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
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
@require_api_key
def update_node(
    node_id: str,
    label: str,
    node_type: str = "concept",
    summary: str = "",
    metadata_json: str = "{}",
    source_memory_id: str = "",
) -> dict[str, Any]:
    """Update an existing knowledge graph node's mutable fields.

    Args:
        node_id: The ID of the node to update.
        label: New label (display name).
        node_type: Type category (default: ``"concept"``).
        summary: Updated summary text.
        metadata_json: Updated JSON metadata string.
        source_memory_id: Optional source memory ID.
    """
    return get_client().update_node(
        node_id, label, node_type, summary, metadata_json,
        source_memory_id,
    )


@mcp.tool()
@require_api_key
def delete_node(
    node_id: str,
) -> dict[str, Any]:
    """Soft-delete a knowledge graph node by ID.

    Removes the node from the KG. The node's edges remain but become orphaned.

    Args:
        node_id: The ID of the node to delete.
    """
    return get_client().delete_node(node_id)


@mcp.tool()
@require_api_key
def create_edge(
    workspace_id: str,
    source_node_id: str,
    target_node_id: str,
    relation: str,
    weight: float = 1.0,
    confidence: str = "EXTRACTED",
    metadata_json: str = "{}",
    source_memory_id: str = "",
) -> dict[str, Any]:
    """Create a directed, typed edge between two knowledge graph nodes.

    Args:
        workspace_id: Target workspace.
        source_node_id: Source node ID.
        target_node_id: Target node ID.
        relation: Relationship type label (e.g. "informed_by", "related_to", "part_of").
        weight: Edge weight (default: 1.0).
        confidence: Confidence level (default: "EXTRACTED").
        metadata_json: Optional JSON metadata string.
        source_memory_id: Optional memory record ID that supports this edge.
    """
    return get_client().create_edge(
        workspace_id, source_node_id, target_node_id,
        relation, weight, confidence, metadata_json,
        source_memory_id,
    )


@mcp.tool()
@require_api_key
def update_edge(
    edge_id: str,
    relation: str,
    weight: float = 1.0,
    metadata_json: str = "{}",
) -> dict[str, Any]:
    """Update an existing knowledge-graph edge's mutable fields.

    Args:
        edge_id: The ID of the edge to update.
        relation: New relationship type label.
        weight: New edge weight (default: 1.0).
        metadata_json: Updated JSON metadata string.

    Returns:
        Dict with operation status and updated edge details.
    """
    return get_client().update_edge(
        edge_id, relation, weight, metadata_json,
    )


@mcp.tool()
@require_api_key
def delete_edge(
    edge_id: str,
) -> dict[str, Any]:
    """Soft-delete a knowledge graph edge by ID.

    Removes the edge from the KG.

    Args:
        edge_id: The ID of the edge to delete.
    """
    return get_client().delete_edge(edge_id)


@mcp.tool()
@require_api_key
def add_node_citation(
    workspace_id: str,
    node_id: str,
    memory_id: str,
    description: str = "",
) -> dict[str, Any]:
    """Add a citation linking a KG node to a supporting source memory.

    Citations provide provenance: they record which memory (raw source,
    note, or observation) supports a particular knowledge-graph node.

    Args:
        workspace_id: Target workspace.
        node_id: The knowledge graph node ID.
        memory_id: The memory record that supports this node.
        description: Optional description of the citation relationship.

    Returns:
        Dict with operation status and citation details.
    """
    return get_client().add_node_citation(
        workspace_id, node_id, memory_id, description,
    )


@mcp.tool()
@require_api_key
def add_edge_citation(
    workspace_id: str,
    edge_id: str,
    memory_id: str,
    description: str = "",
) -> dict[str, Any]:
    """Add a citation linking a KG edge to a supporting source memory.

    Citations provide provenance for edges — useful for marking which
    source memory supports a particular ``informed_by``, ``related_to``,
    or ``contradicts`` relationship between nodes.

    Args:
        workspace_id: Target workspace.
        edge_id: The knowledge graph edge ID.
        memory_id: The memory record that supports this edge.
        description: Optional description of the citation relationship.

    Returns:
        Dict with operation status and citation details.
    """
    return get_client().add_edge_citation(
        workspace_id, edge_id, memory_id, description,
    )


@mcp.tool()
@require_api_key
def get_citations(
    workspace_id: str,
    entity_id: str,
    entity_type: str = "node",
) -> list[dict[str, Any]]:
    """Get all citations for a KG entity (node or edge).

    Citations link KG nodes/edges back to the source memories that
    support them. Use this to trace provenance for any KG entity.

    Args:
        workspace_id: Target workspace.
        entity_id: The node or edge ID.
        entity_type: ``"node"`` (default) or ``"edge"``.

    Returns:
        List of citation records, each with source_memory_id,
        description, and timestamp.
    """
    return get_client().get_citations(
        workspace_id, entity_id, entity_type,
    )


@mcp.tool()
@require_api_key
def get_edge_history(edge_group_id: str) -> list[dict[str, Any]]:
    """Get all historical versions of a KG edge.

    Edges in the knowledge graph are versioned — when an edge is updated
    a new version is created with the same ``edge_group_id``. This tool
    returns every version ordered by ``created_at``, letting you trace
    how a relationship evolved over time.

    Args:
        edge_group_id: The group ID shared by all versions of the edge.
    """
    return get_client().get_edge_history(edge_group_id)


@mcp.tool()
@require_api_key
def get_edge_as_of(edge_group_id: str, timestamp_micros: int) -> dict[str, Any] | None:
    """Get an edge version as of a specific point in time (temporal query).

    Queries the KG for an edge that was valid at the given Unix timestamp
    (in microseconds). An edge is considered valid at time ``t`` if:
    ``valid_at <= t < invalid_at`` (or ``invalid_at == 0`` for edges
    that are still valid).

    This provides parity with Mnemosyne/Graphiti ``as_of`` temporal queries.

    Args:
        edge_group_id: The group ID of the edge to query.
        timestamp_micros: Unix timestamp in microseconds to query at.
    """
    return get_client().get_edge_as_of(edge_group_id, timestamp_micros)


@mcp.tool()
@require_api_key
def query_graph(workspace_id: str, query: str = "") -> list[dict[str, Any]]:
    """Search knowledge graph nodes by label within a workspace."""
    return get_client().query_graph(workspace_id, query)


@mcp.tool()
@require_api_key
def get_node(id: str) -> list[dict[str, Any]]:
    """Retrieve a knowledge graph node by its ID."""
    return get_client().get_node(id)


@mcp.tool()
@require_api_key
def get_neighbors(node_id: str) -> list[dict[str, Any]]:
    """Get all edges (neighbors) connected to a node."""
    return get_client().get_neighbors(node_id)


@mcp.tool()
@require_api_key
def get_community(community_id: int) -> dict[str, Any]:
    """Get community details and list all nodes in that community."""
    return get_client().get_community(community_id)


@mcp.tool()
@require_api_key
def compute_pagerank(workspace_id: str, damping: float = 0.85, max_iterations: int = 100) -> str:
    """Compute PageRank centrality for all nodes in a workspace.

    Args:
        workspace_id: The workspace to compute PageRank for.
        damping: PageRank damping factor (default: 0.85).
        max_iterations: Maximum iterations (default: 100).

    Returns:
        Summary string with the number of nodes ranked.
    """
    get_client().compute_pagerank(workspace_id, damping, max_iterations)
    # Read back the results
    client = get_client()
    rows = client._sql_param(
        "SELECT * FROM pagerank_result WHERE "
        "workspace_id = ? "
        "ORDER BY rank DESC",
        workspace_id,
    )
    return json.dumps(rows, default=str)


@mcp.tool()
@require_api_key
def compute_community_hierarchy(workspace_id: str) -> str:
    """Build hierarchical community dendrogram using agglomerative clustering.

    Args:
        workspace_id: The workspace to build hierarchy for.

    Returns:
        JSON string with hierarchy edges and clusters.
    """
    get_client().compute_community_hierarchy(workspace_id)
    # Read back the hierarchy
    client = get_client()
    edges = client._sql_param(
        "SELECT * FROM community_hierarchy WHERE "
        "workspace_id = ? "
        "ORDER BY depth ASC",
        workspace_id,
    )
    clusters = client._sql_param(
        "SELECT * FROM hierarchy_cluster WHERE "
        "workspace_id = ? "
        "ORDER BY depth ASC",
        workspace_id,
    )
    return json.dumps({"edges": edges, "clusters": clusters}, default=str)


@mcp.tool()
@require_api_key
def compute_kg_stats(workspace_id: str) -> str:
    """Compute knowledge graph statistics for a workspace.

    Returns node_count, edge_count, community_count, orphan_nodes,
    avg_degree, and other KG metrics for health monitoring.

    Args:
        workspace_id: The workspace to compute stats for.

    Returns:
        JSON string with KG statistics.
    """
    result = get_client().compute_kg_stats(workspace_id)
    if result is None:
        return json.dumps({"workspace_id": workspace_id, "error": "No stats found"})
    return json.dumps(result, default=str)


@mcp.tool()
@require_api_key
def get_memory_stats(workspace_id: str) -> str:
    """Collect per-workspace memory metrics.

    Returns total_memories, active_memories, by_tier, by_type,
    avg_confidence, avg_age_seconds, total_revisions, top_tags,
    and total_users as a JSON dict.

    Args:
        workspace_id: The workspace to compute memory stats for.

    Returns:
        JSON string with memory statistics.
    """
    result = get_client().get_memory_stats(workspace_id)
    if result is None:
        return json.dumps({"workspace_id": workspace_id, "error": "No stats found"})
    return json.dumps(result, default=str)


@mcp.tool()
@require_api_key
def detect_communities(workspace_id: str) -> dict[str, Any]:
    """Run label-propagation community detection on the knowledge graph.

    Identifies communities of closely-connected nodes within a workspace
    using a label-propagation algorithm. Each node gets assigned a
    ``community_id``.

    Args:
        workspace_id: The workspace to run detection on.

    Returns:
        Dict with status, nodes_processed, and communities_found.
    """
    result = get_client().detect_communities(workspace_id)
    if result is None:
        return {"workspace_id": workspace_id, "error": "No result"}
    return result


@mcp.tool()
@require_api_key
def seed_communities(workspace_id: str) -> dict[str, Any]:
    """Seed unassigned KG nodes into new communities.

    Takes any knowledge-graph nodes that do not yet belong to a community
    and assigns them to new communities using label-propagation seeding.
    Useful after adding new nodes to an existing workspace.

    Args:
        workspace_id: The workspace to seed communities in.

    Returns:
        Dict with reducer response status.
    """
    return get_client().seed_communities(workspace_id)


@mcp.tool()
@require_api_key
def detect_bridge_nodes(
    workspace_id: str,
    limit: int = 20,
    min_communities: int = 2,
) -> str:
    """Detect bridge nodes — concepts that connect multiple communities.

    Bridge nodes are knowledge-graph entities that belong to or are
    referenced by multiple communities, making them integration points
    between otherwise separate knowledge clusters. Results are stored
    in the ``bridge_result`` table and returned here sorted by bridge
    score (higher = more integrative).

    Args:
        workspace_id: The workspace to analyze.
        limit: Max bridge nodes to return (default: 20).
        min_communities: Minimum number of communities a node must
            bridge to be included (default: 2).

    Returns:
        JSON string with bridge nodes sorted by score descending.
    """
    import json as _json

    rows = get_client().detect_bridge_nodes(workspace_id, limit, min_communities)
    return _json.dumps(rows, default=str)


# ---------------------------------------------------------------------------
# KG Graph Traversal tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def graph_bfs(workspace_id: str, start_node_id: str, max_depth: int = 3) -> str:
    """BFS traverse the knowledge graph from a node. Results in graph_traversal_result table."""
    get_client().graph_bfs(workspace_id, start_node_id, max_depth)
    return f"BFS from {start_node_id} up to depth {max_depth} completed. Read via SQL on graph_traversal_result."


@mcp.tool()
@require_api_key
def shortest_path(workspace_id: str, source_id: str, target_id: str, max_hops: int = 6) -> str:
    """Find shortest path between two KG nodes. Results in shortest_path_result table."""
    get_client().shortest_path(workspace_id, source_id, target_id, max_hops)
    return "Shortest path computed. Read via SQL on shortest_path_result."


# ---------------------------------------------------------------------------
