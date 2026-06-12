"""Connector framework for spacetime-memory — split into per-connector modules.

For backward compatibility, all classes are re-exported from this package.
Old import: ``from spacetime_memory.connectors import RssFeedConnector``
New import: ``from spacetime_memory.connectors.rss import RssFeedConnector``
"""

from .base import Connector, Event, ConnectorRegistry, ConnectorDaemon
from .rss import RssFeedConnector
from .github import GitHubConnector
from .twitter import TwitterConnector
from .webhook import WebhookConnector
from .slack import SlackConnector
from .discord import DiscordConnector
from .notion import NotionConnector
from .orgmode import OrgModeParser

__all__ = [
    "Connector",
    "Event",
    "ConnectorRegistry",
    "ConnectorDaemon",
    "RssFeedConnector",
    "GitHubConnector",
    "TwitterConnector",
    "WebhookConnector",
    "SlackConnector",
    "DiscordConnector",
    "NotionConnector",
    "OrgModeParser",
]
