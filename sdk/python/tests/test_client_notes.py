"""Unit tests for NotesMixin — note CRUD, backlinks, blocks.

All tests use the ``mock_http_client`` fixture — no live SpacetimeDB required.
"""

from __future__ import annotations

from unittest.mock import patch


class TestNotesMixin:
    """NotesMixin methods (notes, backlinks, blocks)."""

    # --- Note CRUD ---

    def test_create_note_basic(self, mock_http_client):
        """create_note with no content returns ok (no embed needed)."""
        result = mock_http_client.create_note(
            workspace_id="ws-1", title="Test", content=""
        )
        assert result == {"status": "ok"}

    def test_create_note_with_content_no_embed(self, mock_http_client):
        """create_note with content but embed=False skips embedding."""
        result = mock_http_client.create_note(
            workspace_id="ws-1", title="Hello", content="World", embed=False
        )
        assert result == {"status": "ok"}

    def test_create_note_with_embed(self, mock_http_client):
        """create_note with content triggers embedding and indexing."""
        with patch.object(mock_http_client, "_embed", return_value=[0.1, 0.2, 0.3]), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"id": "note-1", "content": "World", "title": "Hello"}
             ]), \
             patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_tantivy_index", return_value=True):
            result = mock_http_client.create_note(
                workspace_id="ws-1", title="Hello", content="World", embed=True
            )
        assert result["status"] == "ok"
        assert result["id"] == "note-1"
        assert result["title"] == "Hello"
        assert result["content"] == "World"

    def test_update_note(self, mock_http_client):
        with patch.object(mock_http_client, "_embed", return_value=[0.1]), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"id": "note-1", "workspace_id": "ws-1", "content": "test"}
             ]), \
             patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_tantivy_index", return_value=True):
            result = mock_http_client.update_note(
                note_id="note-1", title="Updated", content="New content", expected_version=1
            )
        assert result == {"status": "ok"}

    def test_update_note_content_empty(self, mock_http_client):
        """update_note with empty content skips re-indexing."""
        result = mock_http_client.update_note(
            note_id="note-1", title="Updated", content="", expected_version=0
        )
        assert result == {"status": "ok"}

    def test_delete_note(self, mock_http_client):
        result = mock_http_client.delete_note("note-1")
        assert result == {"status": "ok"}

    def test_delete_note_with_cleanup_failure(self, mock_http_client):
        """delete_note still returns ok even if remove_from_index fails."""
        with patch.object(mock_http_client, "_call", side_effect=[
            {"status": "ok"},
            RuntimeError("index cleanup failed"),
        ]):
            result = mock_http_client.delete_note("note-1")
        assert result == {"status": "ok"}

    def test_list_notes(self, mock_http_client):
        """list_notes returns empty list when no notes exist."""
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.list_notes("ws-1")
        assert result == []

    def test_list_notes_with_data(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[
            {"id": "note-1", "title": "Note 1", "updated_at": 200},
            {"id": "note-2", "title": "Note 2", "updated_at": 100},
        ]):
            result = mock_http_client.list_notes("ws-1")
        assert len(result) == 2
        # Should be sorted by updated_at DESC
        assert result[0]["id"] == "note-1"

    def test_list_notes_include_inactive(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[
            {"id": "note-1", "is_active": "false"},
        ]):
            result = mock_http_client.list_notes("ws-1", include_inactive=True)
        assert len(result) == 1

    def test_get_note(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[{"id": "note-1", "title": "Test Note"}]):
            result = mock_http_client.get_note("note-1")
        assert len(result) == 1
        assert result[0]["id"] == "note-1"

    def test_get_note_by_date(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.get_note_by_date("2026-07-07")
        assert result == []

    def test_get_note_by_title(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.get_note_by_title("Hello")
        assert result == []

    def test_get_note_by_title_with_workspace(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[{"id": "note-1", "title": "Hello"}]):
            result = mock_http_client.get_note_by_title("Hello", workspace_id="ws-1")
        assert len(result) == 1
        assert result[0]["id"] == "note-1"

    def test_get_backlinks(self, mock_http_client):
        with patch.object(mock_http_client, "_query", side_effect=[
            [{"source_note_id": "note-2", "target_note_id": "note-1"}],
            [{"id": "note-2", "title": "Backlink Source"}],
        ]):
            result = mock_http_client.get_backlinks("note-1")
        assert len(result) == 1
        assert result[0]["source_title"] == "Backlink Source"

    def test_get_outgoing_links(self, mock_http_client):
        with patch.object(mock_http_client, "_query", side_effect=[
            [{"source_note_id": "note-1", "target_note_id": "note-2"}],
            [{"id": "note-2", "title": "Target Note"}],
        ]):
            result = mock_http_client.get_outgoing_links("note-1")
        assert len(result) == 1
        assert result[0]["target_title"] == "Target Note"

    def test_update_note_block(self, mock_http_client):
        result = mock_http_client.update_note_block("block-1", content="New content", block_type="text")
        assert result == {"status": "ok"}

    def test_parse_note_blocks(self, mock_http_client):
        result = mock_http_client.parse_note_blocks("note-1")
        assert result == {"status": "ok"}
