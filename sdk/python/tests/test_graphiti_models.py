"""Unit tests for the Graphiti adapter models (_models.py).

Tests all dataclass model types: construction, serialization,
deserialization, model_dump, model_validate, and from_stmem.
"""

from __future__ import annotations

import pytest

from spacetime_memory.sdks.graphiti._models import (
    AddBulkEpisodeResults,
    AddEpisodeResults,
    AddTripletResults,
    CommunityEdge,
    CommunityNode,
    EntityEdge,
    EntityNode,
    EpisodicEdge,
    EpisodicNode,
    HasEpisodeEdge,
    NextEpisodeEdge,
    RawEpisode,
    SagaNode,
    SearchResults,
)

pytestmark = pytest.mark.unit


# ── EntityNode ─────────────────────────────────────────────────────────────


class TestEntityNode:
    def test_default_construction(self):
        node = EntityNode()
        assert node.uuid  # auto-generated hex UUID
        assert node.name == ""
        assert node.group_id == "default"
        assert node.attributes == {}

    def test_custom_construction(self):
        node = EntityNode(
            uuid="my-uuid",
            name="Alice",
            summary="A person",
            group_id="ws-1",
            labels=["person", "user"],
            attributes={"age": 30},
        )
        assert node.uuid == "my-uuid"
        assert node.name == "Alice"
        assert node.summary == "A person"
        assert node.group_id == "ws-1"
        assert node.labels == ["person", "user"]
        assert node.attributes == {"age": 30}

    def test_model_dump(self):
        node = EntityNode(name="Test", group_id="g1")
        d = node.model_dump()
        assert isinstance(d, dict)
        assert d["name"] == "Test"
        assert d["group_id"] == "g1"
        assert "uuid" in d
        assert "attributes" in d

    def test_model_validate(self):
        data = {
            "uuid": "abc",
            "name": "Alice",
            "summary": "Person",
            "group_id": "ws-1",
            "labels": ["person"],
            "attributes": {"k": "v"},
        }
        node = EntityNode.model_validate(data)
        assert node.uuid == "abc"
        assert node.name == "Alice"
        assert node.labels == ["person"]

    def test_from_stmem_typical(self):
        row = {
            "id": "n1",
            "label": "Alice",
            "summary": "A person",
            "workspace_id": "ws-1",
            "labels": '["person"]',
            "metadata_json": '{"age": 30}',
            "created_at": 1_700_000_000_000_000,  # microseconds
        }
        node = EntityNode.from_stmem(row)
        assert node.uuid == "n1"
        assert node.name == "Alice"
        assert node.group_id == "ws-1"
        assert node.attributes == {"age": 30}

    def test_from_stmem_corrupt_metadata(self):
        row = {
            "id": "n1",
            "label": "Bob",
            "metadata_json": "{{{corrupt",
        }
        node = EntityNode.from_stmem(row)
        assert node.name == "Bob"
        assert node.attributes == {}  # gracefully handled

    def test_from_stmem_empty_metadata(self):
        row = {"id": "n1", "label": "Charlie"}
        node = EntityNode.from_stmem(row)
        assert node.attributes == {}


# ── EntityEdge ─────────────────────────────────────────────────────────────


class TestEntityEdge:
    def test_default_construction(self):
        edge = EntityEdge()
        assert edge.uuid
        assert edge.name == ""
        assert edge.fact == ""
        assert edge.version == 1
        assert edge.edge_group_id == ""

    def test_custom_construction(self):
        edge = EntityEdge(
            uuid="e1",
            name="likes",
            fact="Alice likes pizza",
            source_node_uuid="n1",
            target_node_uuid="n2",
            group_id="ws-1",
            version=3,
            edge_group_id="eg-1",
        )
        assert edge.uuid == "e1"
        assert edge.name == "likes"
        assert edge.source_node_uuid == "n1"
        assert edge.version == 3
        assert edge.edge_group_id == "eg-1"

    def test_model_dump(self):
        edge = EntityEdge(name="knows", fact="Known", group_id="g1")
        d = edge.model_dump()
        assert isinstance(d, dict)
        assert d["name"] == "knows"
        assert d["fact"] == "Known"

    def test_model_validate(self):
        data = {
            "uuid": "e1",
            "name": "likes",
            "fact": "Likes pizza",
            "source_node_uuid": "n1",
            "target_node_uuid": "n2",
            "group_id": "ws-1",
            "version": 2,
        }
        edge = EntityEdge.model_validate(data)
        assert edge.name == "likes"
        assert edge.version == 2

    def test_from_stmem_typical(self):
        row = {
            "id": "e1",
            "relation": "likes",
            "fact": "likes pizza",
            "source_node_id": "n1",
            "target_node_id": "n2",
            "workspace_id": "ws-1",
            "metadata_json": '{"fact": "likes pizza"}',
            "version": 1,
            "edge_group_id": "eg-1",
            "created_at": 1_700_000_000_000_000,
            "valid_at": 0,
            "invalid_at": 0,
        }
        edge = EntityEdge.from_stmem(row)
        assert edge.uuid == "e1"
        assert edge.name == "likes"
        assert edge.fact == "likes pizza"
        assert edge.version == 1
        assert edge.edge_group_id == "eg-1"

    def test_from_stmem_fact_fallback_to_relation(self):
        row = {
            "id": "e1",
            "relation": "knows",
            "source_node_id": "s1",
            "target_node_id": "t1",
        }
        edge = EntityEdge.from_stmem(row)
        assert edge.fact == "knows"  # falls back to relation


# ── EpisodicNode ───────────────────────────────────────────────────────────


class TestEpisodicNode:
    def test_default_construction(self):
        ep = EpisodicNode()
        assert ep.uuid
        assert ep.source == "message"
        assert ep.group_id == "default"

    def test_custom_construction(self):
        ep = EpisodicNode(
            uuid="ep1",
            name="my-episode",
            content="Some text",
            source="text",
            group_id="ws-1",
            episode_metadata={"key": "val"},
        )
        assert ep.name == "my-episode"
        assert ep.content == "Some text"
        assert ep.episode_metadata == {"key": "val"}

    def test_model_dump(self):
        ep = EpisodicNode(name="test", content="hello")
        d = ep.model_dump()
        assert d["name"] == "test"
        assert d["content"] == "hello"

    def test_model_validate(self):
        data = {
            "uuid": "ep1",
            "name": "test",
            "content": "hello",
            "source": "message",
            "group_id": "ws-1",
        }
        ep = EpisodicNode.model_validate(data)
        assert ep.name == "test"
        assert ep.content == "hello"


# ── CommunityNode ──────────────────────────────────────────────────────────


class TestCommunityNode:
    def test_default_construction(self):
        cn = CommunityNode()
        assert cn.uuid == ""
        assert cn.group_id == "default"
        assert cn.member_uuids == []

    def test_custom_construction(self):
        cn = CommunityNode(
            uuid="c1",
            name="developers",
            group_id="ws-1",
            summary="Dev community",
            member_uuids=["n1", "n2"],
        )
        assert cn.name == "developers"
        assert cn.member_uuids == ["n1", "n2"]

    def test_model_dump(self):
        cn = CommunityNode(name="test", group_id="g1")
        d = cn.model_dump()
        assert d["name"] == "test"

    def test_model_validate(self):
        data = {"uuid": "c1", "name": "comm", "group_id": "ws-1"}
        cn = CommunityNode.model_validate(data)
        assert cn.name == "comm"


# ── Other model types ──────────────────────────────────────────────────────


class TestOtherModels:
    def test_community_edge_defaults(self):
        ce = CommunityEdge()
        assert ce.uuid == ""

    def test_episodic_edge_defaults(self):
        ee = EpisodicEdge()
        assert ee.uuid

    def test_has_episode_edge_defaults(self):
        he = HasEpisodeEdge()
        assert he.uuid

    def test_next_episode_edge_defaults(self):
        ne = NextEpisodeEdge()
        assert ne.uuid

    def test_saga_node_defaults(self):
        sn = SagaNode()
        assert sn.uuid
        assert sn.name == ""
        assert sn.first_episode_uuid is None

    def test_saga_node_model_dump(self):
        sn = SagaNode(name="saga1", summary="A saga")
        d = sn.model_dump()
        assert d["name"] == "saga1"
        assert d["summary"] == "A saga"

    def test_saga_node_model_validate(self):
        data = {
            "uuid": "s1",
            "name": "saga1",
            "group_id": "ws-1",
            "summary": "A long saga",
        }
        sn = SagaNode.model_validate(data)
        assert sn.name == "saga1"


# ── Result containers ──────────────────────────────────────────────────────


class TestResultContainers:
    def test_search_results_defaults(self):
        sr = SearchResults()
        assert sr.edges == []
        assert sr.nodes == []

    def test_search_results_with_data(self):
        sr = SearchResults(
            edges=[EntityEdge(name="e1")],
            nodes=[EntityNode(name="n1")],
        )
        assert len(sr.edges) == 1
        assert len(sr.nodes) == 1

    def test_add_triplet_results_defaults(self):
        atr = AddTripletResults()
        assert atr.nodes == []
        assert atr.edges == []

    def test_add_episode_results_defaults(self):
        aer = AddEpisodeResults()
        assert aer.episode is None
        assert aer.nodes == []
        assert aer.edges == []

    def test_add_bulk_episode_results_defaults(self):
        aber = AddBulkEpisodeResults()
        assert aber.episodes == []

    def test_raw_episode_defaults(self):
        re = RawEpisode()
        assert re.name == ""
        assert re.content == ""
        assert re.source == "message"
