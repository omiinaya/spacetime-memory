"""Dedicated RssFeedConnector tests.

Augments the RSS tests in test_connectors.py with comprehensive
edge case coverage: empty feeds, missing IDs, Atom feeds,
maximum entries per poll, cursor persistence, and error handling.

All tests use mock feedparser — no live network calls.
"""

import json
import os
import shutil
from unittest.mock import MagicMock, patch

import pytest

# Clean cursor directory before tests
_conn_base_dir = os.path.expanduser("~/.spacetime-memory/connectors")
if os.path.exists(_conn_base_dir):
    shutil.rmtree(_conn_base_dir, ignore_errors=True)

from spacetime_memory.connectors import Event, RssFeedConnector


@pytest.fixture(autouse=True)
def _isolated_cursor_dir(tmp_path, monkeypatch):
    """Each test gets an isolated cursor directory.

    Prevents cascading cursor-pollution failures: connector tests that
    do NOT pass an explicit ``cursor_dir`` all share the default global
    path ``~/.spacetime-memory/connectors/``.  When one test calls
    ``poll()`` the saved cursor leaks into the next test.
    """
    cursor_dir = str(tmp_path / "connectors")
    os.makedirs(cursor_dir, exist_ok=True)
    import spacetime_memory.connectors._base as _base_mod
    monkeypatch.setattr(_base_mod.os.path, "expanduser", lambda _: cursor_dir)


def _make_fake_entry(
    entry_id: str | None = None,
    title: str = "",
    summary: str = "",
    link: str = "",
) -> dict:
    """Build a fake feedparser entry dict."""
    entry: dict = {}
    if entry_id is not None:
        entry["id"] = entry_id
    if title:
        entry["title"] = title
    if summary:
        entry["summary"] = summary
    if link:
        entry["link"] = link
    return entry


def _make_mock_feed(entries: list[dict]) -> MagicMock:
    """Build a mock feedparser.parse() return value."""
    mock = MagicMock()
    mock.entries = entries
    mock.bozo = False
    mock.feed = {}
    return mock


class TestRssInit:
    """Constructor edge cases."""

    def test_init_defaults(self):
        """Default peer_id is 'rss-bot'."""
        c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
        assert c.feed_url == "https://example.com/feed"
        assert c.workspace_id == "ws-1"
        assert c.peer_id == "rss-bot"
        assert c._seen == set()

    def test_init_custom_peer_id(self):
        """Custom peer_id is respected."""
        c = RssFeedConnector(
            feed_url="https://example.com/feed",
            workspace_id="ws-1",
            peer_id="my-rss",
        )
        assert c.peer_id == "my-rss"

    def test_init_cursor_restores_seen(self):
        """Cursor persisted _seen IDs are restored on init."""
        cursor_dir = os.path.join(_conn_base_dir, "rss_cursor_test")
        os.makedirs(cursor_dir, exist_ok=True)
        cursor_file = os.path.join(cursor_dir, "RssFeedConnector_cursor.json")
        with open(cursor_file, "w") as f:
            json.dump({"seen_ids": ["old-1", "old-2"]}, f)

        c = RssFeedConnector(
            feed_url="https://example.com/feed",
            workspace_id="ws-1",
            cursor_dir=cursor_dir,
        )
        assert "old-1" in c._seen
        assert "old-2" in c._seen

        shutil.rmtree(cursor_dir, ignore_errors=True)


class TestRssPoll:
    """Poll behavior."""

    def test_single_entry(self):
        """Single entry creates one Event with correct fields."""
        with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([
            _make_fake_entry(entry_id="e1", title="T1", summary="S1", link="https://ex.com/1"),
        ])):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            events = c.poll()

        assert len(events) == 1
        assert isinstance(events[0], Event)
        assert events[0].workspace_id == "ws-1"
        assert events[0].peer_id == "rss-bot"
        assert events[0].summary == "T1"
        assert "T1" in events[0].content
        assert "S1" in events[0].content
        assert "https://ex.com/1" in events[0].content

    def test_multiple_entries(self):
        """Multiple entries produce multiple events."""
        entries = [
            _make_fake_entry(entry_id=f"e{i}", title=f"Title {i}", summary=f"Body {i}")
            for i in range(5)
        ]
        with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed(entries)):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            events = c.poll()

        assert len(events) == 5
        assert events[2].summary == "Title 2"

    def test_deduplication(self):
        """Same entry on second poll is skipped."""
        entry = _make_fake_entry(entry_id="e1", title="Dupe", summary="Same")
        with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([entry])):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            first = c.poll()
            second = c.poll()

        assert len(first) == 1
        assert len(second) == 0

    def test_max_10_entries(self):
        """Maximum 10 entries per poll."""
        entries = [
            _make_fake_entry(entry_id=f"e{i}", title=f"E{i}")
            for i in range(20)
        ]
        with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed(entries)):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            events = c.poll()

        assert len(events) == 10

    def test_empty_feed(self):
        """Empty feed returns empty list."""
        with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([])):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            events = c.poll()

        assert events == []

    def test_no_entries_key(self):
        """Feed with no 'entries' key is handled."""
        mock = MagicMock()
        del mock.entries  # Simulate no entries attribute
        mock.bozo = False
        mock.feed = {}

        with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=mock):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            events = c.poll()
        assert events == []


class TestRssEntryFields:
    """Edge cases for entry fields."""

    def test_entry_no_id_fallback_to_link(self):
        """When id is missing, uses link for dedup."""
        entry = _make_fake_entry(title="No ID", summary="Body", link="https://ex.com/no-id")
        # Ensure no 'id' key
        entry.pop("id", None)

        with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([entry])):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            events = c.poll()

        assert len(events) == 1

    def test_entry_no_id_no_link(self):
        """When both id and link are missing, entry is still processed."""
        entry = _make_fake_entry(title="Bare", summary="No identifiers")
        entry.pop("id", None)
        entry["link"] = ""  # Empty link

        with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([entry])):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            events = c.poll()

        assert len(events) == 1

    def test_entry_no_title(self):
        """Entry without title uses empty string for title."""
        entry = _make_fake_entry(entry_id="e1", summary="Just body")
        with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([entry])):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            events = c.poll()

        assert len(events) == 1
        assert events[0].content.startswith("\n\n")

    def test_entry_fallback_to_description(self):
        """When summary is missing, falls back to description."""
        entry = {
            "id": "e1",
            "title": "Fallback",
            "description": "Description body",
            "link": "https://ex.com/desc",
        }
        with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([entry])):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            events = c.poll()

        assert len(events) == 1
        assert "Description body" in events[0].content

    def test_atom_entry_format(self):
        """Atom feed entries have the same dict structure."""
        entry = _make_fake_entry(entry_id="atom-1", title="Atom Entry", summary="Atom summary")
        with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([entry])):
            c = RssFeedConnector(feed_url="https://example.com/atom.xml", workspace_id="ws-1")
            events = c.poll()

        assert len(events) == 1
        assert events[0].summary == "Atom Entry"

    def test_entry_with_html_in_summary(self):
        """HTML in summary is preserved in content."""
        entry = _make_fake_entry(
            entry_id="e1",
            title="HTML Entry",
            summary="<p>Paragraph with <b>bold</b> text</p>",
        )
        with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([entry])):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            events = c.poll()

        assert len(events) == 1
        assert "<p>" in events[0].content
        assert "<b>" in events[0].content

    def test_content_format(self):
        """Content includes title, body, and source link."""
        entry = _make_fake_entry(
            entry_id="e1",
            title="My Title",
            summary="My Body",
            link="https://ex.com/link",
        )
        with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([entry])):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            events = c.poll()

        content = events[0].content
        assert "My Title" in content
        assert "My Body" in content
        assert "https://ex.com/link" in content

    def test_entry_no_title_no_summary(self):
        """Entry with only link creates minimal content."""
        entry = {"id": "e1", "link": "https://ex.com/minimal"}
        with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([entry])):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            events = c.poll()

        assert len(events) == 1

    def test_entry_unicode_content(self):
        """Unicode in title/summary is preserved."""
        entry = _make_fake_entry(
            entry_id="e1",
            title="日本語タイトル",
            summary="über cool résumé",
        )
        with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([entry])):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            events = c.poll()

        assert len(events) == 1
        assert "日本語" in events[0].content
        assert "über" in events[0].content


class TestRssCursorPersistence:
    """Cursor state persists between poll calls."""

    def test_seen_tracked_in_memory(self):
        """Seen IDs are tracked in local _seen set after poll."""
        entry = _make_fake_entry(entry_id="e1", title="Test")
        with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([entry])):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            c.poll()

        assert "e1" in c._seen

    def test_cursor_saved_to_disk(self):
        """Cursor _seen IDs are saved to disk after poll."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            entry = _make_fake_entry(entry_id="persist-1", title="Persist")
            with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([entry])):
                c = RssFeedConnector(
                    feed_url="https://example.com/feed",
                    workspace_id="ws-1",
                    cursor_dir=tmpdir,
                )
                c.poll()

            cursor_file = tmpdir + "/RssFeedConnector_cursor.json"
            assert os.path.exists(cursor_file)
            with open(cursor_file) as f:
                data = json.load(f)
            assert "persist-1" in data["seen_ids"]

    def test_cursor_restored_on_new_instance(self):
        """New instance with same cursor dir restores seen IDs."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # First instance
            entry = _make_fake_entry(entry_id="restore-1", title="Restore")
            with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([entry])):
                c1 = RssFeedConnector(
                    feed_url="https://example.com/feed",
                    workspace_id="ws-1",
                    cursor_dir=tmpdir,
                )
                c1.poll()

            # Second instance with same cursor dir
            with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([entry])):
                c2 = RssFeedConnector(
                    feed_url="https://example.com/feed",
                    workspace_id="ws-1",
                    cursor_dir=tmpdir,
                )
                events = c2.poll()

            assert len(events) == 0  # Already seen

    def test_new_entries_after_restore(self):
        """New entries are processed even after restoring old seen IDs."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            entry1 = _make_fake_entry(entry_id="old-1", title="Old")
            with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([entry1])):
                c1 = RssFeedConnector(
                    feed_url="https://example.com/feed",
                    workspace_id="ws-1",
                    cursor_dir=tmpdir,
                )
                c1.poll()

            entry2 = _make_fake_entry(entry_id="new-1", title="New")
            with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=_make_mock_feed([entry2])):
                c2 = RssFeedConnector(
                    feed_url="https://example.com/feed",
                    workspace_id="ws-1",
                    cursor_dir=tmpdir,
                )
                events = c2.poll()

            assert len(events) == 1
            assert events[0].summary == "New"


class TestRssPollErrorHandling:
    """Poll error handling."""

    def test_feedparser_network_error(self):
        """Network error (connection failed) returns empty list."""
        with patch("spacetime_memory.connectors._rss.feedparser.parse", side_effect=OSError("Connection refused")):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            events = c.poll()

        assert events == []

    def test_feedparser_timeout(self):
        """Timeout returns empty list."""
        with patch("spacetime_memory.connectors._rss.feedparser.parse", side_effect=TimeoutError("timed out")):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            events = c.poll()

        assert events == []

    def test_feedparser_no_connection(self):
        """Any other feedparser exception returns empty list."""
        with patch("spacetime_memory.connectors._rss.feedparser.parse", side_effect=Exception("unexpected")):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            events = c.poll()

        assert events == []

    def test_malformed_feed_xml(self):
        """Malformed XML returns bozo=True but no entries."""
        mock = MagicMock()
        mock.entries = []
        mock.bozo = True
        mock.bozo_exception = "syntax error"
        mock.feed = {}

        with patch("spacetime_memory.connectors._rss.feedparser.parse", return_value=mock):
            c = RssFeedConnector(feed_url="https://example.com/feed", workspace_id="ws-1")
            events = c.poll()

        assert events == []
