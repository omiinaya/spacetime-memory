"""Tests for server/mcp/tools/mental.py MCP tools.

Patches ``server.mcp.tools.app.get_client`` to verify delegation.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    """Patch ``server.mcp.tools.mental.get_client`` to return a MagicMock.

    Patches the module-level reference directly so that even if the module
    is already cached by ``sys.modules``, the attribute is replaced.
    """
    with patch("server.mcp.tools.mental.get_client") as mock_fn:
        instance = MagicMock()
        mock_fn.return_value = instance
        yield instance


@pytest.mark.unit
class TestSynthesizeMentalModels:
    """Tests for ``synthesize_mental_models``."""

    def test_success(self, mock_client):
        from server.mcp.tools.mental import synthesize_mental_models

        result = synthesize_mental_models(
            workspace_id="ws-abc",
            memory_ids_json='["mem1","mem2"]',
        )
        mock_client.synthesize_mental_models.assert_called_once_with(
            "ws-abc", ["mem1", "mem2"]
        )
        assert "Mental model synthesis requested" in result
        assert "ws-abc" in result

    def test_invalid_json_raises(self, mock_client):
        """Passing invalid JSON raises json.JSONDecodeError."""
        from server.mcp.tools.mental import synthesize_mental_models

        with pytest.raises(json.JSONDecodeError):
            synthesize_mental_models(
                workspace_id="ws-1",
                memory_ids_json="not-json",
            )

    def test_error_propagates(self, mock_client):
        """Client exception propagates to caller."""
        from server.mcp.tools.mental import synthesize_mental_models

        mock_client.synthesize_mental_models.side_effect = ConnectionError(
            "service unavailable"
        )
        with pytest.raises(ConnectionError, match="service unavailable"):
            synthesize_mental_models(
                workspace_id="ws-1",
                memory_ids_json='["mem1"]',
            )


@pytest.mark.unit
class TestGetMentalModel:
    """Tests for ``get_mental_model``."""

    def test_returns_json(self, mock_client):
        from server.mcp.tools.mental import get_mental_model

        mock_client._sql_param.return_value = [
            {"id": "mm1", "content": "test content"}
        ]
        result = get_mental_model(id="mm1")
        mock_client._sql_param.assert_called_once_with(
            "SELECT * FROM mental_model WHERE id = ?",
            "mm1",
        )
        parsed = json.loads(result)
        assert parsed[0]["id"] == "mm1"

    def test_empty_result(self, mock_client):
        from server.mcp.tools.mental import get_mental_model

        mock_client._sql_param.return_value = []
        result = get_mental_model(id="nonexistent")
        parsed = json.loads(result)
        assert parsed == []

    def test_error_propagates(self, mock_client):
        """Client exception propagates."""
        from server.mcp.tools.mental import get_mental_model

        mock_client._sql_param.side_effect = RuntimeError("db connection lost")
        with pytest.raises(RuntimeError, match="db connection lost"):
            get_mental_model(id="mm1")

    def test_multiple_results(self, mock_client):
        """SQL returning multiple rows (edge case) is handled."""
        from server.mcp.tools.mental import get_mental_model

        mock_client._sql_param.return_value = [
            {"id": "mm1", "content": "first"},
            {"id": "mm2", "content": "second"},
        ]
        result = get_mental_model(id="mm1")
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[1]["id"] == "mm2"


@pytest.mark.unit
class TestListMentalModels:
    """Tests for ``list_mental_models``."""

    def test_with_status(self, mock_client):
        from server.mcp.tools.mental import list_mental_models

        mock_client._sql_param.return_value = [
            {"id": "mm1", "status": "completed"}
        ]
        result = list_mental_models(workspace_id="ws-1", status="completed")
        mock_client._sql_param.assert_called_once_with(
            "SELECT * FROM mental_model WHERE "
            "workspace_id = ? AND status = ? "
            "ORDER BY created_at DESC",
            "ws-1", "completed",
        )
        parsed = json.loads(result)
        assert parsed[0]["status"] == "completed"

    def test_without_status(self, mock_client):
        from server.mcp.tools.mental import list_mental_models

        mock_client._sql_param.return_value = []
        result = list_mental_models(workspace_id="ws-1")
        mock_client._sql_param.assert_called_once_with(
            "SELECT * FROM mental_model WHERE "
            "workspace_id = ? "
            "ORDER BY created_at DESC",
            "ws-1",
        )
        assert json.loads(result) == []

    def test_error_propagates(self, mock_client):
        """Client exception propagates."""
        from server.mcp.tools.mental import list_mental_models

        mock_client._sql_param.side_effect = ConnectionError("db timeout")
        with pytest.raises(ConnectionError, match="db timeout"):
            list_mental_models(workspace_id="ws-1")

    def test_multiple_results(self, mock_client):
        """Multiple models returned correctly."""
        from server.mcp.tools.mental import list_mental_models

        mock_client._sql_param.return_value = [
            {"id": "mm1", "status": "completed"},
            {"id": "mm2", "status": "pending"},
        ]
        result = list_mental_models(workspace_id="ws-1", status="")
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[1]["id"] == "mm2"


@pytest.mark.unit
class TestDeleteMentalModel:
    """Tests for ``delete_mental_model``."""

    def test_delegation(self, mock_client):
        from server.mcp.tools.mental import delete_mental_model

        result = delete_mental_model(model_id="mm-12345")
        mock_client.delete_mental_model.assert_called_once_with("mm-12345")
        assert "deleted" in result
        assert "mm-12345" in result

    def test_error_propagates(self, mock_client):
        """Client exception propagates."""
        from server.mcp.tools.mental import delete_mental_model

        mock_client.delete_mental_model.side_effect = PermissionError("forbidden")
        with pytest.raises(PermissionError, match="forbidden"):
            delete_mental_model(model_id="restricted")


@pytest.mark.unit
class TestUpdateMentalModel:
    """Tests for ``update_mental_model``."""

    def test_with_defaults(self, mock_client):
        from server.mcp.tools.mental import update_mental_model

        result = update_mental_model(
            model_id="mm-1",
            content="updated content",
        )
        mock_client.update_mental_model.assert_called_once_with(
            "mm-1", "updated content", 0.5, "completed"
        )
        assert "updated" in result

    def test_custom_values(self, mock_client):
        from server.mcp.tools.mental import update_mental_model

        result = update_mental_model(
            model_id="mm-1",
            content="new content",
            confidence=0.9,
            status="pending",
        )
        mock_client.update_mental_model.assert_called_once_with(
            "mm-1", "new content", 0.9, "pending"
        )
        assert "updated" in result

    def test_error_propagates(self, mock_client):
        """Client exception propagates."""
        from server.mcp.tools.mental import update_mental_model

        mock_client.update_mental_model.side_effect = RuntimeError("update failed")
        with pytest.raises(RuntimeError, match="update failed"):
            update_mental_model(model_id="mm-1", content="fail")
