"""CLI commands — peer module."""

from __future__ import annotations

import click

from ..root import (
    _quiet_print,
    _sdk_client,
    cli,
    console,
    parse_json_flag,
    print_json,
    print_table,
)


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

