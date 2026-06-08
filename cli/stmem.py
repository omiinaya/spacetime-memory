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

import csv
import io
import json
import os
import subprocess
import sys
import time
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

# Global output format; set by root CLI group --output flag
_current_output_format: str = "table"
_quiet_mode: bool = False
_no_header_mode: bool = False
_compact_json_mode: bool = False
_no_color_mode: bool = False
_verbose_mode: bool = False

# Aliases file path
ALIASES_FILE = os.path.join(os.path.expanduser("~"), ".stmem_aliases.json")


def _load_aliases() -> dict[str, str]:
    """Load aliases from ~/.stmem_aliases.json."""
    if os.path.exists(ALIASES_FILE):
        try:
            with open(ALIASES_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_aliases(aliases: dict[str, str]) -> None:
    """Save aliases to ~/.stmem_aliases.json."""
    with open(ALIASES_FILE, "w") as f:
        json.dump(aliases, f, indent=2)


def _sdk_client() -> Client:
    """Build an SDK Client from the CLI's env-var config."""
    return Client(
        host=HOST, port=PORT, database=DB,
        embedder_url=EMBEDDER_URL,
        verbose=_verbose_mode,
    )


def _quiet_print(msg: str) -> None:
    """Print a message unless quiet mode is on."""
    if not _quiet_mode:
        console.print(msg)


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def print_table(rows: list[dict[str, Any]], title: str = "",
                output: str | None = None) -> None:
    """Print query results as table, json, or csv.

    Args:
        rows: List of dicts to display.
        title: Optional table title (only used in table mode).
        output: One of "table", "json", "csv".  Defaults to the
                module-global ``_current_output_format``.
    """
    if output is None:
        output = _current_output_format

    if not rows:
        if not _quiet_mode:
            console.print("[yellow]No results found.[/yellow]")
        return

    if _quiet_mode:
        return

    if output == "json":
        if _compact_json_mode:
            console.print(json.dumps(rows, default=str))
        else:
            console.print_json(json.dumps(rows, default=str))
        return

    if output == "csv":
        cols = list(rows[0].keys())
        buf = io.StringIO()
        writer = csv.writer(buf)
        if not _no_header_mode:
            writer.writerow(cols)
        for row in rows:
            writer.writerow([str(row.get(c, "")) for c in cols])
        console.print(buf.getvalue().strip())
        return

    # Default: Rich table
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
    console.print_json(json.dumps(data, default=str) if not isinstance(data, str) else data)


def parse_json_flag(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    """Click callback that validates JSON is parseable."""
    if value is None:
        return value
    try:
        json.loads(value)
    except json.JSONDecodeError as e:
        raise click.BadParameter(f"Invalid JSON: {e}")
    return value


def _esc(val: str) -> str:
    """Basic SQL string escaping for single-quoted string literals."""
    return val.replace("'", "''")


# ---------------------------------------------------------------------------
# stmem CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(version="0.1.0", prog_name="stmem")
@click.option("--output", "-o", type=click.Choice(["table", "json", "csv"]),
              default="table", help="Output format: table, json, or csv")
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-error output")
@click.option("--no-header", is_flag=True, help="Skip header row in CSV output")
@click.option("--compact-json", is_flag=True, help="Compact JSON output (no indentation)")
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.option("--verbose", "-v", is_flag=True, help="Show raw error messages instead of friendly ones")
@click.pass_context
def cli(ctx: click.Context, output: str, quiet: bool, no_header: bool,
        compact_json: bool, no_color: bool, verbose: bool) -> None:
    """stmem — Spacetime-Memory CLI.

    Manage workspaces, peers, memories, profiles, knowledge graphs, and sessions
    on a SpacetimeDB instance.
    """
    global console, _current_output_format, _quiet_mode, _no_header_mode, _compact_json_mode, _no_color_mode, _verbose_mode
    _current_output_format = output
    _quiet_mode = quiet
    _no_header_mode = no_header
    _compact_json_mode = compact_json
    _no_color_mode = no_color
    _verbose_mode = verbose
    ctx.ensure_object(dict)
    ctx.obj["output"] = output
    ctx.obj["quiet"] = quiet
    ctx.obj["no_header"] = no_header
    ctx.obj["compact_json"] = compact_json
    ctx.obj["no_color"] = no_color
    ctx.obj["verbose"] = verbose
    if no_color:
        os.environ["NO_COLOR"] = "1"
        console = Console(no_color=True)


# ===================================================================
# completion — shell completion scripts
# ===================================================================


@cli.command(name="completion")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completion(shell: str) -> None:
    """Generate shell completion script.

    Usage: eval "$(stmem completion bash)"
    """
    if shell == "bash":
        click.echo('eval "$(_STMEM_COMPLETE=bash_source stmem)"')
    elif shell == "zsh":
        click.echo('eval "$(_STMEM_COMPLETE=zsh_source stmem)"')
    elif shell == "fish":
        click.echo('eval "$(_STMEM_COMPLETE=fish_source stmem)"')


# ===================================================================
# alias — CLI aliases
# ===================================================================


@cli.group()
def alias() -> None:
    """Manage CLI aliases."""


@alias.command(name="set")
@click.argument("name")
@click.argument("command")
def alias_set(name: str, command: str) -> None:
    """Set an alias.

    Example: stmem alias set ll 'memory list --tier L0'
    """
    aliases = _load_aliases()
    aliases[name] = command
    _save_aliases(aliases)
    _quiet_print(f"[green]Alias '{name}' set to:[/green] {command}")


@alias.command(name="list")
def alias_list() -> None:
    """List all aliases."""
    aliases = _load_aliases()
    if not aliases:
        console.print("[yellow]No aliases defined.[/yellow]")
        return
    table = Table(title="Aliases", box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Name")
    table.add_column("Command")
    for name, cmd in sorted(aliases.items()):
        table.add_row(name, cmd)
    console.print(table)


@alias.command(name="remove")
@click.argument("name")
def alias_remove(name: str) -> None:
    """Remove an alias."""
    aliases = _load_aliases()
    if name not in aliases:
        console.print(f"[yellow]Alias '{name}' not found.[/yellow]")
        return
    del aliases[name]
    _save_aliases(aliases)
    _quiet_print(f"[green]Alias '{name}' removed.[/green]")


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
    _quiet_print(f"[green]Workspace '{name}' created successfully.[/green]")
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
# space commands (Supermemory shareable workspace permissions)
# ===================================================================


@cli.group()
def space() -> None:
    """Manage Supermemory spaces (shareable workspace permissions)."""


@space.command(name="members")
@click.argument("workspace_id")
def space_members(workspace_id: str) -> None:
    """List members with their permissions for a workspace.

    Calls list_space_members reducer and reads from space_member_result.
    """
    client = _sdk_client()
    with console.status(f"Fetching members for workspace '{workspace_id[:16]}...'..."):
        client._call("list_space_members", [workspace_id])
        rows = client._sql(
            f"SELECT * FROM space_member_result WHERE "
            f"workspace_id = '{_esc(workspace_id)}' "
            f"ORDER BY created_at ASC"
        )
    if not rows:
        console.print("[yellow]No members found for this workspace.[/yellow]")
        return
    print_table(rows, title=f"Space Members (workspace: {workspace_id[:16]}...)")


@space.command(name="grant")
@click.argument("workspace_id")
@click.argument("peer_id")
@click.argument("permission", type=click.Choice(["owner", "editor", "viewer"]))
def space_grant(workspace_id: str, peer_id: str, permission: str) -> None:
    """Grant a peer access to a workspace with a specific permission level.

    Only an existing owner can grant access. Permission levels: owner, editor, viewer.
    """
    client = _sdk_client()
    with console.status(f"Granting '{permission}' access to peer '{peer_id[:16]}...'..."):
        client._call("grant_space_access", [workspace_id, peer_id, permission])
    _quiet_print(
        f"[green]Granted '{permission}' access to peer '{peer_id[:16]}...' "
        f"for workspace '{workspace_id[:16]}...'.[/green]"
    )


@space.command(name="revoke")
@click.argument("workspace_id")
@click.argument("peer_id")
def space_revoke(workspace_id: str, peer_id: str) -> None:
    """Revoke a peer's access to a workspace.

    Only an existing owner can revoke access.
    """
    client = _sdk_client()
    with console.status(f"Revoking access for peer '{peer_id[:16]}...'..."):
        client._call("revoke_space_access", [workspace_id, peer_id])
    _quiet_print(
        f"[green]Revoked access for peer '{peer_id[:16]}...' "
        f"from workspace '{workspace_id[:16]}...'.[/green]"
    )


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
    _quiet_print(f"[green]Peer '{name}' created successfully.[/green]")
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
    _quiet_print("[green]Memory stored successfully.[/green]")
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
@click.option("--watch", "-w", is_flag=True, help="Watch for changes (poll every 5s)")
@click.pass_context
def memory_search(ctx: click.Context, workspace_id: str, query: str,
                  memory_type: str | None, tier: str | None, limit: int,
                  semantic: bool, watch: bool) -> None:
    """Search memories in a workspace."""
    client = _sdk_client()

    def _run_search() -> list[dict[str, Any]]:
        with console.status("Searching..."):
            return client.search(
                workspace_id=workspace_id,
                query=query,
                memory_type=memory_type or "",
                tier=tier or "",
                limit=limit,
                semantic=semantic,
            )

    def _display(rows: list[dict[str, Any]]) -> None:
        print_table(rows, title=f"Search results (workspace: {workspace_id})",
                    output=ctx.obj.get("output", "table"))

    if watch:
        try:
            while True:
                console.clear()
                rows = _run_search()
                _display(rows)
                time.sleep(5)
        except KeyboardInterrupt:
            pass
    else:
        rows = _run_search()
        _display(rows)


@memory.command(name="get")
@click.argument("memory_id")
def memory_get(memory_id: str) -> None:
    """Get a single memory by ID (auto-reinforces on read)."""
    client = _sdk_client()
    with console.status(f"Fetching memory '{memory_id}'..."):
        rows = client.get_memory(memory_id)
    if rows:
        print_json(rows[0])
    else:
        console.print(f"[yellow]Memory '{memory_id}' not found.[/yellow]")


@memory.command(name="reinforce")
@click.argument("memory_id")
def memory_reinforce(memory_id: str) -> None:
    """Reinforce a memory (increment access count and bump strength)."""
    with console.status(f"Reinforcing memory '{memory_id}'..."):
        result = _sdk_client().reinforce(memory_id)
    _quiet_print(f"[green]Memory '{memory_id}' reinforced.[/green]")
    if result:
        print_json(result)


@memory.command(name="escalate")
@click.argument("workspace_id")
@click.option("--l2-to-l1", default=5, type=int, help="Access count threshold for L2→L1 escalation (default: 5)")
@click.option("--l1-to-l0", default=20, type=int, help="Access count threshold for L1→L0 escalation (default: 20)")
def memory_escalate(workspace_id: str, l2_to_l1: int, l1_to_l0: int) -> None:
    """Batch-escalate memory tiers based on access_count thresholds."""
    with console.status(f"Escalating memories in workspace '{workspace_id[:16]}...'..."):
        result = _sdk_client().escalate_memories(workspace_id, l2_to_l1, l1_to_l0)
    _quiet_print(f"[green]Tier escalation triggered for workspace {workspace_id[:16]}...[/green]")
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
    _quiet_print(f"[green]Memory '{memory_id}' rated as '{rating}'.[/green]")
    if result:
        print_json(result)


@memory.command(name="list")
@click.argument("workspace_id")
@click.option("--type", "memory_type", help="Filter by memory type (world_fact/experience/mental_model)")
@click.option("--tier", default="", type=click.Choice(["", "L0", "L1", "L2"]), help="Filter by tier")
@click.option("--directory", default="", help="Directory ID — list memories linked to this directory")
@click.option("--recursive", is_flag=True, help="When used with --directory, recursively traverse subdirectories")
@click.option("--watch", "-w", is_flag=True, help="Watch for changes (poll every 5s)")
@click.pass_context
def memory_list(ctx: click.Context, workspace_id: str, memory_type: str | None, tier: str,
                directory: str, recursive: bool, watch: bool) -> None:
    """List memories in a workspace."""
    client = _sdk_client()

    def _run_list() -> list[dict[str, Any]]:
        if directory:
            with console.status(f"Listing directory '{directory[:16]}...'..."):
                if recursive:
                    rows = client.traverse_directory(workspace_id, directory)
                else:
                    rows = client.list_directory(directory)
            # Show linked memories if any rows have memory_id
            linked_memories = []
            for r in rows:
                mid = r.get("memory_id", "")
                if mid:
                    mems = client.get_memory(mid)
                    if mems:
                        linked_memories.append(mems[0])
            if linked_memories:
                return linked_memories
            return rows

        with console.status(f"Fetching memories for workspace '{workspace_id}'..."):
            if tier:
                clauses = [
                    f"workspace_id = '{workspace_id}'",
                    "is_active = true",
                ]
                if memory_type:
                    clauses.append(f"memory_type = '{memory_type}'")
                if tier:
                    clauses.append(f"tier = '{tier}'")
                where = " AND ".join(clauses)
                rows = client._sql(f"SELECT * FROM memory WHERE {where}")
                rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
                return rows
            else:
                return client.list_memories(
                    workspace_id=workspace_id,
                    memory_type=memory_type or "",
                )

    def _display(rows: list[dict[str, Any]]) -> None:
        if directory and not any(r.get("memory_id", "") for r in rows):
            print_table(rows, title=f"Directory contents (workspace: {workspace_id})",
                        output=ctx.obj.get("output", "table"))
        else:
            print_table(rows, title=f"Memories (workspace: {workspace_id})",
                        output=ctx.obj.get("output", "table"))

    if watch:
        try:
            while True:
                console.clear()
                rows = _run_list()
                _display(rows)
                time.sleep(5)
        except KeyboardInterrupt:
            pass
    else:
        rows = _run_list()
        _display(rows)


@memory.command(name="update")
@click.argument("memory_id")
@click.option("--content", default="", help="New content")
@click.option("--summary", default="", help="New summary")
@click.option("--confidence", type=float, default=None, help="New confidence 0.0-1.0")
@click.option("--tier", type=click.Choice(["", "L0", "L1", "L2"]), default="", help="New tier")
def memory_update(memory_id: str, content: str, summary: str,
                  confidence: float | None, tier: str) -> None:
    """Update a memory's content, summary, confidence, and/or tier."""
    client = _sdk_client()
    updates: dict[str, Any] = {}
    if content:
        updates["content"] = content
    if summary:
        updates["summary"] = summary
    if confidence is not None:
        updates["confidence"] = confidence
    if tier:
        updates["tier"] = tier

    if not updates:
        console.print("[yellow]No changes specified. Use --content, --summary, --confidence, or --tier.[/yellow]")
        return

    with console.status(f"Updating memory '{memory_id[:16]}...'..."):
        if "content" in updates or "summary" in updates or "confidence" in updates:
            client.update_memory(
                memory_id,
                content=updates.get("content", ""),
                summary=updates.get("summary", ""),
                confidence=updates.get("confidence", 0.8),
            )
        if "tier" in updates:
            client._call("update_memory_tier", [memory_id, updates["tier"]])
    _quiet_print(f"[green]Memory '{memory_id[:16]}...' updated.[/green]")


@memory.command(name="batch-update")
@click.argument("workspace_id")
@click.argument("memory_ids")
@click.option("--content", default="", help="New content (applied to all)")
@click.option("--summary", default="", help="New summary (applied to all)")
@click.option("--confidence", type=float, default=None, help="New confidence (applied to all)")
@click.option("--tier", type=click.Choice(["", "L0", "L1", "L2"]), default="", help="New tier (applied to all)")
@click.option("--is-active", type=bool, default=None, help="Set active/inactive")
def memory_batch_update(workspace_id: str, memory_ids: str, content: str,
                        summary: str, confidence: float | None,
                        tier: str, is_active: bool | None) -> None:
    """Batch update multiple memories. MEMORY_IDS is a comma-separated list of IDs."""
    client = _sdk_client()
    ids = [m.strip() for m in memory_ids.split(",") if m.strip()]
    if not ids:
        console.print("[yellow]No memory IDs provided.[/yellow]")
        return
    updates: dict[str, Any] = {}
    if content:
        updates["content"] = content
    if summary:
        updates["summary"] = summary
    if confidence is not None:
        updates["confidence"] = confidence
    if tier:
        updates["tier"] = tier
    if is_active is not None:
        updates["is_active"] = is_active
    if not updates:
        console.print("[yellow]No updates specified.[/yellow]")
        return
    with console.status(f"Batch updating {len(ids)} memories..."):
        result = client.batch_update_memories(workspace_id, ids, updates)
    _quiet_print(f"[green]Batch update completed for {len(ids)} memories.[/green]")
    if result:
        print_json(result)


@memory.command(name="history")
@click.argument("memory_id")
def memory_history(memory_id: str) -> None:
    """Get version history for a memory."""
    client = _sdk_client()
    with console.status(f"Fetching history for memory '{memory_id[:16]}...'..."):
        rows = client.get_memory_history(memory_id)
    print_table(rows, title=f"Memory History ({memory_id[:16]}...)")



# ===================================================================
# directory commands
# ===================================================================


@cli.group()
def directory() -> None:
    """Manage context directory trees."""


@directory.command(name="list")
@click.argument("directory_id")
@click.option("--watch", "-w", is_flag=True, help="Watch for changes (poll every 5s)")
@click.pass_context
def directory_list(ctx: click.Context, directory_id: str, watch: bool) -> None:
    """List children of a directory."""
    def _run() -> list[dict[str, Any]]:
        with console.status(f"Listing directory '{directory_id[:16]}...'..."):
            return _sdk_client().list_directory(directory_id)

    def _display(rows: list[dict[str, Any]]) -> None:
        print_table(rows, title=f"Directory: {directory_id[:16]}...",
                    output=ctx.obj.get("output", "table"))

    if watch:
        try:
            while True:
                console.clear()
                rows = _run()
                _display(rows)
                time.sleep(5)
        except KeyboardInterrupt:
            pass
    else:
        rows = _run()
        _display(rows)


@directory.command(name="tree")
@click.argument("workspace_id")
@click.argument("root_directory_id")
def directory_tree(workspace_id: str, root_directory_id: str) -> None:
    """Recursively traverse directory tree."""
    with console.status(f"Traversing tree from '{root_directory_id[:16]}...'..."):
        rows = _sdk_client().traverse_directory(workspace_id, root_directory_id)
    print_table(rows, title=f"Directory tree (root: {root_directory_id[:16]}...)")


@directory.command(name="create")
@click.argument("workspace_id")
@click.argument("name")
@click.argument("path")
@click.option("--parent-id", default="", help="Parent directory ID")
@click.option("--description", default="", help="Directory description")
def directory_create(workspace_id: str, name: str, path: str,
                     parent_id: str, description: str) -> None:
    """Create a directory in the context directory tree."""
    with console.status(f"Creating directory '{name}'..."):
        result = _sdk_client().create_directory(workspace_id, name, path, parent_id, description)
    _quiet_print(f"[green]Directory '{name}' created.[/green]")
    if result:
        print_json(result)


@directory.command(name="link")
@click.argument("directory_id")
@click.argument("memory_id")
@click.argument("workspace_id")
def directory_link(directory_id: str, memory_id: str, workspace_id: str) -> None:
    """Link a memory to a directory."""
    with console.status(f"Linking memory '{memory_id[:16]}...' to directory..."):
        result = _sdk_client().link_memory_to_directory(directory_id, memory_id, workspace_id)
    _quiet_print(f"[green]Memory linked to directory.[/green]")
    if result:
        print_json(result)


@directory.command(name="unlink")
@click.argument("directory_id")
@click.argument("memory_id")
def directory_unlink(directory_id: str, memory_id: str) -> None:
    """Unlink a memory from a directory."""
    with console.status(f"Unlinking memory '{memory_id[:16]}...' from directory..."):
        result = _sdk_client().unlink_memory_from_directory(directory_id, memory_id)
    _quiet_print(f"[green]Memory unlinked from directory.[/green]")
    if result:
        print_json(result)


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
    _quiet_print(f"[green]Profile for peer '{peer_id}' updated.[/green]")
    if result:
        print_json(result)


# ===================================================================
# fact commands
# ===================================================================


@cli.group()
def fact() -> None:
    """Manage peer facts."""


@fact.command(name="add")
@click.argument("workspace_id")
@click.argument("peer_id")
@click.argument("content")
@click.option("--type", "fact_type", default="dynamic", type=click.Choice(["static", "dynamic"]))
@click.option("--category", default="custom", type=click.Choice(["preference", "behavior", "knowledge", "relationship", "custom"]))
@click.option("--confidence", default=0.8, type=float)
@click.option("--source", default="manual", type=click.Choice(["manual", "extracted", "inferred", "imported"]))
@click.option("--tier", default="L1", type=click.Choice(["L0", "L1", "L2"]))
def fact_add(workspace_id: str, peer_id: str, content: str,
             fact_type: str, category: str, confidence: float,
             source: str, tier: str) -> None:
    """Add a new fact about a peer."""
    with console.status("Adding fact..."):
        _sdk_client()._call("add_fact", [workspace_id, peer_id, fact_type, category, content, confidence, source, tier])
    _quiet_print("[green]Fact added successfully.[/green]")


@fact.command(name="list")
@click.argument("workspace_id")
@click.option("--peer", default="")
@click.option("--type", "fact_type", default="")
@click.option("--tier", default="")
@click.option("--category", default="")
@click.option("--watch", "-w", is_flag=True, help="Watch for changes (poll every 5s)")
@click.pass_context
def fact_list(ctx: click.Context, workspace_id: str, peer: str, fact_type: str,
              tier: str, category: str, watch: bool) -> None:
    """List facts for a workspace with optional filters."""
    client = _sdk_client()

    def _run() -> list[dict[str, Any]]:
        query_hash = f"{workspace_id}:{peer}:{fact_type}:{tier}:{category}"
        with console.status("Listing facts..."):
            client._call("list_facts", [workspace_id, peer, fact_type, tier, category])
            rows = client._sql(
                f"SELECT * FROM fact_result WHERE query_hash = '{_esc(query_hash)}' ORDER BY created_at DESC"
            )
        facts: list[dict[str, Any]] = []
        if rows:
            try:
                facts = json.loads(rows[0].get("json_data", "[]"))
            except (json.JSONDecodeError, IndexError):
                pass
        return facts

    def _display(rows: list[dict[str, Any]]) -> None:
        print_table(rows, title=f"Facts (workspace: {workspace_id})",
                    output=ctx.obj.get("output", "table"))

    if watch:
        try:
            while True:
                console.clear()
                rows = _run()
                _display(rows)
                time.sleep(5)
        except KeyboardInterrupt:
            pass
    else:
        rows = _run()
        _display(rows)


@fact.command(name="search")
@click.argument("workspace_id")
@click.argument("query")
@click.option("--tier", default="")
def fact_search(workspace_id: str, query: str, tier: str) -> None:
    """Search facts by content (LIKE / substring match)."""
    client = _sdk_client()
    with console.status("Searching facts..."):
        client._call("search_facts", [workspace_id, query, tier])
        rows = client._sql(
            f"SELECT * FROM fact_result WHERE workspace_id = '{_esc(workspace_id)}' ORDER BY created_at DESC LIMIT 50"
        )
    facts = []
    if rows:
        try:
            facts = json.loads(rows[0].get("json_data", "[]"))
        except (json.JSONDecodeError, IndexError):
            pass
    print_table(facts, title=f"Fact search: '{query}'")


@fact.command(name="get")
@click.argument("fact_id")
def fact_get(fact_id: str) -> None:
    """Get a single fact by ID."""
    with console.status(f"Fetching fact '{fact_id[:16]}...'..."):
        rows = _sdk_client()._sql(f"SELECT * FROM fact WHERE id = '{_esc(fact_id)}'")
    if rows:
        print_json(rows[0])
    else:
        console.print(f"[yellow]Fact '{fact_id[:16]}...' not found.[/yellow]")


@fact.command(name="update")
@click.argument("fact_id")
@click.option("--content", default="")
@click.option("--confidence", type=float, default=None)
@click.option("--tier", type=click.Choice(["L0", "L1", "L2", ""]), default="")
@click.option("--category", default="")
def fact_update(fact_id: str, content: str, confidence: float | None,
                tier: str, category: str) -> None:
    """Update a fact's content, confidence, category, and/or tier."""
    tier_val = tier if tier else ""
    client = _sdk_client()
    with console.status(f"Updating fact '{fact_id[:16]}...'..."):
        client._call("update_fact", [fact_id, content, confidence if confidence else 0.0, category, tier_val])
    _quiet_print(f"[green]Fact '{fact_id[:16]}...' updated.[/green]")


@fact.command(name="delete")
@click.argument("fact_id")
def fact_delete(fact_id: str) -> None:
    """Deactivate a fact (soft delete)."""
    with console.status(f"Deleting fact '{fact_id[:16]}...'..."):
        _sdk_client()._call("delete_fact", [fact_id])
    _quiet_print(f"[green]Fact '{fact_id[:16]}...' deactivated.[/green]")


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
    _quiet_print(f"[green]KG node '{label}' created.[/green]")
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
    _quiet_print(f"[green]Edge '{relation}' created.[/green]")
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
    _quiet_print(f"[green]Session '{name}' created.[/green]")
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
    skip_set: set[str] = set()
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

    _quiet_print(
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
        _quiet_print("[green]Connector finished.[/green]")
    else:
        console.print("[yellow]No connector specified. Use --rss <url>[/yellow]")

@connector.command(name="register")
@click.option("--name", required=True, help="Connector name")
@click.option("--type", "conn_type", required=True, help="Connector type: rss, github, twitter, slack, discord")
@click.option("--config", default="{}", help="JSON config blob for the connector")
@click.option("--workspace-id", required=True, help="Target workspace ID")
@click.option("--interval", default=300, type=int, help="Poll interval (seconds)")
def connector_register(name: str, conn_type: str, config: str, workspace_id: str, interval: int) -> None:
    """Register a connector config in the database."""
    client = _sdk_client()
    # Validate JSON
    try:
        import json
        json.loads(config)
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid config JSON: {e}[/red]")
        sys.exit(1)
    result = client._call("register_connector", [name, conn_type, config, workspace_id, interval])
    console.print(f"[green]Connector '{name}' registered.[/green]")
    if result.get("id"):
        console.print(f"  ID: {result['id']}")


@connector.command(name="list")
def connector_list() -> None:
    """List registered connectors."""
    client = _sdk_client()
    rows = client._sql(
        "SELECT id, name, connector_type, workspace_id, "
        "schedule_secs, is_active, created_at "
        "FROM connector_config"
    )
    if not rows:
        console.print("[yellow]No connectors registered.[/yellow]")
        return
    headers = ["Name", "Type", "Workspace", "Interval", "Active", "ID"]
    table_data = [
        [r["name"], r["connector_type"], r["workspace_id"][:12]+"...",
         f"{r['schedule_secs']}s", "Y" if r["is_active"] else "N", r["id"][:16]]
        for r in rows
    ]
    print_table(table_data, headers=headers, title="Connectors")


@connector.command(name="start")
@click.option("--db-poll", default=60, type=int, help="DB poll interval (seconds)")
def connector_start(db_poll: int) -> None:
    """Start the connector daemon. Polls DB for configs and runs all active connectors."""
    from spacetime_memory.connectors import ConnectorDaemon
    client = _sdk_client()
    daemon = ConnectorDaemon(client, db_poll_secs=db_poll)
    try:
        daemon.start()
    except KeyboardInterrupt:
        daemon.stop()
        console.print("\n[yellow]Connector daemon stopped.[/yellow]")


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
# plugin commands
# ===================================================================


@cli.group()
def plugin() -> None:
    """Manage plugins (discover, load, unload, list)."""


def _plugin_manager() -> Any:
    """Build a PluginManager from the CLI's env-var config."""
    from spacetime_memory.plugin_manager import PluginManager

    client = _sdk_client()
    # Default plugin dir: <project>/plugins/
    default_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "plugins",
    )
    plugin_dir = os.environ.get("STMEM_PLUGIN_DIR", default_dir)
    return PluginManager(client, plugin_dir=plugin_dir)


@plugin.command(name="list")
def plugin_list() -> None:
    """List all discovered and loaded plugins."""
    mgr = _plugin_manager()
    with console.status("Discovering plugins..."):
        plugins = mgr.list()
    if not plugins:
        console.print("[yellow]No plugins discovered.[/yellow]")
        console.print(
            f"  Plugin directory: [cyan]{mgr.plugin_dir}[/cyan]"
        )
        return

    table = Table(
        title=f"Plugins (dir: {mgr.plugin_dir})",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Description")
    table.add_column("Loaded")
    table.add_column("Type")
    for p in plugins:
        loaded = "[green]✔[/green]" if p["loaded"] else "[dim]—[/dim]"
        table.add_row(
            p["name"],
            p["version"],
            p["description"][:80] if p["description"] else "",
            loaded,
            p["type"],
        )
    console.print(table)


@plugin.command(name="load")
@click.argument("name")
def plugin_load(name: str) -> None:
    """Load a plugin by name."""
    mgr = _plugin_manager()
    with console.status(f"Loading plugin '{name}'..."):
        mgr.discover()
        ok = mgr.load(name)
    if ok:
        _quiet_print(f"[green]Plugin '{name}' loaded successfully.[/green]")
    else:
        console.print(f"[red]Failed to load plugin '{name}'.[/red]")
        sys.exit(1)


@plugin.command(name="unload")
@click.argument("name")
def plugin_unload(name: str) -> None:
    """Unload a plugin by name."""
    mgr = _plugin_manager()
    with console.status(f"Unloading plugin '{name}'..."):
        ok = mgr.unload(name)
    if ok:
        _quiet_print(f"[green]Plugin '{name}' unloaded.[/green]")
    else:
        console.print(f"[yellow]Plugin '{name}' was not loaded.[/yellow]")
        sys.exit(1)


@plugin.command(name="reload")
def plugin_reload() -> None:
    """Discover and reload all plugins."""
    mgr = _plugin_manager()
    with console.status("Reloading all plugins..."):
        mgr.unload_all()
        loaded = mgr.load_all()
    _quiet_print(
        f"[green]Reloaded {len(loaded)} plugin(s): {', '.join(loaded)}[/green]"
    )


# ===================================================================
# replication commands
# ===================================================================


@cli.group()
def replication() -> None:
    """Manage replication peers and sync status."""


@replication.command(name="peers")
def replication_peers() -> None:
    """List replication peers."""
    client = _sdk_client()
    with console.status("Fetching replication peers..."):
        client._call("list_replication_peers", ["*"])
        rows = client._sql(
            "SELECT * FROM replication_result "
            "WHERE query_type = 'peers' "
            "ORDER BY created_at DESC LIMIT 1"
        )
    if not rows:
        console.print("[yellow]No replication peers found.[/yellow]")
        return
    peers = json.loads(rows[0].get("json_data", "[]"))
    if not peers:
        console.print("[yellow]No replication peers found.[/yellow]")
        return
    print_table(peers, title="Replication Peers")


@replication.command(name="add")
@click.argument("name")
@click.argument("remote_url")
@click.argument("remote_db")
@click.option("--workspace-id", default="", help="Workspace ID (uses default if empty)")
@click.option("--auth-token", default="", help="Auth token for remote instance")
def replication_add(name: str, remote_url: str, remote_db: str,
                    workspace_id: str, auth_token: str) -> None:
    """Add a replication peer.

    NAME is a human-readable name for the peer.
    REMOTE_URL is the base URL of the remote instance, e.g. http://127.0.0.10:3001.
    REMOTE_DB is the remote database identity.
    """
    client = _sdk_client()
    ws_id = workspace_id
    if not ws_id:
        workspaces = client.list_workspaces()
        if not workspaces:
            console.print("[red]No workspaces found. Create one first or specify --workspace-id.[/red]")
            sys.exit(1)
        ws_id = workspaces[0]["id"]
        console.print(f"[dim]Using workspace: {ws_id}[/dim]")

    with console.status(f"Adding replication peer '{name}'..."):
        result = client._call("add_replication_peer", [
            ws_id, name, remote_url, remote_db, auth_token,
        ])
    _quiet_print(f"[green]Replication peer '{name}' added successfully.[/green]")
    if result:
        print_json(result)


@replication.command(name="remove")
@click.argument("peer_id")
def replication_remove(peer_id: str) -> None:
    """Remove a replication peer by ID."""
    client = _sdk_client()
    with console.status(f"Removing replication peer '{peer_id}'..."):
        result = client._call("remove_replication_peer", [peer_id])
    _quiet_print(f"[green]Replication peer removed.[/green]")
    if result:
        print_json(result)


@replication.command(name="status")
@click.option("--workspace-id", default="", help="Workspace ID (uses default if empty)")
@click.option("--watch", "-w", is_flag=True, help="Watch for changes (poll every 5s)")
@click.pass_context
def replication_status(ctx: click.Context, workspace_id: str, watch: bool) -> None:
    """Show replication sync status."""
    client = _sdk_client()

    def _resolve_ws() -> str:
        ws_id = workspace_id
        if not ws_id:
            workspaces = client.list_workspaces()
            if not workspaces:
                console.print("[red]No workspaces found. Create one first or specify --workspace-id.[/red]")
                sys.exit(1)
            ws_id = workspaces[0]["id"]
        return ws_id

    def _run() -> dict[str, Any] | None:
        ws_id = _resolve_ws()
        with console.status("Fetching replication status..."):
            client._call("get_replication_status", [ws_id])
            rows = client._sql(
                "SELECT * FROM replication_result "
                "WHERE query_type = 'status' "
                "AND workspace_id = '{}' "
                "ORDER BY created_at DESC LIMIT 1".format(ws_id)
            )
        if not rows:
            console.print("[yellow]No replication status available.[/yellow]")
            return None
        status = json.loads(rows[0].get("json_data", "{}"))
        if not status:
            console.print("[yellow]Empty status response.[/yellow]")
            return None
        return status

    def _display(status: dict[str, Any]) -> None:
        output = ctx.obj.get("output", "table")
        if output == "json":
            print_json(status)
        elif output == "csv":
            # Convert single dict to a one-row list for print_table
            print_table([status], title="Replication Status", output=output)
        else:
            print_json(status)

    if watch:
        try:
            while True:
                console.clear()
                status = _run()
                if status is not None:
                    _display(status)
                time.sleep(5)
        except KeyboardInterrupt:
            pass
    else:
        status = _run()
        if status is not None:
            _display(status)


@replication.command(name="sync")
@click.option("--workspace-id", default="", help="Workspace ID (uses default if empty)")
@click.option("--mode", default="both", type=click.Choice(["push", "pull", "both"]),
              help="Sync direction: push, pull, or both (default: both)")
def replication_sync(workspace_id: str, mode: str) -> None:
    """Trigger a one-time sync cycle (push+pull by default)."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
    try:
        from replication_daemon import ReplicationDaemon
    except ImportError:
        console.print("[red]Error: replication_daemon.py not found in scripts/[/red]")
        sys.exit(1)

    with console.status("Running sync cycle..."):
        daemon = ReplicationDaemon(interval=60, once=True, mode=mode)
        total = daemon.sync_once()
    _quiet_print(f"[green]Sync complete — {total} entries replicated (mode={mode}).[/green]")


@replication.command(name="daemon")
@click.option("--interval", default=60, type=int, help="Sync interval in seconds")
@click.option("--mode", default="both", type=click.Choice(["push", "pull", "both"]),
              help="Sync direction: push, pull, or both (default: both)")
@click.option("--daemonize/--no-daemonize", default=False,
              help="Fork to background (Unix only)")
def replication_daemon(interval: int, mode: str, daemonize: bool) -> None:
    """Start the replication daemon.

    Runs continuously, syncing mutations to/from remote peers at the given interval.
    Supports push-only, pull-only, or bi-directional sync.
    """
    if daemonize:
        pid = os.fork()
        if pid > 0:
            parent_exit_msg = f"[green]Replication daemon started (PID: {pid})[/green]"
            _quiet_print(parent_exit_msg)
            sys.exit(0)
        os.setsid()

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
    try:
        from replication_daemon import ReplicationDaemon
    except ImportError:
        console.print("[red]Error: replication_daemon.py not found in scripts/[/red]")
        sys.exit(1)

    daemon = ReplicationDaemon(interval=interval, once=False, mode=mode)
    daemon.run()


# ===================================================================
# mental — mental model synthesis
# ===================================================================


@cli.group()
def mental() -> None:
    """Manage mental models (LLM-synthesized abstractions from memories)."""


@mental.command(name="list")
@click.option("--status", default="",
              type=click.Choice(["", "pending", "completed", "failed"]),
              help="Filter by status")
def mental_list(status: str) -> None:
    """List mental models, optionally filtered by status."""
    client = _sdk_client()
    where = "1=1"
    if status:
        where = f"status = '{status}'"
    with console.status("Fetching mental models..."):
        rows = client._sql(f"SELECT * FROM mental_model WHERE {where} ORDER BY created_at DESC")
    print_table(rows, title="Mental Models")


@mental.command(name="create")
@click.argument("workspace_id")
@click.option("--memory-ids", required=True,
              help="Comma-separated list of source memory IDs")
def mental_create(workspace_id: str, memory_ids: str) -> None:
    """Create a new mental model synthesis request from source memories."""
    client = _sdk_client()
    ids_list = [mid.strip() for mid in memory_ids.split(",") if mid.strip()]
    ids_json = json.dumps(ids_list)
    with console.status("Creating mental model..."):
        result = client._call("synthesize_mental_models", [workspace_id, ids_json])
    _quiet_print("[green]Mental model created (status=pending). Run `stmem mental synthesize` to generate content.[/green]")
    if result:
        print_json(result)


@mental.command(name="synthesize")
@click.option("--all", "all_flag", is_flag=True,
              help="Process ALL pending models (default: only last 24h)")
@click.option("--dry-run", is_flag=True,
              help="Print what would be synthesized without calling LLM")
def mental_synthesize(all_flag: bool, dry_run: bool) -> None:
    """Run the mental model synthesis script for pending models."""
    script_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts", "mental_model_synthesis.py",
    )
    if not os.path.exists(script_path):
        console.print(f"[red]Error: {script_path} not found.[/red]")
        sys.exit(1)

    cmd = [sys.executable, script_path]
    if all_flag:
        cmd.append("--all")
    if dry_run:
        cmd.append("--dry-run")

    console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        console.print(f"[red]Synthesis script exited with code {result.returncode}[/red]")
        sys.exit(result.returncode)


@mental.command(name="get")
@click.argument("id")
def mental_get(id: str) -> None:
    """Get a single mental model by ID."""
    client = _sdk_client()
    with console.status(f"Fetching mental model '{id[:16]}...'..."):
        rows = client._sql(
            f"SELECT * FROM mental_model WHERE id = '{_esc(id)}'"
        )
    if not rows:
        console.print(f"[yellow]Mental model '{id[:16]}...' not found.[/yellow]")
        return
    print_json(rows[0])


# ===================================================================
# agent — Agent orchestration commands (P3g)
# ===================================================================


@cli.group()
def agent() -> None:
    """Manage agent sessions and reasoning steps."""


@agent.command(name="start")
@click.argument("workspace_id")
@click.option("--agent-name", default="assistant", help="Agent name")
@click.option("--user-id", default="user1", help="User identifier")
@click.option("--context", default="", help="JSON context string")
def agent_start(workspace_id: str, agent_name: str, user_id: str, context: str) -> None:
    """Start a new agent session in a workspace."""
    from spacetime_memory.agent_orchestrator import AgentOrchestrator

    orch = AgentOrchestrator(_sdk_client(), workspace_id=workspace_id)
    session_id = orch.start_session(agent_name=agent_name, user_id=user_id, context=context)
    _quiet_print(f"[green]Agent session started: {session_id}[/green]")
    print_json({"session_id": session_id})


@agent.command(name="step")
@click.argument("session_id")
@click.argument("step_type")
@click.argument("content")
@click.option("--summary", default="", help="Short summary of the step")
@click.option("--workspace-id", default="", help="Workspace ID (auto-detected if possible)")
def agent_step(session_id: str, step_type: str, content: str, summary: str, workspace_id: str) -> None:
    """Add an agent reasoning step.

    STEP_TYPE must be one of: thought, action, observation, tool_call, tool_result.
    CONTENT is the step text (or JSON for tool calls).
    """
    from spacetime_memory.agent_orchestrator import AgentOrchestrator

    # For a simple step without orchestration state, just call the reducer directly
    client = _sdk_client()
    if workspace_id:
        w_id = workspace_id
    else:
        # Try to infer workspace from session
        rows = client._sql(f"SELECT workspace_id FROM session WHERE id = '{_esc(session_id)}'")
        w_id = rows[0]["workspace_id"] if rows else "default"

    client._call("add_agent_step", [session_id, w_id, step_type, content, summary, ""])
    # Discover step ID
    rows = client._sql(
        "SELECT id FROM agent_step WHERE "
        f"session_id = '{_esc(session_id)}' "
        "ORDER BY created_at DESC LIMIT 1"
    )
    step_id = rows[0]["id"] if rows else "unknown"
    _quiet_print(f"[green]Step recorded: {step_id}[/green]")
    print_json({"step_id": step_id})


@agent.command(name="steps")
@click.argument("session_id")
@click.option("--output", "-o", help="Output format override")
def agent_steps(session_id: str, output: str | None) -> None:
    """List all reasoning steps for a session."""
    client = _sdk_client()
    client._call("get_session_steps", [session_id])
    query_hash = f"steps:{session_id}"
    rows = client._sql(
        "SELECT * FROM session_step_result WHERE "
        f"query_hash = '{query_hash}' "
        "ORDER BY created_at ASC"
    )
    if not rows:
        console.print("[yellow]No steps found for this session.[/yellow]")
        return
    print_table(rows, title=f"Agent Steps (session: {session_id[:16]}...)", output=output)


@agent.command(name="context")
@click.argument("session_id")
@click.argument("query")
@click.option("--top-k", default=10, type=int, help="Max context entries")
@click.option("--workspace-id", default="", help="Workspace ID")
def agent_context(session_id: str, query: str, top_k: int, workspace_id: str) -> None:
    """Get relevant context for an agent from memories + session steps."""
    from spacetime_memory.agent_orchestrator import AgentOrchestrator

    client = _sdk_client()
    if workspace_id:
        w_id = workspace_id
    else:
        rows = client._sql(f"SELECT workspace_id FROM session WHERE id = '{_esc(session_id)}'")
        w_id = rows[0]["workspace_id"] if rows else "default"

    orch = AgentOrchestrator(client, workspace_id=w_id)
    context = orch.get_context(query=query, top_k=top_k, session_id=session_id)
    if not context:
        console.print("[yellow]No context found.[/yellow]")
        return
    print_table(context, title=f"Agent Context (session: {session_id[:16]}...)")


# ===================================================================
# org — Org-mode sync
# ===================================================================


@cli.group()
def org() -> None:
    """Sync .org files to Spacetime Memory."""


@org.command(name="sync")
@click.argument("workspace_id")
@click.option("--dir", "org_dir", default="~/org",
              help="Directory with .org files (default: ~/org)")
@click.option("--dry-run", is_flag=True,
              help="Preview without writing data")
def org_sync(workspace_id: str, org_dir: str, dry_run: bool) -> None:
    """One-shot sync of .org files to Spacetime Memory."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
    try:
        from org_sync_daemon import OrgSyncDaemon
    except ImportError:
        console.print("[red]Error: org_sync_daemon.py not found in scripts/[/red]")
        sys.exit(1)

    client = None if dry_run else _sdk_client()
    daemon = OrgSyncDaemon(
        org_dir=org_dir,
        workspace_id=workspace_id,
        client=client,
        dry_run=dry_run,
    )
    total = daemon.scan()
    _quiet_print(f"[green]Org sync complete — {total} events synced.[/green]")
    if dry_run:
        _quiet_print("[dim](dry-run — no data written)[/dim]")
    else:
        s = daemon.get_status()
        _quiet_print(f"[dim]Tracked {s['files_tracked']} file(s)[/dim]")


@org.command(name="daemon")
@click.argument("workspace_id")
@click.option("--dir", "org_dir", default="~/org",
              help="Directory with .org files (default: ~/org)")
@click.option("--interval", default=30, type=int,
              help="Poll interval in seconds (default: 30)")
@click.option("--dry-run", is_flag=True,
              help="Preview without writing data")
@click.option("--daemonize/--no-daemonize", default=False,
              help="Fork to background (Unix only)")
def org_daemon(workspace_id: str, org_dir: str,
               interval: int, dry_run: bool, daemonize: bool) -> None:
    """Start the org sync daemon (continuous watch)."""
    if daemonize:
        pid = os.fork()
        if pid > 0:
            _quiet_print(f"[green]Org sync daemon started (PID: {pid})[/green]")
            sys.exit(0)
        os.setsid()

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
    try:
        from org_sync_daemon import OrgSyncDaemon, _start_watchdog_observer
    except ImportError:
        console.print("[red]Error: org_sync_daemon.py not found in scripts/[/red]")
        sys.exit(1)

    client = None if dry_run else _sdk_client()
    daemon = OrgSyncDaemon(
        org_dir=org_dir,
        workspace_id=workspace_id,
        client=client,
        interval=interval,
        dry_run=dry_run,
    )

    # Try watchdog first
    observer = _start_watchdog_observer(org_dir, daemon)
    if observer is not None:
        _quiet_print(f"[green]Watchdog observer started on {org_dir}[/green]")
        try:
            while observer.is_alive():
                observer.join(timeout=1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
    else:
        # Polling fallback
        _quiet_print(f"[green]Org sync daemon running (polling every {interval}s)[/green]")
        if dry_run:
            _quiet_print("[dim](dry-run — no data written)[/dim]")
        daemon.run()


@org.command(name="status")
@click.option("--dir", "org_dir", default="~/org",
              help="Directory with .org files (default: ~/org)")
def org_status(org_dir: str) -> None:
    """Show org sync state (tracked files, last sync)."""
    try:
        from org_sync_daemon import OrgSyncDaemon, STATE_FILE
    except ImportError:
        console.print("[red]Error: org_sync_daemon.py not found in scripts/[/red]")
        sys.exit(1)

    state_path = os.path.expanduser("~/.spacetime-memory/org_sync_state.json")
    if not os.path.exists(state_path):
        console.print("[yellow]No org sync state found. Run `stmem org sync` first.[/yellow]")
        return

    import time as _time

    rows = []
    try:
        with open(state_path) as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        console.print(f"[red]Error reading sync state: {e}[/red]")
        return

    last_mtime = os.path.getmtime(state_path) if os.path.exists(state_path) else 0
    if last_mtime:
        rows.append({
            "key": "last_sync_time",
            "value": _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(last_mtime)),
        })
    rows.append({"key": "files_tracked", "value": str(len(state))})

    for file_path, file_hash in sorted(state.items()):
        short = file_path if len(file_path) < 80 else f"...{file_path[-77:]}"
        rows.append({"key": f"file: {short}", "value": file_hash[:16] + "..."})

    print_table(rows, title="Org Sync Status")


# ===================================================================
# metrics — request and performance metrics
# ===================================================================


@cli.group()
def metrics() -> None:
    """View request metrics and performance statistics."""


@metrics.command(name="show")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def metrics_show(as_json: bool, token: str | None) -> None:
    """Show collected request metrics (counts, latency, errors).

    Metrics are collected from the moment the client is created.
    Use ``stmem metrics reset`` to clear counters.
    Use ``stmem metrics watch`` for a live updating view.
    """
    from spacetime_memory.metrics import MetricsCollector

    client = _sdk_client()
    if token:
        client.token = token

    # Attach a one-shot collector and run a few probes
    mc = MetricsCollector()
    client.set_metrics_collector(mc)

    with console.status("Gathering metrics..."):
        # Run health and memory count queries to populate the collector
        try:
            client.ping()  # records under "sql" via _sql or reducer
        except Exception:
            pass
        try:
            rows = client._sql("SELECT COUNT(*) AS c FROM memory")
            total_memories = rows[0]["c"] if rows else 0
        except Exception:
            total_memories = 0
        try:
            ws_rows = client.list_workspaces()
            workspace_count = len(ws_rows) if ws_rows else 0
        except Exception:
            workspace_count = 0

        mc.record_memory_stats(total=total_memories)
        # Add system-level info
        ping_result = client.ping()

    if as_json:
        data = mc.to_dict()
        data["workspace_count"] = workspace_count
        data["database_latency_ms"] = ping_result.get("latency_ms", 0)
        console.print_json(json.dumps(data, default=str))
        return

    d = mc.to_dict()

    # Overview
    table = Table(title="Metrics Overview", box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Uptime", d["uptime_human"])
    table.add_row("Total Calls", str(d["total_calls"]))
    table.add_row("Total Errors", str(d["total_errors"]))
    table.add_row("Error Rate", f"{d['overall_error_rate_pct']}%")
    table.add_row("Embedder Errors", str(d["embedder_errors"]))
    table.add_row("Workspaces", str(workspace_count))
    table.add_row("Total Memories", str(total_memories))
    table.add_row("Database Latency", f"{ping_result.get('latency_ms', 0)}ms")
    console.print(table)

    # Per-endpoint breakdown
    if d["endpoints"]:
        ep_table = Table(title="Per-Endpoint Breakdown", box=box.ROUNDED, header_style="bold cyan")
        ep_table.add_column("Endpoint")
        ep_table.add_column("Count")
        ep_table.add_column("Errors")
        ep_table.add_column("Error %")
        ep_table.add_column("Avg (ms)")
        ep_table.add_column("Min (ms)")
        ep_table.add_column("Max (ms)")
        for name, stats in sorted(d["endpoints"].items()):
            ep_table.add_row(
                name,
                str(stats["count"]),
                str(stats["errors"]),
                f"{stats['error_rate_pct']}%",
                str(stats["latency_ms"]["avg"]),
                str(stats["latency_ms"]["min"]),
                str(stats["latency_ms"]["max"]),
            )
        console.print(ep_table)


@metrics.command(name="reset")
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def metrics_reset(token: str | None) -> None:
    """Reset all metrics counters to zero."""
    from spacetime_memory.metrics import MetricsCollector

    client = _sdk_client()
    if token:
        client.token = token

    mc = MetricsCollector()
    client.set_metrics_collector(mc)
    console.print("[green]Metrics counters reset.[/green]")


@metrics.command(name="watch")
@click.option("--interval", "-i", default=5, type=int, help="Refresh interval (seconds)")
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def metrics_watch(interval: int, token: str | None) -> None:
    """Live-updating metrics view (refreshes every N seconds)."""
    from spacetime_memory.metrics import MetricsCollector

    client = _sdk_client()
    if token:
        client.token = token

    mc = MetricsCollector()
    client.set_metrics_collector(mc)

    try:
        while True:
            import time as _time
            console.clear()
            try:
                client.ping()
                rows = client._sql("SELECT COUNT(*) AS c FROM memory")
                total_memories = rows[0]["c"] if rows else 0
            except Exception:
                total_memories = 0

            mc.record_memory_stats(total=total_memories)
            d = mc.to_dict()

            table = Table(title=f"Live Metrics (refreshing every {interval}s — Ctrl+C to stop)",
                          box=box.ROUNDED, header_style="bold cyan")
            table.add_column("Metric", style="bold")
            table.add_column("Value")
            table.add_row("Uptime", d["uptime_human"])
            table.add_row("Total Calls", str(d["total_calls"]))
            table.add_row("Errors", str(d["total_errors"]))
            table.add_row("Error Rate", f"{d['overall_error_rate_pct']}%")
            table.add_row("Memories", str(total_memories))
            console.print(table)

            _time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/yellow]")


@metrics.command(name="prometheus")
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def metrics_prometheus(token: str | None) -> None:
    """Export metrics in Prometheus exposition format."""
    from spacetime_memory.metrics import MetricsCollector

    client = _sdk_client()
    if token:
        client.token = token

    mc = MetricsCollector()
    client.set_metrics_collector(mc)

    # Run probes to populate the collector
    try:
        client.ping()
    except Exception:
        pass
    try:
        rows = client._sql("SELECT COUNT(*) AS c FROM memory")
        mc.record_memory_stats(total=rows[0]["c"] if rows else 0)
    except Exception:
        pass

    console.print(mc.prometheus_text())


# ===================================================================
# admin — admin management
# ===================================================================


@cli.group()
def admin() -> None:
    """Manage admin accounts."""


@admin.command(name="init")
@click.argument("identity")
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def admin_init(identity: str, token: str | None) -> None:
    """Set the initial admin identity (only works if no admin exists yet).

    The IDENTITY is the identity hex string from a JWT token or
    SpacetimeDB identity. Call after initial module deployment.
    """
    client = _sdk_client()
    if token:
        client.token = token
    with console.status("Setting initial admin..."):
        client._call("set_initial_admin", [identity])
    console.print(f"[green]Initial admin set for identity {identity[:16]}...[/green]")


@admin.command(name="promote")
@click.argument("identity")
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def admin_promote(identity: str, token: str | None) -> None:
    """Promote a user to admin. Only an existing admin can promote.

    The IDENTITY is the identity hex string of the user to promote.
    """
    client = _sdk_client()
    if token:
        client.token = token
    with console.status(f"Promoting identity {identity[:16]}... to admin..."):
        client._call("promote_admin", [identity])
    console.print(f"[green]Identity {identity[:16]}... promoted to admin.[/green]")


@admin.command(name="demote")
@click.argument("identity")
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def admin_demote(identity: str, token: str | None) -> None:
    """Demote an admin to user. Only an existing admin can demote.

    Cannot demote yourself. Cannot demote the last admin.
    The IDENTITY is the identity hex string of the admin to demote.
    """
    client = _sdk_client()
    if token:
        client.token = token
    with console.status(f"Demoting identity {identity[:16]}... to user..."):
        client._call("demote_admin", [identity])
    console.print(f"[green]Identity {identity[:16]}... demoted to user.[/green]")


@admin.command(name="list")
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def admin_list(token: str | None) -> None:
    """List all admin accounts."""
    client = _sdk_client()
    if token:
        client.token = token
    with console.status("Fetching admin list..."):
        client._call("list_admins", [])
        rows = client._sql(
            "SELECT identity, username, display_name, created_at "
            "FROM admin_list_result "
            "ORDER BY created_at ASC"
        )
    if not rows:
        console.print("[yellow]No admin accounts found.[/yellow]")
        return
    print_table(rows, title="Admin Accounts")


# ===================================================================
# diagnostics — full system health and metrics dump
# ===================================================================


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def diagnostics(as_json: bool, token: str | None) -> None:
    """Run comprehensive system diagnostics.

    Checks connectivity, gathers metrics, inspects workspace/memory
    counts, and reports embedder status in a single snapshot.
    """
    from spacetime_memory.metrics import MetricsCollector

    client = _sdk_client()
    if token:
        client.token = token

    mc = MetricsCollector()
    client.set_metrics_collector(mc)

    with console.status("Running diagnostics..."):
        # 1. Connectivity
        ping_result = client.ping()
        health_result = client.health()
        embedder = health_result.get("embedder", {})

        # 2. Memory counts
        try:
            rows = client._sql("SELECT memory_type, COUNT(*) AS c FROM memory GROUP BY memory_type")
            mem_by_type: dict[str, int] = {}
            total_memories = 0
            for r in rows or []:
                mem_by_type[r["memory_type"]] = r["c"]
                total_memories += r["c"]
        except Exception:
            mem_by_type = {}
            total_memories = 0

        try:
            tier_rows = client._sql("SELECT tier, COUNT(*) AS c FROM memory WHERE tier != '' GROUP BY tier")
            mem_by_tier: dict[str, int] = {}
            for r in tier_rows or []:
                mem_by_tier[r["tier"]] = r["c"]
        except Exception:
            mem_by_tier = {}

        mc.record_memory_stats(total=total_memories, by_type=mem_by_type, by_tier=mem_by_tier)

        # 3. Workspace count
        try:
            workspaces = client.list_workspaces()
            ws_count = len(workspaces) if workspaces else 0
        except Exception:
            workspaces = []
            ws_count = 0

    metrics_data = mc.to_dict()

    if as_json:
        data = {
            **metrics_data,
            "database": {
                "host": HOST,
                "port": PORT,
                "database": DB,
                "reachable": ping_result.get("status") == "ok",
                "latency_ms": ping_result.get("latency_ms", 0),
            },
            "embedder": {
                "reachable": embedder.get("reachable", False),
                "model_path": embedder.get("model_path", ""),
            },
            "workspaces": {
                "count": ws_count,
                "names": [w.get("name", "") for w in (workspaces or [])][:50],
            },
            "memory_counts": {
                "total": total_memories,
                "by_type": mem_by_type,
                "by_tier": mem_by_tier,
            },
        }
        console.print_json(json.dumps(data, default=str))
        return

    # Human-readable output
    console.print("\n[bold cyan]═══ System Diagnostics ═══[/bold cyan]\n")

    # Connectivity
    db_status = "[green]✔[/green]" if ping_result.get("status") == "ok" else "[red]✘[/red]"
    emb_status = "[green]✔[/green]" if embedder.get("reachable") else "[red]✘[/red]"
    auth_status = "[green]JWT[/green]" if health_result.get("token_configured") else "[yellow]anonymous[/yellow]"

    console.print(f"[bold]SpacetimeDB:[/bold] {db_status}  {ping_result.get('latency_ms', '?')}ms  ({HOST}:{PORT})")
    console.print(f"[bold]Embedder:[/bold]   {emb_status}  {embedder.get('model_path', 'n/a')}")
    console.print(f"[bold]Auth:[/bold]       {auth_status}")
    console.print()

    # Metrics
    console.print(f"[bold]Metrics (uptime: {metrics_data['uptime_human']}):[/bold]")
    console.print(f"  Calls:  {metrics_data['total_calls']}  |  "
                  f"Errors: {metrics_data['total_errors']}  |  "
                  f"Rate: {metrics_data['overall_error_rate_pct']}%")
    console.print(f"  Embedder errors: {metrics_data['embedder_errors']}")
    console.print()

    # Memory
    console.print(f"[bold]Memory:[/bold]  {total_memories} total")
    if mem_by_type:
        console.print(f"  By type: {', '.join(f'{k}={v}' for k, v in sorted(mem_by_type.items()))}")
    if mem_by_tier:
        console.print(f"  By tier: {', '.join(f'{k}={v}' for k, v in sorted(mem_by_tier.items()))}")
    console.print(f"[bold]Workspaces:[/bold]  {ws_count}")
    console.print()


# ===================================================================
# backup / restore / health
# ===================================================================


@cli.command()
@click.argument("output_path", required=False, default=None)
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def backup(output_path: str | None, token: str | None) -> None:
    """Export all data tables to a JSON backup file.

    OUTPUT_PATH is optional; defaults to spacetime-memory-backup-<date>.json
    in the current directory.
    """
    client = _sdk_client()
    if token:
        client.token = token
    result = client.backup(output_path=output_path)
    if result["status"] == "ok":
        console.print(f"[green]Backup complete:[/green] {result['path']}")
        console.print(f"  Tables: {len(result['tables'])}")
        console.print(f"  Rows:   {result['total_rows']}")
    else:
        console.print(f"[red]Backup failed:[/red] {result}")


@cli.command()
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def health(token: str | None) -> None:
    """Check connectivity to SpacetimeDB and the embedder sidecar."""
    client = _sdk_client()
    if token:
        client.token = token
    result = client.health()
    if result["status"] == "ok":
        console.print("[green]All systems healthy[/green]")
    else:
        console.print(f"[yellow]System degraded:[/yellow] {result['status']}")
    console.print(f"  Database: {result['database']['status']} "
                  f"({result['database'].get('latency_ms', '?')}ms)")
    emb = result["embedder"]
    console.print(f"  Embedder: {'reachable' if emb.get('reachable') else 'unreachable'}")
    if emb.get("reachable") and emb.get("model_path"):
        console.print(f"    Model: {emb['model_path']}")
    console.print(f"  Auth: {'JWT configured' if result['token_configured'] else 'anonymous'}")


@cli.command()
@click.argument("input_path", required=True)
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def restore(input_path: str, token: str | None) -> None:
    """Import data from a JSON backup file into the current database.

    INPUT_PATH is the path to the backup JSON file created by \b
    `stmem backup`.
    """
    client = _sdk_client()
    if token:
        client.token = token
    result = client.restore(input_path=input_path)
    if result["status"] == "ok":
        console.print(f"[green]Restore complete:[/green] {result['input_path']}")
        console.print(f"  Tables: {len(result['tables'])}")
        console.print(f"  Rows:   {result['total_rows']}")
    else:
        console.print(f"[red]Restore failed:[/red] {result}")


# ===================================================================
# Entry point
# ===================================================================

def main() -> None:
    # Check for alias substitution before Click parses arguments
    args = sys.argv[1:]
    if args and args[0] not in ("alias", "completion", "--help", "--version"):
        aliases = _load_aliases()
        # Match the first non-flag argument against alias names
        for i, arg in enumerate(args):
            if not arg.startswith("-") and arg in aliases:
                # Replace the matched argument with the alias value
                alias_cmd = aliases[arg]
                rest = args[i + 1:]
                # Reconstruct sys.argv with the alias expansion
                sys.argv = [sys.argv[0]] + alias_cmd.split() + rest
                break

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
    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
