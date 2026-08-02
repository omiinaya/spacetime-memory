"""Unit tests for the Mem0 adapter models (_models.py).

Tests _InferMergeDone exception class and all type aliases.
"""

from __future__ import annotations

import pytest

from spacetime_memory.sdks.mem0._models import (
    FilterDict,
    GraphEntityDict,
    LLMConfigDict,
    MessageDict,
    MetadataDict,
    ResultDict,
    _InferMergeDone,
)

pytestmark = pytest.mark.unit


# ── _InferMergeDone ────────────────────────────────────────────────────────


class TestInferMergeDone:
    def test_is_base_exception(self):
        """_InferMergeDone inherits from BaseException, not Exception."""
        assert issubclass(_InferMergeDone, BaseException)

    def test_can_be_raised_and_caught(self):
        """It can be raised with a payload and caught."""
        payload = {"results": [{"id": "m1"}]}
        try:
            raise _InferMergeDone(payload)
        except _InferMergeDone as e:
            assert e.args[0] == payload

    def test_no_arg_construction(self):
        """Can be constructed without arguments."""
        exc = _InferMergeDone()
        assert exc.args == ()

    def test_single_arg(self):
        exc = _InferMergeDone("just a string")
        assert exc.args[0] == "just a string"

    def test_nested_catch_does_not_catch_value_error(self):
        """Ordinary Exception subclasses should not be caught."""
        with pytest.raises(ValueError):
            try:
                raise ValueError("normal error")
            except _InferMergeDone:
                pytest.fail("Should not catch ValueError")

    def test_raised_from_try_except_works(self):
        """Simulate the pattern used in Memory.add() where it's raised from
        _handle_message_list."""
        payload = {"results": []}
        with pytest.raises(_InferMergeDone) as exc_info:
            try:
                # Simulate the add() flow
                try:
                    # Simulate _handle_message_list raising _InferMergeDone
                    raise _InferMergeDone(payload)
                except _InferMergeDone:
                    # This models the _InferMergeDone catch in add()
                    raise
            except RuntimeError:
                pytest.fail("Should not hit RuntimeError path")
        assert exc_info.value.args[0] == payload


# ── Type aliases ───────────────────────────────────────────────────────────


class TestTypeAliases:
    def test_message_dict_shape(self):
        """MessageDict should model {'role': str, 'content': str}."""
        msg: MessageDict = {"role": "user", "content": "Hello"}
        assert msg["role"] == "user"
        assert msg["content"] == "Hello"

    def test_message_dict_optional_keys(self):
        """MessageDict allows extra keys via dict[str, str]."""
        msg: MessageDict = {"role": "user", "content": "Hi", "extra": "val"}
        assert msg["extra"] == "val"

    def test_filter_dict_as_dict(self):
        fd: FilterDict = {"user_id": "u1", "agent_id": "a1", "run_id": "r1"}
        assert fd["user_id"] == "u1"

    def test_filter_dict_empty(self):
        fd: FilterDict = {}
        assert len(fd) == 0

    def test_llm_config_dict(self):
        lc: LLMConfigDict = {
            "provider": "openai",
            "model": "gpt-4",
            "api_key": "sk-xxx",
            "base_url": "https://api.openai.com",
        }
        assert lc["model"] == "gpt-4"

    def test_llm_config_dict_minimal(self):
        lc: LLMConfigDict = {"model": "gpt-4o-mini"}
        assert lc["model"] == "gpt-4o-mini"

    def test_metadata_dict(self):
        md: MetadataDict = {"key": "value", "count": 42}
        assert md["key"] == "value"

    def test_result_dict(self):
        rd: ResultDict = {
            "id": "mem-1",
            "memory": "I like pizza",
            "score": 0.95,
            "user_id": "alice",
            "agent_id": "assistant",
            "metadata": {},
        }
        assert rd["id"] == "mem-1"
        assert rd["score"] == 0.95

    def test_result_dict_minimal(self):
        rd: ResultDict = {}
        assert len(rd) == 0

    def test_graph_entity_dict(self):
        ge: GraphEntityDict = {
            "id": "node-1",
            "label": "Alice",
            "node_type": "entity",
            "entity_type": "person",
            "summary": "A person",
            "metadata_json": "{}",
            "created_at": 1_700_000_000,
        }
        assert ge["label"] == "Alice"
        assert ge["node_type"] == "entity"


# ── All exports ────────────────────────────────────────────────────────────


class TestAllExports:
    def test_all_is_defined(self):
        from spacetime_memory.sdks.mem0._models import __all__ as all_exports
        assert isinstance(all_exports, list)
        assert "_InferMergeDone" in all_exports
        assert "MessageDict" in all_exports
        assert "FilterDict" in all_exports
        assert "LLMConfigDict" in all_exports
        assert "MetadataDict" in all_exports
        assert "ResultDict" in all_exports
        assert "GraphEntityDict" in all_exports
