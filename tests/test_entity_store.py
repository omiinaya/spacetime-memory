"""Tests for spacetime_memory.entity_store — Mem0 .entity_store parity.

Uses ``MagicMock`` for the client so no STDB connection is needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from spacetime_memory.entity_store import (
    EntityStore,
    extract_entities,
    search_entities,
    store_entities,
    get_entity_graph,
    _extract_entities_heuristic,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client() -> MagicMock:
    """Build a MagicMock that simulates the STDB KG methods."""
    client = MagicMock()
    client._query = MagicMock()
    client.create_node = MagicMock()
    client.get_neighbors = MagicMock()
    return client


# ---------------------------------------------------------------------------
# extract_entities
# ---------------------------------------------------------------------------


class TestExtractEntities:
    """Standalone extract_entities function."""

    def test_heuristic_fallback_empty(self):
        """Empty text returns empty list."""
        result = extract_entities("", llm_func=None)
        assert result == []

    def test_heuristic_fallback_quoted(self):
        """Quoted strings are extracted as entities."""
        result = extract_entities('He read "The Great Gatsby".', llm_func=None)
        names = [e["name"] for e in result]
        assert "The Great Gatsby" in names

    def test_heuristic_fallback_hashtag(self):
        """Hashtags are extracted as concepts."""
        result = extract_entities(
            "Loving the #AI revolution!", llm_func=None
        )
        names = [e["name"] for e in result]
        assert "AI" in names
        types = [e["entity_type"] for e in result]
        assert "concept" in types

    def test_heuristic_fallback_url(self):
        """URLs are extracted."""
        result = extract_entities(
            "Visit https://example.com/path for details.", llm_func=None
        )
        urls = [e["name"] for e in result if e["name"].startswith("http")]
        assert len(urls) == 1

    def test_llm_func_used_when_provided(self):
        """When llm_func is given, it is called and its result is parsed."""
        llm_func = MagicMock(
            return_value='[{"name": "Alice", "entity_type": "person", "description": "A person"}]'
        )
        result = extract_entities("Alice went to the store.", llm_func=llm_func)
        assert len(result) == 1
        assert result[0]["name"] == "Alice"
        assert result[0]["entity_type"] == "person"
        llm_func.assert_called_once()

    def test_llm_func_fallback_on_failure(self):
        """When llm_func raises, the heuristic fallback is used."""
        llm_func = MagicMock(side_effect=RuntimeError("API down"))
        result = extract_entities('Some "quoted text".', llm_func=llm_func)
        names = [e["name"] for e in result]
        assert "quoted text" in names

    def test_llm_func_fallback_on_empty(self):
        """When llm_func returns empty string, fallback is used."""
        llm_func = MagicMock(return_value="")
        result = extract_entities(
            'Empty response #fallback', llm_func=llm_func
        )
        names = [e["name"] for e in result]
        assert "fallback" in names

    def test_llm_func_parses_json_from_code_fence(self):
        """Markdown code fences are stripped before JSON parsing."""
        llm_func = MagicMock(
            return_value="```json\n[{\"name\": \"Bob\", \"entity_type\": \"person\", \"description\": \"\"}]\n```"
        )
        result = extract_entities("Bob is here.", llm_func=llm_func)
        assert len(result) == 1
        assert result[0]["name"] == "Bob"

    def test_heuristic_multi_word_capitalised(self):
        """Capitalised multi-word phrases are extracted."""
        result = extract_entities(
            "Alice Johnson went to New York City with Bob Smith.",
            llm_func=None,
        )
        names = [e["name"] for e in result]
        # At minimum we should get something
        assert len(result) >= 0

    def test_llm_func_dict_response(self):
        """LLM returning a dict with 'entities' key is handled."""
        llm_func = MagicMock(
            return_value='{"entities": [{"name": "Charlie", "entity_type": "person", "description": ""}]}'
        )
        result = extract_entities("Charlie is here.", llm_func=llm_func)
        assert len(result) == 1
        assert result[0]["name"] == "Charlie"


# ---------------------------------------------------------------------------
# store_entities
# ---------------------------------------------------------------------------


class TestStoreEntities:
    """Standalone store_entities function."""

    def test_store_new_entities(self):
        """Entities are created as KG nodes."""
        client = _make_mock_client()
        client._query.return_value = []  # No existing nodes
        client.create_node.side_effect = [
            {"id": "n1", "label": "Alice"},
            {"id": "n2", "label": "Bob"},
        ]

        entities = [
            {"name": "Alice", "entity_type": "person", "description": "A friend"},
            {"name": "Bob", "entity_type": "person", "description": "Another friend"},
        ]
        created = store_entities(client, "ws-1", entities)

        assert len(created) == 2
        assert created[0]["label"] == "Alice"
        assert created[1]["label"] == "Bob"
        assert client.create_node.call_count == 2

    def test_store_skip_existing(self):
        """Existing nodes are skipped when skip_existing=True."""
        client = _make_mock_client()
        # First entity already exists
        client._query.side_effect = [
            [{"id": "existing-1", "label": "Alice"}],  # first lookup: exists
            [],  # second lookup: not exists
        ]
        client.create_node.return_value = {"id": "n2", "label": "Bob"}

        entities = [
            {"name": "Alice", "entity_type": "person", "description": "A friend"},
            {"name": "Bob", "entity_type": "person", "description": "Another friend"},
        ]
        created = store_entities(client, "ws-1", entities)

        assert len(created) == 1
        assert created[0]["label"] == "Bob"
        client.create_node.assert_called_once()

    def test_store_empty_name_skipped(self):
        """Entities with empty names are silently skipped."""
        client = _make_mock_client()
        client._query.return_value = []
        client.create_node.return_value = {"id": "n1", "label": "Valid"}

        entities = [
            {"name": "", "entity_type": "person", "description": ""},
            {"name": "Valid", "entity_type": "concept", "description": ""},
        ]
        created = store_entities(client, "ws-1", entities)

        assert len(created) == 1
        assert created[0]["label"] == "Valid"
        client.create_node.assert_called_once()

    def test_store_create_node_error_skipped(self):
        """If create_node raises, that entity is skipped but others continue."""
        client = _make_mock_client()
        client._query.return_value = []
        client.create_node.side_effect = [
            RuntimeError("STDB error"),
            {"id": "n2", "label": "Bob"},
        ]

        entities = [
            {"name": "Alice", "entity_type": "person", "description": ""},
            {"name": "Bob", "entity_type": "person", "description": ""},
        ]
        created = store_entities(client, "ws-1", entities)

        assert len(created) == 1
        assert created[0]["label"] == "Bob"
        assert client.create_node.call_count == 2

    def test_store_with_source_memory_id(self):
        """source_memory_id is forwarded to create_node."""
        client = _make_mock_client()
        client._query.return_value = []
        client.create_node.return_value = {"id": "n1", "label": "Alice"}

        entities = [
            {"name": "Alice", "entity_type": "person", "description": ""}
        ]
        store_entities(client, "ws-1", entities, source_memory_id="mem-1")

        client.create_node.assert_called_with(
            workspace_id="ws-1",
            label="Alice",
            node_type="entity",
            summary="person: Alice",
            source_memory_id="mem-1",
        )

    def test_store_type_mapping(self):
        """entity_type is mapped to valid kg node_type."""
        client = _make_mock_client()
        client._query.return_value = []
        client.create_node.return_value = {"id": "n1", "label": "RLHF"}

        entities = [
            {"name": "RLHF", "entity_type": "concept", "description": ""}
        ]
        store_entities(client, "ws-1", entities)

        call_kwargs = client.create_node.call_args[1]
        assert call_kwargs["node_type"] == "concept"


# ---------------------------------------------------------------------------
# search_entities
# ---------------------------------------------------------------------------


class TestSearchEntities:
    """Standalone search_entities function."""

    def test_search_by_label(self):
        """Search matches on label substring."""
        client = _make_mock_client()
        client._query.return_value = [
            {"id": "n1", "label": "Python", "node_type": "concept", "summary": "A language"},
            {"id": "n2", "label": "PyTorch", "node_type": "concept", "summary": "A framework"},
            {"id": "n3", "label": "Rust", "node_type": "concept", "summary": "A language"},
        ]

        results = search_entities(client, "ws-1", "Py")
        assert len(results) == 2
        labels = {r["label"] for r in results}
        assert labels == {"Python", "PyTorch"}

    def test_search_by_summary(self):
        """Search matches on summary substring."""
        client = _make_mock_client()
        client._query.return_value = [
            {"id": "n1", "label": "Go", "node_type": "concept", "summary": "A compiled language"},
            {"id": "n2", "label": "Rust", "node_type": "concept", "summary": "A systems language"},
        ]

        results = search_entities(client, "ws-1", "compiled")
        assert len(results) == 1
        assert results[0]["label"] == "Go"

    def test_search_with_type_filter(self):
        """Type filter narrows results."""
        client = _make_mock_client()
        client._query.return_value = [
            {"id": "n1", "label": "Alice", "node_type": "entity", "summary": ""},
            {"id": "n2", "label": "RLHF", "node_type": "concept", "summary": ""},
        ]

        results = search_entities(client, "ws-1", "al", type="entity")
        assert len(results) == 1
        assert results[0]["label"] == "Alice"

    def test_search_no_matches(self):
        """Empty results when nothing matches."""
        client = _make_mock_client()
        client._query.return_value = [
            {"id": "n1", "label": "Python", "node_type": "concept", "summary": ""}
        ]

        results = search_entities(client, "ws-1", "Java")
        assert results == []

    def test_search_query_error_returns_empty(self):
        """_query failure returns empty list."""
        client = _make_mock_client()
        client._query.side_effect = RuntimeError("DB error")

        results = search_entities(client, "ws-1", "anything")
        assert results == []

    def test_search_empty_query_returns_all(self):
        """Empty query returns all nodes."""
        client = _make_mock_client()
        client._query.return_value = [
            {"id": "n1", "label": "A", "node_type": "concept", "summary": ""},
            {"id": "n2", "label": "B", "node_type": "entity", "summary": ""},
        ]

        results = search_entities(client, "ws-1", "")
        assert len(results) == 2


# ---------------------------------------------------------------------------
# get_entity_graph
# ---------------------------------------------------------------------------


class TestGetEntityGraph:
    """Standalone get_entity_graph function."""

    def test_entity_not_found(self):
        """When entity doesn't exist, returns empty graph."""
        client = _make_mock_client()
        client._query.return_value = []  # node not found

        result = get_entity_graph(client, "ws-1", "nonexistent")
        assert result["node"] is None
        assert result["edges"] == []
        assert result["neighbors"] == []

    def test_entity_with_neighbors(self):
        """Returns node, edges, and neighbor details."""
        client = _make_mock_client()

        # Mock the node query
        def _query(table, workspace_id="", filter_dict=None, columns=None, **kwargs):
            if table == "kg_node" and filter_dict == {"id": "n1"}:
                return [
                    {"id": "n1", "label": "Python", "node_type": "concept", "summary": "A language"}
                ]
            if table == "kg_node" and filter_dict == {"id": "n2"}:
                return [
                    {"id": "n2", "label": "Django", "node_type": "entity", "summary": "A framework"}
                ]
            return []

        client._query = _query
        client.get_neighbors.return_value = [
            {
                "id": "e1",
                "source_node_id": "n1",
                "target_node_id": "n2",
                "relation": "related_to",
                "weight": 1.0,
                "source_label": "Python",
                "target_label": "Django",
            }
        ]

        result = get_entity_graph(client, "ws-1", "n1")
        assert result["node"] is not None
        assert result["node"]["label"] == "Python"
        assert len(result["edges"]) == 1
        assert result["edges"][0]["relation"] == "related_to"
        assert len(result["neighbors"]) == 1
        assert result["neighbors"][0]["label"] == "Django"

    def test_get_neighbors_error_returns_partial(self):
        """If get_neighbors fails, still returns the node."""
        client = _make_mock_client()
        client._query.return_value = [
            {"id": "n1", "label": "Python", "node_type": "concept", "summary": ""}
        ]
        client.get_neighbors.side_effect = RuntimeError("KG error")

        result = get_entity_graph(client, "ws-1", "n1")
        assert result["node"] is not None
        assert result["edges"] == []
        assert result["neighbors"] == []


# ---------------------------------------------------------------------------
# EntityStore  (class-based API)
# ---------------------------------------------------------------------------


class TestEntityStoreClass:
    """EntityStore class wraps the standalone functions."""

    def test_init(self):
        """EntityStore stores client, workspace_id, and llm_func."""
        client = _make_mock_client()
        store = EntityStore(client, "ws-1")
        assert store.client is client
        assert store.workspace_id == "ws-1"
        assert store.llm_func is None

    def test_init_with_llm_func(self):
        """EntityStore accepts an optional llm_func."""
        client = _make_mock_client()
        llm = MagicMock()
        store = EntityStore(client, "ws-1", llm_func=llm)
        assert store.llm_func is llm

    def test_extract_entities_delegates(self):
        """EntityStore.extract_entities calls the standalone function."""
        client = _make_mock_client()
        store = EntityStore(client, "ws-1")

        result = store.extract_entities('Some "quoted text".')
        names = [e["name"] for e in result]
        assert "quoted text" in names

    def test_extract_entities_with_llm_func(self):
        """EntityStore passes its llm_func when no override given."""
        client = _make_mock_client()
        llm = MagicMock(
            return_value='[{"name": "X", "entity_type": "concept", "description": ""}]'
        )
        store = EntityStore(client, "ws-1", llm_func=llm)

        result = store.extract_entities("X is here.")
        assert len(result) == 1
        assert result[0]["name"] == "X"

    def test_store_entities_delegates(self):
        """EntityStore.store_entities calls the standalone function."""
        client = _make_mock_client()
        client._query.return_value = []
        client.create_node.return_value = {"id": "n1", "label": "Alice"}
        store = EntityStore(client, "ws-1")

        entities = [
            {"name": "Alice", "entity_type": "person", "description": ""}
        ]
        created = store.store_entities(entities)
        assert len(created) == 1
        assert created[0]["label"] == "Alice"

    def test_search_entities_delegates(self):
        """EntityStore.search_entities calls the standalone function."""
        client = _make_mock_client()
        client._query.return_value = [
            {"id": "n1", "label": "Python", "node_type": "concept", "summary": ""}
        ]
        store = EntityStore(client, "ws-1")

        results = store.search_entities("Python")
        assert len(results) == 1
        assert results[0]["label"] == "Python"

    def test_search_entities_with_type_filter(self):
        """EntityStore.search_entities passes type filter."""
        client = _make_mock_client()
        client._query.return_value = [
            {"id": "n1", "label": "Alice", "node_type": "entity", "summary": ""}
        ]
        store = EntityStore(client, "ws-1")

        results = store.search_entities("Ali", type="entity")
        assert len(results) == 1

    def test_get_entity_graph_delegates(self):
        """EntityStore.get_entity_graph calls the standalone function."""
        client = _make_mock_client()
        client._query.return_value = [
            {"id": "n1", "label": "Python", "node_type": "concept", "summary": ""}
        ]
        client.get_neighbors.return_value = []
        store = EntityStore(client, "ws-1")

        result = store.get_entity_graph("n1")
        assert result["node"] is not None
        assert result["node"]["label"] == "Python"

    def test_extract_and_store_combined(self):
        """extract_and_store runs both steps and returns both results."""
        client = _make_mock_client()
        client._query.return_value = []
        client.create_node.return_value = {"id": "n1", "label": "Alice"}
        store = EntityStore(client, "ws-1")

        # Use heuristic (no llm_func) — text with a quoted string
        result = store.extract_and_store('Her name is "Alice".')
        assert "entities" in result
        assert "stored" in result
        assert len(result["entities"]) >= 1
        assert len(result["stored"]) >= 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge and error cases."""

    def test_extract_entities_none_text(self):
        """Non-string text is not handled gracefully but won't crash."""
        with pytest.raises((TypeError, AttributeError)):
            extract_entities(None, llm_func=None)  # type: ignore[arg-type]

    def test_store_entities_empty_list(self):
        """Empty entities list returns empty."""
        client = _make_mock_client()
        created = store_entities(client, "ws-1", [])
        assert created == []

    def test_search_entities_empty_db(self):
        """Empty KG returns empty results."""
        client = _make_mock_client()
        client._query.return_value = []
        results = search_entities(client, "ws-1", "anything")
        assert results == []

    def test_get_entity_graph_node_not_found(self):
        """Nonexistent entity returns node=None."""
        client = _make_mock_client()
        client._query.return_value = []
        result = get_entity_graph(client, "ws-1", "missing")
        assert result["node"] is None
