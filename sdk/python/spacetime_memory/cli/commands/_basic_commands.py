"""CLI commands — basic commands."""

from __future__ import annotations

from typing import Any

import click

from ..root import (
    _sdk_client,
    cli,
    console,
    print_json,
)


@cli.command(name="completion")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completion(shell: str) -> None:
    """Generate shell completion script.

    Usage: eval "$(stmem completion bash)"
    """
    if shell == "bash":
        click.echo('eval "$(_STMEM_COMPLETE=bash_source stmem)"')
    elif shell == "zsh":
        click.echo('eval "$(_STMEM_COMPLETE=zsh_source stmem)"')
    elif shell == "fish":
        click.echo('eval "$(_STMEM_COMPLETE=fish_source stmem)"')


@cli.command(name="recommend")
@click.argument("workspace_id")
@click.option("--limit", default=20, type=int, help="Max recommendations")
@click.option("--min-urgency", default=0.3, type=float,
              help="Minimum urgency threshold (0.0-1.0)")
@click.pass_context
def recommend(ctx: click.Context, workspace_id: str, limit: int,
              min_urgency: float) -> None:
    """Recommend memories needing attention (review/reinforce/discard)."""

    def _run() -> list[dict[str, Any]]:
        with console.status("Analyzing memories..."):
            return _sdk_client().recommend_memories(
                workspace_id, limit=limit, min_urgency=min_urgency,
            )

    rows = _run()
    if rows:
        # Color by action
        action_colors = {"discard": "red", "reinforce": "yellow", "review": "cyan"}
        for r in rows:
            action = r.get("action", "review")
            color = action_colors.get(action, "white")
            urgency = r.get("urgency", 0.0)
            content = (r.get("content", "") or "")[:120]
            console.print(
                f"[{color}][{action.upper():>9}][/{color}] "
                f"[dim]urgency={urgency:.2f}[/dim] "
                f"trust={r.get('trust_score', 0):.2f} "
                f"fb={r.get('feedback_count', 0)} "
                f"[italic]{content}[/italic]"
            )
        if ctx.obj.get("output") == "json":
            print_json(rows)
    else:
        console.print("[green]No memories need attention — all clear![/green]")



@cli.command(name="peer-reputation")
@click.argument("peer_id")
def peer_reputation(peer_id: str) -> None:
    """Show reputation stats for a peer."""
    client = _sdk_client()
    with console.status(f"Fetching reputation for '{peer_id[:16]}...'..."):
        rep = client.get_peer_reputation(peer_id)
    if rep:
        from rich import box
        from rich.table import Table
        table = Table(title=f"Peer Reputation ({peer_id[:16]}...)", box=box.ROUNDED)
        table.add_column("Metric", style="cyan")
        table.add_column("Value")
        table.add_row("Reputation", f"{rep.get('reputation_score', 0):.3f}")
        table.add_row("Helpful", str(rep.get("helpful_count", 0)))
        table.add_row("Unhelpful", str(rep.get("unhelpful_count", 0)))
        table.add_row("Total", str(rep.get("total_feedback", 0)))
        console.print(table)
    else:
        console.print(f"[yellow]No reputation data for peer '{peer_id[:16]}...'[/yellow]")

@cli.command(name="synthesize")
@click.argument("workspace_id")
@click.argument("query")
@click.option("--budget", default=4096, type=int, help="Token budget for context (default: 4096)")
def synthesize_cmd(workspace_id: str, query: str, budget: int) -> None:
    """Synthesize a grounded answer with gap analysis (GBrain-style).

    Searches the workspace, finds relevant memories, and calls an LLM to
    produce a structured answer that includes:

    \b
    - answer: synthesized answer grounded in found memories
    - gaps: what the knowledge base does NOT contain
    - sources: indices of source memories used
    - confidence: 0.0-1.0

    Requires OPENAI_API_KEY for LLM calls.

    Example:
        stmem synthesize my-workspace "What do we know about Alice Chen?"
    """
    from spacetime_memory.context_agent import ContextAgent

    client = _sdk_client()
    agent = ContextAgent(client)

    with console.status("Synthesizing with gap analysis..."):
        result = agent.synthesize(query, workspace_id=workspace_id, token_budget=budget)

    if result.get("error"):
        console.print(f"[red]{result['error']}[/red]")
        return

    answer = result.get("answer")
    gaps = result.get("gaps", [])
    sources = result.get("sources", [])
    confidence = result.get("confidence", 0.0)

    if answer:
        console.print(f"\n[bold green]Answer[/bold green] (confidence: {confidence:.0%})")
        console.print(f"[dim]{'─' * 60}[/dim]")
        console.print(answer)
    else:
        console.print("\n[yellow]LLM unavailable — showing raw context entries.[/yellow]")
        if "pack" in result:
            pack = result["pack"]
            console.print(f"  Pack: {pack.get('id', '')[:16]}...")

    if gaps:
        console.print(f"\n[bold yellow]Knowledge Gaps[/bold yellow] ({len(gaps)})")
        console.print(f"[dim]{'─' * 60}[/dim]")
        for i, gap in enumerate(gaps, 1):
            console.print(f"  {i}. {gap}")

    if sources:
        console.print(f"\n[bold dim]Sources[/bold dim]: {' '.join(str(s) for s in sources)}")

