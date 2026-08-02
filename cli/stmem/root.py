#!/usr/bin/env python3
"""stmem — Spacetime-Memory CLI.

A command-line interface for managing memory from the terminal,
using the spacetime-memory Python SDK.

Configuration via environment variables:
    STMEM_HOST / SPACETIMEDB_HOST (default: localhost)
    STMEM_PORT / SPACETIMEDB_PORT (default: 3001)
    STMEM_DB / SPACETIMEDB_DB (default: spacetime-memory)
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
from typing import Any

import click
import httpx
from rich.console import Console
from rich.table import Table
from rich import box

from spacetime_memory import Client

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HOST = os.environ.get("STMEM_HOST", os.environ.get("SPACETIMEDB_HOST", "localhost"))
PORT = os.environ.get("STMEM_PORT", os.environ.get("SPACETIMEDB_PORT", "3001"))
DB = os.environ.get("STMEM_DB", os.environ.get("SPACETIMEDB_DB", "spacetime-memory"))
EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://localhost:4000")

console = Console()

# Global output format; set by root CLI group --output flag
_current_output_format: str = "table"
_quiet_mode: bool = False
_no_header_mode: bool = False
_compact_json_mode: bool = False
_no_color_mode: bool = False
_verbose_mode: bool = False

# Aliases file path
ALIASES_FILE = os.path.join(os.path.expanduser("~"), ".stmem_aliases.json")


def _load_aliases() -> dict[str, str]:
    """Load aliases from ~/.stmem_aliases.json."""
    if os.path.exists(ALIASES_FILE):
        try:
            with open(ALIASES_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_aliases(aliases: dict[str, str]) -> None:
    """Save aliases to ~/.stmem_aliases.json."""
    with open(ALIASES_FILE, "w") as f:
        json.dump(aliases, f, indent=2)


def _sdk_client() -> Client:
    """Build an SDK Client from the CLI's env-var config, auto-registering for auth."""
    c = Client(
        host=HOST, port=PORT, database=DB,
        embedder_url=EMBEDDER_URL,
        verbose=_verbose_mode,
    )
    # Auto-register to satisfy auth requirements (first call = admin)
    import os
    suffix = os.urandom(4).hex()
    try:
        c._call("register", [f"cli_{suffix}", "CLI User", "clipass"])
    except RuntimeError:
        pass  # already registered
    return c


def _quiet_print(msg: str) -> None:
    """Print a message unless quiet mode is on."""
    if not _quiet_mode:
        console.print(msg)


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def print_table(rows: list[dict[str, Any]], title: str = "",
                output: str | None = None) -> None:
    """Print query results as table, json, or csv.

    Args:
        rows: List of dicts to display.
        title: Optional table title (only used in table mode).
        output: One of "table", "json", "csv".  Defaults to the
                module-global ``_current_output_format``.
    """
    if output is None:
        output = _current_output_format

    if not rows:
        if not _quiet_mode:
            console.print("[yellow]No results found.[/yellow]")
        return

    if _quiet_mode:
        return

    if output == "json":
        if _compact_json_mode:
            console.print(json.dumps(rows, default=str))
        else:
            console.print_json(json.dumps(rows, default=str))
        return

    if output == "csv":
        cols = list(rows[0].keys())
        buf = io.StringIO()
        writer = csv.writer(buf)
        if not _no_header_mode:
            writer.writerow(cols)
        for row in rows:
            writer.writerow([str(row.get(c, "")) for c in cols])
        console.print(buf.getvalue().strip())
        return

    # Default: Rich table
    table = Table(title=title, box=box.ROUNDED, header_style="bold cyan")
    cols = list(rows[0].keys())
    for c in cols:
        table.add_column(c, overflow="fold")
    for row in rows:
        vals = [str(row.get(c, "")) for c in cols]
        table.add_row(*vals)
    console.print(table)


def print_json(data: Any) -> None:
    """Print data as formatted JSON."""
    console.print_json(json.dumps(data, default=str) if not isinstance(data, str) else data)


def parse_json_flag(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    """Click callback that validates JSON is parseable."""
    if value is None:
        return value
    try:
        json.loads(value)
    except json.JSONDecodeError as e:
        raise click.BadParameter(f"Invalid JSON: {e}")
    return value


def _esc(val: str) -> str:
    """Basic SQL string escaping for single-quoted string literals."""
    return val.replace("'", "''")


# ---------------------------------------------------------------------------
# stmem CLI group
# ---------------------------------------------------------------------------


@click.group(invoke_without_command=True, no_args_is_help=True)
@click.version_option(version="0.1.0", prog_name="stmem")
@click.option("--output", "-o", type=click.Choice(["table", "json", "csv"]),
              default="table", help="Output format: table, json, or csv")
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-error output")
@click.option("--no-header", is_flag=True, help="Skip header row in CSV output")
@click.option("--compact-json", is_flag=True, help="Compact JSON output (no indentation)")
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.option("--verbose", "-v", is_flag=True, help="Show raw error messages instead of friendly ones")
@click.pass_context
def cli(ctx: click.Context, output: str, quiet: bool, no_header: bool,
        compact_json: bool, no_color: bool, verbose: bool) -> None:
    """stmem — Spacetime-Memory CLI.

    Manage workspaces, peers, memories, profiles, knowledge graphs, and sessions
    on a SpacetimeDB instance.
    """
    global console, _current_output_format, _quiet_mode, _no_header_mode, _compact_json_mode, _no_color_mode, _verbose_mode
    _current_output_format = output
    _quiet_mode = quiet
    _no_header_mode = no_header
    _compact_json_mode = compact_json
    _no_color_mode = no_color
    _verbose_mode = verbose
    ctx.ensure_object(dict)
    ctx.obj["output"] = output
    ctx.obj["quiet"] = quiet
    ctx.obj["no_header"] = no_header
    ctx.obj["compact_json"] = compact_json
    ctx.obj["no_color"] = no_color
    ctx.obj["verbose"] = verbose
    if no_color:
        os.environ["NO_COLOR"] = "1"
        console = Console(no_color=True)


# ===================================================================
# Entry point
# ===================================================================

def main() -> None:
    # Check for alias substitution before Click parses arguments
    args = sys.argv[1:]
    if args and args[0] not in ("alias", "completion", "--help", "--version"):
        aliases = _load_aliases()
        # Match the first non-flag argument against alias names
        for i, arg in enumerate(args):
            if not arg.startswith("-") and arg in aliases:
                # Replace the matched argument with the alias value
                alias_cmd = aliases[arg]
                rest = args[i + 1:]
                # Reconstruct sys.argv with the alias expansion
                sys.argv = [sys.argv[0]] + alias_cmd.split() + rest
                break

    try:
        cli()
    except click.ClickException as e:
        console.print(f"[red]Error:[/red] {e.format_message()}")
        sys.exit(1)
    except httpx.ConnectError as e:
        console.print(
            f"[red]Connection error:[/red] Could not connect to SpacetimeDB at "
            f"http://{HOST}:{PORT}. Is it running?\n  {e}"
        )
        sys.exit(1)
    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
