"""Integration tests for Mem0-compatible adapter.

These tests require a running SpacetimeDB instance.
Run with::

    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 pytest tests/test_mem0_store_facts.py -v

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


class TestStoreFactsAsKgNodes:
    """Cover _store_facts_as_kg_nodes paths (lines 666-691)."""

    def test_store_facts_empty_ws_returns_empty(self, mem: Memory) -> None:
        """_store_facts_as_kg_nodes with no ws_id returns [] (line 667)."""
        with patch.object(mem, "_ws", return_value=""):
            result = mem._store_facts_as_kg_nodes(["fact 1", "fact 2"], user_id=None)
            assert result == []

    def test_store_facts_empty_list_returns_empty(self, mem: Memory) -> None:
        """_store_facts_as_kg_nodes with empty facts returns [] (line 667)."""
        uid = _uid()
        result = mem._store_facts_as_kg_nodes([], user_id=uid)
        assert result == []

    def test_store_facts_short_fact_skipped(self, mem: Memory) -> None:
        """_store_facts_as_kg_nodes skips facts shorter than 4 chars (line 671)."""
        uid = _uid()
        with patch.object(mem, "_ws", return_value="ws-test"):
            with patch.object(mem, "_call", return_value={"id": "nid-ok"}) as mock_call:
                result = mem._store_facts_as_kg_nodes(["ab", "c", "valid fact"], user_id=uid)
                # Only "valid fact" should be stored
                assert mock_call.call_count == 1
                assert len(result) == 1

    def test_store_facts_with_agent_id(self, mem: Memory) -> None:
        """_store_facts_as_kg_nodes includes agent_id in metadata (line 675)."""
        uid = _uid()
        with patch.object(mem, "_ws", return_value="ws-test"):
            with patch.object(mem, "_call", return_value={"id": "nid-1"}) as mock_call:
                result = mem._store_facts_as_kg_nodes(
                    ["fact about agent"], user_id=uid, agent_id="my-agent"
                )
                call_kwargs = mock_call.call_args[1]
                meta = json.loads(call_kwargs["metadata_json"])
                assert meta["agent_id"] == "my-agent"
                assert len(result) == 1

    def test_store_facts_runtime_error_per_fact(self, mem: Memory) -> None:
        """_store_facts_as_kg_nodes handles RuntimeError per fact (line 689-690)."""
        uid = _uid()
        with patch.object(mem, "_ws", return_value="ws-test"):
            # First fact raises, second succeeds
            with patch.object(
                mem,
                "_call",
                side_effect=[
                    RuntimeError("node creation failed"),
                    {"id": "nid-ok"},
                ],
            ):
                result = mem._store_facts_as_kg_nodes(["good fact 1", "good fact 2"], user_id=uid)
                # Only the second one should succeed
                assert len(result) == 1
                assert result[0] == "nid-ok"

    def test_store_facts_non_dict_result(self, mem: Memory) -> None:
        """_store_facts_as_kg_nodes with non-dict result (no id)."""
        uid = _uid()
        with patch.object(mem, "_ws", return_value="ws-test"):
            with patch.object(mem, "_call", return_value="just-a-string"):
                result = mem._store_facts_as_kg_nodes(["valid fact here"], user_id=uid)
                assert result == []  # non-dict result gives no id


# ---------------------------------------------------------------------------
# _handle_message_list and _try_infer_merge coverage (mocked)
# ---------------------------------------------------------------------------




class TestHandleMessageList:
    """Cover _handle_message_list paths."""

    def test_message_list_no_infer(self, mem: Memory) -> None:
        """_handle_message_list with infer=False → non-infer path (lines 761-762)."""
        messages = [
            {"role": "user", "content": "Hello there"},
            {"role": "assistant", "content": "Hi, how can I help?"},
        ]
        content, summary = mem._handle_message_list(
            messages, user_id=None, agent_id=None, run_id=None, infer=False
        )
        assert "Hello there" in content
        assert "Hi, how can I help" in content

    def test_message_list_infer_no_llm(self, mem: Memory) -> None:
        """_handle_message_list with infer=True but no LLM available."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        with patch.object(mem, "_resolve_llm_for", return_value=None):
            content, summary = mem._handle_message_list(
                messages, user_id=None, agent_id=None, run_id=None, infer=True
            )
            assert content in ("Hello Hi", "Hello Hi")

    def test_message_list_infer_llm_error(self, mem: Memory) -> None:
        """_handle_message_list with infer=True, LLM raises RuntimeError (lines 740-741)."""
        messages = [{"role": "user", "content": "Test"}]
        fake_llm = type(
            "FakeLLM",
            (),
            {
                "available": True,
                "extract_facts": lambda self, x: (_ for _ in ()).throw(RuntimeError("LLM down")),
            },
        )()
        with patch.object(mem, "_resolve_llm_for", return_value=fake_llm):
            content, summary = mem._handle_message_list(
                messages, user_id=None, agent_id=None, run_id=None, infer=True
            )
            assert content == "Test"

    def test_message_list_infer_llm_extraction_success(self, mem: Memory) -> None:
        """_handle_message_list with infer=True and LLM returns facts → recursive add (lines 745-752)."""
        from spacetime_memory.sdks.mem0 import _InferMergeDone

        messages = [{"role": "user", "content": "I live in Paris and like cheese"}]
        fake_llm = type(
            "FakeLLM",
            (),
            {
                "available": True,
                "extract_facts": lambda self, x: ["User lives in Paris", "User likes cheese"],
            },
        )()
        with patch.object(mem, "_resolve_llm_for", return_value=fake_llm):
            # The recursive add() call will be handled
            fake_add_result = {
                "results": [{"id": "f1", "memory": "User lives in Paris", "event": "ADD"}],
                "relation_events": [],
            }
            with patch.object(mem, "add", return_value=fake_add_result):
                with pytest.raises(_InferMergeDone) as exc_info:
                    mem._handle_message_list(
                        messages, user_id="u1", agent_id=None, run_id=None, infer=True
                    )
                result = exc_info.value.args[0]
                assert len(result["results"]) == 2  # Two facts stored
                assert result["results"][0]["memory"] == "User lives in Paris"




class TestTryInferMerge:
    """Cover _try_infer_merge paths (lines 765-810)."""

    def test_try_infer_merge_no_close_matches(self, mem: Memory) -> None:
        """_try_infer_merge returns None when no close matches (line 781)."""
        uid = _uid()
        with patch.object(
            mem, "search", return_value={"results": [{"id": "m1", "memory": "test", "score": 0.3}]}
        ):
            result = mem._try_infer_merge("new content", user_id=uid, agent_id=None)
            assert result is None

    def test_try_infer_merge_empty_results(self, mem: Memory) -> None:
        """_try_infer_merge returns None when search returns empty results."""
        with patch.object(mem, "search", return_value={"results": []}):
            result = mem._try_infer_merge("content", user_id=None, agent_id=None)
            assert result is None

    def test_try_infer_merge_success_no_llm(self, mem: Memory) -> None:
        """_try_infer_merge merges with existing memory (no LLM facts)."""
        uid = _uid()
        with patch.object(
            mem,
            "search",
            return_value={"results": [{"id": "mem-1", "memory": "Existing", "score": 0.95}]},
        ), patch.object(mem, "update") as mock_update:
            with patch.object(mem, "_resolve_llm_for", return_value=None):
                result = mem._try_infer_merge("Appended", user_id=uid, agent_id=None)
                mock_update.assert_called_once()
                assert result is not None
                assert result["results"][0]["event"] == "UPDATE"
                assert "Existing" in result["results"][0]["memory"]
                assert "Appended" in result["results"][0]["memory"]

    def test_try_infer_merge_llm_facts_error(self, mem: Memory) -> None:
        """_try_infer_merge handles LLM fact extraction error (lines 799-800)."""
        uid = _uid()
        fake_llm = type(
            "FakeLLM",
            (),
            {
                "available": True,
                "extract_facts": lambda self, x: (_ for _ in ()).throw(RuntimeError("LLM boom")),
            },
        )()
        with patch.object(
            mem,
            "search",
            return_value={"results": [{"id": "mem-2", "memory": "Old", "score": 0.90}]},
        ), patch.object(mem, "update"):
            with patch.object(mem, "_resolve_llm_for", return_value=fake_llm):
                result = mem._try_infer_merge("New", user_id=uid, agent_id=None)
                assert result is not None
                assert result["results"][0]["event"] == "UPDATE"

    def test_try_infer_merge_llm_facts_success(self, mem: Memory) -> None:
        """_try_infer_merge with LLM facts extraction success (lines 793-795)."""
        uid = _uid()
        fake_llm = type(
            "FakeLLM",
            (),
            {
                "available": True,
                "extract_facts": lambda self, x: ["fact A", "fact B"],
            },
        )()
        with patch.object(
            mem,
            "search",
            return_value={"results": [{"id": "mem-3", "memory": "Existing", "score": 0.92}]},
        ), patch.object(mem, "update"), patch.object(mem, "_store_facts_as_kg_nodes") as mock_store:
            with patch.object(mem, "_call") as mock_call:
                with patch.object(mem, "_resolve_llm_for", return_value=fake_llm):
                    result = mem._try_infer_merge(
                        "New fact", user_id=uid, agent_id="agent1"
                    )
                    assert result is not None
                    assert result["results"][0]["event"] == "UPDATE"
                    mock_store.assert_called_once_with(["fact A", "fact B"], uid, "agent1")
                    # update_memory is called with extracted facts
                    assert mock_call.called


# ---------------------------------------------------------------------------
# add() specific paths (mocked)
# ---------------------------------------------------------------------------




class TestAddSpecificPaths:
    """Cover add() paths: infer merge, facts, scope, LLM error."""

    def test_add_infer_merge_activated(self, mem: Memory) -> None:
        """add() triggers _try_infer_merge when infer=True and content is string."""
        uid = _uid()
        merge_result = {
            "results": [
                {
                    "id": "merged-1",
                    "memory": "Merged",
                    "event": "UPDATE",
                    "user_id": uid,
                    "agent_id": "",
                }
            ],
            "relation_events": [],
        }
        with patch.object(mem, "_try_infer_merge", return_value=merge_result):
            result = mem.add("content", user_id=uid)
            assert result["results"][0]["event"] == "UPDATE"

    def test_add_llm_error_in_add(self, mem: Memory) -> None:
        """add() handles LLM fact extraction RuntimeError gracefully (lines 896-897)."""
        uid = _uid()
        fake_llm = type(
            "FakeLLM",
            (),
            {
                "available": True,
                "extract_facts": lambda self, x: (_ for _ in ()).throw(RuntimeError("LLM fail")),
            },
        )()
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem, "_try_infer_merge", return_value=None):
                with patch.object(mem, "_resolve_llm_for", return_value=fake_llm):
                    with patch.object(
                        mem,
                        "_call",
                        side_effect=[
                            None,  # store
                            [
                                {"entity_id": "mem-x", "memory_content": "content"}
                            ],  # search for scope
                            [{"entity_id": "mem-x", "memory_content": "content"}],  # final search
                        ],
                    ):
                        with patch.object(
                            mem._client, "_call", return_value=None
                        ):  # set_memory_scope
                            result = mem.add("content", user_id=uid)
                            assert "results" in result

    def test_add_set_memory_scope_failure(self, mem: Memory) -> None:
        """add() set_memory_scope failure is logged not raised (lines 926-927)."""
        uid = _uid()
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem, "_try_infer_merge", return_value=None):
                with patch.object(mem, "_resolve_llm_for", return_value=None):
                    with patch.object(
                        mem,
                        "_call",
                        side_effect=[
                            None,  # store
                            [
                                {"entity_id": "mem-x", "memory_content": "content"}
                            ],  # search for scope
                            [{"entity_id": "mem-y", "memory_content": "content"}],  # final search
                        ],
                    ):
                        with patch.object(
                            mem._client, "_call", side_effect=RuntimeError("scope set failed")
                        ):
                            result = mem.add("content", user_id=uid)
                            assert "results" in result

    def test_add_message_list_infer_merge_done(self, mem: Memory) -> None:
        """add() with message list that triggers _InferMergeDone (line 948)."""
        from spacetime_memory.sdks.mem0 import _InferMergeDone

        uid = _uid()
        fake_results = {
            "results": [{"id": "f1", "memory": "fact1", "event": "ADD"}],
            "relation_events": [],
        }
        with patch.object(mem, "_handle_message_list", side_effect=_InferMergeDone(fake_results)):
            result = mem.add([{"role": "user", "content": "test"}], user_id=uid)
            assert result["results"][0]["memory"] == "fact1"

    def test_add_with_extracted_facts_from_llm(self, mem: Memory) -> None:
        """add() with LLM returning extracted_facts (lines 901, 916)."""
        uid = _uid()
        fake_llm = type(
            "FakeLLM",
            (),
            {
                "available": True,
                "extract_facts": lambda self, x: ["fact one", "fact two"],
            },
        )()
        with patch.object(mem, "_ws", return_value="ws-mock"):
            with patch.object(mem, "_try_infer_merge", return_value=None):
                with patch.object(mem, "_resolve_llm_for", return_value=fake_llm):
                    with patch.object(mem, "_store_facts_as_kg_nodes") as mock_store:
                        with patch.object(
                            mem,
                            "_call",
                            side_effect=[
                                None,  # store
                                [{"entity_id": "mem-f", "memory_content": "test"}],  # search scope
                                [{"entity_id": "mem-f", "memory_content": "test"}],  # final search
                            ],
                        ):
                            with patch.object(mem._client, "_call", return_value=None):
                                result = mem.add("test content", user_id=uid)
                                assert "results" in result
                                # Facts should have been stored as KG nodes
                                mock_store.assert_called_once_with(
                                    ["fact one", "fact two"], uid, None
                                )


# ---------------------------------------------------------------------------
# search() specific paths (mocked)
# ---------------------------------------------------------------------------


