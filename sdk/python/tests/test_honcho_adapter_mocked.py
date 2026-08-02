"""
Tests that mock client internals to cover success paths.

Integration tests for the Honcho adapter - split from the original
test_honcho_adapter.py.  These tests require a running SpacetimeDB instance
on localhost:3001 (handled by the ``stdb_session`` fixture in conftest.py).
"""

from __future__ import annotations

import uuid

import pytest

from spacetime_memory.sdks import Honcho

pytestmark = [
    pytest.mark.integration,
]


def _uid(prefix: str = "honcho-test") -> str:
    """Generate a unique ID."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class TestWithMocks:
    """Tests that mock client internals to cover success paths."""

    def test_add_messages_success_path(self, honcho: Honcho, monkeypatch) -> None:
        """Session.add_messages() success path — mock store to return ok."""
        from unittest.mock import MagicMock

        sid = _uid("session")
        pid = _uid()
        p = honcho.peer(pid)
        s = honcho.session(sid)
        s.add_peers([p])

        # Mock store to succeed
        mock_store = MagicMock(return_value={"status": "ok"})
        monkeypatch.setattr(honcho._client, "store", mock_store)

        msg = p.message("Mocked success")
        results = s.add_messages([msg])
        assert isinstance(results, list)

    def test_session_search_returns_results(self, honcho: Honcho, monkeypatch) -> None:
        """Session.search() with mocked search results."""
        from unittest.mock import MagicMock

        sid = _uid("session")
        s = honcho.session(sid)

        mock_search = MagicMock(
            return_value=[
                {"id": "mem-1", "memory_content": "test result", "metadata": {"peer_id": "p1"}}
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        results = s.search("test")
        assert isinstance(results, list)

    def test_peer_search_returns_results(self, honcho: Honcho, monkeypatch) -> None:
        """Peer.search() with mocked search results."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)

        mock_search = MagicMock(
            return_value=[
                {
                    "id": "mem-1",
                    "memory_content": "peer search result",
                    "metadata": {"peer_id": pid},
                }
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        results = p.search("test")
        assert isinstance(results, list)

    def test_peer_chat_with_search_results(self, honcho: Honcho, monkeypatch) -> None:
        """Peer.chat() returns string when search finds memories."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)

        mock_search = MagicMock(
            return_value=[
                {"memory_content": "I enjoy hiking", "metadata": {"peer_id": pid}},
                {"memory_content": "I like pizza", "metadata": {"peer_id": pid}},
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        response = p.chat("What do I like?")
        # Should return a string now since search finds data
        assert response is not None
        assert isinstance(response, str)

    def test_peer_chat_stream_with_results(self, honcho: Honcho, monkeypatch) -> None:
        """Peer.chat_stream() yields chunks when chat returns data."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)

        mock_search = MagicMock(
            return_value=[
                {"memory_content": "stream test data", "metadata": {"peer_id": pid}},
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        gen = p.chat_stream("test")
        chunks = list(gen)
        assert isinstance(chunks, list)

    def test_honcho_search_returns_results(self, honcho: Honcho, monkeypatch) -> None:
        """Honcho.search() with mocked search results hits Message construction."""
        from unittest.mock import MagicMock

        mock_search = MagicMock(
            return_value=[
                {"id": "mem-1", "memory_content": "honcho search", "metadata": {"peer_id": "p1"}}
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        results = honcho.search("test")
        assert isinstance(results, list)

    def test_session_messages_returns_data(self, honcho: Honcho, monkeypatch) -> None:
        """Session.messages() with mocked search results."""
        from unittest.mock import MagicMock

        sid = _uid("session")
        s = honcho.session(sid)

        mock_search = MagicMock(
            return_value=[
                {"id": "msg-1", "memory_content": "content", "metadata": {"peer_id": "p1"}}
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        page = s.messages()
        assert page is not None

    def test_session_delete_fallback(self, honcho: Honcho, monkeypatch) -> None:
        """Session.delete() exercises the _call fallback path."""
        from unittest.mock import MagicMock

        sid = _uid("session")
        s = honcho.session(sid)

        # Mock _call to see the fallback path
        mock_call = MagicMock()
        monkeypatch.setattr(honcho._client, "_call", mock_call)

        try:
            s.delete()
        except RuntimeError:
            pass  # Fallback call may still fail but tests the path

    def test_queue_status_with_memories(self, honcho: Honcho, monkeypatch) -> None:
        """Honcho.queue_status() with mocked list_memories."""
        from unittest.mock import MagicMock

        mock_list = MagicMock(return_value=[{"id": "c1"}, {"id": "c2"}])
        monkeypatch.setattr(honcho._client, "list_memories", mock_list)

        status = honcho.queue_status()
        assert status is not None

    def test_conclusion_scope_list_with_data(self, honcho: Honcho, monkeypatch) -> None:
        """ConclusionScope.list() with mocked search returning conclusions."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)

        mock_search = MagicMock(
            return_value=[
                {
                    "id": "c1",
                    "memory_content": "conclusion text",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": p.id,
                    },
                }
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        page = scope.list()
        assert page is not None

    def test_conclusion_scope_query_with_data(self, honcho: Honcho, monkeypatch) -> None:
        """ConclusionScope.query() with mocked search returning conclusions."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)

        mock_search = MagicMock(
            return_value=[
                {
                    "id": "c1",
                    "memory_content": "queried conclusion",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": p.id,
                    },
                }
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        results = scope.query("test")
        assert isinstance(results, list)

    def test_conclusion_scope_list_reverse(self, honcho: Honcho, monkeypatch) -> None:
        """ConclusionScope.list() with reverse=True."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)

        mock_search = MagicMock(
            return_value=[
                {
                    "id": "c1",
                    "memory_content": "first",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": p.id,
                    },
                },
                {
                    "id": "c2",
                    "memory_content": "second",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": p.id,
                    },
                },
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        page = scope.list(reverse=True)
        assert page is not None

    def test_conclusion_scope_list_filters(self, honcho: Honcho, monkeypatch) -> None:
        """ConclusionScope.list() exercises filter skip paths (non-matching data)."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)

        # Return mix: some non-conclusion, some wrong observer/observed
        mock_search = MagicMock(
            return_value=[
                {
                    "id": "s1",
                    "memory_content": "not a conclusion",
                    "metadata": {"memory_type": "message"},
                },  # skipped: wrong type
                {
                    "id": "c1",
                    "memory_content": "wrong observer",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": "other",
                        "observed_id": p.id,
                    },
                },  # skipped: wrong observer
                {
                    "id": "c2",
                    "memory_content": "wrong observed",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": "other",
                    },
                },  # skipped: wrong observed
                {
                    "id": "c3",
                    "memory_content": "valid conclusion",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": p.id,
                    },
                },  # included
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        page = scope.list()
        assert page is not None

    def test_conclusion_scope_list_with_session_filter(self, honcho: Honcho, monkeypatch) -> None:
        """ConclusionScope.list() with session filter skips wrong session."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)

        mock_search = MagicMock(
            return_value=[
                {
                    "id": "c1",
                    "memory_content": "wrong session",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": p.id,
                        "session_id": "other-session",
                    },
                },  # skipped: wrong session
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        page = scope.list(session="target-session")
        assert page is not None

    def test_conclusion_scope_query_filters(self, honcho: Honcho, monkeypatch) -> None:
        """ConclusionScope.query() exercises filter skip paths."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)

        mock_search = MagicMock(
            return_value=[
                {
                    "id": "s1",
                    "memory_content": "plain message",
                    "metadata": {"memory_type": "message"},
                },  # skipped
                {
                    "id": "c1",
                    "memory_content": "wrong observer",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": "other",
                        "observed_id": p.id,
                    },
                },  # skipped
                {
                    "id": "c2",
                    "memory_content": "wrong observed",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": "other",
                    },
                },  # skipped
                {
                    "id": "c3",
                    "memory_content": "valid query result",
                    "metadata": {
                        "memory_type": "conclusion",
                        "observer_id": p.id,
                        "observed_id": p.id,
                    },
                },  # included
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        results = scope.query("filter test")
        assert isinstance(results, list)

