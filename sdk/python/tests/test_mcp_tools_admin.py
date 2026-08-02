"""Tests for server/mcp/tools/admin.py — Health, monitoring, API key, decay, connector tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _patch_get_client():
    """Patch get_client at the module level where admin.py imports it."""
    with patch("server.mcp.tools.admin.get_client") as mock_fn:
        instance = MagicMock()
        mock_fn.return_value = instance
        yield instance


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHealthCheck:
    """Tests for the health_check MCP tool."""

    def test_all_ok(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import health_check

        _patch_get_client.list_workspaces.return_value = ["ws1", "ws2"]
        _patch_get_client.check_embedder_health.return_value = {"status": "ok"}
        _patch_get_client.check_tantivy_health.return_value = {
            "status": "ok",
            "reachable": True,
        }
        _patch_get_client._sql.return_value = [{"cnt": 42}]

        result = health_check()
        assert result["status"] == "ok"
        assert result["spacetimedb"] == "ok"
        assert result["embedder"] == "ok"
        assert result["tantivy"] == "ok"
        assert result["workspace_count"] == 2
        assert result["memory_count"] == 42

    def test_spacetimedb_error(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import health_check

        _patch_get_client.list_workspaces.side_effect = RuntimeError("STDB down")
        _patch_get_client.check_embedder_health.return_value = {"status": "ok"}
        _patch_get_client.check_tantivy_health.return_value = {
            "status": "ok",
            "reachable": True,
        }

        result = health_check()
        assert result["status"] == "degraded"
        assert "error" in result["spacetimedb"]

    def test_embedder_error(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import health_check

        _patch_get_client.list_workspaces.return_value = []
        _patch_get_client.check_embedder_health.side_effect = RuntimeError("no GPU")
        _patch_get_client.check_tantivy_health.return_value = {
            "status": "ok",
            "reachable": True,
        }

        result = health_check()
        assert result["status"] == "degraded"
        assert "error" in result["embedder"]

    def test_tantivy_not_reachable(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import health_check

        _patch_get_client.list_workspaces.return_value = []
        _patch_get_client.check_embedder_health.return_value = {"status": "ok"}
        _patch_get_client.check_tantivy_health.return_value = {
            "status": "ok",
            "reachable": False,
        }

        result = health_check()
        assert result["status"] == "degraded"

    def test_tantivy_error(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import health_check

        _patch_get_client.list_workspaces.return_value = []
        _patch_get_client.check_embedder_health.return_value = {"status": "ok"}
        _patch_get_client.check_tantivy_health.side_effect = RuntimeError(
            "Tantivy crash"
        )

        result = health_check()
        assert result["status"] == "degraded"
        assert "error" in result["tantivy"]

    def test_sql_fails_gracefully(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import health_check

        _patch_get_client.list_workspaces.return_value = []
        _patch_get_client.check_embedder_health.return_value = {"status": "ok"}
        _patch_get_client.check_tantivy_health.return_value = {
            "status": "ok",
            "reachable": True,
        }
        _patch_get_client._sql.side_effect = RuntimeError("SQL fail")

        result = health_check()
        # SQL failure should be silently caught, memory_count stays 0
        assert result["status"] == "ok"
        assert result["memory_count"] == 0


# ---------------------------------------------------------------------------
# get_metrics
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetMetrics:
    """Tests for the get_metrics MCP tool."""

    def test_returns_metrics(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import get_metrics

        def sql_side_effect(query: str):
            if "COUNT(*) as c FROM memory" in query and "WHERE" not in query:
                return [{"c": 100}]
            if "COUNT(*) as c FROM memory WHERE is_active" in query:
                return [{"c": 80}]
            if "tier = 'L0'" in query:
                return [{"c": 40}]
            if "tier = 'L1'" in query:
                return [{"c": 30}]
            if "tier = 'L2'" in query:
                return [{"c": 10}]
            if "DISTINCT peer_id" in query:
                return [{"c": 5}]
            if "FROM kg_node" in query:
                return [{"c": 20}]
            if "FROM kg_edge" in query:
                return [{"c": 35}]
            if "FROM session" in query:
                return [{"c": 3}]
            if "FROM note" in query:
                return [{"c": 15}]
            if "FROM fact" in query:
                return [{"c": 50}]
            return []

        _patch_get_client._sql.side_effect = sql_side_effect
        _patch_get_client.list_workspaces.return_value = ["ws1", "ws2", "ws3"]

        result = get_metrics()
        assert result["memories"]["total"] == 100
        assert result["memories"]["active"] == 80
        assert result["memories"]["by_tier"]["L0"] == 40
        assert result["memories"]["by_tier"]["L1"] == 30
        assert result["memories"]["by_tier"]["L2"] == 10
        assert result["workspaces"] == 3
        assert result["peers"] == 5
        assert result["kg_nodes"] == 20
        assert result["kg_edges"] == 35
        assert result["sessions"] == 3
        assert result["notes"] == 15
        assert result["facts"] == 50

    def test_sql_error_returns_error_key(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import get_metrics

        _patch_get_client._sql.side_effect = RuntimeError("DB unreachable")
        result = get_metrics()
        assert "error" in result
        assert "DB unreachable" in result["error"]

    def test_missing_tables_return_minus_one(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import get_metrics

        def sql_side_effect(query: str):
            if "FROM memory" in query:
                return [{"c": 10}]
            if "DISTINCT peer_id" in query:
                return [{"c": 2}]
            # Raise for tables that may not exist
            raise RuntimeError("table not found")

        _patch_get_client._sql.side_effect = sql_side_effect
        _patch_get_client.list_workspaces.return_value = ["ws1"]

        result = get_metrics()
        assert result["memories"]["total"] == 10
        assert result["workspaces"] == 1
        assert result["kg_nodes"] == -1
        assert result["kg_edges"] == -1
        assert result["sessions"] == -1
        assert result["notes"] == -1
        assert result["facts"] == -1


# ---------------------------------------------------------------------------
# create_api_key
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateApiKey:
    """Tests for the create_api_key MCP tool."""

    def test_creates_key(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import create_api_key

        _patch_get_client.create_api_key.return_value = {
            "api_key": "sk-1234",
            "id": "key_abc123",
        }
        result = create_api_key(
            workspace_id="ws1", name="test-key", permissions='["read", "write"]'
        )
        assert "sk-1234" in result
        assert "key_abc123" in result
        assert "created successfully" in result
        _patch_get_client.create_api_key.assert_called_once_with(
            workspace_id="ws1",
            name="test-key",
            permissions='["read", "write"]',
        )

    def test_default_permissions(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import create_api_key

        _patch_get_client.create_api_key.return_value = {
            "api_key": "sk-5678",
            "id": "key_def",
        }
        result = create_api_key(workspace_id="ws1", name="default-key")
        assert "sk-5678" in result
        _patch_get_client.create_api_key.assert_called_once_with(
            workspace_id="ws1",
            name="default-key",
            permissions='["read"]',
        )


# ---------------------------------------------------------------------------
# deactivate_api_key
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeactivateApiKey:
    """Tests for the deactivate_api_key MCP tool."""

    def test_deactivates(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import deactivate_api_key

        _patch_get_client.deactivate_api_key.return_value = {"status": "ok"}
        result = deactivate_api_key(key_id="key_abc123")
        assert "deactivated" in result
        assert "key_abc123" in result
        _patch_get_client.deactivate_api_key.assert_called_once_with("key_abc123")

    def test_with_unknown_status(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import deactivate_api_key

        _patch_get_client.deactivate_api_key.return_value = {"status": "already_inactive"}
        result = deactivate_api_key(key_id="key_xyz")
        assert "key_xyz" in result
        assert "already_inactive" in result


# ---------------------------------------------------------------------------
# list_api_keys
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListApiKeys:
    """Tests for the list_api_keys MCP tool."""

    def test_lists_keys(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import list_api_keys

        _patch_get_client.list_api_keys.return_value = [
            {
                "api_key_id": "key_abc",
                "name": "dev-key",
                "permissions": '["read"]',
                "is_active": True,
                "created_at": 1000,
            },
        ]
        result = list_api_keys(workspace_id="ws1")
        assert "dev-key" in result
        assert "key_abc" in result
        _patch_get_client.list_api_keys.assert_called_once_with("ws1")

    def test_empty(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import list_api_keys

        _patch_get_client.list_api_keys.return_value = []
        result = list_api_keys(workspace_id="empty_ws")
        assert "No API keys found" in result


# ---------------------------------------------------------------------------
# set_decay_model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSetDecayModel:
    """Tests for the set_decay_model MCP tool."""

    def test_linear_default(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import set_decay_model

        _patch_get_client.set_decay_model.return_value = {"status": "ok"}
        result = set_decay_model(workspace_id="ws1")
        assert "linear" in result
        _patch_get_client.set_decay_model.assert_called_once_with(
            workspace_id="ws1",
            model="linear",
            decay_rate=0.005,
            max_days=90,
            weibull_shape=0.6,
            weibull_scale=30.0,
        )

    def test_weibull(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import set_decay_model

        _patch_get_client.set_decay_model.return_value = {"status": "ok"}
        result = set_decay_model(
            workspace_id="ws1",
            model="weibull",
            weibull_shape=0.8,
            weibull_scale=45.0,
        )
        assert "weibull" in result
        _patch_get_client.set_decay_model.assert_called_once_with(
            workspace_id="ws1",
            model="weibull",
            decay_rate=0.005,
            max_days=90,
            weibull_shape=0.8,
            weibull_scale=45.0,
        )


# ---------------------------------------------------------------------------
# get_decay_config
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetDecayConfig:
    """Tests for the get_decay_config MCP tool."""

    def test_returns_config(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import get_decay_config

        _patch_get_client.get_decay_config.return_value = {
            "model": "linear",
            "decay_rate": 0.005,
            "max_days": 90,
        }
        result = get_decay_config(workspace_id="ws1")
        assert "model" in result
        assert "decay_rate" in result
        _patch_get_client.get_decay_config.assert_called_once_with("ws1")

    def test_no_config(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import get_decay_config

        _patch_get_client.get_decay_config.return_value = None
        result = get_decay_config(workspace_id="ws1")
        assert "No decay configuration" in result


# ---------------------------------------------------------------------------
# cross_encoder_rerank
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCrossEncoderRerank:
    """Tests for the cross_encoder_rerank MCP tool."""

    def test_reranks(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import cross_encoder_rerank

        candidates = [
            {"memory_content": "text a", "id": "1"},
            {"memory_content": "text b", "id": "2"},
        ]
        mock_result = [
            {"memory_content": "text b", "id": "2", "cross_encoder_score": 0.95},
            {"memory_content": "text a", "id": "1", "cross_encoder_score": 0.45},
        ]

        with patch(
            "spacetime_memory.cross_encoder.cross_encoder_rerank"
        ) as mock_rerank:
            mock_rerank.return_value = mock_result
            result_str = cross_encoder_rerank(
                query="test query",
                candidates_json=json.dumps(candidates),
            )
            result = json.loads(result_str)
            assert len(result) == 2
            assert result[0]["cross_encoder_score"] == 0.95
            mock_rerank.assert_called_once_with(
                query="test query",
                candidates=candidates,
                content_key="memory_content",
                top_k=20,
            )

    def test_invalid_json(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import cross_encoder_rerank

        result = cross_encoder_rerank(query="q", candidates_json="not json")
        assert "Error" in result

    def test_not_a_list(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import cross_encoder_rerank

        result = cross_encoder_rerank(query="q", candidates_json='"string"')
        assert "Error" in result


# ---------------------------------------------------------------------------
# ping
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPing:
    """Tests for the ping MCP tool."""

    def test_reachable(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import ping

        _patch_get_client.ping.return_value = {
            "status": "ok",
            "latency_ms": 5,
        }
        result = ping()
        assert "reachable" in result
        assert "5ms" in result

    def test_unreachable(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import ping

        _patch_get_client.ping.return_value = {
            "status": "error",
            "message": "connection refused",
            "latency_ms": "N/A",
        }
        result = ping()
        assert "unreachable" in result
        assert "connection refused" in result


# ---------------------------------------------------------------------------
# register_connector
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegisterConnector:
    """Tests for the register_connector MCP tool."""

    def test_registers(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import register_connector

        result = register_connector(
            name="arXiv Feed",
            connector_type="rss",
            config_json='{"url": "https://export.arxiv.org/rss/cs"}',
            workspace_id="ws1",
            schedule_secs=300,
        )
        assert "arXiv Feed" in result
        _patch_get_client.register_connector.assert_called_once_with(
            name="arXiv Feed",
            connector_type="rss",
            config_json='{"url": "https://export.arxiv.org/rss/cs"}',
            workspace_id="ws1",
            schedule_secs=300,
        )


# ---------------------------------------------------------------------------
# update_connector
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateConnector:
    """Tests for the update_connector MCP tool."""

    def test_updates(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import update_connector

        result = update_connector(
            id="conn_abc",
            name="Updated Feed",
            connector_type="rss",
            config_json='{"url": "https://new.url"}',
            workspace_id="ws1",
            schedule_secs=600,
            is_active=False,
        )
        assert "updated" in result
        _patch_get_client.update_connector.assert_called_once_with(
            id="conn_abc",
            name="Updated Feed",
            connector_type="rss",
            config_json='{"url": "https://new.url"}',
            workspace_id="ws1",
            schedule_secs=600,
            is_active=False,
        )

    def test_default_active(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import update_connector

        update_connector(
            id="c1",
            name="n",
            connector_type="github",
            config_json="{}",
            workspace_id="w",
            schedule_secs=100,
        )
        _patch_get_client.update_connector.assert_called_once()
        assert _patch_get_client.update_connector.call_args[1]["is_active"] is True


# ---------------------------------------------------------------------------
# delete_connector
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteConnector:
    """Tests for the delete_connector MCP tool."""

    def test_deletes(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import delete_connector

        result = delete_connector(id="conn_abc")
        assert "deleted" in result
        _patch_get_client.delete_connector.assert_called_once_with("conn_abc")


# ---------------------------------------------------------------------------
# list_connectors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListConnectors:
    """Tests for the list_connectors MCP tool."""

    def test_lists_connectors(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import list_connectors

        _patch_get_client._sql.return_value = [
            {
                "id": "conn_abc123",
                "name": "arXiv RSS",
                "connector_type": "rss",
                "workspace_id": "ws1",
                "schedule_secs": 300,
                "is_active": True,
                "created_at": 1000,
            },
        ]
        result = list_connectors()
        assert "arXiv RSS" in result
        assert "rss" in result
        _patch_get_client._sql.assert_called_once()

    def test_empty(self, _patch_get_client: MagicMock):
        from server.mcp.tools.admin import list_connectors

        _patch_get_client._sql.return_value = []
        result = list_connectors()
        assert "No connectors registered" in result
