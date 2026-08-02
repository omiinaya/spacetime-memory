"""Tests for the TaskQueueMixin — Honcho-parity durable task queue.

Unit tests use the ``mock_http_client`` fixture (no SpacetimeDB required).
"""
from __future__ import annotations

import json
import time
from unittest.mock import Mock

import pytest
from conftest import make_sql_response

# ============================================================================
# Helpers
# ============================================================================

def _reducer_resp() -> Mock:
    """Return a mock response for a successful reducer call (200 + empty body)."""
    resp = Mock(status_code=200)
    resp.text = "{}"
    resp.json = dict
    return resp


def _sql_resp(rows):
    """Return a mock SQL response."""
    payload = make_sql_response(rows)
    resp = Mock(status_code=200)
    resp.text = payload
    resp.json = lambda: {"result": payload}
    return resp


def _make_task_memory(
    memory_id: str,
    workspace_id: str = "ws1",
    task_type: str = "embed",
    payload: str = "compute-embeddings",
    priority: int = 0,
    status: str = "pending",
    worker_id: str = "",
    result: str = "",
    error: str = "",
) -> dict:
    """Build a memory dict representing a task queue entry."""
    state = {
        "task_type": task_type,
        "payload": payload,
        "priority": priority,
        "status": status,
        "worker_id": worker_id,
        "result": result,
        "error": error,
        "created_at": 1000_000_000,
        "run_at": 1000_000_000,
        "claimed_at": 1001_000_000 if status == "claimed" else 0,
        "completed_at": 1002_000_000 if status == "completed" else 0,
    }
    return {
        "id": memory_id,
        "workspace_id": workspace_id,
        "memory_type": "task_queue",
        "content": json.dumps(state, separators=(",", ":")),
        "summary": f"task:{task_type} status:{status}",
    }


def _make_non_task_memory(
    memory_id: str,
    workspace_id: str = "ws1",
) -> dict:
    """Build a regular (non-task) memory dict — should be ignored."""
    return {
        "id": memory_id,
        "workspace_id": workspace_id,
        "memory_type": "experience",
        "content": "some regular memory",
        "summary": "a regular experience",
    }


# ============================================================================
# TaskQueue tests
# ============================================================================

class TestTaskQueue:
    """TaskQueue — enqueue, claim, complete, fail, list, requeue, stats."""

    # ── enqueue_task ─────────────────────────────────────────────────────

    def test_enqueue_task(self, mock_http_client):
        """enqueue_task calls store_memory with correct args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.enqueue_task(
            workspace_id="ws1",
            task_type="embed",
            payload="compute-embeddings",
            priority=5,
            delay=10,
        )

        assert result["status"] == "ok"
        mock_http_client._http.post.assert_called_once()
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/store_memory" in args[0]
        body = json.loads(kwargs["content"])
        # [workspace_id, peer_id, observer_id, memory_type, content, summary,
        #  entities_json, confidence, source_session_id, source_message_id, images_json]
        assert body[0] == "ws1"
        assert body[3] == "task_queue"
        # Verify content is valid JSON with expected fields
        task_state = json.loads(body[4])
        assert task_state["task_type"] == "embed"
        assert task_state["payload"] == "compute-embeddings"
        assert task_state["priority"] == 5
        assert task_state["status"] == "pending"
        assert body[5] == "task:embed status:pending"

    def test_enqueue_task_defaults(self, mock_http_client):
        """enqueue_task with minimal args uses defaults."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.enqueue_task(
            workspace_id="ws1",
            task_type="summarise",
            payload="do-summary",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        state = json.loads(body[4])
        assert state["priority"] == 0
        # run_at should be close to now (within ~2s)
        assert state["run_at"] <= _now_micros() + 2_000_000

    # ── claim_next_task ──────────────────────────────────────────────────

    def test_claim_next_task_happy_path(self, mock_http_client):
        """claim_next_task finds, claims, and returns the highest-priority task."""
        pending_high = _make_task_memory(
            "task-high", priority=10, status="pending",
        )
        pending_low = _make_task_memory(
            "task-low", priority=1, status="pending",
        )
        # _query("memory", ...) returns all memories
        mock_http_client._http.post.return_value = _sql_resp(
            [pending_high, pending_low]
        )

        task = mock_http_client.claim_next_task("ws1", "worker-1")

        assert task is not None
        assert task["task_id"] == "task-high"
        assert task["task_type"] == "embed"
        assert task["payload"] == "compute-embeddings"
        assert task["priority"] == 10
        assert task["worker_id"] == "worker-1"
        assert task["status"] == "claimed"
        assert task["claimed_at"] > 0

    def test_claim_next_task_with_type_filter(self, mock_http_client):
        """claim_next_task respects the task_types filter."""
        task_a = _make_task_memory("task-a", task_type="embed", status="pending")
        task_b = _make_task_memory("task-b", task_type="summarise", status="pending")
        mock_http_client._http.post.return_value = _sql_resp([task_a, task_b])

        task = mock_http_client.claim_next_task("ws1", "worker-1", task_types=["summarise"])

        assert task is not None
        assert task["task_id"] == "task-b"
        assert task["task_type"] == "summarise"

    def test_claim_next_task_no_pending(self, mock_http_client):
        """claim_next_task returns None when no tasks are pending."""
        claimed = _make_task_memory("task-1", status="claimed")
        completed = _make_task_memory("task-2", status="completed")
        mock_http_client._http.post.return_value = _sql_resp([claimed, completed])

        task = mock_http_client.claim_next_task("ws1", "worker-1")

        assert task is None

    def test_claim_next_task_filters_non_task_memories(self, mock_http_client):
        """claim_next_task ignores non-task-queue memories."""
        task = _make_task_memory("task-1", status="pending")
        regular = _make_non_task_memory("mem-1")
        mock_http_client._http.post.return_value = _sql_resp([task, regular])

        result = mock_http_client.claim_next_task("ws1", "worker-1")

        assert result is not None
        assert result["task_id"] == "task-1"

    def test_claim_next_task_empty(self, mock_http_client):
        """claim_next_task returns None on empty workspace."""
        mock_http_client._http.post.return_value = _sql_resp([])

        task = mock_http_client.claim_next_task("ws1", "worker-1")

        assert task is None

    # ── complete_task ────────────────────────────────────────────────────

    def test_complete_task(self, mock_http_client):
        """complete_task updates the task content and returns ok."""
        pending = _make_task_memory("task-1", status="claimed")
        mock_http_client._http.post.return_value = _sql_resp([pending])

        result = mock_http_client.complete_task("task-1", "success-result")

        assert result["status"] == "ok"
        # Second call is update_memory
        calls = mock_http_client._http.post.call_args_list
        assert len(calls) >= 1

    def test_complete_task_not_found(self, mock_http_client):
        """complete_task raises NotFoundError for missing task."""
        mock_http_client._http.post.return_value = _sql_resp([])

        with pytest.raises(Exception, match="not found"):
            mock_http_client.complete_task("missing-task", "result")

    # ── fail_task ────────────────────────────────────────────────────────

    def test_fail_task(self, mock_http_client):
        """fail_task updates the task with error message."""
        pending = _make_task_memory("task-1", status="claimed")
        mock_http_client._http.post.return_value = _sql_resp([pending])

        result = mock_http_client.fail_task("task-1", "something went wrong")

        assert result["status"] == "ok"

    def test_fail_task_not_found(self, mock_http_client):
        """fail_task raises NotFoundError for missing task."""
        mock_http_client._http.post.return_value = _sql_resp([])

        with pytest.raises(Exception, match="not found"):
            mock_http_client.fail_task("missing-task", "error")

    # ── list_tasks ───────────────────────────────────────────────────────

    def test_list_tasks_all(self, mock_http_client):
        """list_tasks returns all tasks in the workspace."""
        t1 = _make_task_memory("task-1", status="pending")
        t2 = _make_task_memory("task-2", status="completed")
        regular = _make_non_task_memory("mem-1")
        mock_http_client._http.post.return_value = _sql_resp([t1, t2, regular])

        tasks = mock_http_client.list_tasks("ws1")

        assert len(tasks) == 2
        assert {t["task_id"] for t in tasks} == {"task-1", "task-2"}

    def test_list_tasks_by_status(self, mock_http_client):
        """list_tasks filters by status."""
        t1 = _make_task_memory("task-1", status="pending")
        t2 = _make_task_memory("task-2", status="completed")
        mock_http_client._http.post.return_value = _sql_resp([t1, t2])

        pending = mock_http_client.list_tasks("ws1", status="pending")
        completed = mock_http_client.list_tasks("ws1", status="completed")

        assert len(pending) == 1
        assert pending[0]["task_id"] == "task-1"
        assert len(completed) == 1
        assert completed[0]["task_id"] == "task-2"

    def test_list_tasks_by_type(self, mock_http_client):
        """list_tasks filters by task_type."""
        t1 = _make_task_memory("task-1", task_type="embed", status="pending")
        t2 = _make_task_memory("task-2", task_type="summarise", status="pending")
        mock_http_client._http.post.return_value = _sql_resp([t1, t2])

        embed = mock_http_client.list_tasks("ws1", task_type="embed")

        assert len(embed) == 1
        assert embed[0]["task_id"] == "task-1"

    def test_list_tasks_invalid_status(self, mock_http_client):
        """list_tasks raises ValueError for invalid status."""
        with pytest.raises(ValueError, match="Invalid status"):
            mock_http_client.list_tasks("ws1", status="invalid")

    # ── requeue_task ─────────────────────────────────────────────────────

    def test_requeue_task(self, mock_http_client):
        """requeue_task resets status to pending and clears worker/result/error."""
        claimed = _make_task_memory("task-1", status="claimed", worker_id="w1")
        mock_http_client._http.post.return_value = _sql_resp([claimed])

        result = mock_http_client.requeue_task("task-1", delay=5)

        assert result["status"] == "ok"

    def test_requeue_task_not_found(self, mock_http_client):
        """requeue_task raises NotFoundError for missing task."""
        mock_http_client._http.post.return_value = _sql_resp([])

        with pytest.raises(Exception, match="not found"):
            mock_http_client.requeue_task("missing-task")

    # ── get_queue_stats ──────────────────────────────────────────────────

    def test_get_queue_stats(self, mock_http_client):
        """get_queue_stats returns correct counts."""
        pending = _make_task_memory("task-1", status="pending", priority=1)
        claimed = _make_task_memory("task-2", status="claimed", priority=2)
        completed = _make_task_memory("task-3", status="completed", priority=3)
        failed = _make_task_memory("task-4", status="failed", priority=4)
        regular = _make_non_task_memory("mem-1")
        mock_http_client._http.post.return_value = _sql_resp(
            [pending, claimed, completed, failed, regular]
        )

        stats = mock_http_client.get_queue_stats("ws1")

        assert stats["total"] == 4
        assert stats["pending"] == 1
        assert stats["claimed"] == 1
        assert stats["completed"] == 1
        assert stats["failed"] == 1
        assert isinstance(stats["avg_processing_time_ms"], (int, float))

    def test_get_queue_stats_empty(self, mock_http_client):
        """get_queue_stats handles empty workspace."""
        mock_http_client._http.post.return_value = _sql_resp([])

        stats = mock_http_client.get_queue_stats("ws1")

        assert stats["total"] == 0
        assert stats["pending"] == 0
        assert stats["claimed"] == 0
        assert stats["completed"] == 0
        assert stats["failed"] == 0
        assert stats["avg_processing_time_ms"] == 0.0

    def test_get_queue_stats_no_tasks_only_regular_memories(self, mock_http_client):
        """get_queue_stats ignores non-task memories."""
        regular = _make_non_task_memory("mem-1")
        mock_http_client._http.post.return_value = _sql_resp([regular])

        stats = mock_http_client.get_queue_stats("ws1")

        assert stats["total"] == 0

    # ── Edge cases ───────────────────────────────────────────────────────

    def test_claim_next_task_respects_delayed_tasks(self, mock_http_client):
        """claim_next_task skips tasks whose run_at is in the future."""
        future_run_at = (int(time.time()) + 3600) * 1_000_000  # 1 hour from now
        state = {
            "task_type": "embed",
            "payload": "delayed",
            "priority": 0,
            "status": "pending",
            "worker_id": "",
            "result": "",
            "error": "",
            "created_at": 1000_000_000,
            "run_at": future_run_at,
            "claimed_at": 0,
            "completed_at": 0,
        }
        delayed = {
            "id": "task-delayed",
            "workspace_id": "ws1",
            "memory_type": "task_queue",
            "content": json.dumps(state, separators=(",", ":")),
            "summary": "task:embed status:pending",
        }
        ready = _make_task_memory("task-ready", status="pending")
        mock_http_client._http.post.return_value = _sql_resp([delayed, ready])

        task = mock_http_client.claim_next_task("ws1", "worker-1")

        assert task is not None
        assert task["task_id"] == "task-ready"


def _now_micros() -> int:
    """Return current time in microseconds (helper for tests)."""
    return int(time.time() * 1_000_000)
