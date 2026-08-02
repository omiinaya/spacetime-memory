"""API key management"""

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
    with _root.console.status(f"Creating API key '{name}'..."):
        result = client.create_api_key(workspace_id, name, permissions)
    key = result.get("api_key", "")
    _quiet_print(f"[green]API key '{name}' created successfully.[/green]")
    _quiet_print("[bold yellow]Save this key — it will not be shown again:[/bold yellow]")
    _root.console.print(key)
    if _root._current_output_format == "json":
        print_json(result)


@apikey.command(name="revoke")
@click.argument("key_id")
def apikey_revoke(key_id: str) -> None:
    """Deactivate (revoke) an API key by its ID."""
    client = _sdk_client()
    with _root.console.status(f"Revoking API key '{key_id[:16]}...'..."):
        result = client.deactivate_api_key(key_id)
    _quiet_print(f"[green]API key '{key_id[:16]}...' revoked.[/green]")
    if result and _root._current_output_format == "json":
        print_json(result)


@apikey.command(name="list")
@click.argument("workspace_id")
def apikey_list(workspace_id: str) -> None:
    """List all API keys for a workspace."""
    client = _sdk_client()
    with _root.console.status(f"Fetching API keys for workspace '{workspace_id[:16]}...'..."):
        rows = client.list_api_keys(workspace_id)
    print_table(rows, title=f"API Keys (workspace: {workspace_id})")
