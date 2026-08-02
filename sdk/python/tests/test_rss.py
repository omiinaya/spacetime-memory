"""Tests for spacetime_memory.connectors._rss — RssFeedConnector.

Tests use mocked feedparser responses. No real network calls.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestRssFeedConnector:
    """RSS/Atom feed connector that polls URLs and stores entries as memories."""

    @pytest.fixture
    def connector(self, tmp_path):
        from spacetime_memory.connectors._rss import RssFeedConnector

        conn = RssFeedConnector(
            feed_url="https://example.com/feed.xml",
            workspace_id="ws-1",
            peer_id="rss-bot",
            cursor_dir=str(tmp_path),
        )
        return conn

    def test_init_sets_attributes(self, connector):
        assert connector.feed_url == "https://example.com/feed.xml"
        assert connector.workspace_id == "ws-1"
        assert connector.peer_id == "rss-bot"
        assert hasattr(connector, "_seen")

    def test_poll_returns_events_for_new_entries(self, connector):
        mock_entry = MagicMock()
        mock_entry.id = "entry-1"
        mock_entry.link = "https://example.com/1"
        mock_entry.title = "Test Entry"
        mock_entry.summary = "This is a test entry"
        mock_entry.get = lambda key, default="": {
            "id": "entry-1",
            "link": "https://example.com/1",
            "title": "Test Entry",
            "summary": "This is a test entry",
            "description": "",
        }.get(key, default)

        mock_parsed = MagicMock()
        mock_parsed.bozo = False
        mock_parsed.entries = [mock_entry]

        with patch("feedparser.parse", return_value=mock_parsed):
            events = connector.poll()

        assert len(events) == 1
        assert events[0].content.startswith("Test Entry")
        assert "This is a test entry" in events[0].content
        assert events[0].workspace_id == "ws-1"
        assert events[0].memory_type == "experience"
        assert events[0].peer_id == "rss-bot"

    def test_poll_deduplicates_entries(self, connector):
        mock_entry = MagicMock()
        mock_entry.id = "entry-1"
        mock_entry.link = ""
        mock_entry.title = "Test Entry"
        mock_entry.summary = "Content"
        mock_entry.get = lambda key, default="": {
            "id": "entry-1",
            "link": "",
            "title": "Test Entry",
            "summary": "Content",
            "description": "",
        }.get(key, default)

        mock_parsed = MagicMock()
        mock_parsed.bozo = False
        mock_parsed.entries = [mock_entry]

        with patch("feedparser.parse", return_value=mock_parsed):
            first = connector.poll()
            second = connector.poll()

        assert len(first) == 1
        assert len(second) == 0  # duplicate, already seen

    def test_poll_bozo_error_returns_empty(self, connector):
        mock_parsed = MagicMock()
        mock_parsed.bozo = True
        mock_parsed.bozo_exception = "Bad XML"
        mock_parsed.entries = []

        with patch("feedparser.parse", return_value=mock_parsed):
            events = connector.poll()

        assert events == []

    def test_poll_empty_feed_returns_empty(self, connector):
        mock_parsed = MagicMock()
        mock_parsed.bozo = False
        mock_parsed.entries = []

        with patch("feedparser.parse", return_value=mock_parsed):
            events = connector.poll()

        assert events == []

    def test_poll_max_10_entries(self, connector):
        entries = []
        for i in range(15):
            entry = MagicMock()
            entry.id = f"entry-{i}"
            entry.link = f"https://example.com/{i}"
            entry.title = f"Entry {i}"
            entry.summary = f"Content {i}"
            entry.get = lambda key, default="", i=i: {
                "id": f"entry-{i}",
                "link": f"https://example.com/{i}",
                "title": f"Entry {i}",
                "summary": f"Content {i}",
                "description": "",
            }.get(key, default)
            entries.append(entry)

        mock_parsed = MagicMock()
        mock_parsed.bozo = False
        mock_parsed.entries = entries

        with patch("feedparser.parse", return_value=mock_parsed):
            events = connector.poll()

        assert len(events) == 10  # capped at 10

    def test_poll_parse_exception_returns_empty(self, connector):
        with patch("feedparser.parse", side_effect=Exception("Network error")):
            events = connector.poll()

        assert events == []

    def test_poll_uses_link_as_fallback_id(self, connector):
        mock_entry = MagicMock()
        mock_entry.id = ""
        mock_entry.link = "https://example.com/unique-link"
        mock_entry.title = "No ID"
        mock_entry.summary = "Fallback"
        mock_entry.get = lambda key, default="": {
            "id": "",
            "link": "https://example.com/unique-link",
            "title": "No ID",
            "summary": "Fallback",
            "description": "",
        }.get(key, default)

        mock_parsed = MagicMock()
        mock_parsed.bozo = False
        mock_parsed.entries = [mock_entry]

        with patch("feedparser.parse", return_value=mock_parsed):
            events = connector.poll()

        assert len(events) == 1

    def test_poll_persists_cursor(self, connector):
        mock_entry = MagicMock()
        mock_entry.id = "entry-1"
        mock_entry.link = ""
        mock_entry.title = "T"
        mock_entry.summary = "C"
        mock_entry.get = lambda key, default="": {
            "id": "entry-1",
            "link": "",
            "title": "T",
            "summary": "C",
            "description": "",
        }.get(key, default)

        mock_parsed = MagicMock()
        mock_parsed.bozo = False
        mock_parsed.entries = [mock_entry]

        with patch("feedparser.parse", return_value=mock_parsed):
            connector.poll()

        assert "seen_ids" in connector._cursor
        assert "entry-1" in connector._cursor["seen_ids"]

    def test_description_fallback(self, connector):
        """When summary is absent, uses description."""
        mock_entry = MagicMock()
        mock_entry.id = "entry-desc"
        mock_entry.link = ""
        mock_entry.title = "Desc"
        mock_entry.description = "Description fallback"
        mock_entry.get = lambda key, default="": {
            "id": "entry-desc",
            "link": "",
            "title": "Desc",
            "description": "Description fallback",
        }.get(key, default)

        mock_parsed = MagicMock()
        mock_parsed.bozo = False
        mock_parsed.entries = [mock_entry]

        with patch("feedparser.parse", return_value=mock_parsed):
            events = connector.poll()

        assert len(events) == 1
        assert "Description fallback" in events[0].content

    def test_cursor_dir_passed_to_super(self, tmp_path):
        from spacetime_memory.connectors._rss import RssFeedConnector

        conn = RssFeedConnector(
            feed_url="https://example.com/feed.xml",
            workspace_id="ws-1",
            cursor_dir=str(tmp_path),
        )
        assert conn._cursor_dir == str(tmp_path)
