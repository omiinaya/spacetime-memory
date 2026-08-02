"""CLI commands — decay module."""

from __future__ import annotations

import click

from ..root import (
    _quiet_print,
    _sdk_client,
    cli,
    console,
)


@cli.group()
def decay() -> None:
    """Manage reputation decay configuration."""


@decay.command(name="set-linear")
@click.argument("workspace_id")
@click.option("--rate", default=0.005, type=float, help="Decay rate per day (default: 0.005 = 0.5%%)")
@click.option("--max-days", default=90, type=int, help="Max days before floor (default: 90)")
def decay_set_linear(workspace_id: str, rate: float, max_days: int) -> None:
    """Set linear decay model for a workspace."""
    client = _sdk_client()
    with console.status(f"Applying linear decay to workspace '{workspace_id[:12]}...'..."):
        client.set_decay_model(workspace_id, model="linear", decay_rate=rate, max_days=max_days)
    _quiet_print(f"[green]Linear decay configured: {rate:.3f}/day, max {max_days} days[/green]")


@decay.command(name="set-weibull")
@click.argument("workspace_id")
@click.option("--shape", "-k", default=0.6, type=float,
              help="Weibull shape k (< 1 = rapid-then-slow, default: 0.6)")
@click.option("--scale", "-l", default=30.0, type=float,
              help="Weibull scale λ in days (default: 30)")
def decay_set_weibull(workspace_id: str, shape: float, scale: float) -> None:
    """Set Weibull decay model for a workspace.

    Weibull formula: trust = initial * exp(-(t/λ)^k)

    At t=λ, trust ≈ 37% of initial.
    At t=3λ, trust ≈ 5%.
    """
    client = _sdk_client()
    with console.status(f"Applying Weibull decay to workspace '{workspace_id[:12]}...'..."):
        client.set_decay_model(workspace_id, model="weibull",
                               weibull_shape=shape, weibull_scale=scale)
    _quiet_print(f"[green]Weibull decay configured: k={shape}, λ={scale} days[/green]")


@decay.command(name="show")
@click.argument("workspace_id")
def decay_show(workspace_id: str) -> None:
    """Show current decay configuration for a workspace."""
    client = _sdk_client()
    config = client.get_decay_config(workspace_id)
    if config:
        from rich import box
        from rich.table import Table
        table = Table(title=f"Decay Config ({workspace_id[:12]}...)", box=box.ROUNDED)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        for k, v in config.items():
            table.add_row(k, str(v))
        console.print(table)
    else:
        console.print("[yellow]No decay config set (defaults: linear, 0.5%/day, 90 day max)[/yellow]")


@decay.command(name="run")
@click.argument("workspace_id")
def decay_run(workspace_id: str) -> None:
    """Run one decay cycle for a workspace using current config."""
    client = _sdk_client()
    config = client.get_decay_config(workspace_id)
    model = (config or {}).get("decay_model", "linear")
    with console.status(f"Running {model} decay on workspace '{workspace_id[:12]}...'..."):
        if model == "weibull":
            k = (config or {}).get("weibull_shape", 0.6)
            lmbda = (config or {}).get("weibull_scale", 30.0)
            client.set_decay_model(workspace_id, model="weibull", weibull_shape=k, weibull_scale=lmbda)
        else:
            rate = (config or {}).get("decay_rate", 0.005)
            max_days = (config or {}).get("max_decay_days", 90)
            client.set_decay_model(workspace_id, model="linear", decay_rate=rate, max_days=max_days)
    _quiet_print(f"[green]{model} decay cycle complete[/green]")

