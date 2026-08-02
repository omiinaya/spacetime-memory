"""CLI commands — veracity module."""

from __future__ import annotations

import sys

import click
from rich.table import Table, box

from ..root import (
    cli,
    console,
)


@cli.group()
def veracity() -> None:
    """Veracity tiers — Bayesian confidence scoring for memory trustworthiness.

    Mnemosyne-style 5-tier system: stated (1.0), unknown (0.8),
    inferred (0.7), imported (0.6), tool (0.5).

    Examples:
      stmem veracity compound --tier stated --sources 3
      stmem veracity calc --tier inferred --sources 5
    """


@veracity.command(name="compound")
@click.option("--tier", "-t", required=True,
              type=click.Choice(["stated", "unknown", "inferred", "imported", "tool"]),
              help="Veracity tier")
@click.option("--sources", "-s", type=int, default=1, help="Number of independent sources (default 1)")
def veracity_compound_cmd(tier: str, sources: int) -> None:
    """Compute Bayesian compounded confidence for a veracity tier."""
    from spacetime_memory.veracity import VeracityTier, compound, format_veracity

    t = VeracityTier(tier)
    conf = compound(tier=t, sources=sources)
    base = t.base_confidence

    table = Table(title="Veracity Compounding", box=box.ROUNDED)
    table.add_column("Parameter", style="cyan")
    table.add_column("Value")
    table.add_row("Tier", format_veracity(t, conf, sources))
    table.add_row("Base confidence", f"{base:.2f}")
    table.add_row("Sources", str(sources))
    table.add_row("Formula", f"1 - (1-{base:.2f})^{sources}")
    table.add_row("Compounded", f"[bold green]{conf:.4f}[/bold green]")
    table.add_row("Score multiplier", f"{0.5 + conf * 0.5:.2f}x")
    console.print(table)


@veracity.command(name="calc")
@click.option("--tier", "-t",
              type=click.Choice(["stated", "unknown", "inferred", "imported", "tool"]),
              help="Veracity tier to look up base confidence for")
@click.option("--base", "-b", type=float, help="Custom base confidence (0.0-1.0)")
@click.option("--sources", "-s", type=int, default=1, help="Number of sources for compounding")
def veracity_calc_cmd(tier: str | None, base: float | None, sources: int) -> None:
    """Calculate confidence with custom parameters."""
    from spacetime_memory.veracity import VeracityTier, compound, confidence_multiplier

    if tier:
        t = VeracityTier(tier)
        conf = compound(tier=t, sources=sources)
    elif base is not None:
        conf = compound(base=base, sources=sources)
    else:
        console.print("[red]Error:[/red] provide --tier or --base")
        sys.exit(1)

    console.print(f"Confidence: [bold green]{conf:.4f}[/bold green] "
                  f"(× [cyan]{confidence_multiplier(conf):.2f}[/cyan] search multiplier)")


@veracity.command(name="list")
def veracity_list_cmd() -> None:
    """List all veracity tiers with base confidences."""
    from spacetime_memory.veracity import TIER_LABELS, TIER_SYMBOLS, VeracityTier

    table = Table(title="Veracity Tiers", box=box.ROUNDED)
    table.add_column("Symbol", style="bold")
    table.add_column("Tier", style="cyan")
    table.add_column("Label")
    table.add_column("Base", justify="right")

    for tier in VeracityTier:
        table.add_row(
            TIER_SYMBOLS[tier],
            tier.value,
            TIER_LABELS[tier],
            f"{tier.base_confidence:.2f}",
        )

    console.print(table)
    console.print("\\n[dim]Formula: confidence = 1 - (1 - base)^sources[/dim]")

