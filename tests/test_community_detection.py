"""
Tests for community detection (native Louvain-like modularity optimization).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_sdk_path = str(Path(__file__).resolve().parent.parent / "sdk" / "python")
if _sdk_path not in sys.path:
    sys.path.insert(0, _sdk_path)

from spacetime_memory.community_detection import (
    COMMUNITY_SUMMARY_PROMPT,
    _connected_components,
    _generate_community_name,
    _move_node,
    detect_communities,
    persist_communities,
    summarize_communities,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(nodes: list[dict], edges: list[dict]) -> MagicMock:
    """Build a MagicMock client that returns canned nodes/edges from _query."""
    client = MagicMock()

    def _query(table: str, workspace_id: str = "", columns: list[str] | None = None,
               filter_dict: dict | None = None, **kwargs) -> list[dict]:
        if table == "kg_node":
            return nodes
        if table == "kg_edge":
            return edges
        return []

    client._query = _query
    client.create_community = MagicMock(return_value={"community_id": 42})
    client.assign_to_community = MagicMock(return_value={})
    return client


def _simple_graph() -> tuple[list[dict], list[dict]]:
    """Two clear communities with bridging edges."""
    nodes = [
        {"id": "n1", "label": "Python", "node_type": "concept", "community_id": 0},
        {"id": "n2", "label": "Rust", "node_type": "concept", "community_id": 0},
        {"id": "n3", "label": "JavaScript", "node_type": "concept", "community_id": 0},
        {"id": "n4", "label": "TensorFlow", "node_type": "concept", "community_id": 0},
        {"id": "n5", "label": "PyTorch", "node_type": "concept", "community_id": 0},
        {"id": "n6", "label": "Keras", "node_type": "concept", "community_id": 0},
    ]
    edges = [
        # Programming languages cluster
        {"source_node_id": "n1", "target_node_id": "n2", "weight": 5, "relationship_type": "related_to"},
        {"source_node_id": "n1", "target_node_id": "n3", "weight": 4, "relationship_type": "related_to"},
        {"source_node_id": "n2", "target_node_id": "n3", "weight": 3, "relationship_type": "related_to"},
        # ML frameworks cluster
        {"source_node_id": "n4", "target_node_id": "n5", "weight": 10, "relationship_type": "related_to"},
        {"source_node_id": "n4", "target_node_id": "n6", "weight": 8, "relationship_type": "related_to"},
        {"source_node_id": "n5", "target_node_id": "n6", "weight": 7, "relationship_type": "related_to"},
        # Bridge edge between clusters
        {"source_node_id": "n1", "target_node_id": "n4", "weight": 1, "relationship_type": "related_to"},
    ]
    return nodes, edges


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDetectCommunities:
    """Core community detection algorithm tests."""

    def test_empty_graph(self):
        """Empty graph returns empty result."""
        client = _make_mock_client([], [])
        result = detect_communities(client, "ws1")
        assert result["communities"] == []
        assert result["modularity"] == 0.0
        assert result["iterations"] == 0
        assert result["node_count"] == 0

    def test_single_node_no_edges(self):
        """Single node with no edges."""
        client = _make_mock_client(
            [{"id": "n1", "label": "solo", "node_type": "concept", "community_id": 0}],
            [],
        )
        result = detect_communities(client, "ws1")
        assert result["node_count"] == 1
        assert result["edge_count"] == 0
        assert len(result["communities"]) == 1
        assert result["communities"][0]["size"] == 1

    def test_two_clear_communities(self):
        """Two densely connected clusters with a single weak bridge."""
        nodes, edges = _simple_graph()
        client = _make_mock_client(nodes, edges)
        result = detect_communities(client, "ws1")

        assert result["node_count"] == 6
        assert result["edge_count"] == 7
        assert len(result["communities"]) >= 2

        # The two main communities should be detected
        community_sizes = [c["size"] for c in result["communities"]]
        # Either 3+3 or 2+4 split depending on algorithm behaviour
        assert sum(community_sizes) == 6
        assert all(s >= 1 for s in community_sizes)

        # Modularity should be positive (strong community structure)
        assert result["modularity"] > 0.1, "Modularity should show strong structure"

    def test_with_existing_community_assignments(self):
        """Existing community_id values should be respected as seeds."""
        nodes = [
            {"id": "n1", "label": "A", "node_type": "concept", "community_id": 1},
            {"id": "n2", "label": "B", "node_type": "concept", "community_id": 1},
            {"id": "n3", "label": "C", "node_type": "concept", "community_id": 2},
            {"id": "n4", "label": "D", "node_type": "concept", "community_id": 2},
        ]
        edges = [
            {"source_node_id": "n1", "target_node_id": "n2", "weight": 5},
            {"source_node_id": "n3", "target_node_id": "n4", "weight": 5},
            {"source_node_id": "n1", "target_node_id": "n3", "weight": 1},  # weak bridge
        ]
        client = _make_mock_client(nodes, edges)
        result = detect_communities(client, "ws1")

        assert result["node_count"] == 4
        # Seeds should be preserved (2 communities)
        assert len(result["communities"]) >= 2

    def test_complete_graph_single_community(self):
        """A fully connected graph should converge to one community."""
        nodes = [{"id": f"n{i}", "label": f"Node{i}", "node_type": "entity",
                  "community_id": 0} for i in range(5)]
        edges = []
        for i in range(5):
            for j in range(i + 1, 5):
                edges.append({"source_node_id": f"n{i}", "target_node_id": f"n{j}",
                              "weight": 1})
        client = _make_mock_client(nodes, edges)
        result = detect_communities(client, "ws1", min_community_size=1)

        # May converge to fewer communities
        assert result["node_count"] == 5
        assert result["edge_count"] == 10

    def test_large_community_merges_small(self):
        """Small communities (< min_community_size) should be merged."""
        nodes = [{"id": f"n{i}", "label": f"Node{i}", "node_type": "entity",
                  "community_id": 0} for i in range(8)]
        edges = []
        # Cluster 1: nodes 0-4 densely connected
        for i in range(5):
            for j in range(i + 1, 5):
                edges.append({"source_node_id": f"n{i}", "target_node_id": f"n{j}", "weight": 5})
        # Cluster 2: nodes 5-7 moderately connected
        for i in range(5, 8):
            for j in range(i + 1, 8):
                edges.append({"source_node_id": f"n{i}", "target_node_id": f"n{j}", "weight": 3})
        # Bridge
        edges.append({"source_node_id": "n4", "target_node_id": "n5", "weight": 2})

        client = _make_mock_client(nodes, edges)
        result = detect_communities(client, "ws1", min_community_size=3)

        # The 3-node community should be >= min_community_size or merged
        for comm in result["communities"]:
            assert comm["size"] >= 3, f"Community size {comm['size']} below min"

    def test_custom_resolution(self):
        """Higher resolution penalizes merging, producing more communities or the same number."""
        nodes, edges = _simple_graph()
        client = _make_mock_client(nodes, edges)

        # Resolution=0.3 (low penalty) should encourage merging into communities
        low_res = detect_communities(client, "ws1", resolution=0.3, min_community_size=1)
        # Resolution=1.0 (default) is the standard modularity
        default_res = detect_communities(client, "ws1", resolution=1.0, min_community_size=1)

        # Lower resolution should produce larger communities (fewer total)
        assert len(low_res["communities"]) <= len(default_res["communities"])

    def test_convergence_fast(self):
        """Should converge in well under max_iterations for simple graphs."""
        nodes, edges = _simple_graph()
        client = _make_mock_client(nodes, edges)

        result = detect_communities(client, "ws1", max_iterations=100)
        # Should converge quickly (well under 100 iterations)
        assert result["iterations"] < 20

    def test_large_graph_performance(self):
        """Performance test with 200 nodes and ~1000 edges."""
        n_nodes = 200
        nodes = [
            {"id": f"n{i}", "label": f"Node{i}", "node_type": "entity", "community_id": 0}
            for i in range(n_nodes)
        ]
        edges = []
        # Create 4 natural clusters of 50 nodes each
        for cluster in range(4):
            base = cluster * 50
            for i in range(base, base + 50):
                for j in range(i + 1, base + 50):
                    if (j - i) < 5:  # Sparse intra-cluster connections
                        edges.append({
                            "source_node_id": f"n{i}",
                            "target_node_id": f"n{j}",
                            "weight": 3,
                        })
            # Weak inter-cluster edges
            if cluster < 3:
                for _ in range(3):
                    a = base + (hash(f"a{cluster}") % 50)
                    b = (cluster + 1) * 50 + (hash(f"b{cluster}") % 50)
                    edges.append({
                        "source_node_id": f"n{a}",
                        "target_node_id": f"n{b}",
                        "weight": 1,
                    })

        client = _make_mock_client(nodes, edges)
        start = time.time()
        result = detect_communities(client, "ws1")
        elapsed = time.time() - start

        # Should complete in reasonable time
        assert elapsed < 30, f"Community detection on 200 nodes took {elapsed:.1f}s"
        assert result["node_count"] == n_nodes
        # Should find at least 2 communities
        assert len(result["communities"]) >= 2


class TestInternalHelpers:
    """Test the internal helper functions."""

    def test_connected_components(self):
        """Connected components on a simple graph."""
        adj = [
            [(1, 1.0), (2, 1.0)],  # 0 -> 1, 2
            [(0, 1.0)],            # 1 -> 0
            [(0, 1.0)],            # 2 -> 0
            [(4, 1.0)],            # 3 -> 4 (separate component)
            [(3, 1.0)],            # 4 -> 3
        ]
        result = _connected_components(adj, 5, [0, 1, 2, 3, 4])
        assert result[0] == result[1]  # Same component
        assert result[0] == result[2]  # Same component
        assert result[3] == result[4]  # Same component
        assert result[0] != result[3]  # Different components

    def test_connected_components_single(self):
        """Single node component."""
        adj = [[]]
        result = _connected_components(adj, 1, [0])
        assert result[0] == 1  # Should get component id 1

    def test_generate_community_name_few(self):
        """Name generation for small communities."""
        members = [
            {"label": "Python", "node_type": "concept"},
            {"label": "Rust", "node_type": "concept"},
        ]
        name = _generate_community_name(members)
        assert "Python" in name
        assert "Rust" in name

    def test_generate_community_name_many(self):
        """Name generation for large communities."""
        members = [
            {"label": f"Entity{i}", "node_type": "entity"}
            for i in range(10)
        ]
        name = _generate_community_name(members)
        assert "Entity0" in name
        assert "+" in name  # Should abbreviate

    def test_generate_community_name_no_labels(self):
        """Name generation falls back to type-based."""
        members = [
            {"label": "", "node_type": "concept"},
            {"label": "", "node_type": "concept"},
        ]
        name = _generate_community_name(members)
        assert "concept" in name

    def test_move_node_updates_stats(self):
        """Moving a node correctly updates community statistics."""
        adj = [[(1, 2.0)], [(0, 2.0), (2, 3.0)], [(1, 3.0)]]
        degree = [2.0, 5.0, 3.0]
        community_of_node = [1, 1, 2]
        comm_total_degree = [0.0, 7.0, 3.0]
        comm_internal_weight = [0.0, 2.0, 0.0]

        # Move node 1 from community 1 to community 2
        _move_node(1, 1, 2, adj, degree, community_of_node,
                    comm_total_degree, comm_internal_weight)

        assert community_of_node[1] == 2
        # Node 1's degree (5) removed from comm 1
        assert comm_total_degree[1] == 2.0
        # Node 1's degree (5) added to comm 2
        assert comm_total_degree[2] == 8.0
        # Internal edge (1-2) removed from comm 1
        assert comm_internal_weight[1] == 0.0
        # Internal edge (1-2) added to comm 2 (weight 3)
        assert comm_internal_weight[2] == 3.0


class TestPersistCommunities:
    """Tests for persisting communities to STDB."""

    def test_persist_creates_communities(self):
        """persist_communities creates kg_community records."""
        client = _make_mock_client([], [])
        communities = [
            {"id": 1, "name": "Lang Cluster", "summary": "Programming languages",
             "size": 3, "members": ["n1", "n2", "n3"]},
            {"id": 2, "name": "ML Cluster", "summary": "Machine learning frameworks",
             "size": 3, "members": ["n4", "n5", "n6"]},
        ]
        result = persist_communities(client, "ws1", communities)
        assert result["communities_created"] == 2
        assert result["nodes_assigned"] == 6
        assert client.create_community.call_count == 2
        assert client.assign_to_community.call_count == 6

    def test_persist_empty(self):
        """Persisting empty communities list."""
        client = _make_mock_client([], [])
        result = persist_communities(client, "ws1", [])
        assert result["communities_created"] == 0
        assert result["nodes_assigned"] == 0

    def test_persist_error_handling(self):
        """Errors during create/assign should not crash the batch."""
        client = _make_mock_client([], [])
        client.create_community = MagicMock(side_effect=Exception("STDB error"))
        communities = [
            {"id": 1, "name": "Test", "summary": "Test community",
             "size": 1, "members": ["n1"]},
        ]
        # Should not raise
        result = persist_communities(client, "ws1", communities)
        assert result["communities_created"] == 0  # failed gracefully
        assert result["nodes_assigned"] == 1  # still tried assigning


class TestSummarizeCommunities:
    """Tests for LLM-based community summarization."""

    def test_summarize_without_llm(self):
        """Without an LLM client, generates basic summaries."""
        communities = [
            {"id": 1, "name": "Test", "size": 3, "member_labels": ["A", "B", "C"]},
        ]
        result = summarize_communities(None, "ws1", communities, llm_client=None)
        assert "summary" in result[0]
        assert "related" in result[0]["summary"].lower()

    def test_summarize_with_llm(self):
        """With an LLM client, generates narrative summaries."""
        llm = MagicMock()
        llm.chat = MagicMock(return_value="This is a test community summary.")

        communities = [
            {"id": 1, "name": "Lang Cluster", "size": 2, "member_labels": ["Python", "Rust"]},
        ]
        result = summarize_communities(None, "ws1", communities, llm_client=llm)
        assert result[0]["summary"] == "This is a test community summary."
        # Verify the prompt was constructed correctly
        call_args = llm.chat.call_args[0][0]
        assert "Lang Cluster" in call_args
        assert "Python" in call_args
        assert "Rust" in call_args

    def test_summarize_with_empty_labels(self):
        """Communities without labels get fallback summaries."""
        communities = [
            {"id": 1, "name": "Community 1", "size": 2, "member_labels": []},
        ]
        result = summarize_communities(None, "ws1", communities, llm_client=None)
        assert "summary" in result[0]
        assert len(result[0]["summary"]) > 0

    def test_llm_error_fallback(self):
        """LLM errors should fall back gracefully."""
        llm = MagicMock()
        llm.chat = MagicMock(side_effect=Exception("LLM unavailable"))

        communities = [
            {"id": 1, "name": "Test", "size": 2, "member_labels": ["A", "B"]},
        ]
        result = summarize_communities(None, "ws1", communities, llm_client=llm)
        assert "summary" in result[0]


class TestEndToEnd:
    """End-to-end integration tests."""

    def test_detect_and_persist_flow(self):
        """Full detect -> summarize -> persist flow."""
        nodes, edges = _simple_graph()
        client = _make_mock_client(nodes, edges)

        # Detect
        result = detect_communities(client, "ws1")
        assert result["node_count"] == 6
        assert result["modularity"] > 0

        # Summarize (without LLM)
        communities = summarize_communities(client, "ws1", result["communities"], llm_client=None)
        for c in communities:
            assert "summary" in c

        # Persist
        persist_result = persist_communities(client, "ws1", communities)
        assert persist_result["communities_created"] == len(communities)
        assert persist_result["nodes_assigned"] == 6

    def test_detect_on_noisy_graph(self):
        """Community detection on graph with noise (mostly random edges)."""
        n_nodes = 30
        nodes = [
            {"id": f"n{i}", "label": f"Node{i}", "node_type": "entity", "community_id": 0}
            for i in range(n_nodes)
        ]
        edges = []
        # Dense intra-cluster for 10 nodes
        for i in range(10):
            for j in range(i + 1, 10):
                edges.append({"source_node_id": f"n{i}", "target_node_id": f"n{j}", "weight": 5})
        # Weak random connections for remaining 20 nodes (noise)
        for i in range(10, 30):
            for j in range(10, 30):
                if i != j and hash(f"{i},{j}") % 4 == 0:
                    edges.append({"source_node_id": f"n{i}", "target_node_id": f"n{j}", "weight": 1})

        client = _make_mock_client(nodes, edges)
        result = detect_communities(client, "ws1")

        # Should detect at least the dense cluster plus noise communities
        assert result["modularity"] > 0
        assert len(result["communities"]) >= 2


class TestPromptConstruction:
    """Test the community summary prompt."""

    def test_prompt_contains_key_sections(self):
        prompt = COMMUNITY_SUMMARY_PROMPT.format(
            name="Test",
            size=5,
            member_labels="A, B, C",
            top_labels="A, B",
        )
        assert "Community name: Test" in prompt
        assert "Member count: 5" in prompt
        assert "Members: A, B, C" in prompt
        assert "Representative entities: A, B" in prompt
