"""CLI commands — admin module."""

from __future__ import annotations

import click

from ..root import (
    _sdk_client,
    cli,
    console,
    print_table,
)


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
        rows = client._query("admin_list_result")
        rows.sort(key=lambda r: r.get("created_at", ""))
    if not rows:
        console.print("[yellow]No admin accounts found.[/yellow]")
        return
    print_table(rows, title="Admin Accounts")

