"""Backup / restore"""

from __future__ import annotations

import json

import click


from .. import root as _root
from ..root import (
    _sdk_client,
    cli,
)

# ===================================================================
# backup / restore
# ===================================================================


@cli.command(name="backup")
@click.argument("workspace_id")
@click.option("--output", "-o", default=None, help="Output file (default: ~/.hermes/backups/<ws>.jsonl)")
@click.option("--tables", default="memory,session,message,profile,insight,note,kg_node,kg_edge",
              help="Comma-separated tables to backup")
def backup_cmd(workspace_id: str, output: str | None, tables: str) -> None:
    """Backup all data for a workspace to a JSONL file."""
    from pathlib import Path

    table_list = [t.strip() for t in tables.split(",")]

    if not output:
        backup_dir = Path.home() / ".hermes" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        output = str(backup_dir / f"{workspace_id[:16]}.jsonl")

    client = _sdk_client()
    total = 0

    with open(output, "w") as f:
        for table in table_list:
            try:
                rows = client._query(table, workspace_id=workspace_id)
            except RuntimeError:
                _root.console.print(f"  [yellow]Skipping {table}[/yellow] (not accessible)")
                continue
            for row in rows:
                f.write(json.dumps({"table": table, **row}) + "\n")
                total += 1
        _root.console.print(f"  {total} rows from {len(table_list)} tables")

    _root.console.print(f"\n[green]Backup complete:[/green] {output}")
    _root.console.print(f"  {total} rows written")


@cli.command(name="restore")
@click.argument("workspace_id")
@click.argument("backup_file", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Print what would be restored without making changes")
def restore_cmd(workspace_id: str, backup_file: str, dry_run: bool) -> None:
    """Restore workspace data from a JSONL backup file."""
    client = _sdk_client()
    total = 0
    errors = 0

    with open(backup_file) as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                _root.console.print(f"  [red]Line {line_no}: invalid JSON[/red]")
                errors += 1
                continue

            table = row.pop("table", "")
            if not table:
                _root.console.print(f"  [red]Line {line_no}: missing table field[/red]")
                errors += 1
                continue

            if dry_run:
                _root.console.print(f"  [DRY] {table}: {json.dumps(row)[:80]}...")
                total += 1
                continue

            try:
                # Use store_memory for memory rows, generic _call for others
                if table == "memory":
                    client.store(
                        workspace_id=workspace_id,
                        content=row.get("content", ""),
                        summary=row.get("summary", ""),
                        memory_type=row.get("memory_type", "world_fact"),
                        peer_id=row.get("peer_id", ""),
                    )
                elif table == "session":
                    client._call("create_session", [
                        workspace_id, row.get("id", ""), row.get("name", ""),
                        row.get("summary", ""), row.get("participants_json", "[]"),
                    ])
                elif table == "kg_node":
                    client._call("create_node", [
                        workspace_id, row.get("label", ""), row.get("node_type", ""),
                        row.get("summary", ""), row.get("metadata_json", "{}"),
                    ])
                elif table == "kg_edge":
                    client._call("create_edge", [
                        workspace_id, row.get("source_node_id", ""),
                        row.get("target_node_id", ""), row.get("relation", ""),
                        row.get("weight", 1.0), row.get("confidence", "EXTRACTED"),
                        row.get("metadata_json", "{}"),
                    ])
                elif table == "profile":
                    client._call("upsert_profile", [
                        workspace_id, row.get("peer_id", ""),
                        row.get("static_facts_json", "{}"),
                        row.get("dynamic_context_json", "{}"),
                    ])
                elif table == "insight":
                    client._call("create_insight", [
                        workspace_id, row.get("source", "restore"),
                        row.get("content", ""), row.get("insight_type", "observation"),
                        row.get("entities_json", "[]"), row.get("confidence", 0.7),
                    ])
                elif table == "note":
                    client._call("create_note", [
                        workspace_id, row.get("title", ""), row.get("content", ""),
                        row.get("tags_json", "[]"),
                    ])
                else:
                    _root.console.print(f"  [yellow]Skipping {table} (no restore handler)[/yellow]")
                    continue

                total += 1
            except RuntimeError as e:
                _root.console.print(f"  [red]Line {line_no} ({table}): {e}[/red]")
                errors += 1

    mode = " [DRY-RUN]" if dry_run else ""
    _root.console.print(f"\n[green]Restore complete{mode}:[/green] {total} rows restored, {errors} errors")
