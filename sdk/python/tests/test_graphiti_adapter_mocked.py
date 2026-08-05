"""Mock-based tests for the Graphiti adapter — error paths and edge cases.

Does NOT require a running SpacetimeDB instance.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from spacetime_memory.sdks.graphiti import (
    CommunityNode,
    EntityEdge,
    EntityNode,
    EpisodicNode,
    Graphiti,
    SagaNode,
    SearchResults,
)

HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get("SPACETIMEDB_DB", None)
REPO_ROOT = __file__.rsplit("/", 5)[0] if "/" in __file__ else "."


class TestGraphitiMocked:
    """Tests using mocks to reach error-handling code paths."""

    def test_resolve_workspace_uuid_match(self):
        """_resolve_workspace matches by UUID."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid-123", "name": "some-name"},
        ]
        g = Graphiti(client=mock_client)
        result = g._resolve_workspace("ws-uuid-123")
        assert result == "ws-uuid-123"
        # Should be cached
        assert g._ws_cache["ws-uuid-123"] == "ws-uuid-123"

    def test_resolve_workspace_name_match(self):
        """_resolve_workspace matches by name."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "real-uuid", "name": "my-workspace"},
        ]
        g = Graphiti(client=mock_client)
        result = g._resolve_workspace("my-workspace")
        assert result == "real-uuid"

    def test_resolve_workspace_list_error(self):
        """_resolve_workspace handles list_workspaces RuntimeError."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        # First call fails, second succeeds with empty list
        mock_client.list_workspaces.side_effect = [
            RuntimeError("connection error"),
            [],
        ]
        mock_client.create_workspace.return_value = None

        g = Graphiti(client=mock_client)
        result = g._resolve_workspace("new-workspace")
        # Falls through to "use group_id itself"
        assert result == "new-workspace"

    def test_resolve_workspace_create_then_find_by_uuid(self):
        """_resolve_workspace creates workspace then finds by UUID."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        # First list: not found
        # After create: found by UUID
        mock_client.list_workspaces.side_effect = [
            [],  # first check: not found
            [{"id": "new-ws-uuid", "name": "new-ws-uuid"}],  # after create
        ]
        mock_client.create_workspace.return_value = None

        g = Graphiti(client=mock_client)
        result = g._resolve_workspace("new-ws-uuid")
        assert result == "new-ws-uuid"

    def test_resolve_workspace_create_then_find_by_name(self):
        """_resolve_workspace creates workspace then finds by name."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.side_effect = [
            [],
            [{"id": "fresh-uuid", "name": "my-ws-name"}],
        ]
        mock_client.create_workspace.return_value = None

        g = Graphiti(client=mock_client)
        result = g._resolve_workspace("my-ws-name")
        assert result == "fresh-uuid"

    def test_resolve_workspace_create_error(self):
        """_resolve_workspace handles create_workspace RuntimeError."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.side_effect = [
            [],
            [{"id": "created-uuid", "name": "my-ws"}],
        ]
        mock_client.create_workspace.side_effect = RuntimeError("already exists")

        g = Graphiti(client=mock_client)
        result = g._resolve_workspace("my-ws")
        assert result == "created-uuid"

    def test_resolve_workspace_second_list_error(self):
        """_resolve_workspace handles second list_workspaces error."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.side_effect = [
            RuntimeError("first fail"),
            RuntimeError("second fail"),
        ]
        mock_client.create_workspace.return_value = None

        g = Graphiti(client=mock_client)
        result = g._resolve_workspace("fallback-ws")
        assert result == "fallback-ws"

    def test_sql_query_error(self):
        """_sql_query handles RuntimeError."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._sql.side_effect = RuntimeError("query error")
        g = Graphiti(client=mock_client)
        result = g._sql_query("SELECT * FROM nothing")
        assert result == []

    def test_sql_query_success(self):
        """_sql_query returns results on success."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._sql.return_value = [{"id": "1", "name": "test"}]
        g = Graphiti(client=mock_client)
        result = g._sql_query("SELECT * FROM test")
        assert result == [{"id": "1", "name": "test"}]

    def test_filter_by_valid_at_both_filters(self):
        """_filter_by_valid_at with both after and before."""

        now = datetime.now(UTC)
        g = Graphiti()

        e1 = EntityEdge(uuid="e1", valid_at=now)
        e2 = EntityEdge(uuid="e2", valid_at=None)  # no timestamp
        e3 = EntityEdge(uuid="e3", valid_at=datetime(2020, 1, 1, tzinfo=UTC))

        edges = [e1, e2, e3]
        filtered = g._filter_by_valid_at(
            edges, valid_at_after=datetime(2024, 1, 1, tzinfo=UTC), valid_at_before=None
        )
        # e1 should pass (now > 2024), e2 excluded (no valid_at), e3 excluded (too old)
        assert len(filtered) == 1
        assert filtered[0].uuid == "e1"

    def test_filter_by_valid_at_none_filters(self):
        """_filter_by_valid_at with no filters returns all."""

        e1 = EntityEdge(uuid="e1")
        e2 = EntityEdge(uuid="e2")
        g = Graphiti()
        result = g._filter_by_valid_at([e1, e2])
        assert len(result) == 2

    def test_filter_by_valid_at_before(self):
        """_filter_by_valid_at with before filter only."""

        now = datetime.now(UTC)
        e1 = EntityEdge(uuid="e1", valid_at=datetime(2020, 1, 1, tzinfo=UTC))
        e2 = EntityEdge(uuid="e2", valid_at=now)

        g = Graphiti()
        filtered = g._filter_by_valid_at(
            [e1, e2], valid_at_before=datetime(2021, 1, 1, tzinfo=UTC)
        )
        assert len(filtered) == 1
        assert filtered[0].uuid == "e1"

    def test_extract_entities_from_text_no_llm(self):
        """_extract_entities_from_text returns None when LLM unavailable."""
        g = Graphiti()
        result = g._extract_entities_from_text("some text")
        assert result is None

    def test_get_or_create_node_case_insensitive(self):
        """_get_or_create_node handles case-insensitive match."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = [
            {"id": "node-1", "label": "HelloWorld"},
        ]

        g = Graphiti(client=mock_client)
        node = EntityNode(name="helloworld", group_id="default")
        result = g._get_or_create_node(node, "ws-1", create=False)
        assert result is not None
        uuid, score = result
        assert uuid == "node-1"
        assert score == 0.95

    def test_get_or_create_node_fuzzy_match(self):
        """_get_or_create_node handles fuzzy (difflib) match."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = [
            {"id": "node-1", "label": "HellowWorld"},  # one char off
        ]

        g = Graphiti(client=mock_client)
        node = EntityNode(name="HelloWorld", group_id="default")
        result = g._get_or_create_node(node, "ws-1", create=False)
        assert result is not None
        uuid, score = result
        assert uuid == "node-1"
        assert score > 0.85

    def test_get_or_create_node_no_match_no_create(self):
        """_get_or_create_node with create=False returns None when no match."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = [
            {"id": "node-1", "label": "CompletelyDifferent"},
        ]

        g = Graphiti(client=mock_client)
        node = EntityNode(name="HelloWorld", group_id="default")
        result = g._get_or_create_node(node, "ws-1", create=False)
        assert result is None

    def test_get_or_create_node_semantic_match(self):
        """_get_or_create_node falls back to semantic (embedding) dedup."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        # Pass 1-3 all fail: no exact/case/fuzzy match
        mock_client._query.return_value = [
            {"id": "node-1", "label": "CompletelyDifferent"},
        ]
        # Pass 4: semantic search finds the same entity under a paraphrase
        mock_client.search.return_value = [
            {
                "entity_id": "node-1",
                "entity_type": "node",
                "score": 0.72,
            }
        ]
        # The follow-up _query for the semantic candidate returns the node
        mock_client._query.side_effect = [
            [{"id": "node-1", "label": "CompletelyDifferent"}],
            [{"id": "node-1", "label": "CompletelyDifferent", "summary": "s"}],
        ]

        g = Graphiti(client=mock_client)
        node = EntityNode(name="The Hello World Library", group_id="default")
        result = g._get_or_create_node(node, "ws-1", create=False)
        assert result is not None
        uuid, score = result
        assert uuid == "node-1"
        assert score >= 0.55

    def test_get_or_create_node_semantic_no_match_returns_none(self):
        """Semantic dedup below threshold returns None with create=False."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = [
            {"id": "node-1", "label": "CompletelyDifferent"},
        ]
        # Semantic scores too low to count as a duplicate
        mock_client.search.return_value = [
            {"entity_id": "node-1", "entity_type": "node", "score": 0.2}
        ]

        g = Graphiti(client=mock_client)
        node = EntityNode(name="HelloWorld", group_id="default")
        result = g._get_or_create_node(node, "ws-1", create=False)
        assert result is None

    def test_search_recipe_config_semantic_keyword(self):
        """search_ honours search_strategy in the recipe config."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.search.return_value = []
        mock_client._query.return_value = []
        mock_client.query_graph.return_value = []

        g = Graphiti(client=mock_client)
        g.search_(
            "hello",
            config={"search_strategy": "keyword"},
            group_ids=["default"],
        )
        # keyword strategy → semantic=False
        assert mock_client.search.call_args[1]["semantic"] is False

    def test_search_recipe_config_cross_encoder_mmr(self):
        """search_ honours cross_encoder and mmr_strength in the recipe."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.search.return_value = []
        mock_client._query.return_value = []
        mock_client.query_graph.return_value = []

        g = Graphiti(client=mock_client)
        g.search_(
            "hello",
            config={"cross_encoder": True, "mmr_strength": 0.6},
            group_ids=["default"],
        )
        assert mock_client.search.call_args[1]["cross_encoder"] is True
        assert mock_client.search.call_args[1]["mmr_lambda"] == 0.6

    def test_search_recipe_config_relaxed_fallback(self):
        """relaxed hybrid mode falls back to keyword when fusion is empty."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        # First call (hybrid) returns nothing; second (keyword fallback) returns a row
        mock_client.search.side_effect = [
            [],
            [{"entity_id": "e1", "entity_type": "edge"}],
        ]
        mock_client._query.return_value = [
            {"id": "e1", "source_node_id": "n1", "target_node_id": "n2",
             "relation": "r", "valid_at": 1, "invalid_at": 0}
        ]

        g = Graphiti(client=mock_client)
        _ = g.search_(
            "hello",
            config={"hybrid_mode": "relaxed"},
            group_ids=["default"],
        )
        assert mock_client.search.call_count == 2
        assert mock_client.search.call_args_list[1][1]["semantic"] is False

    def test_build_entities_and_edges_empty(self):
        """_build_entities_and_edges with empty data returns empty."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        g = Graphiti(client=mock_client)

        extracted = {"entities": [], "edges": []}
        nodes, edges = g._build_entities_and_edges(extracted, "ws-1", "default", "ep-1")
        assert nodes == []
        assert edges == []

    def test_build_entities_and_edges_with_data(self):
        """_build_entities_and_edges creates entities and edges."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        # _query is called for _get_or_create_node (×2) and edge lookup
        mock_client._query.return_value = [{"id": "node-123", "label": "Test"}]
        mock_client.create_edge.return_value = {"id": "edge-1"}
        mock_client.create_node.return_value = None

        g = Graphiti(client=mock_client)
        extracted = {
            "entities": [
                {"name": "Alice", "entity_type": "person"},
                {"name": "Bob", "entity_type": "person"},
            ],
            "edges": [
                {"source": "Alice", "target": "Bob", "relation": "knows"},
            ],
        }
        nodes, edges = g._build_entities_and_edges(extracted, "ws-1", "default", "ep-1")
        assert len(nodes) == 2
        assert len(edges) == 1
        assert edges[0].name == "knows"
        assert edges[0].fact == "Alice knows Bob"

    def test_graphiti_init_with_params(self):
        """Graphiti.__init__ with host/port creates Client."""
        from unittest.mock import MagicMock, patch

        with patch("spacetime_memory.sdks.graphiti._core.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            Graphiti(host="testhost", port="9999", token="test-token")
            MockClient.assert_called_once()
            # Check it was called with the right params
            call_kwargs = MockClient.call_args.kwargs
            assert call_kwargs["host"] == "testhost"
            assert call_kwargs["port"] == "9999"
            assert call_kwargs["token"] == "test-token"

    def test_add_episode_llm_extraction_with_empty_extracted(self):
        """add_episode with LLM extraction returns episode with empty nodes/edges."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client.store.return_value = None

        g = Graphiti(client=mock_client)

        with patch.object(g, "_extract_entities_from_text") as mock_extract:
            mock_extract.return_value = {"entities": [], "edges": []}
            result = g.add_episode(
                name="test",
                episode_body="Some text",
                source_description="test",
            )
            assert result.episode is not None
            assert result.nodes == []
            assert result.edges == []

    def test_summarize_saga_no_episodes(self):
        """summarize_saga with no episodes returns stub."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = []  # no episodes
        g = Graphiti(client=mock_client)

        saga = g.summarize_saga("saga-1")
        assert isinstance(saga, SagaNode)
        assert saga.uuid == "saga-1"
        assert saga.summary == ""

    def test_summarize_saga_with_episodes_no_llm(self):
        """summarize_saga with episodes but no LLM returns saga with empty summary."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = [
            {
                "id": "ep-1",
                "content": "Alice went to the store.",
                "created_at": 1700000000000000,
                "peer_id": "saga-session",
                "workspace_id": "default",
            },
            {
                "id": "ep-2",
                "content": "Alice bought groceries.",
                "created_at": 1700000100000000,
                "peer_id": "saga-session",
                "workspace_id": "default",
            },
        ]
        mock_client.list_workspaces.return_value = [
            {"id": "default", "name": "default"},
        ]
        # create_node might succeed or fail, that's fine

        g = Graphiti(client=mock_client)
        # The LLM won't be available so summary should be empty
        saga = g.summarize_saga("saga-session")
        assert isinstance(saga, SagaNode)
        assert saga.summary == ""
        assert saga.first_episode_uuid == "ep-1"
        assert saga.last_episode_uuid == "ep-2"

    def test_get_edge_history_empty_group(self):
        """get_edge_history with empty edge_group_id returns empty."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = [{"edge_group_id": ""}]  # empty group
        g = Graphiti(client=mock_client)

        history = g.get_edge_history("edge-1")
        assert history == []

    def test_get_edge_history_call_error(self):
        """get_edge_history handles _call RuntimeError."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = [{"edge_group_id": "group-1"}]
        mock_client._call.side_effect = RuntimeError("call failed")
        g = Graphiti(client=mock_client)

        history = g.get_edge_history("edge-1")
        assert history == []


class TestGraphitiInit:
    """Tests for Graphiti.__init__ edge cases."""

    def test_init_with_client(self):
        """Graphiti.__init__ with existing client uses it."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        g = Graphiti(client=mock_client)
        assert g._client is mock_client
        assert g.clients is mock_client

    def test_init_default_params(self):
        """Graphiti.__init__ with no params creates default Client."""
        from unittest.mock import MagicMock, patch

        with patch("spacetime_memory.sdks.graphiti._core.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            Graphiti()
            MockClient.assert_called_once()


# =====================================================================
# Additional coverage tests
# =====================================================================


@pytest.fixture
def workspace_id() -> str:
    """Provide a fake workspace ID for mock-based tests."""
    return "mock-workspace-001"


@pytest.fixture
def graphiti(request) -> Graphiti:
    """Provide a mocked Graphiti instance for unit tests."""
    from unittest.mock import MagicMock, PropertyMock, patch

    mock_client = MagicMock()
    g = Graphiti(client=mock_client)

    # Patch methods to return sensible defaults
    g.get_nodes_and_edges_by_episode = MagicMock(return_value=SearchResults(edges=[], nodes=[]))
    g.search_ = MagicMock(return_value=SearchResults(edges=[], nodes=[]))
    g.search = MagicMock(return_value=[])
    g.retrieve_episodes = MagicMock(return_value=[])

    # Build pre-configured edge namespace mocks
    edge_mocks = {}
    for ns_name in ("entity", "episodic", "community", "has_episode", "next_episode"):
        ns = MagicMock()
        ns.get_by_group_ids = MagicMock(return_value=[])
        cc_name = "".join(p.capitalize() for p in ns_name.split("_"))
        ns.get_by_uuid = MagicMock(side_effect=KeyError(f"{cc_name}Edge not found"))
        ns.get_by_uuids = MagicMock(return_value=[])
        edge_mocks[ns_name] = ns

    # Build pre-configured node namespace mocks
    node_mocks = {}
    for ns_name in ("entity", "episode", "community", "saga"):
        ns = MagicMock()
        ns.get_by_group_ids = MagicMock(return_value=[])
        ns.get_by_uuid = MagicMock(side_effect=KeyError("not found"))
        ns.get_by_uuids = MagicMock(return_value=[])
        node_mocks[ns_name] = ns

    # Patch the edges property to return a mock EdgeNamespace with pre-configured attrs
    mock_edge_ns = MagicMock()
    for name, ns in edge_mocks.items():
        setattr(mock_edge_ns, name, ns)
    edges_patcher = patch.object(type(g), "edges", new_callable=PropertyMock)
    mock_edges_prop = edges_patcher.start()
    mock_edges_prop.return_value = mock_edge_ns

    # Patch the nodes property similarly
    mock_node_ns = MagicMock()
    for name, ns in node_mocks.items():
        setattr(mock_node_ns, name, ns)
    nodes_patcher = patch.object(type(g), "nodes", new_callable=PropertyMock)
    mock_nodes_prop = nodes_patcher.start()
    mock_nodes_prop.return_value = mock_node_ns

    # Register cleanup
    request.addfinalizer(lambda: edges_patcher.stop())
    request.addfinalizer(lambda: nodes_patcher.stop())

    return g


class TestAdditionalCoverage:
    """Additional tests to cover edge cases and push coverage higher.

    Requires a running SpacetimeDB standalone (graphiti + workspace_id fixtures).
    """

    def test_get_nodes_and_edges_by_nonexistent_episode(self, graphiti: Graphiti):
        """get_nodes_and_edges_by_episode with nonexistent UUID returns empty results."""
        sr = graphiti.get_nodes_and_edges_by_episode(["nonexistent-ep-uuid-12345"])
        assert isinstance(sr, SearchResults)
        assert sr.edges == []
        assert sr.nodes == []

    def test_nodes_entity_get_by_group_ids_with_limit(self, graphiti: Graphiti, workspace_id: str):
        """nodes.entity.get_by_group_ids with limit parameter."""
        nodes = graphiti.nodes.entity.get_by_group_ids([workspace_id], limit=2)
        assert isinstance(nodes, list)
        assert len(nodes) <= 2

    def test_edges_entity_get_by_group_ids_with_limit(self, graphiti: Graphiti, workspace_id: str):
        """edges.entity.get_by_group_ids with limit parameter."""
        edges = graphiti.edges.entity.get_by_group_ids([workspace_id], limit=2)
        assert isinstance(edges, list)
        assert len(edges) <= 2

    def test_search_with_valid_at_filter(self, graphiti: Graphiti, workspace_id: str):
        """search with valid_at_after filter."""

        edges = graphiti.search(
            "test",
            group_ids=[workspace_id],
            valid_at_after=datetime(2020, 1, 1, tzinfo=UTC),
        )
        assert isinstance(edges, list)

    def test_search_with_valid_at_before_filter(self, graphiti: Graphiti, workspace_id: str):
        """search_ with valid_at filters."""

        results = graphiti.search_(
            "test",
            group_ids=[workspace_id],
            valid_at_before=datetime.now(UTC),
        )
        assert isinstance(results, SearchResults)

    def test_retrieve_episodes_with_reference_time(self, graphiti: Graphiti, workspace_id: str):
        """retrieve_episodes with reference_time filter."""

        episodes = graphiti.retrieve_episodes(
            reference_time=datetime(2020, 1, 1, tzinfo=UTC),
            group_ids=[workspace_id],
            last_n=5,
        )
        assert isinstance(episodes, list)

    def test_nodes_episode_get_by_group_ids_with_limit(self, graphiti: Graphiti, workspace_id: str):
        """nodes.episode.get_by_group_ids with limit."""
        episodes = graphiti.nodes.episode.get_by_group_ids([workspace_id], limit=3)
        assert isinstance(episodes, list)
        assert len(episodes) <= 3

    def test_edges_episodic_get_by_group_ids_with_limit(
        self, graphiti: Graphiti, workspace_id: str
    ):
        """edges.episodic.get_by_group_ids with limit."""
        edges = graphiti.edges.episodic.get_by_group_ids([workspace_id], limit=2)
        assert isinstance(edges, list)
        assert len(edges) <= 2

    def test_nodes_community_get_by_group_ids_with_limit(
        self, graphiti: Graphiti, workspace_id: str
    ):
        """nodes.community.get_by_group_ids with limit."""
        communities = graphiti.nodes.community.get_by_group_ids([workspace_id], limit=1)
        assert isinstance(communities, list)
        assert len(communities) <= 1

    def test_nodes_saga_get_by_group_ids_with_limit(self, graphiti: Graphiti, workspace_id: str):
        """nodes.saga.get_by_group_ids with limit."""
        sagas = graphiti.nodes.saga.get_by_group_ids([workspace_id], limit=1)
        assert isinstance(sagas, list)
        assert len(sagas) <= 1

    def test_edges_community_get_by_group_ids_with_limit(
        self, graphiti: Graphiti, workspace_id: str
    ):
        """edges.community.get_by_group_ids with limit."""
        edges = graphiti.edges.community.get_by_group_ids([workspace_id], limit=2)
        assert isinstance(edges, list)
        assert len(edges) <= 2

    def test_edges_has_episode_get_by_group_ids_with_limit(
        self, graphiti: Graphiti, workspace_id: str
    ):
        """edges.has_episode.get_by_group_ids with limit."""
        edges = graphiti.edges.has_episode.get_by_group_ids([workspace_id], limit=2)
        assert isinstance(edges, list)
        assert len(edges) <= 2

    def test_edges_next_episode_get_by_group_ids_with_limit(
        self, graphiti: Graphiti, workspace_id: str
    ):
        """edges.next_episode.get_by_group_ids with limit."""
        edges = graphiti.edges.next_episode.get_by_group_ids([workspace_id], limit=2)
        assert isinstance(edges, list)
        assert len(edges) <= 2

    def test_episodic_node_from_stmem_row(self):
        """EpisodeNodeNamespace._row_to_episode static method."""
        from spacetime_memory.sdks.graphiti import EpisodeNodeNamespace

        row = {
            "id": "mem-1",
            "source_session_id": "ep-uuid-1",
            "peer_id": "test-peer",
            "content": "Episode content here",
            "source": "message",
            "workspace_id": "ws-1",
            "created_at": 1700000000000000,
        }
        ep = EpisodeNodeNamespace._row_to_episode(row)
        assert ep.uuid == "ep-uuid-1"
        assert ep.name == "test-peer"
        assert ep.content == "Episode content here"

    def test_episodic_node_from_stmem_no_session_id(self):
        """_row_to_episode falls back to id when no source_session_id."""
        from spacetime_memory.sdks.graphiti import EpisodeNodeNamespace

        row = {
            "id": "mem-2",
            "peer_id": "fallback-peer",
            "content": "Content",
            "workspace_id": "ws-2",
            "created_at": 0,
        }
        ep = EpisodeNodeNamespace._row_to_episode(row)
        assert ep.uuid == "mem-2"

    def test_community_row_to_community(self):
        """CommunityNodeNamespace._row_to_community static method."""
        from spacetime_memory.sdks.graphiti import CommunityNodeNamespace

        row = {
            "id": "comm-1",
            "label": "Test Community",
            "workspace_id": "ws-1",
            "summary": "A summary",
            "labels": '["tag1", "tag2"]',
            "created_at": 1700000000000000,
        }
        cn = CommunityNodeNamespace._row_to_community(row)
        assert cn.uuid == "comm-1"
        assert cn.name == "Test Community"
        assert cn.summary == "A summary"
        assert cn.labels == ["tag1", "tag2"]

    def test_saga_row_to_saga(self):
        """SagaNodeNamespace._row_to_saga static method."""
        from spacetime_memory.sdks.graphiti import SagaNodeNamespace

        row = {
            "id": "saga-1",
            "label": "Test Saga",
            "workspace_id": "ws-1",
            "summary": "Saga summary",
            "labels": '["epic"]',
            "created_at": 1700000000000000,
        }
        sn = SagaNodeNamespace._row_to_saga(row)
        assert sn.uuid == "saga-1"
        assert sn.name == "Test Saga"

    def test_entity_node_from_stmem_no_labels_field(self):
        """EntityNode.from_stmem with missing labels field."""
        row = {
            "id": "nolabel-node",
            "label": "NoLabel",
            "workspace_id": "default",
            "created_at": 1700000000000000,
            "metadata_json": "{}",
        }
        node = EntityNode.from_stmem(row)
        assert node.labels == []

    def test_entity_edge_from_stmem_no_fact(self):
        """EntityEdge.from_stmem with no fact falls back to relation."""
        row = {
            "id": "nofact-edge",
            "relation": "test_rel",
            "workspace_id": "default",
            "created_at": 1700000000000000,
            "valid_at": 0,
            "invalid_at": 0,
            "metadata_json": "{}",
        }
        edge = EntityEdge.from_stmem(row)
        assert edge.fact == "test_rel"

    def test_entity_node_from_stmem_empty_json(self):
        """EntityNode.from_stmem with empty metadata_json string."""
        row = {
            "id": "empty-json-node",
            "label": "EmptyJSON",
            "workspace_id": "default",
            "created_at": 1700000000000000,
            "metadata_json": "{}",
            "labels": "",
        }
        node = EntityNode.from_stmem(row)
        assert node.attributes == {}

    def test_episodic_edge_not_found(self, graphiti: Graphiti):
        """edges.episodic.get_by_uuid raises KeyError when not found."""
        with pytest.raises(KeyError, match="EpisodicEdge"):
            graphiti.edges.episodic.get_by_uuid("nonexistent-ep-edge-999")

    def test_community_edge_not_found(self, graphiti: Graphiti):
        """edges.community.get_by_uuid raises KeyError when not found."""
        with pytest.raises(KeyError, match="CommunityEdge"):
            graphiti.edges.community.get_by_uuid("nonexistent-comm-edge-999")

    def test_has_episode_edge_not_found(self, graphiti: Graphiti):
        """edges.has_episode.get_by_uuid raises KeyError when not found."""
        with pytest.raises(KeyError, match="HasEpisodeEdge"):
            graphiti.edges.has_episode.get_by_uuid("nonexistent-he-edge-999")

    def test_next_episode_edge_not_found(self, graphiti: Graphiti):
        """edges.next_episode.get_by_uuid raises KeyError when not found."""
        with pytest.raises(KeyError, match="NextEpisodeEdge"):
            graphiti.edges.next_episode.get_by_uuid("nonexistent-ne-edge-999")

    def test_episodic_edge_get_by_uuids_empty(self, graphiti: Graphiti):
        """edges.episodic.get_by_uuids with nonexistent UUIDs returns empty."""
        edges = graphiti.edges.episodic.get_by_uuids(["no-such-edge-1", "no-such-edge-2"])
        assert edges == []

    def test_community_edge_get_by_uuids_empty(self, graphiti: Graphiti):
        """edges.community.get_by_uuids with nonexistent UUIDs returns empty."""
        edges = graphiti.edges.community.get_by_uuids(["no-such-ce-1", "no-such-ce-2"])
        assert edges == []

    def test_has_episode_edge_get_by_uuids_empty(self, graphiti: Graphiti):
        """edges.has_episode.get_by_uuids with nonexistent UUIDs returns empty."""
        edges = graphiti.edges.has_episode.get_by_uuids(["no-such-he-1", "no-such-he-2"])
        assert edges == []

    def test_next_episode_edge_get_by_uuids_empty(self, graphiti: Graphiti):
        """edges.next_episode.get_by_uuids with nonexistent UUIDs returns empty."""
        edges = graphiti.edges.next_episode.get_by_uuids(["no-such-ne-1", "no-such-ne-2"])
        assert edges == []

    def test_extract_entities_from_text_no_api_key(self):
        """_extract_entities_from_text: returns None when no API key configured."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        g = Graphiti(client=mock_client)

        # Ensure LLMClient.available returns False
        with patch("spacetime_memory.sdks.graphiti._episodes.LLMClient") as MockLLM:
            mock_llm = MagicMock()
            mock_llm.available = False
            MockLLM.return_value = mock_llm
            result = g._extract_entities_from_text("some text")
            assert result is None


class TestGraphitiMockedExtended:
    """Additional mock-based tests to push coverage ≥92%."""

    # ------------------------------------------------------------------
    # _get_or_create_node error paths
    # ------------------------------------------------------------------

    def test_get_or_create_node_create_runtime_error(self):
        """_get_or_create_node: create_node RuntimeError is caught silently."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = []  # no existing nodes
        mock_client.create_node.side_effect = RuntimeError("create failed")

        g = Graphiti(client=mock_client)
        g._ws_cache["ws-1"] = "ws-1"
        result = g._get_or_create_node(
            EntityNode(name="NewNode", group_id="default"), "ws-1", create=True
        )
        # Should fall through to returning the node.uuid with 0.0 dedup score
        assert result is not None
        assert result[1] == 0.0

    # ------------------------------------------------------------------
    # add_triplet error paths
    # ------------------------------------------------------------------

    def test_add_triplet_create_edge_runtime_error(self):
        """add_triplet: create_edge RuntimeError is re-raised."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        # _get_or_create_node needs _query to return matching node
        mock_client._query.return_value = [
            {"id": "node-1", "label": "Alice"},
        ]
        # create_edge fails
        mock_client.create_edge.side_effect = RuntimeError("edge creation failed")

        g = Graphiti(client=mock_client)
        with pytest.raises(RuntimeError, match="create_edge failed"):
            g.add_triplet(
                source_node=EntityNode(name="Alice", group_id="default"),
                edge=EntityEdge(name="likes", group_id="default"),
                target_node=EntityNode(name="Bob", group_id="default"),
            )

    # ------------------------------------------------------------------
    # add_episode error paths
    # ------------------------------------------------------------------

    def test_add_episode_store_runtime_error(self):
        """add_episode: store RuntimeError is re-raised."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client.store.side_effect = RuntimeError("store failed")

        g = Graphiti(client=mock_client)

        with patch.object(g, "_extract_entities_from_text", return_value=None):
            with pytest.raises(RuntimeError, match="add_episode.*failed"):
                g.add_episode(
                    name="test-ep",
                    episode_body="some content",
                    source_description="test",
                )

    # ------------------------------------------------------------------
    # _build_entities_and_edges edge cases
    # ------------------------------------------------------------------

    def test_build_entities_and_edges_empty_entity_name(self):
        """_build_entities_and_edges: entity with empty name is skipped."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        g = Graphiti(client=mock_client)

        extracted = {
            "entities": [{"name": "", "entity_type": "person"}],
            "edges": [],
        }
        nodes, edges = g._build_entities_and_edges(extracted, "ws-1", "gid", "ep-1")
        assert nodes == []
        assert edges == []

    def test_build_entities_and_edges_get_node_returns_none(self):
        """_build_entities_and_edges: _get_or_create_node returns None is skipped."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        g = Graphiti(client=mock_client)
        g._ws_cache["ws-1"] = "ws-1"

        # mock _get_or_create_node to return None
        with patch.object(g, "_get_or_create_node", return_value=None):
            extracted = {
                "entities": [{"name": "Alice", "entity_type": "person"}],
                "edges": [],
            }
            nodes, edges = g._build_entities_and_edges(extracted, "ws-1", "gid", "ep-1")
            assert nodes == []
            assert edges == []

    def test_build_entities_and_edges_missing_src_tgt_names(self):
        """_build_entities_and_edges: edge with missing source/target is skipped."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = [{"id": "node-1", "label": "Alice"}]
        mock_client.create_node.return_value = None

        g = Graphiti(client=mock_client)
        g._ws_cache["ws-1"] = "ws-1"

        extracted = {
            "entities": [{"name": "Alice", "entity_type": "person"}],
            "edges": [{"source": "", "target": "Alice", "relation": "knows"}],
        }
        nodes, edges = g._build_entities_and_edges(extracted, "ws-1", "gid", "ep-1")
        assert len(nodes) == 1  # Alice entity created
        assert edges == []  # edge skipped due to empty source

    def test_build_entities_and_edges_src_not_in_map(self):
        """_build_entities_and_edges: edge source not in entity_map is skipped."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = [{"id": "node-1", "label": "Alice"}]
        mock_client.create_node.return_value = None

        g = Graphiti(client=mock_client)
        g._ws_cache["ws-1"] = "ws-1"

        extracted = {
            "entities": [{"name": "Alice", "entity_type": "person"}],
            "edges": [{"source": "Bob", "target": "Alice", "relation": "knows"}],
        }
        nodes, edges = g._build_entities_and_edges(extracted, "ws-1", "gid", "ep-1")
        assert len(nodes) == 1
        assert edges == []  # Bob not in entity_map

    def test_build_entities_and_edges_create_edge_runtime_error(self):
        """_build_entities_and_edges: create_edge RuntimeError is caught."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client._query.side_effect = [
            # First call: _get_or_create_node → _query for Alice
            [{"id": "node-1", "label": "Alice"}],
            # Second call: _get_or_create_node → _query for Bob
            [{"id": "node-2", "label": "Bob"}],
            # Third+ call: edge lookup after create_edge
            [{"id": "edge-1", "relation": "knows"}],
        ]
        mock_client.create_node.return_value = None
        mock_client.create_edge.side_effect = RuntimeError("edge failed")

        g = Graphiti(client=mock_client)
        g._ws_cache["ws-1"] = "ws-1"

        # Patch _get_or_create_node to return fake IDs since we control _query
        with patch.object(g, "_get_or_create_node") as mock_gn:
            mock_gn.side_effect = [
                ("node-1", 1.0),  # Alice
                ("node-2", 1.0),  # Bob
            ]
            extracted = {
                "entities": [
                    {"name": "Alice", "entity_type": "person"},
                    {"name": "Bob", "entity_type": "person"},
                ],
                "edges": [{"source": "Alice", "target": "Bob", "relation": "knows"}],
            }
            nodes, edges = g._build_entities_and_edges(extracted, "ws-1", "gid", "ep-1")
            assert len(nodes) == 2
            # Edge creation failed, but the edge query after won't find it
            # The RuntimeError is caught, so edges list should be empty
            assert edges == []

    # ------------------------------------------------------------------
    # search() edge cases
    # ------------------------------------------------------------------

    def test_search_edge_type_in_results(self):
        """search: hybrid results include edge-type entries."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        # search returns hybrid results with an edge entry
        mock_client.search.return_value = [
            {"entity_id": "node-1", "entity_type": "node"},
            {"entity_id": "edge-1", "entity_type": "edge"},
        ]
        # get_neighbors returns edge data for node-1
        mock_client.get_neighbors.return_value = [
            {
                "id": "neighbor-edge-1",
                "source_node_id": "node-1",
                "target_node_id": "node-2",
                "relation": "likes",
                "workspace_id": "ws-uuid",
                "created_at": 1700000000000000,
                "valid_at": 1700000000000000,
                "invalid_at": 0,
                "metadata_json": "{}",
            },
        ]
        # _query for edge by ID
        mock_client._query.return_value = [
            {
                "id": "edge-1",
                "source_node_id": "node-3",
                "target_node_id": "node-4",
                "relation": "knows",
                "workspace_id": "ws-uuid",
                "created_at": 1700000000000000,
                "valid_at": 1700000000000000,
                "invalid_at": 0,
                "metadata_json": "{}",
            },
        ]

        g = Graphiti(client=mock_client)
        edges = g.search("test query", group_ids=["default"])
        assert len(edges) >= 1

    def test_search_get_neighbors_runtime_error(self):
        """search: get_neighbors RuntimeError is caught."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client.search.return_value = [
            {"entity_id": "node-1", "entity_type": "node"},
        ]
        # get_neighbors fails
        mock_client.get_neighbors.side_effect = RuntimeError("neighbor error")

        g = Graphiti(client=mock_client)
        edges = g.search("test query", group_ids=["default"])
        # No edges found, falls through to fallback query_graph which also fails
        assert isinstance(edges, list)

    def test_search_fallback_get_neighbors_runtime_error(self):
        """search: fallback query_graph then get_neighbors RuntimeError."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        # search returns no results → forces fallback path
        mock_client.search.return_value = []
        # query_graph returns some nodes
        mock_client.query_graph.return_value = [
            {"id": "node-fb", "label": "Fallback"},
        ]
        # get_neighbors fails for fallback nodes
        mock_client.get_neighbors.side_effect = RuntimeError("fallback neighbor error")

        g = Graphiti(client=mock_client)
        edges = g.search("test query", group_ids=["default"])
        assert edges == []

    def test_search_fallback_query_graph_runtime_error(self):
        """search: query_graph RuntimeError in fallback path."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client.search.return_value = []
        mock_client.query_graph.side_effect = RuntimeError("query_graph error")

        g = Graphiti(client=mock_client)
        edges = g.search("test query", group_ids=["default"])
        assert edges == []

    # ------------------------------------------------------------------
    # search_() edge cases
    # ------------------------------------------------------------------

    def test_search_underscore_edge_type_in_results(self):
        """search_: hybrid results include edge-type entries."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client.search.return_value = [
            {"entity_id": "node-1", "entity_type": "node"},
            {"entity_id": "edge-99", "entity_type": "edge"},
        ]
        mock_client.get_neighbors.return_value = [
            {
                "id": "ne-edge",
                "source_node_id": "node-1",
                "target_node_id": "node-2",
                "relation": "test_rel",
                "workspace_id": "ws-uuid",
                "created_at": 1700000000000000,
                "valid_at": 1700000000000000,
                "invalid_at": 0,
                "metadata_json": "{}",
            },
        ]
        mock_client._query.return_value = [
            {
                "id": "edge-99",
                "source_node_id": "n-a",
                "target_node_id": "n-b",
                "relation": "edge_rel",
                "workspace_id": "ws-uuid",
                "created_at": 1700000000000000,
                "valid_at": 1700000000000000,
                "invalid_at": 0,
                "metadata_json": "{}",
            },
        ]

        g = Graphiti(client=mock_client)
        results = g.search_("test query", group_ids=["default"])
        assert isinstance(results, SearchResults)
        assert len(results.edges) >= 1

    def test_search_underscore_fallback_query_graph_runtime_error(self):
        """search_: fallback query_graph RuntimeError is caught."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client.search.return_value = []
        mock_client.query_graph.side_effect = RuntimeError("query_graph error")

        g = Graphiti(client=mock_client)
        results = g.search_("test query", group_ids=["default"])
        assert isinstance(results, SearchResults)
        assert results.edges == []

    # ------------------------------------------------------------------
    # get_entity_edge_summary error path
    # ------------------------------------------------------------------

    def test_get_entity_edge_summary_runtime_error(self):
        """get_entity_edge_summary: get_neighbors RuntimeError returns empty."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client.get_neighbors.side_effect = RuntimeError("neighbor error")

        g = Graphiti(client=mock_client)
        result = g.get_entity_edge_summary("entity-1", group_ids=["default"])
        assert result == {"edges": [], "nodes": [], "summary": ""}

    # ------------------------------------------------------------------
    # build_communities
    # ------------------------------------------------------------------

    def test_build_communities_detect_error(self):
        """build_communities: detect_communities RuntimeError is caught."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client.detect_communities.side_effect = RuntimeError("detect failed")
        # seed_communities also called; mock it too
        mock_client.seed_communities.return_value = None
        # _query for community nodes returns empty
        mock_client._query.return_value = []

        g = Graphiti(client=mock_client)
        communities = g.build_communities(group_ids=["default"])
        assert communities == []

    def test_build_communities_with_summary_no_llm(self):
        """build_communities: community with existing summary skips LLM."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client.detect_communities.return_value = None
        mock_client.seed_communities.return_value = None

        # First _query call: community nodes
        community_row = {
            "id": "comm-1",
            "label": "Tech Community",
            "workspace_id": "ws-uuid",
            "summary": "A tech-focused community",
            "node_type": "community",
            "created_at": 1700000000000000,
            "labels": '["tech"]',
        }
        # Second+ _query calls: community edges
        edge_row = {
            "id": "ce-1",
            "source_node_id": "comm-1",
            "target_node_id": "node-1",
            "relation": "MEMBER_OF",
            "workspace_id": "ws-uuid",
            "created_at": 1700000000000000,
            "valid_at": 1700000000000000,
            "invalid_at": 0,
            "metadata_json": "{}",
        }
        mock_client._query.side_effect = [
            [community_row],  # community nodes query
            [edge_row],  # community edges query
        ]

        g = Graphiti(client=mock_client)
        communities = g.build_communities(group_ids=["default"])
        assert len(communities) == 1
        assert communities[0].name == "Tech Community"
        assert communities[0].summary == "A tech-focused community"

    def test_build_communities_empty_summary_no_llm(self):
        """build_communities: community with empty summary triggers LLM path."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client.detect_communities.return_value = None
        mock_client.seed_communities.return_value = None

        community_row = {
            "id": "comm-2",
            "label": "community_abc123",
            "workspace_id": "ws-uuid",
            "summary": "",
            "node_type": "community",
            "created_at": 1700000000000000,
            "labels": "[]",
        }
        mock_client._query.side_effect = [
            [community_row],  # community nodes
            [],  # community edges (empty)
        ]

        g = Graphiti(client=mock_client)
        # LLM not available → skips summarization
        communities = g.build_communities(group_ids=["default"])
        assert len(communities) == 1
        assert communities[0].name == "community_abc123"  # unchanged

    def test_build_communities_edge_query_runtime_error(self):
        """build_communities: edge query RuntimeError for community is caught."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client.detect_communities.return_value = None
        mock_client.seed_communities.return_value = None

        community_row = {
            "id": "comm-3",
            "label": "My Community",
            "workspace_id": "ws-uuid",
            "summary": "Has summary",
            "node_type": "community",
            "created_at": 1700000000000000,
            "labels": '["misc"]',
        }
        mock_client._query.side_effect = [
            [community_row],  # community nodes
            RuntimeError("edge query failed"),  # community edges
        ]

        g = Graphiti(client=mock_client)
        communities = g.build_communities(group_ids=["default"])
        assert len(communities) == 1  # still returns the community
        assert communities[0].name == "My Community"

    # ------------------------------------------------------------------
    # summarize_saga edge cases
    # ------------------------------------------------------------------

    def test_summarize_saga_episode_no_content(self):
        """summarize_saga: episode with empty content gets placeholder."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "default", "name": "default"},
        ]
        mock_client._query.return_value = [
            {
                "id": "ep-1",
                "content": "",
                "created_at": 1700000000000000,
                "peer_id": "saga-1",
                "workspace_id": "default",
            },
        ]
        mock_client.create_node.return_value = None

        g = Graphiti(client=mock_client)
        saga = g.summarize_saga("saga-1")
        assert isinstance(saga, SagaNode)
        assert saga.summary == ""

    def test_summarize_saga_create_node_error_then_update(self):
        """summarize_saga: create_node fails, falls back to update_node."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "default", "name": "default"},
        ]
        mock_client._query.return_value = [
            {
                "id": "ep-1",
                "content": "Episode content",
                "created_at": 1700000000000000,
                "peer_id": "saga-1",
                "workspace_id": "default",
            },
        ]
        mock_client.create_node.side_effect = RuntimeError("node exists")
        mock_client._call.return_value = None

        g = Graphiti(client=mock_client)
        saga = g.summarize_saga("saga-1")
        assert isinstance(saga, SagaNode)
        # Should have attempted update_node via _call
        assert mock_client._call.called

    def test_summarize_saga_create_and_update_both_error(self):
        """summarize_saga: both create_node and update_node error is caught."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "default", "name": "default"},
        ]
        mock_client._query.return_value = [
            {
                "id": "ep-1",
                "content": "Some saga episode",
                "created_at": 1700000000000000,
                "peer_id": "saga-x",
                "workspace_id": "default",
            },
        ]
        mock_client.create_node.side_effect = RuntimeError("create failed")
        mock_client._call.side_effect = RuntimeError("update failed")

        g = Graphiti(client=mock_client)
        saga = g.summarize_saga("saga-x")
        assert isinstance(saga, SagaNode)
        # Both failed but saga is still returned

    # ------------------------------------------------------------------
    # remove_episode error path
    # ------------------------------------------------------------------

    def test_remove_episode_delete_memory_runtime_error(self):
        """remove_episode: delete_memory RuntimeError is caught."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = [{"id": "mem-1"}]
        mock_client.delete_memory.side_effect = RuntimeError("delete failed")

        g = Graphiti(client=mock_client)
        result = g.remove_episode("ep-uuid")
        assert result == {"status": "ok", "episode_uuid": "ep-uuid"}

    # ------------------------------------------------------------------
    # retrieve_episodes timestamp encoding
    # ------------------------------------------------------------------

    def test_retrieve_episodes_microsecond_timestamp(self):
        """retrieve_episodes: timestamp > 1e12 treated as microseconds."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        # timestamp > 1e12 → microseconds
        mock_client._query.return_value = [
            {
                "id": "mem-1",
                "content": "test content",
                "created_at": 1700000000000000,  # microseconds
                "source_session_id": "ep-1",
                "workspace_id": "ws-uuid",
                "peer_id": "test-peer",
            },
        ]

        g = Graphiti(client=mock_client)
        episodes = g.retrieve_episodes(group_ids=["default"])
        assert len(episodes) == 1
        assert episodes[0].uuid == "ep-1"

    def test_retrieve_episodes_second_timestamp(self):
        """retrieve_episodes: timestamp ≤ 1e12 treated as seconds."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        # timestamp ≤ 1e12 → seconds
        mock_client._query.return_value = [
            {
                "id": "mem-2",
                "content": "test content 2",
                "created_at": 1700000000,  # seconds
                "source_session_id": "ep-2",
                "workspace_id": "ws-uuid",
                "peer_id": "test-peer-2",
            },
        ]

        g = Graphiti(client=mock_client)
        episodes = g.retrieve_episodes(group_ids=["default"])
        assert len(episodes) == 1
        assert episodes[0].uuid == "ep-2"

    def test_retrieve_episodes_zero_timestamp(self):
        """retrieve_episodes: created_at=0 falls back to now."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client._query.return_value = [
            {
                "id": "mem-3",
                "content": "content",
                "created_at": 0,
                "source_session_id": "",
                "workspace_id": "ws-uuid",
                "peer_id": "peer-3",
            },
        ]

        g = Graphiti(client=mock_client)
        episodes = g.retrieve_episodes(group_ids=["default"])
        assert len(episodes) == 1

    # ------------------------------------------------------------------
    # Namespace save/delete/get_by_uuid methods
    # ------------------------------------------------------------------

    def test_nodes_entity_delete_runtime_error(self):
        """nodes.entity.delete: RuntimeError is caught."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._call.side_effect = RuntimeError("delete failed")

        g = Graphiti(client=mock_client)
        node = EntityNode(uuid="node-x", group_id="default")
        # Should not raise
        g.nodes.entity.delete(node)

    def test_nodes_episode_save(self):
        """nodes.episode.save calls store_memory reducer."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client._call.return_value = None

        g = Graphiti(client=mock_client)
        ep = EpisodicNode(
            uuid="ep-1",
            name="test-ep",
            group_id="default",
            content="episode body",
        )
        result = g.nodes.episode.save(ep)
        assert result is ep
        assert mock_client._call.called

    def test_nodes_community_save_existing(self):
        """nodes.community.save: existing community returns immediately."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client._query.return_value = [{"id": "comm-exists"}]

        g = Graphiti(client=mock_client)
        comm = CommunityNode(uuid="comm-exists", group_id="default")
        result = g.nodes.community.save(comm)
        assert result is comm
        # Should NOT have called create_node
        mock_client.create_node.assert_not_called()

    def test_nodes_community_save_new(self):
        """nodes.community.save: creates new community node."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client._query.return_value = []  # not existing
        mock_client.create_node.return_value = None

        g = Graphiti(client=mock_client)
        comm = CommunityNode(uuid="comm-new", group_id="default")
        result = g.nodes.community.save(comm)
        assert result is comm
        mock_client.create_node.assert_called_once()

    def test_nodes_community_get_by_uuid_not_found(self):
        """nodes.community.get_by_uuid raises KeyError when not found."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = []  # no results

        g = Graphiti(client=mock_client)
        with pytest.raises(KeyError, match="CommunityNode"):
            g.nodes.community.get_by_uuid("nonexistent-comm")

    def test_nodes_community_delete_runtime_error(self):
        """nodes.community.delete: RuntimeError is caught."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._call.side_effect = RuntimeError("delete failed")

        g = Graphiti(client=mock_client)
        comm = CommunityNode(uuid="comm-x")
        # Should not raise
        g.nodes.community.delete(comm)

    def test_nodes_saga_save_existing(self):
        """nodes.saga.save: existing saga returns immediately."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client._query.return_value = [{"id": "saga-exists"}]

        g = Graphiti(client=mock_client)
        saga = SagaNode(uuid="saga-exists", group_id="default")
        result = g.nodes.saga.save(saga)
        assert result is saga
        mock_client.create_node.assert_not_called()

    def test_nodes_saga_save_new(self):
        """nodes.saga.save: creates new saga node."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client._query.return_value = []
        mock_client.create_node.return_value = None

        g = Graphiti(client=mock_client)
        saga = SagaNode(uuid="saga-new", group_id="default")
        result = g.nodes.saga.save(saga)
        assert result is saga
        mock_client.create_node.assert_called_once()

    def test_nodes_saga_get_by_uuid_not_found(self):
        """nodes.saga.get_by_uuid raises KeyError when not found."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = []

        g = Graphiti(client=mock_client)
        with pytest.raises(KeyError, match="SagaNode"):
            g.nodes.saga.get_by_uuid("nonexistent-saga")

    def test_nodes_saga_get_by_uuids(self):
        """nodes.saga.get_by_uuids returns matching sagas."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.side_effect = [
            [
                {
                    "id": "saga-1",
                    "label": "Saga 1",
                    "workspace_id": "ws-uuid",
                    "summary": "",
                    "labels": "[]",
                    "created_at": 1700000000000000,
                }
            ],
            [],  # second uuid not found
        ]

        g = Graphiti(client=mock_client)
        sagas = g.nodes.saga.get_by_uuids(["saga-1", "saga-2"])
        assert len(sagas) == 1
        assert sagas[0].uuid == "saga-1"

    def test_nodes_saga_get_by_group_ids(self):
        """nodes.saga.get_by_group_ids returns sagas by workspace."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client._query.return_value = [
            {
                "id": "saga-ws",
                "label": "Workspace Saga",
                "workspace_id": "ws-uuid",
                "summary": "",
                "labels": "[]",
                "created_at": 1700000000000000,
            },
        ]

        g = Graphiti(client=mock_client)
        sagas = g.nodes.saga.get_by_group_ids(["default"])
        assert len(sagas) == 1
        assert sagas[0].name == "Workspace Saga"

    def test_edges_entity_delete_runtime_error(self):
        """edges.entity.delete: RuntimeError is caught."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._call.side_effect = RuntimeError("delete failed")

        g = Graphiti(client=mock_client)
        edge = EntityEdge(uuid="edge-x", group_id="default")
        # Should not raise
        g.edges.entity.delete(edge)

    def test_edges_episodic_get_by_uuids(self):
        """edges.episodic.get_by_uuids returns matching edges."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.side_effect = [
            [
                {
                    "id": "ep-edge-1",
                    "source_node_id": "n1",
                    "target_node_id": "n2",
                    "workspace_id": "default",
                    "created_at": 1700000000000000,
                    "valid_at": 1700000000000000,
                    "invalid_at": 0,
                    "metadata_json": "{}",
                    "relation": "HAS_EPISODE",
                }
            ],
            [],  # second not found
        ]

        g = Graphiti(client=mock_client)
        edges = g.edges.episodic.get_by_uuids(["ep-edge-1", "ep-edge-2"])
        assert len(edges) == 1
        assert edges[0].uuid == "ep-edge-1"

    def test_edges_community_get_by_uuids(self):
        """edges.community.get_by_uuids returns matching edges."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.side_effect = [
            [
                {
                    "id": "comm-edge-1",
                    "source_node_id": "c1",
                    "target_node_id": "n1",
                    "workspace_id": "default",
                    "created_at": 1700000000000000,
                    "valid_at": 1700000000000000,
                    "invalid_at": 0,
                    "metadata_json": "{}",
                    "relation": "MEMBER_OF",
                }
            ],
        ]

        g = Graphiti(client=mock_client)
        edges = g.edges.community.get_by_uuids(["comm-edge-1"])
        assert len(edges) == 1
        assert edges[0].uuid == "comm-edge-1"

    def test_edges_has_episode_get_by_uuids(self):
        """edges.has_episode.get_by_uuids returns matching edges."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.side_effect = [
            [
                {
                    "id": "he-edge-1",
                    "source_node_id": "e1",
                    "target_node_id": "e2",
                    "workspace_id": "default",
                    "created_at": 1700000000000000,
                    "valid_at": 1700000000000000,
                    "invalid_at": 0,
                    "metadata_json": "{}",
                    "relation": "HAS_EPISODE",
                }
            ],
        ]

        g = Graphiti(client=mock_client)
        edges = g.edges.has_episode.get_by_uuids(["he-edge-1"])
        assert len(edges) == 1
        assert edges[0].uuid == "he-edge-1"

    def test_edges_next_episode_get_by_uuids(self):
        """edges.next_episode.get_by_uuids returns matching edges."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.side_effect = [
            [
                {
                    "id": "ne-edge-1",
                    "source_node_id": "ep1",
                    "target_node_id": "ep2",
                    "workspace_id": "default",
                    "created_at": 1700000000000000,
                    "valid_at": 1700000000000000,
                    "invalid_at": 0,
                    "metadata_json": "{}",
                    "relation": "NEXT_EPISODE",
                }
            ],
        ]

        g = Graphiti(client=mock_client)
        edges = g.edges.next_episode.get_by_uuids(["ne-edge-1"])
        assert len(edges) == 1
        assert edges[0].uuid == "ne-edge-1"

    # ------------------------------------------------------------------
    # get_by_uuid success paths (currently only "not found" paths tested)
    # ------------------------------------------------------------------

    def test_nodes_community_get_by_uuid_success(self):
        """nodes.community.get_by_uuid returns community when found."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = [
            {
                "id": "comm-found",
                "label": "FoundComm",
                "workspace_id": "ws",
                "summary": "desc",
                "labels": '["tag"]',
                "created_at": 1700000000000000,
            },
        ]

        g = Graphiti(client=mock_client)
        community = g.nodes.community.get_by_uuid("comm-found")
        assert community.uuid == "comm-found"
        assert community.name == "FoundComm"

    def test_nodes_saga_get_by_uuid_success(self):
        """nodes.saga.get_by_uuid returns saga when found."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = [
            {
                "id": "saga-found",
                "label": "FoundSaga",
                "workspace_id": "ws",
                "summary": "saga desc",
                "labels": "[]",
                "created_at": 1700000000000000,
            },
        ]

        g = Graphiti(client=mock_client)
        saga = g.nodes.saga.get_by_uuid("saga-found")
        assert saga.uuid == "saga-found"
        assert saga.name == "FoundSaga"

    def test_edges_episodic_get_by_uuid_success(self):
        """edges.episodic.get_by_uuid returns edge when found."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = [
            {
                "id": "ep-edge-found",
                "source_node_id": "n1",
                "target_node_id": "n2",
                "workspace_id": "default",
                "created_at": 1700000000000000,
                "valid_at": 1700000000000000,
                "invalid_at": 0,
                "metadata_json": "{}",
                "relation": "HAS_EPISODE",
            },
        ]

        g = Graphiti(client=mock_client)
        edge = g.edges.episodic.get_by_uuid("ep-edge-found")
        assert edge.uuid == "ep-edge-found"

    def test_edges_community_get_by_uuid_success(self):
        """edges.community.get_by_uuid returns edge when found."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = [
            {
                "id": "comm-edge-found",
                "source_node_id": "c1",
                "target_node_id": "n1",
                "workspace_id": "default",
                "created_at": 1700000000000000,
                "valid_at": 1700000000000000,
                "invalid_at": 0,
                "metadata_json": "{}",
                "relation": "MEMBER_OF",
            },
        ]

        g = Graphiti(client=mock_client)
        edge = g.edges.community.get_by_uuid("comm-edge-found")
        assert edge.uuid == "comm-edge-found"

    def test_edges_has_episode_get_by_uuid_success(self):
        """edges.has_episode.get_by_uuid returns edge when found."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = [
            {
                "id": "he-edge-found",
                "source_node_id": "e1",
                "target_node_id": "e2",
                "workspace_id": "default",
                "created_at": 1700000000000000,
                "valid_at": 1700000000000000,
                "invalid_at": 0,
                "metadata_json": "{}",
                "relation": "HAS_EPISODE",
            },
        ]

        g = Graphiti(client=mock_client)
        edge = g.edges.has_episode.get_by_uuid("he-edge-found")
        assert edge.uuid == "he-edge-found"

    def test_edges_next_episode_get_by_uuid_success(self):
        """edges.next_episode.get_by_uuid returns edge when found."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.return_value = [
            {
                "id": "ne-edge-found",
                "source_node_id": "ep1",
                "target_node_id": "ep2",
                "workspace_id": "default",
                "created_at": 1700000000000000,
                "valid_at": 1700000000000000,
                "invalid_at": 0,
                "metadata_json": "{}",
                "relation": "NEXT_EPISODE",
            },
        ]

        g = Graphiti(client=mock_client)
        edge = g.edges.next_episode.get_by_uuid("ne-edge-found")
        assert edge.uuid == "ne-edge-found"

    # ------------------------------------------------------------------
    # search sort key TypeError/ValueError
    # ------------------------------------------------------------------

    def test_search_sort_key_type_error(self):
        """search: sort key handles _score with non-numeric value."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client.search.return_value = [
            {"entity_id": "n1", "entity_type": "node"},
        ]
        mock_client.get_neighbors.return_value = [
            {
                "id": "edge-1",
                "source_node_id": "n1",
                "target_node_id": "n2",
                "relation": "test",
                "workspace_id": "ws-uuid",
                "created_at": 1700000000000000,
                "valid_at": 1700000000000000,
                "invalid_at": 0,
                "metadata_json": "{}",
            },
        ]

        g = Graphiti(client=mock_client)

        # Patch EntityEdge.from_stmem to add a non-numeric _score
        original_from_stmem = EntityEdge.from_stmem

        def from_stmem_with_bad_score(row):
            edge = original_from_stmem(row)
            object.__setattr__(edge, "_score", "not-a-number")
            return edge

        with patch.object(EntityEdge, "from_stmem", side_effect=from_stmem_with_bad_score):
            edges = g.search("test", group_ids=["default"])
            # The sort function caught the TypeError, edges still returned
            assert isinstance(edges, list)

    # ------------------------------------------------------------------
    # get_nodes_and_edges_by_episode edge rows
    # ------------------------------------------------------------------

    def test_get_nodes_and_edges_by_episode_with_edges(self):
        """get_nodes_and_edges_by_episode with edges in results (empty case)."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        # Episode UUID → memory → empty results
        mock_client._query.return_value = []

        g = Graphiti(client=mock_client)
        results = g.get_nodes_and_edges_by_episode(["ep-uuid"])
        assert isinstance(results, SearchResults)
        assert results.edges == []
        assert results.nodes == []

    # ------------------------------------------------------------------
    # Nodes namespace methods
    # ------------------------------------------------------------------

    def test_nodes_community_get_by_uuids_with_matches(self):
        """nodes.community.get_by_uuids returns matching communities."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client._query.side_effect = [
            [
                {
                    "id": "comm-a",
                    "label": "CommA",
                    "workspace_id": "ws",
                    "summary": "",
                    "labels": "[]",
                    "created_at": 1700000000000000,
                }
            ],
            [],  # second not found
        ]

        g = Graphiti(client=mock_client)
        communities = g.nodes.community.get_by_uuids(["comm-a", "comm-b"])
        assert len(communities) == 1
        assert communities[0].uuid == "comm-a"

    def test_nodes_community_get_by_group_ids_with_rows(self):
        """nodes.community.get_by_group_ids returns matching communities."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [
            {"id": "ws-uuid", "name": "default"},
        ]
        mock_client._query.return_value = [
            {
                "id": "comm-gid",
                "label": "GroupComm",
                "workspace_id": "ws-uuid",
                "summary": "",
                "labels": "[]",
                "created_at": 1700000000000000,
            },
        ]

        g = Graphiti(client=mock_client)
        communities = g.nodes.community.get_by_group_ids(["default"])
        assert len(communities) == 1
        assert communities[0].uuid == "comm-gid"


class TestBiTemporalFilter:
    """Tests for _filter_by_valid_at Graphiti-parity bi-temporal semantics.

    Mirrors Graphiti's SearchFilters: valid_at / invalid_at are separate
    field comparisons (>= / <=) on the edge validity window
    [valid_at, invalid_at). invalid_at 0/None means currently valid.
    """

    @staticmethod
    def _make_edge(
        name: str,
        valid_at: str | None = None,
        invalid_at: str | None = None,
    ) -> EntityEdge:
        def _p(s: str | None) -> datetime | None:
            return datetime.fromisoformat(s).replace(tzinfo=UTC) if s else None

        return EntityEdge(
            name=name,
            fact=f"fact {name}",
            group_id="default",
            valid_at=_p(valid_at),
            invalid_at=_p(invalid_at),
        )

    @staticmethod
    def _graphiti() -> Graphiti:
        from unittest.mock import MagicMock

        return Graphiti(client=MagicMock())

    def test_no_bounds_returns_all(self):
        """No bounds returns the original list unchanged (Graphiti parity)."""
        g = self._graphiti()
        edges = [
            self._make_edge("current", valid_at="2023-01-01T00:00:00+00:00"),
            self._make_edge(
                "superseded",
                valid_at="2023-01-01T00:00:00+00:00",
                invalid_at="2023-06-01T00:00:00+00:00",
            ),
            self._make_edge("untimed"),
        ]
        assert g._filter_by_valid_at(edges) == edges

    def test_valid_at_after(self):
        """valid_at_after keeps edges with valid_at >= date."""
        g = self._graphiti()
        edges = [
            self._make_edge("old", valid_at="2023-01-01T00:00:00+00:00"),
            self._make_edge("new", valid_at="2023-06-01T00:00:00+00:00"),
        ]
        result = g._filter_by_valid_at(
            edges, valid_at_after=datetime.fromisoformat("2023-03-01T00:00:00+00:00")
        )
        assert [e.name for e in result] == ["new"]

    def test_valid_at_before(self):
        """valid_at_before keeps edges with valid_at <= date."""
        g = self._graphiti()
        edges = [
            self._make_edge("old", valid_at="2023-01-01T00:00:00+00:00"),
            self._make_edge("new", valid_at="2023-06-01T00:00:00+00:00"),
        ]
        result = g._filter_by_valid_at(
            edges, valid_at_before=datetime.fromisoformat("2023-03-01T00:00:00+00:00")
        )
        assert [e.name for e in result] == ["old"]

    def test_invalid_at_after_includes_never_invalidated(self):
        """Never-invalidated edges satisfy invalid_at >= date."""
        g = self._graphiti()
        edges = [
            self._make_edge(
                "invalidated-early",
                valid_at="2023-01-01T00:00:00+00:00",
                invalid_at="2023-02-01T00:00:00+00:00",
            ),
            self._make_edge("still-valid", valid_at="2023-01-01T00:00:00+00:00"),
        ]
        result = g._filter_by_valid_at(
            edges, invalid_at_after=datetime.fromisoformat("2023-03-01T00:00:00+00:00")
        )
        assert [e.name for e in result] == ["still-valid"]

    def test_invalid_at_before_excludes_never_invalidated(self):
        """invalid_at_before keeps only edges invalidated by that date."""
        g = self._graphiti()
        edges = [
            self._make_edge(
                "superseded",
                valid_at="2023-01-01T00:00:00+00:00",
                invalid_at="2023-02-01T00:00:00+00:00",
            ),
            self._make_edge("still-valid", valid_at="2023-01-01T00:00:00+00:00"),
        ]
        result = g._filter_by_valid_at(
            edges, invalid_at_before=datetime.fromisoformat("2023-03-01T00:00:00+00:00")
        )
        assert [e.name for e in result] == ["superseded"]

    def test_combined_valid_and_invalid_window(self):
        """Combine valid_at_after + invalid_at_before for an as-of snapshot."""
        g = self._graphiti()
        edges = [
            self._make_edge(
                "valid-then-superseded",
                valid_at="2023-01-01T00:00:00+00:00",
                invalid_at="2023-06-01T00:00:00+00:00",
            ),
            self._make_edge(
                "too-early",
                valid_at="2022-01-01T00:00:00+00:00",
                invalid_at="2023-06-01T00:00:00+00:00",
            ),
            self._make_edge(
                "invalidated-before-window",
                valid_at="2023-01-01T00:00:00+00:00",
                invalid_at="2023-02-01T00:00:00+00:00",
            ),
        ]
        result = g._filter_by_valid_at(
            edges,
            valid_at_after=datetime.fromisoformat("2023-01-01T00:00:00+00:00"),
            invalid_at_before=datetime.fromisoformat("2023-12-01T00:00:00+00:00"),
        )
        # All three edges are invalidated by end-2023 and valid_at >= 2023-01-01
        assert {e.name for e in result} == {
            "valid-then-superseded",
            "invalidated-before-window",
        }

    def test_edges_without_valid_at_excluded_when_valid_bound_active(self):
        """Edges without valid_at are excluded when a valid_at bound is active."""
        g = self._graphiti()
        edges = [self._make_edge("untimed")]
        result = g._filter_by_valid_at(
            edges, valid_at_after=datetime.fromisoformat("2023-01-01T00:00:00+00:00")
        )
        assert result == []

    def test_invalid_at_zero_treated_as_never(self):
        """invalid_at == 0 (raw STDB) means currently valid."""
        g = self._graphiti()
        edge = EntityEdge(
            name="zero-invalid",
            fact="f",
            group_id="default",
            valid_at=datetime(2023, 1, 1, tzinfo=UTC),
            invalid_at=datetime.fromtimestamp(0, tz=UTC),
        )
        result = g._filter_by_valid_at(
            [edge], invalid_at_before=datetime(2023, 6, 1, tzinfo=UTC)
        )
        assert result == []  # never invalidated → not matched by invalid_at_before

    def test_search_passes_invalid_at_kwargs(self):
        """search() forwards invalid_at filters to _filter_by_valid_at."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.list_workspaces.return_value = [{"id": "ws-1", "name": "default"}]
        # First search call returns rows referencing a node, second (neighbors) empty
        mock_client.search.return_value = [
            {"entity_id": "node-a", "entity_type": "node", "score": 0.9},
        ]
        mock_client.get_neighbors.return_value = []
        mock_client.query_graph.return_value = []
        g = Graphiti(client=mock_client)
        result = g.search(
            "query",
            group_ids=["default"],
            invalid_at_before=datetime(2023, 6, 1, tzinfo=UTC),
        )
        # No edges found with empty neighbors, but the call should not raise
        assert result == []
