"""Pattern detection and peer reputation"""

from __future__ import annotations

import datetime

import click
from rich import box
from rich.table import Table


from .. import root as _root
from ..root import (
    _sdk_client,
    cli,
    print_json,
)

# ===================================================================
# detect-patterns command
# ===================================================================


@cli.command(name="detect-patterns")
@click.argument("workspace_id")
@click.option("--limit", default=200, type=int, help="Max memories to analyze")
@click.option("--no-clusters", is_flag=True, help="Skip temporal clustering")
@click.option("--no-terms", is_flag=True, help="Skip frequent term extraction")
@click.option("--no-co-occur", is_flag=True, help="Skip co-occurrence detection")
@click.pass_context
def detect_patterns_cmd(ctx: click.Context, workspace_id: str, limit: int,
                        no_clusters: bool, no_terms: bool, no_co_occur: bool) -> None:
    """Run pattern detection on a workspace's memories.

    Analyzes temporal patterns, frequent terms, and co-occurrence
    relationships — no LLM needed, purely statistical.
    """
    result = {}
    with _root.console.status(f"Analyzing workspace '{workspace_id}'..."):
        result = _sdk_client().detect_patterns(
            workspace_id,
            limit=limit,
            include_clusters=not no_clusters,
            include_terms=not no_terms,
            include_co_occur=not no_co_occur,
        )

    if not result or result.get("total_memories", 0) == 0:
        _root.console.print("[yellow]No memories found to analyze.[/yellow]")
        return

    total = result.get("total_memories", 0)
    summary = result.get("summary", "")
    clusters = result.get("temporal_clusters", [])
    terms = result.get("frequent_terms", [])
    co_occurs = result.get("co_occurrences", [])

    _root.console.print(f"\n[bold]Pattern Detection Results[/bold] — [dim]{total} memories[/dim]")
    _root.console.print(f"[italic]{summary}[/italic]\n")

    # Temporal Clusters
    if clusters:
        _root.console.print(f"[bold cyan]Temporal Clusters ({len(clusters)}):[/bold cyan]")
        for i, c in enumerate(clusters[:10], 1):
            ts = datetime.datetime.fromtimestamp(
                c.get("start_time", 0)
            ).strftime("%Y-%m-%d %H:%M")
            count = c.get("count", 0)
            terms_str = ", ".join(c.get("summary_terms", [])[:3])
            _root.console.print(
                f"  {i}. [yellow]{ts}[/yellow] — {count} memories"
                + (f" [dim]({terms_str})[/dim]" if terms_str else "")
            )
        if len(clusters) > 10:
            _root.console.print(f"  ... and {len(clusters) - 10} more")
    else:
        _root.console.print("[dim]No temporal clusters found.[/dim]")

    # Frequent Terms
    if terms:
        _root.console.print(f"\n[bold cyan]Frequent Terms ({len(terms)}):[/bold cyan]")
        table = Table(show_header=True, box=box.SIMPLE)
        table.add_column("Term", style="yellow")
        table.add_column("Frequency", justify="right")
        table.add_column("Docs", justify="right")
        for t in terms[:15]:
            table.add_row(t["term"], str(t.get("frequency", 0)), str(t.get("doc_count", 0)))
        _root.console.print(table)
    else:
        _root.console.print("[dim]No frequent terms found.[/dim]")

    # Co-occurrences
    if co_occurs:
        _root.console.print(f"\n[bold cyan]Co-occurrences ({len(co_occurs)}):[/bold cyan]")
        table = Table(show_header=True, box=box.SIMPLE)
        table.add_column("Term A", style="cyan")
        table.add_column("Term B", style="cyan")
        table.add_column("Count", justify="right")
        if "strength" in co_occurs[0]:
            table.add_column("Strength", justify="right")
        for c in co_occurs[:10]:
            row = [c.get("term_a", ""), c.get("term_b", ""), str(c.get("count", 0))]
            if "strength" in c:
                row.append(f"{c['strength']:.3f}")
            table.add_row(*row)
        _root.console.print(table)
    else:
        _root.console.print("[dim]No co-occurrences found.[/dim]")

    if ctx.obj.get("output") == "json":
        print_json(result)


@cli.command(name="peer-reputation")
@click.argument("peer_id")
def peer_reputation(peer_id: str) -> None:
    """Show reputation stats for a peer."""
    client = _sdk_client()
    with _root.console.status(f"Fetching reputation for '{peer_id[:16]}...'..."):
        rep = client.get_peer_reputation(peer_id)
    if rep:
        from rich.table import Table
        from rich import box
        table = Table(title=f"Peer Reputation ({peer_id[:16]}...)", box=box.ROUNDED)
        table.add_column("Metric", style="cyan")
        table.add_column("Value")
        table.add_row("Reputation", f"{rep.get('reputation_score', 0):.3f}")
        table.add_row("Helpful", str(rep.get("helpful_count", 0)))
        table.add_row("Unhelpful", str(rep.get("unhelpful_count", 0)))
        table.add_row("Total", str(rep.get("total_feedback", 0)))
        _root.console.print(table)
    else:
        _root.console.print(f"[yellow]No reputation data for peer '{peer_id[:16]}...'[/yellow]")
