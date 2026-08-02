"""stmem — Spacetime-Memory CLI package.

A command-line interface for managing memory from the terminal,
using the spacetime-memory Python SDK.

Configuration via environment variables:
    STMEM_HOST / SPACETIMEDB_HOST (default: localhost)
    STMEM_PORT / SPACETIMEDB_PORT (default: 3001)
    STMEM_DB / SPACETIMEDB_DB (default: spacetime-memory)
"""

from .root import cli, main, _sdk_client
from . import commands  # noqa: F401  (import side effect: registers subcommands)

__all__ = ["cli", "main", "_sdk_client"]
