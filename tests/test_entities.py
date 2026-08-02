"""Tests for server/mcp/tools/entities.py - Entity MCP tools."""
import pytest
from server.mcp.tools.entities import resolve_entity, add_alias, create_entity_link


class TestEntitiesModule:
    """Test suite for entities.py - verify all expected exports exist."""

    def test_resolve_entity_exists(self):
        assert callable(resolve_entity)

    def test_add_alias_exists(self):
        assert callable(add_alias)

    def test_create_entity_link_exists(self):
        assert callable(create_entity_link)
