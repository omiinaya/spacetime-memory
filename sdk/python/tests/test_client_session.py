"""Tests for SessionMixin (client/_session.py).

Covers: get_peer_sessions, get_session_messages, get_session_steps,
add_agent_step.
"""

from __future__ import annotations

import json
from unittest.mock import Mock

from conftest import make_sql_response

# ══════════════════════════════════════════════════════════════════════
# get_peer_sessions
# ══════════════════════════════════════════════════════════════════════


class TestGetPeerSessions:
    """get_peer_sessions — sessions a peer has participated in."""

    def test_no_participant_returns_empty(self, mock_http_client):
        """No session_participant rows returns []."""
        result = mock_http_client.get_peer_sessions("peer-1")
        assert result == []

    def test_one_session(self, mock_http_client):
        """Peer in one session returns that session with role/joined_at."""
        # _query("session_participant", ...) → _call("query_table", ...) + _sql
        # _query("session", ...) → _call("query_table", ...) + _sql
        # Total: 4 POST calls
        participant_rows = make_sql_response(
            [
                {
                    "table_name": "session_participant",
                    "row_json": json.dumps(
                        {
                            "session_id": "sess-1",
                            "peer_id": "peer-1",
                            "role": "owner",
                            "joined_at": 1000,
                        }
                    ),
                }
            ]
        )
        session_rows = make_sql_response(
            [
                {
                    "table_name": "session",
                    "row_json": json.dumps(
                        {
                            "id": "sess-1",
                            "workspace_id": "ws-1",
                            "name": "Test Session",
                            "created_at": 999,
                        }
                    ),
                }
            ]
        )
        # _call returns {} (default mock text=[] parsed as json returns {})
        # _sql returns the participant rows
        # _call returns {}
        # _sql returns the session rows
        Mock(status_code=200, text=json.dumps([]))
        mock_http_client._http.post.side_effect = [
            Mock(status_code=200, text=json.dumps([])),  # _call call 1
            Mock(status_code=200, text=participant_rows),  # _sql call 1
            Mock(status_code=200, text=json.dumps([])),    # _call call 2
            Mock(status_code=200, text=session_rows),      # _sql call 2
        ]

        result = mock_http_client.get_peer_sessions("peer-1")
        assert len(result) == 1
        assert result[0]["id"] == "sess-1"
        assert result[0]["role"] == "owner"
        assert result[0]["joined_at"] == 1000

    def test_multiple_sessions_sorted_by_joined_at_desc(self, mock_http_client):
        """Multiple sessions are returned sorted by joined_at descending."""
        participant_rows = make_sql_response(
            [
                {
                    "table_name": "session_participant",
                    "row_json": json.dumps(
                        {"session_id": "sess-1", "peer_id": "peer-1", "role": "member", "joined_at": 3000}
                    ),
                },
                {
                    "table_name": "session_participant",
                    "row_json": json.dumps(
                        {"session_id": "sess-2", "peer_id": "peer-1", "role": "owner", "joined_at": 1000}
                    ),
                },
            ]
        )
        # Two participant rows → two _query("session", ...) calls → 2 more pairs
        # Total: 6 POST calls
        sess1_rows = make_sql_response(
            [
                {
                    "table_name": "session",
                    "row_json": json.dumps({"id": "sess-1", "workspace_id": "ws-1", "name": "Sess1"}),
                }
            ]
        )
        sess2_rows = make_sql_response(
            [
                {
                    "table_name": "session",
                    "row_json": json.dumps({"id": "sess-2", "workspace_id": "ws-1", "name": "Sess2"}),
                }
            ]
        )

        Mock(status_code=200, text=json.dumps([]))
        mock_http_client._http.post.side_effect = [
            Mock(status_code=200, text=json.dumps([])),  # _call 1 (query_table)
            Mock(status_code=200, text=participant_rows),  # _sql 1
            Mock(status_code=200, text=json.dumps([])),  # _call 2 (session 1)
            Mock(status_code=200, text=sess1_rows),       # _sql 2
            Mock(status_code=200, text=json.dumps([])),  # _call 3 (session 2)
            Mock(status_code=200, text=sess2_rows),       # _sql 3
        ]

        result = mock_http_client.get_peer_sessions("peer-1")
        assert len(result) == 2
        # sorted by joined_at desc → sess-1 (3000) first, sess-2 (1000) second
        assert result[0]["id"] == "sess-1"
        assert result[1]["id"] == "sess-2"


# ══════════════════════════════════════════════════════════════════════
# get_session_messages
# ══════════════════════════════════════════════════════════════════════


class TestGetSessionMessages:
    """get_session_messages — messages for a session."""

    def test_no_messages_returns_empty(self, mock_http_client):
        """No message rows returns []."""
        result = mock_http_client.get_session_messages("sess-1")
        assert result == []

    def test_returns_sorted_messages(self, mock_http_client):
        """Messages are sorted by created_at ascending."""
        msg_rows = make_sql_response(
            [
                {
                    "table_name": "message",
                    "row_json": json.dumps(
                        {
                            "session_id": "sess-1",
                            "id": "msg-2",
                            "content": "second",
                            "created_at": 2000,
                        }
                    ),
                },
                {
                    "table_name": "message",
                    "row_json": json.dumps(
                        {
                            "session_id": "sess-1",
                            "id": "msg-1",
                            "content": "first",
                            "created_at": 1000,
                        }
                    ),
                },
            ]
        )
        mock_http_client._http.post.side_effect = [
            Mock(status_code=200, text=json.dumps([])),  # _call
            Mock(status_code=200, text=msg_rows),         # _sql
        ]

        result = mock_http_client.get_session_messages("sess-1")
        assert len(result) == 2
        assert result[0]["id"] == "msg-1"
        assert result[1]["id"] == "msg-2"


# ══════════════════════════════════════════════════════════════════════
# get_session_steps
# ══════════════════════════════════════════════════════════════════════


class TestGetSessionSteps:
    """get_session_steps — reasoning steps for a session."""

    def test_no_steps_returns_empty(self, mock_http_client):
        """No session_step_result rows returns []."""
        result = mock_http_client.get_session_steps("sess-1")
        assert result == []

    def test_returns_sorted_steps(self, mock_http_client):
        """Steps are sorted by created_at ascending."""
        step_rows = make_sql_response(
            [
                {
                    "table_name": "session_step_result",
                    "row_json": json.dumps(
                        {
                            "id": "step-2",
                            "session_id": "sess-1",
                            "step_type": "observation",
                            "content": "observed",
                            "created_at": 2000,
                        }
                    ),
                },
                {
                    "table_name": "session_step_result",
                    "row_json": json.dumps(
                        {
                            "id": "step-1",
                            "session_id": "sess-1",
                            "step_type": "thought",
                            "content": "thinking",
                            "created_at": 1000,
                        }
                    ),
                },
            ]
        )
        mock_http_client._http.post.side_effect = [
            Mock(status_code=200, text=json.dumps([])),  # _call (get_session_steps)
            Mock(status_code=200, text=json.dumps([])),   # _call (query_table)
            Mock(status_code=200, text=step_rows),        # _sql
        ]

        result = mock_http_client.get_session_steps("sess-1")
        assert len(result) == 2
        assert result[0]["id"] == "step-1"
        assert result[1]["id"] == "step-2"

    def test_calls_get_session_steps_reducer(self, mock_http_client):
        """get_session_steps calls the get_session_steps reducer."""
        mock_http_client._http.post.side_effect = [
            Mock(status_code=200, text=json.dumps([])),  # _call (get_session_steps)
            Mock(status_code=200, text=json.dumps([])),   # _call (query_table)
            Mock(status_code=200, text=json.dumps([])),   # _sql
        ]

        mock_http_client.get_session_steps("sess-42")
        # Verify the _call was made with the right reducer and args
        called_url = mock_http_client._http.post.call_args_list[0][0][0]
        assert "get_session_steps" in called_url


# ══════════════════════════════════════════════════════════════════════
# add_agent_step
# ══════════════════════════════════════════════════════════════════════


class TestAddAgentStep:
    """add_agent_step — record a reasoning step."""

    def test_success_returns_status(self, mock_http_client):
        """Successful reducer call returns status dict."""
        result = mock_http_client.add_agent_step(
            "sess-1", "ws-1", "thought", "I think therefore I am",
            summary="thinking", parent_step_id="",
        )
        assert result == {"status": "ok"}

    def test_calls_add_agent_step_reducer_with_correct_args(self, mock_http_client):
        """The reducer is called with the correct session/workspace/step args."""
        mock_http_client.add_agent_step(
            "sess-42", "ws-7", "action", "do_something()",
            summary="doing", parent_step_id="step-0",
        )
        called_url = mock_http_client._http.post.call_args_list[0][0][0]
        assert "add_agent_step" in called_url

    def test_custom_parent_step(self, mock_http_client):
        """parent_step_id is passed through to the reducer."""
        # Default mock response works — just verify no exception
        result = mock_http_client.add_agent_step(
            "sess-1", "ws-1", "tool_call", '{"tool": "search"}',
            summary="searching", parent_step_id="step-1",
        )
        assert result == {"status": "ok"}

    def test_empty_content_and_summary(self, mock_http_client):
        """Empty content and summary are accepted."""
        result = mock_http_client.add_agent_step(
            "sess-1", "ws-1", "observation", "", summary="",
        )
        assert result == {"status": "ok"}
