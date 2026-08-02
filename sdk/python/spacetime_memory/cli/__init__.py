"""stmem — Spacetime-Memory CLI interface."""

from .root import (
    DB,
    EMBEDDER_URL,
    HOST,
    PORT,
    _esc,
    _quiet_print,
    _sdk_client,
    cli,
    print_json,
    print_table,
)

__all__ = ["cli", "main"]

# main() is available via spacetime_memory.cli.main
