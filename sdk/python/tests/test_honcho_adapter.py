"""Integration tests for Honcho-compatible adapter.

These tests require a running SpacetimeDB instance.
Run with::

    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest tests/test_honcho_adapter.py -v

"""

from __future__ import annotations

import os
import uuid
import pytest

from spacetime_memory import Client

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("SPACETIMEDB_HOST"),
        reason="Integration tests require SPACETIMEDB_HOST env var",
    ),
]

from spacetime_memory.sdks.honcho import Honcho


@pytest.fixture(scope="module")
def host() -> str:
    return os.environ.get("SPACETIMEDB_HOST", "localhost")


@pytest.fixture(scope="module")
def port() -> int:
    return int(os.environ.get("SPACETIMEDB_PORT", "3001"))


@pytest.fixture
def honcho(host: str, port: int) -> Honcho:
    """Fresh Honcho instance per test."""
    h = Honcho(config={"host": host, "port": port})
    yield h
    h._user_cache.clear()
    h._session_cache.clear()


def _uname(prefix: str = "honcho-test") -> str:
    """Generate a unique user name to avoid cross-test contamination."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class TestUserMetadata:
    """Tests for the User metadata API."""

    def test_set_metadata(self, honcho: Honcho) -> None:
        """Set metadata on a user."""
        name = _uname()
        user = honcho.create_user(name=name)
        user.set_metadata({"age": 25, "city": "NYC"})

        # Verify via get_metadata
        result = user.get_metadata()
        assert result.get("age") == 25
        assert result.get("city") == "NYC"

    def test_get_metadata_default(self, honcho: Honcho) -> None:
        """get_metadata on a user with no metadata returns empty dict."""
        name = _uname()
        user = honcho.create_user(name=name)
        result = user.get_metadata()
        assert result == {}

    def test_set_metadata_overwrite(self, honcho: Honcho) -> None:
        """Setting metadata overwrites previous values."""
        name = _uname()
        user = honcho.create_user(name=name)
        user.set_metadata({"key": "value1"})
        user.set_metadata({"key": "value2"})

        result = user.get_metadata()
        assert result.get("key") == "value2"

    def test_set_metadata_with_create(self, honcho: Honcho) -> None:
        """Metadata passed to create_user is stored."""
        name = _uname()
        user = honcho.create_user(name=name, metadata={"source": "test"})
        result = user.get_metadata()
        assert result.get("source") == "test"

    def test_multiple_users_isolated_metadata(self, honcho: Honcho) -> None:
        """Different users have independent metadata."""
        name_a = _uname("honcho-iso-A")
        name_b = _uname("honcho-iso-B")
        user_a = honcho.create_user(name=name_a, metadata={"user": "A"})
        user_b = honcho.create_user(name=name_b, metadata={"user": "B"})

        meta_a = user_a.get_metadata()
        meta_b = user_b.get_metadata()
        assert meta_a.get("user") == "A"
        assert meta_b.get("user") == "B"

    def test_roundtrip_complex_metadata(self, honcho: Honcho) -> None:
        """Complex nested metadata roundtrips correctly."""
        name = _uname()
        user = honcho.create_user(name=name)
        complex_meta = {
            "nested": {"a": 1, "b": [1, 2, 3]},
            "tags": ["alpha", "beta"],
            "enabled": True,
            "count": 42,
        }
        user.set_metadata(complex_meta)
        result = user.get_metadata()
        assert result.get("nested") == {"a": 1, "b": [1, 2, 3]}
        assert result.get("tags") == ["alpha", "beta"]
        assert result.get("enabled") is True
        assert result.get("count") == 42
