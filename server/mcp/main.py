"""
MCP (Model Context Protocol) server for spacetime-memory.

Connects to a SpacetimeDB instance via its HTTP API and exposes ~15 MCP tools
covering workspaces, memories, profiles, knowledge graph, sessions, and search.
Uses stdio transport for integration with MCP-compatible clients.

Configuration via environment variables:
  SPACETIMEDB_HOST   (default: localhost)
  SPACETIMEDB_PORT   (default: 3001)
  SPACETIMEDB_DB     (default: spacetime-memory)
  EMBEDDER_URL       (default: http://localhost:9090)
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

EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://localhost:9090")

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
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Embedder client (Rust ONNX sidecar)
# ---------------------------------------------------------------------------


def _embed(text: str) -> list[float]:
    """Generate an embedding vector via the Rust ONNX embedder sidecar."""
    try:
        resp = get_client().post(
            f"{EMBEDDER_URL}/embed",
            content=json.dumps({"text": text}),
            headers={"Content-Type": "application/json"},
            timeout=10.0,
        )
        if resp.status_code >= 400:
            return []
        data = resp.json()
        return data.get("embedding", [])
    except Exception:
        # Embedder unavailable — return empty (semantic search disabled)
        return []


def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for multiple texts in one call."""
    if not texts:
        return []
    try:
        resp = get_client().post(
            f"{EMBEDDER_URL}/embed",
            content=json.dumps({"text": "", "texts": texts}),
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )
        if resp.status_code >= 400:
            return []
        data = resp.json()
        return data.get("embeddings", [])
    except Exception:
        return []


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
    Automatically generates an embedding index for semantic search.
    """
    result = _call("store_memory", [
        workspace_id, peer_id, observer_id,
        memory_type, content, summary, entities_json,
        confidence, source_session_id, source_message_id,
    ])

    # Generate embedding and index
    emb = _embed(content)
    if emb:
        # Find the memory id that was just created
        mems = _sql(
            "SELECT id FROM memory WHERE "
            f"workspace_id = '{_esc(workspace_id)}' AND "
            f"peer_id = '{_esc(peer_id)}' "
            "ORDER BY created_at DESC LIMIT 1"
        )
        if mems:
            mem_id = mems[0]["id"]
            _call("index_entity", [
                workspace_id, "memory", mem_id,
                content, json.dumps(emb),
            ])

    # If tier is specified, update it after creation
    if tier and tier in ("L0", "L1", "L2"):
        mems = _sql(
            "SELECT id FROM memory WHERE "
            f"workspace_id = '{_esc(workspace_id)}' AND "
            f"peer_id = '{_esc(peer_id)}' "
            "ORDER BY created_at DESC LIMIT 1"
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
    and tier filters.  Auto-reinforces every memory returned.
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
    results = _sql(
        f"SELECT * FROM memory WHERE {where} ORDER BY created_at DESC LIMIT {int(limit)}"
    )
    # Auto-reinforce every memory returned
    for row in results:
        try:
            _call("reinforce_memory", [row["id"]])
        except Exception:
            pass
    return results


@mcp.tool()
def hybrid_search(
    workspace_id: str,
    query_text: str,
    memory_type: str = "",
    tier: str = "",
    limit: int = 20,
    strategies: str = "semantic,keyword,graph,temporal",
) -> list[dict[str, Any]]:
    """Multi-strategy search across memories, KG nodes, and temporal data.

    Uses real vector embeddings (from the ONNX embedder) for the 'semantic'
    strategy. Query text is embedded at search time.

    Args:
        workspace_id: Scope the search.
        query_text: Natural-language query.
        memory_type: Optional filter (world_fact/experience/mental_model).
        tier: Optional filter (L0/L1/L2).
        limit: Max results per strategy.
        strategies: Comma-separated strategy names or empty for all.

    Returns rows from the hybrid_result table (read after reducer call).
    """
    # Embed the query text for semantic search
    query_embedding = _embed(query_text)
    query_emb_json = json.dumps(query_embedding) if query_embedding else "[]"

    strategy_list = [s.strip() for s in strategies.split(",") if s.strip()]
    strategies_json = json.dumps(strategy_list) if strategy_list else ""

    _call("hybrid_search", [
        workspace_id, query_text, query_emb_json,
        memory_type, tier, limit, strategies_json,
    ])

    # Read back results via SQL
    qhash = _query_hash(query_text)
    results = _sql(
        "SELECT hr.*, "
        "  COALESCE(m.content, '') AS memory_content, "
        "  COALESCE(k.label, '') AS node_label "
        "FROM hybrid_result hr "
        "LEFT JOIN memory m ON hr.entity_type = 'memory' AND hr.entity_id = m.id "
        "LEFT JOIN kg_node k ON hr.entity_type = 'node' AND hr.entity_id = k.id "
        f"WHERE hr.workspace_id = '{_esc(workspace_id)}' "
        f"  AND hr.query_hash = '{_esc(qhash)}' "
        "ORDER BY hr.score DESC "
        f"LIMIT {int(limit * 4)}"
    )

    # Auto-reinforce every memory returned by the search
    for row in results:
        if row.get("entity_type") == "memory" and row.get("entity_id"):
            try:
                _call("reinforce_memory", [row["entity_id"]])
            except Exception:
                pass  # embedder or reducer temporarily offline — skip

    return results


@mcp.tool()
def get_memory(id: str) -> list[dict[str, Any]]:
    """Retrieve a single memory by its ID.  Auto-reinforces on read."""
    results = _sql(f"SELECT * FROM memory WHERE id = '{_esc(id)}'")
    if results:
        try:
            _call("reinforce_memory", [id])
        except Exception:
            pass
    return results


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
def create_node(
    workspace_id: str,
    label: str,
    node_type: str,
    summary: str = "",
    metadata_json: str = "{}",
) -> dict[str, Any]:
    """Create a knowledge graph node and index it for semantic search.

    Valid node_type values: code, concept, entity, document, topic.
    """
    result = _call("create_node", [workspace_id, label, node_type, summary, metadata_json])

    # Generate embedding and index
    content = f"{label}: {summary}" if summary else label
    emb = _embed(content)
    if emb:
        # Find the node id that was just created
        nodes = _sql(
            "SELECT id FROM kg_node WHERE "
            f"workspace_id = '{_esc(workspace_id)}' AND "
            f"label = '{_esc(label)}' "
            "ORDER BY created_at DESC LIMIT 1"
        )
        if nodes:
            node_id = nodes[0]["id"]
            _call("index_entity", [
                workspace_id, "node", node_id,
                content, json.dumps(emb),
            ])

    return result


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


def _query_hash(query: str) -> str:
    """Compute the same query hash as the Rust hybrid_query reducer."""
    h = 0
    for b in query.encode("utf-8"):
        h = ((h * 6364136223846793005) + b) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP server using stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
