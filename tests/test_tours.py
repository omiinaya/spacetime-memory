"""Tests for server/mcp/tools/tours.py - Tour MCP tools."""
import pytest
from server.mcp.tools.tours import (
    create_tour, delete_tour,
    add_tour_stop, delete_tour_stop,
)


class TestToursModule:
    """Test suite for tours.py - verify all expected exports exist."""

    def test_create_tour_exists(self):
        """create_tour should be callable."""
        assert callable(create_tour)

    def test_delete_tour_exists(self):
        """delete_tour should be callable."""
        assert callable(delete_tour)

    def test_add_tour_stop_exists(self):
        """add_tour_stop should be callable."""
        assert callable(add_tour_stop)

    def test_delete_tour_stop_exists(self):
        """delete_tour_stop should be callable."""
        assert callable(delete_tour_stop)
