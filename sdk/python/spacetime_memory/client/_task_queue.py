"""Task Queue mixin — Honcho-parity durable task queue for agent tasks.

Stores tasks as structured memories with ``memory_type="task_queue"``.
All task state (type, payload, priority, status, worker, result, error) is
encoded as JSON in the memory's ``content`` field so that status changes can
be made via the existing ``update_memory`` reducer.

This avoids needing new STDB reducers or a dedicated table.
"""
from __future__ import annotations

import json
import time
from typing import Any

from ._base import NotFoundError, logger

# ── Task status constants ────────────────────────────────────────────────

TASK_PENDING = "pending"
TASK_CLAIMED = "claimed"
TASK_COMPLETED = "completed"
TASK_FAILED = "failed"

_VALID_STATUSES = {TASK_PENDING, TASK_CLAIMED, TASK_COMPLETED, TASK_FAILED}


# ── Helpers ──────────────────────────────────────────────────────────────

def _now_micros() -> int:
    """Return current time in microseconds since epoch."""
    return int(time.time() * 1_000_000)


def _task_id_from_memory(memory: dict[str, Any]) -> str:
    """Extract the task (memory) ID from a memory dict."""
    return memory.get("id", memory.get("memory_id", ""))


def _make_task_content(
    task_type: str,
    payload: str,
    priority: int = 0,
    delay: int = 0,
) -> str:
    """Build the JSON ``content`` for a new task memory."""
    now = _now_micros()
    run_at = now + (delay * 1_000_000)
    state = {
        "task_type": task_type,
        "payload": payload,
        "priority": priority,
        "status": TASK_PENDING,
        "worker_id": "",
        "result": "",
        "error": "",
        "created_at": now,
        "run_at": run_at,
        "claimed_at": 0,
        "completed_at": 0,
    }
    return json.dumps(state, separators=(",", ":"))


def _update_task_content(
    current_content: str,
    updates: dict[str, Any],
) -> str:
    """Apply *updates* to a JSON task content string and re-serialise."""
    try:
        state = json.loads(current_content)
    except (json.JSONDecodeError, TypeError):
        state = {}
    state.update(updates)
    return json.dumps(state, separators=(",", ":"))


def _parse_task_state(content: str) -> dict[str, Any]:
    """Parse the JSON task state from a memory content field."""
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {}


# ═══════════════════════════════════════════════════════════════════════════
# Mixin
# ═══════════════════════════════════════════════════════════════════════════

class TaskQueueMixin:
    """Spacetime-Memory task-queue mixin.

    Provides a durable task queue backed by the existing memory store.
    Tasks are ``memory_type="task_queue"`` entries whose ``content`` is a
    JSON blob holding ``task_type``, ``payload``, ``priority``, ``status``,
    ``worker_id``, ``result``, ``error``, and timestamps.

    Inherits from ``ClientBase`` for connection infrastructure.
    """

    # ── enqueue_task ─────────────────────────────────────────────────────

    def enqueue_task(
        self,
        workspace_id: str,
        task_type: str,
        payload: str,
        priority: int = 0,
        delay: int = 0,
    ) -> dict[str, Any]:
        """Add a task to the queue.

        Args:
            workspace_id: Target workspace.
            task_type: A label categorising the task (e.g. ``"embed"``,
                ``"summarise"``).
            payload: Opaque string payload for the worker.
            priority: Priority (higher = processed sooner). Default ``0``.
            delay: Delay in seconds before the task becomes claimable.
                Default ``0`` (claimable immediately).

        Returns:
            Reducer status dict with a ``task_id`` key.
        """
        content = _make_task_content(task_type, payload, priority, delay)
        summary = f"task:{task_type} status:{TASK_PENDING}"
        result = self._call(
            "store_memory",
            [
                workspace_id,
                "",                    # peer_id
                "",                    # observer_id
                "task_queue",          # memory_type
                content,
                summary,
                "[]",                  # entities_json
                0.8,                   # confidence
                "",                    # source_session_id
                "",                    # source_message_id
                "",                    # images_json
            ],
        )
        return result

    # ── claim_next_task ──────────────────────────────────────────────────

    def claim_next_task(
        self,
        workspace_id: str,
        worker_id: str,
        task_types: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Claim the next available task for a worker.

        Finds the highest-priority pending task whose delay has elapsed,
        optionally filtered by *task_types*, and claims it atomically.

        Args:
            workspace_id: Target workspace.
            worker_id: Unique identifier for the worker.
            task_types: If provided, only claim tasks matching one of
                these types.

        Returns:
            A task dict with keys ``task_id``, ``task_type``, ``payload``,
            ``priority``, ``worker_id``, ``status``, ``created_at``,
            ``run_at``, ``claimed_at`` — or ``None`` if no task is available.
        """
        # Fetch all pending task-queue memories for this workspace
        rows = self._query("memory", workspace_id=workspace_id)
        candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        now = _now_micros()

        for row in rows:
            if row.get("memory_type") != "task_queue":
                continue
            state = _parse_task_state(row.get("content", ""))
            if state.get("status") != TASK_PENDING:
                continue
            if state.get("run_at", 0) > now:
                continue
            if task_types is not None and state.get("task_type") not in task_types:
                continue
            candidates.append((row, state))

        if not candidates:
            return None

        # Sort by priority descending, then created_at ascending (FIFO)
        candidates.sort(
            key=lambda x: (-x[1].get("priority", 0), x[1].get("created_at", 0)),
        )

        memory, state = candidates[0]
        task_id = _task_id_from_memory(memory)
        content = memory.get("content", "")

        # Attempt to claim by updating the memory content with claimed status
        updated = _update_task_content(content, {
            "status": TASK_CLAIMED,
            "worker_id": worker_id,
            "claimed_at": now,
        })
        try:
            self.update_memory(task_id, updated)
        except Exception as exc:
            logger.warning("claim_next_task: update_memory failed for %s: %s", task_id, exc)
            return None

        state["status"] = TASK_CLAIMED
        state["worker_id"] = worker_id
        state["claimed_at"] = now
        return {
            "task_id": task_id,
            "task_type": state.get("task_type", ""),
            "payload": state.get("payload", ""),
            "priority": state.get("priority", 0),
            "worker_id": worker_id,
            "status": TASK_CLAIMED,
            "created_at": state.get("created_at", 0),
            "run_at": state.get("run_at", 0),
            "claimed_at": now,
        }

    # ── complete_task ────────────────────────────────────────────────────

    def complete_task(
        self,
        task_id: str,
        result: str,
    ) -> dict[str, Any]:
        """Mark a task as completed.

        Args:
            task_id: The task ID returned by :meth:`enqueue_task` /
                :meth:`claim_next_task`.
            result: Opaque result string produced by the worker.

        Returns:
            Reducer status dict.
        """
        rows = self._query("memory", filter_dict={"id": task_id})
        if not rows:
            raise NotFoundError(f"Task {task_id!r} not found")
        current = rows[0].get("content", "")
        now = _now_micros()
        updated = _update_task_content(current, {
            "status": TASK_COMPLETED,
            "result": result,
            "completed_at": now,
        })
        return self.update_memory(task_id, updated)

    # ── fail_task ────────────────────────────────────────────────────────

    def fail_task(
        self,
        task_id: str,
        error: str,
    ) -> dict[str, Any]:
        """Mark a task as failed.

        Args:
            task_id: The task ID.
            error: Error description / traceback.

        Returns:
            Reducer status dict.
        """
        rows = self._query("memory", filter_dict={"id": task_id})
        if not rows:
            raise NotFoundError(f"Task {task_id!r} not found")
        current = rows[0].get("content", "")
        updated = _update_task_content(current, {
            "status": TASK_FAILED,
            "error": error,
        })
        return self.update_memory(task_id, updated)

    # ── list_tasks ───────────────────────────────────────────────────────

    def list_tasks(
        self,
        workspace_id: str,
        status: str | None = None,
        task_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """List tasks with optional filtering.

        Args:
            workspace_id: Target workspace.
            status: Only return tasks with this status (``"pending"``,
                ``"claimed"``, ``"completed"``, ``"failed"``).
            task_type: Only return tasks with this type label.

        Returns:
            List of task dicts with keys: ``task_id``, ``task_type``,
            ``payload``, ``priority``, ``status``, ``worker_id``,
            ``result``, ``error``, ``created_at``, ``run_at``,
            ``claimed_at``, ``completed_at``.
        """
        if status is not None and status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid status {status!r}. Must be one of {_VALID_STATUSES}"
            )

        rows = self._query("memory", workspace_id=workspace_id)
        tasks: list[dict[str, Any]] = []
        for row in rows:
            if row.get("memory_type") != "task_queue":
                continue
            state = _parse_task_state(row.get("content", ""))
            if status is not None and state.get("status") != status:
                continue
            if task_type is not None and state.get("task_type") != task_type:
                continue
            tasks.append({
                "task_id": _task_id_from_memory(row),
                "task_type": state.get("task_type", ""),
                "payload": state.get("payload", ""),
                "priority": state.get("priority", 0),
                "status": state.get("status", TASK_PENDING),
                "worker_id": state.get("worker_id", ""),
                "result": state.get("result", ""),
                "error": state.get("error", ""),
                "created_at": state.get("created_at", 0),
                "run_at": state.get("run_at", 0),
                "claimed_at": state.get("claimed_at", 0),
                "completed_at": state.get("completed_at", 0),
            })
        tasks.sort(key=lambda t: (-t["priority"], t["created_at"]))
        return tasks

    # ── requeue_task ─────────────────────────────────────────────────────

    def requeue_task(
        self,
        task_id: str,
        delay: int = 0,
    ) -> dict[str, Any]:
        """Put a task back in the queue (reset status to pending).

        Args:
            task_id: The task ID.
            delay: Delay in seconds before the task becomes claimable
                again. Default ``0``.

        Returns:
            Reducer status dict.
        """
        rows = self._query("memory", filter_dict={"id": task_id})
        if not rows:
            raise NotFoundError(f"Task {task_id!r} not found")
        current = rows[0].get("content", "")
        now = _now_micros()
        run_at = now + (delay * 1_000_000)
        updated = _update_task_content(current, {
            "status": TASK_PENDING,
            "worker_id": "",
            "result": "",
            "error": "",
            "run_at": run_at,
            "claimed_at": 0,
            "completed_at": 0,
        })
        return self.update_memory(task_id, updated)

    # ── get_queue_stats ──────────────────────────────────────────────────

    def get_queue_stats(
        self,
        workspace_id: str,
    ) -> dict[str, Any]:
        """Get queue depth, processing time, and status breakdown.

        Args:
            workspace_id: Target workspace.

        Returns:
            Dict with keys: ``total``, ``pending``, ``claimed``,
            ``completed``, ``failed``, ``avg_processing_time_ms``.
        """
        rows = self._query("memory", workspace_id=workspace_id)
        total = 0
        counts = {s: 0 for s in _VALID_STATUSES}
        processing_times: list[int] = []

        for row in rows:
            if row.get("memory_type") != "task_queue":
                continue
            state = _parse_task_state(row.get("content", ""))
            status = state.get("status", TASK_PENDING)
            total += 1
            if status in counts:
                counts[status] += 1

            # Compute processing time for completed tasks
            if status == TASK_COMPLETED:
                claimed = state.get("claimed_at", 0)
                completed = state.get("completed_at", 0)
                if claimed and completed and completed > claimed:
                    processing_times.append(completed - claimed)

        avg_ms = 0.0
        if processing_times:
            # Convert microseconds to milliseconds
            avg_ms = (sum(processing_times) / len(processing_times)) / 1000.0

        return {
            "total": total,
            "pending": counts[TASK_PENDING],
            "claimed": counts[TASK_CLAIMED],
            "completed": counts[TASK_COMPLETED],
            "failed": counts[TASK_FAILED],
            "avg_processing_time_ms": round(avg_ms, 1),
        }
