"""Tests for server/mcp/tools/kg.py - Knowledge Graph MCP tools."""
import pytest
from server.mcp.tools.kg import (
    create_node, create_edge, delete_node, delete_edge,
    compute_pagerank, compute_community_hierarchy, compute_kg_stats,
    add_node_citation, add_edge_citation,
)


class TestKnowledgeGraphModule:
    """Test suite for kg.py - verify all expected exports exist."""

    def test_create_node_exists(self):
        assert callable(create_node)

    def test_create_edge_exists(self):
        assert callable(create_edge)

    def test_delete_node_exists(self):
        assert callable(delete_node)

    def test_delete_edge_exists(self):
        assert callable(delete_edge)

    def test_compute_pagerank_exists(self):
        assert callable(compute_pagerank)

    def test_compute_community_hierarchy_exists(self):
        assert callable(compute_community_hierarchy)

    def test_compute_kg_stats_exists(self):
        assert callable(compute_kg_stats)

    def test_add_node_citation_exists(self):
        assert callable(add_node_citation)

    def test_add_edge_citation_exists(self):
        assert callable(add_edge_citation)
