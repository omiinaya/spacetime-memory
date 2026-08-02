"""Tests for server/mcp/tools/notes.py - Note-specific MCP tools."""
import pytest
from server.mcp.tools.notes import (
    create_note, get_note, delete_note, update_note,
    list_notes, get_note_by_title, get_note_by_date,
    get_note_history, get_backlinks, get_outgoing_links,
)


class TestNotesModule:
    """Test suite for notes.py - verify all expected exports exist."""

    def test_create_note_exists(self):
        """create_note should be callable."""
        assert callable(create_note)

    def test_get_note_exists(self):
        """get_note should be callable."""
        assert callable(get_note)

    def test_delete_note_exists(self):
        """delete_note should be callable."""
        assert callable(delete_note)

    def test_update_note_exists(self):
        """update_note should be callable."""
        assert callable(update_note)

    def test_list_notes_exists(self):
        """list_notes should be callable."""
        assert callable(list_notes)

    def test_get_note_by_title_exists(self):
        """get_note_by_title should be callable."""
        assert callable(get_note_by_title)

    def test_get_note_by_date_exists(self):
        """get_note_by_date should be callable."""
        assert callable(get_note_by_date)

    def test_get_note_history_exists(self):
        """get_note_history should be callable."""
        assert callable(get_note_history)

    def test_get_backlinks_exists(self):
        """get_backlinks should be callable."""
        assert callable(get_backlinks)

    def test_get_outgoing_links_exists(self):
        """get_outgoing_links should be callable."""
        assert callable(get_outgoing_links)
