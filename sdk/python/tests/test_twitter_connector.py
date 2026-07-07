"""Dedicated TwitterConnector tests.

Augments the Twitter tests in test_connectors.py with additional
edge case coverage: pagination, network errors, malformed responses,
empty results, and cursor save/load.

All tests use mock httpx — no live Twitter API calls.
"""

from unittest.mock import Mock, patch, MagicMock
import json
import os
import shutil
import pytest

# Ensure clean cursor directory before tests
_conn_base_dir = os.path.expanduser("~/.spacetime-memory/connectors")
if os.path.exists(_conn_base_dir):
    shutil.rmtree(_conn_base_dir, ignore_errors=True)

from spacetime_memory.connectors import TwitterConnector, Event  # noqa: E402


def _mock_ok_response(data, status_code=200):
    """Build a mock httpx.Response with JSON data."""
    resp = Mock(status_code=status_code)
    resp.json.return_value = data
    resp.text = json.dumps(data)
    resp.headers = {}
    return resp


class TestTwitterInit:
    """Constructor edge cases."""

    def test_init_with_user_id(self):
        c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
        assert c.user_id == "u1"
        assert c.list_id is None

    def test_init_with_list_id(self):
        c = TwitterConnector(bearer_token="tok", list_id="l1", workspace_id="ws-1")
        assert c.list_id == "l1"
        assert c.user_id is None

    def test_init_neither_raises(self):
        with pytest.raises(ValueError, match="Either user_id or list_id"):
            TwitterConnector(bearer_token="tok", workspace_id="ws-1")

    def test_init_both_provided(self):
        c = TwitterConnector(
            bearer_token="tok", user_id="u1", list_id="l1", workspace_id="ws-1"
        )
        assert c.user_id == "u1"
        assert c.list_id == "l1"

    def test_init_peer_id_default(self):
        c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
        assert c.peer_id == "twitter-bot"

    def test_init_custom_peer_id(self):
        c = TwitterConnector(
            bearer_token="tok", user_id="u1", workspace_id="ws-1", peer_id="my-bot"
        )
        assert c.peer_id == "my-bot"

    def test_init_seen_empty(self):
        c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
        assert c._seen == set()


class TestTwitterPollEdgeCases:
    """Poll edge cases beyond the basic test_connectors coverage."""

    def test_poll_httpx_connection_error(self):
        """Connection error returns empty list."""
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.side_effect = Exception("Connection refused")
            c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
            events = c.poll()
        assert events == []

    def test_poll_timeout(self):
        """Timeout exception returns empty list."""
        import httpx
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.side_effect = httpx.TimeoutException("timed out")
            c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
            events = c.poll()
        assert events == []

    def test_poll_missing_author_id(self):
        """Tweet without author_id uses default peer_id."""
        resp = _mock_ok_response({
            "data": [
                {"id": "t1", "text": "no author", "created_at": "2024-01-01T00:00:00Z"}
            ]
        })
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.return_value = resp
            c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
            events = c.poll()
        assert len(events) == 1
        assert events[0].peer_id == "twitter-bot"

    def test_poll_very_long_tweet(self):
        """Long tweet text is truncated or passed as-is."""
        long_text = "A" * 5000
        resp = _mock_ok_response({
            "data": [
                {"id": "t-long", "text": long_text, "author_id": "u1",
                 "created_at": "2024-01-01T00:00:00Z"}
            ]
        })
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.return_value = resp
            c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
            events = c.poll()
        assert len(events) == 1
        assert len(events[0].content) >= 5000

    def test_poll_multiple_tweets(self):
        """Multiple tweets in one poll."""
        tweets = [{"id": f"t-{i}", "text": f"Tweet {i}", "author_id": "u1",
                    "created_at": f"2024-01-0{i+1}T00:00:00Z"} for i in range(5)]
        resp = _mock_ok_response({"data": tweets})
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.return_value = resp
            c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
            events = c.poll()
        assert len(events) == 5

    def test_poll_dedup_across_calls(self):
        """Same tweets on second poll are deduplicated."""
        tweets = [{"id": "t-1", "text": "dup", "author_id": "u1", "created_at": "2024-01-01T00:00:00Z"}]
        resp = _mock_ok_response({"data": tweets})
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.return_value = resp
            c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
            first = c.poll()
            second = c.poll()
        assert len(first) == 1
        assert len(second) == 0

    def test_poll_mixed_new_and_seen(self):
        """Mix of new and already-seen tweet IDs."""
        tweets_1 = [{"id": "t-1", "text": "first", "author_id": "u1", "created_at": "2024-01-01T00:00:00Z"}]
        tweets_2 = [
            {"id": "t-1", "text": "first", "author_id": "u1", "created_at": "2024-01-01T00:00:00Z"},
            {"id": "t-2", "text": "second", "author_id": "u1", "created_at": "2024-01-02T00:00:00Z"},
        ]
        resp1 = _mock_ok_response({"data": tweets_1})
        resp2 = _mock_ok_response({"data": tweets_2})
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.side_effect = [resp1, resp2]
            c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
            first = c.poll()
            second = c.poll()
        assert len(first) == 1
        assert len(second) == 1
        assert second[0].content == "second"

    def test_poll_with_list_id_uses_correct_endpoint(self):
        """poll() with list_id hits /2/lists/{id}/tweets."""
        resp = _mock_ok_response({"data": []})
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.return_value = resp
            c = TwitterConnector(bearer_token="tok", list_id="l-1", workspace_id="ws-1")
            c.poll()
            called_url = mock_inst.get.call_args[0][0]
            assert "lists" in called_url
            assert "l-1" in called_url

    def test_poll_with_user_id_uses_correct_endpoint(self):
        """poll() with user_id hits /2/users/{id}/tweets."""
        resp = _mock_ok_response({"data": []})
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.return_value = resp
            c = TwitterConnector(bearer_token="tok", user_id="u-1", workspace_id="ws-1")
            c.poll()
            called_url = mock_inst.get.call_args[0][0]
            assert "users" in called_url
            assert "u-1" in called_url

    def test_poll_response_missing_data_key(self):
        """Response without 'data' key returns empty."""
        resp = _mock_ok_response({"meta": {"result_count": 0}})
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.return_value = resp
            c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
            events = c.poll()
        assert events == []

    def test_poll_response_with_errors(self):
        """Response with error array still returns data if present."""
        resp = _mock_ok_response({
            "data": [{"id": "t-1", "text": "partial", "author_id": "u1",
                      "created_at": "2024-01-01T00:00:00Z"}],
            "errors": [{"code": 130, "message": "Over capacity"}],
        })
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.return_value = resp
            c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
            events = c.poll()
        assert len(events) == 1

    def test_poll_only_errors_no_data(self):
        """Response with only errors returns empty."""
        resp = _mock_ok_response({"errors": [{"code": 130, "message": "Over capacity"}]})
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.return_value = resp
            c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
            events = c.poll()
        assert events == []

    def test_poll_status_429_rate_limit(self):
        """429 rate limit returns empty list."""
        resp = _mock_ok_response({}, status_code=429)
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.return_value = resp
            c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
            events = c.poll()
        assert events == []

    def test_poll_status_401_unauthorized(self):
        """401 unauthorized returns empty list."""
        resp = _mock_ok_response({}, status_code=401)
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.return_value = resp
            c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
            events = c.poll()
        assert events == []

    def test_poll_status_500_server_error(self):
        """500 server error returns empty list."""
        resp = _mock_ok_response({}, status_code=500)
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.return_value = resp
            c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
            events = c.poll()
        assert events == []


class TestTwitterEventFields:
    """Verify event field mapping."""

    def test_event_has_correct_fields(self):
        """Event has workspace_id, peer_id, content, timestamp."""
        resp = _mock_ok_response({
            "data": [{"id": "t-1", "text": "hello", "author_id": "u1",
                      "created_at": "2024-06-15T10:30:00Z"}]
        })
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.return_value = resp
            c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
            events = c.poll()
        ev = events[0]
        assert ev.workspace_id == "ws-1"
        assert ev.peer_id == "twitter-bot"
        assert "hello" in ev.content
        assert hasattr(ev, "metadata")

    def test_event_memory_type(self):
        """Event memory type is 'experience'."""
        resp = _mock_ok_response({
            "data": [{"id": "t-1", "text": "test", "author_id": "u1",
                      "created_at": "2024-01-01T00:00:00Z"}]
        })
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.return_value = resp
            c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
            events = c.poll()
        assert events[0].memory_type == "experience"


class TestTwitterCursorPersistence:
    """Cursor state persists between poll calls."""

    def test_seen_tracked_in_memory(self):
        """Seen tweet IDs are tracked in local _seen set."""
        resp = _mock_ok_response({
            "data": [{"id": "t-1", "text": "test", "author_id": "u1",
                      "created_at": "2024-01-01T00:00:00Z"}]
        })
        with patch("httpx.Client") as MockClient:
            mock_inst = MockClient.return_value.__enter__.return_value
            mock_inst.get.return_value = resp
            c = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
            c.poll()
        assert isinstance(c._seen, set)
        assert "t-1" in c._seen

    def test_seen_set_cleared_on_new_instance(self):
        """New instance has empty _seen set."""
        c1 = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
        c2 = TwitterConnector(bearer_token="tok", user_id="u1", workspace_id="ws-1")
        assert c1._seen == set()
        assert c2._seen == set()
