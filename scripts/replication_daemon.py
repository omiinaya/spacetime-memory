#!/usr/bin/env python3
"""Replication daemon for spacetime-memory.

Syncs mutations between SpacetimeDB instances.

Usage:
    python scripts/replication_daemon.py [--interval 60] [--once]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

# Allow running from the project root
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from spacetime_memory import Client

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    """Log to stderr with ISO timestamp."""
    ts = datetime.now(tz=timezone.utc).isoformat()
    print(f"{ts} [REPLICATION] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Mapping: table_name -> reducer name for applying mutations on the remote
# ---------------------------------------------------------------------------

# When pushing a log entry to a remote instance, we call the appropriate
# reducer to replicate the mutation.  These mappings cover the main tables
# that the replication_log is expected to record.

# Insert reducers (table_name -> (reducer, arg_extractor))
INSERT_REDUCERS: dict[str, tuple[str, callable]] = {
    "memory": (
        "store_memory",
        lambda d: [
            d.get("workspace_id", ""),
            d.get("peer_id", ""),
            d.get("observer_id", ""),
            d.get("memory_type", "experience"),
            d.get("content", ""),
            d.get("summary", ""),
            d.get("entities_json", "[]"),
            d.get("confidence", 0.8),
            d.get("source_session_id", ""),
            d.get("source_message_id", ""),
        ],
    ),
    "kg_node": (
        "create_node",
        lambda d: [
            d.get("workspace_id", ""),
            d.get("label", ""),
            d.get("node_type", "concept"),
            d.get("summary", ""),
            d.get("metadata_json", "{}"),
        ],
    ),
    "kg_edge": (
        "create_edge",
        lambda d: [
            d.get("workspace_id", ""),
            d.get("source_node_id", ""),
            d.get("target_node_id", ""),
            d.get("relation", ""),
            d.get("weight", 1.0),
            d.get("confidence", "EXTRACTED"),
            d.get("metadata_json", "{}"),
        ],
    ),
    "note": (
        "create_note",
        lambda d: [
            d.get("workspace_id", ""),
            d.get("title", ""),
            d.get("content", ""),
            d.get("note_date", ""),
            d.get("embedding_json", "[]"),
            d.get("id", ""),
        ],
    ),
    "profile": (
        "upsert_profile",
        lambda d: [
            d.get("peer_id", ""),
            d.get("static_facts_json", "[]"),
            d.get("dynamic_context_json", "[]"),
            d.get("preferences_json", "{}"),
            d.get("tags_json", "[]"),
        ],
    ),
}

# Update reducers
UPDATE_REDUCERS: dict[str, tuple[str, callable]] = {
    "memory": (
        "update_memory",
        lambda d: [
            d.get("id", ""),
            d.get("content", ""),
            d.get("summary", ""),
            d.get("confidence", 0.8),
        ],
    ),
}

# Delete reducers
DELETE_REDUCERS: dict[str, tuple[str, callable]] = {
    "memory": ("deactivate_memory", lambda d: [d.get("id", "")]),
}


# ---------------------------------------------------------------------------
# ReplicationDaemon
# ---------------------------------------------------------------------------


class ReplicationDaemon:
    """Syncs mutations between SpacetimeDB instances.

    Reads replication peers from the local database, pushes unsynced log
    entries to each remote peer, and marks entries as synced on success.

    Args:
        interval: Seconds between sync cycles (default: 60).
        once: If True, run a single sync cycle and exit.
    """

    def __init__(self, interval: int = 60, once: bool = False) -> None:
        self.interval = interval
        self.once = once
        self._local_client = self._build_local_client()

    # ------------------------------------------------------------------
    # Client factory
    # ------------------------------------------------------------------

    @staticmethod
    def _build_local_client() -> Client:
        """Build a Client from the same env vars the SDK uses."""
        return Client()

    @staticmethod
    def _build_remote_client(
        remote_url: str, remote_db: str, auth_token: str = ""
    ) -> Client:
        """Build a Client pointing at a remote SpacetimeDB instance.

        The remote_url is the base (e.g. "http://127.0.0.10:3001").
        We parse host and port from it.
        """
        # Strip protocol
        url = remote_url
        if "://" in url:
            url = url.split("://", 1)[1]
        # Strip trailing slashes
        url = url.rstrip("/")
        # Split on ':'
        if ":" in url:
            host, port_str = url.rsplit(":", 1)
            port = port_str.split("/")[0]
        else:
            host = url
            port = "3001"

        return Client(host=host, port=port, database=remote_db)

    # ------------------------------------------------------------------
    # Peer helpers
    # ------------------------------------------------------------------

    def _get_active_peers(self) -> list[dict[str, Any]]:
        """Fetch active replication peers from local SpacetimeDB."""
        try:
            self._local_client._call("list_replication_peers", ["*"])
            # Read from result table
            rows = self._local_client._sql(
                "SELECT * FROM replication_result "
                "WHERE query_type = 'peers' "
                "ORDER BY created_at DESC LIMIT 1"
            )
            if not rows:
                return []
            result_row = rows[0]
            peers = json.loads(result_row.get("json_data", "[]"))
            # Filter active
            return [p for p in peers if p.get("is_active", False)]
        except Exception as exc:
            _log(f"Error fetching peers: {exc}")
            return []

    def _get_unsynced_entries(
        self, workspace_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Fetch unsynced log entries for a workspace."""
        try:
            self._local_client._call(
                "get_unsynced_entries", [workspace_id, limit]
            )
            rows = self._local_client._sql(
                "SELECT * FROM replication_result "
                "WHERE query_type = 'unsynced' "
                "AND workspace_id = '{}' "
                "ORDER BY created_at DESC LIMIT 1".format(workspace_id)
            )
            if not rows:
                return []
            return json.loads(rows[0].get("json_data", "[]"))
        except Exception as exc:
            _log(f"Error fetching unsynced entries for {workspace_id}: {exc}")
            return []

    def _mark_synced(self, log_ids: list[str]) -> None:
        """Mark log entries as synced locally."""
        if not log_ids:
            return
        try:
            self._local_client._call("mark_log_synced", [json.dumps(log_ids)])
        except Exception as exc:
            _log(f"Error marking log entries as synced: {exc}")

    # ------------------------------------------------------------------
    # Apply a single log entry to a remote instance
    # ------------------------------------------------------------------

    def _apply_entry(
        self, remote: Client, entry: dict[str, Any]
    ) -> bool:
        """Apply a single replication log entry to a remote instance.

        Returns True on success, False on failure.
        """
        table_name = entry.get("table_name", "")
        operation = entry.get("operation", "")
        data_json = entry.get("data_json", "{}")

        try:
            data = json.loads(data_json)
        except json.JSONDecodeError as exc:
            _log(
                f"Invalid data_json in log entry {entry.get('id', '')}: {exc}"
            )
            return False

        # Dispatch by operation
        if operation == "insert":
            mapping = INSERT_REDUCERS.get(table_name)
            if mapping is None:
                _log(f"No insert reducer for table '{table_name}' — skipping")
                return False
            reducer_name, arg_fn = mapping
            args = arg_fn(data)
        elif operation == "update":
            mapping = UPDATE_REDUCERS.get(table_name)
            if mapping is None:
                _log(f"No update reducer for table '{table_name}' — skipping")
                return False
            reducer_name, arg_fn = mapping
            args = arg_fn(data)
        elif operation == "delete":
            mapping = DELETE_REDUCERS.get(table_name)
            if mapping is None:
                _log(f"No delete reducer for table '{table_name}' — skipping")
                return False
            reducer_name, arg_fn = mapping
            args = arg_fn(data)
        else:
            _log(f"Unknown operation '{operation}' — skipping")
            return False

        try:
            remote._call(reducer_name, args)
            return True
        except Exception as exc:
            _log(
                f"Failed to apply {operation} on {table_name} "
                f"(record_id={entry.get('record_id', '')}): {exc}"
            )
            return False

    # ------------------------------------------------------------------
    # Sync a workspace to a single peer
    # ------------------------------------------------------------------

    def _sync_to_peer(
        self, peer: dict[str, Any]
    ) -> int:
        """Push unsynced entries for a workspace to a single peer.

        Returns the number of entries successfully synced.
        """
        workspace_id = peer.get("workspace_id", "")
        remote_url = peer.get("remote_url", "")
        remote_db = peer.get("remote_db", "")
        auth_token = peer.get("auth_token", "")

        _log(
            f"Syncing workspace '{workspace_id}' "
            f"to peer '{peer.get('name', '')}' at {remote_url}"
        )

        # Build remote client
        try:
            remote = self._build_remote_client(remote_url, remote_db, auth_token)
        except Exception as exc:
            _log(f"Failed to build remote client: {exc}")
            return 0

        synced_ids: list[str] = []
        failures = 0

        while True:
            entries = self._get_unsynced_entries(workspace_id, limit=100)
            if not entries:
                break

            for entry in entries:
                success = self._apply_entry(remote, entry)
                if success:
                    synced_ids.append(entry.get("id", ""))
                else:
                    failures += 1

            # Mark synced entries
            if synced_ids:
                self._mark_synced(synced_ids)

            # If we got fewer than limit, we're done for this cycle
            if len(entries) < 100:
                break

        count = len(synced_ids)
        _log(
            f"Synced {count} entries to '{peer.get('name', '')}' "
            f"({failures} failures)"
        )
        return count

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def sync_once(self) -> int:
        """Run a single sync cycle. Returns total entries synced."""
        total = 0
        peers = self._get_active_peers()

        if not peers:
            _log("No active replication peers found")
            return 0

        _log(f"Found {len(peers)} active peer(s)")

        for peer in peers:
            total += self._sync_to_peer(peer)

        _log(f"Sync cycle complete — {total} entries replicated")
        return total

    def run(self) -> None:
        """Run the daemon loop (or single sync if --once)."""
        if self.once:
            self.sync_once()
            return

        _log(
            f"Replication daemon started (interval={self.interval}s, "
            f"pid={os.getpid()})"
        )

        # Write PID file
        pid_file = "/tmp/spacetime-replication.pid"
        try:
            with open(pid_file, "w") as f:
                f.write(str(os.getpid()))
        except Exception:
            pass  # Non-fatal

        try:
            while True:
                self.sync_once()
                time.sleep(self.interval)
        except KeyboardInterrupt:
            _log("Replication daemon shutting down")
        finally:
            # Clean up PID file
            try:
                if os.path.exists(pid_file):
                    os.unlink(pid_file)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Spacetime-Memory Replication Daemon"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Seconds between sync cycles (default: 60)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single sync cycle and exit",
    )
    args = parser.parse_args()

    daemon = ReplicationDaemon(interval=args.interval, once=args.once)
    daemon.run()


if __name__ == "__main__":
    main()
