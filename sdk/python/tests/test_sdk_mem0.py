"""Tests for spacetime_memory.sdks.mem0 — Mem0 adapter."""

from unittest.mock import MagicMock, Mock

from spacetime_memory.sdks.mem0 import Memory, _GraphStore


class TestTag:
    """Tag suffix builder."""

    def test_with_user_id(self):
        graph = _GraphStore(Mock())
        result = graph._tag("alice")
        assert result == "mem0_user:alice"

    def test_without_user_id(self):
        graph = _GraphStore(Mock())
        result = graph._tag(None)
        assert result == "mem0_global"
        result = graph._tag("")
        assert result == "mem0_global"


class TestTagFilter:
    """Filter entity rows by tag."""

    def setup_method(self):
        self.graph = _GraphStore(Mock())

    def test_kg_node_with_matching_tag(self):
        rows = [{"metadata_json": '{"tag": "mem0_user:alice"}'}]
        result = self.graph._tag_filter(rows, "mem0_user:alice")
        assert len(result) == 1

    def test_kg_node_with_different_tag(self):
        rows = [{"metadata_json": '{"tag": "mem0_user:bob"}'}]
        result = self.graph._tag_filter(rows, "mem0_user:alice")
        assert len(result) == 0

    def test_entity_link_with_matching_tag(self):
        rows = [{"description": '{"tag": "mem0_user:alice"}'}]
        result = self.graph._tag_filter(rows, "mem0_user:alice")
        assert len(result) == 1

    def test_both_fields_present(self):
        """metadata_json takes priority when both contain tag."""
        rows = [{"metadata_json": '{"tag": "mem0_user:alice"}', "description": '{"tag": "mem0_user:bob"}'}]
        result = self.graph._tag_filter(rows, "mem0_user:alice")
        assert len(result) == 1

    def test_no_metadata_or_description(self):
        """Empty metadata — allow (global entries)."""
        rows = [{"id": "entry1", "metadata_json": "", "description": ""}]
        result = self.graph._tag_filter(rows, "mem0_global")
        assert len(result) == 1

    def test_invalid_json_in_metadata(self):
        """Invalid JSON in metadata falls back to description check."""
        rows = [{"metadata_json": "not-json", "description": '{"tag": "mem0_user:alice"}'}]
        result = self.graph._tag_filter(rows, "mem0_user:alice")
        assert len(result) == 1

    def test_multiple_rows_mixed(self):
        rows = [
            {"metadata_json": '{"tag": "mem0_user:alice"}'},
            {"metadata_json": '{"tag": "mem0_user:bob"}'},
            {"metadata_json": "", "description": ""},
        ]
        result = self.graph._tag_filter(rows, "mem0_user:alice")
        # The row with empty metadata/description passes through (no tag = unscoped),
        # so both the alice row and the empty row match.
        assert len(result) == 2

    def test_metadata_without_tag_key(self):
        """metadata_json present but without tag key — not a match."""
        rows = [{"metadata_json": '{"other_key": "value"}'}]
        result = self.graph._tag_filter(rows, "mem0_user:alice")
        assert len(result) == 0

    def test_description_is_dict_not_string(self):
        """description may already be parsed as dict by some callers."""
        rows = [{"description": {"tag": "mem0_user:alice"}}]
        result = self.graph._tag_filter(rows, "mem0_user:alice")
        assert len(result) == 1

    def test_empty_rows(self):
        assert self.graph._tag_filter([], "mem0_user:alice") == []


class TestEntityLinkToDict:
    """Convert entity_link rows to graph entity dicts."""

    def setup_method(self):
        self.graph = _GraphStore(Mock())

    def test_basic_conversion(self):
        row = {
            "id": "abc123",
            "entity_name": "Alice",
            "entity_type": "person",
            "description": '{"tag": "mem0_user:alice"}',
            "created_at": 1000000,
        }
        result = self.graph._entity_link_to_dict(row, "mem0_user:alice")
        assert result["id"] == "abc123"
        assert result["label"] == "Alice"
        assert result["node_type"] == "person"
        assert result["entity_type"] == "person"
        assert result["summary"] == "Alice"

    def test_no_description(self):
        """Missing description uses default tag."""
        row = {"id": "x", "entity_name": "Bob", "entity_type": "concept", "created_at": 0}
        result = self.graph._entity_link_to_dict(row, "mem0_global")
        assert result["metadata_json"] == '{"tag": "mem0_global"}'

    def test_minimal_row(self):
        """Row with only id and entity_name."""
        row = {"id": "minimal", "entity_name": "Min"}
        result = self.graph._entity_link_to_dict(row, "tag1")
        assert result["id"] == "minimal"
        assert result["node_type"] == "concept"
        assert result["created_at"] == 0


class TestGraphStoreDelegation:
    """Delegate methods that forward to self._memory."""

    def test_ws_delegation(self):
        """_ws() forwards to memory._ws()."""
        mem = Mock()
        mem._ws.return_value = "ws-1"
        graph = _GraphStore(mem)
        result = graph._ws("alice")
        assert result == "ws-1"
        mem._ws.assert_called_once_with("alice")

    def test_ws_no_user_id(self):
        """_ws(None) calls memory._ws(None)."""
        mem = Mock()
        mem._ws.return_value = "ws-default"
        graph = _GraphStore(mem)
        result = graph._ws(None)
        assert result == "ws-default"
        mem._ws.assert_called_once_with(None)

    def test_call_delegation(self):
        """_call() forwards to memory._call()."""
        mem = Mock()
        mem._call.return_value = {"status": "ok"}
        graph = _GraphStore(mem)
        result = graph._call("create_node", workspace_id="ws-1", label="test")
        assert result == {"status": "ok"}
        mem._call.assert_called_once_with("create_node", workspace_id="ws-1", label="test")


class TestMemoryToolAndEntityStore:
    """create_memory_tool() real tool definition + entity_store alias."""

    def _memory(self) -> Memory:
        mem = Memory(config={"host": "127.0.0.1", "port": 3001})
        mem._client = MagicMock()
        return mem

    def test_create_memory_tool_returns_tools(self):
        mem = self._memory()
        result = mem.create_memory_tool(user_id="alice", agent_id="agent-1")
        assert "tools" in result
        assert isinstance(result["tools"], list)
        names = [t["function"]["name"] for t in result["tools"]]
        assert names == ["memory_add", "memory_search", "memory_get", "memory_delete"]
        assert result["scope"]["user_id"] == "alice"
        assert "alice" in result["tools"][0]["function"]["description"]

    def test_create_memory_tool_no_scope(self):
        mem = self._memory()
        result = mem.create_memory_tool()
        assert len(result["tools"]) == 4
        assert result["scope"] == {"user_id": None, "agent_id": None, "run_id": None}

    def test_entity_store_alias_returns_graph(self):
        mem = self._memory()
        assert mem.entity_store is mem.graph
        assert isinstance(mem.entity_store, _GraphStore)


class TestGraphStoreAddEdgeCases:
    """Edge cases for _GraphStore.add()."""

    def setup_method(self):
        self.graph = _GraphStore(Mock())

    def test_add_empty_text_raises(self):
        """add with empty string raises ValueError."""
        import pytest
        with pytest.raises(ValueError, match="non-empty text"):
            self.graph.add("")

    def test_add_whitespace_only_raises(self):
        """add with whitespace-only string raises ValueError."""
        import pytest
        with pytest.raises(ValueError, match="non-empty text"):
            self.graph.add("   ")

    def test_add_newline_raises(self):
        """add with newline-only string raises ValueError."""
        import pytest
        with pytest.raises(ValueError, match="non-empty text"):
            self.graph.add("\n\n")


class TestResolveLLM:
    """Tests for the _resolve_llm helper function."""

    def test_resolve_llm_no_config(self):
        """_resolve_llm() without config returns a default LLMClient."""
        from spacetime_memory.sdks.mem0 import _resolve_llm
        result = _resolve_llm(None)
        from spacetime_memory.llm import LLMClient
        assert isinstance(result, LLMClient)
        assert isinstance(result.model, str) and len(result.model) > 0

    def test_resolve_llm_with_model_override(self):
        """_resolve_llm() passes model from config."""
        from spacetime_memory.sdks.mem0 import _resolve_llm
        result = _resolve_llm({"model": "gpt-4o", "api_key": "sk-test"})
        assert result.model == "gpt-4o"

    def test_resolve_llm_with_base_url(self):
        """_resolve_llm() passes base_url from config."""
        from spacetime_memory.sdks.mem0 import _resolve_llm
        result = _resolve_llm({"base_url": "http://localhost:8080/v1"})
        from spacetime_memory.llm import LLMClient
        assert isinstance(result, LLMClient)
