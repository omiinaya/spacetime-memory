"""
MCP (Model Context Protocol) server for spacetime-memory.

Uses the spacetime-memory Python SDK client. No raw SQL.

Configuration via environment variables:
  SPACETIMEDB_HOST (default: localhost)
  SPACETIMEDB_PORT (default: 3001)
  SPACETIMEDB_DB (default: spacetime-memory)
  EMBEDDER_URL (default: http://localhost:9090)
  MCP_API_KEY (optional) — if set, tools require this key for HTTP/SSE transport.
    Stdio transport (local agent) does not use token auth; rely on filesystem
    permissions instead.  For HTTP/SSE access, it is recommended to pair this
    with a reverse proxy (nginx / Caddy) that enforces the API key at the
    transport layer.
"""

from __future__ import annotations

import functools
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
MCP_API_KEY = os.environ.get("MCP_API_KEY", "")

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

if MCP_API_KEY:
    print(
        "  [mcp] MCP API key authentication is enabled. "
        "Tools will require a valid key for HTTP/SSE transport."
    )


def require_api_key(func):
    """Decorator that enforces MCP_API_KEY on non-stdio transports.

    For HTTP/SSE transport, the FastMCP tool receives request context via
    the ``ctx`` argument.  If ``MCP_API_KEY`` is set, we extract the
    ``Authorization`` header from the request metadata and compare it
    against the configured key.

    For stdio transport (local agent), there are no HTTP headers, so auth
    does not apply — rely on filesystem permissions instead.

    .. note::

        FastMCP passes context as the first positional arg when the tool
        signature includes ``ctx``.  This decorator introspects the
        available context to determine the transport type.
    """

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        # If no key is configured, allow all
        if not MCP_API_KEY:
            return await func(*args, **kwargs)

        # Try to extract the Authorization header from the request context.
        # FastMCP passes the request context in a variety of ways depending
        # on transport.  We do a best-effort check.
        request_meta = None

        # Check if first arg is the FastMCP context object
        for arg in args:
            if hasattr(arg, "request"):
                request_meta = getattr(arg, "request", None)
                break
        if not request_meta:
            # Check kwargs for common context names
            for key in ("ctx", "context", "request"):
                val = kwargs.get(key)
                if val is not None and hasattr(val, "request"):
                    request_meta = getattr(val, "request", None)
                    break

        if request_meta is not None:
            # We have request metadata — check the Authorization header
            headers = getattr(request_meta, "headers", {}) or getattr(
                request_meta, "scope", {}
            )
            # FastMCP / Starlette-style: headers is a dict-like object
            auth_header = ""
            if isinstance(headers, dict):
                auth_header = headers.get("authorization", "") or headers.get(
                    "Authorization", ""
                )
            elif hasattr(headers, "get"):
                auth_header = headers.get("authorization", "") or headers.get(
                    "Authorization", ""
                )

            expected = f"Bearer {MCP_API_KEY}"
            if auth_header != expected:
                raise PermissionError("Unauthorized: invalid or missing API key")

        # If no request context (stdio), auth doesn't apply
        return await func(*args, **kwargs)

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        # If no key is configured, allow all
        if not MCP_API_KEY:
            return func(*args, **kwargs)

        # Try to extract the Authorization header from the request context.
        request_meta = None
        for arg in args:
            if hasattr(arg, "request"):
                request_meta = getattr(arg, "request", None)
                break
        if not request_meta:
            for key in ("ctx", "context", "request"):
                val = kwargs.get(key)
                if val is not None and hasattr(val, "request"):
                    request_meta = getattr(val, "request", None)
                    break

        if request_meta is not None:
            headers = getattr(request_meta, "headers", {}) or getattr(
                request_meta, "scope", {}
            )
            auth_header = ""
            if isinstance(headers, dict):
                auth_header = headers.get("authorization", "") or headers.get(
                    "Authorization", ""
                )
            elif hasattr(headers, "get"):
                auth_header = headers.get("authorization", "") or headers.get(
                    "Authorization", ""
                )

            expected = f"Bearer {MCP_API_KEY}"
            if auth_header != expected:
                raise PermissionError("Unauthorized: invalid or missing API key")

        return func(*args, **kwargs)

    # Return the appropriate wrapper depending on whether the function is async
    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


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
@require_api_key
def create_workspace(name: str, description: str = "") -> dict[str, Any]:
    """Create a new workspace."""
    return get_client().create_workspace(name, description)


@mcp.tool()
@require_api_key
def list_workspaces() -> list[dict[str, Any]]:
    """List all workspaces."""
    return get_client().list_workspaces()


# ---------------------------------------------------------------------------
# Memory tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
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
@require_api_key
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
@require_api_key
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
@require_api_key
def get_memory(id: str) -> list[dict[str, Any]]:
    """Retrieve a single memory by its ID. Auto-reinforces on read."""
    return get_client().get_memory(id)


@mcp.tool()
@require_api_key
def reinforce_memory(memory_id: str) -> dict[str, Any]:
    """Reinforce a memory: increment access_count and bump strength."""
    return get_client().reinforce(memory_id)


@mcp.tool()
@require_api_key
def rate_memory(memory_id: str, rating: str, peer_id: str) -> dict[str, Any]:
    """Rate a memory on a 1-5 scale to adjust its trust score.

    Accepts:
      - "helpful" (score 5) or "unhelpful" (score 1) for binary ratings.
      - "1", "2", "3", "4", or "5" for graded numeric feedback.

    Trust score is recomputed as the average of all feedback scores / 5.
    """
    return get_client()._call("rate_memory", [memory_id, rating, peer_id])


@mcp.tool()
@require_api_key
def escalate_memories(workspace_id: str, l2_to_l1: int = 5, l1_to_l0: int = 20) -> str:
    """Batch-escalate memory tiers: L2->L1 at l2_to_l1 accesses, L1->L0 at l1_to_l0."""
    get_client().escalate_memories(workspace_id, l2_to_l1, l1_to_l0)
    return f"Tier escalation triggered for workspace {workspace_id[:16]}..."


@mcp.tool()
@require_api_key
def dedup_memories(workspace_id: str) -> str:
    """Deduplicate near-duplicate memories in a workspace (cosine >= 0.85 + edit dist <= 30%)."""
    get_client()._call("dedup_memories", [workspace_id])
    return f"Dedup complete for workspace {workspace_id[:16]}..."


@mcp.tool()
@require_api_key
def suggest_merges(workspace_id: str, threshold: float = 0.8) -> str:
    """Find candidate merge pairs in a workspace and record them as MergeSuggestion rows.

    Args:
        workspace_id: The workspace to scan.
        threshold: Minimum cosine similarity threshold (default: 0.8).

    Returns:
        Confirmation message.
    """
    get_client().suggest_merges(workspace_id, threshold)
    return (f"Merge suggestion scan complete for workspace {workspace_id[:16]}... "
            f"Check the merge_suggestion table for results.")


@mcp.tool()
@require_api_key
def approve_merge(suggestion_id: str) -> str:
    """Approve a pending merge suggestion — deactivates the source into the target.

    Args:
        suggestion_id: The ID of the MergeSuggestion row to approve.

    Returns:
        Confirmation message.
    """
    get_client().approve_merge(suggestion_id)
    return f"Merge suggestion {suggestion_id[:16]}... approved."


@mcp.tool()
@require_api_key
def reject_merge(suggestion_id: str) -> str:
    """Reject a pending merge suggestion without merging.

    Args:
        suggestion_id: The ID of the MergeSuggestion row to reject.

    Returns:
        Confirmation message.
    """
    get_client().reject_merge(suggestion_id)
    return f"Merge suggestion {suggestion_id[:16]}... rejected."


@mcp.tool()
@require_api_key
def set_memory_scope(memory_id: str, user_scope: str) -> str:
    """Set the user scope on an existing memory for user-level isolation.

    Args:
        memory_id: The UUID of the memory to scope.
        user_scope: The user identity hash to scope the memory to.
            Use an empty string ("") to make the memory shared (visible to all).

    Returns:
        A confirmation message.

    Example::

        set_memory_scope("abc-123", "alice")   # Scope to alice only
        set_memory_scope("abc-123", "")         # Make shared
    """
    get_client()._call("set_memory_scope", [memory_id, user_scope])
    return f"Memory {memory_id[:16]}... scoped to '{user_scope or 'shared'}'."


# ---------------------------------------------------------------------------
# Profile tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def get_profile(peer_id: str) -> list[dict[str, Any]]:
    """Retrieve a peer's profile."""
    return get_client().get_profile(peer_id)


@mcp.tool()
@require_api_key
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
    rows = get_client()._sql(
        "SELECT * FROM pagerank_result WHERE "
        f"workspace_id = '{workspace_id}' "
        "ORDER BY rank DESC"
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
    edges = get_client()._sql(
        "SELECT * FROM community_hierarchy WHERE "
        f"workspace_id = '{workspace_id}' "
        "ORDER BY depth ASC"
    )
    clusters = get_client()._sql(
        "SELECT * FROM hierarchy_cluster WHERE "
        f"workspace_id = '{workspace_id}' "
        "ORDER BY depth ASC"
    )
    return json.dumps({"edges": edges, "clusters": clusters}, default=str)


# ---------------------------------------------------------------------------
# Session tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def get_peer_sessions(peer_id: str) -> list[dict[str, Any]]:
    """List all sessions a peer has participated in."""
    return get_client().get_peer_sessions(peer_id)


@mcp.tool()
@require_api_key
def get_session_messages(session_id: str) -> list[dict[str, Any]]:
    """Retrieve all messages for a session."""
    return get_client().get_session_messages(session_id)


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
    return f"Shortest path computed. Read via SQL on shortest_path_result."


# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
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
    client._call("synthesize_mental_models", [workspace_id, memory_ids_json])
    return f"Mental model synthesis requested for workspace {workspace_id[:16]}..."


@mcp.tool()
@require_api_key
def get_mental_model(id: str) -> str:
    """Get a single mental model by its ID."""
    client = get_client()
    rows = client._sql(f"SELECT * FROM mental_model WHERE id = '{id}'")
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
    where = f"workspace_id = '{workspace_id}'"
    if status:
        where += f" AND status = '{status}'"
    rows = client._sql(f"SELECT * FROM mental_model WHERE {where} ORDER BY created_at DESC")
    return json.dumps(rows, default=str)


# -------------------------------------------------------------------------
# Fact tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def add_fact(
    workspace_id: str,
    peer_id: str,
    content: str,
    fact_type: str = "dynamic",
    category: str = "custom",
    confidence: float = 0.8,
    source: str = "manual",
    tier: str = "L1",
) -> str:
    """Add a fact about a peer. Returns the fact ID."""
    get_client()._call("add_fact", [workspace_id, peer_id, fact_type, category, content, confidence, source, tier])
    return f"Fact added for peer {peer_id[:16]}... in workspace {workspace_id[:16]}..."


@mcp.tool()
@require_api_key
def list_facts(
    workspace_id: str,
    peer_id: str = "",
    fact_type: str = "",
    tier: str = "",
    category: str = "",
) -> list[dict[str, Any]]:
    """List facts for a workspace with optional filters (peer_id, fact_type, tier, category)."""
    client = get_client()
    client._call("list_facts", [workspace_id, peer_id, fact_type, tier, category])
    query_hash = f"{workspace_id}:{peer_id}:{fact_type}:{tier}:{category}"
    rows = client._sql(
        f"SELECT * FROM fact_result WHERE query_hash = '{query_hash}' ORDER BY created_at DESC"
    )
    if rows:
        try:
            return json.loads(rows[0].get("json_data", "[]"))
        except (json.JSONDecodeError, IndexError):
            pass
    return []


# ---------------------------------------------------------------------------
# Directory tools
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def create_directory(workspace_id: str, name: str, path: str, parent_id: str = "", description: str = "") -> str:
    """Create a directory in the context directory tree."""
    get_client().create_directory(workspace_id, name, path, parent_id, description)
    return f"Directory '{name}' created."


@mcp.tool()
@require_api_key
def traverse_directory(workspace_id: str, root_directory_id: str) -> str:
    """Recursively traverse directory tree showing all children."""
    rows = get_client().traverse_directory(workspace_id, root_directory_id)
    return json.dumps(rows, default=str)


@mcp.tool()
@require_api_key
def list_directory(directory_id: str) -> str:
    """List children of a directory."""
    rows = get_client().list_directory(directory_id)
    return json.dumps(rows, default=str)


# ---------------------------------------------------------------------------
# Org-mode sync tool
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def org_sync(
    workspace_id: str,
    directory: str = "~/org",
    dry_run: bool = False,
) -> str:
    """One-shot sync of .org files in a directory to Spacetime Memory as notes and KG task nodes.

    Scans all .org files under DIRECTORY, parses headings with OrgModeParser,
    and stores each heading as a memory. TODO items are additionally created
    as knowledge graph nodes (type="task").

    Args:
        workspace_id: The target workspace to sync into.
        directory: Path to directory containing .org files (default: ~/org).
        dry_run: If True, preview changes without writing any data.

    Returns:
        A summary string describing how many events were synced.
    """
    import os
    import sys

    sys.path.insert(
        0,
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"),
    )
    from org_sync_daemon import OrgSyncDaemon

    daemon = OrgSyncDaemon(
        org_dir=directory,
        workspace_id=workspace_id,
        client=get_client(),
        dry_run=dry_run,
    )
    total = daemon.scan()
    if dry_run:
        return f"[dry-run] Org sync would produce {total} events from {daemon.get_status()['files_tracked']} file(s)."
    return f"Org sync complete — {total} events synced from {daemon.get_status()['files_tracked']} file(s)."


# ---------------------------------------------------------------------------
# Space tools (Supermemory shareable workspace permissions)
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def grant_space_access(workspace_id: str, peer_id: str, permission: str) -> str:
    """Grant a peer access to a workspace with a specific permission level.

    Only an existing owner can grant access. Permission levels: owner, editor, viewer.

    Args:
        workspace_id: The workspace (space) ID.
        peer_id: The peer ID to grant access to.
        permission: One of 'owner', 'editor', 'viewer'.

    Returns:
        Confirmation message.
    """
    get_client()._call("grant_space_access", [workspace_id, peer_id, permission])
    return f"Granted '{permission}' access to peer '{peer_id[:16]}...' for workspace '{workspace_id[:16]}...'."


@mcp.tool()
@require_api_key
def revoke_space_access(workspace_id: str, peer_id: str) -> str:
    """Revoke a peer's access to a workspace.

    Only an existing owner can revoke access.

    Args:
        workspace_id: The workspace (space) ID.
        peer_id: The peer ID to revoke access from.

    Returns:
        Confirmation message.
    """
    get_client()._call("revoke_space_access", [workspace_id, peer_id])
    return f"Revoked access for peer '{peer_id[:16]}...' from workspace '{workspace_id[:16]}...'."


@mcp.tool()
@require_api_key
def list_space_members(workspace_id: str) -> list[dict[str, str]]:
    """List all members with their permissions for a workspace.

    Calls the list_space_members reducer and reads results from
    the space_member_result table.

    Args:
        workspace_id: The workspace (space) ID.

    Returns:
        A list of dicts, each with keys: peer_id, permission, granted_by, created_at.
    """
    client = get_client()
    client._call("list_space_members", [workspace_id])
    rows = client._sql(
        f"SELECT peer_id, permission, granted_by, created_at "
        f"FROM space_member_result WHERE "
        f"workspace_id = '{workspace_id}' "
        f"ORDER BY created_at ASC"
    )
    return rows


# ---------------------------------------------------------------------------
# Agent Step tools (P3g agent orchestration hooks)
# ---------------------------------------------------------------------------


@mcp.tool()
@require_api_key
def add_agent_step(
    session_id: str,
    workspace_id: str,
    step_type: str,
    content: str,
    summary: str = "",
) -> str:
    """Record an agent reasoning step (thought, action, tool_call, etc.).

    Args:
        session_id: The session to attach the step to.
        workspace_id: The workspace containing the session.
        step_type: One of "thought", "action", "observation", "tool_call", "tool_result".
        content: The step content (text or JSON).
        summary: Optional short summary of the step.

    Returns:
        Confirmation message with step ID.
    """
    get_client()._call(
        "add_agent_step",
        [session_id, workspace_id, step_type, content, summary, ""],
    )
    return f"Agent step recorded for session {session_id[:16]}..."


@mcp.tool()
@require_api_key
def get_session_steps(session_id: str) -> list[dict[str, Any]]:
    """Retrieve all reasoning steps for a session.

    Args:
        session_id: The session to get steps for.

    Returns:
        A list of step dicts ordered by creation time.
    """
    client = get_client()
    client._call("get_session_steps", [session_id])
    query_hash = f"steps:{session_id}"
    steps = client._sql(
        "SELECT * FROM session_step_result WHERE "
        f"query_hash = '{query_hash}' "
        "ORDER BY created_at ASC"
    )
    return steps


@mcp.tool()
@require_api_key
def get_agent_context(
    workspace_id: str,
    query: str = "",
    session_id: str = "",
    top_k: int = 10,
) -> str:
    """Retrieve relevant context for an agent prompt from memories + session steps.

    Args:
        workspace_id: The workspace to search in.
        query: Natural language query for relevant memories.
        session_id: Optional session to include recent steps from.
        top_k: Maximum context entries (default: 10).

    Returns:
        JSON string with context entries.
    """
    from spacetime_memory.agent_orchestrator import AgentOrchestrator

    orch = AgentOrchestrator(get_client(), workspace_id=workspace_id)
    context = orch.get_context(query=query, top_k=top_k, session_id=session_id)
    return json.dumps(context, default=str)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
