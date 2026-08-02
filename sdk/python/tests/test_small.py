"""Unit tests for the Graphiti adapter — data classes, helpers, constructors, and mock-backed methods.

No live SpacetimeDB required.  All Client calls are mocked via MagicMock.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from spacetime_memory.sdks.graphiti import (
    AddTripletResults,
    CommunityNode,
    EntityEdge,
    EntityNode,
    EpisodicNode,
    Graphiti,
    RawEpisode,
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
        assert _esc("café") == "café"

    def test_leading_trailing_quotes(self):
        assert _esc("'hello'") == "''hello''"

    def test_backslash_not_escaped(self):
        assert _esc("it\'s") == "it\''s"

    def test_newline_not_affected(self):
        assert _esc("line1\nline2") == "line1\nline2"

    def test_tab_not_affected(self):
        assert _esc("col1\tcol2") == "col1\tcol2"

    def test_non_string_input(self):
        with pytest.raises(AttributeError):
            _esc(None)


# =====================================================================
# Data class constructors
# =====================================================================


class TestEntityNode:
    def test_minimal_constructor(self):
        """EntityNode with only required args."""
        node = EntityNode(name="Alice")
        assert node.name == "Alice"
        assert node.group_id == "default"
        assert isinstance(node.uuid, str) and len(node.uuid) > 0
        assert node.summary == ""

    def test_with_group_id(self):
        node = EntityNode(name="Alice", group_id="my-group")
        assert node.group_id == "my-group"

    def test_summary(self):
        node = EntityNode(name="Alice", summary="A test entity")
        assert node.summary == "A test entity"

    def test_default_name_empty(self):
        node = EntityNode()
        assert node.name == ""

    def test_created_at_auto(self):
        node = EntityNode(name="test")
        assert isinstance(node.created_at, datetime)


class TestEntityEdge:
    def test_minimal_constructor(self):
        edge = EntityEdge(name="likes")
        assert edge.name == "likes"
        assert edge.group_id == "default"
        assert edge.fact == ""

    def test_with_fact(self):
        edge = EntityEdge(name="knows", fact="Alice knows Bob")
        assert edge.fact == "Alice knows Bob"

    def test_with_group_id(self):
        edge = EntityEdge(name="works_with", group_id="team-a")
        assert edge.group_id == "team-a"

    def test_fact_embedding(self):
        edge = EntityEdge(name="likes", fact_embedding=[0.5, 0.6])
        assert edge.fact_embedding == [0.5, 0.6]

    def test_default_name_empty(self):
        edge = EntityEdge()
        assert edge.name == ""
        assert edge.fact == ""


class TestEpisodicNode:
    def test_minimal(self):
        node = EpisodicNode(name="ep1")
        assert node.name == "ep1"
        assert node.group_id == "default"
        assert node.content == ""

    def test_with_content(self):
        node = EpisodicNode(name="Chat", content="Hello world", group_id="g1")
        assert node.content == "Hello world"
        assert node.group_id == "g1"

    def test_source_default(self):
        node = EpisodicNode(name="msg")
        assert node.source == "message"


class TestCommunityNode:
    def test_minimal(self):
        cn = CommunityNode(name="community-1")
        assert cn.name == "community-1"
        assert cn.group_id == "default"
        assert cn.summary == ""

    def test_with_summary(self):
        cn = CommunityNode(name="tech", summary="Tech community", group_id="g1")
        assert cn.summary == "Tech community"
        assert cn.group_id == "g1"


class TestRawEpisode:
    def test_minimal(self):
        ep = RawEpisode(name="ep1", content="raw content")
        assert ep.name == "ep1"
        assert ep.content == "raw content"
        assert ep.source == "message"

    def test_custom_source(self):
        ep = RawEpisode(name="ep1", content="data", source="api")
        assert ep.source == "api"


class TestSearchResults:
    def test_defaults(self):
        results = SearchResults()
        assert results.nodes == []
        assert results.edges == []

    def test_with_nodes(self):
        node = EntityNode(name="Alice")
        results = SearchResults(nodes=[node])
        assert len(results.nodes) == 1

    def test_with_edges(self):
        edge = EntityEdge(name="likes")
        results = SearchResults(edges=[edge])
        assert len(results.edges) == 1

    def test_with_both(self):
        node = EntityNode(name="Alice")
        edge = EntityEdge(name="likes")
        results = SearchResults(nodes=[node], edges=[edge])
        assert len(results.nodes) == 1
        assert len(results.edges) == 1
        assert results.nodes[0].name == "Alice"
        assert results.edges[0].name == "likes"


class TestAddTripletResults:
    def test_minimal(self):
        result = AddTripletResults()
        assert result.nodes == []
        assert result.edges == []

    def test_with_nodes_and_edges(self):
        node = EntityNode(name="Alice")
        edge = EntityEdge(name="likes")
        result = AddTripletResults(nodes=[node], edges=[edge])
        assert len(result.nodes) == 1
        assert len(result.edges) == 1
        assert result.nodes[0].name == "Alice"


# =====================================================================
# Graphiti adapter — construction
# =====================================================================


class TestGraphitiInit:
    def test_minimal_init(self):
        g = Graphiti(host="localhost", port=3001)
        assert g._client is not None
        g.close()

    def test_init_with_client_arg(self):
        from spacetime_memory import Client

        client = MagicMock(spec=Client)
        g = Graphiti(client=client)
        assert g._client is client
        g.close()

    def test_init_with_client_sets_clients_alias(self):
        from spacetime_memory import Client

        client = MagicMock(spec=Client)
        g = Graphiti(client=client)
        assert g.clients is client


class TestGraphitiMethods:
    @pytest.fixture
    def graphiti(self):
        from spacetime_memory import Client

        client = MagicMock(spec=Client)
        client._http = MagicMock()
        client._http.close = MagicMock()
        g = Graphiti(client=client)
        yield g
        g.close()

    def test_close_called(self, graphiti):
        """close() calls the underlying http client's close()."""
        graphiti.close()
        graphiti._client._http.close.assert_called_once()
