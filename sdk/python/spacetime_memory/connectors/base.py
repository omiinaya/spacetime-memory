"""Backward-compatibility shim for spacetime-memory connectors.

This module re-exports everything from ``._base`` and ``._types`` for
backward compatibility with existing connector implementations that
import from ``.base``.

New code should import from the canonical modules:

*   ``SyncConnector``, ``Connector`` → ``._base``
*   ``Event``, ``ConnectorRegistry``, ``ConnectorDaemon`` → ``._types``
*   ``RssFeedConnector`` → ``._rss`` (or use ``.rss`` for compat)
"""

from ._base import Connector, SyncConnector
from ._types import ConnectorDaemon, ConnectorRegistry, Event

__all__ = [
    "Connector",
    "ConnectorDaemon",
    "ConnectorRegistry",
    "Event",
    "SyncConnector",
]
