"""CLI commands — space module."""

from __future__ import annotations

import click

from ..root import (
    _quiet_print,
    _sdk_client,
    cli,
    console,
    print_table,
)


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
        rows = client._query("space_member_result", filter_dict={"workspace_id": workspace_id})
        rows.sort(key=lambda r: r.get("created_at", ""))
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

