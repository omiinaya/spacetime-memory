"""Configuration parsing for SpacetimeDB memory plugin."""

from __future__ import annotations

import os


def _load_config() -> dict:
    return {
        "host": os.environ.get("SPACETIMEDB_HOST", "localhost"),
        "port": os.environ.get("SPACETIMEDB_PORT", "3001"),
        "database": os.environ.get("SPACETIMEDB_DB", "spacetime-memory"),
        "embedder_url": os.environ.get("EMBEDDER_URL", "http://localhost:4000"),
    }
