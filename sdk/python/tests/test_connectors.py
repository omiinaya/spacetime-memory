"""Tests for the Connector framework.

Tests cover:
- Connector abstract base class (can't instantiate directly)
- RssFeedConnector.poll() with mock feed data
- GitHubConnector.poll() with mock API responses
- WebhookConnector.handle() with various payloads
- ConnectorRegistry.register() / poll_all()
"""

import json

# Clear connector cursor files before tests to prevent cross-test pollution
# from persistent cursor state stored in ~/.spacetime-memory/connectors/
import os as _os
import shutil as _shutil
from unittest.mock import MagicMock, Mock, patch

import pytest

_conn_cursor_dir = _os.path.expanduser("~/.spacetime-memory/connectors")
if _os.path.exists(_conn_cursor_dir):
    _shutil.rmtree(_conn_cursor_dir, ignore_errors=True)
from spacetime_memory.connectors import (
    Connector,
    ConnectorRegistry,
    DiscordConnector,
    Event,
    GitHubConnector,
    RssFeedConnector,
    SlackConnector,
    TwitterConnector,
    WebhookConnector,
)


class TestConnectorBase:
    """Connector ABC — must not be instantiable directly."""

    def test_connector_is_abstract(self):
        """Connector cannot be instantiated because poll() is abstract."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            Connector()

    def test_concrete_subclass_must_implement_poll(self):
        """A subclass without poll() is still abstract."""

        class BadConnector(Connector):
            pass

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BadConnector()

    def test_concrete_subclass_can_be_instantiated(self):
        """A subclass that implements poll() can be instantiated."""

        class GoodConnector(Connector):
            def poll(self):
                return []

        inst = GoodConnector()
        assert isinstance(inst, Connector)
        assert inst.poll() == []


class TestRssFeedConnector:
    """RssFeedConnector — polls RSS/Atom feeds via feedparser."""

    def test_poll_with_mock_feed(self):
        """poll() parses a mocked feedparser response into Events."""
        # Build a fake feedparser entry
        fake_entry = {
            "id": "tag:example,2023:entry-1",
            "title": "Test Entry",
            "summary": "This is a summary of the test entry.",
            "link": "https://example.com/entry-1",
        }

        with patch("spacetime_memory.connectors._rss.feedparser.parse") as mock_parse:
            mock_parse.return_value = MagicMock(
                entries=[fake_entry],
                bozo=False,
            )

            connector = RssFeedConnector(
                feed_url="https://example.com/feed.xml",
                workspace_id="ws-1",
            )

            events = connector.poll()

        assert len(events) == 1
        assert isinstance(events[0], Event)
        assert "Test Entry" in events[0].content
        assert events[0].workspace_id == "ws-1"
        assert events[0].peer_id == "rss-bot"
        assert events[0].summary == "Test Entry"

    def test_poll_deduplication(self):
        """poll() skips entries that have already been seen."""
        fake_entry = {
            "id": "tag:example,2023:dupe",
            "title": "Duplicate",
            "link": "https://example.com/dupe",
        }

        with patch("spacetime_memory.connectors._rss.feedparser.parse") as mock_parse:
            mock_parse.return_value = MagicMock(entries=[fake_entry], bozo=False)

            connector = RssFeedConnector(
                feed_url="https://example.com/feed.xml",
                workspace_id="ws-1",
            )

            events_first = connector.poll()
            events_second = connector.poll()

        assert len(events_first) == 1
        assert len(events_second) == 0  # Already seen

    def test_poll_empty_feed(self):
        """poll() handles a feed with no entries gracefully."""
        with patch("spacetime_memory.connectors._rss.feedparser.parse") as mock_parse:
            mock_parse.return_value = MagicMock(entries=[], bozo=False)

            connector = RssFeedConnector(
                feed_url="https://example.com/empty.xml",
                workspace_id="ws-1",
            )

            events = connector.poll()

        assert events == []


class TestGitHubConnector:
    """GitHubConnector — polls GitHub API for user events."""

    def test_poll_success(self):
        """poll() parses GitHub API events into Event objects."""
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = [
            {
                "id": "12345",
                "type": "PushEvent",
                "actor": {"login": "octocat"},
                "repo": {"name": "octocat/Hello-World"},
                "payload": {
                    "ref": "refs/heads/main",
                    "commits": [
                        {"message": "Fix bug"},
                        {"message": "Add feature"},
                    ],
                },
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]
        # The connector checks resp.headers.get("Link", "") for pagination
        mock_response.headers = {"Link": ""}

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.return_value = mock_response

            connector = GitHubConnector(
                token="ghp_fake",
                username="octocat",
                workspace_id="ws-1",
            )

            events = connector.poll()

        assert len(events) == 1
        assert "pushed to main" in events[0].content
        assert "Fix bug" in events[0].content
        assert events[0].workspace_id == "ws-1"

    def test_poll_rate_limited(self):
        """poll() returns empty list on 403."""
        mock_response = Mock(status_code=403)

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.return_value = mock_response

            connector = GitHubConnector(
                token="ghp_fake",
                username="octocat",
                workspace_id="ws-1",
            )

            events = connector.poll()

        assert events == []

    def test_poll_empty_response(self):
        """poll() handles empty JSON array."""
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = []

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.return_value = mock_response

            connector = GitHubConnector(
                token="ghp_fake",
                username="nobody",
                workspace_id="ws-1",
            )

            events = connector.poll()

        assert events == []


class TestTwitterConnector:
    """TwitterConnector — polls Twitter/X API v2."""

    def test_poll_success(self):
        """poll() parses tweets into Events."""
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "tweet-1",
                    "text": "Hello world!",
                    "author_id": "user-1",
                    "created_at": "2024-01-01T00:00:00Z",
                }
            ]
        }

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.return_value = mock_response

            connector = TwitterConnector(
                bearer_token="AAAAfake",
                user_id="user-1",
                workspace_id="ws-1",
            )

            events = connector.poll()

        assert len(events) == 1
        assert "Hello world!" in events[0].content
        assert events[0].workspace_id == "ws-1"

    def test_poll_requires_user_or_list(self):
        """TwitterConnector requires user_id or list_id."""
        with pytest.raises(ValueError, match="Either user_id or list_id"):
            TwitterConnector(
                bearer_token="AAAAfake",
                workspace_id="ws-1",
            )

    def test_poll_with_list_id(self):
        """poll() works with list_id instead of user_id."""
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "tweet-list-1",
                    "text": "List tweet!",
                    "author_id": "user-1",
                    "created_at": "2024-01-01T00:00:00Z",
                }
            ]
        }

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.return_value = mock_response

            connector = TwitterConnector(
                bearer_token="AAAAfake",
                list_id="list-1",
                workspace_id="ws-1",
            )

            events = connector.poll()

        assert len(events) == 1
        assert "List tweet!" in events[0].content

    def test_poll_rate_limited(self):
        """poll() returns empty on 429."""
        mock_response = Mock(status_code=429)

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.return_value = mock_response

            connector = TwitterConnector(
                bearer_token="AAAAfake",
                user_id="user-1",
                workspace_id="ws-1",
            )

            events = connector.poll()

        assert events == []

    def test_poll_unauthorized(self):
        """poll() returns empty on 401."""
        mock_response = Mock(status_code=401)

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.return_value = mock_response

            connector = TwitterConnector(
                bearer_token="AAAAfake",
                user_id="user-1",
                workspace_id="ws-1",
            )

            events = connector.poll()

        assert events == []

    def test_poll_unexpected_status(self):
        """poll() returns empty on unexpected status (e.g. 500)."""
        mock_response = Mock(status_code=500)
        mock_response.text = "Internal Server Error"

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.return_value = mock_response

            connector = TwitterConnector(
                bearer_token="AAAAfake",
                user_id="user-1",
                workspace_id="ws-1",
            )

            events = connector.poll()

        assert events == []

    def test_poll_request_error(self):
        """poll() returns empty on httpx.RequestError."""
        import httpx

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.side_effect = httpx.RequestError("timeout")

            connector = TwitterConnector(
                bearer_token="AAAAfake",
                user_id="user-1",
                workspace_id="ws-1",
            )

            events = connector.poll()

        assert events == []

    def test_poll_empty_data(self):
        """poll() handles empty data array."""
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {"data": []}

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.return_value = mock_response

            connector = TwitterConnector(
                bearer_token="AAAAfake",
                user_id="user-1",
                workspace_id="ws-1",
            )

            events = connector.poll()

        assert events == []

    def test_poll_no_data_key(self):
        """poll() handles response without data key."""
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {}

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.return_value = mock_response

            connector = TwitterConnector(
                bearer_token="AAAAfake",
                user_id="user-1",
                workspace_id="ws-1",
            )

            events = connector.poll()

        assert events == []

    def test_poll_deduplication(self):
        """poll() skips already-seen tweet IDs."""
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "tweet-dup",
                    "text": "Seen before",
                    "author_id": "user-1",
                    "created_at": "2024-01-01T00:00:00Z",
                }
            ]
        }

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.return_value = mock_response

            connector = TwitterConnector(
                bearer_token="AAAAfake",
                user_id="user-1",
                workspace_id="ws-1",
            )

            events1 = connector.poll()
            events2 = connector.poll()

        assert len(events1) == 1
        assert len(events2) == 0

    def test_tweet_no_created_at(self):
        """Tweet without created_at still works."""
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "tweet-no-date",
                    "text": "No date tweet",
                    "author_id": "user-1",
                }
            ]
        }

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.return_value = mock_response

            connector = TwitterConnector(
                bearer_token="AAAAfake",
                user_id="user-1",
                workspace_id="ws-1",
            )

            events = connector.poll()

        assert len(events) == 1
        assert events[0].content == "No date tweet"


class TestWebhookConnector:
    """WebhookConnector — processes incoming HTTP payloads."""

    def test_handle_dict_body(self):
        """handle() extracts content from a JSON dict body."""
        connector = WebhookConnector(
            path="/webhook",
            workspace_id="ws-1",
        )

        events = connector.handle(
            {
                "content": "Hello from webhook",
                "summary": "Greeting",
            }
        )

        assert len(events) == 1
        assert events[0].content == "Hello from webhook"
        assert events[0].summary == "Greeting"
        assert events[0].workspace_id == "ws-1"
        assert events[0].metadata["source"] == "webhook"

    def test_handle_fallback_fields(self):
        """handle() falls back to 'text' then 'message' then str(body)."""
        connector = WebhookConnector(
            path="/hook",
            workspace_id="ws-2",
        )

        events = connector.handle({"text": "fallback text"})
        assert events[0].content == "fallback text"

        events2 = connector.handle({"message": "fallback msg"})
        assert events2[0].content == "fallback msg"

    def test_handle_non_dict_body(self):
        """handle() accepts a non-dict body (converts to str)."""
        connector = WebhookConnector(
            path="/hook",
            workspace_id="ws-3",
        )

        events = connector.handle("just a string")
        assert "just a string" in events[0].content

    def test_hmac_verification_passes(self):
        """handle() passes when HMAC signature is correct."""
        connector = WebhookConnector(
            path="/webhook",
            workspace_id="ws-1",
            secret="my-secret",
        )
        import hmac

        body = {"content": "verified"}
        body_bytes = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        expected_sig = hmac.new(b"my-secret", body_bytes, "sha256").hexdigest()

        events = connector.handle(
            body,
            headers={"x-hub-signature-256": f"sha256={expected_sig}"},
        )

        assert len(events) == 1
        assert events[0].content == "verified"

    def test_hmac_verification_fails(self):
        """handle() raises ValueError when HMAC signature is wrong."""
        connector = WebhookConnector(
            path="/webhook",
            workspace_id="ws-1",
            secret="my-secret",
        )

        with pytest.raises(ValueError, match="HMAC verification failed"):
            connector.handle(
                {"content": "tampered"},
                headers={"x-hub-signature-256": "sha256=badbadbad"},
            )

    def test_hmac_missing_signature_header(self):
        """handle() raises ValueError when secret set but no signature header (line 133)."""
        connector = WebhookConnector(
            path="/webhook",
            workspace_id="ws-1",
            secret="my-secret",
        )

        with pytest.raises(ValueError, match="no signature header found"):
            connector.handle(
                {"content": "test"},
                headers={},  # no signature headers at all
            )

    def test_poll_returns_empty(self):
        """poll() is not applicable for WebhookConnector — returns []."""
        connector = WebhookConnector(
            path="/hook",
            workspace_id="ws-1",
        )

        assert connector.poll() == []


class TestConnectorRegistry:
    """ConnectorRegistry — registers and polls multiple connectors."""

    def test_register_and_list(self):
        """register() stores a connector; list() returns it."""
        registry = ConnectorRegistry()

        class FakeConnector(Connector):
            def poll(self):
                return [Event(content="test")]

        connector = FakeConnector()
        registry.register("fake", connector)

        assert "fake" in registry.list()
        assert registry.get("fake") is connector

    def test_unregister(self):
        """unregister() removes a connector."""
        registry = ConnectorRegistry()
        registry.register("a", Mock(spec=Connector))
        registry.unregister("a")
        assert registry.get("a") is None

    def test_poll_all(self):
        """poll_all() calls poll() on all registered connectors."""
        registry = ConnectorRegistry()

        class A(Connector):
            def poll(self):
                return [Event(content="a1"), Event(content="a2")]

        class B(Connector):
            def poll(self):
                return [Event(content="b1")]

        registry.register("a", A())
        registry.register("b", B())

        results = registry.poll_all()

        assert len(results["a"]) == 2
        assert len(results["b"]) == 1
        assert results["a"][0].content == "a1"

    def test_poll_all_catches_errors(self):
        """poll_all() catches exceptions from individual connectors."""
        registry = ConnectorRegistry()

        class Broken(Connector):
            def poll(self):
                raise RuntimeError("broken!")

        class Good(Connector):
            def poll(self):
                return [Event(content="ok")]

        registry.register("broken", Broken())
        registry.register("good", Good())

        results = registry.poll_all()  # should not raise

        assert results["broken"] == []
        assert len(results["good"]) == 1


class TestSlackConnector:
    """SlackConnector — polls Slack API for messages."""

    def test_poll_success(self):
        """poll() parses Slack messages into Events."""
        # Mock channel info response
        channel_info_resp = Mock(status_code=200)
        channel_info_resp.json.return_value = {
            "ok": True,
            "channel": {"name": "general"},
        }

        # Mock history response
        history_resp = Mock(status_code=200)
        history_resp.json.return_value = {
            "ok": True,
            "messages": [
                {"ts": "123.456", "text": "Hello team!", "user": "U001"},
            ],
        }

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            # First call: channel info, Second call: history
            mock_client.get.side_effect = [channel_info_resp, history_resp]

            connector = SlackConnector(
                token="xoxb-fake",
                channel_ids=["C001"],
                workspace_id="ws-1",
            )

            events = connector.poll()

        assert len(events) == 1
        assert events[0].content == "Hello team!"
        assert events[0].metadata["channel"] == "general"


class TestDiscordConnector:
    """DiscordConnector — polls Discord REST API."""

    def test_poll_success(self):
        """poll() parses Discord messages into Events."""
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = [
            {
                "id": "msg-1",
                "content": "Hello from Discord!",
                "author": {"username": "bot"},
                "timestamp": "2024-01-01T00:00:00Z",
            }
        ]

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = mock_response

            connector = DiscordConnector(
                token="MTEfake",
                channel_ids=["123"],
                workspace_id="ws-1",
            )

            events = connector.poll()

        assert len(events) == 1
        assert events[0].content == "Hello from Discord!"
        assert events[0].metadata["channel_id"] == "123"
