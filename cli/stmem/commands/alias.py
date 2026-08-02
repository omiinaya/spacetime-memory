"""CLI aliases"""

from __future__ import annotations


import click
from rich import box
from rich.table import Table


from .. import root as _root
from ..root import (
    _load_aliases,
    _quiet_print,
    _save_aliases,
    cli,
)

# ===================================================================
# alias — CLI aliases
# ===================================================================


@cli.group()
def alias() -> None:
    """Manage CLI aliases."""


@alias.command(name="set")
@click.argument("name")
@click.argument("command")
def alias_set(name: str, command: str) -> None:
    """Set an alias.

    Example: stmem alias set ll 'memory list --tier L0'
    """
    aliases = _load_aliases()
    aliases[name] = command
    _save_aliases(aliases)
    _quiet_print(f"[green]Alias '{name}' set to:[/green] {command}")


@alias.command(name="list")
def alias_list() -> None:
    """List all aliases."""
    aliases = _load_aliases()
    if not aliases:
        _root.console.print("[yellow]No aliases defined.[/yellow]")
        return
    table = Table(title="Aliases", box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Name")
    table.add_column("Command")
    for name, cmd in sorted(aliases.items()):
        table.add_row(name, cmd)
    _root.console.print(table)


@alias.command(name="remove")
@click.argument("name")
def alias_remove(name: str) -> None:
    """Remove an alias."""
    aliases = _load_aliases()
    if name not in aliases:
        _root.console.print(f"[yellow]Alias '{name}' not found.[/yellow]")
        return
    del aliases[name]
    _save_aliases(aliases)
    _quiet_print(f"[green]Alias '{name}' removed.[/green]")
