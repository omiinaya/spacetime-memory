"""Internal helper utilities for the Graphiti adapter."""

from __future__ import annotations


def _esc(val: str) -> str:
    """Basic SQL string escaping."""
    return val.replace("'", "''")
