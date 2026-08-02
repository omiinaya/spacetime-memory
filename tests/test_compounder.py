"""Tests for server/mcp/tools/compounder.py - Compound MCP tools."""
import pytest
from server.mcp.tools.compounder import (
    store_answer, cross_link, export_workspace,
    generate_overview, find_near_duplicates,
    create_entity_page, create_concept_page, create_comparison_page,
    backup,
)


class TestCompounderModule:
    """Test suite for compounder.py - verify all expected exports exist."""

    def test_store_answer_exists(self):
        assert callable(store_answer)

    def test_cross_link_exists(self):
        assert callable(cross_link)

    def test_export_workspace_exists(self):
        assert callable(export_workspace)

    def test_generate_overview_exists(self):
        assert callable(generate_overview)

    def test_find_near_duplicates_exists(self):
        assert callable(find_near_duplicates)

    def test_create_entity_page_exists(self):
        assert callable(create_entity_page)

    def test_create_concept_page_exists(self):
        assert callable(create_concept_page)

    def test_create_comparison_page_exists(self):
        assert callable(create_comparison_page)

    def test_backup_exists(self):
        assert callable(backup)
