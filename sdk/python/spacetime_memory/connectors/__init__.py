"""Sync connectors for spacetime-memory, split into per-connector modules.

``connectors`` defines **sync connectors** — classes that actively *poll*
external data sources (Discord, Notion, Telegram, GitHub, Slack, RSS, Twitter,
webhook, orgmode) and persist events as memories or KG nodes.  This is distinct
from ``spacetime_memory.sdks``, which provides **parity adapters** (Mem0, Zep,
Graphiti, etc.) for drop-in API compatibility (these don't poll).

The base class is ``SyncConnector`` in ``._base``.  The old ``Connector`` name
is kept as a backward-compatible alias but new code should use
``SyncConnector``.

For backward compatibility, all classes are re-exported from this package.
Old import: ``from spacetime_memory.connectors import RssFeedConnector``
New import: ``from spacetime_memory.connectors._rss import RssFeedConnector``
"""

from __future__ import annotations

from ._base import Connector, SyncConnector
from ._types import ConnectorDaemon, ConnectorRegistry, Event

# Lazy imports — each connector module may have optional dependencies
# (feedparser for RSS, etc.).  Defer importing until the class is actually
# accessed, so importing *this* package doesn't fail when optional deps
# are missing.
_LAZY_CONNECTORS: dict[str, tuple[str, str]] = {
    "RssFeedConnector": ("._rss", "RssFeedConnector"),
    "GitHubConnector": (".github", "GitHubConnector"),
    "TwitterConnector": (".twitter", "TwitterConnector"),
    "WebhookConnector": (".webhook", "WebhookConnector"),
    "SlackConnector": (".slack", "SlackConnector"),
    "DiscordConnector": (".discord", "DiscordConnector"),
    "NotionConnector": (".notion", "NotionConnector"),
    "TelegramConnector": (".telegram", "TelegramConnector"),
    "OrgModeParser": (".orgmode", "OrgModeParser"),
}

__all__ = [
    "Connector",
    "ConnectorDaemon",
    "ConnectorRegistry",
    "DiscordConnector",
    "Event",
    "GitHubConnector",
    "NotionConnector",
    "OrgModeParser",
    "RssFeedConnector",
    "SlackConnector",
    "SyncConnector",
    "TelegramConnector",
    "TwitterConnector",
    "WebhookConnector",
]


def __getattr__(name: str):
    """Lazy-load connector classes on first attribute access."""
    if name in _LAZY_CONNECTORS:
        module_path, class_name = _LAZY_CONNECTORS[name]
        from importlib import import_module

        mod = import_module(module_path, __package__)
        klass = getattr(mod, class_name)
        # Cache in the module dict so subsequent lookups bypass __getattr__
        globals()[name] = klass
        return klass
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
