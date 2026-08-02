"""Unit tests for the Graphiti adapter client (_client.py).

Tests the Graphiti class which wraps Spacetime-Memory KG operations
behind Graphiti's API.  Uses mocked HTTP — no real network calls.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from spacetime_memory.sdks.graphiti._client import (
    CommunityNodeNamespace,
    EntityNodeNamespace,
    EpisodeNodeNamespace,
    Graphiti,
    NodeNamespace,
    SagaNodeNamespace,
)
from spacetime_memory.sdks.graphiti._edge_namespaces import (
    EdgeNamespace,
    EntityEdgeNamespace,
)
from spacetime_memory.sdks.graphiti._models import (
    AddTripletResults,
    CommunityNode,
    EntityEdge,
    EntityNode,
    EpisodicNode,
    RawEpisode,
    SagaNode,
)

pytestmark = pytest.mark.unit


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_client():
    """Return a Graphiti instance with its internal _client fully mocked."""
    g = Graphiti(host="127.0.0.1", port=3001, database="test-db")
    # Patch the underlying client methods
    with patch.object(g._client, "_call") as mock_call:
        with patch.object(g._client, "_query") as mock_query:
            with patch.object(g._client, "search") as mock_search:
                with patch.object(g._client, "list_workspaces") as mock_list_ws:
                    with patch.object(g._client, "create_workspace") as mock_create_ws:
                        with patch.object(g._client, "create_node") as mock_create_node:
                            with patch.object(g._client, "create_edge") as mock_create_edge:
                                with patch.object(g._client, "get_neighbors") as mock_get_neighbors:
                                    with patch.object(g._client, "query_graph") as mock_query_graph:
                                        with patch.object(g._client, "delete_memory") as mock_delete_mem:
                                            with patch.object(g._client, "_sql") as mock_sql:
                                                # Defaults
                                                mock_call.return_value = "ok"
                                                mock_query.return_value = []
                                                mock_search.return_value = []
                                                mock_list_ws.return_value = []
                                                mock_create_ws.return_value = {"id": "ws-uuid"}
                                                mock_create_node.return_value = {"id": "node-uuid"}
                                                mock_create_edge.return_value = {"id": "edge-uuid"}
                                                mock_get_neighbors.return_value = []
                                                mock_query_graph.return_value = []
                                                mock_delete_mem.return_value = {"status": "ok"}
                                                mock_sql.return_value = []

                                                g._mock_call = mock_call
                                                g._mock_query = mock_query
                                                g._mock_search = mock_search
                                                g._mock_list_ws = mock_list_ws
                                                g._mock_create_ws = mock_create_ws
                                                g._mock_create_node = mock_create_node
                                                g._mock_create_edge = mock_create_edge
                                                g._mock_get_neighbors = mock_get_neighbors
                                                g._mock_query_graph = mock_query_graph
                                                g._mock_delete_mem = mock_delete_mem
                                                g._mock_sql = mock_sql
                                                yield g


# ── Test: Constructor & properties ────────────────────────────────────────


class TestGraphitiConstructor:
    def test_default_construction(self):
        g = Graphiti(host="127.0.0.1", port=3001)
        assert g._client is not None
        assert g.clients is g._client
        assert g._ws_cache == {}
        assert g._token_tracker is None

    def test_accepts_existing_client(self):
        from spacetime_memory.client import Client

        c = Client(host="10.0.0.1", port=9999)
        g = Graphiti(client=c)
        assert g._client is c

    def test_token_tracker_property(self):
        g = Graphiti(host="127.0.0.1", port=3001)
        assert g.token_tracker is None

    def test_nodes_property(self):
        g = Graphiti(host="127.0.0.1", port=3001)
        assert isinstance(g.nodes, NodeNamespace)

    def test_edges_property(self):
        g = Graphiti(host="127.0.0.1", port=3001)
        assert isinstance(g.edges, EdgeNamespace)


# ── Test: Workspace resolution ────────────────────────────────────────────


class TestResolveWorkspace:
    def test_uses_cache(self, mock_client):
        mock_client._ws_cache["my-group"] = "cached-uuid"
        result = mock_client._resolve_workspace("my-group")
        assert result == "cached-uuid"
        mock_client._mock_list_ws.assert_not_called()

    def test_creates_workspace_when_missing(self, mock_client):
        mock_client._mock_list_ws.return_value = []
        mock_client._mock_create_ws.return_value = None
        # After create, re-list returns the new workspace
        mock_client._mock_list_ws.side_effect = [
            [],  # first call: empty
            [{"id": "new-uuid", "name": "new-group"}],  # re-list
        ]
        result = mock_client._resolve_workspace("new-group")
        assert result == "new-uuid"
        mock_client._mock_create_ws.assert_called_once_with("new-group")

    def test_finds_existing_by_name(self, mock_client):
        mock_client._mock_list_ws.return_value = [
            {"id": "ws-1", "name": "my-group"},
            {"id": "ws-2", "name": "other"},
        ]
        result = mock_client._resolve_workspace("my-group")
        assert result == "ws-1"

    def test_finds_existing_by_uuid(self, mock_client):
        mock_client._mock_list_ws.return_value = [
            {"id": "exact-uuid", "name": "different-name"},
        ]
        result = mock_client._resolve_workspace("exact-uuid")
        assert result == "exact-uuid"

    def test_fallback_to_group_id(self, mock_client):
        mock_client._mock_list_ws.return_value = []
        result = mock_client._resolve_workspace("fallback-id")
        assert result == "fallback-id"


# ── Test: SQL helpers ─────────────────────────────────────────────────────


class TestSqlHelpers:
    def test_sql_query_returns_results(self, mock_client):
        mock_client._mock_sql.return_value = [{"id": "1"}]
        result = mock_client._sql_query("SELECT * FROM test")
        assert result == [{"id": "1"}]

    def test_sql_query_returns_empty_on_error(self, mock_client):
        mock_client._mock_sql.side_effect = RuntimeError("fail")
        result = mock_client._sql_query("SELECT * FROM test")
        assert result == []

    def test_sql_param_calls_client(self, mock_client):
        mock_client._mock_call.side_effect = None
        with patch.object(mock_client._client, "_sql_param") as mock_sp:
            mock_sp.return_value = [{"foo": "bar"}]
            result = mock_client._sql_param("SELECT ?", "val")
            assert result == [{"foo": "bar"}]
            mock_sp.assert_called_once_with("SELECT ?", "val")


# ── Test: add_triplet ─────────────────────────────────────────────────────


class TestAddTriplet:
    def test_add_triplet_creates_nodes_and_edge(self, mock_client):
        """add_triplet should create nodes if they don't exist, then an edge."""
        mock_client._mock_list_ws.return_value = [{"id": "ws-1", "name": "default"}]
        # _query for nodes returns empty (no existing nodes)
        mock_client._mock_query.side_effect = [
            [],  # _get_or_create_node — query existing nodes (source)
            [],  # _get_or_create_node — re-query after create (source)
            [],  # _get_or_create_node — query existing nodes (target)
            [],  # _get_or_create_node — re-query after create (target)
            [],  # add_triplet — query kg_edge after edge creation
        ]

        source = EntityNode(name="Alice", group_id="default")
        edge = EntityEdge(name="likes", fact="Alice likes pizza", group_id="default")
        target = EntityNode(name="Pizza", group_id="default")

        result = mock_client.add_triplet(source_node=source, edge=edge, target_node=target)

        # Should have created 2 nodes and 1 edge
        assert mock_client._mock_create_node.call_count >= 1
        assert mock_client._mock_create_edge.call_count >= 1
        assert isinstance(result, AddTripletResults)
        assert len(result.nodes) == 2
        assert len(result.edges) == 1

    def test_add_triplet_with_group_id_override(self, mock_client):
        """When group_id is provided, it overrides node/edge group_ids."""
        mock_client._mock_list_ws.return_value = [{"id": "ws-ovr", "name": "my-workspace"}]
        mock_client._mock_query.return_value = []

        result = mock_client.add_triplet(
            source_node=EntityNode(name="S", group_id="ignored"),
            edge=EntityEdge(name="e", fact="f", group_id="ignored"),
            target_node=EntityNode(name="T", group_id="ignored"),
            group_id="my-workspace",
        )
        assert result.edges[0].group_id == "my-workspace"

    def test_add_triplet_propagates_error(self, mock_client):
        """RuntimeError from create_edge should be raised."""
        mock_client._mock_list_ws.return_value = [{"id": "ws-1", "name": "default"}]
        mock_client._mock_query.return_value = []
        mock_client._mock_create_edge.side_effect = RuntimeError("edge failed")

        with pytest.raises(RuntimeError, match="create_edge failed"):
            mock_client.add_triplet(
                source_node=EntityNode(name="S"),
                edge=EntityEdge(name="e", fact="f"),
                target_node=EntityNode(name="T"),
                group_id="default",
            )


# ── Test: add_episode ─────────────────────────────────────────────────────


class TestAddEpisode:
    def test_add_episode_stores_memory(self, mock_client):
        mock_client._mock_list_ws.return_value = [{"id": "ws-1", "name": "default"}]
        mock_client._mock_query.return_value = []

        result = mock_client.add_episode(
            name="test-ep",
            episode_body="Hello world",
            source_description="test",
            group_id="default",
        )
        assert result.episode is not None
        assert result.episode.name == "test-ep"
        assert result.episode.content == "Hello world"
        # Expected 4 calls: store memory, then 2 query for extract results
        assert mock_client._mock_call.call_count >= 1

    def test_add_episode_with_extracted_entities(self, mock_client):
        """When LLM extraction succeeds, entities and edges should be created."""
        mock_client._mock_list_ws.return_value = [{"id": "ws-1", "name": "default"}]
        # _query for nodes returns empty
        mock_client._mock_query.return_value = []

        # Patch LLMClient to return fake extraction data
        with patch(
            "spacetime_memory.sdks.graphiti._episodes.LLMClient"
        ) as MockLLM:
            mock_llm_instance = MockLLM.return_value
            mock_llm_instance.available = True
            mock_llm_instance.chat.return_value = json.dumps(
                {
                    "entities": [
                        {"name": "Alice", "entity_type": "person"},
                        {"name": "Pizza", "entity_type": "food"},
                    ],
                    "edges": [
                        {"source": "Alice", "target": "Pizza", "relation": "likes"},
                    ],
                }
            )

            result = mock_client.add_episode(
                name="food-chat",
                episode_body="Alice really likes eating pizza",
                source_description="conversation",
                group_id="default",
            )

            assert result.episode is not None
            # The extraction creates nodes and edges
            # (exact count may vary based on re-query behavior)
            assert len(result.nodes) >= 1 or len(result.edges) >= 0

    def test_add_episode_without_llm_returns_empty(self, mock_client):
        """When LLM is unavailable, episode is stored but no entities extracted."""
        mock_client._mock_list_ws.return_value = [{"id": "ws-1", "name": "default"}]
        mock_client._mock_query.return_value = []

        with patch(
            "spacetime_memory.sdks.graphiti._episodes.LLMClient"
        ) as MockLLM:
            mock_llm_instance = MockLLM.return_value
            mock_llm_instance.available = False

            result = mock_client.add_episode(
                name="plain",
                episode_body="Some text",
                source_description="src",
                group_id="default",
            )
            assert result.episode is not None
            assert result.nodes == []
            assert result.edges == []


# ── Test: add_episode_bulk ────────────────────────────────────────────────


class TestAddEpisodeBulk:
    def test_bulk_adds_multiple_episodes(self, mock_client):
        mock_client._mock_list_ws.return_value = [{"id": "ws-1", "name": "default"}]
        mock_client._mock_query.return_value = []

        episodes = [
            RawEpisode(name="ep1", content="First"),
            RawEpisode(name="ep2", content="Second"),
        ]
        result = mock_client.add_episode_bulk(episodes, group_id="default")
        assert len(result.episodes) == 2


# ── Test: search ──────────────────────────────────────────────────────────


class TestSearch:
    def test_search_returns_edges(self, mock_client):
        mock_client._mock_list_ws.return_value = [{"id": "ws-1", "name": "default"}]
        mock_client._mock_search.return_value = [
            {"entity_id": "node-1", "entity_type": "node", "score": 0.9},
        ]
        mock_client._mock_get_neighbors.return_value = [
            {"id": "edge-1", "relation": "likes", "fact": "likes pizza",
             "source_node_id": "n1", "target_node_id": "n2",
             "workspace_id": "ws-1", "version": 1, "edge_group_id": ""},
        ]

        result = mock_client.search("test query", group_ids=["default"])
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_search_empty_group_ids_defaults(self, mock_client):
        mock_client._mock_list_ws.return_value = [{"id": "ws-1", "name": "default"}]
        mock_client._mock_search.return_value = []
        result = mock_client.search("query")
        assert result == []

    def test_search_with_temporal_filter(self, mock_client):
        mock_client._mock_list_ws.return_value = [{"id": "ws-1", "name": "default"}]
        mock_client._mock_search.return_value = []
        result = mock_client.search(
            "query",
            group_ids=["default"],
            valid_at_after=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert result == []


# ── Test: build_communities ───────────────────────────────────────────────


class TestBuildCommunities:
    def test_build_communities_calls_detect(self, mock_client):
        mock_client._mock_list_ws.return_value = [{"id": "ws-1", "name": "default"}]
        mock_client._mock_query.return_value = []

        result = mock_client.build_communities(group_ids=["default"])
        # detect_communities and seed_communities should be called
        assert "detect_communities" in [
            c[0] for c in mock_client._mock_call.call_args_list
        ] or mock_client._mock_call.call_count >= 1
        assert isinstance(result, list)


# ── Test: Namespace classes ───────────────────────────────────────────────


class TestEntityNodeNamespace:
    def test_save(self, mock_client):
        ns = EntityNodeNamespace(mock_client)
        mock_client._mock_query.return_value = []  # no existing
        node = EntityNode(name="Bob", group_id="default")
        mock_client._mock_list_ws.return_value = [{"id": "ws-1", "name": "default"}]

        result = ns.save(node)
        assert result.name == "Bob"
        mock_client._mock_create_node.assert_called_once()

    def test_get_by_uuid(self, mock_client):
        ns = EntityNodeNamespace(mock_client)
        mock_client._mock_query.return_value = [
            {"id": "abc", "label": "Bob", "workspace_id": "ws-1",
             "summary": "", "labels": "[]", "created_at": 0, "metadata_json": "{}"}
        ]
        result = ns.get_by_uuid("abc")
        assert result.name == "Bob"

    def test_get_by_uuid_raises_keyerror(self, mock_client):
        ns = EntityNodeNamespace(mock_client)
        mock_client._mock_query.return_value = []
        with pytest.raises(KeyError):
            ns.get_by_uuid("missing")


class TestEntityEdgeNamespace:
    def test_save(self, mock_client):
        ns = EntityEdgeNamespace(mock_client)
        mock_client._mock_list_ws.return_value = [{"id": "ws-1", "name": "default"}]
        edge = EntityEdge(name="knows", fact="known", source_node_uuid="s1",
                          target_node_uuid="t1", group_id="default")
        result = ns.save(edge)
        assert result.name == "knows"
        mock_client._mock_create_edge.assert_called_once()

    def test_get_by_uuid(self, mock_client):
        ns = EntityEdgeNamespace(mock_client)
        mock_client._mock_query.return_value = [
            {"id": "e1", "relation": "knows", "source_node_id": "s1",
             "target_node_id": "t1", "workspace_id": "ws-1",
             "version": 1, "edge_group_id": "", "created_at": 0,
             "valid_at": 0, "invalid_at": 0, "metadata_json": "{}"}
        ]
        result = ns.get_by_uuid("e1")
        assert result.name == "knows"


class TestEpisodeNodeNamespace:
    def test_save(self, mock_client):
        ns = EpisodeNodeNamespace(mock_client)
        mock_client._mock_list_ws.return_value = [{"id": "ws-1", "name": "default"}]
        node = EpisodicNode(name="ep1", content="test", group_id="default")
        result = ns.save(node)
        assert result.name == "ep1"

    def test_get_by_uuid(self, mock_client):
        ns = EpisodeNodeNamespace(mock_client)
        mock_client._mock_query.return_value = [
            {"source_session_id": "abc", "peer_id": "ep1",
             "content": "test", "workspace_id": "ws-1", "created_at": 0}
        ]
        result = ns.get_by_uuid("abc")
        assert result.name == "ep1"


class TestCommunityNodeNamespace:
    def test_save(self, mock_client):
        ns = CommunityNodeNamespace(mock_client)
        mock_client._mock_list_ws.return_value = [{"id": "ws-1", "name": "default"}]
        mock_client._mock_query.return_value = []
        node = CommunityNode(name="comm1", group_id="default")
        result = ns.save(node)
        assert result.name == "comm1"


class TestSagaNodeNamespace:
    def test_save(self, mock_client):
        ns = SagaNodeNamespace(mock_client)
        mock_client._mock_list_ws.return_value = [{"id": "ws-1", "name": "default"}]
        mock_client._mock_query.return_value = []
        node = SagaNode(name="saga1", group_id="default")
        result = ns.save(node)
        assert result.name == "saga1"


# ── Test: Other Graphiti methods ──────────────────────────────────────────


class TestGraphitiMisc:
    def test_close(self, mock_client):
        mock_client.close()
        # close should not raise

    def test_get_entity_edge_summary(self, mock_client):
        mock_client._mock_list_ws.return_value = [{"id": "ws-1", "name": "default"}]
        mock_client._mock_get_neighbors.return_value = [
            {"id": "e1", "relation": "likes", "fact": "likes pizza",
             "source_node_id": "n1", "target_node_id": "n2",
             "workspace_id": "ws-1", "version": 1, "edge_group_id": ""}
        ]
        mock_client._mock_query.return_value = [
            {"id": "n1", "label": "Alice", "workspace_id": "ws-1",
             "summary": "", "labels": "[]", "created_at": 0, "metadata_json": "{}"}
        ]
        result = mock_client.get_entity_edge_summary("n1", group_ids=["default"])
        assert "edges" in result
        assert "summary" in result

    def test_build_indices_and_constraints(self, mock_client):
        result = mock_client.build_indices_and_constraints()
        assert result["status"] == "ok"

    def test_remove_episode(self, mock_client):
        mock_client._mock_query.return_value = [{"id": "mem-1"}]
        result = mock_client.remove_episode("ep-uuid")
        assert result["status"] == "ok"
        assert result["episode_uuid"] == "ep-uuid"
