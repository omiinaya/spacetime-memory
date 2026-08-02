"""Request and performance metrics"""

from __future__ import annotations

import json

import click
from rich import box
from rich.table import Table


from .. import root as _root
from ..root import (
    _sdk_client,
    cli,
)

# ===================================================================
# metrics — request and performance metrics
# ===================================================================


@cli.group()
def metrics() -> None:
    """View request metrics and performance statistics."""


@metrics.command(name="show")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def metrics_show(as_json: bool, token: str | None) -> None:
    """Show collected request metrics (counts, latency, errors).

    Metrics are collected from the moment the client is created.
    Use ``stmem metrics reset`` to clear counters.
    Use ``stmem metrics watch`` for a live updating view.
    """
    from spacetime_memory.metrics import MetricsCollector

    client = _sdk_client()
    if token:
        client.token = token

    # Attach a one-shot collector and run a few probes
    mc = MetricsCollector()
    client.set_metrics_collector(mc)

    with _root.console.status("Gathering metrics..."):
        # Run health and memory count queries to populate the collector
        try:
            client.ping()  # records under "sql" via _sql or reducer
        except (OSError, json.JSONDecodeError):
            pass
        try:
            rows = client._sql("SELECT COUNT(*) AS c FROM memory")
            total_memories = rows[0]["c"] if rows else 0
        except (OSError, json.JSONDecodeError):
            total_memories = 0
        try:
            ws_rows = client.list_workspaces()
            workspace_count = len(ws_rows) if ws_rows else 0
        except (OSError, json.JSONDecodeError):
            workspace_count = 0

        mc.record_memory_stats(total=total_memories)
        # Add system-level info
        ping_result = client.ping()

    if as_json:
        data = mc.to_dict()
        data["workspace_count"] = workspace_count
        data["database_latency_ms"] = ping_result.get("latency_ms", 0)
        _root.console.print_json(json.dumps(data, default=str))
        return

    d = mc.to_dict()

    # Overview
    table = Table(title="Metrics Overview", box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Uptime", d["uptime_human"])
    table.add_row("Total Calls", str(d["total_calls"]))
    table.add_row("Total Errors", str(d["total_errors"]))
    table.add_row("Error Rate", f"{d['overall_error_rate_pct']}%")
    table.add_row("Embedder Errors", str(d["embedder_errors"]))
    table.add_row("Workspaces", str(workspace_count))
    table.add_row("Total Memories", str(total_memories))
    table.add_row("Database Latency", f"{ping_result.get('latency_ms', 0)}ms")
    _root.console.print(table)

    # Per-endpoint breakdown
    if d["endpoints"]:
        ep_table = Table(title="Per-Endpoint Breakdown", box=box.ROUNDED, header_style="bold cyan")
        ep_table.add_column("Endpoint")
        ep_table.add_column("Count")
        ep_table.add_column("Errors")
        ep_table.add_column("Error %")
        ep_table.add_column("Avg (ms)")
        ep_table.add_column("Min (ms)")
        ep_table.add_column("Max (ms)")
        for name, stats in sorted(d["endpoints"].items()):
            ep_table.add_row(
                name,
                str(stats["count"]),
                str(stats["errors"]),
                f"{stats['error_rate_pct']}%",
                str(stats["latency_ms"]["avg"]),
                str(stats["latency_ms"]["min"]),
                str(stats["latency_ms"]["max"]),
            )
        _root.console.print(ep_table)


@metrics.command(name="reset")
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def metrics_reset(token: str | None) -> None:
    """Reset all metrics counters to zero."""
    from spacetime_memory.metrics import MetricsCollector

    client = _sdk_client()
    if token:
        client.token = token

    mc = MetricsCollector()
    client.set_metrics_collector(mc)
    _root.console.print("[green]Metrics counters reset.[/green]")


@metrics.command(name="watch")
@click.option("--interval", "-i", default=5, type=int, help="Refresh interval (seconds)")
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def metrics_watch(interval: int, token: str | None) -> None:
    """Live-updating metrics view (refreshes every N seconds)."""
    from spacetime_memory.metrics import MetricsCollector

    client = _sdk_client()
    if token:
        client.token = token

    mc = MetricsCollector()
    client.set_metrics_collector(mc)

    try:
        while True:
            import time as _time
            _root.console.clear()
            try:
                client.ping()
                rows = client._sql("SELECT COUNT(*) AS c FROM memory")
                total_memories = rows[0]["c"] if rows else 0
            except (OSError, json.JSONDecodeError):
                total_memories = 0

            mc.record_memory_stats(total=total_memories)
            d = mc.to_dict()

            table = Table(title=f"Live Metrics (refreshing every {interval}s — Ctrl+C to stop)",
                          box=box.ROUNDED, header_style="bold cyan")
            table.add_column("Metric", style="bold")
            table.add_column("Value")
            table.add_row("Uptime", d["uptime_human"])
            table.add_row("Total Calls", str(d["total_calls"]))
            table.add_row("Errors", str(d["total_errors"]))
            table.add_row("Error Rate", f"{d['overall_error_rate_pct']}%")
            table.add_row("Memories", str(total_memories))
            _root.console.print(table)

            _time.sleep(interval)
    except KeyboardInterrupt:
        _root.console.print("\n[yellow]Stopped.[/yellow]")


@metrics.command(name="prometheus")
@click.option("--token", "-t", envvar="SPACETIMEDB_TOKEN", help="JWT token for auth")
def metrics_prometheus(token: str | None) -> None:
    """Export metrics in Prometheus exposition format."""
    from spacetime_memory.metrics import MetricsCollector

    client = _sdk_client()
    if token:
        client.token = token

    mc = MetricsCollector()
    client.set_metrics_collector(mc)

    # Run probes to populate the collector
    try:
        client.ping()
    except (OSError, json.JSONDecodeError):
        pass
    try:
        rows = client._sql("SELECT COUNT(*) AS c FROM memory")
        mc.record_memory_stats(total=rows[0]["c"] if rows else 0)
    except (OSError, json.JSONDecodeError):
        pass

    _root.console.print(mc.prometheus_text())
