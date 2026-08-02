"""Tests for the InterruptMixin — LangGraph-parity interrupt/resume protocol.

Unit tests use the ``mock_http_client`` fixture (no SpacetimeDB required).
"""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

# ============================================================================
# Helpers
# ============================================================================

def _reducer_resp() -> Mock:
    """Return a mock response for a successful reducer call (200 + empty body)."""
    resp = Mock(status_code=200)
    resp.text = "{}"
    resp.json = dict
    return resp


def _make_session_step_result(
    session_id: str = "sess_001",
    state: str = "interrupted",
    reason: str = "",
    interrupt_step_id: str = "",
) -> dict:
    """Build a session_step_result row with state info."""
    info = {
        "session_id": session_id,
        "workspace_id": "ws_001",
        "state": state,
        "total_steps": 5,
        "interrupt_reason": reason,
        "interrupt_step_id": interrupt_step_id,
        "last_resume_step_id": "",
        "updated_at": 1000000,
    }
    return {
        "query_hash": f"state:{session_id}",
        "id": "result_001",
        "session_id": session_id,
        "workspace_id": "ws_001",
        "step_type": "state_info",
        "content": json.dumps(info),
        "summary": f"state:{state}",
        "parent_step_id": "",
        "created_at": 1000000,
    }


def _make_session(
    session_id: str = "sess_001",
    workspace_id: str = "ws_001",
    metadata: object = None,
) -> dict:
    """Build a session dict for query results."""
    if metadata is None:
        metadata = {"interrupt_state": "interrupted", "interrupt_reason": "test"}
    return {
        "id": session_id,
        "workspace_id": workspace_id,
        "name": "Test Session",
        "summary": "",
        "metadata": json.dumps(metadata) if isinstance(metadata, dict) else str(metadata),
        "created_at": 1000000,
        "updated_at": 1000000,
    }


# ============================================================================
# Interrupt tests
# ============================================================================

class TestInterruptMixin:
    """InterruptMixin — interrupt_session, resume_session, get_session_state, list_interrupted_sessions."""

    # ── interrupt_session ────────────────────────────────────────────────

    def test_interrupt_session(self, mock_http_client):
        """interrupt_session calls interrupt_session reducer with correct args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.interrupt_session(
            workspace_id="ws_001",
            session_id="sess_001",
            reason="awaiting user input",
            target_step_id="step_005",
        )

        assert result["status"] == "ok"
        mock_http_client._http.post.assert_called()
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/interrupt_session" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["ws_001", "sess_001", "awaiting user input", "step_005"]

    def test_interrupt_session_no_target(self, mock_http_client):
        """interrupt_session works without target_step_id."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.interrupt_session(
            workspace_id="ws_001",
            session_id="sess_001",
            reason="max steps reached",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        assert body == ["ws_001", "sess_001", "max steps reached", ""]

    def test_interrupt_session_empty_reason(self, mock_http_client):
        """interrupt_session works with empty reason."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.interrupt_session(
            workspace_id="ws_001",
            session_id="sess_001",
            reason="",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        assert body == ["ws_001", "sess_001", "", ""]

    # ── resume_session ───────────────────────────────────────────────────

    def test_resume_session(self, mock_http_client):
        """resume_session calls resume_session reducer with correct args."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.resume_session(
            workspace_id="ws_001",
            session_id="sess_001",
            from_step_id="step_interrupt_001",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        assert "/call/resume_session" in args[0]
        body = json.loads(kwargs["content"])
        assert body == ["ws_001", "sess_001", "step_interrupt_001"]

    def test_resume_session_find_latest(self, mock_http_client):
        """resume_session with empty from_step_id lets server find latest interrupt."""
        mock_http_client._http.post.return_value = _reducer_resp()

        result = mock_http_client.resume_session(
            workspace_id="ws_001",
            session_id="sess_001",
        )

        assert result["status"] == "ok"
        args, kwargs = mock_http_client._http.post.call_args
        body = json.loads(kwargs["content"])
        assert body == ["ws_001", "sess_001", ""]

    # ── get_session_state ────────────────────────────────────────────────

    def test_get_session_state(self, mock_http_client):
        """get_session_state calls reducer then queries session_step_result."""
        # First call = get_session_state reducer
        # Second call = query_table reducer (inside _query)
        # Third call = SQL read from query_result (inside _query)
        step_result = _make_session_step_result(
            session_id="sess_001",
            state="interrupted",
            reason="awaiting user input",
            interrupt_step_id="step_interrupt_001",
        )
        reducer_resp = Mock(status_code=200, text="{}", json=dict)
        sql_resp = Mock(
            status_code=200,
            text=json.dumps([{
                "schema": {
                    "elements": [
                        {"name": {"some": k}}
                        for k in step_result.keys()
                    ]
                },
                "rows": [[step_result[k] for k in step_result.keys()]],
            }]),
            json=lambda: {
                "result": json.dumps([{
                    "schema": {
                        "elements": [
                            {"name": {"some": k}}
                            for k in step_result.keys()
                        ]
                    },
                    "rows": [[step_result[k] for k in step_result.keys()]],
                }])
            },
        )
        mock_http_client._http.post.side_effect = [reducer_resp, sql_resp, sql_resp, sql_resp]

        state = mock_http_client.get_session_state("sess_001")

        assert state is not None
        assert state["session_id"] == "sess_001"
        assert state["state"] == "interrupted"
        assert state["interrupt_reason"] == "awaiting user input"
        assert state["interrupt_step_id"] == "step_interrupt_001"
        assert state["total_steps"] == 5

    def test_get_session_state_running(self, mock_http_client):
        """get_session_state returns 'running' state when session is active."""
        step_result = _make_session_step_result(
            session_id="sess_001",
            state="running",
        )
        reducer_resp = Mock(status_code=200, text="{}", json=dict)
        sql_resp = Mock(
            status_code=200,
            text=json.dumps([{
                "schema": {
                    "elements": [
                        {"name": {"some": k}}
                        for k in step_result.keys()
                    ]
                },
                "rows": [[step_result[k] for k in step_result.keys()]],
            }]),
            json=lambda: {
                "result": json.dumps([{
                    "schema": {
                        "elements": [
                            {"name": {"some": k}}
                            for k in step_result.keys()
                        ]
                    },
                    "rows": [[step_result[k] for k in step_result.keys()]],
                }])
            },
        )
        mock_http_client._http.post.side_effect = [reducer_resp, sql_resp, sql_resp, sql_resp]

        state = mock_http_client.get_session_state("sess_001")

        assert state is not None
        assert state["state"] == "running"

    def test_get_session_state_reducer_fails(self, mock_http_client):
        """get_session_state returns None when reducer fails."""
        mock_http_client._http.post.return_value = Mock(
            status_code=500,
            text="Internal error",
            json=lambda: {"error": "internal"},
        )

        state = mock_http_client.get_session_state("sess_001")

        assert state is None

    def test_get_session_state_no_results(self, mock_http_client):
        """get_session_state returns None when no result rows exist."""
        reducer_resp = Mock(status_code=200, text="{}", json=dict)
        sql_resp = Mock(
            status_code=200,
            text=json.dumps([]),
            json=lambda: {"result": json.dumps([])},
        )
        mock_http_client._http.post.side_effect = [reducer_resp, sql_resp, sql_resp, sql_resp]

        state = mock_http_client.get_session_state("sess_001")

        assert state is None

    # ── list_interrupted_sessions ────────────────────────────────────────

    def test_list_interrupted_sessions(self, mock_http_client):
        """list_interrupted_sessions finds sessions with interrupted state."""
        meta_interrupted = {
            "interrupt_state": "interrupted",
            "interrupt_reason": "awaiting input",
            "interrupt_step_id": "step_001",
            "interrupt_target_step": "step_000",
        }
        meta_running = {"interrupt_state": "running"}

        sess1 = _make_session("sess_001", "ws_001", meta_interrupted)
        sess2 = _make_session("sess_002", "ws_001", meta_running)

        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text=json.dumps([{
                "schema": {
                    "elements": [
                        {"name": {"some": k}}
                        for k in sess1.keys()
                    ]
                },
                "rows": [
                    [sess1[k] for k in sess1.keys()],
                    [sess2[k] for k in sess2.keys()],
                ],
            }]),
            json=lambda: {
                "result": json.dumps([{
                    "schema": {
                        "elements": [
                            {"name": {"some": k}}
                            for k in sess1.keys()
                        ]
                    },
                    "rows": [
                        [sess1[k] for k in sess1.keys()],
                        [sess2[k] for k in sess2.keys()],
                    ],
                }])
            },
        )

        interrupted = mock_http_client.list_interrupted_sessions("ws_001")

        assert len(interrupted) == 1
        assert interrupted[0]["id"] == "sess_001"
        assert interrupted[0]["_interrupt_reason"] == "awaiting input"
        assert interrupted[0]["_interrupt_step_id"] == "step_001"
        assert interrupted[0]["_interrupt_target_step"] == "step_000"

    def test_list_interrupted_sessions_empty(self, mock_http_client):
        """list_interrupted_sessions returns empty list when none are interrupted."""
        meta_running = {"interrupt_state": "running"}
        sess = _make_session("sess_001", "ws_001", meta_running)

        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text=json.dumps([{
                "schema": {
                    "elements": [
                        {"name": {"some": k}}
                        for k in sess.keys()
                    ]
                },
                "rows": [[sess[k] for k in sess.keys()]],
            }]),
            json=lambda: {
                "result": json.dumps([{
                    "schema": {
                        "elements": [
                            {"name": {"some": k}}
                            for k in sess.keys()
                        ]
                    },
                    "rows": [[sess[k] for k in sess.keys()]],
                }])
            },
        )

        interrupted = mock_http_client.list_interrupted_sessions("ws_001")

        assert interrupted == []

    def test_list_interrupted_sessions_no_metadata(self, mock_http_client):
        """list_interrupted_sessions handles sessions without interrupt metadata."""
        sess = _make_session("sess_001", "ws_001", metadata={})

        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text=json.dumps([{
                "schema": {
                    "elements": [
                        {"name": {"some": k}}
                        for k in sess.keys()
                    ]
                },
                "rows": [[sess[k] for k in sess.keys()]],
            }]),
            json=lambda: {
                "result": json.dumps([{
                    "schema": {
                        "elements": [
                            {"name": {"some": k}}
                            for k in sess.keys()
                        ]
                    },
                    "rows": [[sess[k] for k in sess.keys()]],
                }])
            },
        )

        interrupted = mock_http_client.list_interrupted_sessions("ws_001")

        assert interrupted == []

    def test_list_interrupted_sessions_invalid_metadata(self, mock_http_client):
        """list_interrupted_sessions handles invalid metadata JSON gracefully."""
        sess = _make_session("sess_001", "ws_001", metadata="not-json")

        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text=json.dumps([{
                "schema": {
                    "elements": [
                        {"name": {"some": k}}
                        for k in sess.keys()
                    ]
                },
                "rows": [[sess[k] for k in sess.keys()]],
            }]),
            json=lambda: {
                "result": json.dumps([{
                    "schema": {
                        "elements": [
                            {"name": {"some": k}}
                            for k in sess.keys()
                        ]
                    },
                    "rows": [[sess[k] for k in sess.keys()]],
                }])
            },
        )

        # Should not raise
        interrupted = mock_http_client.list_interrupted_sessions("ws_001")

        assert interrupted == []

    # ── Error edge cases ─────────────────────────────────────────────────

    def test_interrupt_session_reducer_error(self, mock_http_client):
        """interrupt_session raises when reducer returns error."""
        mock_http_client._http.post.return_value = Mock(
            status_code=400,
            text="Session not found",
            json=lambda: {"error": "Session 'sess_999' not found"},
        )

        with pytest.raises(Exception):
            mock_http_client.interrupt_session(
                workspace_id="ws_001",
                session_id="sess_999",
                reason="test",
            )

    def test_resume_session_reducer_error(self, mock_http_client):
        """resume_session raises when reducer returns error."""
        mock_http_client._http.post.return_value = Mock(
            status_code=400,
            text="Session has no interrupt step",
            json=lambda: {"error": "Session has no interrupt step"},
        )

        with pytest.raises(Exception):
            mock_http_client.resume_session(
                workspace_id="ws_001",
                session_id="sess_001",
            )
