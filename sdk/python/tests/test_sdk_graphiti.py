"""Unit tests for the Graphiti adapter — data classes, helpers, constructors, and mock-backed methods.

No live SpacetimeDB required.  All Client calls are mocked via MagicMock.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from spacetime_memory.sdks.graphiti import (
    AddBulkEpisodeResults,
    AddEpisodeResults,
    AddTripletResults,
    CommunityEdge,
    CommunityNode,
    EdgeNamespace,
    EntityEdge,
    EntityNode,
    EpisodeNodeNamespace,
    EpisodicEdge,
    EpisodicNode,
    Graphiti,
    HasEpisodeEdge,
    NextEpisodeEdge,
    NodeNamespace,
    RawEpisode,
    SagaNode,
    SearchResults,
    _esc,
)


# =====================================================================
# Helper: _esc
# =====================================================================
class TestEsc:
    def test_plain_string(self):
        assert _esc("hello") == "hello"

    def test_single_quote_escaped(self):
        assert _esc("it's") == "it''s"

    def test_multiple_quotes(self):
        assert _esc("'a' 'b'") == "''a'' ''b''"

    def test_empty_string(self):
        assert _esc("") == ""

    def test_unicode(self):
        assert _esc("caf\xe9") == "caf\xe9"

    def test_backslash_not_escaped(self):
        assert _esc("it\\'s") == "it\\''s"

    def test_newline_not_affected(self):
        assert _esc("line1\nline2") == "line1\nline2"

    def test_tab_not_affected(self):
        assert _esc("col1\tcol2") == "col1\tcol2"


# =====================================================================
# EntityNode
# =====================================================================
class TestEntityNodeInit:
    def test_default_fields(self):
        node = EntityNode()
        assert node.name == ""
        assert node.group_id == "default"
        assert len(node.uuid) == 32

    def test_custom_fields(self):
        node = EntityNode(
            name="Alice", group_id="ws1", summary="A test user",
            labels=["person"], attributes={"role": "admin"},
        )
        assert node.name == "Alice"
        assert node.group_id == "ws1"
        assert node.summary == "A test user"
        assert node.labels == ["person"]
        assert node.attributes == {"role": "admin"}

    def test_uuid_unique(self):
        n1, n2 = EntityNode(), EntityNode()
        assert n1.uuid != n2.uuid


class TestEntityNodeFromStmem:
    def test_minimal_row(self):
        node = EntityNode.from_stmem({"id": "abc", "label": "Bob", "workspace_id": "ws1"})
        assert node.uuid == "abc" and node.name == "Bob" and node.group_id == "ws1"

    def test_full_row(self):
        row = {
            "id": "abc", "label": "Bob", "summary": "user",
            "workspace_id": "ws1", "labels": '["person"]',
            "metadata_json": '{"role":"admin"}',
            "created_at": 1_700_000_000_000_000,
        }
        node = EntityNode.from_stmem(row)
        assert node.labels == ["person"]
        assert node.attributes == {"role": "admin"}

    def test_labels_empty_str(self):
        node = EntityNode.from_stmem({"id": "x", "labels": "", "metadata_json": ""})
        assert node.labels == [] and node.attributes == {}

    def test_labels_none(self):
        node = EntityNode.from_stmem({"id": "x", "labels": None, "metadata_json": None})
        assert node.labels == [] and node.attributes == {}

    def test_corrupt_metadata(self):
        node = EntityNode.from_stmem({"id": "x", "metadata_json": "{bad"})
        assert node.attributes == {}

    def test_labels_already_list(self):
        node = EntityNode.from_stmem({"id": "x", "labels": ["a"]})
        # Labels when passed as list (non-string) are treated as empty by from_stmem
        assert node.labels == []

    def test_created_at_zero(self):
        node = EntityNode.from_stmem({"id": "x", "created_at": 0})
        assert isinstance(node.created_at, datetime)


class TestEntityNodeModelDump:
    def test_round_trip(self):
        n = EntityNode(name="Bob", labels=["user"])
        d = n.model_dump()
        assert EntityNode.model_validate(d).name == "Bob"


# =====================================================================
# EntityEdge
# =====================================================================
class TestEntityEdgeInit:
    def test_defaults(self):
        e = EntityEdge()
        assert e.version == 1 and e.valid_at is None and e.invalid_at is None

    def test_custom(self):
        now = datetime.now(UTC)
        e = EntityEdge(
            name="likes", source_node_uuid="s1", target_node_uuid="t1",
            version=2, edge_group_id="eg1", valid_at=now,
        )
        assert e.name == "likes" and e.version == 2 and e.valid_at == now


class TestEntityEdgeFromStmem:
    def test_minimal(self):
        e = EntityEdge.from_stmem({"id": "e1", "relation": "likes"})
        assert e.name == "likes" and e.fact == "likes"

    def test_full(self):
        row = {
            "id": "e1", "relation": "likes", "fact": "likes pizza",
            "source_node_id": "s1", "target_node_id": "t1",
            "workspace_id": "ws1", "metadata_json": '{"c":0.9}',
            "version": 2, "edge_group_id": "eg1",
            "created_at": 1_700_000_000_000_000,
        }
        e = EntityEdge.from_stmem(row)
        assert e.fact == "likes pizza" and e.version == 2
        assert e.edge_group_id == "eg1"

    def test_valid_at_none(self):
        e = EntityEdge.from_stmem({"id": "e1", "relation": "r", "valid_at": 0, "invalid_at": 0})
        assert e.valid_at is None and e.invalid_at is None


class TestEntityEdgeModelDump:
    def test_round_trip(self):
        e = EntityEdge(name="likes", version=1)
        assert EntityEdge.model_validate(e.model_dump()).name == "likes"


# =====================================================================
# Other dataclass tests
# =====================================================================
class TestEpisodicNodeModelDump:
    def test_round_trip(self):
        ep = EpisodicNode(name="t1", content="hello")
        assert EpisodicNode.model_validate(ep.model_dump()).name == "t1"


class TestCommunityNodeModelDump:
    def test_round_trip(self):
        cn = CommunityNode(uuid="c1", name="eng", member_uuids=["a", "b"])
        assert CommunityNode.model_validate(cn.model_dump()).name == "eng"


class TestSagaNodeModelDump:
    def test_round_trip(self):
        s = SagaNode(uuid="s1", name="ms", summary="t")
        assert SagaNode.model_validate(s.model_dump()).name == "ms"


class TestSearchResults:
    def test_default(self):
        sr = SearchResults()
        assert sr.edges == [] and sr.nodes == []


class TestAddTripletResults:
    def test_default(self):
        assert AddTripletResults().nodes == []


class TestAddEpisodeResults:
    def test_default(self):
        assert AddEpisodeResults().episode is None


class TestAddBulkEpisodeResults:
    def test_default(self):
        assert AddBulkEpisodeResults().episodes == []


class TestRawEpisode:
    def test_fields(self):
        re = RawEpisode(name="e1", content="test")
        assert re.name == "e1" and re.content == "test"


class TestCommunityEdge:
    def test_default(self):
        assert CommunityEdge().source_node_uuid == ""


class TestEpisodicEdge:
    def test_default(self):
        assert len(EpisodicEdge().uuid) == 32


class TestHasEpisodeEdge:
    def test_default(self):
        assert len(HasEpisodeEdge().uuid) == 32


class TestNextEpisodeEdge:
    def test_default(self):
        assert len(NextEpisodeEdge().uuid) == 32


# =====================================================================
# Graphiti class
# =====================================================================
class TestGraphitiInit:
    def test_default(self):
        g = Graphiti()
        assert g._ws_cache == {} and g._token_tracker is None
        g.close()

    @patch("spacetime_memory.sdks.graphiti._core.Client")
    def test_with_client(self, mcc):
        mc = MagicMock()
        g = Graphiti(client=mc)
        assert g._client is mc
        mcc.assert_not_called()
        g.close()

    @patch("spacetime_memory.sdks.graphiti._core.Client")
    def test_custom_host(self, mcc):
        g = Graphiti(host="h", port=1234, database="db")
        mcc.assert_called_once_with(
            host="h", port=1234, database="db", token=None, embedder_url=None
        )
        g.close()

    def test_token_tracker(self):
        g = Graphiti()
        assert g.token_tracker is None
        g.close()

    def test_nodes_property(self):
        g = Graphiti()
        assert isinstance(g.nodes, NodeNamespace)
        g.close()

    def test_edges_property(self):
        g = Graphiti()
        assert isinstance(g.edges, EdgeNamespace)
        g.close()


class TestResolveWorkspace:
    def test_cached(self):
        g = Graphiti()
        g._ws_cache["k"] = "v"
        assert g._resolve_workspace("k") == "v"
        g.close()

    def test_uuid_match(self):
        mc = MagicMock()
        mc.list_workspaces.return_value = [{"id": "u1", "name": "n1"}]
        g = Graphiti(client=mc)
        assert g._resolve_workspace("u1") == "u1"
        g.close()

    def test_name_match(self):
        mc = MagicMock()
        mc.list_workspaces.return_value = [{"id": "u1", "name": "my-ws"}]
        g = Graphiti(client=mc)
        assert g._resolve_workspace("my-ws") == "u1"
        g.close()

    def test_creates_workspace(self):
        mc = MagicMock()
        mc.list_workspaces.side_effect = [[], [{"id": "nu", "name": "nw"}]]
        g = Graphiti(client=mc)
        assert g._resolve_workspace("nw") == "nu"
        mc.create_workspace.assert_called_once_with("nw")
        g.close()

    def test_create_runtimeerror_handled(self):
        mc = MagicMock()
        mc.list_workspaces.side_effect = [[], [{"id": "nu", "name": "nw"}]]
        mc.create_workspace.side_effect = RuntimeError()
        g = Graphiti(client=mc)
        assert g._resolve_workspace("nw") == "nu"
        g.close()

    def test_last_resort(self):
        mc = MagicMock()
        mc.list_workspaces.return_value = []
        g = Graphiti(client=mc)
        assert g._resolve_workspace("orphan") == "orphan"
        g.close()


class TestSqlQuery:
    def test_success(self):
        mc = MagicMock()
        mc._sql.return_value = [{"id": "1"}]
        g = Graphiti(client=mc)
        assert g._sql_query("SELECT *") == [{"id": "1"}]
        g.close()

    def test_error_returns_empty(self):
        mc = MagicMock()
        mc._sql.side_effect = RuntimeError("fail")
        g = Graphiti(client=mc)
        assert g._sql_query("SELECT *") == []
        g.close()


class TestFilterByValidAt:
    def test_no_filter(self):
        g = Graphiti()
        edges = [EntityEdge(name="e1"), EntityEdge(name="e2")]
        assert g._filter_by_valid_at(edges) == edges
        g.close()

    def test_after(self):
        g = Graphiti()
        d1 = datetime(2024, 1, 1, tzinfo=UTC)
        d2 = datetime(2024, 6, 1, tzinfo=UTC)
        edges = [EntityEdge(name="e1", valid_at=d1), EntityEdge(name="e2", valid_at=d2)]
        result = g._filter_by_valid_at(edges, valid_at_after=datetime(2024, 3, 1, tzinfo=UTC))
        assert len(result) == 1 and result[0].name == "e2"
        g.close()

    def test_before(self):
        g = Graphiti()
        d1 = datetime(2024, 1, 1, tzinfo=UTC)
        edges = [EntityEdge(name="e1", valid_at=d1)]
        result = g._filter_by_valid_at(edges, valid_at_before=datetime(2024, 3, 1, tzinfo=UTC))
        assert len(result) == 1
        g.close()

    def test_excludes_none_valid_at(self):
        g = Graphiti()
        edges = [
            EntityEdge(name="e1", valid_at=datetime(2024, 6, 1, tzinfo=UTC)),
            EntityEdge(name="e2"),
        ]
        result = g._filter_by_valid_at(edges, valid_at_after=datetime(2024, 1, 1, tzinfo=UTC))
        assert len(result) == 1
        g.close()


class TestGetOrCreateNode:
    def test_exact(self):
        mc = MagicMock()
        mc._query.return_value = [{"id": "u1", "label": "Alice"}]
        g = Graphiti(client=mc)
        r = g._get_or_create_node(EntityNode(name="Alice"), "ws")
        assert r == ("u1", 1.0)
        g.close()

    def test_case_insensitive(self):
        mc = MagicMock()
        mc._query.return_value = [{"id": "u2", "label": "alice"}]
        g = Graphiti(client=mc)
        r = g._get_or_create_node(EntityNode(name="Alice"), "ws")
        assert r[0] == "u2" and r[1] == 0.95
        g.close()

    def test_create_false_returns_none(self):
        mc = MagicMock()
        mc._query.return_value = [{"id": "u1", "label": "Bob"}]
        g = Graphiti(client=mc)
        assert g._get_or_create_node(EntityNode(name="Alice"), "ws", create=False) is None
        g.close()


class TestAddTriplet:
    def test_basic(self):
        mc = MagicMock()
        mc.list_workspaces.return_value = [{"id": "w1", "name": "ws1"}]
        mc._query.return_value = [{"id": "s1", "label": "Alice"}]
        g = Graphiti(client=mc)
        r = g.add_triplet(
            EntityNode(name="Alice", group_id="ws1"),
            EntityEdge(name="likes", group_id="ws1"),
            EntityNode(name="Pizza", group_id="ws1"),
        )
        assert len(r.nodes) == 2 and len(r.edges) == 1
        g.close()

    def test_create_edge_error(self):
        mc = MagicMock()
        mc.list_workspaces.return_value = [{"id": "w1", "name": "ws1"}]
        mc._query.return_value = [{"id": "s1", "label": "Alice"}]
        mc.create_edge.side_effect = RuntimeError("fail")
        g = Graphiti(client=mc)
        with pytest.raises(RuntimeError, match="create_edge failed"):
            g.add_triplet(
                EntityNode(name="Alice", group_id="ws1"),
                EntityEdge(name="likes", group_id="ws1"),
                EntityNode(name="Pizza", group_id="ws1"),
            )
        g.close()


class TestAddEpisode:
    def test_basic(self):
        mc = MagicMock()
        mc.list_workspaces.return_value = [{"id": "w1", "name": "default"}]
        g = Graphiti(client=mc)
        with patch.object(g, "_extract_entities_from_text", return_value=None):
            r = g.add_episode("e1", "body", "src")
        assert r.episode.name == "e1"
        g.close()

    def test_store_error(self):
        mc = MagicMock()
        mc.list_workspaces.return_value = [{"id": "w1", "name": "default"}]
        mc.store.side_effect = RuntimeError("fail")
        g = Graphiti(client=mc)
        with pytest.raises(RuntimeError):
            g.add_episode("e1", "body", "src")
        g.close()

    def test_with_uuid(self):
        mc = MagicMock()
        mc.list_workspaces.return_value = [{"id": "w1", "name": "default"}]
        g = Graphiti(client=mc)
        with patch.object(g, "_extract_entities_from_text", return_value=None):
            r = g.add_episode("e2", "body", "src", uuid="my-uuid")
        assert r.episode.uuid == "my-uuid"
        g.close()


class TestAddEpisodeBulk:
    def test_basic(self):
        mc = MagicMock()
        mc.list_workspaces.return_value = [{"id": "w1", "name": "default"}]
        g = Graphiti(client=mc)
        with patch.object(g, "_extract_entities_from_text", return_value=None):
            r = g.add_episode_bulk([RawEpisode(name="b1", content="c1")])
        assert len(r.episodes) == 1 and r.episodes[0].name == "b1"
        g.close()

    def test_empty(self):
        g = Graphiti()
        r = g.add_episode_bulk([])
        assert r.episodes == [] and r.nodes == []
        g.close()


class TestSearch:
    def test_basic(self):
        mc = MagicMock()
        mc.list_workspaces.return_value = [{"id": "w1", "name": "default"}]
        mc.search.return_value = []
        g = Graphiti(client=mc)
        assert g.search("test") == []
        g.close()

    def test_fallback(self):
        mc = MagicMock()
        mc.list_workspaces.return_value = [{"id": "w1", "name": "default"}]
        mc.search.return_value = []
        mc.query_graph.return_value = [{"id": "n1"}]
        mc.get_neighbors.return_value = [
            {"id": "e1", "relation": "r", "fact": "f",
             "source_node_id": "s1", "target_node_id": "t1"}
        ]
        g = Graphiti(client=mc)
        r = g.search("test")
        assert len(r) == 1
        g.close()


class TestSearchUnderscore:
    def test_basic(self):
        mc = MagicMock()
        mc.list_workspaces.return_value = [{"id": "w1", "name": "default"}]
        mc.search.return_value = []
        g = Graphiti(client=mc)
        r = g.search_("test")
        assert isinstance(r, SearchResults)
        g.close()


class TestGetEntityEdgeSummary:
    def test_basic(self):
        mc = MagicMock()
        mc.list_workspaces.return_value = [{"id": "w1", "name": "default"}]
        mc.get_neighbors.return_value = [
            {"id": "e1", "relation": "r", "fact": "connects",
             "source_node_id": "s1", "target_node_id": "t1"}
        ]
        mc._query.return_value = [{"id": "t1", "label": "Tgt"}]
        g = Graphiti(client=mc)
        r = g.get_entity_edge_summary("s1", group_ids=["default"])
        assert len(r["edges"]) == 1
        g.close()

    def test_nonexistent(self):
        mc = MagicMock()
        mc.get_neighbors.side_effect = RuntimeError()
        g = Graphiti(client=mc)
        r = g.get_entity_edge_summary("bad")
        assert r["edges"] == [] and r["summary"] == ""
        g.close()


class TestRemoveEpisode:
    def test_basic(self):
        mc = MagicMock()
        mc._query.return_value = [{"id": "m1"}]
        g = Graphiti(client=mc)
        r = g.remove_episode("ep-uuid")
        assert r["status"] == "ok"
        mc.delete_memory.assert_called_once_with("m1")
        g.close()

    def test_no_memories(self):
        mc = MagicMock()
        mc._query.return_value = []
        g = Graphiti(client=mc)
        r = g.remove_episode("nonexistent")
        assert r["status"] == "ok"
        g.close()


class TestRetrieveEpisodes:
    def test_basic(self):
        mc = MagicMock()
        mc.list_workspaces.return_value = [{"id": "w1", "name": "default"}]
        mc._query.return_value = [
            {"id": "m1", "content": "ep", "created_at": 1_700_000_000_000_000,
             "source_session_id": "ss1", "workspace_id": "default", "peer_id": "p"}
        ]
        g = Graphiti(client=mc)
        r = g.retrieve_episodes()
        assert len(r) == 1 and r[0].content == "ep"
        g.close()


class TestBuildCommunities:
    def test_basic(self):
        mc = MagicMock()
        mc.list_workspaces.return_value = [{"id": "w1", "name": "default"}]
        mc._query.return_value = []
        g = Graphiti(client=mc)
        r = g.build_communities()
        assert isinstance(r, list)
        g.close()


class TestUpdateEdge:
    def test_basic(self):
        mc = MagicMock()
        mc._call.return_value = {"status": "ok"}
        g = Graphiti(client=mc)
        r = g.update_edge("edge-uuid", relation="new_r")
        assert r["status"] == "ok"
        g.close()

    def test_error(self):
        mc = MagicMock()
        mc._call.side_effect = RuntimeError("fail")
        g = Graphiti(client=mc)
        with pytest.raises(RuntimeError):
            g.update_edge("edge-uuid", relation="r")
        g.close()


class TestGetEdgeHistory:
    def test_no_matching(self):
        mc = MagicMock()
        mc._query.return_value = []
        g = Graphiti(client=mc)
        assert g.get_edge_history("bad") == []
        g.close()

    def test_no_group_id(self):
        mc = MagicMock()
        mc._query.return_value = [{"edge_group_id": ""}]
        g = Graphiti(client=mc)
        assert g.get_edge_history("bad") == []
        g.close()


class TestBuildIndices:
    def test_ok(self):
        g = Graphiti()
        assert g.build_indices_and_constraints()["status"] == "ok"
        g.close()


class TestClose:
    def test_no_http(self):
        Graphiti().close()

    def test_with_http(self):
        mc = MagicMock()
        mc._http = MagicMock()
        g = Graphiti(client=mc)
        g.close()
        mc._http.close.assert_called_once()


class TestSummarizeSaga:
    def test_no_episodes(self):
        mc = MagicMock()
        mc._query.return_value = []
        g = Graphiti(client=mc)
        s = g.summarize_saga("saga-1")
        assert isinstance(s, SagaNode)
        g.close()


class TestEntityNodeNamespace:
    def test_save_new(self):
        mc = MagicMock()
        mc.list_workspaces.return_value = [{"id": "w1", "name": "default"}]
        mc._query.return_value = []
        g = Graphiti(client=mc)
        g.nodes.entity.save(EntityNode(name="A", group_id="default"))
        mc.create_node.assert_called_once()
        g.close()

    def test_save_existing(self):
        mc = MagicMock()
        mc.list_workspaces.return_value = [{"id": "w1", "name": "default"}]
        mc._query.return_value = [{"id": "e1"}]
        g = Graphiti(client=mc)
        g.nodes.entity.save(EntityNode(name="A", group_id="default", uuid="e1"))
        mc.create_node.assert_not_called()
        g.close()

    def test_delete(self):
        mc = MagicMock()
        g = Graphiti(client=mc)
        g.nodes.entity.delete(EntityNode(uuid="n1"))
        mc._call.assert_called_once_with("delete_node", ["n1"])
        g.close()

    def test_get_by_uuid(self):
        mc = MagicMock()
        mc._query.return_value = [{"id": "n1", "label": "Alice"}]
        g = Graphiti(client=mc)
        r = g.nodes.entity.get_by_uuid("n1")
        assert r.name == "Alice"
        g.close()

    def test_get_by_uuid_not_found(self):
        mc = MagicMock()
        mc._query.return_value = []
        g = Graphiti(client=mc)
        with pytest.raises(KeyError):
            g.nodes.entity.get_by_uuid("bad")
        g.close()


class TestEpisodeNodeNamespace:
    def test_row_to_episode(self):
        r = EpisodeNodeNamespace._row_to_episode({
            "id": "m1", "source_session_id": "ss1", "content": "text",
            "peer_id": "sender", "workspace_id": "ws1",
            "created_at": 1_700_000_000_000_000,
        })
        assert r.content == "text" and r.uuid == "ss1"

    def test_get_by_uuid(self):
        mc = MagicMock()
        mc._query.return_value = [
            {"id": "m1", "source_session_id": "ep1", "content": "hello",
             "peer_id": "p", "created_at": 1_700_000_000_000_000}
        ]
        g = Graphiti(client=mc)
        r = g.nodes.episode.get_by_uuid("ep1")
        assert r.content == "hello"
        g.close()


class TestExtractEntitiesFromText:
    def test_no_llm(self):
        g = Graphiti()
        with patch("spacetime_memory.sdks.graphiti._episodes.LLMClient") as mlc:
            mlc().available = False
            assert g._extract_entities_from_text("text") is None
        g.close()

    def test_with_llm(self):
        g = Graphiti()
        with patch("spacetime_memory.sdks.graphiti._episodes.LLMClient") as mlc:
            mlc().available = True
            mlc().chat.return_value = '{"entities":[{"name":"A"}],"edges":[]}'
            r = g._extract_entities_from_text("text")
            assert r["entities"][0]["name"] == "A"
        g.close()
