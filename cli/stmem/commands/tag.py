"""Tag management"""

from __future__ import annotations

import json

import click
from rich import box
from rich.table import Table


from .. import root as _root
from ..root import (
    _quiet_print,
    _sdk_client,
    cli,
    print_json,
    print_table,
)

# ===================================================================
# tag — tag management
# ===================================================================


@cli.group()
def tag() -> None:
    """Manage tags for organizing memories."""


@tag.command(name="list")
@click.argument("workspace_id", required=False, default="default")
@click.option("--json", "_json", is_flag=True, help="Output raw JSON")
def tag_list_cmd(workspace_id: str, _json: bool) -> None:
    """List all tags in a workspace."""
    with _root.console.status(f"Listing tags in workspace '{workspace_id}'..."):
        tags = _sdk_client().list_tags(workspace_id)

    if not tags:
        _quiet_print("[yellow]No tags found in this workspace.[/yellow]")
        return

    if _json or _root._current_output_format == "json":
        print_json(json.dumps(tags))
    elif _root._current_output_format == "csv":
        print_table(tags, title=f"Tags in '{workspace_id}'", output="csv")
    else:
        table = Table(title=f"Tags in '{workspace_id}'", box=box.ROUNDED)
        table.add_column("ID", style="dim")
        table.add_column("Name", style="cyan")
        table.add_column("Color")
        table.add_column("Created", style="dim")
        for t in tags:
            table.add_row(
                t.get("id", ""),
                t.get("name", ""),
                t.get("color", "#808080"),
                str(t.get("created_at", "")),
            )
        _root.console.print(table)


@tag.command(name="delete")
@click.argument("tag_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def tag_delete_cmd(tag_id: str, yes: bool) -> None:
    """Delete a tag and all its memory associations."""
    if not yes:
        confirmed = click.confirm(
            f"Delete tag '{tag_id}'? This will remove all memory associations.",
            default=False,
        )
        if not confirmed:
            _quiet_print("[yellow]Cancelled.[/yellow]")
            return

    with _root.console.status(f"Deleting tag '{tag_id}'..."):
        _sdk_client().delete_tag(tag_id)

    _quiet_print(f"[green]Tag '{tag_id}' deleted.[/green]")


@tag.command(name="batch-tag")
@click.argument("tag_id")
@click.argument("memory_ids")
def tag_batch_tag_cmd(tag_id: str, memory_ids: str) -> None:
    """Batch-attach a tag to multiple memories. MEMORY_IDS is comma-separated."""
    client = _sdk_client()
    ids = [m.strip() for m in memory_ids.split(",") if m.strip()]
    if not ids:
        _root.console.print("[yellow]No memory IDs provided.[/yellow]")
        return
    with _root.console.status(f"Tagging {len(ids)} memories with '{tag_id}'..."):
        client.batch_tag_memories(tag_id, ids)
    _quiet_print(f"[green]Tagged {len(ids)} memories with '{tag_id}'.[/green]")


@tag.command(name="batch-untag")
@click.argument("tag_id")
@click.argument("memory_ids")
def tag_batch_untag_cmd(tag_id: str, memory_ids: str) -> None:
    """Batch-remove a tag from multiple memories. MEMORY_IDS is comma-separated."""
    client = _sdk_client()
    ids = [m.strip() for m in memory_ids.split(",") if m.strip()]
    if not ids:
        _root.console.print("[yellow]No memory IDs provided.[/yellow]")
        return
    with _root.console.status(f"Untagging {len(ids)} memories from '{tag_id}'..."):
        client.batch_untag_memories(tag_id, ids)
    _quiet_print(f"[green]Untagged {len(ids)} memories from '{tag_id}'.[/green]")
