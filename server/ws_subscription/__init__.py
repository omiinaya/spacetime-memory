"""
WebSocket subscription server for spacetime-memory.

Provides real-time memory update push to connected WebSocket clients.
Bridges STDB change_event table changes to WebSocket subscribers.

Usage:
    # From CLI:
    python -m server.ws_subscription.main

    # Programmatic:
    from server.ws_subscription.main import start_server
    start_server(host="0.0.0.0", port=8765)

Classes:
    SubscriptionServer  -- WebSocket server that fans out STDB changes to subscribers
    StdbSubscriptionClient -- Wraps STDB subscription (push via WS, fallback to poll)
    SubscriptionFilter  -- A single subscription filter for a WebSocket connection
    ClientConnection    -- Represents a connected WebSocket client with subscriptions
"""

from server.ws_subscription.main import (
    ClientConnection,
    StdbSubscriptionClient,
    SubscriptionFilter,
    SubscriptionServer,
    start_server,
)
