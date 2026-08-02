"""Unit tests for SessionDistillationMixin (_session_distillation.py).

All tests use mocked HTTP — no live SpacetimeDB required.
"""
from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest

from spacetime_memory.client._session_distillation import (
    SEARCH_STRATEGIES,
    SessionDistillationMixin,
)

# ============================================================================
# Helpers
# ============================================================================


def _make_session(
    session_id: str = "sess_001",
    workspace_id: str = "ws_test",
    name: str = "Test Session",
    summary: str = "A test session about deployment",
    created_at: int | None = None,
) -> dict:
    now = int(time.time() * 1_000_000)
    return {
        "id": session_id,
        "workspace_id": workspace_id,
        "name": name,
        "summary": summary,
        "metadata": json.dumps({"topic": "testing", "tags": ["deploy"]}),
        "created_at": created_at or (now - 3600 * 1_000_000),
        "updated_at": now,
    }


def _make_message(
    msg_id: str = "msg_001",
    session_id: str = "sess_001",
    sender: str = "alice",
    content: str = "Let's deploy the new version.",
    created_at: int | None = None,
) -> dict:
    now = int(time.time() * 1_000_000)
    return {
        "id": msg_id,
        "session_id": session_id,
        "sender_id": sender,
        "sender": sender,
        "content": content,
        "created_at": created_at or (now - 1800 * 1_000_000),
    }


def _make_participant(
    session_id: str = "sess_001",
    peer_id: str = "alice",
    role: str = "editor",
) -> dict:
    return {
        "session_id": session_id,
        "peer_id": peer_id,
        "role": role,
        "joined_at": int(time.time() * 1_000_000) - 3600 * 1_000_000,
    }


# ============================================================================
# Session Distillation tests
# ============================================================================


class TestDistillSession:
    """distill_session method."""

    def test_distill_session_basic(self, mock_http_client):
        client = mock_http_client
        with patch.object(client, "_query") as mock_query:
            # Mock session info
            mock_query.side_effect = [
                [_make_session()],  # session query
                [_make_message()],  # messages
                [],                 # memories
                [_make_participant()],  # participants
            ]

            with patch.object(client, "distill_session",
                              wraps=client.distill_session) as _:
                # We need to mock _llm_complete since there's no LLM
                with patch.object(client, "_llm_complete",
                                  return_value="Summary text."):
                    result = client.distill_session(
                        workspace_id="ws_test",
                        session_id="sess_001",
                    )
                    assert result["session_id"] == "sess_001"
                    assert result["session_name"] == "Test Session"
                    assert result["message_count"] >= 1
                    assert "summary" in result

    def test_distill_session_no_messages(self, mock_http_client):
        """Distilling a session with no messages returns zeros."""
        client = mock_http_client
        with patch.object(client, "_query") as mock_query:
            mock_query.side_effect = [
                [_make_session()],  # session
                [],                 # no messages
                [],                 # no memories
                [],                 # no participants
            ]
            result = client.distill_session(
                workspace_id="ws_test",
                session_id="sess_empty",
            )
            assert result["message_count"] == 0
            assert result["memory_count"] == 0

    def test_distill_session_with_metadata(self, mock_http_client):
        """Include/exclude metadata flag."""
        client = mock_http_client
        with patch.object(client, "_query") as mock_query:
            mock_query.side_effect = [
                [_make_session()],
                [_make_message()],
                [],
                [],
            ]
            with patch.object(client, "_llm_complete",
                              return_value="Summary with metadata."):
                result = client.distill_session(
                    workspace_id="ws_test",
                    session_id="sess_001",
                    include_metadata=True,
                )
                assert "summary" in result


class TestExtractTemporalGraph:
    """extract_temporal_graph method."""

    def test_extract_events_from_messages(self, mock_http_client):
        client = mock_http_client
        messages = [
            _make_message("m1", "sess1", "alice",
                          "We decided to use Kubernetes."),
            _make_message("m2", "sess1", "bob",
                          "TODO: set up the cluster."),
            _make_message("m3", "sess1", "carol",
                          "What about the database?"),
        ]

        with patch.object(client, "_query", return_value=messages):
            events = client.extract_temporal_graph(
                workspace_id="ws_test",
                session_id="sess1",
            )
            # Should detect decision, action item, question
            assert len(events) >= 3
            types = {e["type"] for e in events}
            assert "decision" in types
            assert "action_item" in types
            assert "question" in types

    def test_extract_no_messages(self, mock_http_client):
        client = mock_http_client
        with patch.object(client, "_query", return_value=[]):
            events = client.extract_temporal_graph(
                workspace_id="ws_test",
                session_id="sess_empty",
            )
            assert events == []

    def test_event_confidence_scores(self, mock_http_client):
        """Different event types have different confidence scores."""
        client = mock_http_client
        messages = [
            _make_message("m1", "sess1", "alice", "Agreed on the plan."),
            _make_message("m2", "sess1", "bob", "What?!"),
        ]

        with patch.object(client, "_query", return_value=messages):
            events = client.extract_temporal_graph(
                workspace_id="ws_test",
                session_id="sess1",
            )
            for ev in events:
                assert 0 <= ev.get("confidence", 0) <= 1


class TestSearchSessionStrategies:
    """search_session_strategies — all 18 variants."""

    def test_search_strategies_keys(self):
        """All 18 strategies are defined."""
        assert len(SEARCH_STRATEGIES) == 18

    def test_invalid_strategy_raises(self, mock_http_client):
        client = mock_http_client
        with pytest.raises(ValueError, match="Unknown strategy"):
            client.search_session_strategies(
                query="test",
                strategy="nonexistent",
            )

    def test_search_keyword(self, mock_http_client):
        client = mock_http_client
        sessions = [
            _make_session("s1", "ws1", "Deployment Config"),
            _make_session("s2", "ws1", "Database Setup"),
        ]

        with patch.object(client, "_query", return_value=sessions):
            results = client.search_session_strategies(
                query="deployment",
                strategy="keyword",
                workspace_id="ws1",
            )
            assert len(results) >= 1
            assert results[0]["strategy"] == "keyword"

    def test_search_semantic_fallback(self, mock_http_client):
        """Semantic search falls back to keyword if no embedder."""
        client = mock_http_client
        sessions = [_make_session("s1", "ws1", "Test Session")]

        with patch.object(client, "_query", return_value=sessions):
            results = client.search_session_strategies(
                query="test",
                strategy="semantic",
            )
            # Should not raise
            assert isinstance(results, list)

    def test_search_temporal(self, mock_http_client):
        client = mock_http_client
        now = int(time.time() * 1_000_000)
        sessions = [
            _make_session("old", "ws1", "Old Session",
                          created_at=now - 86400 * 1_000_000 * 10),
            _make_session("recent", "ws1", "Recent Session",
                          created_at=now - 3600 * 1_000_000),
        ]

        with patch.object(client, "_query", return_value=sessions):
            results = client.search_session_strategies(
                query="session",
                strategy="temporal",
                start_time=now - 86400 * 1_000_000 * 2,
                end_time=now,
            )
            assert len(results) >= 1

    def test_search_exact_phrase(self, mock_http_client):
        client = mock_http_client
        sessions = [
            _make_session("s1", "ws1", "Deployment Guide"),
            _make_session("s2", "ws1", "Setup Guide"),
        ]

        with patch.object(client, "_query", return_value=sessions):
            results = client.search_session_strategies(
                query="Deployment Guide",
                strategy="exact_phrase",
            )
            assert len(results) == 1

    def test_search_boolean(self, mock_http_client):
        client = mock_http_client
        sessions = [
            _make_session("s1", "ws1", "Deployment Config"),
            _make_session("s2", "ws1", "Database Setup"),
            _make_session("s3", "ws1", "Both Config and Database"),
        ]

        with patch.object(client, "_query", return_value=sessions):
            results = client.search_session_strategies(
                query="Config AND Database",
                strategy="boolean",
            )
            assert len(results) >= 1

    def test_search_fuzzy(self, mock_http_client):
        client = mock_http_client
        sessions = [
            _make_session("s1", "ws1", "Deploment"),  # typo
            _make_session("s2", "ws1", "Database"),
        ]

        with patch.object(client, "_query", return_value=sessions):
            results = client.search_session_strategies(
                query="deployment",
                strategy="fuzzy",
            )
            # Should match "Deploment" fuzzily
            matching = [r for r in results if r["session"]["id"] == "s1"]
            assert len(matching) >= 1

    def test_search_adaptive_structured(self, mock_http_client):
        """Adaptive strategy selects 'structured' for field:value queries."""
        client = mock_http_client
        sessions = [_make_session("s1", "ws1", "Test")]

        with patch.object(client, "_query", return_value=sessions):
            results = client.search_session_strategies(
                query="metadata:deploy",
                strategy="adaptive",
            )
            assert isinstance(results, list)

    def test_search_adaptive_boolean(self, mock_http_client):
        """Adaptive strategy selects 'boolean' for AND/OR/NOT queries."""
        client = mock_http_client
        sessions = [_make_session("s1", "ws1", "Deployment Config")]

        with patch.object(client, "_query", return_value=sessions):
            results = client.search_session_strategies(
                query="Deployment AND Config",
                strategy="adaptive",
            )
            assert isinstance(results, list)

    def test_search_all_strategies_return_lists(self, mock_http_client):
        """All 18 strategies return a list."""
        client = mock_http_client

        for strategy in SEARCH_STRATEGIES:
            with patch.object(client, "_query",
                              return_value=[_make_session()]):
                try:
                    results = client.search_session_strategies(
                        query="test",
                        strategy=strategy,
                        limit=10,
                    )
                    assert isinstance(results, list)
                except Exception as e:
                    pytest.fail(f"Strategy '{strategy}' raised: {e}")


class TestFuzzyMatchScore:
    """Static fuzzy match scoring."""

    def test_exact_match(self):
        score = SessionDistillationMixin._fuzzy_match_score("hello", "hello")
        assert score == 1.0

    def test_partial_match(self):
        score = SessionDistillationMixin._fuzzy_match_score("hlo", "hello")
        assert score > 0

    def test_no_match(self):
        score = SessionDistillationMixin._fuzzy_match_score("xyz", "hello")
        assert score == 0.0

    def test_empty_query(self):
        score = SessionDistillationMixin._fuzzy_match_score("", "hello")
        assert score == 0.0

    def test_empty_target(self):
        score = SessionDistillationMixin._fuzzy_match_score("hello", "")
        assert score == 0.0


class TestImportRdfOntology:
    """import_rdf_ontology method."""

    def test_import_turtle(self, mock_http_client):
        client = mock_http_client
        turtle_data = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://example.org/> .

:Person a owl:Class .
:Agent a owl:Class .
:Person rdfs:subClassOf :Agent .
:hasName a owl:DatatypeProperty .
        """

        with patch.object(client, "_call",
                          return_value={"status": "ok"}) as _mock_call:
            result = client.import_rdf_ontology(
                workspace_id="ws1",
                ontology_data=turtle_data,
                format="turtle",
            )
            assert result["nodes_created"] >= 3  # Person, Agent, hasName
            assert result["edges_created"] >= 1  # Person subClassOf Agent
            assert result["success"] is True

    def test_import_jsonld(self, mock_http_client):
        client = mock_http_client
        jsonld_data = {
            "@context": {"owl": "http://www.w3.org/2002/07/owl#"},
            "@graph": [
                {"@id": "Person", "@type": "owl:Class"},
                {"@id": "Agent", "@type": "owl:Class"},
            ],
        }

        with patch.object(client, "_call",
                          return_value={"status": "ok"}) as _mock_call:
            result = client.import_rdf_ontology(
                workspace_id="ws1",
                ontology_data=json.dumps(jsonld_data),
                format="jsonld",
            )
            assert result["nodes_created"] >= 2
            assert result["success"] is True

    def test_import_unsupported_format(self, mock_http_client):
        client = mock_http_client
        result = client.import_rdf_ontology(
            workspace_id="ws1",
            ontology_data="data",
            format="rdfxml",
        )
        assert result["format"] == "rdfxml"
        assert len(result["errors"]) >= 1
        assert result["success"] is False


class TestGetSessionTimeline:
    """get_session_timeline method."""

    def test_timeline_with_messages(self, mock_http_client):
        client = mock_http_client
        messages = [
            _make_message("m1", "sess1", "alice", "First message",
                          created_at=1000),
            _make_message("m2", "sess1", "bob", "Second message",
                          created_at=2000),
        ]

        with patch.object(client, "_query", return_value=messages):
            timeline = client.get_session_timeline(
                session_id="sess1",
                include_messages=True,
                include_events=False,
            )
            # Timeline includes messages + agent steps (from Client mixin)
            assert len(timeline) >= 2
            assert timeline[0]["type"] == "message"
            assert timeline[0]["timestamp"] <= timeline[-1]["timestamp"]

    def test_timeline_no_messages(self, mock_http_client):
        client = mock_http_client
        with patch.object(client, "_query", return_value=[]):
            timeline = client.get_session_timeline(
                session_id="sess_empty",
            )
            assert isinstance(timeline, list)

    def test_timeline_chronological_order(self, mock_http_client):
        """Timeline entries are sorted by timestamp."""
        client = mock_http_client
        messages = [
            _make_message("m2", "sess1", "bob", "Later",
                          created_at=2000),
            _make_message("m1", "sess1", "alice", "Earlier",
                          created_at=1000),
        ]

        with patch.object(client, "_query", return_value=messages):
            timeline = client.get_session_timeline(
                session_id="sess1",
                include_events=False,
            )
            timestamps = [t["timestamp"] for t in timeline]
            assert timestamps == sorted(timestamps)


class TestMigrateFromAdapter:
    """migrate_from_adapter method."""

    def test_migrate_unknown_adapter(self, mock_http_client):
        client = mock_http_client
        with pytest.raises(ValueError, match="Unknown adapter type"):
            client.migrate_from_adapter(
                workspace_id="ws1",
                adapter_type="unknown_adapter",
            )

    def test_migrate_mem0_not_installed(self, mock_http_client):
        """When mem0 SDK not installed, returns error gracefully."""
        client = mock_http_client
        result = client.migrate_from_adapter(
            workspace_id="ws1",
            adapter_type="mem0",
        )
        assert result["success"] is False
        assert "error" in result

    def test_migrate_zep_not_installed(self, mock_http_client):
        client = mock_http_client
        result = client.migrate_from_adapter(
            workspace_id="ws1",
            adapter_type="zep",
        )
        assert result["success"] is False

    def test_migrate_honcho_not_installed(self, mock_http_client):
        client = mock_http_client
        import unittest
        with unittest.mock.patch.object(
            client, "_migrate_from_honcho",
            return_value={"adapter": "honcho", "success": False,
                          "error": "Honcho SDK not installed"},
        ):
            result = client.migrate_from_adapter(
                workspace_id="ws1",
                adapter_type="honcho",
            )
            assert result["success"] is False


class TestDistillEdgeCases:
    """Edge cases for session distillation."""

    def test_distill_with_large_message_count(self, mock_http_client):
        """Max messages parameter limits analysis."""
        client = mock_http_client

        # Create more messages than max_messages
        messages = [
            _make_message(f"m{i}", "sess1", "user", f"Message {i}")
            for i in range(50)
        ]

        with patch.object(client, "_query") as mock_query:
            mock_query.side_effect = [
                [_make_session()],  # session
                messages,            # messages (50)
                [],                  # memories
                [],                  # participants
            ]
            with patch.object(client, "_llm_complete",
                              return_value="Summary."):
                result = client.distill_session(
                    workspace_id="ws1",
                    session_id="sess1",
                    max_messages=10,
                )
                # The mixin limits to max_messages, so message_count reflects processed count
                assert result["message_count"] == 10
                assert "summary" in result

    def test_temporal_graph_max_events(self, mock_http_client):
        """Max events parameter limits extraction."""
        client = mock_http_client
        messages = [
            _make_message(f"m{i}", "sess1", "user",
                          "We decided X." if i % 2 == 0 else "TODO: Y")
            for i in range(20)
        ]

        with patch.object(client, "_query", return_value=messages):
            events = client.extract_temporal_graph(
                workspace_id="ws1",
                session_id="sess1",
                max_events=5,
            )
            assert len(events) <= 5

    def test_timeline_limit(self, mock_http_client):
        """Timeline limit parameter works."""
        client = mock_http_client
        messages = [
            _make_message(f"m{i}", "sess1", "user", f"Msg {i}")
            for i in range(50)
        ]

        with patch.object(client, "_query", return_value=messages):
            timeline = client.get_session_timeline(
                session_id="sess1",
                limit=10,
                include_events=False,
            )
            assert len(timeline) <= 10

    def test_search_with_limit(self, mock_http_client):
        """Search limit works for keyword strategy."""
        client = mock_http_client
        sessions = [
            _make_session(f"s{i}", "ws1", f"Session {i}")
            for i in range(20)
        ]

        with patch.object(client, "_query", return_value=sessions):
            results = client.search_session_strategies(
                query="Session",
                strategy="keyword",
                limit=5,
            )
            assert len(results) <= 5
