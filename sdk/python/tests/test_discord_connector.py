"""Tests for DiscordConnector — mock-based HTTP tests.

Covers: poll(), _fetch_messages, _fetch_channel_info, _resolve_emoji,
_msg_to_event, threads, attachments, rate limiting, error handling.
"""

import os as _os
import shutil as _shutil
from unittest.mock import Mock, patch

_conn_cursor_dir = _os.path.expanduser("~/.spacetime-memory/connectors")
if _os.path.exists(_conn_cursor_dir):
    _shutil.rmtree(_conn_cursor_dir, ignore_errors=True)

from spacetime_memory.connectors import (
    DiscordConnector,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _make_msg(
    msg_id,
    content="test",
    author_name="tester",
    author_id="auth-1",
    timestamp="2024-01-01T00:00:00Z",
    guild_id=None,
    attachments=None,
    thread=None,
):
    """Build a Discord message dict for test assertions."""
    msg = {
        "id": msg_id,
        "content": content,
        "author": {"username": author_name, "id": author_id},
        "timestamp": timestamp,
    }
    if guild_id:
        msg["guild_id"] = guild_id
    if attachments:
        msg["attachments"] = attachments
    if thread:
        msg["thread"] = thread
    return msg


# ── Message to Event ─────────────────────────────────────────────────


class TestDiscordMsgToEvent:
    """_msg_to_event conversion and edge cases."""

    def test_deduplication(self):
        """Second call with same msg_id returns None."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
            decode_emoji=False,
        )
        msg = _make_msg("m1", "hello")
        ev1 = connector._msg_to_event(msg, "c1")
        assert ev1 is not None
        ev2 = connector._msg_to_event(msg, "c1")
        assert ev2 is None

    def test_attachments_in_metadata(self):
        """Attachments appear in metadata."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
            decode_emoji=False,
        )
        msg = _make_msg(
            "m2",
            "image",
            attachments=[
                {"url": "https://cdn.discord.com/img.png"},
                {"url": ""},  # empty URL should be filtered
                {},  # no url key
            ],
        )
        ev = connector._msg_to_event(msg, "c1")
        assert ev is not None
        assert "attachments" in ev.metadata
        # Only the first attachment with a real URL should survive
        assert any("img.png" in u for u in ev.metadata.get("attachments", []))

    def test_thread_metadata(self):
        """Thread info is attached to metadata."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
            decode_emoji=False,
        )
        msg = _make_msg(
            "m3",
            "threaded",
            thread={
                "id": "thread-1",
                "name": "cool-thread",
            },
        )
        ev = connector._msg_to_event(msg, "c1")
        assert ev is not None
        assert ev.metadata["thread_id"] == "thread-1"
        assert ev.metadata["thread_name"] == "cool-thread"

    def test_emoji_decode_enabled(self):
        """When decode_emoji=True, _resolve_emoji is called."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
            decode_emoji=True,
        )
        msg = _make_msg("m4", ":wave: hello", guild_id="guild-1")
        # Emoji pattern :wave: will be checked against empty cache,
        # should remain unchanged since we can't resolve it.
        ev = connector._msg_to_event(msg, "c1")
        assert ev is not None
        # The content should still contain :wave: (unchanged)
        assert ":wave:" in ev.content

    def test_missing_author_defaults(self):
        """Missing author fields use defaults."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
            decode_emoji=False,
        )
        msg = {"id": "m5", "content": "bare", "timestamp": ""}
        ev = connector._msg_to_event(msg, "c1")
        assert ev is not None
        assert ev.metadata["author"] == "unknown"
        assert ev.metadata["author_id"] == ""

    def test_no_content(self):
        """Message with no content field still creates an event."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
            decode_emoji=False,
        )
        msg = {"id": "m6", "author": {"username": "u"}, "timestamp": "t"}
        ev = connector._msg_to_event(msg, "c1")
        assert ev is not None
        assert ev.content == ""


# ── Fetch Messages ───────────────────────────────────────────────────


class TestDiscordFetchMessages:
    """_fetch_messages pagination and error handling."""

    def test_single_page(self):
        """One page of messages is returned."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
        )
        resp = Mock(status_code=200)
        resp.json.return_value = [_make_msg("a", "hi")]
        client = Mock()
        client.get.return_value = resp

        msgs = connector._fetch_messages(client, "c1", {})
        assert len(msgs) == 1
        assert msgs[0]["id"] == "a"

    def test_pagination_multiple_pages(self):
        """Paginates through multiple pages using 'before' param."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
        )
        # Page 1: 100 messages, last id = "msg-1"
        page1 = [_make_msg(f"page1-{i}", f"msg{i}") for i in range(100)]
        page1[-1]["id"] = "msg-1"  # oldest

        # Page 2: 50 messages (less than 100, stops pagination)
        page2 = [_make_msg(f"page2-{i}", f"msg2-{i}") for i in range(50)]

        resp1 = Mock(status_code=200)
        resp1.json.return_value = page1
        resp2 = Mock(status_code=200)
        resp2.json.return_value = page2

        client = Mock()
        client.get.side_effect = [resp1, resp2]

        msgs = connector._fetch_messages(client, "c1", {})
        assert len(msgs) == 150
        # Verify second call had 'before' param set to msg-1
        call_args = client.get.call_args_list[1]
        assert call_args[1]["params"]["before"] == "msg-1"

    def test_rate_limited_429(self):
        """429 rate limit breaks out of pagination loop."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
        )
        resp = Mock(status_code=429)
        resp.json.return_value = {"retry_after": 10.0}
        client = Mock()
        client.get.return_value = resp

        msgs = connector._fetch_messages(client, "c1", {})
        assert msgs == []

    def test_forbidden_403(self):
        """403 forbidden breaks out of pagination loop."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
        )
        resp = Mock(status_code=403)
        client = Mock()
        client.get.return_value = resp

        msgs = connector._fetch_messages(client, "c1", {})
        assert msgs == []

    def test_not_found_404_removes_channel(self):
        """404 removes channel from active list."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["c1", "c2"],
            workspace_id="ws",
        )
        resp = Mock(status_code=404)
        client = Mock()
        client.get.return_value = resp

        msgs = connector._fetch_messages(client, "c1", {})
        assert msgs == []
        assert "c1" not in connector.channel_ids
        assert "c2" in connector.channel_ids

    def test_unexpected_status(self):
        """Non-200/404/403/429 status breaks out."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
        )
        resp = Mock(status_code=500)
        client = Mock()
        client.get.return_value = resp

        msgs = connector._fetch_messages(client, "c1", {})
        assert msgs == []

    def test_request_error(self):
        """httpx.RequestError breaks out of pagination."""
        import httpx

        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
        )
        client = Mock()
        client.get.side_effect = httpx.RequestError("connection failed")

        msgs = connector._fetch_messages(client, "c1", {})
        assert msgs == []

    def test_empty_messages_stops_pagination(self):
        """Empty array from API stops pagination."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
        )
        resp = Mock(status_code=200)
        resp.json.return_value = []
        client = Mock()
        client.get.return_value = resp

        msgs = connector._fetch_messages(client, "c1", {})
        assert msgs == []

    def test_max_10_pages(self):
        """Paginates at most 10 pages (1000 messages max)."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
        )
        # Build 11 pages of 100 messages each — only 10 should be fetched
        responses = []
        for pg in range(11):
            page = [_make_msg(f"pg{pg}-{i}", "msg") for i in range(100)]
            page[-1]["id"] = f"last-pg{pg}"
            resp = Mock(status_code=200)
            resp.json.return_value = page
            responses.append(resp)

        client = Mock()
        client.get.side_effect = responses

        msgs = connector._fetch_messages(client, "c1", {})
        # 10 pages × 100 = 1000
        assert len(msgs) == 1000


# ── Fetch Channel Info ───────────────────────────────────────────────


class TestDiscordFetchChannelInfo:
    """_fetch_channel_info response handling."""

    def test_success_200(self):
        """Returns channel dict on 200."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
        )
        resp = Mock(status_code=200)
        resp.json.return_value = {"id": "1", "type": 0, "name": "general"}
        client = Mock()
        client.get.return_value = resp

        info = connector._fetch_channel_info(client, "1")
        assert info == {"id": "1", "type": 0, "name": "general"}

    def test_404_not_found(self):
        """Returns None and prints on 404."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
        )
        resp = Mock(status_code=404)
        client = Mock()
        client.get.return_value = resp

        info = connector._fetch_channel_info(client, "1")
        assert info is None

    def test_403_forbidden(self):
        """Returns None on 403."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
        )
        resp = Mock(status_code=403)
        client = Mock()
        client.get.return_value = resp

        info = connector._fetch_channel_info(client, "1")
        assert info is None

    def test_request_error(self):
        """Returns None on RequestError."""
        import httpx

        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
        )
        client = Mock()
        client.get.side_effect = httpx.RequestError("timeout")

        info = connector._fetch_channel_info(client, "1")
        assert info is None

    def test_other_status(self):
        """Returns None on unexpected status."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
        )
        resp = Mock(status_code=500)
        client = Mock()
        client.get.return_value = resp

        info = connector._fetch_channel_info(client, "1")
        assert info is None


# ── Poll Integration ─────────────────────────────────────────────────


class TestDiscordPollIntegration:
    """poll() integration with mocked HTTP."""

    def test_simple_poll(self):
        """Basic poll with one message."""
        mock_resp = Mock(status_code=200)
        mock_resp.json.return_value = [_make_msg("m1", "hello")]

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = mock_resp

            connector = DiscordConnector(
                token="tok",
                channel_ids=["c1"],
                workspace_id="ws",
            )
            events = connector.poll()

        assert len(events) == 1
        assert events[0].content == "hello"

    def test_multiple_channels(self):
        """Poll fetches from all channels."""
        resp1 = Mock(status_code=200)
        resp1.json.return_value = [_make_msg("a", "ch1")]
        resp2 = Mock(status_code=200)
        resp2.json.return_value = [_make_msg("b", "ch2")]

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.side_effect = [resp1, resp2]

            connector = DiscordConnector(
                token="tok",
                channel_ids=["c1", "c2"],
                workspace_id="ws",
            )
            events = connector.poll()

        assert len(events) == 2

    def test_thread_support_enabled(self):
        """include_threads=True fetches parent messages for thread channels."""
        # Channel info response — type 11 (GUILD_PUBLIC_THREAD) with parent_id
        chan_info_resp = Mock(status_code=200)
        chan_info_resp.json.return_value = {
            "id": "thread-chan",
            "type": 11,
            "parent_id": "parent-chan",
        }
        # Parent channel messages
        parent_resp = Mock(status_code=200)
        parent_resp.json.return_value = [_make_msg("par-1", "parent msg")]

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            # First call: channel info for thread-chan
            # Second call: messages for parent-chan
            # Third call: messages for thread-chan itself
            mock_client.get.side_effect = [
                chan_info_resp,  # channel info
                parent_resp,  # parent messages
                Mock(status_code=200, json=Mock(return_value=[])),  # thread msgs
            ]

            connector = DiscordConnector(
                token="tok",
                channel_ids=["thread-chan"],
                workspace_id="ws",
                include_threads=True,
            )
            events = connector.poll()

        assert len(events) == 1
        assert events[0].content == "parent msg"

    def test_thread_type_10_news(self):
        """Thread type 10 (GUILD_NEWS_THREAD) handled."""
        chan_info = Mock(status_code=200)
        chan_info.json.return_value = {
            "id": "news-thread",
            "type": 10,
            "parent_id": "p",
        }
        parent = Mock(status_code=200)
        parent.json.return_value = [_make_msg("n1", "news")]

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.side_effect = [
                chan_info,
                parent,
                Mock(status_code=200, json=Mock(return_value=[])),
            ]

            connector = DiscordConnector(
                token="tok",
                channel_ids=["news-thread"],
                workspace_id="ws",
                include_threads=True,
            )
            events = connector.poll()

        assert len(events) == 1
        assert events[0].content == "news"

    def test_thread_channel_info_error_removes_channel(self):
        """When channel info fails (404), channel is removed from list."""
        chan_info = Mock(status_code=404)

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = chan_info

            connector = DiscordConnector(
                token="tok",
                channel_ids=["bad-chan"],
                workspace_id="ws",
                include_threads=True,
            )
            events = connector.poll()

        assert events == []
        assert "bad-chan" not in connector.channel_ids

    def test_deduplication_across_polls(self):
        """Previously seen messages are deduplicated on next poll."""
        resp = Mock(status_code=200)
        resp.json.return_value = [_make_msg("m99", "first poll")]

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = resp

            connector = DiscordConnector(
                token="tok",
                channel_ids=["c1"],
                workspace_id="ws",
            )
            events1 = connector.poll()
            events2 = connector.poll()

        assert len(events1) == 1
        assert len(events2) == 0


# ── Emoji Resolution ─────────────────────────────────────────────────


class TestDiscordEmoji:
    """_resolve_emoji behavior."""

    def test_no_emoji_patterns(self):
        """Content with no :name: patterns returned unchanged."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
        )
        result = connector._resolve_emoji("hello world", None)
        assert result == "hello world"

    def test_emoji_with_cache_hit(self):
        """Cached emoji is substituted."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
        )
        connector._emoji_cache["wave"] = "👋"
        result = connector._resolve_emoji(":wave: hello", None)
        assert "👋" in result

    def test_emoji_uncached_unchanged(self):
        """Uncached emoji shortcode is left as-is."""
        connector = DiscordConnector(
            token="tok",
            channel_ids=["1"],
            workspace_id="ws",
        )
        result = connector._resolve_emoji(":unknown_emoji: text", None)
        assert ":unknown_emoji:" in result
