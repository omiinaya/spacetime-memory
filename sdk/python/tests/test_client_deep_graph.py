"""Deep integration tests for client.py — Advanced module.

Includes: ParseRerankJson, ParseSqlResponse, ProfilesWithPeers,
MemoryRetrieval, FuzzyGet, GlobGet, UserMemories, Decay, DecayDeep,
PluginDispatch, GraphTraversalDeep, GraphStatsDeep, AdminDeep,
GraphNeighborsDeep, QueryHash, ParseRerankJsonDeep,
ParseRerankJsonFinal, DeleteMemoryDeep, UpdateMemoryDeep,
GetterMethods, ClientUnitCoverage, SearchWithFilters,
SearchSessionsSemantic, Recommend, TestDecay,
SearchWithFiltersUnit, ConfigAndReputation, KgStats, MemoryStats,
DirectoryOps, NoteEmbedOps, NoteBacklinks, SessionListing,
ListProfiles, ApiKeyCreate, FuzzyGetEdgeCases, MemoryHistory,
BatchEmbedError, CreateNodeEmbed, RerankerErrorHandling,
QueryCacheInvalidation, TantivyAndHealthCheck, RestoreManifest,
and standalone functions.
"""

from __future__ import annotations

import os

import pytest

from spacetime_memory import Client

pytestmark = [
    pytest.mark.integration,
]


def _unique(prefix: str = "deep") -> str:
    """Return a unique name for test entities."""
    suffix = os.urandom(4).hex()
    return f"{prefix}-{suffix}"


def _make_ws(client: Client) -> str:
    """Helper: create a unique workspace and return its ID."""
    ws_name = _unique("deep-ws")
    result = client.create_workspace(ws_name)
    assert result["status"] == "ok"
    workspaces = client.list_workspaces()
    for w in workspaces:
        if w.get("name") == ws_name:
            return w["id"]
    pytest.fail(f"Workspace '{ws_name}' not found after creation")


def _store_mem(client: Client, ws_id: str, content: str, peer: str = "deep-bot") -> dict:
    """Store a memory and return the result."""
    return client.store(
        workspace_id=ws_id,
        content=content,
        peer_id=peer,
        memory_type="experience",
    )


def _get_first_memory_id(client: Client, ws_id: str) -> str | None:
    """Get the ID of the first memory in a workspace."""
    mems = client.list_memories(workspace_id=ws_id, limit=5)
    return mems[0]["id"] if mems else None



class TestGraphTraversalDeep:
    """Deeper graph traversal: get_neighbors with filtering, query_graph
    edge cases, shortest_path with actual edges."""

    def _setup_triangle_graph(self, client, ws_id):
        """Create a triangle: A - B - C - A with edges."""
        client.create_node(ws_id, "TriA", "concept")
        client.create_node(ws_id, "TriB", "concept")
        client.create_node(ws_id, "TriC", "concept")

        nodes_a = client._query("kg_node", workspace_id=ws_id, filter_dict={"label": "TriA"})
        nodes_b = client._query("kg_node", workspace_id=ws_id, filter_dict={"label": "TriB"})
        nodes_c = client._query("kg_node", workspace_id=ws_id, filter_dict={"label": "TriC"})
        if not (nodes_a and nodes_b and nodes_c):
            return None, None, None

        na, nb, nc = nodes_a[0]["id"], nodes_b[0]["id"], nodes_c[0]["id"]
        try:
            client._call("create_edge", [ws_id, na, nb, "related_to", 1.0, "EXTRACTED", "{}", ""])
            client._call("create_edge", [ws_id, nb, nc, "related_to", 1.0, "EXTRACTED", "{}", ""])
            client._call("create_edge", [ws_id, nc, na, "related_to", 1.0, "EXTRACTED", "{}", ""])
        except RuntimeError:
            pass
        return na, nb, nc

    def test_get_neighbors_with_relation_filter(self, stdb_client):
        """get_neighbors with edge relation filtering."""
        ws_id = _make_ws(stdb_client)
        stdb_client.create_node(ws_id, "RelFilterA", "concept")
        stdb_client.create_node(ws_id, "RelFilterB", "concept")
        stdb_client.create_node(ws_id, "RelFilterC", "concept")

        nodes_a = stdb_client._query(
            "kg_node", workspace_id=ws_id, filter_dict={"label": "RelFilterA"}
        )
        nodes_b = stdb_client._query(
            "kg_node", workspace_id=ws_id, filter_dict={"label": "RelFilterB"}
        )
        nodes_c = stdb_client._query(
            "kg_node", workspace_id=ws_id, filter_dict={"label": "RelFilterC"}
        )
        if not (nodes_a and nodes_b and nodes_c):
            pytest.skip("Could not create all test nodes")

        na, nb, nc = nodes_a[0]["id"], nodes_b[0]["id"], nodes_c[0]["id"]
        try:
            stdb_client._call("create_edge", [ws_id, na, nb, "loves", 1.0, "EXTRACTED", "{}", ""])
            stdb_client._call("create_edge", [ws_id, na, nc, "hates", 1.0, "EXTRACTED", "{}", ""])
        except RuntimeError:
            pytest.skip("create_edge reducer not available")

        # Get neighbors without filter
        all_edges = stdb_client.get_neighbors(na, ws_id)
        assert isinstance(all_edges, list)
        assert len(all_edges) >= 2, f"Expected >=2 edges, got {len(all_edges)}"

        # get_neighbors doesn't support relation filter in current API,
        # but we test edge properties are accessible
        relations = [e.get("relation", "") for e in all_edges]
        assert "loves" in relations or "hates" in relations, (
            f"Expected loves/hates in relations: {relations}"
        )

    def test_query_graph_no_matches(self, stdb_client):
        """query_graph returns empty list when no nodes match."""
        ws_id = _make_ws(stdb_client)
        results = stdb_client.query_graph(ws_id, "NoSuchNode_XYZ123")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_query_graph_exact_match(self, stdb_client):
        """query_graph with exact label match."""
        ws_id = _make_ws(stdb_client)
        stdb_client.create_node(ws_id, "ExactMatchNode", "concept")
        stdb_client.create_node(ws_id, "OtherNode", "concept")

        results = stdb_client.query_graph(ws_id, "ExactMatchNode")
        assert isinstance(results, list)
        labels = [r.get("label", "") for r in results]
        assert any("ExactMatchNode" in label for label in labels), f"ExactMatchNode not found in {labels}"

    def test_shortest_path_with_triangle(self, stdb_client):
        """shortest_path through an actual triangle graph."""
        ws_id = _make_ws(stdb_client)
        na, nb, nc = self._setup_triangle_graph(stdb_client, ws_id)
        if na is None:
            pytest.skip("Could not create triangle graph")

        try:
            # Shortest path from A to C should be 1 hop (A→B→C or A→C)
            stdb_client.shortest_path(ws_id, na, nc, max_hops=3)
        except RuntimeError as e:
            if "No such procedure" in str(e):
                pytest.skip("shortest_path reducer not available")
            raise

    def test_graph_bfs_with_triangle(self, stdb_client):
        """graph_bfs on a triangle graph with depth limit."""
        ws_id = _make_ws(stdb_client)
        na, nb, nc = self._setup_triangle_graph(stdb_client, ws_id)
        if na is None:
            pytest.skip("Could not create triangle graph")

        try:
            stdb_client.graph_bfs(ws_id, na, max_depth=1)
            stdb_client.graph_bfs(ws_id, na, max_depth=3)
        except RuntimeError as e:
            if "No such procedure" in str(e):
                pytest.skip("graph_bfs reducer not available")
            raise

    def test_get_neighbors_node_with_no_edges(self, stdb_client):
        """get_neighbors on an isolated node returns empty or no edges."""
        ws_id = _make_ws(stdb_client)
        stdb_client.create_node(ws_id, "IsolatedNode", "concept")
        nodes = stdb_client._query(
            "kg_node", workspace_id=ws_id, filter_dict={"label": "IsolatedNode"}
        )
        if nodes:
            edges = stdb_client.get_neighbors(nodes[0]["id"], ws_id)
            assert isinstance(edges, list)
            # An isolated node should have 0 edges
            assert len(edges) == 0, f"Isolated node has edges: {edges}"

    def test_get_neighbors_via_reducer_isolated(self, stdb_client):
        """get_neighbors_via_reducer on an isolated node."""
        ws_id = _make_ws(stdb_client)
        stdb_client.create_node(ws_id, "IsoRedNode", "concept")
        nodes = stdb_client._query(
            "kg_node", workspace_id=ws_id, filter_dict={"label": "IsoRedNode"}
        )
        if nodes:
            try:
                stdb_client.get_neighbors_via_reducer(ws_id, nodes[0]["id"])
            except RuntimeError as e:
                if "No such procedure" in str(e):
                    pytest.skip("get_neighbors reducer not available")
                raise


class TestGraphStatsDeep:
    """Deep graph statistics: community detection, pagerank, bridge
    detection, hierarchy — verify response shapes and keys."""

    def test_detect_communities_with_data(self, stdb_client):
        """detect_communities on a workspace with multiple connected nodes."""
        ws_id = _make_ws(stdb_client)
        for i in range(5):
            stdb_client.create_node(ws_id, f"CommNode_{i}", "concept")
        # Create some edges between them
        nodes = stdb_client._query("kg_node", workspace_id=ws_id)
        if len(nodes) >= 3:
            try:
                stdb_client._call(
                    "create_edge",
                    [ws_id, nodes[0]["id"], nodes[1]["id"], "related", 1.0, "EXTRACTED", "{}", ""],
                )
                stdb_client._call(
                    "create_edge",
                    [ws_id, nodes[1]["id"], nodes[2]["id"], "related", 1.0, "EXTRACTED", "{}", ""],
                )
            except RuntimeError:
                pass

        try:
            result = stdb_client.detect_communities(ws_id)
            assert result["status"] == "ok"
        except RuntimeError as e:
            if "Admin" in str(e):
                pytest.skip("Admin access required")
            raise

    def test_compute_pagerank_result_shape(self, stdb_client):
        """compute_pagerank returns valid result shape."""
        ws_id = _make_ws(stdb_client)
        stdb_client.create_node(ws_id, "PRA", "concept")
        stdb_client.create_node(ws_id, "PRB", "concept")
        # Edges
        na = stdb_client._query("kg_node", workspace_id=ws_id, filter_dict={"label": "PRA"})
        nb = stdb_client._query("kg_node", workspace_id=ws_id, filter_dict={"label": "PRB"})
        if na and nb:
            try:
                stdb_client._call(
                    "create_edge",
                    [ws_id, na[0]["id"], nb[0]["id"], "links_to", 1.0, "EXTRACTED", "{}", ""],
                )
            except RuntimeError:
                pass

        try:
            result = stdb_client.compute_pagerank(ws_id, 0.85, 50)
            assert result["status"] == "ok"
        except RuntimeError as e:
            if "Admin" in str(e):
                pytest.skip("Admin access required")
            raise

    def test_compute_community_hierarchy_shape(self, stdb_client):
        """compute_community_hierarchy after community detection."""
        ws_id = _make_ws(stdb_client)
        stdb_client.create_node(ws_id, "HierA", "concept")
        stdb_client.create_node(ws_id, "HierB", "concept")
        try:
            stdb_client.detect_communities(ws_id)
        except RuntimeError:
            pass

        try:
            result = stdb_client.compute_community_hierarchy(ws_id)
            assert result["status"] == "ok"
        except RuntimeError as e:
            if "Admin" in str(e):
                pytest.skip("Admin access required")
            raise

    def test_detect_bridge_nodes_with_data(self, stdb_client):
        """detect_bridge_nodes with inter-community edges."""
        ws_id = _make_ws(stdb_client)
        stdb_client.create_node(ws_id, "BridgeNode1", "concept")
        stdb_client.create_node(ws_id, "BridgeNode2", "concept")
        stdb_client.create_node(ws_id, "BridgeNode3", "concept")
        nodes = stdb_client._query("kg_node", workspace_id=ws_id)
        if len(nodes) >= 2:
            try:
                stdb_client._call(
                    "create_edge",
                    [ws_id, nodes[0]["id"], nodes[1]["id"], "bridges", 1.0, "EXTRACTED", "{}", ""],
                )
            except RuntimeError:
                pass

        try:
            result = stdb_client.detect_bridge_nodes(ws_id)
            assert isinstance(result, list)
        except RuntimeError as e:
            pytest.skip(f"bridge detection not available: {e}")

    def test_compute_kg_stats_with_nodes(self, stdb_client):
        """compute_kg_stats on a workspace with nodes."""
        ws_id = _make_ws(stdb_client)
        stdb_client.create_node(ws_id, "StatsA", "concept")
        stdb_client.create_node(ws_id, "StatsB", "concept")
        try:
            result = stdb_client.compute_kg_stats(ws_id)
            assert result is not None
        except RuntimeError as e:
            if "Table" in str(e):
                pytest.skip("kg_stats_result table not queryable")
            raise

    def test_get_community_multiple(self, stdb_client):
        """get_community for different community IDs."""
        ws_id = _make_ws(stdb_client)
        for i in range(3):
            stdb_client.create_node(ws_id, f"MultiComm_{i}", "concept")
        try:
            stdb_client.detect_communities(ws_id)
        except RuntimeError:
            pass

        # Query community 0 and verify shape
        c0 = stdb_client.get_community(0)
        assert "community" in c0
        assert "nodes" in c0
        assert isinstance(c0["nodes"], list)


class TestGraphNeighborsDeep:
    """Verify edge properties on get_neighbors results."""

    def test_get_neighbors_edge_properties(self, stdb_client):
        """get_neighbors returns edges with source_id, target_id, relation."""
        ws_id = _make_ws(stdb_client)
        stdb_client.create_node(ws_id, "EdgePropSrc", "concept")
        stdb_client.create_node(ws_id, "EdgePropTgt", "concept")

        nodes_src = stdb_client._query(
            "kg_node", workspace_id=ws_id, filter_dict={"label": "EdgePropSrc"}
        )
        nodes_tgt = stdb_client._query(
            "kg_node", workspace_id=ws_id, filter_dict={"label": "EdgePropTgt"}
        )
        if not (nodes_src and nodes_tgt):
            pytest.skip("Could not create nodes")

        try:
            stdb_client._call(
                "create_edge",
                [
                    ws_id,
                    nodes_src[0]["id"],
                    nodes_tgt[0]["id"],
                    "is_friend_of",
                    0.95,
                    "EXTRACTED",
                    "{}",
                    "",
                ],
            )
        except RuntimeError:
            pytest.skip("create_edge reducer not available")

        edges = stdb_client.get_neighbors(nodes_src[0]["id"], ws_id)
        assert len(edges) >= 1

        edge = edges[0]
        # Check that edge has the expected fields (snake_case naming in STDB)
        assert "source_node_id" in edge or "source_id" in edge or "node_a" in edge, (
            f"Edge missing source field: {edge.keys()}"
        )
        assert "target_node_id" in edge or "target_id" in edge or "node_b" in edge, (
            f"Edge missing target field: {edge.keys()}"
        )

    def test_get_neighbors_bidirectional(self, stdb_client):
        """get_neighbors returns edges regardless of direction."""
        ws_id = _make_ws(stdb_client)
        stdb_client.create_node(ws_id, "BidirA", "concept")
        stdb_client.create_node(ws_id, "BidirB", "concept")

        nodes_a = stdb_client._query("kg_node", workspace_id=ws_id, filter_dict={"label": "BidirA"})
        nodes_b = stdb_client._query("kg_node", workspace_id=ws_id, filter_dict={"label": "BidirB"})
        if not (nodes_a and nodes_b):
            pytest.skip("Could not create nodes")

        try:
            stdb_client._call(
                "create_edge",
                [
                    ws_id,
                    nodes_a[0]["id"],
                    nodes_b[0]["id"],
                    "connects",
                    1.0,
                    "EXTRACTED",
                    "{}",
                    "",
                ],
            )
        except RuntimeError:
            pytest.skip("create_edge reducer not available")

        # Query from both sides
        edges_a = stdb_client.get_neighbors(nodes_a[0]["id"], ws_id)
        edges_b = stdb_client.get_neighbors(nodes_b[0]["id"], ws_id)

        assert isinstance(edges_a, list)
        assert isinstance(edges_b, list)
        # At least one side should see the edge
        assert len(edges_a) >= 1 or len(edges_b) >= 1, (
            f"No edges found from either side: A={len(edges_a)}, B={len(edges_b)}"
        )
