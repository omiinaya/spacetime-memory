"""Replication management"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import click


from .. import root as _root
from ..root import (
    _esc,
    _quiet_print,
    _sdk_client,
    cli,
    print_json,
    print_table,
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
    with _root.console.status("Fetching replication peers..."):
        client._call("list_replication_peers", [workspace_id or "*"])
        rows = client._query(
            "replication_result",
            filter_dict={"query_type": "peers"},
        )
    if rows:
        rows.sort(key=lambda r: r.get("created_at", 0) or 0, reverse=True)
        rows = rows[:1]
    if not rows:
        _root.console.print("[yellow]No replication peers found.[/yellow]")
        return
    peers = json.loads(rows[0].get("json_data", "[]"))
    if not peers:
        _root.console.print("[yellow]No replication peers found.[/yellow]")
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
            _root.console.print("[red]No workspaces found. Create one first or specify --workspace-id.[/red]")
            sys.exit(1)
        ws_id = workspaces[0]["id"]
        _root.console.print(f"[dim]Using workspace: {ws_id}[/dim]")

    with _root.console.status(f"Adding replication peer '{name}'..."):
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
    with _root.console.status(f"Registering replication peer '{peer_name}'..."):
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
    with _root.console.status(f"Removing replication peer '{peer_id}'..."):
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
                _root.console.print("[red]No workspaces found. Create one first or specify --workspace-id.[/red]")
                sys.exit(1)
            ws_id = workspaces[0]["id"]
        return ws_id

    def _run() -> dict[str, Any] | None:
        ws_id = _resolve_ws()
        with _root.console.status("Fetching replication status..."):
            client._call("get_replication_status", [ws_id])
            rows = client._query(
                "replication_result",
                filter_dict={"query_type": "status", "workspace_id": ws_id},
            )
        if rows:
            rows.sort(key=lambda r: r.get("created_at", 0) or 0, reverse=True)
            rows = rows[:1]
        if not rows:
            _root.console.print("[yellow]No replication status available.[/yellow]")
            return None
        status = json.loads(rows[0].get("json_data", "{}"))
        if not status:
            _root.console.print("[yellow]Empty status response.[/yellow]")
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
                _root.console.clear()
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
        _root.console.print("[red]Error: replication_daemon.py not found in scripts/[/red]")
        sys.exit(1)

    with _root.console.status("Running sync cycle..."):
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
        _root.console.print("[red]Error: replication_daemon.py not found in scripts/[/red]")
        sys.exit(1)

    daemon = ReplicationDaemon(interval=interval, once=False, mode=mode)
    daemon.run()
