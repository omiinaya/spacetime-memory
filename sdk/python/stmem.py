"""Command-line interface for spacetime-memory.

Usage:

    stmem --help
    stmem workspace list
    stmem memory store <workspace> <content> [options]
    stmem memory search <workspace> <query> [options]
"""

import sys
import json
import click
from spacetime_memory import Client
from spacetime_memory.plugin_manager import PluginManager, SandboxConfig


# Shared client factory (can be overridden for testing)
def _make_client(**kwargs) -> Client:
    """Build a Client from env vars / defaults."""
    return Client(**kwargs)


# ------------------------------------------------------------------
# Main group
# ------------------------------------------------------------------


@click.group()
@click.option("--host", envvar="SPACETIMEDB_HOST", default=None, help="SpacetimeDB host")
@click.option("--port", envvar="SPACETIMEDB_PORT", default=None, help="SpacetimeDB port")
@click.option("--db", envvar="SPACETIMEDB_DB", default=None, help="Database name")
@click.option("--embedder", envvar="EMBEDDER_URL", default=None, help="Embedder sidecar URL")
@click.pass_context
def cli(ctx, host, port, db, embedder):
    """spacetime-memory CLI — manage workspaces, memories, and knowledge graphs."""
    ctx.ensure_object(dict)
    ctx.obj["client"] = _make_client(
        host=host,
        port=port,
        database=db,
        embedder_url=embedder,
    )


# ------------------------------------------------------------------
# Workspace commands
# ------------------------------------------------------------------


@cli.group()
def workspace():
    """Manage workspaces."""
    pass


@workspace.command("list")
@click.pass_context
def workspace_list(ctx):
    """List all workspaces."""
    client = ctx.obj["client"]
    rows = client.list_workspaces()
    for row in rows:
        click.echo(json.dumps(row, indent=2))
    if not rows:
        click.echo("(no workspaces)")


@workspace.command("create")
@click.argument("name")
@click.option("--description", default="")
@click.pass_context
def workspace_create(ctx, name, description):
    """Create a new workspace."""
    client = ctx.obj["client"]
    result = client.create_workspace(name, description=description)
    click.echo(json.dumps(result, indent=2))


# ------------------------------------------------------------------
# Memory commands
# ------------------------------------------------------------------


@cli.group()
def memory():
    """Manage memories."""
    pass


@memory.command("store")
@click.argument("workspace_id")
@click.argument("content")
@click.option("--peer-id", default="")
@click.option("--memory-type", default="experience")
@click.option("--tier", default="")
@click.pass_context
def memory_store(ctx, workspace_id, content, peer_id, memory_type, tier):
    """Store a memory."""
    client = ctx.obj["client"]
    result = client.store(
        workspace_id=workspace_id,
        content=content,
        peer_id=peer_id,
        memory_type=memory_type,
        tier=tier,
    )
    click.echo(json.dumps(result, indent=2))


@memory.command("search")
@click.argument("workspace_id")
@click.argument("query")
@click.option("--memory-type", default="")
@click.option("--limit", default=20, type=int)
@click.option("--keyword", is_flag=True, default=False, help="Use keyword-only search")
@click.pass_context
def memory_search(ctx, workspace_id, query, memory_type, limit, keyword):
    """Search memories."""
    client = ctx.obj["client"]
    rows = client.search(
        workspace_id=workspace_id,
        query=query,
        memory_type=memory_type,
        limit=limit,
        semantic=not keyword,
    )
    for row in rows:
        click.echo(json.dumps(row, indent=2))
    if not rows:
        click.echo("(no results)")


@memory.command("list")
@click.argument("workspace_id")
@click.option("--memory-type", default="")
@click.option("--limit", default=50, type=int)
@click.pass_context
def memory_list(ctx, workspace_id, memory_type, limit):
    """List memories in a workspace."""
    client = ctx.obj["client"]
    rows = client.list_memories(
        workspace_id=workspace_id,
        memory_type=memory_type,
        limit=limit,
    )
    for row in rows:
        click.echo(json.dumps(row, indent=2))
    if not rows:
        click.echo("(no memories)")


# ------------------------------------------------------------------
# Plugin commands
# ------------------------------------------------------------------


@cli.group()
def plugin():
    """Manage plugins and sandbox compliance."""
    pass


@plugin.command("verify")
@click.argument("name", required=False, default=None)
@click.option("--plugin-dir", default="~/.spacetime-memory/plugins",
              help="Plugin directory (default: ~/.spacetime-memory/plugins)")
@click.pass_context
def plugin_verify(ctx, name, plugin_dir):
    """Check sandbox compliance for plugins.

    If NAME is given, verify a single plugin.  Otherwise check all
    discovered plugins.
    """
    client = ctx.obj["client"]
    mgr = PluginManager(client, plugin_dir=plugin_dir)
    mgr.discover()

    if name:
        # Load the specific plugin so we can verify it
        if mgr.load(name):
            report = mgr.verify_sandbox(name)
            click.echo(json.dumps(report, indent=2, default=str))
        else:
            click.echo(f"Plugin '{name}' could not be loaded for verification.")
    else:
        # Load all and verify
        loaded = mgr.load_all()
        reports = mgr.verify()
        click.echo(json.dumps(reports, indent=2, default=str))
        click.echo(f"\nLoaded {len(loaded)} plugin(s), verified {len(reports)} total.")


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    cli()
