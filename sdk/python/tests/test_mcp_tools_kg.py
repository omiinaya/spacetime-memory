"""Tests for server/mcp/tools/kg.py — Knowledge Graph MCP tools."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateNode:
    """Tests for the ``create_node`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_create_node_calls_client_method(self, mock_get_client):
        """create_node delegates to get_client().create_node."""
        mock_client = MagicMock()
        expected = {"id": "node-1", "status": "created"}
        mock_client.create_node.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import create_node

        result = create_node(
            workspace_id="ws-1",
            label="Test Node",
            node_type="concept",
            summary="A test",
            metadata_json='{"key": "val"}',
        )

        mock_client.create_node.assert_called_once_with(
            "ws-1", "Test Node", "concept", "A test", '{"key": "val"}'
        )
        assert result == expected

    @patch("server.mcp.tools.kg.get_client")
    def test_create_node_with_defaults(self, mock_get_client):
        """create_node uses empty string defaults for summary and metadata_json."""
        mock_client = MagicMock()
        mock_client.create_node.return_value = {"id": "n2"}
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import create_node

        create_node(workspace_id="ws-1", label="Minimal", node_type="concept")

        mock_client.create_node.assert_called_once_with(
            "ws-1", "Minimal", "concept", "", "{}"
        )


@pytest.mark.unit
class TestUpdateNode:
    """Tests for the ``update_node`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_update_node_calls_client_method(self, mock_get_client):
        """update_node delegates to get_client().update_node."""
        mock_client = MagicMock()
        expected = {"id": "n1", "status": "updated"}
        mock_client.update_node.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import update_node

        result = update_node(
            node_id="n1",
            label="Updated Label",
            node_type="person",
            summary="New summary",
            metadata_json='{"k": "v"}',
            source_memory_id="mem-1",
        )

        mock_client.update_node.assert_called_once_with(
            "n1", "Updated Label", "person", "New summary", '{"k": "v"}', "mem-1"
        )
        assert result == expected

    @patch("server.mcp.tools.kg.get_client")
    def test_update_node_with_defaults(self, mock_get_client):
        """update_node uses sensible defaults."""
        mock_client = MagicMock()
        mock_client.update_node.return_value = {"status": "ok"}
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import update_node

        update_node(node_id="n1", label="New Label")

        mock_client.update_node.assert_called_once_with(
            "n1", "New Label", "concept", "", "{}", ""
        )


@pytest.mark.unit
class TestDeleteNode:
    """Tests for the ``delete_node`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_delete_node_calls_client_method(self, mock_get_client):
        """delete_node delegates to get_client().delete_node."""
        mock_client = MagicMock()
        expected = {"status": "deleted"}
        mock_client.delete_node.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import delete_node

        result = delete_node(node_id="n-42")

        mock_client.delete_node.assert_called_once_with("n-42")
        assert result == expected


# ---------------------------------------------------------------------------
# Edge CRUD
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateEdge:
    """Tests for the ``create_edge`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_create_edge_calls_client_method(self, mock_get_client):
        """create_edge delegates to get_client().create_edge."""
        mock_client = MagicMock()
        expected = {"id": "edge-1", "status": "created"}
        mock_client.create_edge.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import create_edge

        result = create_edge(
            workspace_id="ws-1",
            source_node_id="n1",
            target_node_id="n2",
            relation="knows",
            weight=0.75,
            confidence="INFERRED",
            metadata_json='{"src": "test"}',
            source_memory_id="mem-1",
        )

        mock_client.create_edge.assert_called_once_with(
            "ws-1", "n1", "n2", "knows", 0.75, "INFERRED", '{"src": "test"}', "mem-1"
        )
        assert result == expected

    @patch("server.mcp.tools.kg.get_client")
    def test_create_edge_with_defaults(self, mock_get_client):
        """create_edge uses defaults for optional params."""
        mock_client = MagicMock()
        mock_client.create_edge.return_value = {"id": "e1"}
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import create_edge

        create_edge(
            workspace_id="ws-1",
            source_node_id="n1",
            target_node_id="n2",
            relation="related_to",
        )

        mock_client.create_edge.assert_called_once_with(
            "ws-1", "n1", "n2", "related_to", 1.0, "EXTRACTED", "{}", ""
        )


@pytest.mark.unit
class TestUpdateEdge:
    """Tests for the ``update_edge`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_update_edge_calls_client_method(self, mock_get_client):
        """update_edge delegates to get_client().update_edge."""
        mock_client = MagicMock()
        expected = {"status": "updated"}
        mock_client.update_edge.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import update_edge

        result = update_edge(
            edge_id="e-1",
            relation="informed_by",
            weight=0.9,
            metadata_json='{"method": "test"}',
        )

        mock_client.update_edge.assert_called_once_with(
            "e-1", "informed_by", 0.9, '{"method": "test"}'
        )
        assert result == expected


@pytest.mark.unit
class TestDeleteEdge:
    """Tests for the ``delete_edge`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_delete_edge_calls_client_method(self, mock_get_client):
        """delete_edge delegates to get_client().delete_edge."""
        mock_client = MagicMock()
        expected = {"status": "deleted"}
        mock_client.delete_edge.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import delete_edge

        result = delete_edge(edge_id="e-99")

        mock_client.delete_edge.assert_called_once_with("e-99")
        assert result == expected


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddNodeCitation:
    """Tests for the ``add_node_citation`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_add_node_citation(self, mock_get_client):
        """add_node_citation delegates to get_client().add_node_citation."""
        mock_client = MagicMock()
        expected = {"status": "ok"}
        mock_client.add_node_citation.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import add_node_citation

        result = add_node_citation(
            workspace_id="ws-1",
            node_id="n-1",
            memory_id="mem-1",
            description="supports",
        )

        mock_client.add_node_citation.assert_called_once_with(
            "ws-1", "n-1", "mem-1", "supports"
        )
        assert result == expected


@pytest.mark.unit
class TestAddEdgeCitation:
    """Tests for the ``add_edge_citation`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_add_edge_citation(self, mock_get_client):
        """add_edge_citation delegates to get_client().add_edge_citation."""
        mock_client = MagicMock()
        expected = {"status": "ok"}
        mock_client.add_edge_citation.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import add_edge_citation

        result = add_edge_citation(
            workspace_id="ws-1",
            edge_id="e-1",
            memory_id="mem-2",
            description="evidence",
        )

        mock_client.add_edge_citation.assert_called_once_with(
            "ws-1", "e-1", "mem-2", "evidence"
        )
        assert result == expected


@pytest.mark.unit
class TestGetCitations:
    """Tests for the ``get_citations`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_get_citations(self, mock_get_client):
        """get_citations delegates to get_client().get_citations."""
        mock_client = MagicMock()
        expected = [{"memory_id": "mem-1", "description": "src"}]
        mock_client.get_citations.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import get_citations

        result = get_citations(
            workspace_id="ws-1",
            entity_id="n-1",
            entity_type="node",
        )

        mock_client.get_citations.assert_called_once_with("ws-1", "n-1", "node")
        assert result == expected


# ---------------------------------------------------------------------------
# Query / Retrieval
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQueryGraph:
    """Tests for the ``query_graph`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_query_graph_calls_client_method(self, mock_get_client):
        """query_graph delegates to get_client().query_graph."""
        mock_client = MagicMock()
        expected = [{"id": "n1", "label": "Test"}]
        mock_client.query_graph.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import query_graph

        result = query_graph(workspace_id="ws-1", query="test")

        mock_client.query_graph.assert_called_once_with("ws-1", "test")
        assert result == expected

    @patch("server.mcp.tools.kg.get_client")
    def test_query_graph_with_empty_query(self, mock_get_client):
        """query_graph works with empty query string."""
        mock_client = MagicMock()
        mock_client.query_graph.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import query_graph

        query_graph(workspace_id="ws-1", query="")

        mock_client.query_graph.assert_called_once_with("ws-1", "")


@pytest.mark.unit
class TestGetNode:
    """Tests for the ``get_node`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_get_node_calls_client_method(self, mock_get_client):
        """get_node delegates to get_client().get_node."""
        mock_client = MagicMock()
        expected = [{"id": "n1", "label": "Node"}]
        mock_client.get_node.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import get_node

        result = get_node(id="n-001")

        mock_client.get_node.assert_called_once_with("n-001")
        assert result == expected


@pytest.mark.unit
class TestGetNeighbors:
    """Tests for the ``get_neighbors`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_get_neighbors_calls_client_method(self, mock_get_client):
        """get_neighbors delegates to get_client().get_neighbors."""
        mock_client = MagicMock()
        expected = [{"edge_id": "e1", "target": "n2"}]
        mock_client.get_neighbors.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import get_neighbors

        result = get_neighbors(node_id="n-001")

        mock_client.get_neighbors.assert_called_once_with("n-001")
        assert result == expected


@pytest.mark.unit
class TestGetCommunity:
    """Tests for the ``get_community`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_get_community_calls_client_method(self, mock_get_client):
        """get_community delegates to get_client().get_community."""
        mock_client = MagicMock()
        expected = {"community_id": 1, "nodes": ["n1", "n2"]}
        mock_client.get_community.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import get_community

        result = get_community(community_id=42)

        mock_client.get_community.assert_called_once_with(42)
        assert result == expected


@pytest.mark.unit
class TestGetEdgeHistory:
    """Tests for the ``get_edge_history`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_get_edge_history(self, mock_get_client):
        """get_edge_history delegates to get_client().get_edge_history."""
        mock_client = MagicMock()
        expected = [{"edge_group_id": "eg-1", "version": 1}]
        mock_client.get_edge_history.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import get_edge_history

        result = get_edge_history(edge_group_id="eg-001")

        mock_client.get_edge_history.assert_called_once_with("eg-001")
        assert result == expected


class TestGetEdgeAsOf:
    """Tests for the ``get_edge_as_of`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_get_edge_as_of(self, mock_get_client):
        """get_edge_as_of delegates to get_client().get_edge_as_of."""
        mock_client = MagicMock()
        expected = {"edge_group_id": "eg-1", "version": 2, "valid_at": 200, "invalid_at": 0}
        mock_client.get_edge_as_of.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import get_edge_as_of

        result = get_edge_as_of(edge_group_id="eg-001", timestamp_micros=150)

        mock_client.get_edge_as_of.assert_called_once_with("eg-001", 150)
        assert result == expected


# ---------------------------------------------------------------------------
# Compute / Analytics
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComputePagerank:
    """Tests for the ``compute_pagerank`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_compute_pagerank(self, mock_get_client):
        """compute_pagerank calls client and reads back results."""
        mock_client = MagicMock()
        mock_client._sql_param.return_value = [
            {"node_id": "n1", "rank": 1.0, "score": 0.5}
        ]
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import compute_pagerank

        result = compute_pagerank(workspace_id="ws-1", damping=0.85, max_iterations=100)

        mock_client.compute_pagerank.assert_called_once_with("ws-1", 0.85, 100)
        mock_client._sql_param.assert_called_once()
        import json

        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["node_id"] == "n1"


@pytest.mark.unit
class TestComputeCommunityHierarchy:
    """Tests for the ``compute_community_hierarchy`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_compute_community_hierarchy(self, mock_get_client):
        """compute_community_hierarchy calls client and reads back results."""
        mock_client = MagicMock()
        mock_client._sql_param.side_effect = [
            [{"edge_id": "h1", "depth": 1}],  # edges query
            [{"cluster_id": "c1", "depth": 1}],  # clusters query
        ]
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import compute_community_hierarchy

        result = compute_community_hierarchy(workspace_id="ws-1")

        mock_client.compute_community_hierarchy.assert_called_once_with("ws-1")
        assert mock_client._sql_param.call_count == 2

        import json

        parsed = json.loads(result)
        assert "edges" in parsed
        assert "clusters" in parsed
        assert len(parsed["edges"]) == 1
        assert len(parsed["clusters"]) == 1


@pytest.mark.unit
class TestComputeKgStats:
    """Tests for the ``compute_kg_stats`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_compute_kg_stats(self, mock_get_client):
        """compute_kg_stats delegates to get_client().compute_kg_stats."""
        mock_client = MagicMock()
        stats = {
            "node_count": 10,
            "edge_count": 15,
            "community_count": 3,
            "orphan_nodes": 2,
            "avg_degree": 3.0,
        }
        mock_client.compute_kg_stats.return_value = stats
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import compute_kg_stats

        result = compute_kg_stats(workspace_id="ws-1")

        mock_client.compute_kg_stats.assert_called_once_with("ws-1")
        import json

        parsed = json.loads(result)
        assert parsed["node_count"] == 10

    @patch("server.mcp.tools.kg.get_client")
    def test_compute_kg_stats_none_result(self, mock_get_client):
        """compute_kg_stats returns error JSON when client returns None."""
        mock_client = MagicMock()
        mock_client.compute_kg_stats.return_value = None
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import compute_kg_stats

        result = compute_kg_stats(workspace_id="ws-1")

        import json

        parsed = json.loads(result)
        assert parsed["workspace_id"] == "ws-1"
        assert "error" in parsed


@pytest.mark.unit
class TestGetMemoryStats:
    """Tests for the ``get_memory_stats`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_get_memory_stats(self, mock_get_client):
        """get_memory_stats delegates to get_client().get_memory_stats."""
        mock_client = MagicMock()
        stats = {
            "total_memories": 100,
            "active_memories": 95,
            "by_tier": {"L0": 10, "L1": 30, "L2": 60},
        }
        mock_client.get_memory_stats.return_value = stats
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import get_memory_stats

        result = get_memory_stats(workspace_id="ws-1")

        mock_client.get_memory_stats.assert_called_once_with("ws-1")
        import json

        parsed = json.loads(result)
        assert parsed["total_memories"] == 100

    @patch("server.mcp.tools.kg.get_client")
    def test_get_memory_stats_none_result(self, mock_get_client):
        """get_memory_stats returns error JSON when client returns None."""
        mock_client = MagicMock()
        mock_client.get_memory_stats.return_value = None
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import get_memory_stats

        result = get_memory_stats(workspace_id="ws-1")

        import json

        parsed = json.loads(result)
        assert parsed["workspace_id"] == "ws-1"
        assert "error" in parsed


# ---------------------------------------------------------------------------
# Community Detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetectCommunities:
    """Tests for the ``detect_communities`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_detect_communities(self, mock_get_client):
        """detect_communities delegates to get_client().detect_communities."""
        mock_client = MagicMock()
        expected = {
            "status": "ok",
            "nodes_processed": 20,
            "communities_found": 4,
        }
        mock_client.detect_communities.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import detect_communities

        result = detect_communities(workspace_id="ws-1")

        mock_client.detect_communities.assert_called_once_with("ws-1")
        assert result == expected

    @patch("server.mcp.tools.kg.get_client")
    def test_detect_communities_none_result(self, mock_get_client):
        """detect_communities returns error dict when client returns None."""
        mock_client = MagicMock()
        mock_client.detect_communities.return_value = None
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import detect_communities

        result = detect_communities(workspace_id="ws-1")

        assert result == {"workspace_id": "ws-1", "error": "No result"}


@pytest.mark.unit
class TestSeedCommunities:
    """Tests for the ``seed_communities`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_seed_communities(self, mock_get_client):
        """seed_communities delegates to get_client().seed_communities."""
        mock_client = MagicMock()
        expected = {"status": "ok", "seeded": 5}
        mock_client.seed_communities.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import seed_communities

        result = seed_communities(workspace_id="ws-1")

        mock_client.seed_communities.assert_called_once_with("ws-1")
        assert result == expected


@pytest.mark.unit
class TestDetectBridgeNodes:
    """Tests for the ``detect_bridge_nodes`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_detect_bridge_nodes(self, mock_get_client):
        """detect_bridge_nodes delegates to get_client().detect_bridge_nodes."""
        mock_client = MagicMock()
        expected = [{"node_id": "n1", "bridge_score": 2.5}]
        mock_client.detect_bridge_nodes.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import detect_bridge_nodes

        result = detect_bridge_nodes(
            workspace_id="ws-1", limit=10, min_communities=2
        )

        mock_client.detect_bridge_nodes.assert_called_once_with(
            "ws-1", 10, 2
        )
        import json

        parsed = json.loads(result)
        assert parsed[0]["bridge_score"] == 2.5


# ---------------------------------------------------------------------------
# Graph Traversal
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGraphBfs:
    """Tests for the ``graph_bfs`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_graph_bfs(self, mock_get_client):
        """graph_bfs delegates to get_client().graph_bfs."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import graph_bfs

        result = graph_bfs(
            workspace_id="ws-1",
            start_node_id="n-start",
            max_depth=4,
        )

        mock_client.graph_bfs.assert_called_once_with("ws-1", "n-start", 4)
        assert "BFS from n-start" in result
        assert "depth 4" in result


@pytest.mark.unit
class TestShortestPath:
    """Tests for the ``shortest_path`` tool."""

    @patch("server.mcp.tools.kg.get_client")
    def test_shortest_path(self, mock_get_client):
        """shortest_path delegates to get_client().shortest_path."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.kg import shortest_path

        result = shortest_path(
            workspace_id="ws-1",
            source_id="n-src",
            target_id="n-tgt",
            max_hops=5,
        )

        mock_client.shortest_path.assert_called_once_with(
            "ws-1", "n-src", "n-tgt", 5
        )
        assert "Shortest path computed" in result
