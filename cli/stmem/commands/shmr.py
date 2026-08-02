"""Self-harmonizing memory reasoning"""

from __future__ import annotations


import click


from .. import root as _root
from ..root import (
    _sdk_client,
    cli,
)

# ===================================================================
# shmr — self-harmonizing memory reasoning
# ===================================================================


@cli.group()
def shmr() -> None:
    """Self-Harmonizing Memory Reasoning — resonance & belief convergence."""


@shmr.command(name="resonate")
@click.argument("workspace_id")
@click.option("--days", default=7, type=int, help="Days of memories to consider")
@click.option("--iterations", default=3, type=int, help="Max resonance rounds")
@click.option("--threshold", default=0.7, type=float,
              help="Cosine similarity threshold for clustering")
@click.option("--dry-run", is_flag=True, help="Print without storing")
def shmr_resonate_cmd(workspace_id: str, days: int, iterations: int,
                      threshold: float, dry_run: bool) -> None:
    """Run SHMR resonance on a workspace — cluster memories, resolve
    contradictions, converge on stable beliefs."""
    from spacetime_memory.shmr import shmr_resonate
    client = _sdk_client()

    with _root.console.status(f"Resonating workspace {workspace_id[:16]}..."):
        result = shmr_resonate(
            client,
            workspace_id,
            days=days,
            max_iterations=iterations,
            similarity_threshold=threshold,
            dry_run=dry_run,
        )

    mode = " [DRY-RUN]" if dry_run else ""
    _root.console.print(f"\n[bold]SHMR Resonance{mode}:[/bold]")
    _root.console.print(f"  Clusters found:       {result.clusters_found}")
    _root.console.print(f"  Beliefs generated:    {result.beliefs_generated}")
    _root.console.print(f"  Contradictions:       {result.contradictions_resolved}")
    _root.console.print(f"  Harmony score avg:    {result.harmony_score_avg:.2f}")
    _root.console.print(f"  Duration:             {result.duration_ms}ms")
    if result.errors:
        _root.console.print(f"  [yellow]Errors: {result.errors}[/yellow]")
