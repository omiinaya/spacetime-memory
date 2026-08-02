#!/usr/bin/env python3
"""Org-mode live sync daemon.

Monitors a directory for .org file changes and syncs headings, TODOs,
and metadata to Spacetime Memory as notes and KG nodes.

Usage:
    python scripts/org_sync_daemon.py --dir ~/org --workspace ws_id [--interval 30]
    python scripts/org_sync_daemon.py --dir ~/org --workspace ws_id --once
    python scripts/org_sync_daemon.py --dir ~/org --workspace ws_id --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from typing import Any

# ── State persistence ───────────────────────────────────────────────

STATE_DIR = os.path.expanduser("~/.spacetime-memory")
STATE_FILE = os.path.join(STATE_DIR, "org_sync_state.json")


def load_state() -> dict[str, Any]:
    """Load sync state from disk."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_state(state: dict[str, Any]) -> None:
    """Persist sync state to disk."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── File hashing ────────────────────────────────────────────────────


def hash_file(path: str) -> str:
    """Return SHA-256 hex digest of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Org Sync Daemon ─────────────────────────────────────────────────


class OrgSyncDaemon:
    """Monitor a directory of .org files and sync changes to Spacetime Memory.

    Attributes:
        org_dir: Path to the directory containing .org files.
        workspace_id: Spacetime Memory workspace to sync into.
        client: A spacetime_memory.Client instance (or None for dry-run).
        interval: Polling interval in seconds.
        dry_run: If True, print events without persisting.
        state: Dict mapping file path → last content hash.
    """

    def __init__(
        self,
        org_dir: str,
        workspace_id: str,
        client: Any = None,
        interval: int = 30,
        dry_run: bool = False,
    ):
        self.org_dir = os.path.expanduser(org_dir)
        self.workspace_id = workspace_id
        self.client = client
        self.interval = interval
        self.dry_run = dry_run
        self.state = load_state()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync_file(self, path: str) -> int:
        """Sync a single .org file to Spacetime Memory.

        Returns the number of events (headings) synced.
        Returns -1 if the file is unchanged.
        """
        path = os.path.abspath(path)

        # Check content hash first
        try:
            file_hash = hash_file(path)
        except (OSError, FileNotFoundError) as e:
            print(f"  [org-sync] Error reading {path}: {e}")
            return 0

        prev_hash = self.state.get(path)
        if file_hash == prev_hash:
            return -1  # unchanged

        # Parse the .org file
        try:
            from spacetime_memory.connectors import OrgModeParser

            parser = OrgModeParser(
                file_path=path,
                workspace_id=self.workspace_id,
                peer_id="org-sync",
            )
            events = parser.parse()
        except Exception as e:
            print(f"  [org-sync] Parse error {path}: {e}")
            return 0

        if not events:
            # File may be empty or have no headings — still mark as synced
            self.state[path] = file_hash
            save_state(self.state)
            return 0

        # Persist each heading as a memory
        count = 0
        for event in events:
            heading = event.summary or event.content[:80]
            note_title = f"{os.path.basename(path)}: {heading}"

            if self.dry_run:
                print(f"  [dry-run] Would store memory from '{note_title}'")
                print(f"            content preview: {event.content[:100]}...")
                print(f"            tags: {event.metadata.get('tags', [])}")
                print(f"            todo: {event.metadata.get('todo_state', '')}")
            elif self.client is not None:
                try:
                    self.client.store(
                        workspace_id=self.workspace_id,
                        content=event.content,
                        summary=event.summary or heading,
                        memory_type="experience",
                        peer_id="org-sync",
                        source_session_id="",
                    )

                    # Create KG node for TODO items
                    todo_state = event.metadata.get("todo_state", "")
                    if todo_state and todo_state in ("TODO", "IN-PROGRESS", "BLOCKED"):
                        try:
                            self.client.create_node(
                                workspace_id=self.workspace_id,
                                label=heading[:200],
                                node_type="task",
                                summary=event.content[:500],
                                metadata_json=json.dumps({
                                    "source": "org-mode",
                                    "file": path,
                                    "todo_state": todo_state,
                                    "tags": event.metadata.get("tags", []),
                                }),
                            )
                        except Exception as e:
                            print(f"  [org-sync] KG node creation skipped: {e}")
                except Exception as e:
                    print(f"  [org-sync] Store error: {e}")
                    continue
            else:
                print(f"  [org-sync] No client — skipping store for '{note_title}'")
            count += 1

        # Update sync state
        self.state[path] = file_hash
        save_state(self.state)
        return count

    def scan(self) -> int:
        """Walk ``self.org_dir`` and sync any changed .org files.

        Returns total number of events synced across all files.
        """
        if not os.path.isdir(self.org_dir):
            print(f"  [org-sync] Directory not found: {self.org_dir}")
            return 0

        total = 0
        changed_files = 0
        for root, _dirs, files in os.walk(self.org_dir):
            for fname in sorted(files):
                if not fname.endswith(".org"):
                    continue
                path = os.path.join(root, fname)
                count = self.sync_file(path)
                if count > 0:
                    total += count
                    changed_files += 1
                elif count == -1:
                    pass  # unchanged, skip
        if changed_files:
            print(f"  [org-sync] Synced {total} events from {changed_files} files")
        return total

    def run(self) -> None:
        """Continuous polling loop.

        Scans the directory every ``self.interval`` seconds.
        Runs until interrupted (Ctrl+C).
        """
        print(
            f"  [org-sync] Daemon started — watching {self.org_dir} "
            f"(interval={self.interval}s, workspace={self.workspace_id})"
        )
        if self.dry_run:
            print("  [org-sync] DRY RUN — no data will be written")
        try:
            while True:
                self.scan()
                time.sleep(self.interval)
        except KeyboardInterrupt:
            print("\n  [org-sync] Daemon stopped")
            save_state(self.state)

    def get_status(self) -> dict[str, Any]:
        """Return a status dict for the CLI status command."""
        total_files = len(self.state)
        tracked = list(self.state.keys())
        return {
            "org_dir": self.org_dir,
            "workspace_id": self.workspace_id,
            "files_tracked": total_files,
            "last_sync_time": os.path.getmtime(STATE_FILE) if os.path.exists(STATE_FILE) else 0,
            "files": tracked,
        }


# ── Watchdog helper (optional) ──────────────────────────────────────


def _start_watchdog_observer(org_dir: str, daemon: OrgSyncDaemon) -> Any:
    """Start a watchdog observer for filesystem events.

    Falls back to polling if watchdog is not installed.
    Returns the observer (call ``.stop()`` to shut down).
    """
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class OrgFileHandler(FileSystemEventHandler):
            def on_modified(self, event):
                if event.is_directory:
                    return
                if event.src_path.endswith(".org"):
                    daemon.sync_file(event.src_path)

            def on_created(self, event):
                if event.is_directory:
                    return
                if event.src_path.endswith(".org"):
                    daemon.sync_file(event.src_path)

        event_handler = OrgFileHandler()
        observer = Observer()
        observer.schedule(event_handler, org_dir, recursive=True)
        observer.start()
        return observer
    except ImportError:
        print("  [org-sync] watchdog not installed; falling back to polling")
        return None


# ── CLI entry point ─────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Org-mode live sync daemon for Spacetime Memory",
    )
    parser.add_argument(
        "--dir",
        default="~/org",
        help="Directory to monitor for .org files (default: ~/org)",
    )
    parser.add_argument(
        "--workspace",
        "-w",
        required=True,
        help="Spacetime Memory workspace ID",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Polling interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="One-shot sync (for cron) instead of continuous daemon",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing data",
    )
    parser.add_argument(
        "--watchdog/--no-watchdog",
        default=True,
        help="Use watchdog for filesystem events (default: True, falls back to polling)",
    )
    return parser.parse_args(argv)


def main() -> None:
    """Script entry point."""
    args = parse_args()

    # Build a Client unless dry-run
    client: Any = None
    if not args.dry_run:
        try:
            from spacetime_memory import Client

            host = os.environ.get("STMEM_HOST", os.environ.get("SPACETIMEDB_HOST", "localhost"))
            port = os.environ.get("STMEM_PORT", os.environ.get("SPACETIMEDB_PORT", "3001"))
            db = os.environ.get("STMEM_DB", os.environ.get("SPACETIMEDB_DB", "spacetime-memory"))
            embedder_url = os.environ.get("EMBEDDER_URL", "http://localhost:9090")
            client = Client(host=host, port=port, database=db, embedder_url=embedder_url)
        except ImportError:
            print(
                "  [org-sync] Error: spacetime_memory SDK not installed. "
                "Run: pip install spacetime-memory"
            )
            sys.exit(1)
        except Exception as e:
            print(f"  [org-sync] Error connecting to SpacetimeDB: {e}")
            sys.exit(1)

    daemon = OrgSyncDaemon(
        org_dir=args.dir,
        workspace_id=args.workspace,
        client=client,
        interval=args.interval,
        dry_run=args.dry_run,
    )

    if args.once:
        total = daemon.scan()
        print(f"  [org-sync] One-shot sync complete: {total} events")
        return

    # Continuous mode — try watchdog, fall back to polling
    if args.watchdog:
        observer = _start_watchdog_observer(args.dir, daemon)
        if observer is not None:
            print(f"  [org-sync] Watchdog observer started on {args.dir}")
            try:
                while observer.is_alive():
                    observer.join(timeout=1)
            except KeyboardInterrupt:
                observer.stop()
            observer.join()
            save_state(daemon.state)
            print("  [org-sync] Watchdog stopped")
            return

    # Polling fallback
    daemon.run()


if __name__ == "__main__":
    main()
