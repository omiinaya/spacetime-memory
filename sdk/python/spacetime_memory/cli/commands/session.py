"""CLI commands — session module.

Includes session management and advanced session distillation commands
(temporal graph, strategies, timeline).
"""
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
def session() -> None:
    """Manage sessions and session distillation."""


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


# ── Session Distillation Commands ──────────────────────────────────────


@session.command(name="distill")
@click.argument("workspace_id")
@click.argument("session_id")
@click.option("--max-messages", "-n", default=100, type=int,
              help="Max messages to analyze")
@click.option("--no-metadata", is_flag=True, default=False,
              help="Exclude session metadata")
def session_distill(workspace_id: str, session_id: str,
                    max_messages: int, no_metadata: bool) -> None:
    """Distill a session into a structured summary.

    Analyzes all messages and produces key topics, decisions, entities, etc.
    """
    with console.status(f"Distilling session '{session_id}'..."):
        result = _sdk_client().distill_session(
            workspace_id=workspace_id,
            session_id=session_id,
            max_messages=max_messages,
            include_metadata=not no_metadata,
        )
    _quiet_print("[green]Session distilled.[/green]")
    print_json(result)


@session.command(name="temporal-graph")
@click.argument("workspace_id")
@click.argument("session_id")
@click.option("--max-events", "-n", default=50, type=int,
              help="Max events to extract")
def session_temporal_graph(workspace_id: str, session_id: str,
                           max_events: int) -> None:
    """Extract temporal events from session messages.

    Detects decisions, action items, and questions with timestamps.
    """
    with console.status(f"Extracting temporal graph for session '{session_id}'..."):
        events = _sdk_client().extract_temporal_graph(
            workspace_id=workspace_id,
            session_id=session_id,
            max_events=max_events,
        )
    if not events:
        console.print("[yellow]No events detected.[/yellow]")
        return
    print_table(events, title=f"Temporal Events (session: {session_id})")


@session.command(name="strategies")
@click.argument("query")
@click.option("--strategy", "-s", default="semantic",
              help="Search strategy (keyword, semantic, hybrid, temporal, ...)")
@click.option("--workspace", "-w", default=None, help="Workspace filter")
@click.option("--limit", "-n", default=10, type=int, help="Max results")
@click.option("--list-strategies", is_flag=True, default=False,
              help="List all available strategies")
def session_strategies(query: str, strategy: str,
                       workspace: str | None, limit: int,
                       list_strategies: bool) -> None:
    """Search sessions using one of 18 strategy variants.

    Use --list-strategies to see all available strategies.
    """
    from spacetime_memory.client._session_distillation import SEARCH_STRATEGIES

    if list_strategies:
        console.print("[bold]Available Search Strategies:[/bold]")
        for name, desc in sorted(SEARCH_STRATEGIES.items()):
            console.print(f"  [green]{name}[/green]: {desc}")
        return

    with console.status(f"Searching with strategy '{strategy}'..."):
        results = _sdk_client().search_session_strategies(
            query=query,
            strategy=strategy,
            workspace_id=workspace,
            limit=limit,
        )
    if not results:
        console.print(f"[yellow]No results for strategy '{strategy}'.[/yellow]")
        return
    print_table(results, title=f"Session Search ({strategy}): '{query}'")


@session.command(name="timeline")
@click.argument("session_id")
@click.option("--limit", "-n", default=100, type=int, help="Max timeline entries")
@click.option("--no-messages", is_flag=True, default=False,
              help="Exclude messages from timeline")
@click.option("--no-events", is_flag=True, default=False,
              help="Exclude detected events from timeline")
def session_timeline(session_id: str, limit: int,
                     no_messages: bool, no_events: bool) -> None:
    """Temporal event timeline for a session.

    Chronologically ordered timeline of messages, agent steps, and events.
    """
    with console.status(f"Building timeline for session '{session_id}'..."):
        timeline = _sdk_client().get_session_timeline(
            session_id=session_id,
            limit=limit,
            include_messages=not no_messages,
            include_events=not no_events,
        )
    if not timeline:
        console.print("[yellow]No timeline entries found.[/yellow]")
        return
    print_table(timeline, title=f"Session Timeline: {session_id}")
