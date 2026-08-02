"""
Optional integration tests for connectors — run against live API endpoints.

All tests in this file are gated by environment variables:

    CONNECTOR_INTEGRATION=1 python -m pytest tests/test_connector_integration.py -v

Or set individual connector creds to run only a subset:

    DISCORD_BOT_TOKEN=abc... python -m pytest tests/test_connector_integration.py -k discord -v

Each test creates the connector with real credentials (from environment),
calls poll() or handle(), and validates the result structure.  These tests
validate that URL construction, auth headers, and response parsing work
correctly against the live API.
"""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.connector_integration,
]

# ── Helpers ────────────────────────────────────────────────────────────────


def _clear_cursors():
    """Remove cursor dir so tests start fresh."""
    import shutil
    cursor_dir = os.path.expanduser("~/.spacetime-memory/connectors")
    if os.path.exists(cursor_dir):
        shutil.rmtree(cursor_dir, ignore_errors=True)


# ── Discord Connector Integration ──────────────────────────────────────────


class TestDiscordConnectorIntegration:
    """Live Discord poll test.

    Requires DISCORD_BOT_TOKEN + DISCORD_CHANNEL_ID.
    """

    @pytest.fixture(autouse=True)
    def check_creds(self):
        from .connector_cred_fixtures import discord_creds

        self.creds = discord_creds()
        _clear_cursors()

    def test_poll_returns_events(self):
        """poll() with real credentials returns Event objects."""
        from spacetime_memory.connectors import DiscordConnector

        connector = DiscordConnector(
            token=self.creds.token,
            channel_ids=[self.creds.channel_id],
            workspace_id="ws-discord-integration",
            decode_emoji=True,
        )
        events = connector.poll()

        assert isinstance(events, list)
        # May be empty if no new messages, but should always be a list
        if events:
            ev = events[0]
            assert hasattr(ev, "content")
            assert hasattr(ev, "metadata")
            assert "channel_id" in ev.metadata
            assert ev.metadata["channel_id"] == self.creds.channel_id


# ── GitHub Connector Integration ────────────────────────────────────────────


class TestGitHubConnectorIntegration:
    """Live GitHub event poll test.

    Requires GITHUB_TOKEN + GITHUB_USERNAME.
    """

    @pytest.fixture(autouse=True)
    def check_creds(self):
        from .connector_cred_fixtures import github_creds

        self.creds = github_creds()
        _clear_cursors()

    def test_poll_returns_events(self):
        """poll() with real GitHub token returns events."""
        from spacetime_memory.connectors import GitHubConnector

        connector = GitHubConnector(
            token=self.creds.token,
            username=self.creds.username,
            workspace_id="ws-gh-integration",
        )
        events = connector.poll()

        assert isinstance(events, list)
        if events:
            ev = events[0]
            assert hasattr(ev, "content")
            assert hasattr(ev, "peer_id")
            assert ev.peer_id == "github-bot"
            # Content should contain meaningful text
            assert len(ev.content) > 10


# ── Slack Connector Integration ──────────────────────────────────────────────


class TestSlackConnectorIntegration:
    """Live Slack poll test.

    Requires SLACK_BOT_TOKEN + SLACK_CHANNEL_ID.
    """

    @pytest.fixture(autouse=True)
    def check_creds(self):
        from .connector_cred_fixtures import slack_creds

        self.creds = slack_creds()
        _clear_cursors()

    def test_poll_returns_events(self):
        """poll() with real Slack token returns events."""
        from spacetime_memory.connectors import SlackConnector

        connector = SlackConnector(
            token=self.creds.token,
            channel_ids=[self.creds.channel_id],
            workspace_id="ws-slack-integration",
        )
        events = connector.poll()

        assert isinstance(events, list)
        if events:
            ev = events[0]
            assert hasattr(ev, "content")
            assert "channel" in ev.metadata


# ── Telegram Connector Integration ──────────────────────────────────────────


class TestTelegramConnectorIntegration:
    """Live Telegram poll test.

    Requires TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID.
    """

    @pytest.fixture(autouse=True)
    def check_creds(self):
        from .connector_cred_fixtures import telegram_creds

        self.creds = telegram_creds()
        _clear_cursors()

    def test_poll_returns_events(self):
        """poll() with real Telegram token returns events."""
        from spacetime_memory.connectors import TelegramConnector

        connector = TelegramConnector(
            token=self.creds.token,
            chat_ids=[int(self.creds.chat_id)],
            workspace_id="ws-tg-integration",
        )
        events = connector.poll()

        assert isinstance(events, list)
        if events:
            ev = events[0]
            assert ev.metadata["source"] == "telegram"
            assert "chat_name" in ev.metadata
            assert "sender" in ev.metadata
            assert ev.workspace_id == "ws-tg-integration"


# ── Twitter/X Connector Integration ─────────────────────────────────────────


class TestTwitterConnectorIntegration:
    """Live Twitter API poll test.

    Requires TWITTER_BEARER_TOKEN + TWITTER_USER_ID.
    """

    @pytest.fixture(autouse=True)
    def check_creds(self):
        from .connector_cred_fixtures import twitter_creds

        self.creds = twitter_creds()
        _clear_cursors()

    def test_poll_returns_events(self):
        """poll() with real Twitter bearer token returns events."""
        from spacetime_memory.connectors import TwitterConnector

        connector = TwitterConnector(
            bearer_token=self.creds.bearer_token,
            user_id=self.creds.user_id,
            workspace_id="ws-twitter-integration",
        )
        events = connector.poll()

        assert isinstance(events, list)
        if events:
            ev = events[0]
            assert hasattr(ev, "content")
            assert hasattr(ev, "workspace_id")
            assert ev.workspace_id == "ws-twitter-integration"


# ── Notion Connector Integration ────────────────────────────────────────────


class TestNotionConnectorIntegration:
    """Live Notion poll test.

    Requires NOTION_API_KEY + NOTION_DATABASE_ID.
    """

    @pytest.fixture(autouse=True)
    def check_creds(self):
        from .connector_cred_fixtures import notion_creds

        self.creds = notion_creds()
        _clear_cursors()

    def test_poll_returns_events(self):
        """poll() with real Notion API key returns events."""
        from spacetime_memory.connectors import NotionConnector

        connector = NotionConnector(
            api_key=self.creds.api_key,
            database_id=self.creds.database_id,
            workspace_id="ws-notion-integration",
        )
        events = connector.poll()

        assert isinstance(events, list)
        if events:
            ev = events[0]
            assert hasattr(ev, "content")
            assert ev.workspace_id == "ws-notion-integration"
            assert "source" in ev.metadata
            assert ev.metadata["source"] == "notion"


# ── RSS Connector Integration ────────────────────────────────────────────────


class TestRssConnectorIntegration:
    """Live RSS feed poll test.

    Requires RSS_FEED_URL (default: https://hnrss.org/frontpage).
    """

    feed_url: str = ""

    @pytest.fixture(autouse=True)
    def check_creds(self):
        from .connector_cred_fixtures import rss_creds

        creds = rss_creds()
        self.feed_url = creds.feed_url
        _clear_cursors()

    def test_poll_returns_events(self):
        """poll() with real RSS feed URL returns events."""
        from spacetime_memory.connectors import RssFeedConnector

        connector = RssFeedConnector(
            feed_url=self.feed_url,
            workspace_id="ws-rss-integration",
        )
        events = connector.poll()

        assert isinstance(events, list)
        # A real RSS feed should have entries
        assert len(events) > 0, f"RSS feed {self.feed_url} returned no entries"
        ev = events[0]
        assert hasattr(ev, "content")
        assert hasattr(ev, "summary")
        assert ev.workspace_id == "ws-rss-integration"
        assert ev.peer_id == "rss-bot"

    def test_poll_with_cursor_persistence(self):
        """Second poll with same feed should deduplicate."""
        from spacetime_memory.connectors import RssFeedConnector

        connector = RssFeedConnector(
            feed_url=self.feed_url,
            workspace_id="ws-rss-integration",
        )
        first = connector.poll()
        second = connector.poll()

        assert len(first) > 0, "First poll should return entries"
        assert len(second) == 0, (
            f"Second poll with same feed returned {len(second)} events "
            f"(expected 0 — already seen {len(first)} entries)"
        )


# ── Org-mode Parser Integration ──────────────────────────────────────────────


class TestOrgModeParserIntegration:
    """Org-mode parser with real file.

    Requires ORG_MODE_FILE_PATH pointing to an existing .org file.
    """

    file_path: str = ""

    @pytest.fixture(autouse=True)
    def check_creds(self):
        import os
        path = os.environ.get("ORG_MODE_FILE_PATH", "")
        if not path or not os.path.exists(path):
            pytest.skip(f"ORG_MODE_FILE_PATH={path!r} not found or not set")
        self.file_path = path

    def test_parse_returns_events(self):
        """parse() with a real org file returns structured events."""
        from spacetime_memory.connectors import OrgModeParser

        parser = OrgModeParser(
            file_path=self.file_path,
            workspace_id="ws-org-integration",
        )
        events = parser.parse()

        assert isinstance(events, list)
        if events:
            ev = events[0]
            assert hasattr(ev, "content")
            assert ev.workspace_id == "ws-org-integration"
            assert ev.metadata["source"] == "org-mode"
            assert "outline_level" in ev.metadata
            assert "todo_state" in ev.metadata


# ── Webhook Connector Functional Tests ───────────────────────────────────────


class TestWebhookConnectorFunctional:
    """Webhook connector needs no live credentials — purely local."""

    def test_handle_json_body(self):
        """handle() with JSON dict returns a single Event."""
        from spacetime_memory.connectors import WebhookConnector

        connector = WebhookConnector(
            path="/webhook/test",
            workspace_id="ws-webhook-integration",
        )
        events = connector.handle({
            "content": "test payload",
            "summary": "test",
        })

        assert len(events) == 1
        assert events[0].content == "test payload"
        assert events[0].workspace_id == "ws-webhook-integration"
        assert events[0].metadata["source"] == "webhook"
        assert events[0].metadata["path"] == "/webhook/test"

    def test_handle_with_hmac(self):
        """handle() with valid HMAC signature works."""
        import hmac
        import json

        from spacetime_memory.connectors import WebhookConnector

        secret = "test-secret"
        body = {"content": "hmac test"}
        body_bytes = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        sig = hmac.new(secret.encode(), body_bytes, "sha256").hexdigest()

        connector = WebhookConnector(
            path="/webhook/hmac",
            workspace_id="ws-webhook-integration",
            secret=secret,
        )
        events = connector.handle(
            body,
            headers={"x-hub-signature-256": f"sha256={sig}"},
        )

        assert len(events) == 1
        assert events[0].content == "hmac test"

    def test_handle_invalid_hmac_raises(self):
        """handle() with invalid HMAC raises ValueError."""
        from spacetime_memory.connectors import WebhookConnector

        connector = WebhookConnector(
            path="/webhook/hmac",
            workspace_id="ws-webhook-integration",
            secret="real-secret",
        )
        with pytest.raises(ValueError, match="HMAC verification failed|signature mismatch"):
            connector.handle(
                {"content": "tampered"},
                headers={"x-hub-signature-256": "sha256=badbadbadbadbad"},
            )

    def test_poll_returns_empty(self):
        """WebhookConnector.poll() always returns empty list."""
        from spacetime_memory.connectors import WebhookConnector

        connector = WebhookConnector(
            path="/webhook/poll",
            workspace_id="ws-webhook-integration",
        )
        assert connector.poll() == []
