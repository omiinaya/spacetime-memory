"""Tests for batch_tag_memories and batch_untag_memories SDK methods.

These tests mock the SpacetimeDB HTTP call layer so no live STDB is needed.

Also covers: create_tag, list_tags, delete_tag, list_tags_by_memory, tag_memory, untag_memory.
"""

import json
from unittest.mock import MagicMock


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
    # Mock internal methods
    client._call = MagicMock(return_value={"status": "ok"})
    client._sql = MagicMock(return_value=[])
    client._query = MagicMock(return_value=[])
    client._identity_established = True
    return client


class TestCreateTag:
    """Tests for create_tag SDK method."""

    def test_create_tag_basic(self):
        client = _make_client()
        client.create_tag("ws-1", "urgent", "#ff0000")
        client._call.assert_called_once_with(
            "create_tag", ["ws-1", "urgent", "#ff0000"]
        )

    def test_create_tag_no_color(self):
        """Color defaults to #808080."""
        client = _make_client()
        client.create_tag("ws-1", "default")
        client._call.assert_called_once_with(
            "create_tag", ["ws-1", "default", "#808080"]
        )

    def test_create_tag_special_characters(self):
        """Tag names with special characters."""
        client = _make_client()
        client.create_tag("ws-1", "test/tag:name", "#00ff00")
        client._call.assert_called_once_with(
            "create_tag", ["ws-1", "test/tag:name", "#00ff00"]
        )

    def test_create_tag_unicode(self):
        """Tag names with unicode."""
        client = _make_client()
        client.create_tag("ws-1", "\u65e5\u672c\u8a9e\u30bf\u30b0", "#0000ff")
        client._call.assert_called_once_with(
            "create_tag", ["ws-1", "\u65e5\u672c\u8a9e\u30bf\u30b0", "#0000ff"]
        )


class TestListTags:
    """Tests for list_tags SDK method."""

    def test_list_tags_basic(self):
        client = _make_client()
        client._query.return_value = [
            {"id": "tag-1", "name": "urgent", "color": "#ff0000"},
            {"id": "tag-2", "name": "wip", "color": "#ffff00"},
        ]

        results = client.list_tags("ws-1")
        client._call.assert_called_once_with("list_tags", ["ws-1"])
        assert len(results) == 2
        assert results[0]["name"] == "urgent"

    def test_list_tags_empty(self):
        """Returns empty list when no tags."""
        client = _make_client()
        results = client.list_tags("ws-1")
        assert results == []

    def test_list_tags_no_color(self):
        """Tags without color are still returned."""
        client = _make_client()
        client._query.return_value = [
            {"id": "tag-3", "name": "simple"},
        ]

        results = client.list_tags("ws-2")
        assert len(results) == 1
        assert results[0]["name"] == "simple"


class TestDeleteTag:
    """Tests for delete_tag SDK method."""

    def test_delete_tag_basic(self):
        client = _make_client()
        client.delete_tag("tag-1")
        client._call.assert_called_once_with("delete_tag", ["tag-1"])

    def test_delete_tag_nonexistent(self):
        """Deleting a non-existent tag doesn't raise."""
        client = _make_client()
        client.delete_tag("nonexistent-id")
        client._call.assert_called_once_with("delete_tag", ["nonexistent-id"])


class TestListTagsByMemory:
    """Tests for list_tags_by_memory SDK method."""

    def test_list_by_memory_basic(self):
        client = _make_client()
        client._query.return_value = [
            {"id": "mt-1", "tag_id": "tag-1", "tag_name": "urgent"},
            {"id": "mt-2", "tag_id": "tag-2", "tag_name": "review"},
        ]

        results = client.list_tags_by_memory("mem-1")
        client._call.assert_called_once_with("list_tags_by_memory", ["mem-1"])
        assert len(results) == 2

    def test_list_by_memory_no_tags(self):
        """Memory with no tags returns empty list."""
        client = _make_client()
        results = client.list_tags_by_memory("mem-1")
        assert results == []

    def test_list_by_memory_nonexistent(self):
        """Non-existent memory returns empty list."""
        client = _make_client()
        results = client.list_tags_by_memory("nonexistent")
        assert results == []


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
        client.batch_tag_memories("tag/with/slashes", ["mem-1"])
        client._call.assert_called_once_with(
            "batch_tag_memories",
            ["tag/with/slashes", json.dumps(["mem-1"])]
        )

    def test_batch_tag_empty_tag_id(self):
        """Empty tag ID still goes to reducer."""
        client = _make_client()
        result = client.batch_tag_memories("", ["mem-1"])
        assert result == client._call.return_value
        client._call.assert_called_once()


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
        client.batch_untag_memories("tag-1", ["mem-1"])

        client._call.assert_called_once_with(
            "batch_untag_memories",
            ["tag-1", json.dumps(["mem-1"])]
        )

    def test_untag_many_ids(self):
        """Batch untag with many IDs."""
        client = _make_client()
        many_ids = [f"mem-{i}" for i in range(50)]
        client.batch_untag_memories("tag-1", many_ids)
        client._call.assert_called_once_with(
            "batch_untag_memories",
            ["tag-1", json.dumps(many_ids)]
        )

    def test_untag_special_chars(self):
        """Untag with special characters in tag_id."""
        client = _make_client()
        result = client.batch_untag_memories("tag:special_chars!", ["mem-1"])
        assert result == client._call.return_value

    def test_untag_same_memory_twice(self):
        """Untagging the same memory twice is idempotent."""
        client = _make_client()
        client.batch_untag_memories("tag-1", ["mem-1"])
        client.batch_untag_memories("tag-1", ["mem-1"])
        assert client._call.call_count == 2

    def test_untag_multiple_tags_from_same_memory(self):
        """Untag multiple different tags from the same memory."""
        client = _make_client()
        client.batch_untag_memories("tag-1", ["mem-1"])
        client.batch_untag_memories("tag-2", ["mem-1"])
        client.batch_untag_memories("tag-3", ["mem-1"])
        assert client._call.call_count == 3
        client._call.assert_any_call(
            "batch_untag_memories",
            ["tag-1", '["mem-1"]']
        )
        client._call.assert_any_call(
            "batch_untag_memories",
            ["tag-2", '["mem-1"]']
        )

    def test_untag_nonexistent_tag(self):
        """Untagging a non-existent tag should not raise."""
        client = _make_client()
        # Server-side handles nonexistent tags gracefully
        result = client.batch_untag_memories("nonexistent-tag", ["mem-1"])
        assert result == client._call.return_value


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

    def test_tag_memory_new_memory(self):
        """Tagging memory with no existing tags."""
        client = _make_client()
        client.tag_memory("new-memory", "tag-1")
        client._call.assert_called_once_with("tag_memory", ["new-memory", "tag-1"])

    def test_tag_memory_special_chars(self):
        """Programming language tag names."""
        client = _make_client()
        client.tag_memory("mem-1", "c++")
        client._call.assert_called_once_with("tag_memory", ["mem-1", "c++"])

    def test_tag_then_untag(self):
        """Tag then untag a memory."""
        client = _make_client()
        client.tag_memory("mem-1", "tag-1")
        client.untag_memory("mem-1", "tag-1")
        assert client._call.call_count == 2
