"""Synthesize command"""

from __future__ import annotations


import click


from .. import root as _root
from ..root import (
    _sdk_client,
    cli,
)

# ===================================================================
# backup / restore
# ===================================================================


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

    with _root.console.status("Synthesizing with gap analysis..."):
        result = agent.synthesize(query, workspace_id=workspace_id, token_budget=budget)

    if result.get("error"):
        _root.console.print(f"[red]{result['error']}[/red]")
        return

    answer = result.get("answer")
    gaps = result.get("gaps", [])
    sources = result.get("sources", [])
    confidence = result.get("confidence", 0.0)

    if answer:
        _root.console.print(f"\n[bold green]Answer[/bold green] (confidence: {confidence:.0%})")
        _root.console.print(f"[dim]{'─' * 60}[/dim]")
        _root.console.print(answer)
    else:
        _root.console.print("\n[yellow]LLM unavailable — showing raw context entries.[/yellow]")
        if "pack" in result:
            pack = result["pack"]
            _root.console.print(f"  Pack: {pack.get('id', '')[:16]}...")

    if gaps:
        _root.console.print(f"\n[bold yellow]Knowledge Gaps[/bold yellow] ({len(gaps)})")
        _root.console.print(f"[dim]{'─' * 60}[/dim]")
        for i, gap in enumerate(gaps, 1):
            _root.console.print(f"  {i}. {gap}")

    if sources:
        _root.console.print(f"\n[bold dim]Sources[/bold dim]: {' '.join(str(s) for s in sources)}")
