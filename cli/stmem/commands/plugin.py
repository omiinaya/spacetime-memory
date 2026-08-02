"""Plugin management"""

from __future__ import annotations

import os
import sys
from typing import Any

import click
from rich import box
from rich.table import Table


from .. import root as _root
from ..root import (
    _quiet_print,
    _sdk_client,
    cli,
)

# ===================================================================
# plugin commands
# ===================================================================


@cli.group()
def plugin() -> None:
    """Manage plugins (discover, load, unload, list)."""


def _plugin_manager() -> Any:
    """Build a PluginManager from the CLI's env-var config."""
    from spacetime_memory.plugin_manager import PluginManager

    client = _sdk_client()
    # Default plugin dir: <project>/plugins/
    default_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "plugins",
    )
    plugin_dir = os.environ.get("STMEM_PLUGIN_DIR", default_dir)
    return PluginManager(client, plugin_dir=plugin_dir)


@plugin.command(name="list")
def plugin_list() -> None:
    """List all discovered and loaded plugins."""
    mgr = _plugin_manager()
    with _root.console.status("Discovering plugins..."):
        plugins = mgr.list()
    if not plugins:
        _root.console.print("[yellow]No plugins discovered.[/yellow]")
        _root.console.print(
            f"  Plugin directory: [cyan]{mgr.plugin_dir}[/cyan]"
        )
        return

    table = Table(
        title=f"Plugins (dir: {mgr.plugin_dir})",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Description")
    table.add_column("Loaded")
    table.add_column("Type")
    for p in plugins:
        loaded = "[green]✔[/green]" if p["loaded"] else "[dim]—[/dim]"
        table.add_row(
            p["name"],
            p["version"],
            p["description"][:80] if p["description"] else "",
            loaded,
            p["type"],
        )
    _root.console.print(table)


@plugin.command(name="load")
@click.argument("name")
def plugin_load(name: str) -> None:
    """Load a plugin by name."""
    mgr = _plugin_manager()
    with _root.console.status(f"Loading plugin '{name}'..."):
        mgr.discover()
        ok = mgr.load(name)
    if ok:
        _quiet_print(f"[green]Plugin '{name}' loaded successfully.[/green]")
    else:
        _root.console.print(f"[red]Failed to load plugin '{name}'. Is it installed?[/red]")
        _root.console.print("  [dim]→ Check: pip list | grep spacetime-memory-plugin[/dim]")
        sys.exit(1)


@plugin.command(name="unload")
@click.argument("name")
def plugin_unload(name: str) -> None:
    """Unload a plugin by name."""
    mgr = _plugin_manager()
    with _root.console.status(f"Unloading plugin '{name}'..."):
        ok = mgr.unload(name)
    if ok:
        _quiet_print(f"[green]Plugin '{name}' unloaded.[/green]")
    else:
        _root.console.print(f"[yellow]Plugin '{name}' was not loaded.[/yellow]")
        sys.exit(1)


@plugin.command(name="reload")
def plugin_reload() -> None:
    """Discover and reload all plugins."""
    mgr = _plugin_manager()
    with _root.console.status("Reloading all plugins..."):
        mgr.unload_all()
        loaded = mgr.load_all()
    _quiet_print(
        f"[green]Reloaded {len(loaded)} plugin(s): {', '.join(loaded)}[/green]"
    )
