"""Tests for batch_tag_memories and batch_untag_memories SDK methods.

These tests mock the SpacetimeDB HTTP call layer so no live STDB is needed.
"""

import json
from unittest.mock import MagicMock, patch, call


def _make_client():
    """Create a minimal mock client for testing tag methods."""
    import sys
    sys.path.insert(0, "sdk/python")

    from spacetime_memory.client import Client

    client = Client(
        host="http://localhost",
        port=3001,
        database="test",
        embedder_url="http://embedder:8000",
    )
    # Mock the underlying _call method
    client._call = MagicMock(return_value={"status": "ok"})
    return client


class TestBatchTagMemories:
    """Tests for batch_tag_memories SDK method."""

    def test_basic_call(self):
        client = _make_client()
        result = client.batch_tag_memories("tag-1", ["mem-1", "mem-2", "mem-3"])

        client._call.assert_called_once_with(
            "batch_tag_memories",
            ["tag-1", json.dumps(["mem-1", "mem-2", "mem-3"])]
        )
        assert result == client._call.return_value

    def test_empty_memory_ids_skips_call(self):
        client = _make_client()
        result = client.batch_tag_memories("tag-1", [])

        client._call.assert_not_called()
        assert result == {"status": "ok", "note": "no memory IDs provided"}

    def test_single_memory(self):
        client = _make_client()
        result = client.batch_tag_memories("tag-1", ["mem-1"])

        client._call.assert_called_once_with(
            "batch_tag_memories",
            ["tag-1", json.dumps(["mem-1"])]
        )
        assert result == client._call.return_value

    def test_many_memories(self):
        client = _make_client()
        many_ids = [f"mem-{i}" for i in range(100)]
        result = client.batch_tag_memories("tag-1", many_ids)

        client._call.assert_called_once_with(
            "batch_tag_memories",
            ["tag-1", json.dumps(many_ids)]
        )
        assert result == client._call.return_value

    def test_special_chars_in_tag_id(self):
        """Tag IDs with special characters should be passed verbatim."""
        client = _make_client()
        result = client.batch_tag_memories("tag/with/slashes", ["mem-1"])

        client._call.assert_called_once_with(
            "batch_tag_memories",
            ["tag/with/slashes", json.dumps(["mem-1"])]
        )


class TestBatchUntagMemories:
    """Tests for batch_untag_memories SDK method."""

    def test_basic_call(self):
        client = _make_client()
        result = client.batch_untag_memories("tag-1", ["mem-1", "mem-2"])

        client._call.assert_called_once_with(
            "batch_untag_memories",
            ["tag-1", json.dumps(["mem-1", "mem-2"])]
        )
        assert result == client._call.return_value

    def test_empty_memory_ids_skips_call(self):
        client = _make_client()
        result = client.batch_untag_memories("tag-1", [])

        client._call.assert_not_called()
        assert result == {"status": "ok", "note": "no memory IDs provided"}

    def test_single_memory(self):
        client = _make_client()
        result = client.batch_untag_memories("tag-1", ["mem-1"])

        client._call.assert_called_once_with(
            "batch_untag_memories",
            ["tag-1", json.dumps(["mem-1"])]
        )


class TestExistingTagMethods:
    """Verify existing tag methods still work unchanged."""

    def test_tag_memory(self):
        client = _make_client()
        client.tag_memory("mem-1", "tag-1")
        client._call.assert_called_once_with("tag_memory", ["mem-1", "tag-1"])

    def test_untag_memory(self):
        client = _make_client()
        client.untag_memory("mem-1", "tag-1")
        client._call.assert_called_once_with("untag_memory", ["mem-1", "tag-1"])
