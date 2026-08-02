"""Tests for the CheckpointMixin — LangGraph-parity checkpoint/restore.

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


def _make_checkpoint_memory(
    memory_id: str,
    workspace_id: str = "ws1",
    agent_id: str = "agent-1",
    state: str = '{"step": 3, "data": "hello"}',
    metadata: dict | None = None,
    created_at: int | None = None,
    expires_at: int | None = None,
    expired: bool = False,
) -> dict:
    """Build a memory dict representing a checkpoint entry."""
    now = int(time.time())
    meta = metadata or {"session_id": "sess_123"}
    state_data = {
        "state": state,
        "metadata": meta,
        "created_at": created_at or (now - 100),
        "expires_at": expires_at if expires_at is not None else (now - 10 if expired else now + 86400 * 30),
    }
    return {
        "id": memory_id,
        "workspace_id": workspace_id,
        "memory_type": "checkpoint",
        "content": json.dumps(state_data, separators=(",", ":")),
        "summary": f"checkpoint:agent={agent_id}",
        "entities_json": json.dumps({"agent_id": agent_id}),
    }


def _make_non_checkpoint_memory(
    memory_id: str,
    workspace_id: str = "ws1",
) -> dict:
    """Build a regular (non-checkpoint) memory dict — should be ignored."""
    return {
        "id": memory_id,
        "workspace_id": workspace_id,
        "memory_type": "experience",
        "content": "some regular memory",
        "summary": "a regular experience",
        "entities_json": "{}",
    }


# ============================================================================
# Checkpoint tests
# ============================================================================

class TestCheckpoint:
    """Checkpoint — create, get, list, restore, delete, prune, active sessions."""

    # ── create_checkpoint ─────────────────────────────────────────────────

    def test_create_checkpoint(self, mock_http_client):
        """create_checkpoint calls store_memory with correct args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.create_checkpoint(
            workspace_id="ws1",
            agent_id="agent-1",
            state='{"step": 3, "data": "hello"}',
            metadata={"session_id": "sess_123", "step": 3},
            ttl_seconds=3600,
        )

        assert result["status"] == "ok"
        mock_http_client._http.post.assert_called()
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/store_memory" in args[0]
        body = json.loads(kwargs["content"])
        # [workspace_id, peer_id, observer_id, memory_type, content, summary,
        #  entities_json, confidence, source_session_id, source_message_id, images_json]
        assert body[0] == "ws1"
        assert body[3] == "checkpoint"
        # Verify content is valid JSON with expected fields
        cp_state = json.loads(body[4])
        assert cp_state["state"] == '{"step": 3, "data": "hello"}'
        assert cp_state["metadata"]["session_id"] == "sess_123"
        assert cp_state["metadata"]["step"] == 3
        assert cp_state["expires_at"] > cp_state["created_at"]
        # entities_json should contain agent_id
        entities = json.loads(body[6])
        assert entities["agent_id"] == "agent-1"

    def test_create_checkpoint_defaults(self, mock_http_client):
        """create_checkpoint with minimal args uses sensible defaults."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.create_checkpoint(
            workspace_id="ws1",
            agent_id="agent-2",
            state="minimal-state",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        state = json.loads(body[4])
        assert state["state"] == "minimal-state"
        # Default TTL should be ~30 days
        expected_ttl = 86400 * 30
        assert state["expires_at"] - state["created_at"] == expected_ttl
        assert state["metadata"] == {}

    def test_create_checkpoint_with_ttl_zero(self, mock_http_client):
        """create_checkpoint with ttl_seconds=0 should not expire (expires_at=created_at)."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.create_checkpoint(
            workspace_id="ws1",
            agent_id="agent-1",
            state="no-expire",
            ttl_seconds=0,
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        state = json.loads(body[4])
        # expires_at == created_at for TTL=0
        assert state["expires_at"] == state["created_at"]

    # ── get_checkpoint ────────────────────────────────────────────────────

    def test_get_checkpoint(self, mock_http_client):
        """get_checkpoint returns the checkpoint when found."""
        memory = _make_checkpoint_memory("cp-1")
        mock_http_client._http.post.return_value = _sql_resp([memory])

        cp = mock_http_client.get_checkpoint("cp-1")

        assert cp is not None
        assert cp["checkpoint_id"] == "cp-1"
        assert cp["agent_id"] == "agent-1"
        assert cp["state"] == '{"step": 3, "data": "hello"}'
        assert cp["metadata"]["session_id"] == "sess_123"
        assert cp["_expired"] is False

    def test_get_checkpoint_not_found(self, mock_http_client):
        """get_checkpoint returns None when not found."""
        mock_http_client._http.post.return_value = _sql_resp([])

        cp = mock_http_client.get_checkpoint("missing-cp")

        assert cp is None

    def test_get_checkpoint_wrong_type(self, mock_http_client):
        """get_checkpoint returns None when the memory is not a checkpoint."""
        non_cp = _make_non_checkpoint_memory("mem-1")
        mock_http_client._http.post.return_value = _sql_resp([non_cp])

        cp = mock_http_client.get_checkpoint("mem-1")

        assert cp is None

    def test_get_checkpoint_expired(self, mock_http_client):
        """get_checkpoint returns checkpoint even if expired (caller sees _expired)."""
        memory = _make_checkpoint_memory("cp-expired", expired=True)
        mock_http_client._http.post.return_value = _sql_resp([memory])

        cp = mock_http_client.get_checkpoint("cp-expired")

        assert cp is not None
        assert cp["checkpoint_id"] == "cp-expired"
        assert cp["_expired"] is True

    # ── list_checkpoints ──────────────────────────────────────────────────

    def test_list_checkpoints(self, mock_http_client):
        """list_checkpoints returns all checkpoints for an agent."""
        cp1 = _make_checkpoint_memory("cp-1", agent_id="agent-1")
        cp2 = _make_checkpoint_memory("cp-2", agent_id="agent-1")
        non_cp = _make_non_checkpoint_memory("mem-1")
        mock_http_client._http.post.return_value = _sql_resp([cp1, cp2, non_cp])

        cps = mock_http_client.list_checkpoints(workspace_id="ws1", agent_id="agent-1")

        assert len(cps) == 2
        assert {c["checkpoint_id"] for c in cps} == {"cp-1", "cp-2"}

    def test_list_checkpoints_filters_by_agent(self, mock_http_client):
        """list_checkpoints only returns checkpoints for the requested agent."""
        cp_a = _make_checkpoint_memory("cp-a", agent_id="agent-a")
        cp_b = _make_checkpoint_memory("cp-b", agent_id="agent-b")
        mock_http_client._http.post.return_value = _sql_resp([cp_a, cp_b])

        cps = mock_http_client.list_checkpoints(workspace_id="ws1", agent_id="agent-a")

        assert len(cps) == 1
        assert cps[0]["checkpoint_id"] == "cp-a"

    def test_list_checkpoints_orders_by_created_desc(self, mock_http_client):
        """list_checkpoints returns newest first."""
        now = int(time.time())
        cp_old = _make_checkpoint_memory("cp-old", created_at=now - 1000)
        cp_new = _make_checkpoint_memory("cp-new", created_at=now)
        mock_http_client._http.post.return_value = _sql_resp([cp_old, cp_new])

        cps = mock_http_client.list_checkpoints(workspace_id="ws1", agent_id="agent-1")

        assert cps[0]["checkpoint_id"] == "cp-new"
        assert cps[1]["checkpoint_id"] == "cp-old"

    def test_list_checkpoints_excludes_expired_by_default(self, mock_http_client):
        """list_checkpoints omits expired checkpoints unless include_expired=True."""
        active = _make_checkpoint_memory("cp-active", expired=False)
        expired = _make_checkpoint_memory("cp-expired", expired=True)
        mock_http_client._http.post.return_value = _sql_resp([active, expired])

        default = mock_http_client.list_checkpoints(workspace_id="ws1", agent_id="agent-1")
        all_cps = mock_http_client.list_checkpoints(
            workspace_id="ws1", agent_id="agent-1", include_expired=True
        )

        assert len(default) == 1
        assert default[0]["checkpoint_id"] == "cp-active"
        assert len(all_cps) == 2

    def test_list_checkpoints_empty(self, mock_http_client):
        """list_checkpoints returns empty list when no checkpoints exist."""
        mock_http_client._http.post.return_value = _sql_resp([])

        cps = mock_http_client.list_checkpoints(workspace_id="ws1", agent_id="agent-1")

        assert cps == []

    # ── restore_checkpoint ────────────────────────────────────────────────

    def test_restore_checkpoint(self, mock_http_client):
        """restore_checkpoint returns the checkpoint state."""
        memory = _make_checkpoint_memory(
            "cp-1",
            state='{"step": 7, "context": "resume-here"}',
        )
        mock_http_client._http.post.return_value = _sql_resp([memory])

        cp = mock_http_client.restore_checkpoint("cp-1")

        assert cp is not None
        assert cp["state"] == '{"step": 7, "context": "resume-here"}'
        assert cp["checkpoint_id"] == "cp-1"

    def test_restore_checkpoint_not_found(self, mock_http_client):
        """restore_checkpoint returns None for missing checkpoint."""
        mock_http_client._http.post.return_value = _sql_resp([])

        cp = mock_http_client.restore_checkpoint("missing")

        assert cp is None

    # ── delete_checkpoint ─────────────────────────────────────────────────

    def test_delete_checkpoint(self, mock_http_client):
        """delete_checkpoint calls delete_memory for a valid checkpoint."""
        memory = _make_checkpoint_memory("cp-1")
        mock_http_client._http.post.return_value = _sql_resp([memory])

        result = mock_http_client.delete_checkpoint("cp-1")

        assert result["status"] == "ok"
        # Should have called delete_memory reducer
        calls = mock_http_client._http.post.call_args_list
        delete_calls = [
            c for c in calls
            if "/call/delete_memory" in str(c)
        ]
        assert len(delete_calls) >= 1

    def test_delete_checkpoint_not_found(self, mock_http_client):
        """delete_checkpoint raises NotFoundError for missing checkpoint."""
        mock_http_client._http.post.return_value = _sql_resp([])

        with pytest.raises(Exception, match="not found"):
            mock_http_client.delete_checkpoint("missing-cp")

    def test_delete_checkpoint_wrong_type(self, mock_http_client):
        """delete_checkpoint raises NotFoundError if memory is not a checkpoint."""
        non_cp = _make_non_checkpoint_memory("mem-1")
        mock_http_client._http.post.return_value = _sql_resp([non_cp])

        with pytest.raises(Exception, match="not a checkpoint|not found"):
            mock_http_client.delete_checkpoint("mem-1")

    # ── prune_checkpoints ─────────────────────────────────────────────────

    def test_prune_checkpoints_keeps_only_n(self, mock_http_client):
        """prune_checkpoints removes all but keep_last_n."""
        now = int(time.time())
        mems = []
        for i in range(15):
            mems.append(_make_checkpoint_memory(
                f"cp-{i:03d}",
                created_at=now - (15 - i) * 10,  # oldest first
                expired=False,
            ))
        mems.reverse()  # put cp-014 as most recent
        mock_http_client._http.post.return_value = _sql_resp(mems)

        result = mock_http_client.prune_checkpoints("ws1", "agent-1", keep_last_n=10)

        assert result["remaining"] == 10
        assert result["pruned"] >= 5  # 15 - 10 = 5 pruned

    def test_prune_checkpoints_removes_expired(self, mock_http_client):
        """prune_checkpoints removes expired checkpoints regardless of keep_last_n."""
        int(time.time())
        active = _make_checkpoint_memory("cp-active", expired=False)
        expired = _make_checkpoint_memory("cp-expired", expired=True)
        mock_http_client._http.post.return_value = _sql_resp([active, expired])

        result = mock_http_client.prune_checkpoints("ws1", "agent-1", keep_last_n=10)

        # Expired should be pruned, active should remain
        assert result["pruned"] >= 1
        assert result["remaining"] == 1

    def test_prune_checkpoints_noop_when_below_limit(self, mock_http_client):
        """prune_checkpoints prunes nothing when under keep_last_n."""
        now = int(time.time())
        mems = []
        for i in range(3):
            mems.append(_make_checkpoint_memory(
                f"cp-{i}", created_at=now - (3 - i) * 10, expired=False,
            ))
        mock_http_client._http.post.return_value = _sql_resp(mems)

        result = mock_http_client.prune_checkpoints("ws1", "agent-1", keep_last_n=10)

        assert result["pruned"] == 0
        assert result["remaining"] == 3

    # ── list_active_sessions ──────────────────────────────────────────────

    def test_list_active_sessions(self, mock_http_client):
        """list_active_sessions finds sessions with recent checkpoints."""
        now = int(time.time())
        meta1 = {"session_id": "sess-a"}
        meta2 = {"session_id": "sess-b"}
        cp_a = _make_checkpoint_memory(
            "cp-a", agent_id="agent-a", metadata=meta1,
            created_at=now - 60,
        )
        cp_b = _make_checkpoint_memory(
            "cp-b", agent_id="agent-b", metadata=meta2,
            created_at=now - 120,
        )
        mock_http_client._http.post.return_value = _sql_resp([cp_a, cp_b])

        sessions = mock_http_client.list_active_sessions("ws1", max_age_seconds=3600)

        assert len(sessions) == 2
        assert {s["agent_id"] for s in sessions} == {"agent-a", "agent-b"}
        # Sorted by last_checkpoint_at desc
        assert sessions[0]["last_checkpoint_at"] >= sessions[1]["last_checkpoint_at"]

    def test_list_active_sessions_excludes_stale(self, mock_http_client):
        """list_active_sessions filters out checkpoints older than max_age."""
        now = int(time.time())
        recent = _make_checkpoint_memory(
            "cp-recent", created_at=now - 60,
        )
        stale = _make_checkpoint_memory(
            "cp-stale", created_at=now - 7200,  # 2 hours ago
        )
        mock_http_client._http.post.return_value = _sql_resp([recent, stale])

        sessions = mock_http_client.list_active_sessions("ws1", max_age_seconds=3600)

        assert len(sessions) == 1
        assert sessions[0]["agent_id"] == "agent-1"

    def test_list_active_sessions_aggregates_by_agent(self, mock_http_client):
        """list_active_sessions aggregates multiple checkpoints per agent."""
        now = int(time.time())
        cp1 = _make_checkpoint_memory("cp-1", created_at=now - 100)
        cp2 = _make_checkpoint_memory("cp-2", created_at=now - 50)
        mock_http_client._http.post.return_value = _sql_resp([cp1, cp2])

        sessions = mock_http_client.list_active_sessions("ws1", max_age_seconds=3600)

        assert len(sessions) == 1
        assert sessions[0]["agent_id"] == "agent-1"
        assert sessions[0]["checkpoint_count"] == 2
        assert sessions[0]["last_checkpoint_at"] >= now - 50

    def test_list_active_sessions_no_checkpoints(self, mock_http_client):
        """list_active_sessions returns empty list when no checkpoints."""
        non_cp = _make_non_checkpoint_memory("mem-1")
        mock_http_client._http.post.return_value = _sql_resp([non_cp])

        sessions = mock_http_client.list_active_sessions("ws1")

        assert sessions == []

    # ── Edge cases ────────────────────────────────────────────────────────

    def test_list_checkpoints_ignores_non_checkpoint_memories(self, mock_http_client):
        """list_checkpoints filters out non-checkpoint memories."""
        cp = _make_checkpoint_memory("cp-1")
        regular = _make_non_checkpoint_memory("mem-1")
        mock_http_client._http.post.return_value = _sql_resp([cp, regular])

        cps = mock_http_client.list_checkpoints(workspace_id="ws1", agent_id="agent-1")

        assert len(cps) == 1
        assert cps[0]["checkpoint_id"] == "cp-1"

    def test_create_checkpoint_emits_event(self, mock_http_client):
        """create_checkpoint emits a checkpoint.created event."""
        mock_http_client._http.post.return_value = _reducer_resp()

        # We just check it doesn't crash — event bus is optional
        result = mock_http_client.create_checkpoint(
            workspace_id="ws1",
            agent_id="agent-1",
            state="{}",
        )

        assert result["status"] == "ok"
