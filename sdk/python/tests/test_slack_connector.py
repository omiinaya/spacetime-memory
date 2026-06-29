"""Tests for SlackConnector — mock-based HTTP tests.

Covers: poll(), _paginate, _refresh_token, _get_channel_name,
_fetch_thread_replies, channel join/leave filtering, dedup.
"""

from unittest.mock import Mock, patch

import os as _os
import shutil as _shutil

_conn_cursor_dir = _os.path.expanduser("~/.spacetime-memory/connectors")
if _os.path.exists(_conn_cursor_dir):
    _shutil.rmtree(_conn_cursor_dir, ignore_errors=True)

from spacetime_memory.connectors import SlackConnector  # noqa: E402 — intentional: after cursor dir setup


# ── Helpers ──────────────────────────────────────────────────────────


def _mock_ok_response(data):
    """Mock a Slack OK response with given data."""
    resp = Mock(status_code=200)
    resp.json.return_value = data
    return resp


def _channel_info_resp(name="general"):
    return _mock_ok_response(
        {
            "ok": True,
            "channel": {"id": "C001", "name": name},
        }
    )


def _history_resp(messages=None, has_more=False, next_cursor=""):
    data = {
        "ok": True,
        "messages": messages or [],
    }
    if has_more and next_cursor:
        data["response_metadata"] = {"next_cursor": next_cursor}
    return _mock_ok_response(data)


# ── Token Refresh ────────────────────────────────────────────────────


class TestSlackTokenRefresh:
    """_refresh_token behavior."""

    def test_no_callback_warns_once(self):
        """First call prints warning, second call doesn't."""
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
        )
        assert not connector._refresh_warned
        connector._refresh_token()
        assert connector._refresh_warned is True
        # Second call should not print again
        connector._refresh_token()

    def test_callback_refreshes_token(self):
        """Callback updates token."""

        def refresh(old):
            return "new-tok"

        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
        )
        connector._token_refresh_callback = refresh
        connector._refresh_token()
        assert connector.token == "new-tok"

    def test_callback_returns_none_keeps_old(self):
        """If callback returns None/falsy, token stays."""

        def refresh(old):
            return None

        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
        )
        connector._token_refresh_callback = refresh
        connector._refresh_token()
        assert connector.token == "tok"


# ── Pagination ───────────────────────────────────────────────────────


class TestSlackPaginate:
    """_paginate with various API responses."""

    def test_single_page(self):
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
        )
        client = Mock()
        client.get.return_value = _history_resp(
            [
                {"ts": "1.0", "text": "hello"},
            ]
        )
        items = connector._paginate(client, "http://slack/api/history", {"channel": "C1"})
        assert len(items) == 1
        assert items[0]["text"] == "hello"

    def test_multi_page(self):
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
        )
        client = Mock()
        client.get.side_effect = [
            _history_resp([{"ts": "1", "text": "a"}], has_more=True, next_cursor="cur1"),
            _history_resp([{"ts": "2", "text": "b"}], has_more=True, next_cursor="cur2"),
            _history_resp([{"ts": "3", "text": "c"}], has_more=False),
        ]
        items = connector._paginate(client, "http://slack/api/history", {"channel": "C1"})
        assert len(items) == 3
        # Three API calls were made (pagination worked across 3 pages)
        assert client.get.call_count == 3

    def test_rate_limited_429(self):
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
        )
        resp = Mock(status_code=429)
        resp.headers = {"Retry-After": "10"}
        client = Mock()
        client.get.return_value = resp
        items = connector._paginate(client, "http://slack/api/history", {"channel": "C1"})
        assert items == []

    def test_unexpected_status(self):
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
        )
        client = Mock()
        client.get.return_value = Mock(status_code=500)
        items = connector._paginate(client, "http://slack/api/history", {"channel": "C1"})
        assert items == []

    def test_not_ok_response(self):
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
        )
        client = Mock()
        client.get.return_value = _mock_ok_response({"ok": False, "error": "channel_not_found"})
        items = connector._paginate(client, "http://slack/api/history", {"channel": "C1"})
        assert items == []

    def test_not_in_channel(self):
        """not_in_channel error returns empty list gracefully."""
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
        )
        client = Mock()
        client.get.return_value = _mock_ok_response({"ok": False, "error": "not_in_channel"})
        items = connector._paginate(client, "http://slack/api/history", {"channel": "C1"})
        assert items == []

    def test_request_error(self):
        import httpx

        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
        )
        client = Mock()
        client.get.side_effect = httpx.RequestError("timeout")
        items = connector._paginate(client, "http://slack/api/history", {"channel": "C1"})
        assert items == []

    def test_respects_max_pages(self):
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
            max_pages=2,
        )
        client = Mock()
        # Return 5 pages but only 2 should be fetched
        pages = []
        for i in range(5):
            pages.append(
                _history_resp(
                    [{"ts": str(i), "text": f"msg{i}"}],
                    has_more=True,
                    next_cursor=f"c{i}",
                )
            )
        client.get.side_effect = pages
        items = connector._paginate(client, "http://slack/api/history", {"channel": "C1"})
        assert len(items) == 2


# ── Channel Name ─────────────────────────────────────────────────────


class TestSlackGetChannelName:
    """_get_channel_name with various responses."""

    def test_success_with_name(self):
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
        )
        client = Mock()
        client.get.return_value = _channel_info_resp("random")
        name = connector._get_channel_name(client, "C1")
        assert name == "random"

    def test_not_ok_falls_back_to_id(self):
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
        )
        client = Mock()
        client.get.return_value = _mock_ok_response({"ok": False})
        name = connector._get_channel_name(client, "C1")
        assert name == "C1"

    def test_non_200_status(self):
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
        )
        client = Mock()
        client.get.return_value = Mock(status_code=500)
        name = connector._get_channel_name(client, "C1")
        assert name == "C1"

    def test_connection_error(self):
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
        )
        client = Mock()
        client.get.side_effect = ConnectionError("refused")
        name = connector._get_channel_name(client, "C1")
        assert name == "C1"


# ── Poll Integration ─────────────────────────────────────────────────


class TestSlackPollIntegration:
    """poll() integration tests."""

    def test_poll_filters_join_leave(self):
        """Messages with subtype channel_join/leave are skipped."""
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
        )
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.side_effect = [
                _channel_info_resp("general"),
                _history_resp(
                    [
                        {"ts": "1", "text": "real msg", "user": "U1"},
                        {
                            "ts": "2",
                            "text": "<@U2> joined",
                            "user": "U2",
                            "subtype": "channel_join",
                        },
                        {"ts": "3", "text": "<@U2> left", "user": "U2", "subtype": "channel_leave"},
                    ]
                ),
            ]
            events = connector.poll()

        assert len(events) == 1
        assert events[0].content == "real msg"

    def test_poll_deduplication(self):
        """Seen messages are not re-emitted."""
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
        )
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.side_effect = [
                _channel_info_resp("general"),
                _history_resp([{"ts": "t1", "text": "hello", "user": "U1"}]),
            ]
            e1 = connector.poll()

        with patch("httpx.Client") as MockClient2:
            mock_client2 = MockClient2.return_value.__enter__.return_value
            mock_client2.get.side_effect = [
                _channel_info_resp("general"),
                _history_resp([{"ts": "t1", "text": "hello", "user": "U1"}]),
            ]
            e2 = connector.poll()

        assert len(e1) == 1
        assert len(e2) == 0

    def test_poll_thread_replies(self):
        """include_threads=True fetches thread replies."""
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
            include_threads=True,
        )
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            # Call 0: channel info for C1
            # Call 1: conversations.history for C1
            # Call 2: conversations.replies for thread
            mock_client.get.side_effect = [
                _channel_info_resp("general"),
                _history_resp(
                    [
                        {
                            "ts": "parent.1",
                            "text": "parent msg",
                            "user": "U1",
                            "thread_ts": "parent.1",
                        },
                    ]
                ),
                _history_resp(
                    [
                        {"ts": "reply.1", "text": "reply msg", "user": "U2"},
                    ]
                ),
            ]
            events = connector.poll()

        # Should have: parent msg + reply msg
        assert len(events) == 2
        contents = {e.content for e in events}
        assert "parent msg" in contents
        assert "reply msg" in contents

    def test_poll_thread_reply_dedup(self):
        """Thread replies already seen are skipped."""
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
            include_threads=True,
        )
        # Pre-seed _seen with the reply ts
        connector._seen.add("reply.1")

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.side_effect = [
                _channel_info_resp("general"),
                _history_resp(
                    [
                        {
                            "ts": "parent.1",
                            "text": "parent msg",
                            "user": "U1",
                            "thread_ts": "parent.1",
                        },
                    ]
                ),
                _history_resp(
                    [
                        {"ts": "reply.1", "text": "already seen", "user": "U2"},
                    ]
                ),
            ]
            events = connector.poll()

        assert len(events) == 1
        assert events[0].content == "parent msg"

    def test_poll_multiple_channels(self):
        """Poll fetches from all channels."""
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1", "C2"],
            workspace_id="ws",
        )
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.side_effect = [
                _channel_info_resp("ch1"),
                _history_resp([{"ts": "1", "text": "c1 msg", "user": "U1"}]),
                _channel_info_resp("ch2"),
                _history_resp([{"ts": "2", "text": "c2 msg", "user": "U2"}]),
            ]
            events = connector.poll()

        assert len(events) == 2
        assert events[0].metadata["channel"] == "ch1"
        assert events[1].metadata["channel"] == "ch2"

    def test_thread_reply_metadata(self):
        """Thread replies have is_thread_reply flag."""
        connector = SlackConnector(
            token="tok",
            channel_ids=["C1"],
            workspace_id="ws",
            include_threads=True,
        )
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.side_effect = [
                _channel_info_resp("general"),
                _history_resp(
                    [
                        {"ts": "p.1", "text": "parent", "user": "U1", "thread_ts": "p.1"},
                    ]
                ),
                _history_resp(
                    [
                        {"ts": "r.1", "text": "reply", "user": "U2", "subtype": ""},
                    ]
                ),
            ]
            events = connector.poll()

        assert len(events) == 2
        # Find the reply event
        reply_ev = [e for e in events if "is_thread_reply" in e.metadata]
        assert len(reply_ev) == 1
        assert reply_ev[0].metadata["is_thread_reply"] is True
        assert reply_ev[0].metadata["thread_ts"] == "p.1"
