"""SpacetimeDB memory plugin — MemoryProvider interface.

Connects to a running spacetime-memory module (SpacetimeDB + embedder sidecar)
for persistent cross-session recall, semantic search, knowledge graph access,
and markdown notes.

Config via environment variables:
  SPACETIMEDB_HOST       — host (default: localhost)
  SPACETIMEDB_PORT       — port (default: 3001)
  SPACETIMEDB_DB        — database name (default: spacetime-memory)
  EMBEDDER_URL           — embedder sidecar URL (default: http://localhost:9090)
"""

from __future__ import annotations

from ._handlers import SpacetimeMemoryProvider
from ._tools import (
    KG_SCHEMA,
    NOTE_SEARCH_SCHEMA,
    PROFILE_SCHEMA,
    SEARCH_SCHEMA,
    STORE_SCHEMA,
)

__all__ = [
    "SpacetimeMemoryProvider",
    "SEARCH_SCHEMA",
    "STORE_SCHEMA",
    "NOTE_SEARCH_SCHEMA",
    "KG_SCHEMA",
    "PROFILE_SCHEMA",
    "register",
]


def register(ctx) -> None:
    """Register SpacetimeDB as a memory provider plugin."""
    ctx.register_memory_provider(SpacetimeMemoryProvider())
