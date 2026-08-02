"""Type definitions, registry, and daemon for spacetime-memory connectors.

``connectors._types`` provides:

*   ``Event`` — a single event from a connector poll.
*   ``ConnectorRegistry`` — registry for managing multiple connectors.
*   ``ConnectorDaemon`` — background daemon that loads connector configs
    from the database and runs them in a poll loop.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._base import SyncConnector

logger = logging.getLogger(__name__)


# ── Event data ──────────────────────────────────────────────────────


@dataclass
class Event:
    """A single event from a connector."""

    content: str
    workspace_id: str = ""
    summary: str = ""
    memory_type: str = "experience"
    peer_id: str = "connector"
    session_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ── SyncConnector registry ──────────────────────────────────────────


class ConnectorRegistry:
    """A registry for managing multiple connectors.

    Usage::

        registry = ConnectorRegistry()
        registry.register("github", github_connector)
        registry.register("rss", rss_connector)
        all_events = registry.poll_all()
    """

    def __init__(self) -> None:
        self._connectors: dict[str, SyncConnector] = {}

    def register(self, name: str, connector: SyncConnector) -> None:
        """Register a connector under a human-friendly name."""
        self._connectors[name] = connector

    def unregister(self, name: str) -> None:
        """Remove a registered connector by name."""
        self._connectors.pop(name, None)

    def get(self, name: str) -> SyncConnector | None:
        """Get a registered connector by name."""
        return self._connectors.get(name)

    def list(self) -> dict[str, SyncConnector]:
        """Return a copy of the registered connectors dict."""
        return dict(self._connectors)

    def poll_all(self) -> dict[str, list[Event]]:
        """Call ``poll()`` on every registered connector.

        Errors from individual connectors are caught and logged; they
        do not prevent other connectors from being polled.

        Returns:
            A dict mapping connector names to their event lists.
        """
        results: dict[str, list[Event]] = {}
        for name, connector in self._connectors.items():
            try:
                results[name] = connector.poll()
            except Exception as e:
                logger.warning("registry error %s: %s", name, e)
                results[name] = []
        return results


# ── SyncConnector daemon ────────────────────────────────────────────


class ConnectorDaemon:
    """Background daemon that loads connector configs from the database
    and runs them in a poll loop.

    Usage::

        daemon = ConnectorDaemon(client)
        daemon.start()  # blocks until interrupted
    """

    def __init__(self, client, db_poll_secs=60):
        self.client = client
        self.db_poll_secs = db_poll_secs
        self._runners = {}
        self._running = False

    def _load_configs(self):
        """Fetch active connector configs from the database."""
        rows = self.client._query(
            "connector_config",
            filter_dict={"is_active": "true"},
            columns=[
                "id",
                "name",
                "connector_type",
                "config_json",
                "workspace_id",
                "schedule_secs",
            ],
        )
        return rows

    def _build_connector(self, cfg):
        """Build a SyncConnector instance from a config row."""

        conn_type = cfg["connector_type"]
        params = json.loads(cfg.get("config_json", "{}"))
        ws = cfg["workspace_id"]

        if conn_type == "rss":
            from . import RssFeedConnector

            return RssFeedConnector(feed_url=params.get("feed_url", ""), workspace_id=ws)
        elif conn_type == "github":
            from . import GitHubConnector

            return GitHubConnector(
                token=params.get("token", ""), username=params.get("username", ""), workspace_id=ws
            )
        elif conn_type == "twitter":
            from . import TwitterConnector

            return TwitterConnector(
                bearer_token=params.get("bearer_token", ""),
                user_id=params.get("user_id", ""),
                workspace_id=ws,
            )
        elif conn_type == "slack":
            from . import SlackConnector

            return SlackConnector(
                token=params.get("token", ""),
                channel_ids=params.get("channel_ids", []),
                workspace_id=ws,
            )
        elif conn_type == "discord":
            from . import DiscordConnector

            return DiscordConnector(
                token=params.get("token", ""),
                channel_ids=params.get("channel_ids", []),
                workspace_id=ws,
            )
        elif conn_type == "telegram":
            from . import TelegramConnector

            return TelegramConnector(
                token=params.get("token", ""),
                chat_ids=params.get("chat_ids", []),
                workspace_id=ws,
            )
        elif conn_type == "orgmode":
            from .orgmode import OrgModeParser

            return OrgModeParser(
                file_path=params.get("file_path", ""),
                workspace_id=ws,
                peer_id=params.get("peer_id", "org-parser"),
                memory_type=params.get("memory_type", "experience"),
            )
        elif conn_type == "notion":
            from . import NotionConnector

            return NotionConnector(
                token=params.get("token", ""),
                database_id=params.get("database_id", ""),
                workspace_id=ws,
                max_pages=params.get("max_pages", 100),
            )
        elif conn_type == "webhook":
            from . import WebhookConnector

            return WebhookConnector(
                path=params.get("path", "/webhook"),
                workspace_id=ws,
                peer_id=params.get("peer_id", "webhook"),
                secret=params.get("secret", None),
            )
        else:
            raise ValueError(f"Unknown connector type: {conn_type}")

    def start(self):
        """Run the daemon loop. Blocks until KeyboardInterrupt."""
        import logging

        logger = logging.getLogger(__name__)
        self._running = True
        logger.info("SyncConnector daemon starting...")

        while self._running:
            try:
                configs = self._load_configs()
                active_ids = {c["id"] for c in configs}

                for cid in list(self._runners):
                    if cid not in active_ids:
                        logger.info("Removing connector %s", cid)
                        del self._runners[cid]

                for cfg in configs:
                    cid = cfg["id"]
                    if cid not in self._runners:
                        try:
                            conn = self._build_connector(cfg)
                            logger.info(
                                "Starting connector %s (%s, %ss interval)",
                                cfg["name"],
                                cfg["connector_type"],
                                cfg["schedule_secs"],
                            )
                            self._runners[cid] = conn
                        except Exception as e:
                            logger.error("Failed to build connector %s: %s", cid, e)

                for cid, conn in list(self._runners.items()):
                    try:
                        events = conn.poll()
                        for ev in events:
                            try:
                                conn.on_event(ev, self.client)
                            except Exception as e:
                                logger.error("Event handler error for %s: %s", cid, e)
                        if events:
                            logger.info("SyncConnector %s: %d events", cid, len(events))
                    except Exception as e:
                        logger.error("Poll error for %s: %s", cid, e)

            except Exception as e:
                logger.error("Daemon tick error: %s", e)

            for _ in range(self.db_poll_secs):
                if not self._running:
                    break

                time.sleep(1)

    def stop(self):
        """Gracefully stop the daemon."""
        self._running = False
