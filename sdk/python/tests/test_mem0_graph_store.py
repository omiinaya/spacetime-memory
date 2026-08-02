"""Integration tests for Mem0-compatible adapter.

These tests require a running SpacetimeDB instance.
Run with::

    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest tests/test_mem0_graph_store.py -v

"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest
from mem0_shared import _uid

from spacetime_memory.sdks.mem0 import Memory

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("SPACETIMEDB_HOST"),
        reason="Integration tests require SPACETIMEDB_HOST env var",
    ),
]


class TestMem0GraphStore:
    """Tests for the Mem0 graph store (_GraphStore)."""

    def test_graph_add(self, mem: Memory) -> None:
        """graph.add() creates a graph entity."""
        uid = _uid()
        result = mem.graph.add("GraphTestEntity", entity_type="concept", user_id=uid)
        assert "id" in result or "status" in result

    def test_graph_add_empty_raises(self, mem: Memory) -> None:
        """graph.add() with empty text raises ValueError."""
        with pytest.raises(ValueError):
            mem.graph.add("  ", user_id=_uid())

    def test_graph_search(self, mem: Memory) -> None:
        """graph.search() returns entities."""
        uid = _uid()
        mem.graph.add("SearchEntity", entity_type="concept", user_id=uid)
        results = mem.graph.search("Search", user_id=uid)
        assert isinstance(results, list)

    def test_graph_get_all(self, mem: Memory) -> None:
        """graph.get_all() lists entities."""
        uid = _uid()
        mem.graph.add("ListAllEntity", entity_type="concept", user_id=uid)
        results = mem.graph.get_all(user_id=uid)
        assert isinstance(results, list)

    def test_graph_delete(self, mem: Memory) -> None:
        """graph.delete() deletes a graph entity."""
        uid = _uid()
        result = mem.graph.add("DeleteEntity", entity_type="concept", user_id=uid)
        entity_id = result.get("id", "")
        if entity_id:
            del_result = mem.graph.delete(entity_id)
            assert del_result["status"] == "ok"

    def test_graph_add_with_metadata(self, mem: Memory) -> None:
        """graph.add() with metadata."""
        uid = _uid()
        result = mem.graph.add(
            "MetaEntity",
            entity_type="person",
            user_id=uid,
            metadata={"source": "test", "importance": 5},
        )
        assert "id" in result or "status" in result

    def test_graph_add_with_agent_id(self, mem: Memory) -> None:
        """graph.add() with agent_id."""
        uid = _uid()
        result = mem.graph.add(
            "AgentScopedEntity",
            entity_type="concept",
            user_id=uid,
            agent_id="my-agent",
        )
        assert "id" in result or "status" in result

    def test_set_llm_config(self, mem: Memory) -> None:
        """set_llm_config stores per-user LLM config overrides."""
        uid = _uid()
        mem.set_llm_config(uid, {"model": "gpt-4", "api_key": "test-key"})
        # No error = success — just testing it doesn't raise

    def test_add_with_metadata_dict(self, mem: Memory) -> None:
        """add() with rich metadata dict."""
        uid = _uid()
        result = mem.add(
            "Metadata rich test",
            user_id=uid,
            metadata={"source": "conversation", "importance": 7, "tags": ["preference"]},
        )
        assert "results" in result
        assert len(result["results"]) >= 1


# ---------------------------------------------------------------------------
# Additional tests to push coverage to ≥70%
# ---------------------------------------------------------------------------




class TestGraphStoreEntityLinkPaths:
    """Cover entity_link / kg_node branches in graph store methods."""

    def test_graph_add_exact_entity_link(self, mem: Memory) -> None:
        """graph.add() via _add_exact → entity_link path (line 257)."""
        uid = _uid()
        fake_row = {
            "id": "el-123",
            "entity_name": "TestEnt",
            "entity_type": "person",
            "description": json.dumps({"tag": f"mem0_user:{uid}"}),
            "created_at": 1234567890,
        }
        # Mock client to avoid vector dedup (semantic search raises) and use entity_link
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", side_effect=RuntimeError("no embedder")):
                with patch.object(mem._client, "create_entity_link"):
                    with patch.object(mem._client, "_query", return_value=[fake_row]):
                        result = mem.graph.add("TestEnt", entity_type="person", user_id=uid)
                        assert "id" in result
                        assert result["label"] == "TestEnt"

    def test_graph_add_exact_entity_link_no_rows(self, mem: Memory) -> None:
        """graph.add() via _add_exact → entity_link with no query results."""
        uid = _uid()
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", side_effect=RuntimeError("no embedder")):
                with patch.object(mem._client, "create_entity_link"):
                    with patch.object(mem._client, "_query", return_value=[]):
                        result = mem.graph.add("GhostEnt", entity_type="concept", user_id=uid)
                        assert result["status"] == "ok"

    def test_graph_add_exact_kg_node_fallback(self, mem: Memory) -> None:
        """graph.add() via _add_exact → entity_link fails → kg_node fallback (lines 259-272)."""
        uid = _uid()
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", side_effect=RuntimeError("no embedder")):
                with patch.object(
                    mem._client, "create_entity_link", side_effect=RuntimeError("no table")
                ):
                    with patch.object(
                        mem, "_call", return_value={"id": "node-456", "label": "FallbackEnt"}
                    ) as mock_call:
                        result = mem.graph.add("FallbackEnt", entity_type="concept", user_id=uid)
                        mock_call.assert_called()
                        assert "id" in result or "status" in result

    def test_graph_add_kg_node_fallback_non_dict_result(self, mem: Memory) -> None:
        """kg_node fallback returns non-dict result (line 272)."""
        uid = _uid()
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", side_effect=RuntimeError("no embedder")):
                with patch.object(
                    mem._client, "create_entity_link", side_effect=RuntimeError("no table")
                ):
                    with patch.object(mem, "_call", return_value="node-id-string"):
                        result = mem.graph.add("StrResult", entity_type="concept", user_id=uid)
                        assert result["status"] == "ok"
                        assert result["id"] == "node-id-string"

    def test_graph_add_vector_dedup_path(self, mem: Memory) -> None:
        """graph.add() vector dedup path (lines 191-230) — matches existing entity."""
        uid = _uid()
        fake_semantic = [
            {"entity_type": "node", "entity_id": "node-abc", "score": 0.95},
            {"entity_type": "memory", "entity_id": "mem-xyz", "score": 0.5},
        ]
        fake_kg_node = [
            {
                "id": "node-abc",
                "label": "ExistingLabel",
                "node_type": "person",
                "summary": "Existing summary",
                "metadata_json": '{"tag": "mem0_global"}',
                "created_at": 1000000,
            }
        ]
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", return_value=fake_semantic):
                with patch.object(mem._client, "_query", side_effect=[fake_kg_node, []]):
                    with patch.object(mem._client, "add_alias"):
                        result = mem.graph.add("ExistingLabel", entity_type="person", user_id=uid)
                        assert result["merged"] is True
                        assert result["label"] == "ExistingLabel"

    def test_graph_add_vector_dedup_below_threshold(self, mem: Memory) -> None:
        """graph.add() vector dedup — score below 0.85 skips (line 192)."""
        uid = _uid()
        fake_semantic = [
            {"entity_type": "node", "entity_id": "node-low", "score": 0.3},
        ]
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", return_value=fake_semantic):
                with patch.object(mem._client, "create_entity_link"):
                    with patch.object(
                        mem._client,
                        "_query",
                        return_value=[
                            {
                                "id": "el-new",
                                "entity_name": "NewEnt",
                                "entity_type": "concept",
                                "description": json.dumps({"tag": f"mem0_user:{uid}"}),
                                "created_at": 1,
                            }
                        ],
                    ):
                        result = mem.graph.add("NewEnt", entity_type="concept", user_id=uid)
                        assert result.get("merged") is not True

    def test_graph_add_vector_dedup_no_entity_id(self, mem: Memory) -> None:
        """graph.add() vector dedup — no entity_id skips (line 196)."""
        uid = _uid()
        fake_semantic = [
            {"entity_type": "node", "entity_id": "", "score": 0.95},
        ]
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", return_value=fake_semantic):
                with patch.object(mem._client, "create_entity_link"):
                    with patch.object(
                        mem._client,
                        "_query",
                        return_value=[
                            {
                                "id": "el-new",
                                "entity_name": "NoEID",
                                "entity_type": "concept",
                                "description": json.dumps({"tag": f"mem0_user:{uid}"}),
                                "created_at": 1,
                            }
                        ],
                    ):
                        result = mem.graph.add("NoEID", entity_type="concept", user_id=uid)
                        assert result.get("merged") is not True

    def test_graph_add_vector_dedup_with_entity_link_alias(self, mem: Memory) -> None:
        """graph.add() vector dedup — resolves entity_link and adds alias (lines 212-215)."""
        uid = _uid()
        fake_semantic = [
            {"entity_type": "node", "entity_id": "node-abc", "score": 0.95},
        ]
        fake_kg_node = [
            {
                "id": "node-abc",
                "label": "ExistingLabel",
                "node_type": "person",
                "summary": "Existing summary",
                "metadata_json": '{"tag": "mem0_global"}',
                "created_at": 1000000,
            }
        ]
        fake_el_rows = [{"id": "el-abc", "entity_name": "ExistingLabel"}]
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", return_value=fake_semantic):
                with patch.object(mem._client, "_query", side_effect=[fake_kg_node, fake_el_rows]):
                    with patch.object(mem._client, "add_alias") as mock_alias:
                        result = mem.graph.add("ExistingLabel", entity_type="person", user_id=uid)
                        assert result["merged"] is True
                        assert result["label"] == "ExistingLabel"
                        mock_alias.assert_called_once_with("el-abc", "ExistingLabel")

    def test_graph_add_vector_dedup_entity_link_runtime_error(self, mem: Memory) -> None:
        """graph.add() vector dedup — entity_link query raises RuntimeError (line 214-215)."""
        uid = _uid()
        fake_semantic = [
            {"entity_type": "node", "entity_id": "node-abc", "score": 0.95},
        ]
        fake_kg_node = [
            {
                "id": "node-abc",
                "label": "ExistingLabel",
                "node_type": "person",
                "summary": "Existing summary",
                "metadata_json": '{"tag": "mem0_global"}',
                "created_at": 1000000,
            }
        ]
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", return_value=fake_semantic):
                # entity_link query raises RuntimeError, caught gracefully
                with patch.object(
                    mem._client,
                    "_query",
                    side_effect=[fake_kg_node, RuntimeError("no entity_link")],
                ):
                    result = mem.graph.add("ExistingLabel", entity_type="person", user_id=uid)
                    assert result["merged"] is True
                    assert result["label"] == "ExistingLabel"

    def test_graph_add_vector_dedup_kg_node_empty(self, mem: Memory) -> None:
        """graph.add() vector dedup — kg_node query returns empty (line 202)."""
        uid = _uid()
        fake_semantic = [
            {"entity_type": "node", "entity_id": "node-ghost", "score": 0.95},
        ]
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", return_value=fake_semantic):
                with patch.object(
                    mem._client,
                    "_query",
                    side_effect=[
                        [],  # kg_node empty
                        [
                            {
                                "id": "el-new",
                                "entity_name": "GhostEnt",
                                "entity_type": "concept",
                                "description": json.dumps({"tag": f"mem0_user:{uid}"}),
                                "created_at": 1,
                            }
                        ],
                    ],
                ):
                    with patch.object(mem._client, "create_entity_link"):
                        result = mem.graph.add("GhostEnt", entity_type="concept", user_id=uid)
                        assert result.get("merged") is not True


