#!/usr/bin/env python3
"""Run all configured connectors once.

Usage::

    python scripts/run_connectors.py

Config file: ~/.spacetime-memory/connectors.yaml

Example config::

    slack:
      token: xoxb-...
      channels:
        - C123
        - C456
      workspace_id: "ws_..."

    discord:
      token: MTEx...
      channels:
        - "123"
        - "456"
      workspace_id: "ws_..."

    notion:
      token: secret_...
      database_id: abc123
      workspace_id: "ws_..."

    org:
      file_path: "/path/to/notes.org"
      workspace_id: "ws_..."

    github:
      token: ghp_...
      username: "me"
      workspace_id: "ws_..."

    twitter:
      bearer_token: "AAAA..."
      user_id: "123456789"     # or list_id: "..."
      workspace_id: "ws_..."

    rss:
      - url: "https://example.com/feed.xml"
        workspace_id: "ws_..."
      - url: "https://other.com/atom.xml"
        workspace_id: "ws_..."
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(
        "Missing dependency: PyYAML.  Install with:\n"
        "  pip install pyyaml"
    )
    sys.exit(1)

# Ensure the SDK is importable (works when run from the repo root)
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "sdk", "python"),
)

from spacetime_memory import Client
from spacetime_memory.connectors import (
    ConnectorRegistry,
    DiscordConnector,
    GitHubConnector,
    NotionConnector,
    OrgModeParser,
    RssFeedConnector,
    SlackConnector,
    TwitterConnector,
)


def _build_github(config: dict, registry: ConnectorRegistry) -> None:
    """Register a GitHub connector from config."""
    required = ("token", "username", "workspace_id")
    if not all(k in config for k in required):
        print("  [config] github: missing one of token/username/workspace_id")
        return
    registry.register(
        "github",
        GitHubConnector(
            token=config["token"],
            username=config["username"],
            workspace_id=config["workspace_id"],
            peer_id=config.get("peer_id", "github-bot"),
        ),
    )


def _build_twitter(config: dict, registry: ConnectorRegistry) -> None:
    """Register a Twitter connector from config."""
    required = ("bearer_token", "workspace_id")
    if not all(k in config for k in required):
        print("  [config] twitter: missing bearer_token or workspace_id")
        return
    if "user_id" not in config and "list_id" not in config:
        print("  [config] twitter: need either user_id or list_id")
        return
    registry.register(
        "twitter",
        TwitterConnector(
            bearer_token=config["bearer_token"],
            workspace_id=config["workspace_id"],
            user_id=config.get("user_id"),
            list_id=config.get("list_id"),
            peer_id=config.get("peer_id", "twitter-bot"),
        ),
    )


def _build_rss(config: list | dict, registry: ConnectorRegistry) -> None:
    """Register RSS feed connectors from config."""
    feeds: list[dict] = config if isinstance(config, list) else [config]
    for i, feed in enumerate(feeds):
        if "url" not in feed or "workspace_id" not in feed:
            print(f"  [config] rss[{i}]: missing url or workspace_id")
            continue
        registry.register(
            f"rss-{i}",
            RssFeedConnector(
                feed_url=feed["url"],
                workspace_id=feed["workspace_id"],
                peer_id=feed.get("peer_id", "rss-bot"),
            ),
        )


def _build_slack(config: dict, registry: ConnectorRegistry) -> None:
    """Register a Slack connector from config."""
    required = ("token", "channels", "workspace_id")
    if not all(k in config for k in required):
        print(
            "  [config] slack: missing one of"
            " token/channels/workspace_id"
        )
        return
    registry.register(
        "slack",
        SlackConnector(
            token=config["token"],
            channel_ids=config["channels"],
            workspace_id=config["workspace_id"],
            peer_id=config.get("peer_id", "slack-bot"),
        ),
    )


def _build_discord(config: dict, registry: ConnectorRegistry) -> None:
    """Register a Discord connector from config."""
    required = ("token", "channels", "workspace_id")
    if not all(k in config for k in required):
        print(
            "  [config] discord: missing one of"
            " token/channels/workspace_id"
        )
        return
    registry.register(
        "discord",
        DiscordConnector(
            token=config["token"],
            channel_ids=config["channels"],
            workspace_id=config["workspace_id"],
            peer_id=config.get("peer_id", "discord-bot"),
        ),
    )


def _build_notion(config: dict, registry: ConnectorRegistry) -> None:
    """Register a Notion connector from config."""
    required = ("token", "database_id", "workspace_id")
    if not all(k in config for k in required):
        print(
            "  [config] notion: missing one of"
            " token/database_id/workspace_id"
        )
        return
    registry.register(
        "notion",
        NotionConnector(
            token=config["token"],
            database_id=config["database_id"],
            workspace_id=config["workspace_id"],
            peer_id=config.get("peer_id", "notion-bot"),
        ),
    )


def _build_org(
    config: dict | list, registry: ConnectorRegistry
) -> None:
    """Register org-mode file parsers from config."""
    files: list[dict] = config if isinstance(config, list) else [config]
    for i, entry in enumerate(files):
        if "file_path" not in entry or "workspace_id" not in entry:
            print(
                f"  [config] org[{i}]: missing file_path or"
                " workspace_id"
            )
            continue
        parser = OrgModeParser(
            file_path=entry["file_path"],
            workspace_id=entry["workspace_id"],
            peer_id=entry.get("peer_id", "org-parser"),
        )
        events = parser.parse()
        print(
            f"  [org] {entry['file_path']}: {len(events)}"
            " headings parsed"
        )
        registry.register(f"org-{i}", parser)


def build_registry(config: dict) -> ConnectorRegistry:
    """Read config dict and return a populated ConnectorRegistry."""
    registry = ConnectorRegistry()

    builders = {
        "github": _build_github,
        "twitter": _build_twitter,
        "rss": _build_rss,
        "slack": _build_slack,
        "discord": _build_discord,
        "notion": _build_notion,
        "org": _build_org,
    }

    for key, builder in builders.items():
        if key in config:
            builder(config[key], registry)

    return registry


def main() -> None:
    """Entry point: load config, build registry, poll all connectors."""
    config_path = os.path.expanduser(
        "~/.spacetime-memory/connectors.yaml"
    )
    if not os.path.exists(config_path):
        # No config = no connectors configured = nothing to do, silently
        return

    with open(config_path) as f:
        config = yaml.safe_load(f)

    if not config:
        print("Empty config — nothing to do.")
        return

    client = Client()
    registry = build_registry(config)

    if not registry.list():
        print("No connectors were configured — nothing to poll.")
        return

    print(f"Polling {len(registry.list())} connector(s)...")
    results = registry.poll_all()

    total_stored = 0
    for name, events in results.items():
        if not events:
            continue
        for ev in events:
            try:
                client.store(
                    workspace_id=ev.workspace_id,
                    content=ev.content,
                    summary=ev.summary or ev.content[:200],
                    memory_type=ev.memory_type or "experience",
                    peer_id=ev.peer_id or "connector",
                    source_session_id=ev.session_id or "",
                )
                total_stored += 1
            except Exception as e:
                print(f"  [store error] {name}: {e}")

    print(
        f"Done. Stored {total_stored} events"
        f" across {len(results)} connector(s)."
    )


if __name__ == "__main__":
    main()
