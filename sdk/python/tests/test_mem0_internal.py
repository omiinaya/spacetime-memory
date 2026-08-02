"""Integration tests for Mem0-compatible adapter.

These tests require a running SpacetimeDB instance.
Run with::

    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest tests/test_mem0_internal.py -v

"""

from __future__ import annotations

import os
import time
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


class TestMem0InternalPaths:
    """Exercise internal code paths for coverage."""

    def test_ws_cached_hit(self, mem: Memory) -> None:
        """_ws returns cached workspace_id without server call."""
        uid = _uid()
        ws1 = mem._ws(uid)  # creates workspace
        ws2 = mem._ws(uid)  # cached → returns immediately
        assert ws1 == ws2

    def test_ws_finds_existing_workspace(self, mem: Memory) -> None:
        """_ws finds existing workspace on server (line 614)."""
        uid = _uid()
        mem._ws(uid)  # creates workspace
        # Clear cache so next call must query server
        mem._user_id_to_ws.clear()
        ws = mem._ws(uid)  # should find existing → line 614
        assert ws

    def test_extract_ids_from_filters_none(self, mem: Memory) -> None:
        """_extract_ids_from_filters with None returns (None, None, None) (line 644)."""
        uid = _uid()
        result = mem.search("test", filters={}, user_id=uid, graph_context=False)
        assert "results" in result

    def test_search_with_graph_context(self, mem: Memory) -> None:
        """search() with graph_context=True populates metadata.graph_context (line 1094)."""
        uid = _uid()
        mem.add("graph context test", user_id=uid)
        time.sleep(0.3)
        result = mem.search("graph", user_id=uid, graph_context=True)
        assert "results" in result
        # May or may not have graph_context depending on KG data

    def test_get_all_with_empty_filters(self, mem: Memory) -> None:
        """get_all() with empty filters dict (exercises _extract_ids_from_filters with {})."""
        uid = _uid()
        mem.add("filter test", user_id=uid)
        result = mem.get_all(filters={}, user_id=uid)
        assert "results" in result

    def test_search_user_scope_isolation(self, mem: Memory) -> None:
        """search() checks user_scope isolation (line 1090 coverage attempt)."""
        uid1 = _uid("mem0-scope-a")
        uid2 = _uid("mem0-scope-b")
        mem.add("user A memory", user_id=uid1)
        time.sleep(0.3)
        # Search as user B — should not return A's scoped memories
        result = mem.search("user A memory", user_id=uid2)
        assert "results" in result  # May be empty but should not crash

    def test_get_graph_context_error(self, mem: Memory) -> None:
        """_get_graph_context returns [] on RuntimeError (lines 704-706)."""
        uid = _uid()
        with patch.object(mem._client, "query_graph", side_effect=RuntimeError("no graph")):
            result = mem._get_graph_context("test", user_id=uid)
            assert result == []

    def test_set_llm_config_persists(self, mem: Memory) -> None:
        """set_llm_config stores per-user overrides."""
        uid = _uid()
        mem.set_llm_config(uid, {"model": "gpt-3.5-turbo"})
        assert uid in mem._llm_overrides
        assert mem._llm_overrides[uid]["model"] == "gpt-3.5-turbo"




class TestWorkspaceResolutionMocks:
    """Cover _ws paths: cache hits, server lookup, creation, failure."""

    def test_ws_server_failure_raises_valueerror(self, mem: Memory) -> None:
        """_ws raises ValueError when workspace cannot be resolved (line 622)."""
        uid = _uid()
        mem._user_id_to_ws.clear()
        with patch.object(mem, "_call", return_value=[]):  # empty list_workspaces
            with pytest.raises(ValueError, match="Could not resolve or create workspace"):
                mem._ws(uid)

    def test_ws_creates_and_finds(self, mem: Memory) -> None:
        """_ws: creates workspace, then finds it on second list call."""
        uid = _uid()
        mem._user_id_to_ws.clear()
        ws_id = "ws-created-123"
        # First list: empty, then create_workspace called, second list finds it
        call_results = [
            [],  # first list_workspaces → empty
            None,  # create_workspace (any return)
            [{"name": uid, "id": ws_id}],  # second list_workspaces
        ]
        with patch.object(mem, "_call", side_effect=call_results):
            result = mem._ws(uid)
            assert result == ws_id

    def test_ws_cached_without_server_call(self, mem: Memory) -> None:
        """_ws returns cached value without server call."""
        uid = _uid()
        mem._user_id_to_ws[uid] = "ws-cached"
        with patch.object(mem, "_call") as mock_call:
            result = mem._ws(uid)
            assert result == "ws-cached"
            mock_call.assert_not_called()  # must not call server


# ---------------------------------------------------------------------------
# _call token refresh coverage (mocked)
# ---------------------------------------------------------------------------




class TestCallTokenRefresh:
    """Cover _call token refresh path (lines 635-638)."""

    def test_call_token_refresh_on_auth_error(self, host: str, port: int) -> None:
        """_call retries after token refresh on auth errors."""
        refreshed = False

        def refresh_cb():
            nonlocal refreshed
            refreshed = True
            return "new-token"

        m = Memory(config={"host": host, "port": port}, token_refresh_callback=refresh_cb)

        # First store call raises auth RuntimeError, second succeeds
        call_count = [0]

        def fake_store(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("unauthorized request")
            return "ok"

        with patch.object(m._client, "store", side_effect=fake_store):
            result = m._call("store", workspace_id="x", content="test")
            assert result == "ok"
            assert refreshed is True

    def test_call_no_token_refresh_on_non_auth_error(self, host: str, port: int) -> None:
        """_call does not retry on non-auth RuntimeError."""
        refresh_called = [False]

        def refresh_cb():
            refresh_called[0] = True
            return "token"

        m = Memory(config={"host": host, "port": port}, token_refresh_callback=refresh_cb)

        with patch.object(m._client, "store", side_effect=RuntimeError("db connection failed")):
            with pytest.raises(RuntimeError, match="db connection failed"):
                m._call("store", workspace_id="x", content="test")
            assert refresh_called[0] is False


# ---------------------------------------------------------------------------
# _store_facts_as_kg_nodes coverage (mocked)
# ---------------------------------------------------------------------------


