#!/usr/bin/env python3
"""Replication daemon for spacetime-memory.

Syncs mutations between SpacetimeDB instances in both directions
(push AND pull) with conflict resolution.

Usage:
    python scripts/replication_daemon.py [--interval 60] [--once] [--mode both]
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
from spacetime_memory.client import _esc

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
            d.get("context", ""),       # images_json / context
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
    """Syncs mutations between SpacetimeDB instances in both directions.

    Reads replication peers from the local database, pushes unsynced log
    entries to each remote peer, and pulls remote unsynced entries to
    the local instance. Supports conflict resolution via timestamp comparison.

    Args:
        interval: Seconds between sync cycles (default: 60).
        once: If True, run a single sync cycle and exit.
        mode: One of "push", "pull", or "both" (default: "both").
    """

    def __init__(
        self, interval: int = 60, once: bool = False, mode: str = "both"
    ) -> None:
        self.interval = interval
        self.once = once
        self.mode = mode
        self._local_client = self._build_local_client()

    # ------------------------------------------------------------------
    # Client factory
    # ------------------------------------------------------------------

    @staticmethod
    def _build_local_client() -> Client:
        """Build a Client from the same env vars the SDK uses."""
        client = Client()
        # Ensure identity is registered (same flow as consolidation cron)
        _TOKEN_FILE = os.getenv("REPLICATION_IDENTITY_TOKEN_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".replication_identity_token"))
        if os.path.exists(_TOKEN_FILE):
            try:
                with open(_TOKEN_FILE) as f:
                    client._identity_token = f.read().strip()
                    client._identity_established = True
                    return client
            except (OSError, json.JSONDecodeError):
                pass
        import uuid as _uuid
        user = f"repl_{_uuid.uuid4().hex[:8]}"
        try:
            client._call("register", [user, "Replication", "replpass123"])
        except RuntimeError:
            pass
        try:
            my_id = client._whoami()
            client._call("set_initial_admin", [my_id])
        except RuntimeError:
            pass
        if getattr(client, "_identity_token", None):
            try:
                with open(_TOKEN_FILE, "w") as f:
                    f.write(client._identity_token)
            except (OSError, json.JSONDecodeError):
                pass
        return client

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
        except (OSError, json.JSONDecodeError) as exc:
            _log(f"Error fetching peers: {exc}")
            return []

    def _get_unsynced_entries(
        self, workspace_id: str, client: Client | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Fetch unsynced log entries for a workspace.

        Args:
            workspace_id: The workspace to query.
            client: The client to query (defaults to local client).
            limit: Max number of entries to fetch.
        """
        c = client or self._local_client
        try:
            c._call("get_unsynced_entries", [workspace_id, limit])
            rows = c._sql(
                "SELECT * FROM replication_result "
                "WHERE query_type = 'unsynced' "
                f"AND workspace_id = '{_esc(workspace_id)}' "
                "ORDER BY created_at DESC LIMIT 1"
            )
            if not rows:
                return []
            return json.loads(rows[0].get("json_data", "[]"))
        except (OSError, json.JSONDecodeError) as exc:
            _log(f"Error fetching unsynced entries for {workspace_id}: {exc}")
            return []

    def _mark_synced(self, log_ids: list[str], client: Client | None = None) -> None:
        """Mark log entries as synced.

        Args:
            log_ids: List of log entry IDs to mark as synced.
            client: The client to use (defaults to local).
        """
        if not log_ids:
            return
        c = client or self._local_client
        try:
            c._call("mark_log_synced", [json.dumps(log_ids)])
        except (OSError, json.JSONDecodeError) as exc:
            _log(f"Error marking log entries as synced: {exc}")

    def _mark_peer_synced(self, peer_id: str, last_sync_at: int) -> None:
        """Update a peer's last_sync_at timestamp locally."""
        try:
            self._local_client._call("mark_peer_synced", [peer_id, last_sync_at])
        except (OSError, json.JSONDecodeError) as exc:
            _log(f"Error marking peer synced: {exc}")

    # ------------------------------------------------------------------
    # Apply a single log entry to a remote instance (push direction)
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
        except (OSError, json.JSONDecodeError) as exc:
            _log(
                f"Failed to apply {operation} on {table_name} "
                f"(record_id={entry.get('record_id', '')}): {exc}"
            )
            return False

    # ------------------------------------------------------------------
    # Push: send local unsynced entries to a remote peer
    # ------------------------------------------------------------------

    def push_to_peer(self, peer: dict[str, Any]) -> int:
        """Push local unsynced entries to a single remote peer.

        Returns the number of entries successfully pushed.
        """
        workspace_id = peer.get("workspace_id", "")
        remote_url = peer.get("remote_url", "")
        remote_db = peer.get("remote_db", "")
        auth_token = peer.get("auth_token", "")

        _log(
            f"PUSH: workspace '{workspace_id}' "
            f"to peer '{peer.get('name', '')}' at {remote_url}"
        )

        # Build remote client
        try:
            remote = self._build_remote_client(remote_url, remote_db, auth_token)
        except (OSError, json.JSONDecodeError) as exc:
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
            f"PUSH: synced {count} entries to '{peer.get('name', '')}' "
            f"({failures} failures)"
        )
        return count

    # ------------------------------------------------------------------
    # Pull: fetch remote unsynced entries and apply them locally
    # ------------------------------------------------------------------

    def pull_from_peer(self, peer: dict[str, Any]) -> int:
        """Pull unsynced entries from a remote peer and apply locally.

        Connects to the remote instance, reads its unsynced replication
        entries, then calls replicate_incoming on the LOCAL instance to
        apply them with conflict resolution.

        Returns the number of entries successfully pulled.
        """
        workspace_id = peer.get("workspace_id", "")
        remote_url = peer.get("remote_url", "")
        remote_db = peer.get("remote_db", "")
        peer_id = peer.get("id", "")
        auth_token = peer.get("auth_token", "")

        _log(
            f"PULL: workspace '{workspace_id}' "
            f"from peer '{peer.get('name', '')}' at {remote_url}"
        )

        # Build remote client
        try:
            remote = self._build_remote_client(remote_url, remote_db, auth_token)
        except (OSError, json.JSONDecodeError) as exc:
            _log(f"Failed to build remote client: {exc}")
            return 0

        # Read remote unsynced entries
        try:
            remote_entries = self._get_unsynced_entries(
                workspace_id, client=remote, limit=200
            )
        except (OSError, json.JSONDecodeError) as exc:
            _log(f"Failed to fetch remote unsynced entries: {exc}")
            return 0

        if not remote_entries:
            _log(f"PULL: no unsynced entries on remote for '{peer.get('name', '')}'")
            return 0

        _log(
            f"PULL: found {len(remote_entries)} unsynced entries on remote"
        )

        # Serialize entries as JSON and call replicate_incoming on LOCAL instance
        entries_json = json.dumps(remote_entries)
        try:
            self._local_client._call(
                "replicate_incoming",
                [workspace_id, peer_id, entries_json],
            )
        except (OSError, json.JSONDecodeError) as exc:
            _log(f"PULL: replicate_incoming failed: {exc}")
            return 0

        # Mark entries as synced on the remote side (they've been pulled)
        log_ids = [e.get("id", "") for e in remote_entries if e.get("id")]
        if log_ids:
            try:
                remote._call("mark_log_synced", [json.dumps(log_ids)])
            except (OSError, json.JSONDecodeError) as exc:
                _log(f"PULL: failed to mark remote entries synced: {exc}")

        # Update the peer's last_sync_at locally
        ts = int(time.time() * 1_000_000)
        self._mark_peer_synced(peer_id, ts)

        _log(
            f"PULL: pulled {len(remote_entries)} entries from "
            f"'{peer.get('name', '')}'"
        )
        return len(remote_entries)

    # ------------------------------------------------------------------
    # Bi-directional sync for a single peer
    # ------------------------------------------------------------------

    def sync_bidirectional(self, peer: dict[str, Any]) -> dict[str, int]:
        """Run push then pull for a single peer.

        Returns a dict with 'pushed' and 'pulled' counts.
        """
        result: dict[str, int] = {"pushed": 0, "pulled": 0}

        if self.mode in ("push", "both"):
            result["pushed"] = self.push_to_peer(peer)

        if self.mode in ("pull", "both"):
            result["pulled"] = self.pull_from_peer(peer)

        return result

    # ------------------------------------------------------------------
    # Legacy: sync a workspace to a single peer (push-only, backwards compat)
    # ------------------------------------------------------------------

    def _sync_to_peer(
        self, peer: dict[str, Any]
    ) -> int:
        """Push unsynced entries for a workspace to a single peer.

        Legacy method — uses push_to_peer internally now.

        Returns the number of entries successfully synced.
        """
        return self.push_to_peer(peer)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def sync_once(self) -> int:
        """Run a single sync cycle. Returns total entries synced (push+pull)."""
        total = 0
        peers = self._get_active_peers()

        if not peers:
            _log("No active replication peers found")
            return 0

        _log(f"Found {len(peers)} active peer(s), mode={self.mode}")

        for peer in peers:
            result = self.sync_bidirectional(peer)
            total += result.get("pushed", 0) + result.get("pulled", 0)

        _log(f"Sync cycle complete — {total} entries replicated")
        return total

    def run(self) -> None:
        """Run the daemon loop (or single sync if --once)."""
        if self.once:
            self.sync_once()
            return

        _log(
            f"Replication daemon started (interval={self.interval}s, "
            f"mode={self.mode}, "
            f"pid={os.getpid()})"
        )

        # Write PID file
        pid_file = "/tmp/spacetime-replication.pid"
        try:
            with open(pid_file, "w") as f:
                f.write(str(os.getpid()))
        except (OSError, json.JSONDecodeError):
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
            except (OSError, json.JSONDecodeError):
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
    parser.add_argument(
        "--mode",
        type=str,
        default="both",
        choices=["push", "pull", "both"],
        help="Sync direction: push, pull, or both (default: both)",
    )
    args = parser.parse_args()

    daemon = ReplicationDaemon(
        interval=args.interval, once=args.once, mode=args.mode
    )
    daemon.run()


if __name__ == "__main__":
    main()
