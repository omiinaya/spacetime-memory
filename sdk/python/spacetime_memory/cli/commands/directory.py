"""CLI commands — directory module."""

from __future__ import annotations

import time
from typing import Any

import click

from ..root import (
    _quiet_print,
    _sdk_client,
    cli,
    console,
    print_json,
    print_table,
)


@cli.group()
def directory() -> None:
    """Manage context directory trees."""


@directory.command(name="list")
@click.argument("directory_id")
@click.option("--watch", "-w", is_flag=True, help="Watch for changes (poll every 5s)")
@click.pass_context
def directory_list(ctx: click.Context, directory_id: str, watch: bool) -> None:
    """List children of a directory."""
    def _run() -> list[dict[str, Any]]:
        with console.status(f"Listing directory '{directory_id[:16]}...'..."):
            return _sdk_client().list_directory(directory_id)

    def _display(rows: list[dict[str, Any]]) -> None:
        print_table(rows, title=f"Directory: {directory_id[:16]}...",
                    output=ctx.obj.get("output", "table"))

    if watch:
        try:
            while True:
                console.clear()
                rows = _run()
                _display(rows)
                time.sleep(5)
        except KeyboardInterrupt:
            pass
    else:
        rows = _run()
        _display(rows)


@directory.command(name="tree")
@click.argument("workspace_id")
@click.argument("root_directory_id")
def directory_tree(workspace_id: str, root_directory_id: str) -> None:
    """Recursively traverse directory tree."""
    with console.status(f"Traversing tree from '{root_directory_id[:16]}...'..."):
        rows = _sdk_client().traverse_directory(workspace_id, root_directory_id)
    print_table(rows, title=f"Directory tree (root: {root_directory_id[:16]}...)")


@directory.command(name="create")
@click.argument("workspace_id")
@click.argument("name")
@click.argument("path")
@click.option("--parent-id", default="", help="Parent directory ID")
@click.option("--description", default="", help="Directory description")
def directory_create(workspace_id: str, name: str, path: str,
                     parent_id: str, description: str) -> None:
    """Create a directory in the context directory tree."""
    with console.status(f"Creating directory '{name}'..."):
        result = _sdk_client().create_directory(workspace_id, name, path, parent_id, description)
    _quiet_print(f"[green]Directory '{name}' created.[/green]")
    if result:
        print_json(result)


@directory.command(name="link")
@click.argument("directory_id")
@click.argument("memory_id")
@click.argument("workspace_id")
def directory_link(directory_id: str, memory_id: str, workspace_id: str) -> None:
    """Link a memory to a directory."""
    with console.status(f"Linking memory '{memory_id[:16]}...' to directory..."):
        result = _sdk_client().link_memory_to_directory(directory_id, memory_id, workspace_id)
    _quiet_print("[green]Memory linked to directory.[/green]")
    if result:
        print_json(result)


@directory.command(name="unlink")
@click.argument("directory_id")
@click.argument("memory_id")
def directory_unlink(directory_id: str, memory_id: str) -> None:
    """Unlink a memory from a directory."""
    with console.status(f"Unlinking memory '{memory_id[:16]}...' from directory..."):
        result = _sdk_client().unlink_memory_from_directory(directory_id, memory_id)
    _quiet_print("[green]Memory unlinked from directory.[/green]")
    if result:
        print_json(result)

