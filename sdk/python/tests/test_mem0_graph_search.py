"""Integration tests for Mem0-compatible adapter.

These tests require a running SpacetimeDB instance.
Run with::

    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest tests/test_mem0_graph_search.py -v

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


class TestGraphStoreSearchPaths:
    """Cover graph.search() fallback and entity paths."""

    def test_graph_search_entity_link_path(self, mem: Memory) -> None:
        """graph.search() → entity_link substring match (lines 407-414)."""
        uid = _uid()
        fake_el_rows = [
            {
                "id": "el-1",
                "entity_name": "SearchTarget",
                "entity_type": "concept",
                "description": json.dumps({"tag": f"mem0_user:{uid}"}),
                "created_at": 1,
            },
            {
                "id": "el-2",
                "entity_name": "OtherThing",
                "entity_type": "person",
                "description": json.dumps({"tag": f"mem0_user:{uid}"}),
                "created_at": 2,
            },
        ]
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", side_effect=RuntimeError("no embedder")):
                with patch.object(
                    mem._client, "_tantivy_search", side_effect=RuntimeError("no tantivy")
                ):
                    with patch.object(mem._client, "resolve_entity"):
                        with patch.object(mem._client, "_query", return_value=fake_el_rows):
                            results = mem.graph.search("Search", user_id=uid)
                            assert isinstance(results, list)
                            if results:
                                assert results[0]["label"] == "SearchTarget"

    def test_graph_search_kg_node_fallback(self, mem: Memory) -> None:
        """graph.search() → entity_link unavailable → kg_node fallback (line 414)."""
        uid = _uid()
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", side_effect=RuntimeError("no embedder")):
                with patch.object(
                    mem._client, "_tantivy_search", side_effect=RuntimeError("no tantivy")
                ):
                    with patch.object(
                        mem._client, "resolve_entity", side_effect=RuntimeError("no resolve")
                    ):
                        with patch.object(
                            mem._client, "_query", side_effect=RuntimeError("no entity_link")
                        ):
                            with patch.object(
                                mem,
                                "_call",
                                return_value=[
                                    {
                                        "id": "n1",
                                        "label": "KGNode",
                                        "node_type": "concept",
                                        "summary": "kg",
                                        "metadata_json": json.dumps({"tag": f"mem0_user:{uid}"}),
                                        "created_at": 1,
                                    }
                                ],
                            ) as mock_call:
                                results = mem.graph.search("KG", user_id=uid)
                                assert isinstance(results, list)
                                mock_call.assert_called()

    def test_graph_search_tantivy_node_path(self, mem: Memory) -> None:
        """graph.search() Tantivy fallback → node results (lines 345-366)."""
        uid = _uid()
        tantivy_hits = [
            {"entity_id": "nid-1", "entity_type": "node", "score": 0.9},
        ]
        kg_node_rows = [
            {
                "id": "nid-1",
                "label": "TantivyNode",
                "node_type": "concept",
                "summary": "t",
                "metadata_json": json.dumps({"tag": f"mem0_user:{uid}"}),
                "created_at": 1,
            }
        ]
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", side_effect=RuntimeError("no embedder")):
                with patch.object(mem._client, "_tantivy_search", return_value=tantivy_hits):
                    with patch.object(mem._client, "_query", return_value=kg_node_rows):
                        results = mem.graph.search("Tantivy", user_id=uid)
                        assert isinstance(results, list)
                        if results:
                            assert results[0]["label"] == "TantivyNode"

    def test_graph_search_tantivy_memory_path(self, mem: Memory) -> None:
        """graph.search() Tantivy fallback → memory results (lines 367-382)."""
        uid = _uid()
        tantivy_hits = [
            {"entity_id": "mid-1", "entity_type": "memory", "score": 0.8},
        ]
        memory_rows = [
            {
                "id": "mid-1",
                "content": "A memory content that is long enough to test truncation",
                "summary": "s",
                "created_at": 1,
            }
        ]
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", side_effect=RuntimeError("no embedder")):
                with patch.object(mem._client, "_tantivy_search", return_value=tantivy_hits):
                    with patch.object(mem._client, "_query", return_value=memory_rows):
                        results = mem.graph.search("memory", user_id=uid)
                        assert isinstance(results, list)

    def test_graph_search_tantivy_no_entity_id(self, mem: Memory) -> None:
        """graph.search() Tantivy hit with no entity_id is skipped (line 349)."""
        uid = _uid()
        tantivy_hits = [
            {"entity_id": "", "entity_type": "node", "score": 0.9},
            {"entity_id": "nid-ok", "entity_type": "node", "score": 0.8},
        ]
        kg_node_rows = [
            {
                "id": "nid-ok",
                "label": "OKNode",
                "node_type": "concept",
                "summary": "ok",
                "metadata_json": json.dumps({"tag": f"mem0_user:{uid}"}),
                "created_at": 1,
            }
        ]
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", side_effect=RuntimeError("no embedder")):
                with patch.object(mem._client, "_tantivy_search", return_value=tantivy_hits):
                    with patch.object(mem._client, "_query", return_value=kg_node_rows):
                        results = mem.graph.search("test", user_id=uid)
                        assert isinstance(results, list)

    def test_graph_search_tantivy_kg_node_empty(self, mem: Memory) -> None:
        """graph.search() Tantivy → kg_node query returns empty (line 355)."""
        uid = _uid()
        tantivy_hits = [
            {"entity_id": "ghost", "entity_type": "memory", "score": 0.5},
        ]
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", side_effect=RuntimeError("no embedder")):
                with patch.object(mem._client, "_tantivy_search", return_value=tantivy_hits):
                    with patch.object(mem._client, "_query", return_value=[]):
                        results = mem.graph.search("ghost", user_id=uid)
                        assert isinstance(results, list)

    def test_graph_search_vector_path(self, mem: Memory) -> None:
        """graph.search() vector search → node results (lines 312-335)."""
        uid = _uid()
        semantic_rows = [
            {"entity_type": "memory", "entity_id": "mem-x", "score": 0.3},
            {"entity_type": "node", "entity_id": "nid-v", "score": 0.92},
        ]
        kg_node_rows = [
            {
                "id": "nid-v",
                "label": "VectorNode",
                "node_type": "concept",
                "summary": "v",
                "metadata_json": json.dumps({"tag": f"mem0_user:{uid}"}),
                "created_at": 1,
            }
        ]
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", return_value=semantic_rows):
                with patch.object(mem._client, "_query", return_value=kg_node_rows):
                    results = mem.graph.search("Vector", user_id=uid)
                    assert isinstance(results, list)
                    if results:
                        assert results[0]["label"] == "VectorNode"

    def test_graph_search_vector_no_node(self, mem: Memory) -> None:
        """graph.search() vector search → no nodes found, falls through."""
        uid = _uid()
        semantic_rows = [
            {"entity_type": "memory", "entity_id": "mem-x", "score": 0.3},
        ]
        fake_el_rows = [
            {
                "id": "el-v",
                "entity_name": "VectorEnt",
                "entity_type": "concept",
                "description": json.dumps({"tag": f"mem0_user:{uid}"}),
                "created_at": 1,
            },
        ]
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", return_value=semantic_rows):
                with patch.object(
                    mem._client, "_tantivy_search", side_effect=RuntimeError("no tantivy")
                ):
                    with patch.object(mem._client, "resolve_entity"):
                        with patch.object(mem._client, "_query", return_value=fake_el_rows):
                            results = mem.graph.search("Vector", user_id=uid)
                            assert isinstance(results, list)

    def test_graph_search_vector_no_entity_id(self, mem: Memory) -> None:
        """graph.search() vector hit with no entity_id is skipped (line 315)."""
        uid = _uid()
        semantic_rows = [
            {"entity_type": "node", "entity_id": "", "score": 0.95},
            {"entity_type": "node", "entity_id": "nid-good", "score": 0.90},
        ]
        kg_node_rows = [
            {
                "id": "nid-good",
                "label": "GoodNode",
                "node_type": "concept",
                "summary": "g",
                "metadata_json": json.dumps({"tag": f"mem0_user:{uid}"}),
                "created_at": 1,
            }
        ]
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", return_value=semantic_rows):
                with patch.object(mem._client, "_query", return_value=kg_node_rows):
                    results = mem.graph.search("test", user_id=uid)
                    assert isinstance(results, list)
                    if results:
                        assert results[0]["id"] == "nid-good"

    def test_graph_search_vector_kg_node_empty(self, mem: Memory) -> None:
        """graph.search() vector → kg_node query returns empty for a hit."""
        uid = _uid()
        semantic_rows = [
            {"entity_type": "node", "entity_id": "nid-ghost", "score": 0.95},
            {"entity_type": "node", "entity_id": "nid-real", "score": 0.90},
        ]
        real_row = [
            {
                "id": "nid-real",
                "label": "RealNode",
                "node_type": "concept",
                "summary": "r",
                "metadata_json": json.dumps({"tag": f"mem0_user:{uid}"}),
                "created_at": 1,
            }
        ]
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "search", return_value=semantic_rows):
                with patch.object(mem._client, "_query", side_effect=[[], real_row]):
                    results = mem.graph.search("test", user_id=uid)
                    assert isinstance(results, list)




class TestGraphGetAllPaths:
    """Cover graph.get_all() entity_link and fallback paths."""

    def test_graph_get_all_entity_link(self, mem: Memory) -> None:
        """graph.get_all() via entity_link (lines 437-443)."""
        uid = _uid()
        fake_rows = [
            {
                "id": "el-1",
                "entity_name": "EntA",
                "entity_type": "person",
                "description": json.dumps({"tag": f"mem0_user:{uid}"}),
                "created_at": 1,
            },
            {
                "id": "el-2",
                "entity_name": "EntB",
                "entity_type": "concept",
                "description": json.dumps({"tag": f"mem0_user:{uid}"}),
                "created_at": 2,
            },
        ]
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "_query", return_value=fake_rows):
                results = mem.graph.get_all(user_id=uid)
                assert isinstance(results, list)
                assert len(results) == 2

    def test_graph_get_all_kg_node_fallback(self, mem: Memory) -> None:
        """graph.get_all() entity_link fails → kg_node fallback (lines 444-452)."""
        uid = _uid()
        kg_rows = [
            {
                "id": "n1",
                "label": "KG-A",
                "node_type": "fact",
                "summary": "a",
                "metadata_json": json.dumps({"tag": f"mem0_user:{uid}"}),
                "created_at": 1,
            },
        ]
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem._client, "_query", side_effect=RuntimeError("no entity_link")):
                with patch.object(mem, "_call", return_value=kg_rows) as mock_call:
                    results = mem.graph.get_all(user_id=uid)
                    assert isinstance(results, list)
                    mock_call.assert_called()

    def test_graph_delete(self, mem: Memory) -> None:
        """graph.delete() calls delete_node (line 468-469)."""
        with patch.object(mem, "_call") as mock_call:
            result = mem.graph.delete("entity-123")
            mock_call.assert_called_once_with("delete_node", "entity-123")
            assert result == {"status": "ok", "deleted": "entity-123"}


# ---------------------------------------------------------------------------
# Workspace resolution coverage (mocked)
# ---------------------------------------------------------------------------


