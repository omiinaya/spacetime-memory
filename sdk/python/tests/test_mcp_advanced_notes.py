"""Tests for MCP tools — split from test_mcp_advanced.py."""

import pytest

pytest.skip("requires MCP server runtime (server/mcp/)", allow_module_level=True)

class TestCreateNote:
    """Tests for the create_note MCP tool."""

    def test_creates_note(self, mock_mcp_client):
        from server.mcp.main import create_note

        mock_mcp_client.create_note.return_value = {"id": "note1", "title": "Test"}
        result = create_note(workspace_id="ws1", title="Test", content="Hello")
        assert result["title"] == "Test"
        mock_mcp_client.create_note.assert_called_once_with(
            workspace_id="ws1",
            title="Test",
            content="Hello",
            note_date="",
            embed=True,
        )

    def test_with_date_and_no_embed(self, mock_mcp_client):
        from server.mcp.main import create_note

        mock_mcp_client.create_note.return_value = {"id": "n2"}
        create_note(
            workspace_id="ws1",
            title="Dated",
            content="Content",
            note_date="2026-07-23",
            embed=False,
        )
        mock_mcp_client.create_note.assert_called_once_with(
            workspace_id="ws1",
            title="Dated",
            content="Content",
            note_date="2026-07-23",
            embed=False,
        )



# ── TestGetNote ────────────────────────────────────────────────────────

class TestGetNote:
    """Tests for the get_note MCP tool."""

    def test_gets_note(self, mock_mcp_client):
        from server.mcp.main import get_note

        mock_mcp_client.get_note.return_value = [{"id": "n1", "title": "Test"}]
        result = get_note(note_id="n1")
        assert result[0]["title"] == "Test"
        mock_mcp_client.get_note.assert_called_once_with("n1")



# ── TestUpdateNote ────────────────────────────────────────────────────────

class TestUpdateNote:
    """Tests for the update_note MCP tool."""

    def test_updates_note(self, mock_mcp_client):
        from server.mcp.main import update_note

        mock_mcp_client.update_note.return_value = {"status": "ok"}
        result = update_note(note_id="n1", title="Updated", content="New content")
        assert result["status"] == "ok"
        mock_mcp_client.update_note.assert_called_once_with(
            note_id="n1",
            title="Updated",
            content="New content",
            embed=True,
        )



# ── TestDeleteNote ────────────────────────────────────────────────────────

class TestDeleteNote:
    """Tests for the delete_note MCP tool."""

    def test_deletes(self, mock_mcp_client):
        from server.mcp.main import delete_note

        mock_mcp_client.delete_note.return_value = {"status": "ok"}
        result = delete_note(note_id="n1")
        assert result["status"] == "ok"
        mock_mcp_client.delete_note.assert_called_once_with("n1")



# ── TestListNotes ────────────────────────────────────────────────────────

class TestListNotes:
    """Tests for the list_notes MCP tool."""

    def test_lists(self, mock_mcp_client):
        from server.mcp.main import list_notes

        mock_mcp_client.list_notes.return_value = [
            {"id": "n1", "title": "Note 1"},
        ]
        result = list_notes(workspace_id="ws1")
        assert len(result) == 1
        mock_mcp_client.list_notes.assert_called_once_with("ws1")

    def test_default_workspace(self, mock_mcp_client):
        from server.mcp.main import list_notes

        mock_mcp_client.list_notes.return_value = []
        list_notes()
        mock_mcp_client.list_notes.assert_called_once_with("default")



# ── TestGetNoteByTitle ────────────────────────────────────────────────────────

class TestGetNoteByTitle:
    """Tests for the get_note_by_title MCP tool."""

    def test_gets_by_title(self, mock_mcp_client):
        from server.mcp.main import get_note_by_title

        mock_mcp_client.get_note_by_title.return_value = [
            {"id": "n1", "title": "My Note"},
        ]
        result = get_note_by_title(title="My Note")
        assert result[0]["title"] == "My Note"
        mock_mcp_client.get_note_by_title.assert_called_once_with("My Note")



# ── TestGetNoteHistory ────────────────────────────────────────────────────────

class TestGetNoteHistory:
    """Tests for the get_note_history MCP tool."""

    def test_gets_history(self, mock_mcp_client):
        from server.mcp.main import get_note_history

        mock_mcp_client.get_note_history.return_value = [
            {"version": 1, "title": "v1"},
        ]
        result = get_note_history(note_id="n1")
        assert len(result) == 1
        mock_mcp_client.get_note_history.assert_called_once_with("n1")



# ── TestGetBacklinks ────────────────────────────────────────────────────────

class TestGetBacklinks:
    """Tests for the get_backlinks MCP tool."""

    def test_gets_backlinks(self, mock_mcp_client):
        from server.mcp.main import get_backlinks

        mock_mcp_client.get_backlinks.return_value = [
            {"note_id": "n1", "title": "Source"},
        ]
        result = get_backlinks(note_id="n1")
        assert len(result) == 1
        mock_mcp_client.get_backlinks.assert_called_once_with("n1")



# ── TestGetOutgoingLinks ────────────────────────────────────────────────────────

class TestGetOutgoingLinks:
    """Tests for the get_outgoing_links MCP tool."""

    def test_gets_outgoing(self, mock_mcp_client):
        from server.mcp.main import get_outgoing_links

        mock_mcp_client.get_outgoing_links.return_value = [
            {"note_id": "n1", "target_title": "Target"},
        ]
        result = get_outgoing_links(note_id="n1")
        assert len(result) == 1
        mock_mcp_client.get_outgoing_links.assert_called_once_with("n1")


# ── Document tools ────────────────────────────────────────────────────────



# ── TestCreateNoteDefaults ────────────────────────────────────────────────────────

class TestCreateNoteDefaults:
    """Tests for the create_note MCP tool."""

    def test_creates_note(self, mock_mcp_client):
        from server.mcp.main import create_note

        mock_mcp_client.create_note.return_value = {
            "id": "note-1", "title": "Test Note", "status": "created"
        }
        result = create_note(
            workspace_id="ws-1",
            title="Test Note",
            content="This is a test note.",
            note_date="2026-07-23",
            embed=True,
        )
        assert result["title"] == "Test Note"
        mock_mcp_client.create_note.assert_called_once_with(
            workspace_id="ws-1",
            title="Test Note",
            content="This is a test note.",
            note_date="2026-07-23",
            embed=True,
        )

    def test_creates_with_defaults(self, mock_mcp_client):
        from server.mcp.main import create_note

        mock_mcp_client.create_note.return_value = {
            "id": "note-2", "title": "Minimal", "status": "created"
        }
        result = create_note(title="Minimal", content="Just content")
        assert result["title"] == "Minimal"
        call_kw = mock_mcp_client.create_note.call_args[1]
        assert call_kw["workspace_id"] == "default"
        assert call_kw["embed"] is True


# ── get_note (uses get_client directly) ────────────────────────────────────



# ── TestGetNoteEmpty ────────────────────────────────────────────────────────

class TestGetNoteEmpty:
    """Tests for the get_note MCP tool."""

    def test_gets_note(self, mock_mcp_client):
        from server.mcp.main import get_note

        mock_mcp_client.get_note.return_value = [
            {"id": "n1", "title": "My Note", "content": "Hello"}
        ]
        result = get_note(note_id="n1")
        assert len(result) == 1
        assert result[0]["title"] == "My Note"
        mock_mcp_client.get_note.assert_called_once_with("n1")

    def test_empty_result(self, mock_mcp_client):
        from server.mcp.main import get_note

        mock_mcp_client.get_note.return_value = []
        result = get_note(note_id="nonexistent")
        assert result == []


# ── delete_workspace (uses get_client directly) ────────────────────────────
