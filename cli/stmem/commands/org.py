"""Org-mode sync"""

from __future__ import annotations

import json
import os
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
# org — Org-mode sync
# ===================================================================


@cli.group()
def org() -> None:
    """Sync .org files to Spacetime Memory."""


@org.command(name="sync")
@click.argument("workspace_id")
@click.option("--dir", "org_dir", default="~/org",
              help="Directory with .org files (default: ~/org)")
@click.option("--dry-run", is_flag=True,
              help="Preview without writing data")
def org_sync(workspace_id: str, org_dir: str, dry_run: bool) -> None:
    """One-shot sync of .org files to Spacetime Memory."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
    try:
        from org_sync_daemon import OrgSyncDaemon
    except ImportError:
        _root.console.print("[red]Error: org_sync_daemon.py not found in scripts/[/red]")
        sys.exit(1)

    client = None if dry_run else _sdk_client()
    daemon = OrgSyncDaemon(
        org_dir=org_dir,
        workspace_id=workspace_id,
        client=client,
        dry_run=dry_run,
    )
    total = daemon.scan()
    _quiet_print(f"[green]Org sync complete — {total} events synced.[/green]")
    if dry_run:
        _quiet_print("[dim](dry-run — no data written)[/dim]")
    else:
        s = daemon.get_status()
        _quiet_print(f"[dim]Tracked {s['files_tracked']} file(s)[/dim]")


@org.command(name="daemon")
@click.argument("workspace_id")
@click.option("--dir", "org_dir", default="~/org",
              help="Directory with .org files (default: ~/org)")
@click.option("--interval", default=30, type=int,
              help="Poll interval in seconds (default: 30)")
@click.option("--dry-run", is_flag=True,
              help="Preview without writing data")
@click.option("--daemonize/--no-daemonize", default=False,
              help="Fork to background (Unix only)")
def org_daemon(workspace_id: str, org_dir: str,
               interval: int, dry_run: bool, daemonize: bool) -> None:
    """Start the org sync daemon (continuous watch)."""
    if daemonize:
        pid = os.fork()
        if pid > 0:
            _quiet_print(f"[green]Org sync daemon started (PID: {pid})[/green]")
            sys.exit(0)
        os.setsid()

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
    try:
        from org_sync_daemon import OrgSyncDaemon, _start_watchdog_observer
    except ImportError:
        _root.console.print("[red]Error: org_sync_daemon.py not found in scripts/[/red]")
        sys.exit(1)

    client = None if dry_run else _sdk_client()
    daemon = OrgSyncDaemon(
        org_dir=org_dir,
        workspace_id=workspace_id,
        client=client,
        interval=interval,
        dry_run=dry_run,
    )

    # Try watchdog first
    observer = _start_watchdog_observer(org_dir, daemon)
    if observer is not None:
        _quiet_print(f"[green]Watchdog observer started on {org_dir}[/green]")
        try:
            while observer.is_alive():
                observer.join(timeout=1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
    else:
        # Polling fallback
        _quiet_print(f"[green]Org sync daemon running (polling every {interval}s)[/green]")
        if dry_run:
            _quiet_print("[dim](dry-run — no data written)[/dim]")
        daemon.run()


@org.command(name="status")
@click.option("--dir", "org_dir", default="~/org",
              help="Directory with .org files (default: ~/org)")
def org_status(org_dir: str) -> None:
    """Show org sync state (tracked files, last sync)."""
    try:
        from org_sync_daemon import OrgSyncDaemon  # noqa: F401  (availability probe)
    except ImportError:
        _root.console.print("[red]Error: org_sync_daemon.py not found in scripts/[/red]")
        sys.exit(1)

    state_path = os.path.expanduser("~/.spacetime-memory/org_sync_state.json")
    if not os.path.exists(state_path):
        _root.console.print("[yellow]No org sync state found. Run `stmem org sync` first.[/yellow]")
        return

    import time as _time

    rows = []
    try:
        with open(state_path) as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        _root.console.print(f"[red]Error reading sync state: {e}[/red]")
        return

    last_mtime = os.path.getmtime(state_path) if os.path.exists(state_path) else 0
    if last_mtime:
        rows.append({
            "key": "last_sync_time",
            "value": _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(last_mtime)),
        })
    rows.append({"key": "files_tracked", "value": str(len(state))})

    for file_path, file_hash in sorted(state.items()):
        short = file_path if len(file_path) < 80 else f"...{file_path[-77:]}"
        rows.append({"key": f"file: {short}", "value": file_hash[:16] + "..."})

    print_table(rows, title="Org Sync Status")
