"""Tests for server/mcp/tools/notes.py — Note MCP tools."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestCreateNote:
    """Tests for the ``create_note`` tool."""

    @patch("server.mcp.tools.notes.get_client")
    def test_create_note(self, mock_get_client):
        """create_note delegates to get_client().create_note."""
        mock_client = MagicMock()
        expected = {"id": "note-1", "title": "Test Note", "status": "created"}
        mock_client.create_note.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import create_note

        result = create_note(
            workspace_id="ws-1",
            title="Test Note",
            content="Hello world",
            note_date="2026-06-26",
            embed=True,
        )

        mock_client.create_note.assert_called_once_with(
            workspace_id="ws-1",
            title="Test Note",
            content="Hello world",
            note_date="2026-06-26",
            embed=True,
        )
        assert result == expected

    @patch("server.mcp.tools.notes.get_client")
    def test_create_note_with_defaults(self, mock_get_client):
        """create_note uses defaults when not all args provided."""
        mock_client = MagicMock()
        mock_client.create_note.return_value = {"id": "n1"}
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import create_note

        create_note(title="Minimal")

        mock_client.create_note.assert_called_once_with(
            workspace_id="default",
            title="Minimal",
            content="",
            note_date="",
            embed=True,
        )

    @patch("server.mcp.tools.notes.get_client")
    def test_create_note_empty_title(self, mock_get_client):
        """create_note handles empty title."""
        mock_client = MagicMock()
        mock_client.create_note.return_value = {"id": "n1", "title": ""}
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import create_note

        result = create_note(title="")

        mock_client.create_note.assert_called_once()
        assert result["id"] == "n1"
        assert result["title"] == ""

    @patch("server.mcp.tools.notes.get_client")
    def test_create_note_with_embed_false(self, mock_get_client):
        """create_note passes embed=False when specified."""
        mock_client = MagicMock()
        mock_client.create_note.return_value = {"id": "n1"}
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import create_note

        result = create_note(title="No Embed", embed=False)

        mock_client.create_note.assert_called_once_with(
            workspace_id="default",
            title="No Embed",
            content="",
            note_date="",
            embed=False,
        )
        assert result["id"] == "n1"

    @patch("server.mcp.tools.notes.get_client")
    def test_create_note_propagates_client_error(self, mock_get_client):
        """create_note propagates exceptions from the client."""
        mock_client = MagicMock()
        mock_client.create_note.side_effect = RuntimeError("Creation failed")
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import create_note

        with pytest.raises(RuntimeError, match="Creation failed"):
            create_note(title="Fail")

        mock_client.create_note.assert_called_once()


@pytest.mark.unit
class TestGetNote:
    """Tests for the ``get_note`` tool."""

    @patch("server.mcp.tools.notes.get_client")
    def test_get_note(self, mock_get_client):
        """get_note delegates to get_client().get_note."""
        mock_client = MagicMock()
        expected = [{"id": "note-1", "title": "Test"}]
        mock_client.get_note.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_note

        result = get_note(note_id="note-001")

        mock_client.get_note.assert_called_once_with("note-001")
        assert result == expected

    @patch("server.mcp.tools.notes.get_client")
    def test_get_note_not_found(self, mock_get_client):
        """get_note returns empty list when note does not exist."""
        mock_client = MagicMock()
        mock_client.get_note.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_note

        result = get_note(note_id="nonexistent")

        mock_client.get_note.assert_called_once_with("nonexistent")
        assert result == []

    @patch("server.mcp.tools.notes.get_client")
    def test_get_note_propagates_error(self, mock_get_client):
        """get_note propagates exceptions from the client."""
        mock_client = MagicMock()
        mock_client.get_note.side_effect = KeyError("Note not found")
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_note

        with pytest.raises(KeyError, match="Note not found"):
            get_note(note_id="bad")

        mock_client.get_note.assert_called_once_with("bad")


@pytest.mark.unit
class TestUpdateNote:
    """Tests for the ``update_note`` tool."""

    @patch("server.mcp.tools.notes.get_client")
    def test_update_note(self, mock_get_client):
        """update_note delegates to get_client().update_note."""
        mock_client = MagicMock()
        expected = {"id": "note-1", "status": "updated"}
        mock_client.update_note.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import update_note

        result = update_note(
            note_id="note-001",
            title="New Title",
            content="Updated content",
            embed=True,
        )

        mock_client.update_note.assert_called_once_with(
            note_id="note-001",
            title="New Title",
            content="Updated content",
            embed=True,
        )
        assert result == expected

    @patch("server.mcp.tools.notes.get_client")
    def test_update_note_with_default_embed(self, mock_get_client):
        """update_note defaults embed to True."""
        mock_client = MagicMock()
        mock_client.update_note.return_value = {"status": "ok"}
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import update_note

        update_note(note_id="n1", title="T")

        mock_client.update_note.assert_called_once_with(
            note_id="n1", title="T", content="", embed=True
        )

    @patch("server.mcp.tools.notes.get_client")
    def test_update_note_propagates_error(self, mock_get_client):
        """update_note propagates exceptions from the client."""
        mock_client = MagicMock()
        mock_client.update_note.side_effect = RuntimeError("Update failed")
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import update_note

        with pytest.raises(RuntimeError, match="Update failed"):
            update_note(note_id="n1", title="Fail")

        mock_client.update_note.assert_called_once()


@pytest.mark.unit
class TestDeleteNote:
    """Tests for the ``delete_note`` tool."""

    @patch("server.mcp.tools.notes.get_client")
    def test_delete_note(self, mock_get_client):
        """delete_note delegates to get_client().delete_note."""
        mock_client = MagicMock()
        expected = {"status": "deleted"}
        mock_client.delete_note.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import delete_note

        result = delete_note(note_id="note-001")

        mock_client.delete_note.assert_called_once_with("note-001")
        assert result == expected

    @patch("server.mcp.tools.notes.get_client")
    def test_delete_note_propagates_error(self, mock_get_client):
        """delete_note propagates exceptions from the client."""
        mock_client = MagicMock()
        mock_client.delete_note.side_effect = RuntimeError("Delete failed")
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import delete_note

        with pytest.raises(RuntimeError, match="Delete failed"):
            delete_note(note_id="bad")

        mock_client.delete_note.assert_called_once_with("bad")


@pytest.mark.unit
class TestListNotes:
    """Tests for the ``list_notes`` tool."""

    @patch("server.mcp.tools.notes.get_client")
    def test_list_notes(self, mock_get_client):
        """list_notes delegates to get_client().list_notes."""
        mock_client = MagicMock()
        expected = [{"id": "n1", "title": "Note 1"}, {"id": "n2", "title": "Note 2"}]
        mock_client.list_notes.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import list_notes

        result = list_notes(workspace_id="ws-1")

        mock_client.list_notes.assert_called_once_with("ws-1")
        assert result == expected

    @patch("server.mcp.tools.notes.get_client")
    def test_list_notes_with_default_workspace(self, mock_get_client):
        """list_notes defaults workspace_id to 'default'."""
        mock_client = MagicMock()
        mock_client.list_notes.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import list_notes

        list_notes()

        mock_client.list_notes.assert_called_once_with("default")

    @patch("server.mcp.tools.notes.get_client")
    def test_list_notes_empty(self, mock_get_client):
        """list_notes returns empty list when no notes exist."""
        mock_client = MagicMock()
        mock_client.list_notes.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import list_notes

        result = list_notes(workspace_id="empty-ws")

        mock_client.list_notes.assert_called_once_with("empty-ws")
        assert result == []

    @patch("server.mcp.tools.notes.get_client")
    def test_list_notes_propagates_error(self, mock_get_client):
        """list_notes propagates exceptions from the client."""
        mock_client = MagicMock()
        mock_client.list_notes.side_effect = ConnectionError("DB connection lost")
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import list_notes

        with pytest.raises(ConnectionError, match="DB connection lost"):
            list_notes("ws")

        mock_client.list_notes.assert_called_once_with("ws")


@pytest.mark.unit
class TestGetNoteByTitle:
    """Tests for the ``get_note_by_title`` tool."""

    @patch("server.mcp.tools.notes.get_client")
    def test_get_note_by_title(self, mock_get_client):
        """get_note_by_title delegates to get_client().get_note_by_title."""
        mock_client = MagicMock()
        expected = [{"id": "n1", "title": "My Note"}]
        mock_client.get_note_by_title.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_note_by_title

        result = get_note_by_title(title="My Note")

        mock_client.get_note_by_title.assert_called_once_with("My Note")
        assert result == expected

    @patch("server.mcp.tools.notes.get_client")
    def test_get_note_by_title_not_found(self, mock_get_client):
        """get_note_by_title returns empty list when no match."""
        mock_client = MagicMock()
        mock_client.get_note_by_title.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_note_by_title

        result = get_note_by_title(title="Does Not Exist")

        mock_client.get_note_by_title.assert_called_once_with("Does Not Exist")
        assert result == []

    @patch("server.mcp.tools.notes.get_client")
    def test_get_note_by_title_propagates_error(self, mock_get_client):
        """get_note_by_title propagates exceptions from the client."""
        mock_client = MagicMock()
        mock_client.get_note_by_title.side_effect = RuntimeError("Search failed")
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_note_by_title

        with pytest.raises(RuntimeError, match="Search failed"):
            get_note_by_title("bad")

        mock_client.get_note_by_title.assert_called_once_with("bad")


@pytest.mark.unit
class TestGetNoteByDate:
    """Tests for the ``get_note_by_date`` tool."""

    @patch("server.mcp.tools.notes.get_client")
    def test_get_note_by_date(self, mock_get_client):
        """get_note_by_date delegates to get_client().get_note_by_date."""
        mock_client = MagicMock()
        expected = [{"id": "n1", "note_date": "2026-06-26"}]
        mock_client.get_note_by_date.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_note_by_date

        result = get_note_by_date(note_date="2026-06-26")

        mock_client.get_note_by_date.assert_called_once_with("2026-06-26")
        assert result == expected

    @patch("server.mcp.tools.notes.get_client")
    def test_get_note_by_date_empty_result(self, mock_get_client):
        """get_note_by_date returns empty list when no notes for date."""
        mock_client = MagicMock()
        mock_client.get_note_by_date.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_note_by_date

        result = get_note_by_date(note_date="2099-01-01")

        mock_client.get_note_by_date.assert_called_once_with("2099-01-01")
        assert result == []

    @patch("server.mcp.tools.notes.get_client")
    def test_get_note_by_date_propagates_error(self, mock_get_client):
        """get_note_by_date propagates exceptions from the client."""
        mock_client = MagicMock()
        mock_client.get_note_by_date.side_effect = ValueError("Bad date format")
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_note_by_date

        with pytest.raises(ValueError, match="Bad date format"):
            get_note_by_date("not-a-date")

        mock_client.get_note_by_date.assert_called_once_with("not-a-date")


@pytest.mark.unit
class TestGetNoteHistory:
    """Tests for the ``get_note_history`` tool."""

    @patch("server.mcp.tools.notes.get_client")
    def test_get_note_history(self, mock_get_client):
        """get_note_history delegates to get_client().get_note_history."""
        mock_client = MagicMock()
        expected = [{"version": 1}, {"version": 2}]
        mock_client.get_note_history.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_note_history

        result = get_note_history(note_id="note-001")

        mock_client.get_note_history.assert_called_once_with("note-001")
        assert result == expected

    @patch("server.mcp.tools.notes.get_client")
    def test_get_note_history_empty(self, mock_get_client):
        """get_note_history returns empty list for notes with no history."""
        mock_client = MagicMock()
        mock_client.get_note_history.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_note_history

        result = get_note_history(note_id="new-note")

        mock_client.get_note_history.assert_called_once_with("new-note")
        assert result == []

    @patch("server.mcp.tools.notes.get_client")
    def test_get_note_history_propagates_error(self, mock_get_client):
        """get_note_history propagates exceptions from the client."""
        mock_client = MagicMock()
        mock_client.get_note_history.side_effect = RuntimeError("History unavailable")
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_note_history

        with pytest.raises(RuntimeError, match="History unavailable"):
            get_note_history(note_id="bad")

        mock_client.get_note_history.assert_called_once_with("bad")


@pytest.mark.unit
class TestGetBacklinks:
    """Tests for the ``get_backlinks`` tool."""

    @patch("server.mcp.tools.notes.get_client")
    def test_get_backlinks(self, mock_get_client):
        """get_backlinks delegates to get_client().get_backlinks."""
        mock_client = MagicMock()
        expected = [{"note_id": "n2", "title": "Referrer"}]
        mock_client.get_backlinks.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_backlinks

        result = get_backlinks(note_id="note-001")

        mock_client.get_backlinks.assert_called_once_with("note-001")
        assert result == expected

    @patch("server.mcp.tools.notes.get_client")
    def test_get_backlinks_empty(self, mock_get_client):
        """get_backlinks returns empty list when no backlinks exist."""
        mock_client = MagicMock()
        mock_client.get_backlinks.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_backlinks

        result = get_backlinks(note_id="orphan-note")

        mock_client.get_backlinks.assert_called_once_with("orphan-note")
        assert result == []

    @patch("server.mcp.tools.notes.get_client")
    def test_get_backlinks_propagates_error(self, mock_get_client):
        """get_backlinks propagates exceptions from the client."""
        mock_client = MagicMock()
        mock_client.get_backlinks.side_effect = RuntimeError("Backlink query failed")
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_backlinks

        with pytest.raises(RuntimeError, match="Backlink query failed"):
            get_backlinks(note_id="bad")

        mock_client.get_backlinks.assert_called_once_with("bad")


@pytest.mark.unit
class TestGetOutgoingLinks:
    """Tests for the ``get_outgoing_links`` tool."""

    @patch("server.mcp.tools.notes.get_client")
    def test_get_outgoing_links(self, mock_get_client):
        """get_outgoing_links delegates to get_client().get_outgoing_links."""
        mock_client = MagicMock()
        expected = [{"target_note_id": "n2", "title": "Linked Note"}]
        mock_client.get_outgoing_links.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_outgoing_links

        result = get_outgoing_links(note_id="note-001")

        mock_client.get_outgoing_links.assert_called_once_with("note-001")
        assert result == expected

    @patch("server.mcp.tools.notes.get_client")
    def test_get_outgoing_links_empty(self, mock_get_client):
        """get_outgoing_links returns empty list when no outgoing links."""
        mock_client = MagicMock()
        mock_client.get_outgoing_links.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_outgoing_links

        result = get_outgoing_links(note_id="dead-end")

        mock_client.get_outgoing_links.assert_called_once_with("dead-end")
        assert result == []

    @patch("server.mcp.tools.notes.get_client")
    def test_get_outgoing_links_propagates_error(self, mock_get_client):
        """get_outgoing_links propagates exceptions from the client."""
        mock_client = MagicMock()
        mock_client.get_outgoing_links.side_effect = RuntimeError("Links query failed")
        mock_get_client.return_value = mock_client

        from server.mcp.tools.notes import get_outgoing_links

        with pytest.raises(RuntimeError, match="Links query failed"):
            get_outgoing_links(note_id="bad")

        mock_client.get_outgoing_links.assert_called_once_with("bad")
