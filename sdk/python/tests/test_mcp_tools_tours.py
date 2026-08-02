"""Tests for server/mcp/tools/tours.py MCP tools.

Patches ``server.mcp.tools.app.get_client`` to verify delegation.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    """Patch ``server.mcp.tools.tours.get_client`` to return a MagicMock."""
    with patch("server.mcp.tools.tours.get_client") as mock_fn:
        instance = MagicMock()
        mock_fn.return_value = instance
        yield instance


@pytest.mark.unit
class TestCreateTour:
    """Tests for ``create_tour``."""

    def test_with_description(self, mock_client):
        from server.mcp.tools.tours import create_tour

        result = create_tour(
            workspace_id="ws-1",
            title="Getting Started",
            description="A tour for new users",
        )
        mock_client.create_tour.assert_called_once_with(
            "ws-1", "Getting Started", "A tour for new users"
        )
        assert "created" in result
        assert "Getting Started" in result

    def test_without_description(self, mock_client):
        from server.mcp.tools.tours import create_tour

        result = create_tour(workspace_id="ws-1", title="Quick Tour")
        mock_client.create_tour.assert_called_once_with(
            "ws-1", "Quick Tour", ""
        )
        assert "created" in result

    def test_error_propagates(self, mock_client):
        """Client exception propagates to caller."""
        from server.mcp.tools.tours import create_tour

        mock_client.create_tour.side_effect = PermissionError("access denied")
        with pytest.raises(PermissionError, match="access denied"):
            create_tour(workspace_id="ws-1", title="Fail")

    def test_empty_title(self, mock_client):
        """Creating a tour with an empty title still delegates correctly."""
        from server.mcp.tools.tours import create_tour

        result = create_tour(workspace_id="ws-1", title="")
        mock_client.create_tour.assert_called_once_with("ws-1", "", "")
        assert "created" in result


@pytest.mark.unit
class TestAddTourStop:
    """Tests for ``add_tour_stop``."""

    def test_default_description(self, mock_client):
        from server.mcp.tools.tours import add_tour_stop

        result = add_tour_stop(
            tour_id="tour-1",
            node_id="node-1",
            heading="Introduction",
        )
        mock_client.add_tour_stop.assert_called_once_with(
            "tour-1", "node-1", "Introduction", ""
        )
        assert "Stop 'Introduction' added" in result

    def test_with_description(self, mock_client):
        from server.mcp.tools.tours import add_tour_stop

        result = add_tour_stop(
            tour_id="tour-1",
            node_id="node-1",
            heading="Deep Dive",
            description="Detailed explanation",
        )
        mock_client.add_tour_stop.assert_called_once_with(
            "tour-1", "node-1", "Deep Dive", "Detailed explanation"
        )
        assert "Stop 'Deep Dive' added" in result

    def test_error_propagates(self, mock_client):
        """Client exception on invalid tour or node ID."""
        from server.mcp.tools.tours import add_tour_stop

        mock_client.add_tour_stop.side_effect = ValueError("tour not found")
        with pytest.raises(ValueError, match="tour not found"):
            add_tour_stop(tour_id="invalid", node_id="n1", heading="H")

    def test_empty_heading(self, mock_client):
        """Adding a stop with empty heading still delegates correctly."""
        from server.mcp.tools.tours import add_tour_stop

        result = add_tour_stop(tour_id="tour-1", node_id="node-1", heading="")
        mock_client.add_tour_stop.assert_called_once_with(
            "tour-1", "node-1", "", ""
        )
        assert "Stop '' added" in result


@pytest.mark.unit
class TestDeleteTour:
    """Tests for ``delete_tour``."""

    def test_delegation(self, mock_client):
        from server.mcp.tools.tours import delete_tour

        result = delete_tour(tour_id="tour-123")
        mock_client.delete_tour.assert_called_once_with("tour-123")
        assert "deleted" in result
        assert "tour-123" in result

    def test_error_propagates(self, mock_client):
        """Client exception propagates."""
        from server.mcp.tools.tours import delete_tour

        mock_client.delete_tour.side_effect = RuntimeError("db error")
        with pytest.raises(RuntimeError, match="db error"):
            delete_tour(tour_id="missing")


@pytest.mark.unit
class TestDeleteTourStop:
    """Tests for ``delete_tour_stop``."""

    def test_delegation(self, mock_client):
        from server.mcp.tools.tours import delete_tour_stop

        result = delete_tour_stop(stop_id="stop-123")
        mock_client.delete_tour_stop.assert_called_once_with("stop-123")
        assert "deleted" in result
        assert "stop-123" in result

    def test_error_propagates(self, mock_client):
        """Client exception propagates."""
        from server.mcp.tools.tours import delete_tour_stop

        mock_client.delete_tour_stop.side_effect = PermissionError("forbidden")
        with pytest.raises(PermissionError, match="forbidden"):
            delete_tour_stop(stop_id="restricted")
