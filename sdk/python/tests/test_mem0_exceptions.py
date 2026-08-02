"""Integration tests for Mem0-compatible adapter.

These tests require a running SpacetimeDB instance.
Run with::

    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest tests/test_mem0_exceptions.py -v

"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from mem0_shared import _uid

from spacetime_memory import EmbedderUnavailableError
from spacetime_memory.sdks.mem0 import Memory

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("SPACETIMEDB_HOST"),
        reason="Integration tests require SPACETIMEDB_HOST env var",
    ),
]


class TestMem0ExceptionHandlers:
    """Test that API methods properly handle and wrap exceptions via mocking."""

    # ── add() exception handlers (lines 951-956) ─────────────────────────

    def test_add_handles_value_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, "store", side_effect=ValueError("test err")):
            with pytest.raises(ValueError, match="test err"):
                mem.add("test", user_id=uid, infer=False)

    def test_add_handles_runtime_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, "store", side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError, match="db down"):
                mem.add("test", user_id=uid, infer=False)

    def test_add_handles_embedder_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(
            mem._client, "store", side_effect=EmbedderUnavailableError("no embedder")
        ), pytest.raises(EmbedderUnavailableError, match="no embedder"):
            mem.add("test", user_id=uid, infer=False)

    def test_add_wraps_generic_exception(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, "store", side_effect=TypeError("boom")):
            with pytest.raises(RuntimeError, match=r"mem0\.add\(\) failed"):
                mem.add("test", user_id=uid, infer=False)

    # ── get() exception handlers (lines 990-997) ─────────────────────────

    def test_get_handles_value_error(self, mem: Memory) -> None:
        with patch.object(mem._client, "get_memory", side_effect=ValueError("test err")):
            with pytest.raises(ValueError, match="test err"):
                mem.get("fake-id")

    def test_get_handles_runtime_error(self, mem: Memory) -> None:
        with patch.object(mem._client, "get_memory", side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError, match="db down"):
                mem.get("fake-id")

    def test_get_handles_embedder_error(self, mem: Memory) -> None:
        with patch.object(
            mem._client, "get_memory", side_effect=EmbedderUnavailableError("no embedder")
        ), pytest.raises(EmbedderUnavailableError, match="no embedder"):
            mem.get("fake-id")

    def test_get_wraps_generic_exception(self, mem: Memory) -> None:
        with patch.object(mem._client, "get_memory", side_effect=TypeError("boom")):
            with pytest.raises(RuntimeError, match=r"mem0\.get\('fake-id'\) failed"):
                mem.get("fake-id")

    # ── search() exception handlers (lines 1105-1112) ────────────────────

    def test_search_handles_value_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, "search", side_effect=ValueError("test err")):
            with pytest.raises(ValueError, match="test err"):
                mem.search("test", user_id=uid, graph_context=False)

    def test_search_handles_runtime_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, "search", side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError, match="db down"):
                mem.search("test", user_id=uid, graph_context=False)

    def test_search_handles_embedder_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(
            mem._client, "search", side_effect=EmbedderUnavailableError("no embedder")
        ), pytest.raises(EmbedderUnavailableError, match="no embedder"):
            mem.search("test", user_id=uid, graph_context=False)

    def test_search_wraps_generic_exception(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, "search", side_effect=TypeError("boom")):
            with pytest.raises(RuntimeError, match=r"mem0\.search\('test'\) failed"):
                mem.search("test", user_id=uid, graph_context=False)

    # ── get_all() exception handlers (lines 1183-1190) ───────────────────

    def test_get_all_handles_value_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, "list_memories", side_effect=ValueError("test err")):
            with pytest.raises(ValueError, match="test err"):
                mem.get_all(user_id=uid)

    def test_get_all_handles_runtime_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, "list_memories", side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError, match="db down"):
                mem.get_all(user_id=uid)

    def test_get_all_handles_embedder_error(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(
            mem._client, "list_memories", side_effect=EmbedderUnavailableError("no embedder")
        ), pytest.raises(EmbedderUnavailableError, match="no embedder"):
            mem.get_all(user_id=uid)

    def test_get_all_wraps_generic_exception(self, mem: Memory) -> None:
        uid = _uid()
        with patch.object(mem._client, "list_memories", side_effect=TypeError("boom")):
            with pytest.raises(RuntimeError, match=r"mem0\.get_all\(user_id="):
                mem.get_all(user_id=uid)

    # ── update() exception handlers (lines 1227-1232) ────────────────────

    def test_update_handles_value_error(self, mem: Memory) -> None:
        with patch.object(mem._client, "update_memory", side_effect=ValueError("test err")):
            with pytest.raises(ValueError, match="test err"):
                mem.update("fake-id", "content")

    def test_update_handles_runtime_error(self, mem: Memory) -> None:
        with patch.object(mem._client, "update_memory", side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError, match="db down"):
                mem.update("fake-id", "content")

    def test_update_handles_embedder_error(self, mem: Memory) -> None:
        with patch.object(
            mem._client, "update_memory", side_effect=EmbedderUnavailableError("no embedder")
        ), pytest.raises(EmbedderUnavailableError, match="no embedder"):
            mem.update("fake-id", "content")

    def test_update_wraps_generic_exception(self, mem: Memory) -> None:
        with patch.object(mem._client, "update_memory", side_effect=TypeError("boom")):
            with pytest.raises(RuntimeError, match=r"mem0\.update\('fake-id'\) failed"):
                mem.update("fake-id", "content")

    # ── delete() exception handlers (lines 1252-1259) ────────────────────

    def test_delete_handles_value_error(self, mem: Memory) -> None:
        with patch.object(mem._client, "delete_memory", side_effect=ValueError("test err")):
            with pytest.raises(ValueError, match="test err"):
                mem.delete("fake-id")

    def test_delete_handles_runtime_error(self, mem: Memory) -> None:
        with patch.object(mem._client, "delete_memory", side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError, match="db down"):
                mem.delete("fake-id")

    def test_delete_handles_embedder_error(self, mem: Memory) -> None:
        with patch.object(
            mem._client, "delete_memory", side_effect=EmbedderUnavailableError("no embedder")
        ), pytest.raises(EmbedderUnavailableError, match="no embedder"):
            mem.delete("fake-id")

    def test_delete_wraps_generic_exception(self, mem: Memory) -> None:
        with patch.object(mem._client, "delete_memory", side_effect=TypeError("boom")):
            with pytest.raises(RuntimeError, match=r"mem0\.delete\('fake-id'\) failed"):
                mem.delete("fake-id")

    # ── delete_all() exception handlers (lines 1296-1303) ────────────────

    def test_delete_all_handles_value_error(self, mem: Memory) -> None:
        uid = _uid()
        # Add a memory first so get_all returns results, then delete_memory raises
        mem.add("to delete", user_id=uid)
        with patch.object(mem._client, "delete_memory", side_effect=ValueError("test err")):
            with pytest.raises(ValueError, match="test err"):
                mem.delete_all(user_id=uid)

    def test_delete_all_handles_runtime_error(self, mem: Memory) -> None:
        uid = _uid()
        mem.add("to delete", user_id=uid)
        with patch.object(mem._client, "delete_memory", side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError, match="db down"):
                mem.delete_all(user_id=uid)

    def test_delete_all_handles_embedder_error(self, mem: Memory) -> None:
        uid = _uid()
        mem.add("to delete", user_id=uid)
        with patch.object(
            mem._client, "delete_memory", side_effect=EmbedderUnavailableError("no embedder")
        ), pytest.raises(EmbedderUnavailableError, match="no embedder"):
            mem.delete_all(user_id=uid)

    def test_delete_all_wraps_generic_exception(self, mem: Memory) -> None:
        uid = _uid()
        mem.add("to delete", user_id=uid)
        with patch.object(mem._client, "delete_memory", side_effect=TypeError("boom")):
            with pytest.raises(RuntimeError, match=r"mem0\.delete_all\(user_id="):
                mem.delete_all(user_id=uid)

    # ── history() exception handlers (lines 1325-1332) ───────────────────

    def test_history_handles_value_error(self, mem: Memory) -> None:
        with patch.object(mem._client, "get_memory_history", side_effect=ValueError("test err")):
            with pytest.raises(ValueError, match="test err"):
                mem.history("fake-id")

    def test_history_handles_runtime_error(self, mem: Memory) -> None:
        with patch.object(mem._client, "get_memory_history", side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError, match="db down"):
                mem.history("fake-id")

    def test_history_handles_embedder_error(self, mem: Memory) -> None:
        with patch.object(
            mem._client, "get_memory_history", side_effect=EmbedderUnavailableError("no embedder")
        ), pytest.raises(EmbedderUnavailableError, match="no embedder"):
            mem.history("fake-id")

    def test_history_wraps_generic_exception(self, mem: Memory) -> None:
        with patch.object(mem._client, "get_memory_history", side_effect=TypeError("boom")):
            with pytest.raises(RuntimeError, match=r"mem0\.history\('fake-id'\) failed"):
                mem.history("fake-id")


# ---------------------------------------------------------------------------
# Graph store coverage tests (mocked — no live server needed for these paths)
# ---------------------------------------------------------------------------


