"""Harmonic beliefs and resonance"""

from __future__ import annotations


import click


from .. import root as _root
from ..root import (
    _sdk_client,
    cli,
)

# ===================================================================
# harmonic — harmonic beliefs & resonance
# ===================================================================


@cli.group()
def harmonic() -> None:
    """Manage harmonic beliefs and resonance sessions."""


@harmonic.command(name="store")
@click.argument("workspace_id")
@click.option("--peer-id", required=True, help="Peer identity string")
@click.option("--beliefs", required=True, help="JSON array of belief objects (or JSON file path with @prefix)")
@click.option("--cluster-id", required=True, help="Cluster ID")
def harmonic_store(workspace_id: str, peer_id: str, beliefs: str, cluster_id: str) -> None:
    """Store harmonized beliefs from one resonance round."""
    client = _sdk_client()
    # Support @filepath syntax like curl
    if beliefs.startswith("@"):
        with open(beliefs[1:]) as f:
            beliefs = f.read()
    client.store_harmonic_beliefs(workspace_id, peer_id, beliefs, cluster_id)
    _root.console.print(f"[green]Harmonic beliefs stored for cluster {cluster_id}.[/green]")


@harmonic.command(name="clear")
@click.argument("workspace_id")
@click.option("--min-confidence", default=0.0, type=float, help="Min confidence to keep")
def harmonic_clear(workspace_id: str, min_confidence: float) -> None:
    """Clear stale beliefs below a confidence threshold."""
    client = _sdk_client()
    client.clear_harmonic_beliefs(workspace_id, min_confidence)
    _root.console.print("[green]Stale harmonic beliefs cleared.[/green]")


@harmonic.command(name="log")
@click.argument("workspace_id")
@click.option("--peer-id", required=True, help="Peer identity")
@click.option("--clusters", type=int, default=0, help="Number of clusters identified")
@click.option("--beliefs", "beliefs_generated", type=int, default=0, help="Beliefs generated")
@click.option("--contradictions", type=int, default=0, help="Contradictions resolved")
@click.option("--harmony-avg", type=float, default=0.0, help="Average harmony score")
@click.option("--duration-ms", type=int, default=0, help="Session duration in ms")
def harmonic_log(workspace_id: str, peer_id: str, clusters: int,
                 beliefs_generated: int, contradictions: int,
                 harmony_avg: float, duration_ms: int) -> None:
    """Log a resonance session summary."""
    client = _sdk_client()
    client.log_resonance_session(
        workspace_id, peer_id, clusters, beliefs_generated,
        contradictions, harmony_avg, duration_ms,
    )
    _root.console.print("[green]Resonance session logged.[/green]")
