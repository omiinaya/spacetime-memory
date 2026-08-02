"""Sessions"""

from __future__ import annotations


import click


from .. import root as _root
from ..root import (
    _quiet_print,
    _sdk_client,
    cli,
    parse_json_flag,
    print_json,
    print_table,
)

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
    with _root.console.status(f"Creating session '{name}'..."):
        result = _sdk_client()._call("create_session", [workspace_id, name, metadata])
    _quiet_print(f"[green]Session '{name}' created.[/green]")
    if result:
        print_json(result)


@session.command(name="messages")
@click.argument("session_id")
def session_messages(session_id: str) -> None:
    """Get messages for a session."""
    with _root.console.status(f"Fetching messages for session '{session_id}'..."):
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
    with _root.console.status(f"Searching sessions for '{query}'..."):
        rows = _sdk_client().search_sessions_semantic(query=query, limit=limit)
    if not rows:
        _root.console.print("[yellow]No matching sessions found.[/yellow]")
        return
    print_table(
        rows,
        title=f"Session Search: '{query}'",
    )
