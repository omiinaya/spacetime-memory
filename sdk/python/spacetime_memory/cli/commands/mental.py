"""CLI commands — mental module."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import click

from ..root import (
    _esc,
    _quiet_print,
    _sdk_client,
    cli,
    console,
    print_json,
    print_table,
)


@cli.group()
def mental() -> None:
    """Manage mental models (LLM-synthesized abstractions from memories)."""


@mental.command(name="list")
@click.option("--status", default="",
              type=click.Choice(["", "pending", "completed", "failed"]),
              help="Filter by status")
def mental_list(status: str) -> None:
    """List mental models, optionally filtered by status."""
    client = _sdk_client()
    if status:
        with console.status("Fetching mental models..."):
            rows = client._sql_param(
                "SELECT * FROM mental_model WHERE status = ?",
                status,
            )
    else:
        with console.status("Fetching mental models..."):
            rows = client._sql("SELECT * FROM mental_model")
    if rows:
        rows.sort(key=lambda r: r.get("created_at", 0) or 0, reverse=True)
    print_table(rows, title="Mental Models")


@mental.command(name="create")
@click.argument("workspace_id")
@click.option("--memory-ids", required=True,
              help="Comma-separated list of source memory IDs")
def mental_create(workspace_id: str, memory_ids: str) -> None:
    """Create a new mental model synthesis request from source memories."""
    client = _sdk_client()
    ids_list = [mid.strip() for mid in memory_ids.split(",") if mid.strip()]
    ids_json = json.dumps(ids_list)
    with console.status("Creating mental model..."):
        result = client._call("synthesize_mental_models", [workspace_id, ids_json])
    _quiet_print("[green]Mental model created (status=pending). Run `stmem mental synthesize` to generate content.[/green]")
    if result:
        print_json(result)


@mental.command(name="synthesize")
@click.option("--all", "all_flag", is_flag=True,
              help="Process ALL pending models (default: only last 24h)")
@click.option("--dry-run", is_flag=True,
              help="Print what would be synthesized without calling LLM")
def mental_synthesize(all_flag: bool, dry_run: bool) -> None:
    """Run the mental model synthesis script for pending models."""
    script_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts", "mental_model_synthesis.py",
    )
    if not os.path.exists(script_path):
        console.print(f"[red]Error: {script_path} not found.[/red]")
        sys.exit(1)

    cmd = [sys.executable, script_path]
    if all_flag:
        cmd.append("--all")
    if dry_run:
        cmd.append("--dry-run")

    console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        console.print(f"[red]Synthesis script exited with code {result.returncode}[/red]")
        sys.exit(result.returncode)


@mental.command(name="get")
@click.argument("id")
def mental_get(id: str) -> None:
    """Get a single mental model by ID."""
    client = _sdk_client()
    with console.status(f"Fetching mental model '{id[:16]}...'..."):
        rows = client._sql(
            f"SELECT * FROM mental_model WHERE id = '{_esc(id)}'"
        )
    if not rows:
        console.print(f"[yellow]Mental model '{id[:16]}...' not found.[/yellow]")
        return
    print_json(rows[0])

