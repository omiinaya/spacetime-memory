"""
Connector integration test credential loading and fixture helpers.

All connector integration tests are gated by environment variables so they
only run when the user has explicitly configured live credentials.  This
module provides the fixtures and helpers.

Usage::

    CONNECTOR_INTEGRATION=1 python -m pytest tests/test_connector_integration.py -v

To run a specific connector's live tests, set its env var::

    DISCORD_BOT_TOKEN=abc... python -m pytest tests/test_connector_integration.py -k discord -v

Available connectors and their env vars:

    +---------------------+---------------------------------------+-----------------+
    | Connector           | Env var(s)                            | Required scope   |
    +---------------------+---------------------------------------+-----------------+
    | Discord             | DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID | Read messages    |
    | GitHub              | GITHUB_TOKEN, GITHUB_USERNAME         | Public events    |
    | Slack               | SLACK_BOT_TOKEN, SLACK_CHANNEL_ID     | channels:history |
    | Telegram            | TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  | Read messages    |
    | Twitter/X           | TWITTER_BEARER_TOKEN, TWITTER_USER_ID | v2 API           |
    | Notion              | NOTION_API_KEY, NOTION_DATABASE_ID    | Read content     |
    | RSS                 | RSS_FEED_URL                          | Public feed      |
    | Telegram            | TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  | Bot token         |
    | Orgmode             | ORGMODE_FILE_PATH                     | Local file        |
    | Telegram            | TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  | Bot token         |
    | Orgmode             | ORGMODE_FILE_PATH                     | Local file        |
    | Org-mode            | ORG_MODE_FILE_PATH                    | File read        |
    | Webhook             | (no credentials needed)               | Local only       |
    +---------------------+---------------------------------------+-----------------+

Each integration test file should import ``integration_credentials`` and
``requires_connector_creds`` from this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

# ── Dataclasses for credential bundles ─────────────────────────────────────


@dataclass
class DiscordCreds:
    token: str
    channel_id: str


@dataclass
class GitHubCreds:
    token: str
    username: str


@dataclass
class SlackCreds:
    token: str
    channel_id: str


@dataclass
class TelegramCreds:
    token: str
    chat_id: str


@dataclass
class TwitterCreds:
    bearer_token: str
    user_id: str


@dataclass
class NotionCreds:
    api_key: str
    database_id: str


@dataclass
class RssCreds:
    feed_url: str


# ── Environment detection ──────────────────────────────────────────────────


def _check_all_set(*vars: str) -> bool:
    """Check all environment variables are set and non-empty."""
    return all(bool(os.environ.get(v, "").strip()) for v in vars)


def _get_or_skip(*vars: str) -> dict[str, str]:
    """Get env vars or skip the test if any are missing."""
    values = {}
    for v in vars:
        val = os.environ.get(v, "").strip()
        if not val:
            pytest.skip(f"Missing {v} — set to run this integration test")
        values[v] = val
    return values


# ── Single-connector credential loaders ────────────────────────────────────


def discord_creds() -> DiscordCreds:
    """Load Discord credentials or skip."""
    env = _get_or_skip("DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID")
    return DiscordCreds(token=env["DISCORD_BOT_TOKEN"], channel_id=env["DISCORD_CHANNEL_ID"])


def github_creds() -> GitHubCreds:
    """Load GitHub credentials or skip."""
    env = _get_or_skip("GITHUB_TOKEN", "GITHUB_USERNAME")
    return GitHubCreds(token=env["GITHUB_TOKEN"], username=env["GITHUB_USERNAME"])


def slack_creds() -> SlackCreds:
    """Load Slack credentials or skip."""
    env = _get_or_skip("SLACK_BOT_TOKEN", "SLACK_CHANNEL_ID")
    return SlackCreds(token=env["SLACK_BOT_TOKEN"], channel_id=env["SLACK_CHANNEL_ID"])


def telegram_creds() -> TelegramCreds:
    """Load Telegram credentials or skip."""
    env = _get_or_skip("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    return TelegramCreds(token=env["TELEGRAM_BOT_TOKEN"], chat_id=env["TELEGRAM_CHAT_ID"])


def twitter_creds() -> TwitterCreds:
    """Load Twitter/X credentials or skip."""
    env = _get_or_skip("TWITTER_BEARER_TOKEN", "TWITTER_USER_ID")
    return TwitterCreds(bearer_token=env["TWITTER_BEARER_TOKEN"], user_id=env["TWITTER_USER_ID"])


def notion_creds() -> NotionCreds:
    """Load Notion credentials or skip."""
    env = _get_or_skip("NOTION_API_KEY", "NOTION_DATABASE_ID")
    return NotionCreds(api_key=env["NOTION_API_KEY"], database_id=env["NOTION_DATABASE_ID"])


def rss_creds() -> RssCreds:
    """Load RSS feed URL or skip."""
    env = _get_or_skip("RSS_FEED_URL")
    return RssCreds(feed_url=env["RSS_FEED_URL"])


# ── Global credential check ────────────────────────────────────────────────


def has_any_creds() -> bool:
    """Check whether ANY connector credentials are configured."""
    checks = [
        _check_all_set("DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID"),
        _check_all_set("GITHUB_TOKEN", "GITHUB_USERNAME"),
        _check_all_set("SLACK_BOT_TOKEN", "SLACK_CHANNEL_ID"),
        _check_all_set("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
        _check_all_set("TWITTER_BEARER_TOKEN", "TWITTER_USER_ID"),
        _check_all_set("NOTION_API_KEY", "NOTION_DATABASE_ID"),
        _check_all_set("RSS_FEED_URL"),
    ]
    # Re-enable all integration tests if CONNECTOR_INTEGRATION=1 is set
    if os.environ.get("CONNECTOR_INTEGRATION") in ("1", "true", "yes"):
        return True
    return any(checks)


def requires_any_creds(func=None):
    """Decorator / pytest-marker factory: skip if no credentials are configured."""
    if not has_any_creds():
        return pytest.mark.skip(
            reason="No connector credentials configured. "
            "Set CONNECTOR_INTEGRATION=1 or individual connector env vars."
        )
    return func if func else ()


# ── Pytest fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def integration_mode() -> bool:
    """Check whether connector integration test mode is active.

    Returns True when at least one credential env var is set OR
    CONNECTOR_INTEGRATION=1 is in the environment.
    """
    return has_any_creds()


@pytest.fixture
def ws_id() -> str:
    """Return a unique workspace ID for connector integration tests."""
    import uuid
    return f"conn-integration-{uuid.uuid4().hex[:12]}"


def pytest_configure():
    """Register the ``connector_integration`` marker."""
    import pytest as _pytest
    _pytest.add_marker(
        "connector_integration: integration tests that require live API credentials"
    )
