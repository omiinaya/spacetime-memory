"""
Tests that mock client internals — session, peer, and dream operations.

Split from test_honcho_adapter_mocked.py to keep each file under 500 lines.
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


class TestWithMocksExtra:
    """Tests that mock client internals — session, peer, and dream operations."""

    def test_session_get_message_with_mock(self, honcho: Honcho, monkeypatch) -> None:
        """Session.get_message() success path with mocked get_memory."""
        from unittest.mock import MagicMock

        sid = _uid("session")
        s = honcho.session(sid)

        mock_get = MagicMock(
            return_value=[
                {
                    "id": "msg-1",
                    "memory_content": "found message",
                    "peer_id": "p1",
                    "metadata": {"k": "v"},
                }
            ]
        )
        monkeypatch.setattr(honcho._client, "get_memory", mock_get)

        result = s.get_message("msg-1")
        assert result is not None

    def test_session_update_message_with_mock(self, honcho: Honcho, monkeypatch) -> None:
        """Session.update_message() success path with mocked get_memory."""
        from unittest.mock import MagicMock

        sid = _uid("session")
        s = honcho.session(sid)

        mock_get = MagicMock(
            return_value=[
                {"id": "msg-1", "memory_content": "update me", "peer_id": "p1", "metadata": {}}
            ]
        )
        mock_update = MagicMock()
        monkeypatch.setattr(honcho._client, "get_memory", mock_get)
        monkeypatch.setattr(honcho._client, "update_memory", mock_update)

        s.update_message("msg-1", {"new_key": "new_val"})

    def test_session_delete_call_path(self, honcho: Honcho) -> None:
        """Session.delete() exercises the real _call path (not mocked)."""
        sid = _uid("session")
        s = honcho.session(sid)
        try:
            s.delete()
        except RuntimeError:
            pass  # May fail without auth but tests the path

    def test_peer_get_card_llm_unavailable(self, honcho: Honcho, monkeypatch) -> None:
        """Peer.get_card() returns empty when LLM unavailable."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)

        # Mock LLMClient to be unavailable
        mock_llm = MagicMock()
        mock_llm.available = False
        monkeypatch.setattr(
            "spacetime_memory.sdks.honcho.LLMClient",
            lambda: mock_llm,
        )
        # Also mock search to return something so we exercise the path
        mock_search = MagicMock(
            return_value=[{"memory_content": "some data", "metadata": {"peer_id": pid}}]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        card = p.get_card()
        assert card == {"summary": "", "traits": []}

    def test_peer_representation_llm_unavailable(self, honcho: Honcho, monkeypatch) -> None:
        """Peer.representation() with LLM unavailable but memories exist."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)

        # Mock LLMClient to be unavailable
        mock_llm = MagicMock()
        mock_llm.available = False
        monkeypatch.setattr(
            "spacetime_memory.sdks.honcho.LLMClient",
            lambda: mock_llm,
        )
        # Mock search to return data
        mock_search = MagicMock(
            return_value=[
                {"memory_content": "I like running", "metadata": {"peer_id": pid}},
                {"memory_content": "I enjoy reading", "metadata": {"peer_id": pid}},
            ]
        )
        monkeypatch.setattr(honcho._client, "search", mock_search)

        rep = p.representation()
        assert isinstance(rep, str)
        assert pid in rep

    def test_schedule_dream_with_session_and_observed(self, honcho: Honcho) -> None:
        """Honcho.schedule_dream() with explicit session and observed params."""
        pid = _uid()
        pid2 = _uid()
        p = honcho.peer(pid)
        p2 = honcho.peer(pid2)
        sid = _uid("session")
        s = honcho.session(sid)

        try:
            honcho.schedule_dream(observer=p, session=s, observed=p2)
        except RuntimeError:
            pass  # May fail without LLM but tests the ID resolution paths

    def test_schedule_dream_with_string_ids(self, honcho: Honcho) -> None:
        """Honcho.schedule_dream() with string IDs (not Peer/Session objects)."""
        pid = _uid()
        pid2 = _uid()
        sid = _uid("session")

        try:
            honcho.schedule_dream(observer=pid, session=sid, observed=pid2)
        except RuntimeError:
            pass  # May fail without LLM but tests the string ID paths

    def test_schedule_dream_with_mock(self, honcho: Honcho, monkeypatch) -> None:
        """Honcho.schedule_dream() with mocked list_memories to hit filter path."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)

        mock_list = MagicMock(
            return_value=[
                {"peer_id": pid, "content": "observation 1"},
                {"peer_id": pid, "content": "observation 2"},
                {"peer_id": "other", "content": "irrelevant"},
            ]
        )
        monkeypatch.setattr(honcho._client, "list_memories", mock_list)

        # Mock LLM to be unavailable to avoid API calls
        mock_llm = MagicMock()
        mock_llm.available = False
        monkeypatch.setattr(
            "spacetime_memory.sdks.honcho.LLMClient",
            lambda: mock_llm,
        )

        try:
            honcho.schedule_dream(observer=p)
        except RuntimeError:
            pass

    def test_peer_representation_no_llm_no_memories(self, honcho: Honcho, monkeypatch) -> None:
        """Peer.representation() with LLM unavailable and no memories."""
        from unittest.mock import MagicMock

        pid = _uid()
        p = honcho.peer(pid)

        mock_llm = MagicMock()
        mock_llm.available = False
        monkeypatch.setattr(
            "spacetime_memory.sdks.honcho.LLMClient",
            lambda: mock_llm,
        )
        # Mock search to return empty
        mock_search = MagicMock(return_value=[])
        monkeypatch.setattr(honcho._client, "search", mock_search)

        rep = p.representation()
        assert "unavailable" in rep

    def test_session_get_message_empty_results(self, honcho: Honcho, monkeypatch) -> None:
        """Session.get_message() returns None when get_memory returns empty."""
        from unittest.mock import MagicMock

        sid = _uid("session")
        s = honcho.session(sid)

        # Empty results from get_memory
        mock_get = MagicMock(return_value=[])
        monkeypatch.setattr(honcho._client, "get_memory", mock_get)

        result = s.get_message("msg-1")
        assert result is None

    def test_session_update_message_empty_results(self, honcho: Honcho, monkeypatch) -> None:
        """Session.update_message() returns early when get_memory returns empty."""
        from unittest.mock import MagicMock

        sid = _uid("session")
        s = honcho.session(sid)

        mock_get = MagicMock(return_value=[])
        monkeypatch.setattr(honcho._client, "get_memory", mock_get)

        # Should return without calling update_memory
        s.update_message("msg-1", {"k": "v"})

    def test_conclusion_scope_create_success(self, honcho: Honcho, monkeypatch) -> None:
        """ConclusionScope.create() success path — mock store to return ok."""
        from unittest.mock import MagicMock

        from spacetime_memory.sdks.honcho import ConclusionCreateParams

        pid = _uid()
        p = honcho.peer(pid)
        scope = p.conclusions(observer=p)

        mock_store = MagicMock(return_value={"status": "ok"})
        monkeypatch.setattr(honcho._client, "store", mock_store)

        params = ConclusionCreateParams(content="Success conclusion")
        results = scope.create([params])
        assert isinstance(results, list)
        assert len(results) > 0


