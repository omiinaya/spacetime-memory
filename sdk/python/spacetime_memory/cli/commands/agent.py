"""CLI commands — agent module."""

from __future__ import annotations

import click

from ..root import (
    _esc,
    _quiet_print,
    _sdk_client,
    cli,
    console,
    print_json,
    print_table,
)


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

    # For a simple step without orchestration state, just call the reducer directly
    client = _sdk_client()
    if workspace_id:
        w_id = workspace_id
    else:
        # Try to infer workspace from session
        rows = client._sql_param(
            "SELECT workspace_id FROM session WHERE id = ?",
            session_id,
        )
        w_id = rows[0]["workspace_id"] if rows else "default"

    client._call("add_agent_step", [session_id, w_id, step_type, content, summary, ""])
    # Discover step ID (STDB SQL has no ORDER BY — sort client-side)
    rows = client._sql(
        "SELECT id FROM agent_step WHERE "
        f"session_id = '{_esc(session_id)}'"
    )
    if rows:
        rows.sort(key=lambda r: r.get("created_at", 0) or 0, reverse=True)
        rows = rows[:1]
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
    rows = client._query("session_step_result", filter_dict={"query_hash": query_hash})
    rows.sort(key=lambda r: r.get("created_at", ""))
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
        rows = client._sql_param(
            "SELECT workspace_id FROM session WHERE id = ?",
            session_id,
        )
        w_id = rows[0]["workspace_id"] if rows else "default"

    orch = AgentOrchestrator(client, workspace_id=w_id)
    context = orch.get_context(query=query, top_k=top_k, session_id=session_id)
    if not context:
        console.print("[yellow]No context found.[/yellow]")
        return
    print_table(context, title=f"Agent Context (session: {session_id[:16]}...)")

