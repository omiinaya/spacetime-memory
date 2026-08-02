"""Unit tests for HistoryMixin — memory history, note history, batch updates.

All tests use the ``mock_http_client`` fixture — no live SpacetimeDB required.
"""

from __future__ import annotations

from unittest.mock import patch


class TestHistoryMixin:
    """HistoryMixin methods (batch updates, memory history, note history)."""

    # --- Batch update memories ---

    def test_batch_update_memories(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[
            {"id": "mem-1", "workspace_id": "ws-1", "content": "old", "summary": "", "confidence": 0.8}
        ]), \
             patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.batch_update_memories(
                "ws-1", ["mem-1"], {"content": "new content", "confidence": 0.95}
            )
        assert result == {"status": "ok", "updated": 1}

    def test_batch_update_memories_not_found(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.batch_update_memories(
                "ws-1", ["mem-1"], {"content": "new"}
            )
        assert result["status"] == "partial"
        assert result["updated"] == 0
        assert len(result["errors"]) == 1

    def test_batch_update_memories_wrong_workspace(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[
            {"id": "mem-1", "workspace_id": "other-ws", "content": "old", "summary": "", "confidence": 0.8}
        ]):
            result = mock_http_client.batch_update_memories(
                "ws-1", ["mem-1"], {"content": "new"}
            )
        assert result["status"] == "partial"
        assert result["updated"] == 0

    def test_batch_update_memories_exception(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[
            {"id": "mem-1", "workspace_id": "ws-1", "content": "old", "summary": "", "confidence": 0.8}
        ]), \
             patch.object(mock_http_client, "_call", side_effect=RuntimeError("update failed")):
            result = mock_http_client.batch_update_memories(
                "ws-1", ["mem-1"], {"content": "new"}
            )
        assert result["status"] == "partial"
        assert len(result["errors"]) == 1

    # --- Memory history ---

    def test_get_memory_history_empty(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.get_memory_history("mem-1")
        assert result == []

    def test_get_memory_history_with_revisions(self, mock_http_client):
        with patch.object(mock_http_client, "_query", side_effect=[
            [  # revisions
                {"memory_id": "mem-1", "version": 1, "previous_content": "", "previous_summary": "",
                 "previous_confidence": 0.0, "new_content": "v1", "new_summary": "s1", "new_confidence": 0.8,
                 "changed_at": 100, "changed_by": "user1"},
                {"memory_id": "mem-1", "version": 2, "previous_content": "v1", "previous_summary": "s1",
                 "previous_confidence": 0.8, "new_content": "v2", "new_summary": "s2", "new_confidence": 0.9,
                 "changed_at": 200, "changed_by": "user2"},
            ],
            [  # current state (version 2 already in revisions, skipped)
                {"id": "mem-1", "content": "v2", "summary": "s2", "version": 2, "updated_at": 200, "confidence": 0.9},
            ],
        ]):
            result = mock_http_client.get_memory_history("mem-1")
        assert len(result) == 2
        assert result[0]["version"] == 1
        assert result[1]["version"] == 2

    def test_get_memory_history_with_current(self, mock_http_client):
        """Current state is appended when version is newer than last revision."""
        with patch.object(mock_http_client, "_query", side_effect=[
            [  # revisions
                {"memory_id": "mem-1", "version": 1, "previous_content": "", "previous_summary": "",
                 "previous_confidence": 0.0, "new_content": "v1", "new_summary": "s1", "new_confidence": 0.8,
                 "changed_at": 100, "changed_by": "user1"},
            ],
            [  # current state (version 3, newer than last revision version 1)
                {"id": "mem-1", "content": "v3", "summary": "s3", "version": 3, "updated_at": 300, "confidence": 0.95},
            ],
        ]):
            result = mock_http_client.get_memory_history("mem-1")
        assert len(result) == 2
        assert result[1]["version"] == 3

    # --- Note history ---

    def test_get_note_history_empty(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.get_note_history("note-1")
        assert result == []

    def test_get_note_history_with_revisions(self, mock_http_client):
        with patch.object(mock_http_client, "_query", side_effect=[
            [  # revisions
                {"note_id": "note-1", "version": 1, "previous_title": "", "previous_content": "",
                 "new_title": "Title", "new_content": "Content", "changed_at": 100, "changed_by": "user1"},
            ],
            [  # current state (version not in revisions)
                {"id": "note-1", "title": "Title", "content": "Content", "version": 2, "updated_at": 200},
            ],
        ]):
            result = mock_http_client.get_note_history("note-1")
        assert len(result) == 2
        assert result[0]["version"] == 1
        assert result[1]["version"] == 2
        assert result[1]["title"] == "Title"

    def test_get_note_history_current_already_present(self, mock_http_client):
        """Current state is NOT appended when its version matches the last revision."""
        with patch.object(mock_http_client, "_query", side_effect=[
            [  # revisions
                {"note_id": "note-1", "version": 2, "previous_title": "Old", "previous_content": "Old content",
                 "new_title": "New", "new_content": "New content", "changed_at": 200, "changed_by": "user2"},
            ],
            [  # current state (version 2 matches last revision)
                {"id": "note-1", "title": "New", "content": "New content", "version": 2, "updated_at": 200},
            ],
        ]):
            result = mock_http_client.get_note_history("note-1")
        assert len(result) == 1  # only the revision, current not appended
        assert result[0]["version"] == 2
