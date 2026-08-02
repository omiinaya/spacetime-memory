"""External data connectors"""

from __future__ import annotations

import sys

import click


from .. import root as _root
from ..root import (
    _quiet_print,
    _sdk_client,
    cli,
    print_table,
)

# ===================================================================
# connector — external data sources
# ===================================================================


@cli.group()
def connector() -> None:
    """Manage external data connectors."""


@connector.command(name="run")
@click.option("--rss", help="RSS/Atom feed URL")
@click.option("--workspace-id", required=True, help="Target workspace")
@click.option("--interval", default=300, type=int, help="Poll interval (seconds)")
@click.option("--ticks", default=1, type=int, help="Number of poll cycles (0 = forever)")
def connector_run(rss: str | None, workspace_id: str,
                  interval: int, ticks: int) -> None:
    """Run a connector. Currently supports --rss feeds."""
    client = _sdk_client()

    if rss:
        try:
            from spacetime_memory.connectors import RssFeedConnector
        except ImportError:
            _root.console.print("[red]Error:[/red] Missing dep. Run: pip install feedparser")
            sys.exit(1)
        conn = RssFeedConnector(rss, workspace_id)
        stop = None if ticks == 0 else ticks
        conn.run(client, interval_secs=interval, stop_after=stop)
        _quiet_print("[green]Connector finished.[/green]")
    else:
        _root.console.print("[yellow]No connector specified. Use --rss <url>[/yellow]")

@connector.command(name="register")
@click.option("--name", required=True, help="Connector name")
@click.option("--type", "conn_type", required=True, help="Connector type: rss, github, twitter, slack, discord, telegram, notion, webhook, orgmode")
@click.option("--config", default="{}", help="JSON config blob for the connector")
@click.option("--workspace-id", required=True, help="Target workspace ID")
@click.option("--interval", default=300, type=int, help="Poll interval (seconds)")
def connector_register(name: str, conn_type: str, config: str, workspace_id: str, interval: int) -> None:
    """Register a connector config in the database."""
    client = _sdk_client()
    # Validate JSON
    try:
        import json
        json.loads(config)
    except json.JSONDecodeError as e:
        _root.console.print(f"[red]Invalid config JSON: {e}[/red]")
        sys.exit(1)
    result = client.register_connector(name, conn_type, config, workspace_id, interval)
    _root.console.print(f"[green]Connector '{name}' registered.[/green]")
    if result and result.get("id"):
        _root.console.print(f"  ID: {result['id']}")


@connector.command(name="update")
@click.option("--id", "conn_id", required=True, help="Connector ID")
@click.option("--name", required=True, help="Connector name")
@click.option("--type", "conn_type", required=True, help="Connector type: rss, github, twitter, slack, discord, telegram, notion, webhook, orgmode")
@click.option("--config", default="{}", help="JSON config blob for the connector")
@click.option("--workspace-id", required=True, help="Target workspace ID")
@click.option("--interval", default=300, type=int, help="Poll interval (seconds)")
@click.option("--active/--inactive", default=True, help="Whether the connector is active")
def connector_update(conn_id: str, name: str, conn_type: str, config: str,
                     workspace_id: str, interval: int, active: bool) -> None:
    """Update an existing connector configuration."""
    client = _sdk_client()
    try:
        import json
        json.loads(config)
    except json.JSONDecodeError as e:
        _root.console.print(f"[red]Invalid config JSON: {e}[/red]")
        sys.exit(1)
    client.update_connector(conn_id, name, conn_type, config, workspace_id, interval, active)
    _root.console.print(f"[green]Connector '{name}' updated.[/green]")


@connector.command(name="delete")
@click.argument("conn_id")
def connector_delete(conn_id: str) -> None:
    """Delete a connector configuration by ID."""
    client = _sdk_client()
    client.delete_connector(conn_id)
    _root.console.print(f"[green]Connector '{conn_id}' deleted.[/green]")


@connector.command(name="list")
def connector_list() -> None:
    """List registered connectors."""
    client = _sdk_client()
    rows = client._sql(
        "SELECT id, name, connector_type, workspace_id, "
        "schedule_secs, is_active, created_at "
        "FROM connector_config"
    )
    if not rows:
        _root.console.print("[yellow]No connectors registered.[/yellow]")
        return
    table_data = [
        dict(
            name=r["name"],
            type=r["connector_type"],
            workspace=r["workspace_id"][:12] + "...",
            interval=f"{r['schedule_secs']}s",
            active="Y" if r["is_active"] else "N",
            id=r["id"][:16],
        )
        for r in rows
    ]
    print_table(table_data, title="Connectors")


@connector.command(name="start")
@click.option("--db-poll", default=60, type=int, help="DB poll interval (seconds)")
def connector_start(db_poll: int) -> None:
    """Start the connector daemon. Polls DB for configs and runs all active connectors."""
    from spacetime_memory.connectors import ConnectorDaemon
    client = _sdk_client()
    daemon = ConnectorDaemon(client, db_poll_secs=db_poll)
    try:
        daemon.start()
    except KeyboardInterrupt:
        daemon.stop()
        _root.console.print("\n[yellow]Connector daemon stopped.[/yellow]")


        sys.exit(1)
