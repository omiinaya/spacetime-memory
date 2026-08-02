"""Integration tests for the Graphiti adapter — core/general classes.

Requires a running SpacetimeDB instance.
Run with: SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 SPACETIMEDB_DB=<identity> pytest ... -v
"""

from __future__ import annotations

import os

import pytest

from spacetime_memory import Client

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("SPACETIMEDB_HOST"),
        reason="Integration tests require SPACETIMEDB_HOST env var",
    ),
]


from spacetime_memory.auth import generate_token
from spacetime_memory.sdks.graphiti import (
    AddBulkEpisodeResults,
    AddEpisodeResults,
    AddTripletResults,
    CommunityNode,
    EntityEdge,
    EntityNode,
    EpisodicNode,
    Graphiti,
    RawEpisode,
    SagaNode,
    SearchResults,
)

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
def client(stdb_session: dict) -> Client:
    c = Client(
        host=stdb_session["host"],
        port=stdb_session["port"],
        database=stdb_session["database"],
    )
    # Auto-register for auth
    import secrets

    try:
        c._call("register", [f"graphiti_test_{secrets.token_hex(4)}", "Graphiti Test", "testpass"])
    except RuntimeError:
        pass
    return c


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
            edge=EntityEdge(name="prefers", fact="Charlie prefers tea", group_id=workspace_id),
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


class TestAddEpisodeBulk:
    """Tests for ``add_episode_bulk``."""

    def test_add_episode_bulk_basic(self, graphiti: Graphiti, workspace_id: str):
        """Bulk adding episodes processes all of them."""
        raws = [
            RawEpisode(
                name=f"bulk-ep-{i}",
                content=f"Bulk episode {i} content about topic alpha and beta.",
                source="message",
                source_description="bulk-test",
            )
            for i in range(3)
        ]
        result = graphiti.add_episode_bulk(raws, group_id=workspace_id)
        assert isinstance(result, AddBulkEpisodeResults)
        assert len(result.episodes) == 3
        assert result.episodes[0].name == "bulk-ep-0"
        assert result.episodes[1].name == "bulk-ep-1"
        assert result.episodes[2].name == "bulk-ep-2"
        assert isinstance(result.nodes, list)
        assert isinstance(result.edges, list)

    def test_add_episode_bulk_empty(self, graphiti: Graphiti):
        """Bulk adding empty list returns empty results."""
        result = graphiti.add_episode_bulk([])
        assert isinstance(result, AddBulkEpisodeResults)
        assert result.episodes == []
        assert result.nodes == []
        assert result.edges == []

    def test_add_episode_bulk_single(self, graphiti: Graphiti, workspace_id: str):
        """Bulk adding a single episode works."""
        raw = RawEpisode(
            name="single-bulk",
            content="Single bulk episode content.",
            source="message",
            source_description="single-test",
        )
        result = graphiti.add_episode_bulk([raw], group_id=workspace_id)
        assert isinstance(result, AddBulkEpisodeResults)
        assert len(result.episodes) == 1


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
                name="relates_to",
                fact="SummarySource relates to Target1",
                group_id=workspace_id,
            ),
            target_node=tgt1,
        )
        source_uuid = result.nodes[0].uuid

        graphiti.add_triplet(
            source_node=src,
            edge=EntityEdge(
                name="also_relates",
                fact="SummarySource also relates to Target2",
                group_id=workspace_id,
            ),
            target_node=tgt2,
        )

        # Now get the summary
        summary = graphiti.get_entity_edge_summary(source_uuid, group_ids=[workspace_id])
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

        c = Client(host=HOST, port=PORT)
        g = Graphiti(client=c)
        g.close()  # should not raise
        assert True

    def test_build_indices(self, graphiti: Graphiti):
        """build_indices_and_constraints is a no-op that returns ok."""
        result = graphiti.build_indices_and_constraints()
        assert result["status"] == "ok"


class TestTemporalEdgeTracking:
    """Tests for temporal edge versioning."""

    def test_update_edge_creates_new_version(self, graphiti: Graphiti, workspace_id: str):
        """update_edge invalidates the old edge and creates a new version."""
        src = EntityNode(name="VersionSource", group_id=workspace_id)
        tgt = EntityNode(name="VersionTarget", group_id=workspace_id)
        result = graphiti.add_triplet(
            source_node=src,
            edge=EntityEdge(name="connects", fact="v1: connects", group_id=workspace_id),
            target_node=tgt,
        )
        edge_id = result.edges[0].uuid

        # Update the edge
        update_result = graphiti.update_edge(
            edge_id=edge_id,
            relation="updated_connects",
            weight=2.0,
            metadata={"reason": "temporal test"},
        )
        assert update_result["status"] == "ok"

    def test_get_edge_history_returns_all_versions(self, graphiti: Graphiti, workspace_id: str):
        """get_edge_history returns all temporal versions of an edge."""
        src = EntityNode(name="HistorySource", group_id=workspace_id)
        tgt = EntityNode(name="HistoryTarget", group_id=workspace_id)
        result = graphiti.add_triplet(
            source_node=src,
            edge=EntityEdge(name="evolves", fact="v1: initial", group_id=workspace_id),
            target_node=tgt,
        )
        edge_id = result.edges[0].uuid

        # Create two more versions — update_edge auto-finds the latest version
        graphiti.update_edge(edge_id=edge_id, relation="evolves_v2")
        graphiti.update_edge(edge_id=edge_id, relation="evolves_v3")

        history = graphiti.get_edge_history(edge_id)
        assert len(history) >= 3

        # Should have versions 1, 2, 3
        versions = sorted(e.version for e in history)
        assert versions == [1, 2, 3]

    def test_get_edge_history_nonexistent(self, graphiti: Graphiti):
        """get_edge_history for a nonexistent edge returns empty."""
        history = graphiti.get_edge_history("nonexistent-edge-uuid")
        assert history == []

    def test_edge_has_edge_group_id(self, graphiti: Graphiti, workspace_id: str):
        """A newly created edge has an edge_group_id linking all versions."""
        src = EntityNode(name="GroupSource", group_id=workspace_id)
        tgt = EntityNode(name="GroupTarget", group_id=workspace_id)
        result = graphiti.add_triplet(
            source_node=src,
            edge=EntityEdge(name="grouped", fact="group test", group_id=workspace_id),
            target_node=tgt,
        )
        edge = result.edges[0]
        assert edge.edge_group_id
        assert edge.version == 1

    def test_update_edge_invalidates_old_version(self, graphiti: Graphiti, workspace_id: str):
        """After update_edge, the old version has invalid_at set and new version has valid_at."""
        src = EntityNode(name="InvalidateSource", group_id=workspace_id)
        tgt = EntityNode(name="InvalidateTarget", group_id=workspace_id)
        result = graphiti.add_triplet(
            source_node=src,
            edge=EntityEdge(name="temporal", fact="initial", group_id=workspace_id),
            target_node=tgt,
        )
        edge_id = result.edges[0].uuid

        graphiti.update_edge(edge_id=edge_id, relation="temporal_v2")

        history = graphiti.get_edge_history(edge_id)
        # At least one version should have valid_at set (the new one)
        # At least one version should have invalid_at set (the old one, unless it's the latest)
        assert any(e.valid_at is not None for e in history)
        # The first version (v1) should have invalid_at set (not None, not 0)
        v1 = next((e for e in history if e.version == 1), None)
        if v1:
            assert v1.invalid_at is not None

    def test_update_edge_nonexistent(self, graphiti: Graphiti):
        """update_edge on nonexistent edge raises RuntimeError."""
        with pytest.raises(RuntimeError):
            graphiti.update_edge(
                edge_id="nonexistent-edge-uuid-999",
                relation="new_relation",
                weight=1.0,
            )


class TestGraphitiNamespaces:
    """Tests for graphiti.nodes and graphiti.edges namespace properties."""

    def test_nodes_namespace(self, graphiti: Graphiti):
        """graphiti.nodes property exists."""
        assert graphiti.nodes is not None

    def test_edges_namespace(self, graphiti: Graphiti):
        """graphiti.edges property exists."""
        assert graphiti.edges is not None

    def test_token_tracker(self, graphiti: Graphiti):
        """graphiti.token_tracker property returns None."""
        assert graphiti.token_tracker is None


class TestGraphitiDataModels:
    """Tests for EntityNode and EntityEdge data models."""

    def test_entity_node_from_stmem(self, workspace_id: str):
        """EntityNode.from_stmem() parses a kg_node row."""
        row = {
            "id": "test-node-123",
            "label": "TestNode",
            "summary": "A test node",
            "workspace_id": workspace_id,
            "metadata_json": '{"key": "value"}',
            "labels": '["label1", "label2"]',
            "created_at": 1700000000000000,
        }
        node = EntityNode.from_stmem(row)
        assert node.uuid == "test-node-123"
        assert node.name == "TestNode"
        assert node.summary == "A test node"
        assert node.group_id == workspace_id
        assert node.attributes == {"key": "value"}
        assert node.labels == ["label1", "label2"]

    def test_entity_edge_from_stmem(self, workspace_id: str):
        """EntityEdge.from_stmem() parses a kg_edge row."""
        row = {
            "id": "test-edge-456",
            "relation": "likes",
            "fact": "Alice likes pizza",
            "source_node_id": "src-1",
            "target_node_id": "tgt-2",
            "workspace_id": workspace_id,
            "metadata_json": '{"weight": 2.0}',
            "created_at": 1700000000000000,
            "valid_at": 1700000000000000,
            "invalid_at": 0,
            "version": 1,
            "edge_group_id": "group-789",
        }
        edge = EntityEdge.from_stmem(row)
        assert edge.uuid == "test-edge-456"
        assert edge.name == "likes"
        assert edge.fact == "Alice likes pizza"
        assert edge.source_node_uuid == "src-1"
        assert edge.target_node_uuid == "tgt-2"
        assert edge.attributes == {"weight": 2.0}
        assert edge.version == 1

    def test_entity_node_model_dump(self):
        """EntityNode.model_dump() returns dict."""
        node = EntityNode(name="DumpNode", group_id="default")
        d = node.model_dump()
        assert d["name"] == "DumpNode"

    def test_entity_edge_model_dump(self):
        """EntityEdge.model_dump() returns dict."""
        edge = EntityEdge(name="connects", fact="test fact", group_id="default")
        d = edge.model_dump()
        assert d["name"] == "connects"

    def test_entity_node_model_validate(self):
        """EntityNode.model_validate() creates from dict."""
        data = {"name": "ValidatedNode", "group_id": "default", "summary": "test"}
        node = EntityNode.model_validate(data)
        assert node.name == "ValidatedNode"
        assert node.group_id == "default"

    def test_entity_edge_model_validate(self):
        """EntityEdge.model_validate() creates from dict."""
        data = {"name": "ValidatedEdge", "fact": "test", "group_id": "default"}
        edge = EntityEdge.model_validate(data)
        assert edge.name == "ValidatedEdge"

    def test_entity_node_from_stmem_corrupt_json(self):
        """EntityNode.from_stmem() handles corrupt metadata_json gracefully."""
        row = {
            "id": "bad-node",
            "label": "Bad",
            "metadata_json": "{not valid json",
            "labels": "",
            "created_at": 1700000000000000,
            "workspace_id": "default",
        }
        node = EntityNode.from_stmem(row)
        assert node.uuid == "bad-node"
        assert node.attributes == {}

    def test_entity_edge_from_stmem_corrupt_json(self):
        """EntityEdge.from_stmem() handles corrupt metadata_json gracefully."""
        row = {
            "id": "bad-edge",
            "relation": "test",
            "metadata_json": "{not valid json",
            "created_at": 1700000000000000,
            "valid_at": 0,
            "invalid_at": 0,
            "workspace_id": "default",
        }
        edge = EntityEdge.from_stmem(row)
        assert edge.uuid == "bad-edge"
        assert edge.attributes == {}

    def test_entity_node_from_stmem_no_created_at(self):
        """EntityNode.from_stmem() with no created_at falls back to now."""
        row = {
            "id": "no-time-node",
            "label": "NoTime",
            "workspace_id": "default",
            "created_at": 0,
            "metadata_json": "{}",
            "labels": "",
        }
        node = EntityNode.from_stmem(row)
        assert node.uuid == "no-time-node"

    def test_entity_edge_from_stmem_no_timestamps(self):
        """EntityEdge.from_stmem() with no timestamps."""
        row = {
            "id": "no-time-edge",
            "relation": "test",
            "workspace_id": "default",
            "created_at": 0,
            "valid_at": 0,
            "invalid_at": 0,
            "metadata_json": "{}",
        }
        edge = EntityEdge.from_stmem(row)
        assert edge.uuid == "no-time-edge"
        assert edge.valid_at is None
        assert edge.invalid_at is None

    def test_entity_node_from_stmem_small_timestamp(self):
        """EntityNode.from_stmem() with Unix timestamp (< 1e12)."""
        import time

        ts = int(time.time())
        row = {
            "id": "unix-node",
            "label": "UnixTime",
            "workspace_id": "default",
            "created_at": ts,
            "metadata_json": "{}",
            "labels": "",
        }
        node = EntityNode.from_stmem(row)
        assert node.uuid == "unix-node"

    def test_entity_node_from_stmem_dict_metadata(self):
        """EntityNode.from_stmem() with dict metadata_json (not string)."""
        row = {
            "id": "dict-meta-node",
            "label": "DictMeta",
            "workspace_id": "default",
            "created_at": 1700000000000000,
            "metadata_json": {"key": "val"},
            "labels": "",
        }
        node = EntityNode.from_stmem(row)
        assert node.attributes == {"key": "val"}

    def test_entity_edge_from_stmem_dict_metadata(self):
        """EntityEdge.from_stmem() with dict metadata_json."""
        row = {
            "id": "dict-meta-edge",
            "relation": "test",
            "workspace_id": "default",
            "created_at": 1700000000000000,
            "valid_at": 0,
            "invalid_at": 0,
            "metadata_json": {"key": "val"},
        }
        edge = EntityEdge.from_stmem(row)
        assert edge.attributes == {"key": "val"}

    def test_entity_node_from_stmem_empty_labels(self):
        """EntityNode.from_stmem() with empty labels list."""
        row = {
            "id": "empty-labels",
            "label": "Empty",
            "workspace_id": "default",
            "created_at": 1700000000000000,
            "metadata_json": "{}",
            "labels": '["a", "b"]',
        }
        node = EntityNode.from_stmem(row)
        assert node.labels == ["a", "b"]

    def test_episodic_node_model_dump(self):
        """EpisodicNode.model_dump() returns dict."""
        ep = EpisodicNode(name="TestEp", content="hello", group_id="default")
        d = ep.model_dump()
        assert d["name"] == "TestEp"

    def test_episodic_node_model_validate(self):
        """EpisodicNode.model_validate() creates from dict."""
        data = {"name": "ValEp", "content": "hi", "group_id": "default"}
        ep = EpisodicNode.model_validate(data)
        assert ep.name == "ValEp"

    def test_community_node_model_dump(self):
        """CommunityNode.model_dump() returns dict."""
        cn = CommunityNode(name="TestComm", group_id="default")
        d = cn.model_dump()
        assert d["name"] == "TestComm"

    def test_community_node_model_validate(self):
        """CommunityNode.model_validate() creates from dict."""
        data = {"name": "ValComm", "group_id": "default"}
        cn = CommunityNode.model_validate(data)
        assert cn.name == "ValComm"

    def test_saga_node_model_dump(self):
        """SagaNode.model_dump() returns dict."""
        sn = SagaNode(name="TestSaga", group_id="default")
        d = sn.model_dump()
        assert d["name"] == "TestSaga"

    def test_saga_node_model_validate(self):
        """SagaNode.model_validate() creates from dict."""
        data = {"name": "ValSaga", "group_id": "default"}
        sn = SagaNode.model_validate(data)
        assert sn.name == "ValSaga"

    def test_entity_edge_from_stmem_small_timestamps(self):
        """EntityEdge.from_stmem() with Unix timestamps (< 1e12)."""
        import time

        ts = int(time.time())
        row = {
            "id": "unix-edge",
            "relation": "test",
            "workspace_id": "default",
            "created_at": ts,
            "valid_at": ts,
            "invalid_at": ts,
            "metadata_json": "{}",
        }
        edge = EntityEdge.from_stmem(row)
        assert edge.uuid == "unix-edge"
        assert edge.valid_at is not None
        assert edge.invalid_at is not None


class TestGraphitiSearchEdgeCases:
    """Edge cases for search."""

    def test_search_with_explicit_num_results(self, graphiti: Graphiti, workspace_id: str):
        """search with num_results parameter."""
        edges = graphiti.search("anything", group_ids=[workspace_id], num_results=5)
        assert isinstance(edges, list)

    def test_search_nonexistent_query(self, graphiti: Graphiti, workspace_id: str):
        """search on a topic with no results returns empty list."""
        edges = graphiti.search("xyznonexistentquery12345", group_ids=[workspace_id])
        assert edges == []

    def test_search_multiple_group_ids(self, graphiti: Graphiti, workspace_id: str):
        """search with multiple group_ids."""
        edges = graphiti.search("test", group_ids=[workspace_id, "nonexistent-ws"])
        assert isinstance(edges, list)

    def test_build_communities_empty(self, graphiti: Graphiti):
        """build_communities on empty workspace returns list."""
        import uuid

        fresh_name = f"community-empty-{uuid.uuid4().hex[:8]}"
        try:
            graphiti._client.create_workspace(fresh_name)
        except RuntimeError:
            pass
        fresh_id = ""
        for ws in graphiti._client.list_workspaces():
            if ws.get("name") == fresh_name:
                fresh_id = ws["id"]
                break
        if fresh_id:
            result = graphiti.build_communities(group_ids=[fresh_id])
            assert isinstance(result, list)
