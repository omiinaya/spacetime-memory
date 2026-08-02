"""Tests for MCP tools — split from test_mcp_advanced.py."""

import pytest

pytest.skip("requires MCP server runtime (server/mcp/)", allow_module_level=True)

class TestSynthesizeMentalModels:
    """Tests for the synthesize_mental_models MCP tool."""

    def test_synthesizes(self, mock_mcp_client):
        from server.mcp.main import synthesize_mental_models

        result = synthesize_mental_models(
            workspace_id="ws1", memory_ids_json='["mem1", "mem2"]'
        )
        assert "Mental model synthesis requested" in result
        mock_mcp_client.synthesize_mental_models.assert_called_once_with(
            "ws1", ["mem1", "mem2"]
        )



# ── TestGetMentalModel ────────────────────────────────────────────────────────

class TestGetMentalModel:
    """Tests for the get_mental_model MCP tool."""

    def test_gets_model(self, mock_mcp_client):
        from server.mcp.main import get_mental_model

        mock_mcp_client._sql_param.return_value = [
            {"id": "mm1", "content": "Mental model content"}
        ]
        result = get_mental_model(id="mm1")
        import json

        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["id"] == "mm1"
        mock_mcp_client._sql_param.assert_called_once()

    def test_not_found(self, mock_mcp_client):
        from server.mcp.main import get_mental_model

        mock_mcp_client._sql_param.return_value = []
        result = get_mental_model(id="nonexistent")
        import json

        parsed = json.loads(result)
        assert parsed == []



# ── TestListMentalModels ────────────────────────────────────────────────────────

class TestListMentalModels:
    """Tests for the list_mental_models MCP tool."""

    def test_lists_all(self, mock_mcp_client):
        from server.mcp.main import list_mental_models

        mock_mcp_client._sql_param.return_value = [
            {"id": "mm1", "status": "completed"},
            {"id": "mm2", "status": "pending"},
        ]
        result = list_mental_models(workspace_id="ws1")
        import json

        parsed = json.loads(result)
        assert len(parsed) == 2
        mock_mcp_client._sql_param.assert_called_once()

    def test_filters_by_status(self, mock_mcp_client):
        from server.mcp.main import list_mental_models

        mock_mcp_client._sql_param.return_value = [
            {"id": "mm1", "status": "completed"},
        ]
        result = list_mental_models(workspace_id="ws1", status="completed")
        import json

        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["status"] == "completed"

    def test_empty(self, mock_mcp_client):
        from server.mcp.main import list_mental_models

        mock_mcp_client._sql_param.return_value = []
        result = list_mental_models(workspace_id="empty")
        import json

        parsed = json.loads(result)
        assert parsed == []



# ── TestDeleteMentalModel ────────────────────────────────────────────────────────

class TestDeleteMentalModel:
    """Tests for the delete_mental_model MCP tool."""

    def test_deletes(self, mock_mcp_client):
        from server.mcp.main import delete_mental_model

        result = delete_mental_model(model_id="mm1")
        assert "deleted" in result.lower()
        mock_mcp_client.delete_mental_model.assert_called_once_with("mm1")



# ── TestUpdateMentalModel ────────────────────────────────────────────────────────

class TestUpdateMentalModel:
    """Tests for the update_mental_model MCP tool."""

    def test_updates(self, mock_mcp_client):
        from server.mcp.main import update_mental_model

        result = update_mental_model(
            model_id="mm1", content="Updated content", confidence=0.8, status="completed"
        )
        assert "updated" in result.lower()
        mock_mcp_client.update_mental_model.assert_called_once_with(
            "mm1", "Updated content", 0.8, "completed"
        )


# ── Fact tool edge cases ──────────────────────────────────────────────────



# ── TestHealthCheck ────────────────────────────────────────────────────────

class TestHealthCheck:
    """Tests for the health_check MCP tool."""

    def test_all_healthy(self, mock_mcp_client):
        from server.mcp.main import health_check

        mock_mcp_client.list_workspaces.return_value = [
            {"id": "ws1", "name": "Test"}
        ]
        mock_mcp_client.check_embedder_health.return_value = {
            "status": "ok", "reachable": True
        }
        mock_mcp_client.check_tantivy_health.return_value = {
            "status": "ok", "reachable": True
        }
        mock_mcp_client._sql.return_value = [{"cnt": 42}]

        result = health_check()
        assert result["status"] == "ok"
        assert result["spacetimedb"] == "ok"
        assert result["embedder"] == "ok"
        assert result["tantivy"] == "ok"
        assert result["workspace_count"] == 1
        assert result["memory_count"] == 42

    def test_spacetimedb_error(self, mock_mcp_client):
        from server.mcp.main import health_check

        mock_mcp_client.list_workspaces.side_effect = RuntimeError("Connection refused")
        mock_mcp_client.check_embedder_health.return_value = {
            "status": "ok", "reachable": True
        }
        mock_mcp_client.check_tantivy_health.return_value = {
            "status": "ok", "reachable": True
        }

        result = health_check()
        assert result["status"] == "degraded"
        assert "error" in result["spacetimedb"]

    def test_embedder_error(self, mock_mcp_client):
        from server.mcp.main import health_check

        mock_mcp_client.list_workspaces.return_value = []
        mock_mcp_client.check_embedder_health.side_effect = RuntimeError("Embedder down")
        mock_mcp_client.check_tantivy_health.return_value = {
            "status": "ok", "reachable": True
        }

        result = health_check()
        assert result["status"] == "degraded"
        assert "error" in result["embedder"]

    def test_tantivy_unreachable(self, mock_mcp_client):
        from server.mcp.main import health_check

        mock_mcp_client.list_workspaces.return_value = []
        mock_mcp_client.check_embedder_health.return_value = {
            "status": "ok", "reachable": True
        }
        mock_mcp_client.check_tantivy_health.return_value = {
            "status": "ok", "reachable": False
        }

        result = health_check()
        assert result["status"] == "degraded"

    def test_tantivy_error(self, mock_mcp_client):
        from server.mcp.main import health_check

        mock_mcp_client.list_workspaces.return_value = []
        mock_mcp_client.check_embedder_health.return_value = {
            "status": "ok", "reachable": True
        }
        mock_mcp_client.check_tantivy_health.side_effect = RuntimeError("Tantivy error")

        result = health_check()
        assert result["status"] == "degraded"

    def test_sql_error_still_returns_health(self, mock_mcp_client):
        from server.mcp.main import health_check

        mock_mcp_client.list_workspaces.return_value = []
        mock_mcp_client.check_embedder_health.return_value = {
            "status": "ok", "reachable": True
        }
        mock_mcp_client.check_tantivy_health.return_value = {
            "status": "ok", "reachable": True
        }
        mock_mcp_client._sql.side_effect = RuntimeError("SQL error")

        result = health_check()
        assert result["status"] == "ok"
        assert result["memory_count"] == 0


# ── cross_encoder_rerank ──────────────────────────────────────────────────



# ── TestCrossEncoderRerank ────────────────────────────────────────────────────────

class TestCrossEncoderRerank:
    """Tests for the cross_encoder_rerank MCP tool."""

    def test_invalid_candidates_json(self, mock_mcp_client):
        from server.mcp.main import cross_encoder_rerank

        result = cross_encoder_rerank(
            query="test",
            candidates_json="not valid json",
        )
        assert "Error" in result
        assert "valid JSON" in result

    def test_candidates_not_a_list(self, mock_mcp_client):
        from server.mcp.main import cross_encoder_rerank

        result = cross_encoder_rerank(
            query="test",
            candidates_json='"just a string"',
        )
        assert "Error" in result
        assert "JSON array" in result


# ── get_metrics ───────────────────────────────────────────────────────────



# ── TestGetMetrics ────────────────────────────────────────────────────────

class TestGetMetrics:
    """Tests for the get_metrics MCP tool."""

    def test_returns_metrics(self, mock_mcp_client):
        from server.mcp.main import get_metrics

        mock_mcp_client._sql.side_effect = [
            [{"c": 200}],   # total memories
            [{"c": 150}],   # active memories
            [{"c": 50}],    # L0 count
            [{"c": 60}],    # L1 count
            [{"c": 40}],    # L2 count
            [{"c": 0}],     # distinct peers
            [{"c": 5}],     # kg_node count
            [{"c": 3}],     # kg_edge count
            [{"c": 1}],     # session count
            [{"c": 7}],     # note count
            [{"c": 2}],     # fact count
        ]
        mock_mcp_client.list_workspaces.return_value = [
            {"id": "ws1"}, {"id": "ws2"}
        ]

        result = get_metrics()
        assert result["memories"]["total"] == 200
        assert result["memories"]["active"] == 150
        assert result["memories"]["by_tier"]["L0"] == 50
        assert result["memories"]["by_tier"]["L1"] == 60
        assert result["memories"]["by_tier"]["L2"] == 40
        assert result["workspaces"] == 2
        assert result["peers"] == 0
        assert result["kg_nodes"] == 5
        assert result["kg_edges"] == 3
        assert result["sessions"] == 1
        assert result["notes"] == 7
        assert result["facts"] == 2
        assert "error" not in result

    def test_knowledge_graph_tables_not_found(self, mock_mcp_client):
        from server.mcp.main import get_metrics

        call_count = [0]

        def _sql_side_effect(query, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 6:
                return [{"c": 10}]
            raise RuntimeError("Table not found")

        mock_mcp_client._sql.side_effect = _sql_side_effect
        mock_mcp_client.list_workspaces.return_value = []

        result = get_metrics()
        assert result["kg_nodes"] == -1
        assert result["kg_edges"] == -1
        assert result["sessions"] == -1
        assert result["notes"] == -1
        assert result["facts"] == -1
        assert "error" not in result

    def test_metrics_error_handler(self, mock_mcp_client):
        from server.mcp.main import get_metrics

        mock_mcp_client._sql.side_effect = RuntimeError("Connection lost")

        result = get_metrics()
        assert "error" in result
        assert "Connection lost" in result["error"]


# ── require_api_key decorator ─────────────────────────────────────────────
