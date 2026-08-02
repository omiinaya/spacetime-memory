"""Subscription filter and client connection data types for ws_subscription."""

from __future__ import annotations

from dataclasses import dataclass, field

from websockets.asyncio.server import ServerConnection

# ---------------------------------------------------------------------------
# SubscriptionFilter — a single subscription filter
# ---------------------------------------------------------------------------


@dataclass
class SubscriptionFilter:
    """A single subscription filter attached to a WebSocket connection."""

    workspace_id: str = "*"
    table: str = "*"
    operation: str = "*"

    def matches(self, event) -> bool:
        """Check if a change event matches this filter."""
        if self.workspace_id != "*" and self.workspace_id != event.workspace_id:
            return False
        if self.table != "*" and self.table != event.table_name:
            return False
        if self.operation != "*" and self.operation != event.operation:
            return False
        return True


# ---------------------------------------------------------------------------
# ClientConnection — a connected WebSocket client with subscriptions
# ---------------------------------------------------------------------------


@dataclass
class ClientConnection:
    """Represents a connected WebSocket client with its subscriptions."""

    websocket: ServerConnection
    filters: list[SubscriptionFilter] = field(default_factory=list)
    peer_id: str = ""

    def add_filter(self, f: SubscriptionFilter) -> None:
        self.filters.append(f)

    def remove_filter(self, f: SubscriptionFilter) -> None:
        self.filters = [existing for existing in self.filters if not _filters_equal(existing, f)]

    def matches_any(self, event) -> bool:
        return any(f.matches(event) for f in self.filters)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _filters_equal(a: SubscriptionFilter, b: SubscriptionFilter) -> bool:
    return a.workspace_id == b.workspace_id and a.table == b.table and a.operation == b.operation
