"""Unit tests for TagMixin — tag management operations.

All tests use the ``mock_http_client`` fixture — no live SpacetimeDB required.
"""

from __future__ import annotations

from unittest.mock import patch


class TestTagMixin:
    """TagMixin methods (tags, batch tag/untag, search by tags)."""

    def test_create_tag(self, mock_http_client):
        result = mock_http_client.create_tag("ws-1", "important", "#FF0000")
        assert result is None

    def test_create_tag_default_color(self, mock_http_client):
        result = mock_http_client.create_tag("ws-1", "default-tag")
        assert result is None

    def test_tag_memory(self, mock_http_client):
        result = mock_http_client.tag_memory("mem-1", "tag-1")
        assert result is None

    def test_untag_memory(self, mock_http_client):
        result = mock_http_client.untag_memory("mem-1", "tag-1")
        assert result is None

    def test_batch_tag_memories(self, mock_http_client):
        result = mock_http_client.batch_tag_memories("tag-1", ["mem-1", "mem-2"])
        assert result == {"status": "ok"}

    def test_batch_tag_memories_empty(self, mock_http_client):
        result = mock_http_client.batch_tag_memories("tag-1", [])
        assert result == {"status": "ok", "note": "no memory IDs provided"}

    def test_batch_untag_memories(self, mock_http_client):
        result = mock_http_client.batch_untag_memories("tag-1", ["mem-1", "mem-2"])
        assert result == {"status": "ok"}

    def test_batch_untag_memories_empty(self, mock_http_client):
        result = mock_http_client.batch_untag_memories("tag-1", [])
        assert result == {"status": "ok", "note": "no memory IDs provided"}

    def test_list_tags(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"id": "tag-1", "name": "important", "color": "#FF0000", "workspace_id": "ws-1", "created_at": 100}
             ]):
            result = mock_http_client.list_tags("ws-1")
        assert len(result) == 1
        assert result[0]["name"] == "important"

    def test_list_tags_empty(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.list_tags("ws-1")
        assert result == []

    def test_delete_tag(self, mock_http_client):
        result = mock_http_client.delete_tag("tag-1")
        assert result is None

    def test_list_tags_by_memory(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"id": "mt-1", "memory_id": "mem-1", "tag_id": "tag-1", "tag_name": "important", "tag_color": "#FF0000"}
             ]):
            result = mock_http_client.list_tags_by_memory("mem-1")
        assert len(result) == 1
        assert result[0]["tag_name"] == "important"

    def test_list_tags_by_memory_empty(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.list_tags_by_memory("mem-1")
        assert result == []

    def test_update_tag(self, mock_http_client):
        result = mock_http_client.update_tag("tag-1", name="renamed", color="#00FF00")
        assert result is None

    def test_search_by_tags(self, mock_http_client):
        with patch.object(mock_http_client, "_embed", return_value=[0.1, 0.2]), \
             patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"workspace_id": "ws-1", "memory_id": "mem-1", "score": 0.95}
             ]):
            result = mock_http_client.search_by_tags("ws-1", ["tag-1", "tag-2"], query="test", limit=10)
        assert len(result) == 1
        assert result[0]["memory_id"] == "mem-1"

    def test_search_by_tags_no_query(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"workspace_id": "ws-1", "memory_id": "mem-1", "score": 0.0}
             ]):
            result = mock_http_client.search_by_tags("ws-1", ["tag-1"], query="", limit=5)
        assert len(result) == 1

    def test_search_by_tags_no_embedding(self, mock_http_client):
        with patch.object(mock_http_client, "_embed", return_value=[]), \
             patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.search_by_tags("ws-1", ["tag-1"], query="test", limit=10)
        assert result == []
