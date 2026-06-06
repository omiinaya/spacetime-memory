#!/usr/bin/env python3
"""stmem — Spacetime-Memory CLI.

A command-line interface for managing memory from the terminal,
using the spacetime-memory Python SDK.

Configuration via environment variables:
    STMEM_HOST / SPACETIMEDB_HOST (default: localhost)
    STMEM_PORT / SPACETIMEDB_PORT (default: 3001)
    STMEM_DB / SPACETIMEDB_DB (default: spacetime-memory)
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import click
import httpx
from rich.console import Console
from rich.table import Table
from rich import box

from spacetime_memory import Client

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HOST = os.environ.get("STMEM_HOST", os.environ.get("SPACETIMEDB_HOST", "localhost"))
PORT = os.environ.get("STMEM_PORT", os.environ.get("SPACETIMEDB_PORT", "3001"))
DB = os.environ.get("STMEM_DB", os.environ.get("SPACETIMEDB_DB", "spacetime-memory"))
EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://localhost:9090")

console = Console()


def _sdk_client() -> Client:
    """Build an SDK Client from the CLI's env-var config."""
    return Client(
        host=HOST, port=PORT, database=DB,
        embedder_url=EMBEDDER_URL,
    )


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def print_table(rows: list[dict[str, Any]], title: str = "") -> None:
    """Print query results as a Rich table."""
    if not rows:
        console.print("[yellow]No results found.[/yellow]")
        return
    table = Table(title=title, box=box.ROUNDED, header_style="bold cyan")
    cols = list(rows[0].keys())
    for c in cols:
        table.add_column(c, overflow="fold")
    for row in rows:
        vals = [str(row.get(c, "")) for c in cols]
        table.add_row(*vals)
    console.print(table)


def print_json(data: Any) -> None:
    """Print data as formatted JSON."""
    console.print_json(json.dumps(data) if not isinstance(data, str) else data)


def parse_json_flag(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    """Click callback that validates JSON is parseable."""
    if value is None:
        return value
    try:
        json.loads(value)
    except json.JSONDecodeError as e:
        raise click.BadParameter(f"Invalid JSON: {e}")
    return value


# ---------------------------------------------------------------------------
# stmem CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(version="0.1.0", prog_name="stmem")
def cli() -> None:
    """stmem — Spacetime-Memory CLI.

    Manage workspaces, peers, memories, profiles, knowledge graphs, and sessions
    on a SpacetimeDB instance.
    """


# ===================================================================
# workspace commands
# ===================================================================


@cli.group()
def workspace() -> None:
    """Manage workspaces."""


@workspace.command(name="create")
@click.argument("name")
@click.argument("description", default="")
def workspace_create(name: str, description: str) -> None:
    """Create a new workspace."""
    client = _sdk_client()
    with console.status(f"Creating workspace '{name}'..."):
        result = client.create_workspace(name, description)
    console.print(f"[green]Workspace '{name}' created successfully.[/green]")
    if result:
        print_json(result)


@workspace.command(name="list")
def workspace_list() -> None:
    """List all workspaces."""
    with console.status("Fetching workspaces..."):
        rows = _sdk_client().list_workspaces()
    rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
    print_table(rows, title="Workspaces")


# ===================================================================
# peer commands
# ===================================================================


@cli.group()
def peer() -> None:
    """Manage peers."""


@peer.command(name="create")
@click.argument("workspace_id")
@click.argument("name")
@click.argument("peer_type", type=click.Choice(["user", "agent", "entity"]))
@click.option("--metadata", default="{}", help="JSON metadata", callback=parse_json_flag)
def peer_create(workspace_id: str, name: str, peer_type: str, metadata: str) -> None:
    """Create a peer (user/agent/entity) in a workspace."""
    with console.status(f"Creating peer '{name}'..."):
        result = _sdk_client()._call("create_peer", [workspace_id, name, peer_type, metadata])
    console.print(f"[green]Peer '{name}' created successfully.[/green]")
    if result:
        print_json(result)


@peer.command(name="list")
@click.argument("workspace_id")
def peer_list(workspace_id: str) -> None:
    """List peers in a workspace."""
    with console.status(f"Fetching peers for workspace '{workspace_id}'..."):
        rows = _sdk_client().list_peers(workspace_id)
    print_table(rows, title=f"Peers (workspace: {workspace_id})")


# ===================================================================
# memory commands
# ===================================================================


@cli.group()
def memory() -> None:
    """Manage memories."""


@memory.command(name="store")
@click.argument("workspace_id")
@click.argument("peer_id")
@click.argument("content")
@click.option("--observer-id", default="", help="Observer peer ID")
@click.option("--memory-type", default="experience",
              type=click.Choice(["world_fact", "experience", "mental_model"]),
              help="Type of memory")
@click.option("--summary", default="", help="Short summary")
@click.option("--entities-json", default="[]", help="JSON array of entity refs",
              callback=parse_json_flag)
@click.option("--confidence", default=0.8, type=float, help="Confidence 0.0-1.0")
@click.option("--source-session-id", default="", help="Source session ID")
@click.option("--source-message-id", default="", help="Source message ID")
@click.option("--tier", default="",
              type=click.Choice(["", "L0", "L1", "L2"]),
              help="Tier (L0=critical, L1=normal, L2=archival)")
def memory_store(
    workspace_id: str, peer_id: str, content: str,
    observer_id: str, memory_type: str, summary: str,
    entities_json: str, confidence: float,
    source_session_id: str, source_message_id: str,
    tier: str,
) -> None:
    """Store a new memory and index it for semantic search."""
    client = _sdk_client()
    with console.status("Storing memory..."):
        result = client.store(
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
    console.print("[green]Memory stored successfully.[/green]")
    if result:
        print_json(result)


@memory.command(name="search")
@click.argument("workspace_id")
@click.argument("query")
@click.option("--memory-type", help="Filter by memory type")
@click.option("--tier", help="Filter by tier (L0/L1/L2)")
@click.option("--limit", default=50, type=int, help="Max results")
@click.option("--semantic/--no-semantic", default=True,
              help="Use semantic (embedding) search")
def memory_search(workspace_id: str, query: str, memory_type: str | None,
                  tier: str | None, limit: int, semantic: bool) -> None:
    """Search memories in a workspace."""
    client = _sdk_client()
    with console.status("Searching..."):
        rows = client.search(
            workspace_id=workspace_id,
            query=query,
            memory_type=memory_type or "",
            tier=tier or "",
            limit=limit,
            semantic=semantic,
        )
    print_table(rows, title=f"Search results (workspace: {workspace_id})")


@memory.command(name="reinforce")
@click.argument("memory_id")
def memory_reinforce(memory_id: str) -> None:
    """Reinforce a memory (increment access count and bump strength)."""
    with console.status(f"Reinforcing memory '{memory_id}'..."):
        result = _sdk_client().reinforce(memory_id)
    console.print(f"[green]Memory '{memory_id}' reinforced.[/green]")
    if result:
        print_json(result)


@memory.command(name="rate")
@click.argument("memory_id")
@click.argument("rating", type=click.Choice(["helpful", "unhelpful"]))
@click.argument("peer_id")
def memory_rate(memory_id: str, rating: str, peer_id: str) -> None:
    """Rate a memory as 'helpful' or 'unhelpful'."""
    with console.status(f"Rating memory '{memory_id}' as '{rating}'..."):
        result = _sdk_client()._call("rate_memory", [memory_id, rating, peer_id])
    console.print(f"[green]Memory '{memory_id}' rated as '{rating}'.[/green]")
    if result:
        print_json(result)


@memory.command(name="list")
@click.argument("workspace_id")
@click.option("--type", "memory_type", help="Filter by memory type (world_fact/experience/mental_model)")
def memory_list(workspace_id: str, memory_type: str | None) -> None:
    """List memories in a workspace."""
    with console.status(f"Fetching memories for workspace '{workspace_id}'..."):
        rows = _sdk_client().list_memories(
            workspace_id=workspace_id,
            memory_type=memory_type or "",
        )
    print_table(rows, title=f"Memories (workspace: {workspace_id})")


# ===================================================================
# profile commands
# ===================================================================


@cli.group()
def profile() -> None:
    """Manage peer profiles."""


@profile.command(name="get")
@click.argument("peer_id")
def profile_get(peer_id: str) -> None:
    """Retrieve the profile for a peer."""
    with console.status(f"Fetching profile for peer '{peer_id}'..."):
        rows = _sdk_client().get_profile(peer_id)
    print_table(rows, title=f"Profile (peer: {peer_id})")


@profile.command(name="upsert")
@click.argument("peer_id")
@click.option("--static-facts", default="[]", help="JSON array of static facts",
              callback=parse_json_flag)
@click.option("--dynamic-context", default="[]", help="JSON array of dynamic context",
              callback=parse_json_flag)
@click.option("--preferences", default="{}", help="JSON object of preferences",
              callback=parse_json_flag)
@click.option("--tags", default="[]", help="JSON array of tags",
              callback=parse_json_flag)
def profile_upsert(peer_id: str, static_facts: str, dynamic_context: str,
                   preferences: str, tags: str) -> None:
    """Create or update a peer profile."""
    with console.status(f"Upserting profile for peer '{peer_id}'..."):
        result = _sdk_client().upsert_profile(
            peer_id, static_facts, dynamic_context, preferences, tags,
        )
    console.print(f"[green]Profile for peer '{peer_id}' updated.[/green]")
    if result:
        print_json(result)


# ===================================================================
# knowledge-graph commands
# ===================================================================


@cli.group(name="kg")
def kg() -> None:
    """Manage the knowledge graph."""


@kg.group(name="node")
def kg_node() -> None:
    """Manage knowledge graph nodes."""


@kg_node.command(name="create")
@click.argument("workspace_id")
@click.argument("label")
@click.argument("node_type",
                type=click.Choice(["code", "concept", "entity", "document", "topic"]))
@click.option("--summary", default="", help="Node summary")
@click.option("--metadata", default="{}", help="JSON metadata",
              callback=parse_json_flag)
def kg_node_create(workspace_id: str, label: str, node_type: str,
                   summary: str, metadata: str) -> None:
    """Create a knowledge graph node and index it for semantic search."""
    with console.status(f"Creating KG node '{label}'..."):
        result = _sdk_client().create_node(workspace_id, label, node_type, summary, metadata)
    console.print(f"[green]KG node '{label}' created.[/green]")
    if result:
        print_json(result)


@kg.group(name="edge")
def kg_edge() -> None:
    """Manage knowledge graph edges."""


@kg_edge.command(name="create")
@click.argument("workspace_id")
@click.argument("source_node_id")
@click.argument("target_node_id")
@click.argument("relation")
@click.option("--weight", default=1.0, type=float, help="Edge weight")
@click.option("--confidence", default="EXTRACTED",
              type=click.Choice(["EXTRACTED", "INFERRED", "AMBIGUOUS"]),
              help="Confidence level")
@click.option("--metadata", default="{}", help="JSON metadata",
              callback=parse_json_flag)
def kg_edge_create(workspace_id: str, source_node_id: str,
                   target_node_id: str, relation: str,
                   weight: float, confidence: str, metadata: str) -> None:
    """Create a knowledge graph edge."""
    with console.status(f"Creating edge '{relation}'..."):
        result = _sdk_client()._call("create_edge", [
            workspace_id, source_node_id, target_node_id,
            relation, weight, confidence, metadata,
        ])
    console.print(f"[green]Edge '{relation}' created.[/green]")
    if result:
        print_json(result)


@kg.command(name="query")
@click.argument("workspace_id")
@click.argument("query")
def kg_query(workspace_id: str, query: str) -> None:
    """Search knowledge graph nodes by label."""
    with console.status(f"Searching KG nodes for '{query}'..."):
        rows = _sdk_client().query_graph(workspace_id, query)
    print_table(rows, title=f"KG nodes matching '{query}'")


@kg.command(name="neighbors")
@click.argument("node_id")
def kg_neighbors(node_id: str) -> None:
    """Get neighbors of a node in the knowledge graph."""
    with console.status(f"Fetching neighbors for node '{node_id}'..."):
        rows = _sdk_client().get_neighbors(node_id)
    print_table(rows, title=f"Neighbors of node '{node_id}'")


# ===================================================================
# session commands
# ===================================================================


@cli.group()
def session() -> None:
    """Manage sessions."""


@session.command(name="create")
@click.argument("workspace_id")
@click.argument("name")
@click.option("--metadata", default="{}", help="JSON metadata",
              callback=parse_json_flag)
def session_create(workspace_id: str, name: str, metadata: str) -> None:
    """Create a new session."""
    with console.status(f"Creating session '{name}'..."):
        result = _sdk_client()._call("create_session", [workspace_id, name, metadata])
    console.print(f"[green]Session '{name}' created.[/green]")
    if result:
        print_json(result)


@session.command(name="messages")
@click.argument("session_id")
def session_messages(session_id: str) -> None:
    """Get messages for a session."""
    with console.status(f"Fetching messages for session '{session_id}'..."):
        rows = _sdk_client().get_session_messages(session_id)
    print_table(rows, title=f"Messages (session: {session_id})")


# ===================================================================
# ingest — codebase ingestion
# ===================================================================


@cli.group()
def ingest() -> None:
    """Ingest a codebase into the knowledge graph."""


@ingest.command(name="codebase")
@click.argument("repo_path", type=click.Path(exists=True, file_okay=False))
@click.argument("workspace_id")
@click.option("--max-files", default=0, type=int,
              help="Max files to process (0 = unlimited)")
@click.option("--skip-dirs", default="",
              help="Extra directories to skip (comma-separated)")
def ingest_codebase(repo_path: str, workspace_id: str,
                    max_files: int, skip_dirs: str) -> None:
    """Parse a codebase with tree-sitter and populate the KG."""
    skip_set = set()
    if skip_dirs:
        skip_set = set(d.strip() for d in skip_dirs.split(",") if d.strip())

    try:
        from spacetime_memory.ingest import CodebaseIngester
    except ImportError:
        console.print(
            "[red]Error:[/red] `spacetime-memory` SDK not installed. "
            "Run: pip install spacetime-memory"
        )
        sys.exit(1)

    with console.status(f"Ingesting {repo_path} ..."):
        ingester = CodebaseIngester(_sdk_client())
        stats = ingester.ingest(repo_path, workspace_id,
                                max_files=max_files, skip_dirs=skip_set)

    console.print(
        f"[green]Ingestion complete.[/green] "
        f"{stats['files']} files, {stats['defs']} definitions, "
        f"{stats['edges']} edges, {stats['errors']} errors"
    )


# ===================================================================
# connector — external data sources
# ===================================================================


@cli.group()
def connector() -> None:
    """Manage external data connectors."""


@connector.command(name="run")
@click.option("--rss", help="RSS/Atom feed URL")
@click.option("--workspace-id", required=True, help="Target workspace")
@click.option("--interval", default=300, type=int, help="Poll interval (seconds)")
@click.option("--ticks", default=1, type=int, help="Number of poll cycles (0 = forever)")
def connector_run(rss: str | None, workspace_id: str,
                  interval: int, ticks: int) -> None:
    """Run a connector. Currently supports --rss feeds."""
    client = _sdk_client()

    if rss:
        try:
            from spacetime_memory.connectors import RssFeedConnector
        except ImportError:
            console.print("[red]Error:[/red] Missing dep. Run: pip install feedparser")
            sys.exit(1)
        conn = RssFeedConnector(rss, workspace_id)
        stop = None if ticks == 0 else ticks
        conn.run(client, interval_secs=interval, stop_after=stop)
        console.print("[green]Connector finished.[/green]")
    else:
        console.print("[yellow]No connector specified. Use --rss <url>[/yellow]")
        sys.exit(1)


# ===================================================================
# context — context pack / delta agent
# ===================================================================


@cli.group()
def context() -> None:
    """Query the context pack and delta system."""


@context.command(name="pack")
@click.argument("workspace_id")
@click.argument("query")
@click.option("--token-budget", default=4096, type=int, help="Max tokens")
@click.option("--peer-id", default="cli", help="Peer requesting the pack")
def context_pack(workspace_id: str, query: str, token_budget: int,
                 peer_id: str) -> None:
    """Generate a context pack for a query and print results."""
    client = _sdk_client()
    with console.status("Generating context pack..."):
        client._call("generate_context_pack", [
            workspace_id, query, token_budget, peer_id, "",
        ])
        rows = client.list_context_packs(workspace_id)

    if not rows:
        console.print("[yellow]No context pack generated.[/yellow]")
        return

    pack = rows[0]
    print_json(pack)

    print_table(
        client.list_context_entries(pack.get("id", "")),
        title="Context entries",
    )


@context.command(name="delta")
@click.argument("previous_pack_id")
def context_delta(previous_pack_id: str) -> None:
    """Compute and show the delta from a previous pack."""
    client = _sdk_client()
    with console.status("Computing delta..."):
        client._call("get_delta", [previous_pack_id])
        rows = client.list_context_deltas(previous_pack_id)
    print_table(rows, title=f"Delta from {previous_pack_id[:16]}...")


# ===================================================================
# Entry point
# ===================================================================

def main() -> None:
    try:
        cli()
    except click.ClickException as e:
        console.print(f"[red]Error:[/red] {e.format_message()}")
        sys.exit(1)
    except httpx.ConnectError as e:
        console.print(
            f"[red]Connection error:[/red] Could not connect to SpacetimeDB at "
            f"http://{HOST}:{PORT}. Is it running?\n  {e}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
