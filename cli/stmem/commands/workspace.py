"""Workspace management"""

from __future__ import annotations


import click


from .. import root as _root
from ..root import (
    _quiet_print,
    _sdk_client,
    cli,
    print_json,
    print_table,
)

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
    with _root.console.status(f"Creating workspace '{name}'..."):
        result = client.create_workspace(name, description)
    _quiet_print(f"[green]Workspace '{name}' created successfully.[/green]")
    if result:
        print_json(result)


@workspace.command(name="list")
def workspace_list() -> None:
    """List all workspaces."""
    with _root.console.status("Fetching workspaces..."):
        rows = _sdk_client().list_workspaces()
    rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
    print_table(rows, title="Workspaces")
