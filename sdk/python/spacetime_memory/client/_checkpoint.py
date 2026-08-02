"""Checkpoint/Restore module — LangGraph-parity agent state snapshots.

Checkpoints save and restore agent state, allowing interrupted or long-running
tasks to resume.  Stored as memories with ``memory_type="checkpoint"`` whose
``content`` is a JSON blob carrying ``state``, ``metadata``, and timestamps.

TTL support: each checkpoint has an ``expires_at`` field (seconds since epoch).
When the TTL elapses, the checkpoint is considered stale and pruned by
:meth:`prune_checkpoints` or skipped by :meth:`list_checkpoints`.
"""
from __future__ import annotations

import json
import time
from typing import Any

from ._base import NotFoundError, logger

# ── Constants ─────────────────────────────────────────────────────────────

CHECKPOINT_MEMORY_TYPE = "checkpoint"
"""SpacetimeDB ``memory_type`` used for checkpoint entries."""

_DEFAULT_TTL_SECONDS = 86400 * 30  # 30 days
"""Default TTL for checkpoints (seconds)."""


# ── Helpers ───────────────────────────────────────────────────────────────


def _now_seconds() -> int:
    """Return current time in seconds since epoch."""
    return int(time.time())


def _make_checkpoint_content(
    state: str,
    metadata: dict[str, Any] | None = None,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> str:
    """Build the JSON ``content`` for a new checkpoint memory.

    Args:
        state: The serialised agent state (JSON string or opaque value).
        metadata: Optional arbitrary metadata dict.
        ttl_seconds: Time-to-live in seconds from creation.

    Returns:
        A JSON string suitable for the memory's ``content`` field.
    """
    now = _now_seconds()
    payload = {
        "state": state,
        "metadata": metadata or {},
        "created_at": now,
        "expires_at": now + ttl_seconds,
    }
    return json.dumps(payload, separators=(",", ":"))


def _parse_checkpoint_content(content: str) -> dict[str, Any]:
    """Parse the JSON checkpoint state from a memory content field.

    Args:
        content: The raw ``content`` string from a memory record.

    Returns:
        A dict with keys ``state``, ``metadata``, ``created_at``, ``expires_at``.
    """
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {"state": "", "metadata": {}, "created_at": 0, "expires_at": 0}


def _checkpoint_id_from_memory(memory: dict[str, Any]) -> str:
    """Extract the checkpoint (memory) ID from a memory dict."""
    return memory.get("id", memory.get("memory_id", ""))


def _is_expired(checkpoint_data: dict[str, Any]) -> bool:
    """Check whether a parsed checkpoint has expired.

    Args:
        checkpoint_data: Parsed checkpoint content dict.

    Returns:
        ``True`` if ``expires_at`` is set and is in the past.
    """
    expires = checkpoint_data.get("expires_at", 0)
    return expires > 0 and _now_seconds() > expires


# ═══════════════════════════════════════════════════════════════════════════
# Mixin
# ═══════════════════════════════════════════════════════════════════════════


class CheckpointMixin:
    """Spacetime-Memory checkpoint/restore mixin.

    Provides LangGraph-parity checkpoint save, restore, list, prune, and
    session tracking — all backed by the existing memory store.

    Checkpoints are ``memory_type="checkpoint"`` entries whose ``content``
    is a JSON blob holding ``state``, ``metadata``, ``created_at``, and
    ``expires_at``.

    Inherits from ``ClientBase`` for connection infrastructure.
    """

    # ── create_checkpoint ─────────────────────────────────────────────────

    def create_checkpoint(
        self,
        workspace_id: str,
        agent_id: str,
        state: str,
        metadata: dict[str, Any] | None = None,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> dict[str, Any]:
        """Save an agent state snapshot as a checkpoint.

        Args:
            workspace_id: Target workspace.
            agent_id: Unique identifier for the agent.
            state: Serialised agent state (JSON string or opaque value).
            metadata: Optional arbitrary metadata dict (e.g. ``{"step": 5,
                "session_id": "sess_123"}``).
            ttl_seconds: Time-to-live in seconds.  Defaults to 30 days.
                Pass ``0`` for no-expiry (use with caution).

        Returns:
            Reducer status dict with a ``checkpoint_id`` key.
        """
        content = _make_checkpoint_content(state, metadata, ttl_seconds)
        summary = f"checkpoint:agent={agent_id} ts={_now_seconds()}"
        result = self._call(
            "store_memory",
            [
                workspace_id,
                "",                          # peer_id
                "",                          # observer_id
                CHECKPOINT_MEMORY_TYPE,       # memory_type
                content,
                summary,
                json.dumps({"agent_id": agent_id}),  # entities_json
                0.8,                         # confidence
                "",                          # source_session_id
                "",                          # source_message_id
                "",                          # images_json
            ],
        )

        # Emit checkpoint.created event
        self._emit_event(
            "checkpoint.created",
            {
                "agent_id": agent_id,
                "workspace_id": workspace_id,
                "summary": summary,
            },
            workspace_id=workspace_id,
        )

        # Invalidate query cache for this workspace
        if self._query_cache is not None:
            self._query_cache.invalidate(workspace_id=workspace_id)

        return result

    # ── get_checkpoint ────────────────────────────────────────────────────

    def get_checkpoint(
        self,
        checkpoint_id: str,
    ) -> dict[str, Any] | None:
        """Retrieve a single checkpoint by ID.

        Args:
            checkpoint_id: The checkpoint's memory ID.

        Returns:
            A checkpoint dict with keys ``checkpoint_id``, ``state``,
            ``metadata``, ``created_at``, ``expires_at``, ``agent_id``,
            ``workspace_id`` — or ``None`` if not found.
        """
        rows = self._query("memory", filter_dict={"id": checkpoint_id})
        if not rows:
            return None
        memory = rows[0]
        if memory.get("memory_type") != CHECKPOINT_MEMORY_TYPE:
            return None
        return self._build_checkpoint_dict(memory)

    # ── list_checkpoints ──────────────────────────────────────────────────

    def list_checkpoints(
        self,
        workspace_id: str,
        agent_id: str,
        include_expired: bool = False,
    ) -> list[dict[str, Any]]:
        """List checkpoints for an agent, newest first.

        Args:
            workspace_id: Target workspace.
            agent_id: The agent to list checkpoints for.
            include_expired: If ``False`` (default), expired checkpoints are
                omitted from the results.

        Returns:
            A list of checkpoint dicts sorted by ``created_at`` descending.
        """
        rows = self._query("memory", workspace_id=workspace_id)
        checkpoints: list[dict[str, Any]] = []
        for row in rows:
            if row.get("memory_type") != CHECKPOINT_MEMORY_TYPE:
                continue
            # Check agent_id from entities_json
            entities_raw = row.get("entities_json", "{}")
            try:
                entities = json.loads(entities_raw) if entities_raw else {}
            except (json.JSONDecodeError, TypeError):
                entities = {}
            if entities.get("agent_id") != agent_id:
                continue

            cp_data = _parse_checkpoint_content(row.get("content", ""))
            if not include_expired and _is_expired(cp_data):
                continue

            cp_dict = self._build_checkpoint_dict(row)
            checkpoints.append(cp_dict)

        checkpoints.sort(key=lambda c: c.get("created_at", 0), reverse=True)
        return checkpoints

    # ── restore_checkpoint ────────────────────────────────────────────────

    def restore_checkpoint(
        self,
        checkpoint_id: str,
    ) -> dict[str, Any] | None:
        """Retrieve checkpoint state for resuming an agent.

        This is semantically equivalent to :meth:`get_checkpoint` for the
        restore use-case.  It returns the full checkpoint dict so the caller
        can extract ``state``, ``metadata``, etc.

        Args:
            checkpoint_id: The checkpoint's memory ID.

        Returns:
            A checkpoint dict (same shape as :meth:`get_checkpoint`) or
            ``None`` if not found.
        """
        return self.get_checkpoint(checkpoint_id)

    # ── delete_checkpoint ─────────────────────────────────────────────────

    def delete_checkpoint(
        self,
        checkpoint_id: str,
    ) -> dict[str, Any]:
        """Delete a single checkpoint by ID.

        Args:
            checkpoint_id: The checkpoint's memory ID.

        Returns:
            Reducer status dict.

        Raises:
            NotFoundError: If the checkpoint does not exist.
        """
        # Verify it exists and is a checkpoint
        rows = self._query("memory", filter_dict={"id": checkpoint_id})
        if not rows:
            raise NotFoundError(f"Checkpoint {checkpoint_id!r} not found")
        if rows[0].get("memory_type") != CHECKPOINT_MEMORY_TYPE:
            raise NotFoundError(f"Memory {checkpoint_id!r} is not a checkpoint")

        return self._call("delete_memory", [checkpoint_id])

    # ── prune_checkpoints ─────────────────────────────────────────────────

    def prune_checkpoints(
        self,
        workspace_id: str,
        agent_id: str,
        keep_last_n: int = 10,
    ) -> dict[str, Any]:
        """Remove old checkpoints, keeping only the N most recent.

        Also removes any expired checkpoints regardless of count.

        Args:
            workspace_id: Target workspace.
            agent_id: The agent whose checkpoints to prune.
            keep_last_n: Maximum number of recent checkpoints to retain
                (after removing expired ones).  Default ``10``.

        Returns:
            A dict with ``pruned`` (int) and ``remaining`` (int) counters.
        """
        all_cps = self.list_checkpoints(
            workspace_id, agent_id, include_expired=True
        )
        # Separate expired and active
        expired: list[dict[str, Any]] = []
        active: list[dict[str, Any]] = []
        for cp in all_cps:
            if cp.get("_expired", False):
                expired.append(cp)
            else:
                active.append(cp)

        # Active checkpoints are already sorted newest-first
        to_delete = expired + active[keep_last_n:]  # keep_last_n newest
        pruned_count = 0
        for cp in to_delete:
            cid = cp.get("checkpoint_id", "")
            if not cid:
                continue
            try:
                self._call("delete_memory", [cid])
                pruned_count += 1
            except Exception as exc:
                logger.warning(
                    "prune_checkpoints: failed to delete %s: %s", cid, exc
                )

        remaining = max(0, len(active) - max(0, len(active) - keep_last_n))
        return {
            "pruned": pruned_count,
            "remaining": remaining,
        }

    # ── list_active_sessions ──────────────────────────────────────────────

    def list_active_sessions(
        self,
        workspace_id: str,
        max_age_seconds: int = 3600,
    ) -> list[dict[str, Any]]:
        """List sessions that have recent checkpoints.

        Useful for discovering which agents/sessions are still active.

        Args:
            workspace_id: Target workspace.
            max_age_seconds: Maximum age of the most recent checkpoint to
                consider a session active.  Default ``3600`` (1 hour).

        Returns:
            A list of dicts, each with keys ``agent_id``, ``session_id``
            (if present in metadata), ``last_checkpoint_at``, and
            ``checkpoint_count``.  Sorted by ``last_checkpoint_at``
            descending.
        """
        now = _now_seconds()
        cutoff = now - max_age_seconds
        rows = self._query("memory", workspace_id=workspace_id)

        # Aggregate by agent_id
        agent_map: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row.get("memory_type") != CHECKPOINT_MEMORY_TYPE:
                continue
            entities_raw = row.get("entities_json", "{}")
            try:
                entities = json.loads(entities_raw) if entities_raw else {}
            except (json.JSONDecodeError, TypeError):
                entities = {}
            agent_id = entities.get("agent_id", "")

            cp_data = _parse_checkpoint_content(row.get("content", ""))
            created = cp_data.get("created_at", 0)

            if created < cutoff:
                continue  # too old

            session_id = cp_data.get("metadata", {}).get("session_id", "")

            if agent_id not in agent_map:
                agent_map[agent_id] = {
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "last_checkpoint_at": created,
                    "checkpoint_count": 0,
                }
            else:
                existing = agent_map[agent_id]
                existing["last_checkpoint_at"] = max(existing["last_checkpoint_at"], created)
                if session_id and not existing["session_id"]:
                    existing["session_id"] = session_id

            agent_map[agent_id]["checkpoint_count"] += 1

        sessions = list(agent_map.values())
        sessions.sort(key=lambda s: s.get("last_checkpoint_at", 0), reverse=True)
        return sessions

    # ── Internal helpers ──────────────────────────────────────────────────

    def _build_checkpoint_dict(
        self,
        memory: dict[str, Any],
    ) -> dict[str, Any]:
        """Convert a memory record into a structured checkpoint dict.

        Args:
            memory: A raw memory dict from the database.

        Returns:
            A normalised checkpoint dict.
        """
        cp_data = _parse_checkpoint_content(memory.get("content", ""))
        entities_raw = memory.get("entities_json", "{}")
        try:
            entities = json.loads(entities_raw) if entities_raw else {}
        except (json.JSONDecodeError, TypeError):
            entities = {}

        return {
            "checkpoint_id": _checkpoint_id_from_memory(memory),
            "workspace_id": memory.get("workspace_id", ""),
            "agent_id": entities.get("agent_id", ""),
            "state": cp_data.get("state", ""),
            "metadata": cp_data.get("metadata", {}),
            "created_at": cp_data.get("created_at", 0),
            "expires_at": cp_data.get("expires_at", 0),
            "_expired": _is_expired(cp_data),
        }
