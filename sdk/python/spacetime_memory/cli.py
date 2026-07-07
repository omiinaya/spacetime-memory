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
import shutil
import sys
import time
from typing import Any

import click
import datetime
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
EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://127.0.0.1:4000")

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
    """Build an SDK Client from the CLI's env-var config, auto-registering for auth."""
    c = Client(
        host=HOST, port=PORT, database=DB,
        embedder_url=EMBEDDER_URL,
        verbose=_verbose_mode,
    )
    # Auto-register to satisfy auth requirements (first call = admin)
    import os
    suffix = os.urandom(4).hex()
    try:
        c._call("register", [f"cli_{suffix}", "CLI User", "clipass"])
    except RuntimeError:
        pass  # already registered
    return c


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


@click.group(invoke_without_command=True, no_args_is_help=True)
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
# apikey — API key management
# ===================================================================


@cli.group()
def apikey() -> None:
    """Manage API keys for programmatic access."""


@apikey.command(name="create")
@click.argument("workspace_id")
@click.argument("name")
@click.option("--permissions", default='["read"]',
              help='JSON array of permissions (default: ["read"])')
def apikey_create(workspace_id: str, name: str, permissions: str) -> None:
    """Create a new API key.  The secret is returned ONCE — save it."""
    client = _sdk_client()
    with console.status(f"Creating API key '{name}'..."):
        result = client.create_api_key(workspace_id, name, permissions)
    key = result.get("api_key", "")
    _quiet_print(f"[green]API key '{name}' created successfully.[/green]")
    _quiet_print("[bold yellow]Save this key — it will not be shown again:[/bold yellow]")
    console.print(key)
    if _current_output_format == "json":
        print_json(result)


@apikey.command(name="revoke")
@click.argument("key_id")
def apikey_revoke(key_id: str) -> None:
    """Deactivate (revoke) an API key by its ID."""
    client = _sdk_client()
    with console.status(f"Revoking API key '{key_id[:16]}...'..."):
        result = client.deactivate_api_key(key_id)
    _quiet_print(f"[green]API key '{key_id[:16]}...' revoked.[/green]")
    if result and _current_output_format == "json":
        print_json(result)


@apikey.command(name="list")
@click.argument("workspace_id")
def apikey_list(workspace_id: str) -> None:
    """List all API keys for a workspace."""
    client = _sdk_client()
    with console.status(f"Fetching API keys for workspace '{workspace_id[:16]}...'..."):
        rows = client.list_api_keys(workspace_id)
    print_table(rows, title=f"API Keys (workspace: {workspace_id})")


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
@click.option("--polyphonic/--no-polyphonic", default=False,
              help="Use polyphonic recall (RRF + diversity penalty)")
@click.option("--mmr-lambda", type=float, default=0.0,
              help="MMR diversity reranking (0.7 default: 70% relevance, 30% diversity)")
@click.option("--watch", "-w", is_flag=True, help="Watch for changes (poll every 5s)")
@click.option("--snippet", "-s", is_flag=True,
              help="Show snippet preview (first ~200 chars) instead of full content in table output")
@click.option("--from", "from_ts", default=None,
              help="Show only results created after this timestamp. Accepts ISO-8601 "
                   "(e.g. '2026-06-01' or '2026-06-01T12:00:00Z') or a Unix epoch timestamp.")
@click.option("--to", "to_ts", default=None,
              help="Show only results created before this timestamp. Accepts ISO-8601 "
                   "(e.g. '2026-06-30' or '2026-06-30T12:00:00Z') or a Unix epoch timestamp.")
@click.pass_context
def memory_search(ctx: click.Context, workspace_id: str, query: str,
                  memory_type: str | None, tier: str | None, limit: int,
                  semantic: bool, polyphonic: bool, watch: bool,
                  mmr_lambda: float, snippet: bool,
                  from_ts: str | None, to_ts: str | None) -> None:
    """Search memories in a workspace."""

    def _parse_timestamp(val: str | None) -> float | None:
        """Parse ISO-8601 string or Unix timestamp. Returns Unix timestamp (float) or None."""
        if val is None:
            return None
        val = val.strip()
        # Try numeric (Unix timestamp)
        try:
            return float(val)
        except ValueError:
            pass
        # Try ISO-8601 datetime
        for fmt in [
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ]:
            try:
                dt = datetime.datetime.strptime(val, fmt)
                return dt.timestamp()
            except ValueError:
                continue
        raise click.BadParameter(
            f"Cannot parse '{val}' as a timestamp. Use ISO-8601 or a Unix epoch number."
        )

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
                polyphonic=polyphonic,
                mmr_lambda=mmr_lambda,
                before=_parse_timestamp(to_ts),
                after=_parse_timestamp(from_ts),
            )

    def _display(rows: list[dict[str, Any]]) -> None:
        if snippet:
            # Replace verbose content fields with snippet preview
            for r in rows:
                r["memory_content"] = r.get("snippet", "")
                r.pop("content", None)
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
                    f"workspace_id = '{_esc(workspace_id)}'",
                    "is_active = true",
                ]
                if memory_type:
                    clauses.append(f"memory_type = '{_esc(memory_type)}'")
                if tier:
                    clauses.append(f"tier = '{_esc(tier)}'")
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


@memory.command(name="delete")
@click.argument("memory_id")
def memory_delete(memory_id: str) -> None:
    """Deactivate a single memory (soft delete). Idempotent."""
    client = _sdk_client()
    with console.status(f"Deleting memory '{memory_id[:16]}...'..."):
        result = client.delete_memory(memory_id)
    _quiet_print(f"[green]Memory '{memory_id[:16]}...' deactivated.[/green]")
    if result and isinstance(result, dict):
        print_json(result)


@memory.command(name="batch-delete")
@click.argument("memory_ids")
def memory_batch_delete(memory_ids: str) -> None:
    """Batch-deactivate multiple memories. MEMORY_IDS is a comma-separated list of IDs."""
    client = _sdk_client()
    ids = [m.strip() for m in memory_ids.split(",") if m.strip()]
    if not ids:
        console.print("[yellow]No memory IDs provided.[/yellow]")
        return
    with console.status(f"Batch deleting {len(ids)} memories..."):
        result = client.batch_delete_memories(ids)
    _quiet_print(f"[green]Batch deleted {len(ids)} memories.[/green]")
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


@memory.command(name="stats")
@click.argument("workspace_id")
def memory_stats(workspace_id: str) -> None:
    """Show per-workspace memory statistics."""
    with console.status(f"Computing memory stats for workspace '{workspace_id[:12]}...'..."):
        stats = _sdk_client().get_memory_stats(workspace_id)
    if stats:
        from rich.table import Table

        table = Table(title=f"Memory Stats ({workspace_id[:12]}...)", box=box.ROUNDED)
        table.add_column("Metric", style="cyan")
        table.add_column("Value")
        for key in ["total_memories", "active_memories", "avg_confidence",
                     "avg_age_seconds", "total_revisions", "total_users"]:
            table.add_row(key.replace("_", " ").title(), str(stats.get(key, "")))
        from rich.json import JSON
        for key in ["by_tier", "by_type", "top_tags"]:
            raw = stats.get(key)
            if raw:
                table.add_row(key.replace("_", " ").title(), JSON(raw))
        console.print(table)
    else:
        console.print("[yellow]No memory stats — add some memories first.[/yellow]")



# ===================================================================
# decay commands
# ===================================================================


@cli.group()
def decay() -> None:
    """Manage reputation decay configuration."""


@decay.command(name="set-linear")
@click.argument("workspace_id")
@click.option("--rate", default=0.005, type=float, help="Decay rate per day (default: 0.005 = 0.5%%)")
@click.option("--max-days", default=90, type=int, help="Max days before floor (default: 90)")
def decay_set_linear(workspace_id: str, rate: float, max_days: int) -> None:
    """Set linear decay model for a workspace."""
    client = _sdk_client()
    with console.status(f"Applying linear decay to workspace '{workspace_id[:12]}...'..."):
        client.set_decay_model(workspace_id, model="linear", decay_rate=rate, max_days=max_days)
    _quiet_print(f"[green]Linear decay configured: {rate:.3f}/day, max {max_days} days[/green]")


@decay.command(name="set-weibull")
@click.argument("workspace_id")
@click.option("--shape", "-k", default=0.6, type=float,
              help="Weibull shape k (< 1 = rapid-then-slow, default: 0.6)")
@click.option("--scale", "-l", default=30.0, type=float,
              help="Weibull scale λ in days (default: 30)")
def decay_set_weibull(workspace_id: str, shape: float, scale: float) -> None:
    """Set Weibull decay model for a workspace.

    Weibull formula: trust = initial * exp(-(t/λ)^k)

    At t=λ, trust ≈ 37% of initial.
    At t=3λ, trust ≈ 5%.
    """
    client = _sdk_client()
    with console.status(f"Applying Weibull decay to workspace '{workspace_id[:12]}...'..."):
        client.set_decay_model(workspace_id, model="weibull",
                               weibull_shape=shape, weibull_scale=scale)
    _quiet_print(f"[green]Weibull decay configured: k={shape}, λ={scale} days[/green]")


@decay.command(name="show")
@click.argument("workspace_id")
def decay_show(workspace_id: str) -> None:
    """Show current decay configuration for a workspace."""
    client = _sdk_client()
    config = client.get_decay_config(workspace_id)
    if config:
        from rich.table import Table
        from rich import box
        table = Table(title=f"Decay Config ({workspace_id[:12]}...)", box=box.ROUNDED)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        for k, v in config.items():
            table.add_row(k, str(v))
        console.print(table)
    else:
        console.print("[yellow]No decay config set (defaults: linear, 0.5%/day, 90 day max)[/yellow]")


@decay.command(name="run")
@click.argument("workspace_id")
def decay_run(workspace_id: str) -> None:
    """Run one decay cycle for a workspace using current config."""
    client = _sdk_client()
    config = client.get_decay_config(workspace_id)
    model = (config or {}).get("decay_model", "linear")
    with console.status(f"Running {model} decay on workspace '{workspace_id[:12]}...'..."):
        if model == "weibull":
            k = (config or {}).get("weibull_shape", 0.6)
            lmbda = (config or {}).get("weibull_scale", 30.0)
            client.set_decay_model(workspace_id, model="weibull", weibull_shape=k, weibull_scale=lmbda)
        else:
            rate = (config or {}).get("decay_rate", 0.005)
            max_days = (config or {}).get("max_decay_days", 90)
            client.set_decay_model(workspace_id, model="linear", decay_rate=rate, max_days=max_days)
    _quiet_print(f"[green]{model} decay cycle complete[/green]")


# ===================================================================
# recommend command
# ===================================================================


@cli.command(name="recommend")
@click.argument("workspace_id")
@click.option("--limit", default=20, type=int, help="Max recommendations")
@click.option("--min-urgency", default=0.3, type=float,
              help="Minimum urgency threshold (0.0-1.0)")
@click.pass_context
def recommend(ctx: click.Context, workspace_id: str, limit: int,
              min_urgency: float) -> None:
    """Recommend memories needing attention (review/reinforce/discard)."""

    def _run() -> list[dict[str, Any]]:
        with console.status("Analyzing memories..."):
            return _sdk_client().recommend_memories(
                workspace_id, limit=limit, min_urgency=min_urgency,
            )

    rows = _run()
    if rows:
        # Color by action
        action_colors = {"discard": "red", "reinforce": "yellow", "review": "cyan"}
        for r in rows:
            action = r.get("action", "review")
            color = action_colors.get(action, "white")
            urgency = r.get("urgency", 0.0)
            content = (r.get("content", "") or "")[:120]
            console.print(
                f"[{color}][{action.upper():>9}][/{color}] "
                f"[dim]urgency={urgency:.2f}[/dim] "
                f"trust={r.get('trust_score', 0):.2f} "
                f"fb={r.get('feedback_count', 0)} "
                f"[italic]{content}[/italic]"
            )
        if ctx.obj.get("output") == "json":
            print_json(rows)
    else:
        console.print("[green]No memories need attention — all clear![/green]")


@cli.command(name="peer-reputation")
@click.argument("peer_id")
def peer_reputation(peer_id: str) -> None:
    """Show reputation stats for a peer."""
    client = _sdk_client()
    with console.status(f"Fetching reputation for '{peer_id[:16]}...'..."):
        rep = client.get_peer_reputation(peer_id)
    if rep:
        from rich.table import Table
        from rich import box
        table = Table(title=f"Peer Reputation ({peer_id[:16]}...)", box=box.ROUNDED)
        table.add_column("Metric", style="cyan")
        table.add_column("Value")
        table.add_row("Reputation", f"{rep.get('reputation_score', 0):.3f}")
        table.add_row("Helpful", str(rep.get("helpful_count", 0)))
        table.add_row("Unhelpful", str(rep.get("unhelpful_count", 0)))
        table.add_row("Total", str(rep.get("total_feedback", 0)))
        console.print(table)
    else:
        console.print(f"[yellow]No reputation data for peer '{peer_id[:16]}...'[/yellow]")


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
    _quiet_print("[green]Memory linked to directory.[/green]")
    if result:
        print_json(result)


@directory.command(name="unlink")
@click.argument("directory_id")
@click.argument("memory_id")
def directory_unlink(directory_id: str, memory_id: str) -> None:
    """Unlink a memory from a directory."""
    with console.status(f"Unlinking memory '{memory_id[:16]}...' from directory..."):
        result = _sdk_client().unlink_memory_from_directory(directory_id, memory_id)
    _quiet_print("[green]Memory unlinked from directory.[/green]")
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


@kg.command(name="bridges")
@click.argument("workspace_id")
@click.option("--limit", default=20, type=int, help="Max bridge nodes")
@click.option("--min-communities", default=2, type=int,
              help="Minimum communities to qualify as bridge (default: 2)")
@click.pass_context
def kg_bridges(ctx: click.Context, workspace_id: str, limit: int,
               min_communities: int) -> None:
    """Detect bridge nodes — concepts connecting multiple communities."""
    with console.status("Detecting bridge nodes..."):
        rows = _sdk_client().detect_bridge_nodes(
            workspace_id, limit=limit, min_communities=min_communities,
        )
    if rows:
        for r in rows:
            score = r.get("bridge_score", 0.0)
            bar = "█" * int(score * 20)
            label = r.get("node_label", r.get("node_id", ""))[:60]
            console.print(
                f"[cyan]{bar}[/cyan] "
                f"score={score:.2f} "
                f"communities={r.get('community_count', 0)} "
                f"[bold]{label}[/bold]"
            )
        if ctx.obj.get("output") == "json":
            print_json(rows)
    else:
        console.print("[yellow]No bridge nodes found.[/yellow]")


@kg.command(name="stats")
@click.argument("workspace_id")
def kg_stats(workspace_id: str) -> None:
    """Show knowledge graph statistics."""
    with console.status("Computing graph statistics..."):
        stats = _sdk_client().compute_kg_stats(workspace_id)
    if stats:
        from rich.table import Table
        from rich import box
        table = Table(title=f"KG Stats ({workspace_id[:12]}...)", box=box.ROUNDED)
        table.add_column("Metric", style="cyan")
        table.add_column("Value")
        table.add_row("Nodes", str(stats.get("node_count", 0)))
        table.add_row("Edges", str(stats.get("edge_count", 0)))
        table.add_row("Communities", str(stats.get("community_count", 0)))
        table.add_row("Avg Degree", f"{stats.get('avg_degree', 0):.1f}")
        table.add_row("Unassigned (no community)", str(stats.get("unassigned_nodes", 0)))
        table.add_row("Orphans (no edges)", str(stats.get("orphan_nodes", 0)))
        console.print(table)
    else:
        console.print("[yellow]No knowledge graph data — add some nodes first.[/yellow]")


@kg.command(name="add-node-citation")
@click.argument("workspace_id")
@click.argument("node_id")
@click.argument("memory_id")
@click.option("--description", default="",
              help="Description of the citation relationship")
def kg_add_node_citation(workspace_id: str, node_id: str,
                         memory_id: str, description: str) -> None:
    """Add a citation linking a KG node to a source memory.

    Citations provide provenance: they record which memory (raw source,
    note, or observation) supports a particular knowledge-graph node.
    """
    with console.status("Adding node citation..."):
        result = _sdk_client().add_node_citation(
            workspace_id, node_id, memory_id, description,
        )
    _quiet_print("[green]Citation added to node.[/green]")
    if result:
        print_json(result)


@kg.command(name="add-edge-citation")
@click.argument("workspace_id")
@click.argument("edge_id")
@click.argument("memory_id")
@click.option("--description", default="",
              help="Description of the citation relationship")
def kg_add_edge_citation(workspace_id: str, edge_id: str,
                         memory_id: str, description: str) -> None:
    """Add a citation linking a KG edge to a source memory.

    Citations provide provenance for edges — useful for marking which
    source memory supports a particular relationship between nodes.
    """
    with console.status("Adding edge citation..."):
        result = _sdk_client().add_edge_citation(
            workspace_id, edge_id, memory_id, description,
        )
    _quiet_print("[green]Citation added to edge.[/green]")
    if result:
        print_json(result)


@kg.command(name="get-citations")
@click.argument("workspace_id")
@click.argument("entity_id")
@click.option("--entity-type", default="node",
              type=click.Choice(["node", "edge"]),
              help="Entity type: 'node' (default) or 'edge'")
def kg_get_citations(workspace_id: str, entity_id: str,
                     entity_type: str) -> None:
    """Get all citations for a KG entity (node or edge).

    Citations link KG nodes/edges back to the source memories that
    support them. Use this to trace provenance for any KG entity.
    """
    with console.status(f"Fetching citations for {entity_type} '{entity_id}'..."):
        rows = _sdk_client().get_citations(workspace_id, entity_id, entity_type)
    if rows:
        print_table(rows, title=f"Citations for {entity_type} '{entity_id[:40]}'")
    else:
        console.print("[yellow]No citations found for this entity.[/yellow]")


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


@session.command(name="search")
@click.argument("query")
@click.option("--limit", "-n", default=10, type=int, help="Max results")
def session_search(query: str, limit: int) -> None:
    """Semantically search across all sessions/workspaces.

    Embeds the query and returns sessions sorted by relevance score.
    Requires an embedder service to be configured.
    """
    with console.status(f"Searching sessions for '{query}'..."):
        rows = _sdk_client().search_sessions_semantic(query=query, limit=limit)
    if not rows:
        console.print("[yellow]No matching sessions found.[/yellow]")
        return
    print_table(
        rows,
        title=f"Session Search: '{query}'",
    )


# ===================================================================
# ingest — codebase, file, and text source ingestion
# ===================================================================


@cli.group()
def ingest() -> None:
    """Ingest source documents into the wiki.

    Subcommands:
      codebase  — parse a codebase with tree-sitter and populate the KG
      file      — ingest a source document from a file
      text      — ingest a source document from raw text or stdin

    Examples:
      stmem ingest file article.md --title "My Article" --source-type paper
      stmem ingest text "Reinforcement learning is..." --title "RL Notes"
      cat notes.md | stmem ingest text --pipe --title "Piped Notes"
      stmem ingest codebase /path/to/repo workspace_id
    """


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


@ingest.command(name="file")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--title", "-t", required=True, help="Source title")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--source-type", "-s", default="article",
              type=click.Choice(["article", "paper", "transcript",
                                 "note", "podcast"]),
              help="Type of source")
@click.option("--no-embed", is_flag=True, help="Skip semantic embedding")
def ingest_file(path: str, title: str, workspace: str,
                source_type: str, no_embed: bool) -> None:
    """Ingest a source document from a file.

    Uses Compounder.ingest_source() to run the full LLM Wiki ingest
    workflow: summarize, extract entities, create KG nodes, link,
    ripple-update entities, and check for contradictions.
    """
    import pathlib
    text = pathlib.Path(path).read_text(encoding="utf-8")
    _run_ingest(text, title, workspace, source_type, not no_embed)


@ingest.command(name="text")
@click.argument("text", required=False)
@click.option("--title", "-t", required=True, help="Source title")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--source-type", "-s", default="article",
              type=click.Choice(["article", "paper", "transcript",
                                 "note", "podcast"]),
              help="Type of source")
@click.option("--pipe", "-p", is_flag=True, help="Read text from stdin")
@click.option("--no-embed", is_flag=True, help="Skip semantic embedding")
def ingest_text(text: str | None, title: str, workspace: str,
                source_type: str, pipe: bool, no_embed: bool) -> None:
    """Ingest a source document from raw text or stdin."""
    if pipe or (not text and sys.stdin.isatty() is False):
        text = sys.stdin.read()
    elif not text:
        console.print("[red]Error:[/red] provide text or --pipe")
        sys.exit(1)
    _run_ingest(text, title, workspace, source_type, not no_embed)


def _run_ingest(text: str, title: str, workspace: str,
                source_type: str, embed: bool) -> None:
    """Shared ingest logic for file and text commands."""
    from spacetime_memory.compounder import Compounder

    client = _sdk_client()
    cp = Compounder(client)

    with console.status(
        f"Ingesting '{title}' into workspace '{workspace}'..."
    ):
        result = cp.ingest_source(
            source_text=text,
            source_title=title,
            workspace_id=workspace,
            source_type=source_type,
            embed=embed,
        )

    note = result.get("note", {})
    entities = result.get("entities", [])
    links = result.get("links", [])
    contradictions = result.get("contradictions", [])

    summary = Table(title=f"Ingest: {title}", box=box.ROUNDED)
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value")
    summary.add_row("Note ID", note.get("id", "N/A")[:16] + "...")
    summary.add_row("Entities", str(len(entities)))
    summary.add_row("Links Created", str(len(links)))
    summary.add_row("Contradictions", str(len(contradictions)))
    console.print(summary)

    if contradictions:
        console.print("\n[bold yellow]Contradictions found:[/bold yellow]")
        for c in contradictions:
            console.print(
                f"  [yellow]⚠[/yellow] vs `{c.get('memory_id', '?')[:12]}`: "
                f"{c.get('explanation', '')[:120]}"
            )

    if _current_output_format == "json":
        print_json(result)


# ── Export ────────────────────────────────────────────────────────────────────

@cli.group()
def export() -> None:
    """Export wiki data to external formats.

    Examples:
      stmem export markdown ./my-vault/ --workspace default
      stmem export markdown ./my-vault/ --include-kg
    """


@export.command(name="markdown")
@click.argument("output_dir", type=click.Path())
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--include-kg", is_flag=True,
              help="Also export KG nodes as markdown entity pages")
@click.option("--include-system", is_flag=True,
              help="Include _index and _log notes")
def export_markdown(output_dir: str, workspace: str,
                    include_kg: bool, include_system: bool) -> None:
    """Export all notes as markdown files with YAML frontmatter.

    Each note becomes a ``.md`` file with frontmatter (id, title,
    created, updated, backlinks).  The output directory is ready
    for Obsidian or git-based wiki browsing.
    """
    from spacetime_memory.compounder import Compounder

    client = _sdk_client()
    cp = Compounder(client)

    with console.status(
        f"Exporting workspace '{workspace}' to {output_dir}..."
    ):
        result = cp.export_workspace(
            output_dir=output_dir,
            workspace_id=workspace,
            include_kg=include_kg,
            include_system_notes=include_system,
        )

    errors = result.get("errors", [])
    files = result.get("files_written", 0)

    if errors:
        for err in errors:
            console.print(f"  [red]✗[/red] {err}")

    _quiet_print(
        f"[green]Exported {files} files to {output_dir}/[/green]"
    )
    if _current_output_format == "json":
        print_json(result)


# ── Overview ──────────────────────────────────────────────────────────────────

@cli.command(name="overview")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--no-embed", is_flag=True,
              help="Skip semantic embedding for the overview note")
def overview_cmd(workspace: str, no_embed: bool) -> None:
    """Generate a workspace overview/synthesis page.

    Creates a ``_overview`` note with stats, entity tables, recent
    activity, and (if LLM available) an AI-written synthesis.
    """
    from spacetime_memory.compounder import Compounder

    client = _sdk_client()
    cp = Compounder(client)

    with console.status(
        f"Generating overview for workspace '{workspace}'..."
    ):
        result = cp.generate_overview_page(
            workspace_id=workspace,
            embed=not no_embed,
        )

    note = result.get("note", {})
    if note.get("id"):
        _quiet_print(
            f"[green]Overview generated:[/green] `{note['id'][:16]}...`"
        )
    else:
        console.print("[yellow]Workspace is empty. Nothing to generate.[/yellow]")

    if _current_output_format == "json":
        print_json(result)


# ── Lint ──────────────────────────────────────────────────────────────────────

@cli.command(name="lint")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--no-contradictions", is_flag=True,
              help="Skip contradiction detection (LLM-intensive)")
@click.option("--no-crossrefs", is_flag=True,
              help="Skip missing-crossref detection")
def lint_cmd(workspace: str, no_contradictions: bool, no_crossrefs: bool) -> None:
    """Run a workspace health-check.

    Finds orphan KG nodes (no edges), missing cross-references,
    and (optionally) contradictory memory pairs via LLM analysis.

    Contradiction detection requires an available LLM and can be
    slow on large workspaces — use --no-contradictions to skip it.
    """
    from spacetime_memory.compounder import Compounder

    client = _sdk_client()
    cp = Compounder(client)

    with console.status(
        f"Linting workspace '{workspace}'..."
    ):
        result = cp.lint_workspace(
            workspace_id=workspace,
            check_contradictions=not no_contradictions,
            check_missing_crossrefs=not no_crossrefs,
        )

    orphans = result.get("orphans", [])
    crossrefs = result.get("missing_crossrefs", [])
    contradictions = result.get("contradictions", [])

    if orphans:
        console.print(f"\n[bold]Orphan nodes ({len(orphans)}):[/bold]")
        for o in orphans[:20]:
            console.print(f"  • {o.get('label', o.get('id', '?'))[:12]} — {o.get('node_type', '?')}")
        if len(orphans) > 20:
            console.print(f"  ... and {len(orphans) - 20} more")
    else:
        console.print("[green]No orphan nodes.[/green]")

    if crossrefs:
        console.print(f"\n[bold]Missing cross-references ({len(crossrefs)}):[/bold]")
        for cr in crossrefs[:10]:
            console.print(f"  • Note [cyan]{cr.get('note_title', cr.get('note_id', '?'))[:30]}[/cyan] mentions entity [yellow]{cr.get('entity', '?')}[/yellow] with no KG edge")
        if len(crossrefs) > 10:
            console.print(f"  ... and {len(crossrefs) - 10} more")
    elif not no_crossrefs:
        console.print("[green]Cross-references are clean.[/green]")

    if contradictions:
        console.print(f"\n[bold yellow]Contradictions found ({len(contradictions)}):[/bold yellow]")
        for c in contradictions[:5]:
            console.print(f"  • {c.get('note_id', '?')[:12]} vs {c.get('contradicts_note_id', '?')[:12]}")
            note_id = c.get("contradiction_note_id", "")
            if note_id:
                console.print(f"    → contradiction note: [cyan]{note_id[:16]}...[/cyan]")
        if len(contradictions) > 5:
            console.print(f"  ... and {len(contradictions) - 5} more")
    elif not no_contradictions:
        console.print("[green]No contradictions detected.[/green]")

    if not orphans and not crossrefs and not contradictions:
        console.print("[green]Workspace is clean![/green]")

    if _current_output_format == "json":
        print_json(result)


# ── Cross-link ────────────────────────────────────────────────────────────────

@cli.command(name="cross-link")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--dry-run", is_flag=True, help="Preview links without creating them")
def cross_link_cmd(workspace: str, dry_run: bool) -> None:
    """Auto-link related but unconnected memories.

    Finds semantically similar memories that aren't linked in the
    knowledge graph and creates edges between them.  Uses keyword +
    embedding similarity when available.
    """
    from spacetime_memory.compounder import Compounder

    client = _sdk_client()
    cp = Compounder(client)

    with console.status(
        f"Cross-linking workspace '{workspace}'..."
    ):
        result = cp.cross_link(workspace_id=workspace)

    links = result.get("links_created", [])
    if dry_run and links:
        console.print(
            f"[yellow]DRY RUN:[/yellow] Would create {len(links)} edges"
        )
    elif links:
        console.print(
            f"[green]Created {len(links)} new cross-links.[/green]"
        )
    else:
        console.print("[green]No new cross-links found.[/green]")

    if _current_output_format == "json":
        print_json(result)


# ── Suggest Connections ───────────────────────────────────────────────────────

@cli.command(name="suggest-connections")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--limit", "-n", default=20, type=int,
              help="Max suggestions to return")
def suggest_connections_cmd(workspace: str, limit: int) -> None:
    """Suggest node pairs that should be connected.

    Identifies entity/node pairs that share many neighbors but aren't
    directly linked — candidates for manual review or auto-linking.
    """
    from spacetime_memory.compounder import Compounder

    client = _sdk_client()
    cp = Compounder(client)

    with console.status(
        f"Finding connection suggestions for '{workspace}'..."
    ):
        result = cp.suggest_connections(
            workspace_id=workspace,
            limit=limit,
        )

    suggestions = result if isinstance(result, list) else result.get("suggestions", [])
    if suggestions:
        console.print(
            f"\n[bold]Suggested connections ({len(suggestions)}):[/bold]"
        )
        for s in suggestions[:20]:
            src = s.get("source_label", s.get("source", "?"))[:25]
            tgt = s.get("target_label", s.get("target", "?"))[:25]
            score = s.get("score", s.get("shared_neighbors", 0))
            console.print(f"  • [cyan]{src}[/cyan] ↔ [yellow]{tgt}[/yellow]  (score: {score})")
    else:
        console.print("[green]No connection suggestions found.[/green]")

    if _current_output_format == "json":
        print_json(result)


# ── Store Answer ──────────────────────────────────────────────────────────────

@cli.command(name="store-answer")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--query", "-q", required=True, help="The question that was answered")
@click.option("--answer", "-a", required=True, help="The answer text")
@click.option("--source-ids", "-s", help="Comma-separated source memory IDs")
@click.option("--no-embed", is_flag=True, help="Skip semantic embedding")
def store_answer_cmd(workspace: str, query: str, answer: str,
                     source_ids: str | None, no_embed: bool) -> None:
    """Persist an LLM answer as a wiki page.

    Creates a note + KG nodes + index entry from an answer synthesis.
    Implements the 'answers get filed back into the wiki' pattern
    from Karpathy's LLM Wiki.
    """
    from spacetime_memory.compounder import Compounder

    client = _sdk_client()
    cp = Compounder(client)

    mem_ids = (
        [s.strip() for s in source_ids.split(",") if s.strip()]
        if source_ids else None
    )

    with console.status(
        f"Storing answer for '{query[:40]}...'"
    ):
        result = cp.store_answer(
            query=query,
            answer=answer,
            workspace_id=workspace,
            source_memory_ids=mem_ids,
            embed=not no_embed,
        )

    note = result.get("note", {})
    entities = result.get("entities_created", [])
    if note.get("id"):
        _quiet_print(
            f"[green]Answer stored:[/green] [cyan]{note.get('title', note['id'][:16])}[/cyan]"
        )
        if entities:
            _quiet_print(
                f"  Entities created: [yellow]{', '.join(e.get('label', '?') for e in entities)}[/yellow]"
            )
    else:
        console.print("[red]Failed to store answer. Check STDB connection and that OPENAI_API_KEY is set.[/red]")
        console.print("  [dim]→ Run 'stmem doctor' to verify connectivity[/dim]")

    if _current_output_format == "json":
        print_json(result)


# ── Store Answers Batch ──────────────────────────────────────────────────────

@cli.command(name="store-answers-batch")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--pairs", "-p", required=True,
              help='JSON string of [[query, answer], ...] pairs. '
                   'Example: --pairs \'[["Q1","A1"],["Q2","A2"]]\'')
@click.option("--source-ids", "-s", help="Comma-separated source memory IDs")
@click.option("--file", "-f", "pairs_file",
              help="Read JSON pairs from a file instead of --pairs argument")
def store_answers_batch_cmd(workspace: str, pairs: str,
                             source_ids: str | None,
                             pairs_file: str | None) -> None:
    """Batch-persist multiple LLM-synthesized answers as wiki pages.

    More efficient than calling store-answer repeatedly — fetches the
    workspace index once and creates a single consolidated log entry.

    Provide pairs as a JSON string via --pairs, or read from a file
    via --file. Each pair is [query, answer].
    """
    import json as _json

    from spacetime_memory.compounder import Compounder

    # Resolve pairs source
    if pairs_file:
        try:
            with open(pairs_file, "r") as f:
                raw = f.read()
        except FileNotFoundError:
            console.print(f"[red]File not found: {pairs_file}[/red]")
            console.print("  [dim]→ Check the file path and try again[/dim]")
            sys.exit(1)
        except OSError as e:
            console.print(f"[red]Error reading {pairs_file}: {e}[/red]")
            sys.exit(1)
    else:
        raw = pairs

    try:
        qa_pairs = _json.loads(raw)
    except _json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON in pairs: {e}[/red]")
        sys.exit(1)

    if not isinstance(qa_pairs, list) or not all(
        isinstance(p, list) and len(p) == 2 and all(isinstance(s, str) for s in p)
        for p in qa_pairs
    ):
        console.print(
            "[red]Pairs must be a JSON list of [query, answer] string pairs, "
            "e.g. '[['Q1','A1'],['Q2','A2']]'[/red]"
        )
        sys.exit(1)

    mem_ids = (
        [s.strip() for s in source_ids.split(",") if s.strip()]
        if source_ids else None
    )

    client = _sdk_client()
    cp = Compounder(client)

    with console.status(
        f"Storing {len(qa_pairs)} answers in batch..."
    ):
        results = cp.store_answers(
            qa_pairs=qa_pairs,
            workspace_id=workspace,
            source_memory_ids=mem_ids,
        )

    n_stored = len(results)
    n_entities = sum(len(r.get("entities", [])) for r in results)
    _quiet_print(
        f"[green]Batch stored {n_stored} answers[/green] "
        f"([yellow]{n_entities}[/yellow] total entities)"
    )

    if _current_output_format == "json":
        print_json(results)


# ── Entity Page ────────────────────────────────────────────────────────���──────

@cli.command(name="entity-page")
@click.option("--name", "-n", required=True, help="Entity name (page title + node label)")
@click.option("--description", "-d", required=True, help="2-3 sentence description")
@click.option("--type", "-t", "entity_type", default="concept",
              type=click.Choice(["person", "org", "concept", "product", "location", "event", "topic"]),
              help="Entity type")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--tags", help="Comma-separated tags")
@click.option("--related", help="Related entity names (comma-separated)")
def entity_page_cmd(name: str, description: str, entity_type: str,
                    workspace: str, tags: str | None,
                    related: str | None) -> None:
    """Create a structured entity wiki page + KG node.

    Creates both a markdown note with YAML frontmatter and a typed
    knowledge graph node. Use for any named entity: person, org,
    concept, product, location, event, or topic.
    """
    from spacetime_memory.compounder import Compounder

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    rel_list = (
        [{"name": r.strip(), "relation": "related_to"}
         for r in related.split(",") if r.strip()]
        if related else None
    )

    cp = Compounder(_sdk_client())
    with console.status(f"Creating entity page '{name}'..."):
        result = cp.create_entity_page(
            name=name,
            description=description,
            entity_type=entity_type,
            workspace_id=workspace,
            tags=tag_list,
            relations=rel_list,
        )

    note = result.get("note", {})
    node = result.get("node", {})
    if note.get("id"):
        _quiet_print(f"[green]Entity page created:[/green] [cyan]{name}[/cyan] ({entity_type})")
        if node.get("id"):
            _quiet_print(f"  KG node: [yellow]{node['id'][:16]}...[/yellow]")
    else:
        console.print("[red]Failed to create entity page. Check STDB connection and your inputs.[/red]")
        console.print("  [dim]→ Run 'stmem doctor' to verify connectivity[/dim]")

    if _current_output_format == "json":
        print_json(result)


# ── Update Entity Page ─────────────────────────────────────────────────────────

@cli.command(name="update-entity-page")
@click.option("--name", "-n", required=True, help="Entity name to update")
@click.option("--description", "-d", default=None, help="New 2-3 sentence description")
@click.option("--type", "-t", "entity_type", default=None,
              type=click.Choice(["person", "org", "concept", "product", "location", "event", "topic"]),
              help="New entity type")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
def update_entity_page_cmd(name: str, description: str | None,
                           entity_type: str | None, workspace: str) -> None:
    """Update an existing entity wiki page + KG node.

    Finds the entity by name and updates the provided fields.
    Unset fields are left unchanged.
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(_sdk_client())
    with console.status(f"Updating entity page '{name}'..."):
        result = cp.update_entity_page(
            name=name,
            description=description,
            entity_type=entity_type,
            workspace_id=workspace,
        )

    if result.get("note", {}).get("id"):
        _quiet_print(f"[green]Entity page updated:[/green] [cyan]{name}[/cyan]")
        if result.get("node", {}).get("id"):
            _quiet_print(f"  KG node: [yellow]{result['node']['id'][:16]}...[/yellow]")
    else:
        console.print(f"[red]Entity page '{name}' not found. List existing entities:[/red]")
        console.print("  [dim]→ stmem search-entities --label <keyword>[/dim]")

    if _current_output_format == "json":
        print_json(result)


# ── Concept Page ──────────────────────────────────────────────────────────────

@cli.command(name="concept-page")
@click.option("--concept", "-c", required=True, help="Concept name")
@click.option("--definition", "-d", required=True, help="Concept definition")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--related", help="Related concept names (comma-separated)")
def concept_page_cmd(concept: str, definition: str, workspace: str,
                     related: str | None) -> None:
    """Create a concept definition page with [[wiki-links]].

    Creates a note with YAML frontmatter (type: concept) and a
    structured definition. Related concepts are linked as wiki-links.
    """
    from spacetime_memory.compounder import Compounder

    rel_list = (
        [r.strip() for r in related.split(",") if r.strip()]
        if related else None
    )

    cp = Compounder(_sdk_client())
    with console.status(f"Creating concept page '{concept}'..."):
        result = cp.create_concept_page(
            concept=concept,
            definition=definition,
            workspace_id=workspace,
            related_concepts=rel_list,
        )

    note = result.get("note", {})
    if note.get("id"):
        _quiet_print(f"[green]Concept page created:[/green] [cyan]{concept}[/cyan]")
        if rel_list:
            _quiet_print(f"  Related: {', '.join(rel_list)}")
    else:
        console.print("[red]Failed to create concept page. Check STDB connection.[/red]")
        console.print("  [dim]→ Run 'stmem doctor' to verify connectivity[/dim]")

    if _current_output_format == "json":
        print_json(result)


# ── Comparison Page ───────────────────────────────────────────────────────────

@cli.command(name="comparison-page")
@click.option("--title", "-t", required=True, help="Page title (e.g. 'LangGraph vs CrewAI')")
@click.option("--items", "-i", required=True, help="Comma-separated items to compare")
@click.option("--criteria", "-c", default="features,performance,ecosystem",
              help="Comma-separated comparison criteria")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
def comparison_page_cmd(title: str, items: str, criteria: str,
                        workspace: str) -> None:
    """Create a comparison table wiki page.

    Creates a note with YAML frontmatter (type: comparison) and a
    markdown comparison table of the given items across specified
    criteria.
    """
    from spacetime_memory.compounder import Compounder

    item_list = [i.strip() for i in items.split(",") if i.strip()]
    crit_list = [c.strip() for c in criteria.split(",") if c.strip()]

    cp = Compounder(_sdk_client())
    with console.status(f"Creating comparison page '{title}'..."):
        result = cp.create_comparison_page(
            title=title,
            items=item_list,
            workspace_id=workspace,
            criteria=crit_list,
        )

    note = result.get("note", {})
    if note.get("id"):
        _quiet_print(
            f"[green]Comparison page created:[/green] [cyan]{title}[/cyan] "
            f"({len(item_list)} items)"
        )
    else:
        console.print("[red]Failed to create comparison page. Check STDB connection.[/red]")
        console.print("  [dim]→ Run 'stmem doctor' to verify connectivity[/dim]")

    if _current_output_format == "json":
        print_json(result)


# ── Search Entities ───────────────────────────────────────────────────────────

@cli.command(name="search-entities")
@click.option("--workspace", "-w", default="default", help="Workspace ID")
@click.option("--label", "-l", help="Exact entity label to search for")
@click.option("--type", "-t", "node_type",
              help="Entity type (person, org, concept, product, location, event, topic)")
@click.option("--query", "-q", "semantic_query", help="Natural-language semantic query")
@click.option("--limit", type=int, default=20, help="Max results (default: 20)")
def search_entities_cmd(workspace: str, label: str | None, node_type: str | None,
                        semantic_query: str | None, limit: int) -> None:
    """Search knowledge-graph entities with flexible filters.

    Supports label search, type filtering, and semantic search.
    Combine filters to narrow results.

    Examples:

      stmem search-entities --type person

      stmem search-entities --label "RLHF"

      stmem search-entities --type concept --query "machine learning"

      stmem search-entities --query "reinforcement learning" --limit 5
    """
    from spacetime_memory.compounder import Compounder

    cp = Compounder(_sdk_client())
    with console.status("Searching entities..."):
        results = cp.search_entities(
            workspace_id=workspace,
            label=label,
            node_type=node_type,
            semantic_query=semantic_query,
            limit=limit,
        )

    if not results:
        console.print("[yellow]No entities found.[/yellow]")
        if _current_output_format == "json":
            print_json([])
        return

    if _current_output_format == "json":
        print_json(results)
        return

    table = Table(title=f"Entities ({len(results)} found)", box=box.ROUNDED)
    table.add_column("ID", style="dim")
    table.add_column("Label", style="cyan")
    table.add_column("Type", style="yellow")
    table.add_column("Summary")
    for n in results:
        nid = n.get("id", "")[:12]
        label_text = n.get("label", "?")
        ntype = n.get("node_type", "?")
        summary = (n.get("summary", "") or "")[:80]
        table.add_row(nid, label_text, ntype, summary)
    console.print(table)


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
    table_data = [
        dict(
            name=r["name"],
            type=r["connector_type"],
            workspace=r["workspace_id"][:12] + "...",
            interval=f"{r['schedule_secs']}s",
            active="Y" if r["is_active"] else "N",
            id=r["id"][:16],
        )
        for r in rows
    ]
    print_table(table_data, title="Connectors")


@connector.command(name="update")
@click.option("--id", "conn_id", required=True, help="Connector ID")
@click.option("--name", required=True, help="Connector name")
@click.option("--type", "conn_type", required=True, help="Connector type: rss, github, twitter, slack, discord")
@click.option("--config", default="{}", help="JSON config blob for the connector")
@click.option("--workspace-id", required=True, help="Target workspace ID")
@click.option("--interval", default=300, type=int, help="Poll interval (seconds)")
@click.option("--active/--inactive", default=True, help="Whether the connector is active")
def connector_update(conn_id: str, name: str, conn_type: str, config: str,
                     workspace_id: str, interval: int, active: bool) -> None:
    """Update an existing connector configuration."""
    client = _sdk_client()
    try:
        import json
        json.loads(config)
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid config JSON: {e}[/red]")
        sys.exit(1)
    client.update_connector(conn_id, name, conn_type, config, workspace_id, interval, active)
    console.print(f"[green]Connector '{name}' updated.[/green]")


@connector.command(name="delete")
@click.argument("conn_id")
def connector_delete(conn_id: str) -> None:
    """Delete a connector configuration by ID."""
    client = _sdk_client()
    client.delete_connector(conn_id)
    console.print(f"[green]Connector '{conn_id}' deleted.[/green]")


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
# shmr — self-harmonizing memory reasoning
# ===================================================================


@cli.group()
def shmr() -> None:
    """Self-Harmonizing Memory Reasoning — resonance & belief convergence."""


@shmr.command(name="resonate")
@click.argument("workspace_id")
@click.option("--days", default=7, type=int, help="Days of memories to consider")
@click.option("--iterations", default=3, type=int, help="Max resonance rounds")
@click.option("--threshold", default=0.7, type=float,
              help="Cosine similarity threshold for clustering")
@click.option("--dry-run", is_flag=True, help="Print without storing")
def shmr_resonate_cmd(workspace_id: str, days: int, iterations: int,
                      threshold: float, dry_run: bool) -> None:
    """Run SHMR resonance on a workspace — cluster memories, resolve
    contradictions, converge on stable beliefs."""
    from spacetime_memory.shmr import shmr_resonate
    client = _sdk_client()

    with console.status(f"Resonating workspace {workspace_id[:16]}..."):
        result = shmr_resonate(
            client,
            workspace_id,
            days=days,
            max_iterations=iterations,
            similarity_threshold=threshold,
            dry_run=dry_run,
        )

    mode = " [DRY-RUN]" if dry_run else ""
    console.print(f"\n[bold]SHMR Resonance{mode}:[/bold]")
    console.print(f"  Clusters found:       {result.clusters_found}")
    console.print(f"  Beliefs generated:    {result.beliefs_generated}")
    console.print(f"  Contradictions:       {result.contradictions_resolved}")
    console.print(f"  Harmony score avg:    {result.harmony_score_avg:.2f}")
    console.print(f"  Duration:             {result.duration_ms}ms")
    if result.errors:
        console.print(f"  [yellow]Errors: {result.errors}[/yellow]")


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
        console.print(f"[red]Failed to load plugin '{name}'. Is it installed?[/red]")
        console.print("  [dim]→ Check: pip list | grep spacetime-memory-plugin[/dim]")
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
@click.option("--workspace-id", default="", help="Workspace ID (uses default if empty)")
def replication_peers(workspace_id: str) -> None:
    """List replication peers."""
    client = _sdk_client()
    with console.status("Fetching replication peers..."):
        client._call("list_replication_peers", [workspace_id or "*"])
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


@replication.command(name="list")
@click.option("--workspace-id", default="", help="Workspace ID (uses default if empty)")
def replication_list(workspace_id: str) -> None:
    """List registered replication peers (alias for peers)."""
    ctx = click.get_current_context()
    ctx.invoke(replication_peers, workspace_id=workspace_id)


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


@replication.command(name="add-peer")
@click.argument("addr")
@click.option("--workspace-id", required=True, help="Workspace ID to register the peer under")
@click.option("--name", default="", help="Human-readable name (defaults to addr)")
@click.option("--remote-db", default="spacetime-memory", help="Remote database identity")
@click.option("--auth-token", default="", help="Auth token for the remote instance")
def replication_add_peer(addr: str, workspace_id: str, name: str,
                         remote_db: str, auth_token: str) -> None:
    """Register a replication peer.

    ADDR is the remote instance URL (e.g. http://127.0.0.10:3001).
    Specify the workspace with --workspace-id and optionally a human-readable --name.
    """
    peer_name = name or addr
    client = _sdk_client()
    with console.status(f"Registering replication peer '{peer_name}'..."):
        client._call("add_replication_peer", [
            workspace_id, peer_name, addr, remote_db, auth_token,
        ])
    _quiet_print(f"[green]Replication peer '{peer_name}' registered for "
                 f"workspace '{workspace_id[:16]}...'.[/green]")


@replication.command(name="remove")
@click.argument("peer_id")
def replication_remove(peer_id: str) -> None:
    """Remove a replication peer by ID."""
    client = _sdk_client()
    with console.status(f"Removing replication peer '{peer_id}'..."):
        result = client._call("remove_replication_peer", [peer_id])
    _quiet_print("[green]Replication peer removed.[/green]")
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
        where = f"status = '{_esc(status)}'"
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
    from spacetime_memory.agent_orchestrator import AgentOrchestrator  # noqa: F401

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
        from org_sync_daemon import OrgSyncDaemon  # noqa: F401
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
# health
# ===================================================================


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


# ===================================================================
# doctor
# ===================================================================


ADAPTER_MODULES = [
    ("langchain", "spacetime_memory.sdks.langchain"),
    ("mem0", "spacetime_memory.sdks.mem0"),
    ("graphiti", "spacetime_memory.sdks.graphiti"),
    ("zep", "spacetime_memory.sdks.zep"),
    ("hindsight", "spacetime_memory.sdks.hindsight"),
    ("honcho", "spacetime_memory.sdks.honcho"),
]


@cli.command()
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def doctor(token: str | None) -> None:
    """Full system health check: STDB, module, embedder, adapters.

    Runs every diagnostic available and reports a summary with
    actionable guidance for any issues found.
    """
    client = _sdk_client()
    if token:
        client.token = token

    console.print("\n[bold]🔬 stmem doctor — full system check[/bold]\n")

    # 1. Core connectivity (reuses health logic)
    console.print("[bold]1. Core Connectivity[/bold]")
    result = client.health()
    db_ok = result["database"].get("status") == "ok"
    emb_ok = result["embedder"].get("reachable", False)
    auth_type = "JWT configured" if result["token_configured"] else "anonymous"

    if db_ok:
        console.print(f"  [green]✅[/green] SpacetimeDB: {result['database'].get('latency_ms', '?')}ms")
    else:
        console.print(f"  [red]❌[/red] SpacetimeDB: unreachable — is STDB running on {HOST}:{PORT}?")

    if emb_ok:
        model = result["embedder"].get("model_path", "unknown")
        console.print(f"  [green]✅[/green] Embedder: reachable (model: {model})")
    else:
        console.print(f"  [red]❌[/red] Embedder: unreachable — check EMBEDDER_URL ({EMBEDDER_URL})")

    console.print(f"  {'[green]✅[/green]' if auth_type != 'anonymous' else '[yellow]⚠️[/yellow]'} Auth: {auth_type}")

    # 2. Published module
    console.print("\n[bold]2. Published Module[/bold]")
    spacetime_bin = _find_spacetime_bin()
    db_name = os.environ.get("STMEM_DB", os.environ.get("SPACETIMEDB_DB", "spacetime-memory"))
    if spacetime_bin:
        try:
            proc = subprocess.run(
                [spacetime_bin, "list"],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0 and db_name in proc.stdout:
                # Extract the identity hash for the matching database
                for line in proc.stdout.splitlines():
                    if db_name in line and "|" in line:
                        parts = line.split("|")
                        identity = parts[-1].strip()[:16] + "..."
                        console.print(f"  [green]✅[/green] Module published — identity: {identity}")
                        break
                else:
                    console.print(f"  [green]✅[/green] Module '{db_name}' found in database list")
            elif db_name not in proc.stdout:
                console.print(f"  [yellow]⚠️[/yellow] Database '{db_name}' not found in spacetime list — module may not be published")
            else:
                console.print(f"  [yellow]⚠️[/yellow] Could not verify module: {proc.stderr.strip() or 'unknown error'}")
        except (subprocess.TimeoutExpired, OSError) as e:
            console.print(f"  [yellow]⚠️[/yellow] Module check failed: {e}")
    else:
        console.print("  [yellow]⚠️[/yellow] `spacetime` CLI not found — install STDB to check module version")

    # 3. Client library version
    console.print("\n[bold]3. SDK Version[/bold]")
    try:
        import importlib.metadata
        sdk_version = importlib.metadata.version("spacetime_memory")
        console.print(f"  [green]✅[/green] spacetime-memory SDK: v{sdk_version}")
    except (importlib.metadata.PackageNotFoundError, ImportError):
        console.print("  [yellow]⚠️[/yellow] spacetime-memory SDK version not found (editable install?)")

    # 4. Adapter imports
    console.print("\n[bold]4. Adapter Import Status[/bold]")
    all_adapters_ok = True
    for name, module_path in ADAPTER_MODULES:
        try:
            __import__(module_path)
            console.print(f"  [green]✅[/green] {name}")
        except ImportError as e:
            console.print(f"  [red]❌[/red] {name}: {e}")
            all_adapters_ok = False

    # 5. Summary
    console.print("\n[bold]─── Summary ───[/bold]")
    checks = [
        ("SpacetimeDB", db_ok),
        ("Embedder", emb_ok),
        ("Module version", True),  # non-fatal warning only
        ("Adapters", all_adapters_ok),
    ]
    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    if passed == total:
        console.print(f"  [green]✅ All {total}/{total} checks passed[/green]")
        console.print("  [dim]Try: stmem store \"hello\" && stmem search \"hello\"[/dim]")
    else:
        console.print(f"  [yellow]⚠️ {passed}/{total} checks passed[/yellow]")
        if not db_ok:
            console.print("  [red]  → Fix: start SpacetimeDB (docker run clockworklabs/spacetimedb:latest -p 3001:3001)[/red]")
        if not emb_ok:
            console.print(f"  [red]  → Fix: check embedder proxy at {EMBEDDER_URL}/v1/embeddings[/red]")
        if not all_adapters_ok:
            console.print("  [red]  → Fix: pip install upstream packages (mem0, graphiti-core, etc.)[/red]")
    console.print()


@cli.command()
@click.option("--host", default=None, help="SpacetimeDB host (default: 127.0.0.1)")
@click.option("--port", default=None, help="SpacetimeDB port (default: 3001)")
@click.option("--db", default=None, help="Database name (default: spacetime-memory)")
def init(host: str | None, port: str | None, db: str | None) -> None:
    """One-command setup: check prerequisites, start STDB, publish module.

    Performs the full setup flow:
    \b
      1. Check prerequisites (Docker or spacetime CLI)
      2. Start SpacetimeDB via Docker if not running
      3. Publish the Rust module
      4. Create .env config (doesn't overwrite existing)
      5. Run `stmem doctor` to verify
      6. Print test commands
    """
    console.print("\n[bold cyan]╔══════════════════════════════════════════════╗[/]")
    console.print("[bold cyan]║   Spacetime Memory — One-Command Setup      ║[/]")
    console.print("[bold cyan]╚══════════════════════════════════════════════╝[/]")

    # ── Resolve paths ──────────────────────────────────────────────────
    # When run via pip install, the module is inside the package.
    # Try to locate the repo root (where server/ and scripts/ live).
    _mod_dir = os.path.dirname(__file__)
    _repo_root = None
    for candidate in [
        os.path.join(_mod_dir, "..", "..", "..", ".."),  # from site-packages
        os.path.join(_mod_dir, "..", ".."),  # from sdk/python/spacetime_memory
        os.path.join(_mod_dir, ".."),  # from sdk/python
        os.getcwd(),
    ]:
        test_path = os.path.abspath(candidate)
        if os.path.isdir(os.path.join(test_path, "server")):
            _repo_root = test_path
            break

    if _repo_root and os.path.isdir(os.path.join(_repo_root, "server", "spacetimedb")):
        module_dir = os.path.join(_repo_root, "server")
    else:
        module_dir = None

    errs = 0

    # ── Step 1: Check prerequisites ────────────────────────────────────
    console.print("[bold]1. Prerequisites[/bold]")
    spacetime_bin = _find_spacetime_bin()
    docker_available = False
    if shutil.which("docker") is not None:
        docker_available = True
        console.print("  [green]✅[/green] Docker found")
    if spacetime_bin:
        console.print(f"  [green]✅[/green] spacetime CLI: {spacetime_bin}")
    if not spacetime_bin and not docker_available:
        console.print("  [red]❌[/red] Neither Docker nor spacetime CLI found.")
        console.print("  [dim]→ Install Docker: https://docs.docker.com/engine/install/[/dim]")
        console.print("  [dim]→ Or install SpacetimeDB: https://spacetimedb.com/install[/dim]")
        errs += 1
    console.print()

    # ── Step 2: Start SpacetimeDB ──────────────────────────────────────
    console.print("[bold]2. SpacetimeDB[/bold]")
    stdb_host = host or os.environ.get("STMEM_HOST", os.environ.get("SPACETIMEDB_HOST", "127.0.0.1"))
    stdb_port = port or os.environ.get("STMEM_PORT", os.environ.get("SPACETIMEDB_PORT", "3001"))
    db_name = db or os.environ.get("STMEM_DB", os.environ.get("SPACETIMEDB_DB", "spacetime-memory"))

    # Quick connectivity test
    stdb_running = False
    try:
        import httpx
        r = httpx.get(f"http://{stdb_host}:{stdb_port}/health", timeout=2.0)
        # STDB returns 200 (health endpoint) or 404 (no health endpoint) when running
        if r.status_code in (200, 404):
            stdb_running = True
    except Exception:
        pass

    # Also try localhost if target host isn't reachable
    if not stdb_running and stdb_host != "localhost" and stdb_host != "127.0.0.1":
        try:
            import httpx
            r = httpx.get("http://localhost:3001/health", timeout=2.0)
            if r.status_code in (200, 404):
                stdb_host = "localhost"
                stdb_port = "3001"
                stdb_running = True
                console.print("  [yellow]⚠️[/yellow] Found STDB on localhost:3001 (not {})".format(host or os.environ.get("STMEM_HOST", "127.0.0.1")))
        except Exception:
            pass

    if stdb_running:
        console.print(f"  [green]✅[/green] SpacetimeDB is running ({stdb_host}:{stdb_port})")
    elif docker_available:
        console.print("  [yellow]→[/yellow] Starting SpacetimeDB via Docker...")
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=spacetimedb", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=5,
            )
            if "spacetimedb" not in result.stdout:
                console.print("  [yellow]→[/yellow] Pulling clockworklabs/spacetimedb:latest...")
                subprocess.run(
                    ["docker", "pull", "clockworklabs/spacetimedb:latest"],
                    capture_output=True, text=True, timeout=120,
                )
                subprocess.Popen(
                    ["docker", "run", "-d", "--name", "spacetimedb",
                     "-p", f"{stdb_port}:3001",
                     "clockworklabs/spacetimedb:latest",
                     "start"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                # Wait for startup
                for _ in range(15):
                    import time as _time
                    _time.sleep(2)
                    try:
                        r = httpx.get(f"http://{stdb_host}:{stdb_port}/health", timeout=2.0)
                        if r.status_code in (200, 404):
                            stdb_running = True
                            break
                    except Exception:
                        continue
            else:
                stdb_running = True

            if stdb_running:
                console.print("  [green]✅[/green] SpacetimeDB started")
            else:
                console.print("  [red]❌[/red] SpacetimeDB failed to start (check `docker logs spacetimedb`)")
                errs += 1
        except subprocess.TimeoutExpired:
            console.print("  [red]❌[/red] Docker pull timed out")
            errs += 1
        except FileNotFoundError:
            console.print("  [red]❌[/red] Docker not found (shouldn't happen — checked above)")
            errs += 1
    else:
        console.print("  [red]❌[/red] SpacetimeDB not running and Docker unavailable")
        console.print("  [dim]→ Start STDB manually: docker run clockworklabs/spacetimedb:latest -p 3001:3001[/dim]")
        errs += 1
    console.print()

    # ── Step 3: Create .env config ──────────────────────────────────────
    console.print("[bold]3. Configuration[/bold]")
    env_path = os.path.join(os.path.expanduser("~"), ".spacetime-memory.env")
    if not os.path.isfile(env_path):
        try:
            with open(env_path, "w") as f:
                f.write("# Spacetime Memory — generated by `stmem init`\n")
                f.write(f"SPACETIMEDB_HOST={stdb_host}\n")
                f.write(f"SPACETIMEDB_PORT={stdb_port}\n")
                f.write(f"SPACETIMEDB_DB={db_name}\n")
                f.write("EMBEDDER_URL=http://127.0.0.1:4000\n")
            console.print(f"  [green]✅[/green] Created {env_path}")
        except OSError as e:
            console.print(f"  [yellow]⚠️[/yellow] Could not create {env_path}: {e}")
    else:
        console.print(f"  [yellow]⚠️[/yellow] {env_path} already exists — not overwriting")
    console.print()

    # ── Step 4: Publish module ─────────────────────────────────────────
    console.print("[bold]4. Publish Module[/bold]")
    if module_dir:
        wasm_path = os.path.join(module_dir, "target", "wasm32-wasip1", "release", "spacetime_memory.wasm")
        if os.path.isfile(wasm_path):
            console.print(f"  [green]✅[/green] WASM binary found: {wasm_path}")
            if spacetime_bin:
                console.print("  [yellow]→[/yellow] Publishing module...")
                proc = subprocess.run(
                    [spacetime_bin, "publish", "--server", f"http://{stdb_host}:{stdb_port}",
                     "-y", db_name, "--project-path", module_dir],
                    capture_output=True, text=True, timeout=120,
                )
                if proc.returncode == 0:
                    console.print("  [green]✅[/green] Module published")
                else:
                    stderr_clean = proc.stderr.strip()
                    if "already exists" in stderr_clean or "already" in proc.stdout:
                        console.print("  [yellow]⚠️[/yellow] Module already published (ok)")
                    else:
                        console.print(f"  [yellow]⚠️[/yellow] Publish may have issues: {stderr_clean[:200]}")
            else:
                console.print("  [yellow]⚠️[/yellow] `spacetime` CLI not found — cannot auto-publish")
                console.print("  [dim]  → Publish manually: spacetime publish ...[/dim]")
        else:
            console.print(f"  [yellow]⚠️[/yellow] WASM binary not found at {wasm_path}")
            console.print("  [dim]  → Build first: cd server && cargo build --release --target wasm32-wasip1[/dim]")
    else:
        console.print("  [yellow]⚠️[/yellow] Module source not found (running from pip install?)")
        console.print("  [dim]  → Set STMEM_DB env var and publish manually[/dim]")
    console.print()

    # ── Step 5: Run doctor ────────────────────────────────────────────────
    console.print("[bold]5. Verification[/bold]")
    doctor("")
    console.print()

    # ── Summary ────────────────────────────────────────────────────────────
    console.print("[bold cyan]─── Summary ───[/]")
    if errs == 0:
        console.print("  [green]✅ Setup complete![/green]")
        console.print("  [dim]→ stmem store \"hello world\"[/dim]")
        console.print("  [dim]→ stmem search \"hello\"[/dim]")
        console.print("  [dim]→ stmem doctor[/dim]")
    else:
        console.print(f"  [yellow]⚠️ Setup completed with {errs} error(s)[/yellow]")


def _find_spacetime_bin() -> str | None:
    """Locate the `spacetime` CLI binary."""
    import shutil
    # Check PATH first
    exe = shutil.which("spacetime")
    if exe:
        return exe
    # Common fallback locations
    for candidate in [
        os.path.expanduser("~/.local/bin/spacetime"),
        os.path.expanduser("~/.cargo/bin/spacetime"),
        "/usr/local/bin/spacetime",
    ]:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


# ===================================================================
# backup / restore
# ===================================================================


@cli.command(name="synthesize")
@click.argument("workspace_id")
@click.argument("query")
@click.option("--budget", default=4096, type=int, help="Token budget for context (default: 4096)")
def synthesize_cmd(workspace_id: str, query: str, budget: int) -> None:
    """Synthesize a grounded answer with gap analysis (GBrain-style).

    Searches the workspace, finds relevant memories, and calls an LLM to
    produce a structured answer that includes:

    \b
    - answer: synthesized answer grounded in found memories
    - gaps: what the knowledge base does NOT contain
    - sources: indices of source memories used
    - confidence: 0.0-1.0

    Requires OPENAI_API_KEY for LLM calls.

    Example:
        stmem synthesize my-workspace "What do we know about Alice Chen?"
    """
    from spacetime_memory.context_agent import ContextAgent

    client = _sdk_client()
    agent = ContextAgent(client)

    with console.status("Synthesizing with gap analysis..."):
        result = agent.synthesize(query, workspace_id=workspace_id, token_budget=budget)

    if result.get("error"):
        console.print(f"[red]{result['error']}[/red]")
        return

    answer = result.get("answer")
    gaps = result.get("gaps", [])
    sources = result.get("sources", [])
    confidence = result.get("confidence", 0.0)

    if answer:
        console.print(f"\n[bold green]Answer[/bold green] (confidence: {confidence:.0%})")
        console.print(f"[dim]{'─' * 60}[/dim]")
        console.print(answer)
    else:
        console.print("\n[yellow]LLM unavailable — showing raw context entries.[/yellow]")
        if "pack" in result:
            pack = result["pack"]
            console.print(f"  Pack: {pack.get('id', '')[:16]}...")

    if gaps:
        console.print(f"\n[bold yellow]Knowledge Gaps[/bold yellow] ({len(gaps)})")
        console.print(f"[dim]{'─' * 60}[/dim]")
        for i, gap in enumerate(gaps, 1):
            console.print(f"  {i}. {gap}")

    if sources:
        console.print(f"\n[bold dim]Sources[/bold dim]: {' '.join(str(s) for s in sources)}")


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



# ===================================================================
# backup / restore
# ===================================================================


@cli.command(name="backup")
@click.argument("workspace_id")
@click.option("--output", "-o", default=None, help="Output file (default: ~/.hermes/backups/<ws>.jsonl)")
@click.option("--tables", default="memory,session,message,profile,insight,note,kg_node,kg_edge",
              help="Comma-separated tables to backup")
def backup_cmd(workspace_id: str, output: str | None, tables: str) -> None:
    """Backup all data for a workspace to a JSONL file."""
    from pathlib import Path

    table_list = [t.strip() for t in tables.split(",")]

    if not output:
        backup_dir = Path.home() / ".hermes" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        output = str(backup_dir / f"{workspace_id[:16]}.jsonl")

    client = _sdk_client()
    total = 0

    with open(output, "w") as f:
        for table in table_list:
            try:
                rows = client._query(table, workspace_id=workspace_id)
            except RuntimeError:
                console.print(f"  [yellow]Skipping {table}[/yellow] (not accessible)")
                continue
            for row in rows:
                f.write(json.dumps({"table": table, **row}) + "\n")
                total += 1
        console.print(f"  {total} rows from {len(table_list)} tables")

    console.print(f"\n[green]Backup complete:[/green] {output}")
    console.print(f"  {total} rows written")


@cli.command(name="restore")
@click.argument("workspace_id")
@click.argument("backup_file", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Print what would be restored without making changes")
def restore_cmd(workspace_id: str, backup_file: str, dry_run: bool) -> None:
    """Restore workspace data from a JSONL backup file."""
    client = _sdk_client()
    total = 0
    errors = 0

    with open(backup_file) as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                console.print(f"  [red]Line {line_no}: invalid JSON[/red]")
                errors += 1
                continue

            table = row.pop("table", "")
            if not table:
                console.print(f"  [red]Line {line_no}: missing table field[/red]")
                errors += 1
                continue

            if dry_run:
                console.print(f"  [DRY] {table}: {json.dumps(row)[:80]}...")
                total += 1
                continue

            try:
                # Use store_memory for memory rows, generic _call for others
                if table == "memory":
                    client.store(
                        workspace_id=workspace_id,
                        content=row.get("content", ""),
                        summary=row.get("summary", ""),
                        memory_type=row.get("memory_type", "world_fact"),
                        peer_id=row.get("peer_id", ""),
                    )
                elif table == "session":
                    client._call("create_session", [
                        workspace_id, row.get("id", ""), row.get("name", ""),
                        row.get("summary", ""), row.get("participants_json", "[]"),
                    ])
                elif table == "kg_node":
                    client._call("create_node", [
                        workspace_id, row.get("label", ""), row.get("node_type", ""),
                        row.get("summary", ""), row.get("metadata_json", "{}"),
                    ])
                elif table == "kg_edge":
                    client._call("create_edge", [
                        workspace_id, row.get("source_node_id", ""),
                        row.get("target_node_id", ""), row.get("relation", ""),
                        row.get("weight", 1.0), row.get("confidence", "EXTRACTED"),
                        row.get("metadata_json", "{}"),
                    ])
                elif table == "profile":
                    client._call("upsert_profile", [
                        workspace_id, row.get("peer_id", ""),
                        row.get("static_facts_json", "{}"),
                        row.get("dynamic_context_json", "{}"),
                    ])
                elif table == "insight":
                    client._call("create_insight", [
                        workspace_id, row.get("source", "restore"),
                        row.get("content", ""), row.get("insight_type", "observation"),
                        row.get("entities_json", "[]"), row.get("confidence", 0.7),
                    ])
                elif table == "note":
                    client._call("create_note", [
                        workspace_id, row.get("title", ""), row.get("content", ""),
                        row.get("tags_json", "[]"),
                    ])
                else:
                    console.print(f"  [yellow]Skipping {table} (no restore handler)[/yellow]")
                    continue

                total += 1
            except RuntimeError as e:
                console.print(f"  [red]Line {line_no} ({table}): {e}[/red]")
                errors += 1

    mode = " [DRY-RUN]" if dry_run else ""
    console.print(f"\n[green]Restore complete{mode}:[/green] {total} rows restored, {errors} errors")

# ===================================================================
# serve — MCP server
# ===================================================================


@cli.command(name="serve")
@click.option("--transport", default="stdio",
              type=click.Choice(["stdio", "sse"]),
              help="MCP transport protocol (default: stdio)")
@click.option("--host", default=None, help="SSE listen host (default: SPACETIMEDB_HOST)")
@click.option("--port", default=None, type=int, help="SSE listen port (default: 8100)")
@click.option("--api-key", default=None, help="API key for SSE auth (default: MCP_API_KEY env)")
def serve(transport: str, host: str | None, port: int | None, api_key: str | None) -> None:
    """Start the MCP (Model Context Protocol) server.

    By default runs on stdio transport for local agent integration.
    Use ``--transport sse`` for HTTP/SSE mode.
    """
    host_val = host or os.environ.get("SPACETIMEDB_HOST", "localhost")
    port_val = port if port is not None else int(os.environ.get("SPACETIMEDB_PORT", "3001"))
    db_val = os.environ.get("SPACETIMEDB_DB", "spacetime-memory")
    embedder_url = os.environ.get("EMBEDDER_URL", "http://localhost:9090")

    os.environ.setdefault("SPACETIMEDB_HOST", host_val)
    os.environ.setdefault("SPACETIMEDB_PORT", str(port_val))
    os.environ.setdefault("SPACETIMEDB_DB", db_val)
    os.environ.setdefault("EMBEDDER_URL", embedder_url)
    if api_key:
        os.environ["MCP_API_KEY"] = api_key

    listen_host = os.environ.get("MCP_HOST", "0.0.0.0")
    listen_port = int(os.environ.get("MCP_PORT", "8100"))

    if transport == "sse":
        console.print(f"MCP SSE server starting on http://{listen_host}:{listen_port} ...")
        console.print(f"  DB: {host_val}:{port_val}/{db_val}")
        console.print(f"  Embedder: {embedder_url}")
        console.print(f"  Auth: {'enabled' if os.environ.get('MCP_API_KEY') else 'disabled'}")
    else:
        console.print("MCP stdio server starting ...", highlight=False)

    try:
        from server.mcp.main import run
        run(
            transport=transport,
            host=listen_host if transport == "sse" else None,
            port=listen_port if transport == "sse" else None,
        )
    except ImportError as e:
        console.print(f"[red]Error:[/red] Cannot start MCP server — missing dependencies: {e}")
        console.print("  pip install spacetime-memory[mcp]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] MCP server failed: {e}")
        sys.exit(1)


# ── Veracity ────────────────────────────────────────────────────────────────

@cli.group()
def veracity() -> None:
    """Veracity tiers — Bayesian confidence scoring for memory trustworthiness.

    Mnemosyne-style 5-tier system: stated (1.0), unknown (0.8),
    inferred (0.7), imported (0.6), tool (0.5).

    Examples:
      stmem veracity compound --tier stated --sources 3
      stmem veracity calc --tier inferred --sources 5
    """


@veracity.command(name="compound")
@click.option("--tier", "-t", required=True,
              type=click.Choice(["stated", "unknown", "inferred", "imported", "tool"]),
              help="Veracity tier")
@click.option("--sources", "-s", type=int, default=1, help="Number of independent sources (default 1)")
def veracity_compound_cmd(tier: str, sources: int) -> None:
    """Compute Bayesian compounded confidence for a veracity tier."""
    from spacetime_memory.veracity import VeracityTier, compound, format_veracity

    t = VeracityTier(tier)
    conf = compound(tier=t, sources=sources)
    base = t.base_confidence

    table = Table(title="Veracity Compounding", box=box.ROUNDED)
    table.add_column("Parameter", style="cyan")
    table.add_column("Value")
    table.add_row("Tier", format_veracity(t, conf, sources))
    table.add_row("Base confidence", f"{base:.2f}")
    table.add_row("Sources", str(sources))
    table.add_row("Formula", f"1 - (1-{base:.2f})^{sources}")
    table.add_row("Compounded", f"[bold green]{conf:.4f}[/bold green]")
    table.add_row("Score multiplier", f"{0.5 + conf * 0.5:.2f}x")
    console.print(table)


@veracity.command(name="calc")
@click.option("--tier", "-t",
              type=click.Choice(["stated", "unknown", "inferred", "imported", "tool"]),
              help="Veracity tier to look up base confidence for")
@click.option("--base", "-b", type=float, help="Custom base confidence (0.0-1.0)")
@click.option("--sources", "-s", type=int, default=1, help="Number of sources for compounding")
def veracity_calc_cmd(tier: str | None, base: float | None, sources: int) -> None:
    """Calculate confidence with custom parameters."""
    from spacetime_memory.veracity import VeracityTier, compound, confidence_multiplier

    if tier:
        t = VeracityTier(tier)
        conf = compound(tier=t, sources=sources)
    elif base is not None:
        conf = compound(base=base, sources=sources)
    else:
        console.print("[red]Error:[/red] provide --tier or --base")
        sys.exit(1)

    console.print(f"Confidence: [bold green]{conf:.4f}[/bold green] "
                  f"(× [cyan]{confidence_multiplier(conf):.2f}[/cyan] search multiplier)")


@veracity.command(name="list")
def veracity_list_cmd() -> None:
    """List all veracity tiers with base confidences."""
    from spacetime_memory.veracity import VeracityTier, TIER_LABELS, TIER_SYMBOLS

    table = Table(title="Veracity Tiers", box=box.ROUNDED)
    table.add_column("Symbol", style="bold")
    table.add_column("Tier", style="cyan")
    table.add_column("Label")
    table.add_column("Base", justify="right")

    for tier in VeracityTier:
        table.add_row(
            TIER_SYMBOLS[tier],
            tier.value,
            TIER_LABELS[tier],
            f"{tier.base_confidence:.2f}",
        )

    console.print(table)
    console.print("\\n[dim]Formula: confidence = 1 - (1 - base)^sources[/dim]")


@cli.group()
def aaak() -> None:
    """AAAK compression — lossless LLM context shorthand.

    Compresses text using the Mnemosyne AAAK dialect so LLMs
    consume fewer tokens without losing meaning.

    Examples:
      stmem aaak compress "PREFERENCE: User asked for dark mode"
      stmem aaak ratio memory_id ...
    """


@aaak.command(name="compress")
@click.argument("text", required=False)
@click.option("--file", "-f", type=click.Path(exists=True), help="Read text from file")
@click.option("--pipe", "-p", is_flag=True, help="Read from stdin")
def aaak_compress_cmd(text: str | None, file: str | None, pipe: bool) -> None:
    """Compress text using AAAK shorthand."""
    from pathlib import Path
    from spacetime_memory.aaak import aaak_compress as _compress, aaak_ratio

    if pipe or (not text and not file and sys.stdin.isatty() is False):
        text = sys.stdin.read().strip()
    elif file:
        text = Path(file).read_text().strip()
    elif not text:
        console.print("[red]Error:[/red] provide text, --file, or pipe input")
        sys.exit(1)

    compressed = _compress(text)
    ratio = aaak_ratio(text)

    if pipe or file:
        # Machine-readable output for piping
        console.print(compressed, highlight=False)
    else:
        table = Table(title="AAAK Compression", box=box.ROUNDED)
        table.add_column("Metric", style="cyan")
        table.add_column("Value")
        table.add_row("Original", text[:200] + ("..." if len(text) > 200 else ""))
        table.add_row("Compressed", compressed[:200] + ("..." if len(compressed) > 200 else ""))
        table.add_row("Ratio", f"{ratio:.1%} ({len(text)} → {len(compressed)} chars)")
        table.add_row("Savings", f"{len(text) - len(compressed)} chars ({1-ratio:.0%})")
        console.print(table)


@aaak.command(name="decompress")
@click.argument("text", required=False)
@click.option("--file", "-f", type=click.Path(exists=True), help="Read compressed text from file")
@click.option("--pipe", "-p", is_flag=True, help="Read from stdin")
def aaak_decompress_cmd(text: str | None, file: str | None, pipe: bool) -> None:
    """Partially decompress AAAK shorthand (categories + phrases only)."""
    from pathlib import Path
    from spacetime_memory.aaak import aaak_decompress as _decompress

    if pipe or (not text and not file and sys.stdin.isatty() is False):
        text = sys.stdin.read().strip()
    elif file:
        text = Path(file).read_text().strip()
    elif not text:
        console.print("[red]Error:[/red] provide text, --file, or pipe input")
        sys.exit(1)

    decompressed = _decompress(text)
    if pipe or file:
        console.print(decompressed, highlight=False)
    else:
        console.print(f"[bold]Original:[/bold] {text}")
        console.print(f"[bold]Decompressed:[/bold] {decompressed}")


@aaak.command(name="ratio")
@click.argument("text", required=False)
@click.option("--file", "-f", type=click.Path(exists=True), help="Read text from file")
@click.option("--pipe", "-p", is_flag=True, help="Read from stdin")
def aaak_ratio_cmd(text: str | None, file: str | None, pipe: bool) -> None:
    """Show AAAK compression ratio for text."""
    from pathlib import Path
    from spacetime_memory.aaak import aaak_ratio as _ratio

    if pipe or (not text and not file and sys.stdin.isatty() is False):
        text = sys.stdin.read().strip()
    elif file:
        text = Path(file).read_text().strip()
    elif not text:
        console.print("[red]Error:[/red] provide text, --file, or pipe input")
        sys.exit(1)

    ratio = _ratio(text)
    compressed_len = int(len(text) * ratio)
    console.print(f"AAAK ratio: [cyan]{ratio:.1%}[/cyan] "
                  f"({len(text)} → {compressed_len} chars, "
                  f"[green]{len(text) - compressed_len}[/green] saved)")


if __name__ == "__main__":
    main()
