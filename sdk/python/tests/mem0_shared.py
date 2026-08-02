"""Shared fixtures and helpers for Mem0 adapter tests.

These tests require a running SpacetimeDB instance.
Run with::

    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest tests/test_mem0_core.py -v

"""

from __future__ import annotations

import os
import secrets
import uuid

import pytest

from spacetime_memory.sdks.mem0 import Memory


@pytest.fixture(scope="module")
def host() -> str:
    return os.environ.get("SPACETIMEDB_HOST", "localhost")


@pytest.fixture(scope="module")
def port() -> int:
    return int(os.environ.get("SPACETIMEDB_PORT", "3001"))


@pytest.fixture
def mem(host: str, port: int, stdb_session: dict) -> Memory:
    """Fresh Memory instance per test with unique workspace."""
    m = Memory(
        config={
            "host": host,
            "port": port,
            "db": stdb_session["database"],
        }
    )
    # Auto-register for auth
    try:
        m._client._call("register", [f"mem0_test_{secrets.token_hex(4)}", "Mem0 Test", "testpass"])
    except RuntimeError:
        pass
    yield m
    m.reset()


def _uid(prefix: str = "mem0-test") -> str:
    """Generate a unique user ID to avoid cross-test contamination."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
