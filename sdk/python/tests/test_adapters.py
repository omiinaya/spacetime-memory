"""Unit tests for memory adapters (mem0, zep).

Tests mock the underlying SDK client and verify each adapter method
calls the right SDK methods with the right arguments.

Follows the pattern from ``test_compounder_helpers.py`` — uses ``MagicMock``
for the client and ``@pytest.fixture`` for mock clients.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ══════════════════════════════════════════════════════════════════
# Mem0 adapter tests
# ══════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_mem0_client():
    """Create a Memory adapter with a mocked client.

    The adapter's ``_client`` is replaced with a MagicMock so no
    real network calls are made.
    """
    from spacetime_memory.sdks.mem0 import Memory

    mem = MagicMock(spec=Memory)
    mem._client = MagicMock()
    mem._user_id_to_ws = {}
    mem._ws = MagicMock()
    mem._ws.return_value = ""
    mem._call = MagicMock()
    mem._call.return_value = {}
    mem._llm_overrides = {}
    return mem


@pytest.fixture
def mem0_adapter():
    """Create a real Memory adapter backed by a mocked client.

    The _client attribute is a MagicMock so every SDK call returns
    sensible defaults.  The _ws cache is pre-filled so no workspace
    resolution is needed.
    """
    from spacetime_memory.sdks.mem0 import Memory

    adapter = MagicMock(spec=Memory)
    adapter._client = MagicMock()
    adapter._user_id_to_ws = {"test_user": "ws-1"}
    adapter._llm_overrides = {}
    adapter._graph_store = None
    # Wire up _ws to return the cached workspace
    def _ws_side_effect(user_id=None):
        if user_id and user_id in adapter._user_id_to_ws:
            return adapter._user_id_to_ws[user_id]
        return "ws-default"
    adapter._ws = _ws_side_effect
    adapter._call = MagicMock()
    adapter._call.return_value = []
    return adapter


class TestMem0AdapterAdd:
    """Tests for the mem0 Memory.add() method."""

    def test_add_text_string(self):
        """Adding a text string calls the client's store method."""
        from spacetime_memory.sdks.mem0 import Memory

        adapter = Memory()
        adapter._client = MagicMock()
        adapter._user_id_to_ws = {}
        adapter._ws = MagicMock(return_value="ws-1")
        adapter._call = MagicMock(return_value=[])
        adapter._llm_overrides = {}
        adapter._graph_store = None
        # The add() with infer=True calls _try_infer_merge -> search -> _call("query_graph")
        # Then store -> _call("store"), then search -> _call("search")
        # Provide enough side_effect entries for all internal _call() invocations
        adapter._call.side_effect = [
            [],  # _get_graph_context: query_graph returns []
            [],  # search: _call("search", ...) returns []
            None,  # store: _call("store", ...)
            [{"entity_id": "mem-1", "content": "I like pizza", "score": 1.0}],  # search result 1
            [{"entity_id": "mem-1", "content": "I like pizza", "score": 1.0}],  # search result 2
        ]
        adapter._client._call = MagicMock()

        result = adapter.add("I like pizza", user_id="test_user")

        assert "results" in result
        assert len(result["results"]) > 0
        adapter._call.assert_any_call(
            "store",
            workspace_id="ws-1",
            content="I like pizza",
            summary="I like pizza",
            memory_type="experience",
            peer_id="",
            source_session_id="",
            entities_json="{}",
        )

    def test_add_empty_text_raises(self):
        """Adding empty text raises ValueError for graph.add."""
        from spacetime_memory.sdks.mem0 import _GraphStore

        store = _GraphStore(MagicMock())
        with pytest.raises(ValueError, match="non-empty text"):
            store.add("")

    def test_add_with_metadata(self):
        """Adding text with metadata stores correctly."""
        from spacetime_memory.sdks.mem0 import Memory

        adapter = Memory()
        adapter._client = MagicMock()
        adapter._user_id_to_ws = {}
        adapter._ws = MagicMock(return_value="ws-1")
        adapter._call = MagicMock(return_value=[])
        adapter._llm_overrides = {}
        adapter._graph_store = None
        adapter._call.side_effect = [
            [],  # _get_graph_context: query_graph returns []
            [],  # search: _call("search", ...) returns []
            None,  # store
            [{"entity_id": "mem-2", "content": "memory with meta", "score": 1.0}],  # search 1
            [{"entity_id": "mem-2", "content": "memory with meta", "score": 1.0}],  # search 2
        ]
        adapter._client._call = MagicMock()

        result = adapter.add(
            "memory with meta",
            user_id="test_user",
            metadata={"source": "chat"},
        )
        assert len(result["results"]) > 0

    def test_add_message_list(self):
        """Adding a list of message dicts flattens them."""
        from spacetime_memory.sdks.mem0 import Memory

        adapter = Memory()
        adapter._client = MagicMock()
        adapter._user_id_to_ws = {}
        adapter._ws = MagicMock(return_value="ws-1")
        adapter._call = MagicMock(return_value=[])
        adapter._llm_overrides = {}
        adapter._graph_store = None
        adapter._call.side_effect = [
            None,  # store
            [],  # search result (empty = no user scope hit)
            [{"entity_id": "mem-3", "content": "user: hello", "score": 1.0}],  # final search
        ]
        adapter._client._call = MagicMock()

        result = adapter.add(
            [{"role": "user", "content": "hello"},
             {"role": "assistant", "content": "hi there"}],
            user_id="test_user",
        )
        assert len(result["results"]) > 0


class TestMem0AdapterGet:
    """Tests for the mem0 Memory.get() method."""

    def test_get_existing_memory(self):
        """Getting an existing memory returns the record."""
        from spacetime_memory.sdks.mem0 import Memory

        adapter = Memory()
        adapter._client = MagicMock()
        adapter._call = MagicMock()
        adapter._call.return_value = [
            {"id": "mem-1", "content": "I like pizza", "peer_id": "alice", "is_active": True},
        ]

        result = adapter.get("mem-1")
        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == "mem-1"
        assert result["results"][0]["memory"] == "I like pizza"

    def test_get_nonexistent_memory(self):
        """Getting a nonexistent memory returns empty results."""
        from spacetime_memory.sdks.mem0 import Memory

        adapter = Memory()
        adapter._client = MagicMock()
        adapter._call = MagicMock()
        adapter._call.return_value = []

        result = adapter.get("nonexistent")
        assert result["results"] == []

    def test_get_inactive_memory_filtered(self):
        """Inactive (soft-deleted) memories are filtered out."""
        from spacetime_memory.sdks.mem0 import Memory

        adapter = Memory()
        adapter._client = MagicMock()
        adapter._call = MagicMock()
        adapter._call.return_value = [
            {"id": "mem-dead", "content": "deleted", "is_active": False},
        ]

        result = adapter.get("mem-dead")
        assert result["results"] == []


class TestMem0AdapterSearch:
    """Tests for the mem0 Memory.search() method."""

    def test_search_returns_results(self):
        """Search returns formatted results."""
        from spacetime_memory.sdks.mem0 import Memory

        adapter = Memory()
        adapter._client = MagicMock()
        adapter._user_id_to_ws = {}
        adapter._ws = MagicMock(return_value="ws-1")
        adapter._call = MagicMock()
        adapter._call.side_effect = [
            # _get_graph_context: query_graph returns []
            [],
            # main search call → returns results
            [
                {"entity_id": "mem-1", "content": "pizza is great",
                 "memory_content": "pizza is great", "score": 0.95, "peer_id": ""},
            ],
            # get_memory for user_scope check on result
            [{"id": "mem-1", "content": "pizza is great", "user_scope": ""}],
        ]
        adapter._llm_overrides = {}

        result = adapter.search("pizza", user_id="test_user")
        assert "results" in result
        assert len(result["results"]) >= 1

    def test_search_with_threshold_filters(self):
        """Search with threshold filters low-scoring results."""
        from spacetime_memory.sdks.mem0 import Memory

        adapter = Memory()
        adapter._client = MagicMock()
        adapter._user_id_to_ws = {}
        adapter._ws = MagicMock(return_value="ws-1")
        adapter._call = MagicMock()
        adapter._call.side_effect = [
            # _get_graph_context: query_graph returns []
            [],
            # main search call
            [
                {"entity_id": "mem-1", "content": "high score", "score": 0.95},
                {"entity_id": "mem-2", "content": "low score", "score": 0.3},
            ],
            # get_memory for user_scope check on each result
            [{"id": "mem-1", "content": "high score", "user_scope": ""}],
            [{"id": "mem-2", "content": "low score", "user_scope": ""}],
        ]
        adapter._llm_overrides = {}

        result = adapter.search("test", user_id="test_user", threshold=0.5)
        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == "mem-1"

    def test_search_no_results(self):
        """Search with no matches returns empty results."""
        from spacetime_memory.sdks.mem0 import Memory

        adapter = Memory()
        adapter._client = MagicMock()
        adapter._user_id_to_ws = {}
        adapter._ws = MagicMock(return_value="ws-1")
        adapter._call = MagicMock()
        adapter._call.side_effect = [[], []]
        adapter._llm_overrides = {}

        result = adapter.search("nothing", user_id="test_user")
        assert result["results"] == []


class TestMem0AdapterUpdate:
    """Tests for the mem0 Memory.update() method."""

    def test_update_with_string(self):
        """Update with string content calls update_memory."""
        from spacetime_memory.sdks.mem0 import Memory

        adapter = Memory()
        adapter._client = MagicMock()
        adapter._call = MagicMock()
        adapter._call.return_value = {}

        result = adapter.update("mem-1", "Updated content")
        assert result["message"] == "Memory updated successfully!"
        adapter._call.assert_called_once_with(
            "update_memory", "mem-1", content="Updated content", summary="Updated content"
        )

    def test_update_with_dict(self):
        """Update with dict extracts content key."""
        from spacetime_memory.sdks.mem0 import Memory

        adapter = Memory()
        adapter._client = MagicMock()
        adapter._call = MagicMock()
        adapter._call.return_value = {}

        result = adapter.update("mem-1", {"content": "dict content"})
        assert result["message"] == "Memory updated successfully!"
        adapter._call.assert_called_once_with(
            "update_memory", "mem-1", content="dict content", summary="dict content"
        )


class TestMem0AdapterDelete:
    """Tests for the mem0 Memory.delete() method."""

    def test_delete_memory(self):
        """Delete calls delete_memory on the client."""
        from spacetime_memory.sdks.mem0 import Memory

        adapter = Memory()
        adapter._client = MagicMock()
        adapter._call = MagicMock()
        adapter._call.return_value = {}

        result = adapter.delete("mem-1")
        assert result["message"] == "Memory deleted successfully!"
        adapter._call.assert_called_once_with("delete_memory", "mem-1")


class TestMem0AdapterGetAll:
    """Tests for the mem0 Memory.get_all() method."""

    def test_get_all_with_user(self):
        """get_all with user_id returns memories scoped to user."""
        from spacetime_memory.sdks.mem0 import Memory

        adapter = Memory()
        adapter._client = MagicMock()
        adapter._user_id_to_ws = {"alice": "ws-1"}
        adapter._ws = MagicMock(return_value="ws-1")
        adapter._call = MagicMock()
        adapter._call.return_value = [
            {"id": "mem-1", "content": "Memory 1", "user_scope": "alice"},
            {"id": "mem-2", "content": "Memory 2", "user_scope": ""},
        ]

        result = adapter.get_all(user_id="alice")
        assert len(result["results"]) == 2

    def test_get_all_empty(self):
        """get_all with no memories returns empty."""
        from spacetime_memory.sdks.mem0 import Memory

        adapter = Memory()
        adapter._client = MagicMock()
        adapter._user_id_to_ws = {}
        adapter._ws = MagicMock(return_value="ws-1")
        adapter._call = MagicMock()
        adapter._call.return_value = []

        result = adapter.get_all()
        assert result["results"] == []


class TestMem0AdapterHistory:
    """Tests for the mem0 Memory.history() method."""

    def test_history_returns_versions(self):
        """history returns version list from get_memory_history."""
        from spacetime_memory.sdks.mem0 import Memory

        adapter = Memory()
        adapter._client = MagicMock()
        adapter._call = MagicMock()
        adapter._call.return_value = [
            {"version": 2, "content": "Updated content"},
            {"version": 1, "content": "Original content"},
        ]

        result = adapter.history("mem-1")
        assert len(result) == 2
        assert result[0]["version"] == 2


class TestMem0AdapterReset:
    """Tests for the mem0 Memory.reset() method."""

    def test_reset_clears_cache(self):
        """reset clears the workspace cache."""
        from spacetime_memory.sdks.mem0 import Memory

        adapter = Memory()
        adapter._client = MagicMock()
        adapter._user_id_to_ws = {"alice": "ws-1"}

        result = adapter.reset()
        assert result["status"] == "ok"
        assert adapter._user_id_to_ws == {}


# ══════════════════════════════════════════════════════════════════
# Mem0 GraphStore adapter tests
# ══════════════════════════════════════════════════════════════════


class TestMem0GraphStore:
    """Tests for the mem0 GraphStore adapter."""

    def test_graph_add_entity(self):
        """Adding a graph entity calls the right client methods."""
        from spacetime_memory.sdks.mem0 import Memory, _GraphStore

        mem = MagicMock(spec=Memory)
        mem._client = MagicMock()
        mem._ws = MagicMock(return_value="ws-1")
        mem._call = MagicMock()
        mem._client.search = MagicMock(return_value=[])
        mem._client._query = MagicMock(return_value=[])
        mem.add_alias = MagicMock()

        store = _GraphStore(mem)

        with patch.object(store, "_add_exact") as mock_add_exact:
            mock_add_exact.return_value = {"id": "ent-1", "label": "Alice"}
            result = store.add("Alice", entity_type="person", user_id="test_user")
            assert result["id"] == "ent-1"

    def test_graph_add_empty_raises(self):
        """Adding empty text to graph raises ValueError."""
        from spacetime_memory.sdks.mem0 import _GraphStore

        store = _GraphStore(MagicMock())
        with pytest.raises(ValueError, match="non-empty text"):
            store.add("")

    def test_graph_search_returns_results(self):
        """Searching the graph returns entity records."""
        from spacetime_memory.sdks.mem0 import Memory, _GraphStore

        mem = MagicMock(spec=Memory)
        mem._client = MagicMock()
        mem._ws = MagicMock(return_value="ws-1")
        mem._call = MagicMock()
        mem._client.search = MagicMock(return_value=[])
        mem._client._query = MagicMock(return_value=[])

        store = _GraphStore(mem)

        # Mock the search to use the fallback path
        with patch.object(store, "_tag_filter") as mock_filter:
            mock_filter.side_effect = lambda x, y: x
            result = store.search("Alice", user_id="test_user")
            assert isinstance(result, list)

    def test_graph_get_all(self):
        """Getting all graph entities returns entity list."""
        from spacetime_memory.sdks.mem0 import Memory, _GraphStore

        mem = MagicMock(spec=Memory)
        mem._client = MagicMock()
        mem._ws = MagicMock(return_value="ws-1")
        mem._call = MagicMock()
        mem._client._query = MagicMock(return_value=[])

        store = _GraphStore(mem)
        result = store.get_all(user_id="test_user")
        assert isinstance(result, list)

    def test_graph_delete(self):
        """Deleting a graph entity calls delete_node."""
        from spacetime_memory.sdks.mem0 import Memory, _GraphStore

        mem = MagicMock(spec=Memory)
        mem._client = MagicMock()
        mem._call = MagicMock()

        store = _GraphStore(mem)
        result = store.delete("entity-1")
        assert result["status"] == "ok"
        mem._call.assert_called_once_with("delete_node", "entity-1")


# ══════════════════════════════════════════════════════════════════
# Zep adapter tests
# ══════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_zep_client():
    """Create a ZepClient with a mocked underlying client.

    The internal ``_client`` attribute is replaced with a MagicMock
    so no real network calls are made.
    """
    from spacetime_memory.sdks.zep import ZepClient

    adapter = MagicMock(spec=ZepClient)
    adapter._client = MagicMock()
    adapter._session_to_ws = {}
    return adapter


@pytest.fixture
def zep_adapter():
    """Create a real ZepClient backed by a mocked _client.

    Pre-fills the session cache so _ensure_workspace and
    _resolve_session can return cached workspace IDs.
    """
    from spacetime_memory.sdks.zep import ZepClient

    adapter = ZepClient(host="localhost", port=3001)
    # Replace the real _client with a MagicMock
    adapter._client = MagicMock()
    # Pre-fill session cache
    adapter._session_to_ws = {"test-session": "ws-1"}
    return adapter


class TestZepAddMemory:
    """Tests for ZepClient.add_memory()."""

    def test_add_memory_dicts(self):
        """Adding message dicts calls store on the client."""
        from spacetime_memory.sdks.zep import ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._session_to_ws = {"test-session": "ws-1"}
        adapter._client.list_memories.return_value = [
            {"id": "msg-1", "entity_id": "msg-1"},
        ]
        adapter._client.store.return_value = {}

        result = adapter.add_memory(
            session_id="test-session",
            messages=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
            ],
        )
        assert result["status"] == "ok"
        assert len(result["message_ids"]) > 0
        assert adapter._client.store.call_count == 2

    def test_add_memory_memorymessage_objects(self):
        """Adding MemoryMessage objects works."""
        from spacetime_memory.sdks.zep import MemoryMessage, ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._session_to_ws = {"test-session": "ws-1"}
        adapter._client.list_memories.return_value = [
            {"id": "msg-1"},
        ]

        result = adapter.add_memory(
            session_id="test-session",
            messages=[MemoryMessage(role="user", content="Object message")],
        )
        assert result["status"] == "ok"

    def test_add_memory_empty_list(self):
        """Adding empty messages list returns ok with no IDs."""
        from spacetime_memory.sdks.zep import ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._session_to_ws = {"test-session": "ws-1"}
        adapter._client.list_memories.return_value = []

        result = adapter.add_memory(session_id="test-session", messages=[])
        assert result["status"] == "ok"
        assert result["message_ids"] == []


class TestZepGetMemory:
    """Tests for ZepClient.get_memory()."""

    def test_get_memory_returns_messages(self):
        """Getting memory returns messages and facts."""
        from spacetime_memory.sdks.zep import ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._session_to_ws = {"test-session": "ws-1"}
        adapter._client.list_memories.side_effect = [
            # experience memories
            [
                {"id": "m1", "peer_id": "user", "content": "Hello",
                 "created_at": "1000", "strength": 0.9},
                {"id": "m2", "peer_id": "assistant", "content": "Hi",
                 "created_at": "1001", "strength": 0.8},
            ],
            # fact memories
            [
                {"id": "f1", "content": "User likes pizza", "created_at": "1002"},
            ],
        ]

        memory = adapter.get_memory(session_id="test-session")
        assert memory is not None
        assert len(memory["messages"]) == 2
        assert len(memory["facts"]) == 1
        assert "pizza" in memory["facts"][0]

    def test_get_memory_nonexistent_session(self):
        """Getting memory for nonexistent session returns None."""
        from spacetime_memory.sdks.zep import ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._session_to_ws = {}
        adapter._client.list_workspaces.return_value = []

        memory = adapter.get_memory(session_id="no-such-session")
        assert memory is None

    def test_get_memory_respects_limit(self):
        """get_memory respects limit parameter."""
        from spacetime_memory.sdks.zep import ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._session_to_ws = {"test-session": "ws-1"}
        adapter._client.list_memories.return_value = [
            {"id": "m1", "peer_id": "user", "content": "Msg 1",
             "created_at": "1000", "strength": 0.9},
        ]

        memory = adapter.get_memory(session_id="test-session", limit=3)
        assert memory is not None
        assert len(memory["messages"]) == 1


class TestZepSearchMemory:
    """Tests for ZepClient.search_memory()."""

    def test_search_memory_returns_results(self):
        """Search memory returns MemorySearchResult objects."""
        from spacetime_memory.sdks.zep import MemorySearchResult, ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._session_to_ws = {"test-session": "ws-1"}
        adapter._client.search.return_value = [
            {"entity_id": "m1", "content": "pizza is great",
             "memory_content": "pizza is great",
             "score": 0.95, "peer_id": "user"},
        ]

        results = adapter.search_memory(
            session_id="test-session",
            query="food",
            limit=5,
        )
        assert len(results) > 0
        for r in results:
            assert isinstance(r, MemorySearchResult)
            assert r.message is not None

    def test_search_memory_empty_session(self):
        """Search memory for nonexistent session returns empty list."""
        from spacetime_memory.sdks.zep import ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._session_to_ws = {}
        adapter._client.list_workspaces.return_value = []

        results = adapter.search_memory(
            session_id="no-such-session",
            query="anything",
        )
        assert results == []

    def test_search_memory_score_threshold(self):
        """Search memory with score threshold filters results."""
        from spacetime_memory.sdks.zep import ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._session_to_ws = {"test-session": "ws-1"}
        adapter._client.search.return_value = [
            {"entity_id": "m1", "content": "relevant", "score": 0.95,
             "memory_content": "relevant", "peer_id": "user"},
            {"entity_id": "m2", "content": "irrelevant", "score": 0.2,
             "memory_content": "irrelevant", "peer_id": "user"},
        ]

        results = adapter.search_memory(
            session_id="test-session",
            query="test",
            score_threshold=0.5,
        )
        assert len(results) == 1

    def test_search_memory_with_min_score(self):
        """Search memory accepts min_score as alias for score_threshold."""
        from spacetime_memory.sdks.zep import ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._session_to_ws = {"test-session": "ws-1"}
        adapter._client.search.return_value = [
            {"entity_id": "m1", "content": "relevant", "score": 0.8,
             "memory_content": "relevant", "peer_id": "user"},
        ]

        results = adapter.search_memory(
            session_id="test-session",
            query="test",
            min_score=0.5,
        )
        assert len(results) == 1


class TestZepDeleteMemory:
    """Tests for ZepClient.delete_memory()."""

    def test_delete_memory(self):
        """Delete memory removes messages from session."""
        from spacetime_memory.sdks.zep import ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._session_to_ws = {"test-session": "ws-1"}
        adapter._client.list_memories.return_value = [
            {"id": "m1", "entity_id": "m1"},
            {"id": "m2", "entity_id": "m2"},
        ]
        adapter._client.delete_memory.return_value = {"status": "ok"}

        result = adapter.delete_memory(session_id="test-session")
        assert result["status"] == "ok"
        assert result["deleted"] == 2

    def test_delete_memory_nonexistent(self):
        """Delete memory for nonexistent session is idempotent."""
        from spacetime_memory.sdks.zep import ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._session_to_ws = {}
        adapter._client.list_workspaces.return_value = []

        result = adapter.delete_memory(session_id="no-such-session")
        assert result["status"] == "ok"
        assert result["deleted"] == 0


class TestZepFacts:
    """Tests for ZepClient fact methods."""

    def test_add_fact(self):
        """Adding a fact calls store on the client."""
        from spacetime_memory.sdks.zep import ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._session_to_ws = {"test-session": "ws-1"}
        adapter._client.store.return_value = {}
        adapter._client.list_memories.return_value = [
            {"id": "fact-1", "entity_id": "fact-1"},
        ]

        result = adapter.add_fact(session_id="test-session", fact="User likes tea")
        assert result["status"] == "ok"
        assert result["fact_id"] == "fact-1"
        adapter._client.store.assert_called_once()
        store_kw = adapter._client.store.call_args[1]
        assert store_kw["memory_type"] == "fact"

    def test_list_facts(self):
        """Listing facts returns Fact objects."""
        from spacetime_memory.sdks.zep import Fact, ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._session_to_ws = {"test-session": "ws-1"}
        adapter._client.list_memories.return_value = [
            {"id": "f1", "content": "User likes coffee",
             "created_at": "1000", "entity_id": "f1"},
            {"id": "f2", "content": "User likes tea",
             "created_at": "1001", "entity_id": "f2"},
        ]

        facts = adapter.list_facts(session_id="test-session")
        assert len(facts) == 2
        for f in facts:
            assert isinstance(f, Fact)
        fact_texts = [f.fact for f in facts]
        assert "User likes coffee" in fact_texts

    def test_list_facts_empty_session(self):
        """Listing facts for session with no facts returns empty list."""
        from spacetime_memory.sdks.zep import ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._session_to_ws = {}
        adapter._client.list_workspaces.return_value = []

        facts = adapter.list_facts(session_id="no-facts")
        assert facts == []

    def test_delete_fact(self):
        """Deleting a fact calls delete_memory."""
        from spacetime_memory.sdks.zep import ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._client.delete_memory.return_value = {"status": "ok"}

        result = adapter.delete_fact(fact_uuid="fact-1")
        assert result["status"] == "ok"
        assert result["deleted"] == 1
        adapter._client.delete_memory.assert_called_once_with("fact-1")

    def test_delete_fact_nonexistent(self):
        """Deleting a nonexistent fact is idempotent."""
        from spacetime_memory.sdks.zep import ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._client.delete_memory.return_value = {
            "status": "ok", "note": "already deleted",
        }

        result = adapter.delete_fact(fact_uuid="no-such-fact")
        assert result["status"] == "ok"
        assert result["deleted"] == 0


class TestZepSessionManagement:
    """Tests for ZepClient session methods."""

    def test_list_sessions(self):
        """Listing sessions returns Session objects from workspaces."""
        from spacetime_memory.sdks.zep import Session, ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._client.list_workspaces.return_value = [
            {"name": "session-1", "id": "ws-1", "created_at": "1000"},
            {"name": "session-2", "id": "ws-2", "created_at": "1001"},
        ]

        sessions = adapter.list_sessions()
        assert len(sessions) == 2
        for s in sessions:
            assert isinstance(s, Session)
        assert sessions[0].session_id == "session-1"

    def test_get_session(self):
        """Getting a session returns the Session object."""
        from spacetime_memory.sdks.zep import Session, ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._client.list_workspaces.return_value = [
            {"name": "my-session", "id": "ws-1", "created_at": "1000"},
        ]

        session = adapter.get_session("my-session")
        assert isinstance(session, Session)
        assert session.session_id == "my-session"

    def test_get_session_nonexistent_raises(self):
        """Getting a nonexistent session raises NotFoundError."""
        from spacetime_memory.sdks.zep import NotFoundError, ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._client.list_workspaces.return_value = []

        with pytest.raises(NotFoundError):
            adapter.get_session("no-such-session")

    def test_add_session(self):
        """Adding a session creates a workspace."""
        from spacetime_memory.sdks.zep import Session, ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._client.list_workspaces.return_value = [
            {"name": "new-session", "id": "ws-new", "created_at": "2000"},
        ]

        session = adapter.add_session("new-session")
        assert isinstance(session, Session)
        assert session.session_id == "new-session"
        adapter._client.create_workspace.assert_called_once_with(
            "new-session", "Zep session: new-session",
        )


class TestZepClientClose:
    """Tests for ZepClient.close()."""

    def test_close_clears_cache(self):
        """close clears the session cache."""
        from spacetime_memory.sdks.zep import ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._session_to_ws = {"session-1": "ws-1", "session-2": "ws-2"}

        adapter.close()
        assert adapter._session_to_ws == {}

    def test_close_is_idempotent(self):
        """Multiple close calls don't raise."""
        from spacetime_memory.sdks.zep import ZepClient

        adapter = ZepClient(host="localhost", port=3001)
        adapter._client = MagicMock()
        adapter._session_to_ws = {"s": "w"}

        adapter.close()  # First
        adapter.close()  # Second — should not raise
