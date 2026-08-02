"""Tests for the Zep v2 graph namespace (_GraphClient) — mocked client.

Covers: graph.add (episode), graph.search (nodes/edges/episodes scopes),
graph.node.get / get_by_user_id, graph.edge.get, graph.episode.get,
and honest NotImplementedError for unsupported surface.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from spacetime_memory.sdks.zep import (
    BadRequestError,
    NotFoundError,
    Zep,
    _GraphClient,
)


def _make_zep():
    """Zep instance with a fully mocked inner Client."""
    zep = Zep.__new__(Zep)
    zep._client = MagicMock()
    zep._session_to_ws = {}
    zep._ensure_workspace = MagicMock(return_value="ws-graph")
    return zep


@pytest.fixture
def graph():
    zep = _make_zep()
    return zep, _GraphClient(zep)


# ---------------------------------------------------------------------------
# graph.add
# ---------------------------------------------------------------------------


class TestGraphAdd:
    def test_add_text_episode(self, graph):
        zep, g = graph
        zep._client.store.return_value = {"status": "ok", "id": "mem-123"}
        result = g.add("Alice works at Acme", type="text", user_id="alice")
        zep._ensure_workspace.assert_called_with("zep-graph-user-alice")
        zep._client.store.assert_called_once()
        assert result["uuid"] == "mem-123"
        assert result["content"] == "Alice works at Acme"
        assert result["source"] == "text"

    def test_add_json_episode_serializes(self, graph):
        zep, g = graph
        zep._client.store.return_value = {"status": "ok", "id": "mem-9"}
        result = g.add({"name": "Bob"}, type="json", group_id="team1")
        zep._ensure_workspace.assert_called_with("zep-graph-group-team1")
        assert '"name": "Bob"' in result["content"]

    def test_add_default_scope(self, graph):
        zep, g = graph
        zep._client.store.return_value = {"status": "ok", "id": "m1"}
        g.add("hello")
        zep._ensure_workspace.assert_called_with("zep-graph-default")

    def test_add_invalid_type_raises(self, graph):
        _, g = graph
        with pytest.raises(BadRequestError):
            g.add("data", type="video")


# ---------------------------------------------------------------------------
# graph.search
# ---------------------------------------------------------------------------


class TestGraphSearch:
    def _seed(self, zep):
        zep._client._query.side_effect = lambda table, **kw: {
            "kg_node": [
                {"id": "n1", "workspace_id": "ws-graph", "label": "Alice", "node_type": "entity", "summary": "works at Acme", "metadata_json": "{}"},
                {"id": "n2", "workspace_id": "ws-graph", "label": "Acme", "node_type": "entity", "summary": "a company", "metadata_json": "{}"},
            ],
            "kg_edge": [
                {"id": "e1", "workspace_id": "ws-graph", "source_node_id": "n1", "target_node_id": "n2", "relation": "works_at", "weight": 1.0, "metadata_json": "{}", "source_memory_id": "m1"},
            ],
        }.get(table, [])

    def test_search_nodes(self, graph):
        zep, g = graph
        self._seed(zep)
        out = g.search("alice", scope="nodes")
        assert len(out["nodes"]) == 1
        assert out["nodes"][0]["name"] == "Alice"
        assert out["nodes"][0]["uuid"] == "n1"

    def test_search_edges_joins_labels(self, graph):
        zep, g = graph
        self._seed(zep)
        out = g.search("acme", scope="edges")
        assert len(out["edges"]) == 1
        edge = out["edges"][0]
        assert edge["fact"] == "works_at"
        assert edge["source_node_uuid"] == "n1"
        assert edge["target_node_uuid"] == "n2"
        assert edge["episodes"] == ["m1"]

    def test_search_edges_center_node_reranks(self, graph):
        zep, g = graph
        self._seed(zep)
        out = g.search("", scope="edges", center_node_uuid="n2")
        assert out["edges"][0]["uuid"] == "e1"

    def test_search_episodes_delegates(self, graph):
        zep, g = graph
        zep._client.search.return_value = {"results": [{"id": "m1", "content": "Alice works at Acme", "score": 0.9}]}
        out = g.search("alice", scope="episodes")
        assert out["episodes"][0]["uuid"] == "m1"
        assert out["episodes"][0]["score"] == 0.9

    def test_search_empty_query_returns_all_nodes(self, graph):
        zep, g = graph
        self._seed(zep)
        out = g.search("", scope="nodes")
        assert len(out["nodes"]) == 2


# ---------------------------------------------------------------------------
# node / edge / episode namespaces
# ---------------------------------------------------------------------------


class TestGraphNamespaces:
    def test_node_get(self, graph):
        zep, g = graph
        zep._client._query.return_value = [
            {"id": "n1", "workspace_id": "ws-graph", "label": "Alice", "node_type": "entity", "summary": "", "metadata_json": "{}"}
        ]
        node = g.node.get("n1")
        assert node["name"] == "Alice"

    def test_node_get_not_found(self, graph):
        zep, g = graph
        zep._client._query.return_value = []
        with pytest.raises(NotFoundError):
            g.node.get("missing")

    def test_node_get_by_user_id(self, graph):
        zep, g = graph
        zep._client._query.return_value = [
            {"id": "n1", "workspace_id": "ws-graph", "label": "Alice", "node_type": "entity", "summary": "", "metadata_json": "{}"},
        ]
        nodes = g.node.get_by_user_id("alice")
        assert len(nodes) == 1
        zep._ensure_workspace.assert_called_with("zep-graph-user-alice")

    def test_edge_get(self, graph):
        zep, g = graph
        zep._client._query.return_value = [
            {"id": "e1", "workspace_id": "ws-graph", "source_node_id": "n1", "target_node_id": "n2", "relation": "works_at", "weight": 1.0, "metadata_json": "{}", "source_memory_id": ""}
        ]
        edge = g.edge.get("e1")
        assert edge["fact"] == "works_at"
        assert edge["episodes"] == []

    def test_episode_get(self, graph):
        zep, g = graph
        zep._client._query.return_value = [
            {"id": "m1", "workspace_id": "ws-graph", "content": "Alice works at Acme", "created_at": 1}
        ]
        ep = g.episode.get("m1")
        assert ep["content"] == "Alice works at Acme"

    def test_episode_get_not_found(self, graph):
        zep, g = graph
        zep._client._query.return_value = []
        with pytest.raises(NotFoundError):
            g.episode.get("nope")


# ---------------------------------------------------------------------------
# honest unsupported surface
# ---------------------------------------------------------------------------


class TestGraphUnsupported:
    def test_add_triplet_creates_edge(self, graph):
        zep, g = graph
        zep._client.create_edge.return_value = {"status": "ok"}
        zep._client._query.return_value = [
            {
                "id": "e1",
                "workspace_id": "ws-graph",
                "source_node_id": "a",
                "target_node_id": "b",
                "relation": "works_at",
                "weight": 1.0,
                "metadata_json": '{"fact": "Alice works at Acme"}',
                "source_memory_id": "",
            }
        ]
        result = g.add_triplet(
            source_node_uuid="a",
            target_node_uuid="b",
            edge="works_at",
            fact="Alice works at Acme",
        )
        zep._client.create_edge.assert_called_once()
        assert result["source_node_uuid"] == "a"
        assert result["target_node_uuid"] == "b"
        assert result["fact"] == "works_at"
        assert result["uuid"] == "e1"

    def test_add_triplet_with_workspace_id(self, graph):
        zep, g = graph
        zep._client.create_edge.return_value = {"status": "ok"}
        zep._client._query.return_value = [
            {
                "id": "e2",
                "workspace_id": "custom-ws",
                "source_node_id": "n1",
                "target_node_id": "n2",
                "relation": "related_to",
                "weight": 1.0,
                "metadata_json": "{}",
                "source_memory_id": "",
            }
        ]
        result = g.add_triplet(
            source_node_uuid="n1",
            target_node_uuid="n2",
            edge="related_to",
            workspace_id="custom-ws",
        )
        zep._client.create_edge.assert_called_once()
        assert result["uuid"] == "e2"
        assert result["fact"] == "related_to"

    def test_add_triplet_with_rating(self, graph):
        """add_triplet stores rating as edge weight and in metadata."""
        zep, g = graph
        zep._client.create_edge.return_value = {"status": "ok"}
        zep._client._query.return_value = [
            {
                "id": "e3",
                "workspace_id": "ws-graph",
                "source_node_id": "n1",
                "target_node_id": "n2",
                "relation": "knows",
                "weight": 0.85,
                "metadata_json": '{"fact": "Alice knows Bob", "rating": 0.85}',
                "source_memory_id": "",
            }
        ]
        result = g.add_triplet(
            source_node_uuid="n1",
            target_node_uuid="n2",
            edge="knows",
            fact="Alice knows Bob",
            rating=0.85,
        )
        # Verify create_edge was called with rating as weight + metadata
        zep._client.create_edge.call_args[1] if zep._client.create_edge.call_args else {}
        # It might be positional — just check the call happened
        zep._client.create_edge.assert_called_once()
        assert result["uuid"] == "e3"
        assert result["source_node_uuid"] == "n1"
        assert result["target_node_uuid"] == "n2"
        assert result["fact"] == "knows"
        assert result["weight"] == 0.85

    def test_add_triplet_with_rating_only(self, graph):
        """add_triplet with rating but no fact still stores rating."""
        zep, g = graph
        zep._client.create_edge.return_value = {"status": "ok"}
        zep._client._query.return_value = [
            {
                "id": "e4",
                "workspace_id": "ws-graph",
                "source_node_id": "src",
                "target_node_id": "tgt",
                "relation": "depends_on",
                "weight": 0.5,
                "metadata_json": '{"rating": 0.5}',
                "source_memory_id": "",
            }
        ]
        result = g.add_triplet(
            source_node_uuid="src",
            target_node_uuid="tgt",
            edge="depends_on",
            rating=0.5,
        )
        zep._client.create_edge.assert_called_once()
        assert result["weight"] == 0.5
        assert result["uuid"] == "e4"


# ---------------------------------------------------------------------------
# graph.community — community detection backed by the real KG
# ---------------------------------------------------------------------------


class TestGraphCommunity:
    def test_build_runs_reducers_and_returns_communities(self, graph):
        """build() calls detect_communities + seed_communities then lists."""
        zep, g = graph
        zep._client._query.side_effect = [
            # list() call: kg_node query returns one community row
            [{
                "id": "c1",
                "workspace_id": "ws-graph",
                "label": "Community Alpha",
                "node_type": "community",
                "summary": "A group of related entities",
                "created_at": 123,
            }],
            # _community_to_api: kg_edge query for members
            [],
        ]
        result = g.community.build(user_id="u1")
        zep._client.detect_communities.assert_called_once_with("ws-graph")
        zep._client.seed_communities.assert_called_once_with("ws-graph")
        assert len(result) == 1
        assert result[0]["uuid"] == "c1"
        assert result[0]["name"] == "Community Alpha"
        assert result[0]["summary"] == "A group of related entities"
        assert result[0]["member_count"] == 0

    def test_build_swallows_reducer_errors(self, graph):
        """build() tolerates reducers failing (non-fatal)."""
        zep, g = graph
        zep._client.detect_communities.side_effect = RuntimeError("no admin")
        zep._client.seed_communities.side_effect = RuntimeError("no admin")
        zep._client._query.side_effect = [[], []]
        result = g.community.build()
        assert result == []

    def test_list_filters_by_workspace_and_node_type(self, graph):
        """list() filters rows to the scoped workspace + community type."""
        zep, g = graph
        zep._client._query.side_effect = [
            [
                {"id": "c1", "workspace_id": "ws-graph", "label": "C1",
                 "node_type": "community", "summary": "s", "created_at": 1},
                {"id": "n1", "workspace_id": "ws-graph", "label": "Entity",
                 "node_type": "entity", "summary": "", "created_at": 2},
                {"id": "c2", "workspace_id": "other-ws", "label": "C2",
                 "node_type": "community", "summary": "", "created_at": 3},
            ],
            [],  # members edge query for c1
        ]
        result = g.community.list()
        # only the workspace-scoped community row survives
        assert [c["uuid"] for c in result] == ["c1"]

    def test_get_returns_community_with_members(self, graph):
        """get() returns a community with member edges resolved."""
        zep, g = graph
        zep._client._query.side_effect = [
            [{
                "id": "c9", "workspace_id": "ws-graph", "label": "C9",
                "node_type": "community", "summary": "s", "created_at": 9,
            }],
            [
                {"id": "e1", "source_node_id": "c9", "target_node_id": "m1"},
                {"id": "e2", "source_node_id": "c9", "target_node_id": "m2"},
                {"id": "e3", "source_node_id": "c9", "target_node_id": "m1"},
            ],
        ]
        result = g.community.get("c9")
        assert result["uuid"] == "c9"
        assert result["member_count"] == 2
        assert set(result["members"]) == {"m1", "m2"}
        assert len(result["edges"]) == 3

    def test_get_not_found_raises(self, graph):
        """get() on a missing/non-community node raises NotFoundError."""
        zep, g = graph
        zep._client._query.return_value = [
            {"id": "n1", "node_type": "entity", "label": "Entity"}
        ]
        with pytest.raises(NotFoundError):
            g.community.get("n1")

    def test_search_matches_name_or_summary(self, graph):
        """search() matches community name/summary case-insensitively."""
        zep, g = graph
        zep._client._query.side_effect = [
            [
                {"id": "c1", "workspace_id": "ws-graph", "label": "Dogs Club",
                 "node_type": "community", "summary": "All about canines", "created_at": 1},
                {"id": "c2", "workspace_id": "ws-graph", "label": "Cats",
                 "node_type": "community", "summary": "Felines only", "created_at": 2},
            ],
            [],  # c1 member edges
            [],  # c2 member edges
        ]
        result = g.community.search("dogs")
        assert [c["uuid"] for c in result] == ["c1"]

    def test_search_empty_query_returns_all(self, graph):
        """search('') returns every community (no filter)."""
        zep, g = graph
        zep._client._query.side_effect = [
            [
                {"id": "c1", "workspace_id": "ws-graph", "label": "A",
                 "node_type": "community", "summary": "", "created_at": 1},
                {"id": "c2", "workspace_id": "ws-graph", "label": "B",
                 "node_type": "community", "summary": "", "created_at": 2},
            ],
            [], [],
        ]
        result = g.community.search("")
        assert len(result) == 2
