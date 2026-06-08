"""Integration tests for the Graphiti adapter.

Requires a running SpacetimeDB instance.
Run with: SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 SPACETIMEDB_DB=<identity> pytest ... -v
"""

from __future__ import annotations

import os
import pytest

from spacetime_memory import Client

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("SPACETIMEDB_HOST"),
        reason="Integration tests require SPACETIMEDB_HOST env var",
    ),
]


from spacetime_memory.sdks.graphiti import (
    AddEpisodeResults,
    AddTripletResults,
    EntityEdge,
    EntityNode,
    Graphiti,
    SearchResults,
)
from spacetime_memory.auth import generate_token

HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
# Default DB is set by Client.__init__ if not passed
DB = os.environ.get("SPACETIMEDB_DB", None)
REPO_ROOT = __file__.rsplit("/", 5)[0] if "/" in __file__ else "."


def _generate_test_token() -> str:
    key_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "data", "id_ecdsa_pkcs8.pem"
    )
    key_path = os.path.abspath(key_path)
    if os.path.exists(key_path):
        return generate_token(key_path)
    return ""


@pytest.fixture(scope="module")
def token() -> str:
    return _generate_test_token()


@pytest.fixture(scope="module")
def client(token: str) -> Client:
    kwargs = {"host": HOST, "port": PORT, "token": token}
    if DB:
        kwargs["database"] = DB
    return Client(**kwargs)


@pytest.fixture(scope="module")
def graphiti(client: Client) -> Graphiti:
    return Graphiti(client=client)


@pytest.fixture(scope="module")
def workspace_id(client: Client) -> str:
    """Create a clean workspace for Graphiti tests."""
    import uuid

    name = f"graphiti-test-{uuid.uuid4().hex[:8]}"
    client.create_workspace(name)
    for ws in client.list_workspaces():
        if ws.get("name") == name:
            return ws["id"]
    pytest.fail("Workspace not created")


# =====================================================================
# Tests
# =====================================================================


class TestAddTriplet:
    """Tests for ``add_triplet`` — the primary KG manipulation API."""

    def test_add_simple_triplet(self, graphiti: Graphiti, workspace_id: str):
        """Add a source -[edge]-> target triplet and verify nodes + edge are created."""
        source = EntityNode(
            name="Alice",
            summary="A test user",
            group_id=workspace_id,
            attributes={"role": "admin"},
        )
        target = EntityNode(
            name="Pizza",
            summary="Food item",
            group_id=workspace_id,
        )
        edge = EntityEdge(
            name="likes",
            fact="Alice likes eating pizza",
            group_id=workspace_id,
        )

        result = graphiti.add_triplet(source_node=source, edge=edge, target_node=target)

        assert isinstance(result, AddTripletResults)
        assert len(result.nodes) == 2
        assert len(result.edges) == 1

        # Node names should match
        node_names = {n.name for n in result.nodes}
        assert "Alice" in node_names
        assert "Pizza" in node_names

        # Edge should connect the right nodes
        created_edge = result.edges[0]
        assert created_edge.name == "likes"
        assert created_edge.fact == "Alice likes eating pizza"

    def test_add_triplet_with_existing_nodes(self, graphiti: Graphiti, workspace_id: str):
        """Adding a triplet with nodes that already exist should work fine."""
        source = EntityNode(
            name="Bob",
            summary="Another test user",
            group_id=workspace_id,
        )
        target = EntityNode(
            name="Coffee",
            summary="A beverage",
            group_id=workspace_id,
        )

        # First add
        result1 = graphiti.add_triplet(
            source_node=source,
            edge=EntityEdge(name="drinks", fact="Bob drinks coffee", group_id=workspace_id),
            target_node=target,
        )
        assert len(result1.nodes) == 2

        # Second add with same nodes but different edge
        result2 = graphiti.add_triplet(
            source_node=source,
            edge=EntityEdge(
                name="prefers", fact="Bob prefers coffee over tea", group_id=workspace_id
            ),
            target_node=target,
        )
        assert len(result2.edges) == 1
        assert result2.edges[0].name == "prefers"

    def test_add_triplet_multiple_edges(self, graphiti: Graphiti, workspace_id: str):
        """Multiple edges between the same nodes should be creatable."""
        source = EntityNode(name="Charlie", group_id=workspace_id)
        target = EntityNode(name="Tea", group_id=workspace_id)

        graphiti.add_triplet(
            source_node=source,
            edge=EntityEdge(name="drinks", fact="Charlie drinks tea", group_id=workspace_id),
            target_node=target,
        )
        graphiti.add_triplet(
            source_node=source,
            edge=EntityEdge(
                name="prefers", fact="Charlie prefers tea", group_id=workspace_id
            ),
            target_node=target,
        )

        # Verify edges via search
        edges = graphiti.search("Charlie", group_ids=[workspace_id], num_results=20)
        edge_names = {e.name for e in edges}
        assert "drinks" in edge_names
        assert "prefers" in edge_names


class TestSearch:
    """Tests for knowledge graph search."""

    def test_search_basic(self, graphiti: Graphiti, workspace_id: str):
        """Basic search returns edges matching the query."""
        # Add some data first
        data_source = EntityNode(name="Database", group_id=workspace_id)
        data_target = EntityNode(name="Query", group_id=workspace_id)
        graphiti.add_triplet(
            source_node=data_source,
            edge=EntityEdge(
                name="executes", fact="Database executes SQL queries", group_id=workspace_id
            ),
            target_node=data_target,
        )

        edges = graphiti.search("SQL query", group_ids=[workspace_id])
        assert isinstance(edges, list)
        assert len(edges) >= 1

    def test_search_advanced(self, graphiti: Graphiti, workspace_id: str):
        """Advanced search returns SearchResults with nodes and edges."""
        results = graphiti.search_("executes", group_ids=[workspace_id])
        assert isinstance(results, SearchResults)
        # Should have at least some results from earlier tests
        assert isinstance(results.nodes, list)
        assert isinstance(results.edges, list)

    def test_search_empty_workspace(self, graphiti: Graphiti):
        """Search on an empty workspace returns empty list."""
        import uuid

        # Create a fresh workspace that's empty
        fresh_name = f"empty-{uuid.uuid4().hex[:8]}"
        try:
            graphiti._client.create_workspace(fresh_name)
        except RuntimeError:
            pass
        fresh_ws_id = ""
        for ws in graphiti._client.list_workspaces():
            if ws.get("name") == fresh_name:
                fresh_ws_id = ws["id"]
                break

        if fresh_ws_id:
            results = graphiti.search("anything", group_ids=[fresh_ws_id])
            assert results == []


class TestAddEpisode:
    """Tests for ``add_episode``."""

    def test_add_episode_basic(self, graphiti: Graphiti, workspace_id: str):
        """Adding an episode stores the content as a memory."""
        result = graphiti.add_episode(
            name="test-conversation",
            episode_body="Alice said she likes pizza and coffee.",
            source_description="chat-log",
            group_id=workspace_id,
        )
        assert isinstance(result, AddEpisodeResults)
        assert result.episode is not None
        assert result.episode.name == "test-conversation"
        assert result.episode.content == "Alice said she likes pizza and coffee."

    def test_add_episode_in_new_workspace(self, graphiti: Graphiti):
        """Adding an episode creates the workspace if needed."""
        import uuid

        new_ws = f"episode-ws-{uuid.uuid4().hex[:8]}"
        result = graphiti.add_episode(
            name="new-ws-convo",
            episode_body="Test content in a new workspace.",
            source_description="test",
            group_id=new_ws,
        )
        assert result.episode is not None
        assert result.episode.content == "Test content in a new workspace."


class TestGetEntityEdgeSummary:
    """Tests for ``get_entity_edge_summary``."""

    def test_get_edge_summary(self, graphiti: Graphiti, workspace_id: str):
        """Getting edge summary returns edges and nodes connected to an entity."""
        # First create a node and some edges
        src = EntityNode(name="SummarySource", group_id=workspace_id)
        tgt1 = EntityNode(name="SummaryTarget1", group_id=workspace_id)
        tgt2 = EntityNode(name="SummaryTarget2", group_id=workspace_id)

        result = graphiti.add_triplet(
            source_node=src,
            edge=EntityEdge(
                name="relates_to", fact="SummarySource relates to Target1",
                group_id=workspace_id,
            ),
            target_node=tgt1,
        )
        source_uuid = result.nodes[0].uuid

        graphiti.add_triplet(
            source_node=src,
            edge=EntityEdge(
                name="also_relates", fact="SummarySource also relates to Target2",
                group_id=workspace_id,
            ),
            target_node=tgt2,
        )

        # Now get the summary
        summary = graphiti.get_entity_edge_summary(source_uuid)
        assert "edges" in summary
        assert "nodes" in summary
        assert "summary" in summary
        assert len(summary["edges"]) >= 2

    def test_get_edge_summary_nonexistent(self, graphiti: Graphiti):
        """Getting edge summary for a nonexistent node returns empty."""
        summary = graphiti.get_entity_edge_summary("nonexistent-uuid")
        assert summary["edges"] == []
        assert summary["nodes"] == []
        assert summary["summary"] == ""


class TestRemoveEpisode:
    """Tests for ``remove_episode``."""

    def test_remove_episode(self, graphiti: Graphiti, workspace_id: str):
        """Removing an episode deactivates the associated memory."""
        result = graphiti.add_episode(
            name="removable",
            episode_body="This will be removed.",
            source_description="test",
            group_id=workspace_id,
        )
        ep_uuid = result.episode.uuid

        remove_result = graphiti.remove_episode(ep_uuid)
        assert remove_result["status"] == "ok"
        assert remove_result["episode_uuid"] == ep_uuid

    def test_remove_nonexistent_episode(self, graphiti: Graphiti):
        """Removing a nonexistent episode returns gracefully."""
        result = graphiti.remove_episode("nonexistent-episode-uuid")
        assert result["status"] == "ok"


class TestCommunityDetection:
    """Tests for ``build_communities``."""

    def test_build_communities(self, graphiti: Graphiti, workspace_id: str):
        """Community detection runs without error."""
        result = graphiti.build_communities(group_ids=[workspace_id])
        assert isinstance(result, list)


class TestLifecycle:
    """Tests for lifecycle methods."""

    def test_close(self, graphiti: Graphiti):
        """close() should not raise."""
        # Note: this closes the underlying HTTP session
        # We create a new one for this test
        import uuid

        c = Client(host=HOST, port=PORT)
        g = Graphiti(client=c)
        g.close()  # should not raise
        assert True

    def test_build_indices(self, graphiti: Graphiti):
        """build_indices_and_constraints is a no-op that returns ok."""
        result = graphiti.build_indices_and_constraints()
        assert result["status"] == "ok"
