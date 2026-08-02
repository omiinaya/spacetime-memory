"""Tests for MCP tools — split from test_mcp_advanced.py."""

import pytest

pytest.skip("requires MCP server runtime (server/mcp/)", allow_module_level=True)

class TestCreateTag:
    """Tests for the create_tag MCP tool."""

    def test_creates_tag(self, mock_mcp_client):
        from server.mcp.main import create_tag

        mock_mcp_client.create_tag.return_value = {"id": "tag1", "name": "important"}
        result = create_tag(workspace_id="ws1", name="important")
        assert result["name"] == "important"
        mock_mcp_client.create_tag.assert_called_once_with("ws1", "important", "#808080")

    def test_with_custom_color(self, mock_mcp_client):
        from server.mcp.main import create_tag

        mock_mcp_client.create_tag.return_value = {"id": "tag2"}
        create_tag(workspace_id="ws1", name="urgent", color="#FF0000")
        mock_mcp_client.create_tag.assert_called_once_with("ws1", "urgent", "#FF0000")



# ── TestTagMemory ────────────────────────────────────────────────────────

class TestTagMemory:
    """Tests for the tag_memory MCP tool."""

    def test_tags_memory(self, mock_mcp_client):
        from server.mcp.main import tag_memory

        mock_mcp_client.tag_memory.return_value = {"status": "ok"}
        result = tag_memory(memory_id="m1", tag_id="tag1")
        assert result["status"] == "ok"
        mock_mcp_client.tag_memory.assert_called_once_with("m1", "tag1")



# ── TestUntagMemory ────────────────────────────────────────────────────────

class TestUntagMemory:
    """Tests for the untag_memory MCP tool."""

    def test_untags(self, mock_mcp_client):
        from server.mcp.main import untag_memory

        mock_mcp_client.untag_memory.return_value = {"status": "ok"}
        result = untag_memory(memory_id="m1", tag_id="tag1")
        assert result["status"] == "ok"
        mock_mcp_client.untag_memory.assert_called_once_with("m1", "tag1")



# ── TestListTags ────────────────────────────────────────────────────────

class TestListTags:
    """Tests for the list_tags MCP tool."""

    def test_lists(self, mock_mcp_client):
        from server.mcp.main import list_tags

        mock_mcp_client.list_tags.return_value = [
            {"id": "t1", "name": "important"},
            {"id": "t2", "name": "urgent"},
        ]
        result = list_tags(workspace_id="ws1")
        assert len(result) == 2
        mock_mcp_client.list_tags.assert_called_once_with("ws1")

    def test_empty(self, mock_mcp_client):
        from server.mcp.main import list_tags

        mock_mcp_client.list_tags.return_value = []
        result = list_tags(workspace_id="ws1")
        assert result == []



# ── TestDeleteTagMCP ────────────────────────────────────────────────────────

class TestDeleteTagMCP:
    """Tests for the delete_tag MCP tool (avoid name clash)."""

    def test_deletes_tag(self, mock_mcp_client):
        from server.mcp.main import delete_tag

        result = delete_tag(tag_id="tag1")
        assert result["status"] == "ok"
        assert result["deleted_tag_id"] == "tag1"
        mock_mcp_client.delete_tag.assert_called_once_with("tag1")



# ── TestBatchTagMemories ────────────────────────────────────────────────────────

class TestBatchTagMemories:
    """Tests for the batch_tag_memories MCP tool."""

    def test_batch_tags(self, mock_mcp_client):
        from server.mcp.main import batch_tag_memories

        mock_mcp_client.batch_tag_memories.return_value = {"status": "ok"}
        result = batch_tag_memories(tag_id="tag1", memory_ids_json='["m1", "m2"]')
        assert result["status"] == "ok"
        mock_mcp_client.batch_tag_memories.assert_called_once_with(
            "tag1", ["m1", "m2"]
        )



# ── TestBatchUntagMemories ────────────────────────────────────────────────────────

class TestBatchUntagMemories:
    """Tests for the batch_untag_memories MCP tool."""

    def test_batch_untags(self, mock_mcp_client):
        from server.mcp.main import batch_untag_memories

        mock_mcp_client.batch_untag_memories.return_value = {"status": "ok"}
        result = batch_untag_memories(tag_id="tag1", memory_ids_json='["m1", "m2"]')
        assert result["status"] == "ok"
        mock_mcp_client.batch_untag_memories.assert_called_once_with(
            "tag1", ["m1", "m2"]
        )


# ── store_batch ───────────────────────────────────────────────────────────
