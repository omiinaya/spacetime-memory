"""Tests for MCP tools — split from test_mcp_advanced.py."""

import pytest

pytest.skip("requires MCP server runtime (server/mcp/)", allow_module_level=True)

class TestRegisterConnector:
    """Tests for the register_connector MCP tool."""

    def test_registers(self, mock_mcp_client):
        from server.mcp.main import register_connector

        result = register_connector(
            name="arXiv RSS",
            connector_type="rss",
            config_json='{"url": "https://export.arxiv.org/rss/cs.AI"}',
            workspace_id="ws1",
            schedule_secs=300,
        )
        assert "arXiv RSS" in result
        mock_mcp_client.register_connector.assert_called_once_with(
            name="arXiv RSS",
            connector_type="rss",
            config_json='{"url": "https://export.arxiv.org/rss/cs.AI"}',
            workspace_id="ws1",
            schedule_secs=300,
        )



# ── TestUpdateConnector ────────────────────────────────────────────────────────

class TestUpdateConnector:
    """Tests for the update_connector MCP tool."""

    def test_updates(self, mock_mcp_client):
        from server.mcp.main import update_connector

        result = update_connector(
            id="conn1",
            name="Updated RSS",
            connector_type="rss",
            config_json='{"url": "https://new.url"}',
            workspace_id="ws1",
            schedule_secs=600,
            is_active=False,
        )
        assert "updated" in result.lower()
        mock_mcp_client.update_connector.assert_called_once_with(
            id="conn1",
            name="Updated RSS",
            connector_type="rss",
            config_json='{"url": "https://new.url"}',
            workspace_id="ws1",
            schedule_secs=600,
            is_active=False,
        )



# ── TestDeleteConnectorMCP ────────────────────────────────────────────────────────

class TestDeleteConnectorMCP:
    """Tests for the delete_connector MCP tool."""

    def test_deletes(self, mock_mcp_client):
        from server.mcp.main import delete_connector

        result = delete_connector(id="conn1")
        assert "deleted" in result.lower()
        mock_mcp_client.delete_connector.assert_called_once_with("conn1")



# ── TestListConnectors ────────────────────────────────────────────────────────

class TestListConnectors:
    """Tests for the list_connectors MCP tool."""

    def test_lists(self, mock_mcp_client):
        from server.mcp.main import list_connectors

        mock_mcp_client._sql.return_value = [
            {
                "id": "conn1",
                "name": "RSS Feed",
                "connector_type": "rss",
                "workspace_id": "ws1",
                "schedule_secs": 300,
                "is_active": True,
                "created_at": 1000,
            },
        ]
        result = list_connectors()
        assert "RSS Feed" in result
        mock_mcp_client._sql.assert_called_once()

    def test_empty(self, mock_mcp_client):
        from server.mcp.main import list_connectors

        mock_mcp_client._sql.return_value = []
        result = list_connectors()
        assert "No connectors" in result


# ── Compounder-based tools not yet covered ────────────────────────────────



# ── TestFindNearDuplicates ────────────────────────────────────────────────────────

class TestFindNearDuplicates:
    """Tests for the find_near_duplicates MCP tool (uses Compounder)."""

    def test_finds_duplicates(self, mock_compounder):
        from server.mcp.main import find_near_duplicates

        mock_compounder.find_near_duplicates.return_value = [
            {
                "entity_id": "e1",
                "entity_type": "memory",
                "score": 0.95,
                "content": "Sample text",
            },
        ]
        result = find_near_duplicates(
            content="Sample text to check",
            workspace_id="ws1",
            threshold=0.92,
            limit=5,
        )
        assert "Found 1 near-duplicate" in result
        assert "0.9500" in result
        mock_compounder.find_near_duplicates.assert_called_once_with(
            content="Sample text to check",
            workspace_id="ws1",
            threshold=0.92,
            limit=5,
        )

    def test_no_duplicates(self, mock_compounder):
        from server.mcp.main import find_near_duplicates

        mock_compounder.find_near_duplicates.return_value = []
        result = find_near_duplicates(content="Unique text")
        assert "No near-duplicates" in result



# ── TestCrossLink ────────────────────────────────────────────────────────

class TestCrossLink:
    """Tests for the cross_link MCP tool (uses Compounder)."""

    def test_cross_links(self, mock_compounder):
        from server.mcp.main import cross_link

        mock_compounder.cross_link.return_value = {
            "links_created": 5,
            "pairs_checked": 100,
        }
        result = cross_link(workspace_id="ws1")
        assert "Cross-link complete" in result
        assert "5" in result
        assert "100" in result
        mock_compounder.cross_link.assert_called_once_with(workspace_id="ws1")

    def test_default_workspace(self, mock_compounder):
        from server.mcp.main import cross_link

        mock_compounder.cross_link.return_value = {"links_created": 0, "pairs_checked": 0}
        cross_link()
        mock_compounder.cross_link.assert_called_once_with(workspace_id="default")



# ── TestSuggestConnections ────────────────────────────────────────────────────────

class TestSuggestConnections:
    """Tests for the suggest_connections MCP tool (uses Compounder)."""

    def test_suggests(self, mock_compounder):
        from server.mcp.main import suggest_connections

        mock_compounder.suggest_connections.return_value = [
            {
                "source_label": "RLHF",
                "target_label": "PPO",
                "common_count": 3,
            },
        ]
        result = suggest_connections(workspace_id="ws1")
        assert "Found 1 connection suggestion" in result
        assert "RLHF" in result
        mock_compounder.suggest_connections.assert_called_once_with(
            workspace_id="ws1"
        )

    def test_no_suggestions(self, mock_compounder):
        from server.mcp.main import suggest_connections

        mock_compounder.suggest_connections.return_value = []
        result = suggest_connections(workspace_id="ws1")
        assert "No connection suggestions" in result



# ── TestExportWorkspace ────────────────────────────────────────────────────────

class TestExportWorkspace:
    """Tests for the export_workspace MCP tool (uses Compounder)."""

    def test_exports(self, mock_compounder):
        from server.mcp.main import export_workspace

        mock_compounder.export_workspace.return_value = {
            "files_written": 10,
            "output_dir": "/tmp/export",
            "errors": [],
        }
        result = export_workspace(output_dir="/tmp/export", workspace_id="ws1")
        assert "Exported 10 file(s)" in result
        assert "/tmp/export" in result
        mock_compounder.export_workspace.assert_called_once_with(
            output_dir="/tmp/export",
            workspace_id="ws1",
            include_kg=False,
            include_system_notes=False,
        )

    def test_with_errors(self, mock_compounder):
        from server.mcp.main import export_workspace

        mock_compounder.export_workspace.return_value = {
            "files_written": 8,
            "output_dir": "/tmp/export",
            "errors": ["Failed to write note n1"],
        }
        result = export_workspace(output_dir="/tmp/export", workspace_id="ws1")
        assert "8 file(s)" in result
        assert "Errors: 1" in result
        assert "Failed to write note n1" in result


# ── Mental model tools ────────────────────────────────────────────────────
