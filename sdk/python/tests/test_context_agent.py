"""Tests for ContextAgent — comprehensive unit tests with mocked Client.

Covers:
- __init__
- ask() basic flow, delta, aaak, LLM integration, error handling
- format_context()
- _call_llm(), _call_llm_with_gaps(), _call_local_llm()
- synthesize()
- _esc() helper
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, Mock, patch

import pytest

from spacetime_memory.context_agent import ContextAgent, _esc


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _make_pack(pack_id="pack-1", entries_data=None, created_at=1000):
    """Build a mock context_pack dict with given entries."""
    if entries_data is None:
        entries_data = [{"content": "test entry", "score": 0.9}]
    return {
        "id": pack_id,
        "created_at": created_at,
        "pack_json": json.dumps(entries_data),
    }


def _make_client():
    """Return a MagicMock with default returns for _call and _query."""
    c = MagicMock()
    c._call.return_value = {"status": "ok"}
    c._query.return_value = []
    return c


# ─────────────────────────────────────────────────────────────────────
# __init__
# ─────────────────────────────────────────────────────────────────────


class TestInit:
    """ContextAgent.__init__ stores the client."""

    def test_init_stores_client(self):
        client = _make_client()
        agent = ContextAgent(client)
        assert agent._client is client


# ─────────────────────────────────────────────────────────────────────
# format_context
# ─────────────────────────────────────────────────────────────────────


class TestFormatContext:
    """format_context() builds a text block from entries."""

    def test_empty_entries_returns_empty_string(self):
        agent = ContextAgent(_make_client())
        assert agent.format_context([]) == ""

    def test_formats_content_and_score(self):
        agent = ContextAgent(_make_client())
        entries = [
            {"content": "hello world", "score": 0.95},
            {"content": "foo bar", "score": 0.5},
        ]
        result = agent.format_context(entries)
        assert "[1] (score=0.950) hello world" in result
        assert "[2] (score=0.500) foo bar" in result

    def test_falls_back_to_memory_content(self):
        agent = ContextAgent(_make_client())
        entries = [{"memory_content": "alt content", "rank": 3}]
        result = agent.format_context(entries)
        assert "alt content" in result
        assert "score=3.000" in result

    def test_truncates_long_content_to_500_chars(self):
        agent = ContextAgent(_make_client())
        long_text = "x" * 1000
        entries = [{"content": long_text, "score": 0.5}]
        result = agent.format_context(entries)
        # The content after the score prefix should be 500 chars
        line = result.split("\n\n")[0]
        # Extract just the content part after the score marker
        content_part = line.split(") ", 1)[1]
        assert len(content_part) == 500

    def test_uses_rank_as_score_fallback(self):
        agent = ContextAgent(_make_client())
        entries = [{"content": "a", "rank": 5}]
        result = agent.format_context(entries)
        assert "score=5.000" in result

    def test_uses_zero_when_no_score_or_rank(self):
        agent = ContextAgent(_make_client())
        entries = [{"content": "bare entry"}]
        result = agent.format_context(entries)
        assert "score=0.000" in result

    def test_multiple_entries_separated_by_double_newline(self):
        agent = ContextAgent(_make_client())
        entries = [
            {"content": "first", "score": 1.0},
            {"content": "second", "score": 0.5},
        ]
        result = agent.format_context(entries)
        assert "\n\n" in result
        assert result.startswith("[1]")


# ─────────────────────────────────────────────────────────────────────
# ask() — basic flow
# ─────────────────────────────────────────────────────────────────────


class TestAskBasic:
    """ask() basic pipeline with mocked client."""

    def test_basic_ask_returns_pack_and_entries(self):
        client = _make_client()
        pack = _make_pack()
        client._query.return_value = [pack]
        agent = ContextAgent(client)

        result = agent.ask("test query", "ws-1")

        client._call.assert_called_once_with(
            "generate_context_pack",
            ["ws-1", "test query", 4096, "", ""],
        )
        client._query.assert_called_once_with(
            "context_pack", workspace_id="ws-1"
        )
        assert result["pack"] == pack
        assert result["entries"] == [{"content": "test entry", "score": 0.9}]
        assert "delta" not in result

    def test_no_packs_returns_error(self):
        client = _make_client()
        client._query.return_value = []
        agent = ContextAgent(client)

        result = agent.ask("test query", "ws-1")
        assert result == {"error": "No context pack generated"}

    def test_custom_token_budget_passed_to_generator(self):
        client = _make_client()
        client._query.return_value = [_make_pack()]
        agent = ContextAgent(client)

        agent.ask("q", "ws", token_budget=8000)
        client._call.assert_called_once_with(
            "generate_context_pack",
            ["ws", "q", 8000, "", ""],
        )

    def test_sorts_packs_by_created_at_descending(self):
        client = _make_client()
        packs = [
            {"id": "old", "created_at": 500, "pack_json": json.dumps([{"content": "old"}])},
            {"id": "new", "created_at": 2000, "pack_json": json.dumps([{"content": "new"}])},
        ]
        client._query.return_value = packs
        agent = ContextAgent(client)

        result = agent.ask("q", "ws")
        assert result["pack"]["id"] == "new"

    def test_entries_sorted_by_score_descending(self):
        client = _make_client()
        entries = [
            {"content": "low", "score": 0.1},
            {"content": "high", "score": 0.9},
            {"content": "mid", "score": 0.5},
        ]
        client._query.return_value = [_make_pack(entries_data=entries)]
        agent = ContextAgent(client)

        result = agent.ask("q", "ws")
        scores = [e["score"] for e in result["entries"]]
        assert scores == [0.9, 0.5, 0.1]

    def test_entries_sorted_by_rank_fallback(self):
        client = _make_client()
        entries = [
            {"content": "a", "rank": 1},
            {"content": "c", "rank": 3},
            {"content": "b", "rank": 2},
        ]
        client._query.return_value = [_make_pack(entries_data=entries)]
        agent = ContextAgent(client)

        result = agent.ask("q", "ws")
        ranks = [e["rank"] for e in result["entries"]]
        assert ranks == [3, 2, 1]

    def test_entries_with_no_score_or_rank_get_zero(self):
        client = _make_client()
        entries = [
            {"content": "no_score_1"},
            {"content": "no_score_2", "score": 0.5},
        ]
        client._query.return_value = [_make_pack(entries_data=entries)]
        agent = ContextAgent(client)

        result = agent.ask("q", "ws")
        # First entry should be the one with score 0.5
        assert result["entries"][0]["score"] == 0.5
        # Second entry is the one with no score (sorted as 0)
        assert "score" not in result["entries"][1]


# ─────────────────────────────────────────────────────────────────────
# ask() — pack_json parsing
# ─────────────────────────────────────────────────────────────────────


class TestAskPackJsonParsing:
    """Tests for various pack_json formats in ask()."""

    def test_pack_json_dict_with_entries_key(self):
        client = _make_client()
        pack = {
            "id": "p1",
            "created_at": 1000,
            "pack_json": json.dumps({"entries": [{"content": "e1", "score": 0.8}]}),
        }
        client._query.return_value = [pack]
        agent = ContextAgent(client)

        result = agent.ask("q", "ws")
        assert len(result["entries"]) == 1
        assert result["entries"][0]["content"] == "e1"

    def test_pack_json_dict_with_memories_key(self):
        client = _make_client()
        pack = {
            "id": "p1",
            "created_at": 1000,
            "pack_json": json.dumps({"memories": [{"content": "m1", "score": 0.7}]}),
        }
        client._query.return_value = [pack]
        agent = ContextAgent(client)

        result = agent.ask("q", "ws")
        assert len(result["entries"]) == 1
        assert result["entries"][0]["content"] == "m1"

    def test_pack_json_dict_with_neither_entries_nor_memories(self):
        client = _make_client()
        pack = {
            "id": "p1",
            "created_at": 1000,
            "pack_json": json.dumps({"other": "value"}),
        }
        client._query.return_value = [pack]
        agent = ContextAgent(client)

        result = agent.ask("q", "ws")
        assert result["entries"] == []

    def test_pack_json_invalid_json_returns_empty_entries(self):
        client = _make_client()
        pack = {
            "id": "p1",
            "created_at": 1000,
            "pack_json": "not valid json{{{",
        }
        client._query.return_value = [pack]
        agent = ContextAgent(client)

        result = agent.ask("q", "ws")
        assert result["entries"] == []

    def test_pack_json_none_returns_empty_entries(self):
        client = _make_client()
        pack = {
            "id": "p1",
            "created_at": 1000,
            "pack_json": json.dumps(None),
        }
        client._query.return_value = [pack]
        agent = ContextAgent(client)

        result = agent.ask("q", "ws")
        assert result["entries"] == []

    def test_pack_json_non_list_non_dict(self):
        client = _make_client()
        pack = {
            "id": "p1",
            "created_at": 1000,
            "pack_json": json.dumps(42),
        }
        client._query.return_value = [pack]
        agent = ContextAgent(client)

        result = agent.ask("q", "ws")
        assert result["entries"] == []

    def test_pack_json_string_that_is_valid_list_of_dicts(self):
        """Valid JSON list of dict entries."""
        client = _make_client()
        pack = {
            "id": "p1",
            "created_at": 1000,
            "pack_json": json.dumps([{"content": "a", "score": 0.8}, {"content": "b", "score": 0.3}]),
        }
        client._query.return_value = [pack]
        agent = ContextAgent(client)

        result = agent.ask("q", "ws")
        assert len(result["entries"]) == 2
        assert result["entries"][0]["content"] == "a"
        assert result["entries"][1]["content"] == "b"

    def test_pack_json_is_missing(self):
        client = _make_client()
        pack = {
            "id": "p1",
            "created_at": 1000,
        }
        client._query.return_value = [pack]
        agent = ContextAgent(client)

        result = agent.ask("q", "ws")
        assert result["entries"] == []

    def test_pack_json_type_error(self):
        """TypeError during json.loads (non-string pack_json)."""
        client = _make_client()
        pack = {
            "id": "p1",
            "created_at": 1000,
            "pack_json": 42,  # int, not string — TypeError from json.loads
        }
        client._query.return_value = [pack]
        agent = ContextAgent(client)

        result = agent.ask("q", "ws")
        assert result["entries"] == []


# ─────────────────────────────────────────────────────────────────────
# ask() — delta path
# ─────────────────────────────────────────────────────────────────────


class TestAskWithDelta:
    """ask() with previous_pack_id triggers the delta path."""

    def test_delta_computed_when_previous_pack_id_provided(self):
        client = _make_client()
        pack = _make_pack()
        delta_rows = [{"delta_type": "added", "entry_id": "e1"}]
        client._query.side_effect = [  # first call: context_pack, second: context_delta
            [pack],
            delta_rows,
        ]
        agent = ContextAgent(client)

        result = agent.ask("q", "ws", previous_pack_id="prev-pack-1")

        # Verify both _call invocations
        assert client._call.call_count == 2
        client._call.assert_any_call("generate_context_pack", ["ws", "q", 4096, "", "prev-pack-1"])
        client._call.assert_any_call("get_delta", ["prev-pack-1"])
        # Verify _query was called for context_pack and context_delta
        assert client._query.call_count == 2
        client._query.assert_any_call("context_pack", workspace_id="ws")
        client._query.assert_any_call(
            "context_delta",
            filter_dict={"previous_pack_id": "prev-pack-1"},
        )
        assert "delta" in result
        assert result["delta"] == delta_rows

    def test_delta_not_computed_when_no_previous_pack_id(self):
        client = _make_client()
        pack = _make_pack()
        client._query.return_value = [pack]
        agent = ContextAgent(client)

        result = agent.ask("q", "ws", previous_pack_id="")
        assert "delta" not in result
        # Only one _call for generate_context_pack
        assert client._call.call_count == 1


# ─────────────────────────────────────────────────────────────────────
# ask() — AAAK compression
# ─────────────────────────────────────────────────────────────────────


class TestAskWithAaak:
    """ask() with aaak=True compresses entry content/summary."""

    def test_aaak_compresses_non_empty_content(self):
        client = _make_client()
        entries = [
            {"content": "PREFERENCE: User asked for dark mode", "score": 0.9},
            {"content": "", "score": 0.5},  # empty — not compressed
        ]
        client._query.return_value = [_make_pack(entries_data=entries)]
        agent = ContextAgent(client)

        with patch("spacetime_memory.aaak.aaak_compress") as mock_compress:
            mock_compress.return_value = "COMPRESSED"
            result = agent.ask("q", "ws", aaak=True)

        assert mock_compress.call_count == 1
        mock_compress.assert_called_once_with("PREFERENCE: User asked for dark mode")
        assert result["entries"][0]["content"] == "COMPRESSED"
        assert result["entries"][1]["content"] == ""  # unchanged

    def test_aaak_compresses_summary(self):
        client = _make_client()
        entries = [
            {"content": "test content", "summary": "long summary here", "score": 0.9},
        ]
        client._query.return_value = [_make_pack(entries_data=entries)]
        agent = ContextAgent(client)

        with patch("spacetime_memory.aaak.aaak_compress") as mock_compress:
            mock_compress.side_effect = lambda x: f"Z:{x[:10]}"
            result = agent.ask("q", "ws", aaak=True)

        assert mock_compress.call_count == 2
        assert result["entries"][0]["content"].startswith("Z:")
        assert result["entries"][0]["summary"].startswith("Z:")

    def test_aaak_skips_empty_summary(self):
        client = _make_client()
        entries = [
            {"content": "test", "summary": "", "score": 0.9},
        ]
        client._query.return_value = [_make_pack(entries_data=entries)]
        agent = ContextAgent(client)

        with patch("spacetime_memory.aaak.aaak_compress") as mock_compress:
            mock_compress.return_value = "compressed"
            agent.ask("q", "ws", aaak=True)

        # Only content was non-empty, summary was empty — only 1 call
        assert mock_compress.call_count == 1

    def test_aaak_skips_missing_summary(self):
        client = _make_client()
        entries = [
            {"content": "test", "score": 0.9},
        ]
        client._query.return_value = [_make_pack(entries_data=entries)]
        agent = ContextAgent(client)

        with patch("spacetime_memory.aaak.aaak_compress") as mock_compress:
            mock_compress.return_value = "compressed"
            agent.ask("q", "ws", aaak=True)

        assert mock_compress.call_count == 1

    def test_aaak_false_skips_compression(self):
        client = _make_client()
        entries = [
            {"content": "test content", "score": 0.9},
        ]
        client._query.return_value = [_make_pack(entries_data=entries)]
        agent = ContextAgent(client)

        with patch("spacetime_memory.aaak.aaak_compress") as mock_compress:
            agent.ask("q", "ws", aaak=False)

        mock_compress.assert_not_called()


# ─────────────────────────────────────────────────────────────────────
# ask() — LLM integration
# ─────────────────────────────────────────────────────────────────────


class TestAskLLM:
    """ask() with LLM integration (OPENAI_API_KEY and local fallback)."""

    @pytest.fixture
    def ready_client(self):
        """A client with a valid pack already loaded in _query."""
        c = _make_client()
        c._query.return_value = [_make_pack()]
        return c

    def test_llm_with_openai_api_key(self, ready_client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        agent = ContextAgent(ready_client)

        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "LLM synthesized answer"}}]
        }

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = agent.ask("q", "ws")

        assert "llm_answer" in result
        assert result["llm_answer"] == "LLM synthesized answer"
        mock_post.assert_called_once()

    def test_llm_with_litellm_master_key(self, ready_client, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("LITELLM_MASTER_KEY", "litellm-key")
        agent = ContextAgent(ready_client)

        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "lite llm answer"}}]
        }

        with patch("httpx.post", return_value=mock_resp):
            result = agent.ask("q", "ws")

        assert result["llm_answer"] == "lite llm answer"

    def test_llm_call_exception_returns_error_string(self, ready_client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        agent = ContextAgent(ready_client)

        with patch("httpx.post", side_effect=Exception("Network error")):
            result = agent.ask("q", "ws")

        assert result["llm_answer"].startswith("[LLM call failed: ")
        assert "Network error" in result["llm_answer"]

    def test_no_llm_no_api_key_no_local(self, ready_client, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        agent = ContextAgent(ready_client)

        with patch("spacetime_memory.local_llm.LocalLLM") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.available = False
            mock_llm_class.auto.return_value = mock_llm

            result = agent.ask("q", "ws")

        assert "llm_answer" not in result

    def test_llm_with_custom_base_url_and_model(self, ready_client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://custom.api.com/v1")
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        agent = ContextAgent(ready_client)

        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "custom model answer"}}]
        }

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            agent.ask("q", "ws")

        call_args = mock_post.call_args
        assert "https://custom.api.com/v1/chat/completions" in call_args[0]
        sent_json = call_args[1]["json"]
        assert sent_json["model"] == "gpt-4o"

    def test_local_llm_fallback_when_available(self, ready_client, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        agent = ContextAgent(ready_client)

        with patch("spacetime_memory.local_llm.LocalLLM") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.available = True
            mock_llm.generate.return_value = "local model answer"
            mock_llm_class.auto.return_value = mock_llm

            result = agent.ask("q", "ws")

        assert result["llm_answer"] == "local model answer"

    def test_ask_with_llm_and_delta(self, ready_client, monkeypatch):
        """Full integration: delta + LLM in one call."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        ready_client._query.side_effect = [
            [_make_pack()],           # context_pack
            [{"delta_type": "added"}],  # context_delta
        ]
        agent = ContextAgent(ready_client)

        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "delta aware answer"}}]
        }

        with patch("httpx.post", return_value=mock_resp):
            result = agent.ask("q", "ws", previous_pack_id="prev-1")

        assert "delta" in result
        assert result["llm_answer"] == "delta aware answer"


# ─────────────────────────────────────────────────────────────────────
# _call_llm
# ─────────────────────────────────────────────────────────────────────


class TestCallLLM:
    """Direct tests for _call_llm()."""

    def test_no_api_key_calls_local_llm(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        agent = ContextAgent(_make_client())

        with patch.object(agent, "_call_local_llm", return_value="local") as mock_local:
            result = agent._call_llm("q", [{"content": "ctx", "score": 0.8}])

        mock_local.assert_called_once()
        assert result == "local"

    def test_httpx_error_returns_failure_string(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        agent = ContextAgent(_make_client())

        with patch("httpx.post", side_effect=ConnectionError("refused")):
            result = agent._call_llm("q", [])

        assert result == "[LLM call failed: refused]"

    def test_raise_for_status_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        agent = ContextAgent(_make_client())

        mock_resp = Mock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP 500")
        with patch("httpx.post", return_value=mock_resp):
            result = agent._call_llm("q", [])

        assert result == "[LLM call failed: HTTP 500]"


# ─────────────────────────────────────────────────────────────────────
# _call_local_llm
# ─────────────────────────────────────────────────────────────────────


class TestCallLocalLLM:
    """Direct tests for _call_local_llm()."""

    def test_local_llm_available_returns_answer(self):
        agent = ContextAgent(_make_client())

        with patch("spacetime_memory.local_llm.LocalLLM") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.available = True
            mock_llm.generate.return_value = "local answer text"
            mock_llm_class.auto.return_value = mock_llm

            result = agent._call_local_llm(
                "test query", [{"content": "context", "score": 0.9}]
            )

        assert result == "local answer text"
        mock_llm.generate.assert_called_once()
        call_args = mock_llm.generate.call_args
        assert call_args[0][0].startswith("Answer the question")
        assert "test query" in call_args[0][0]
        assert "context" in call_args[0][0]

    def test_local_llm_not_available_returns_none(self):
        agent = ContextAgent(_make_client())

        with patch("spacetime_memory.local_llm.LocalLLM") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.available = False
            mock_llm_class.auto.return_value = mock_llm

            result = agent._call_local_llm("q", [])

        assert result is None

    def test_local_llm_generate_raises_runtime_error(self):
        agent = ContextAgent(_make_client())

        with patch("spacetime_memory.local_llm.LocalLLM") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.available = True
            mock_llm.generate.side_effect = RuntimeError("inference failed")
            mock_llm_class.auto.return_value = mock_llm

            result = agent._call_local_llm("q", [])

        assert result is None

    def test_local_llm_generate_raises_value_error(self):
        agent = ContextAgent(_make_client())

        with patch("spacetime_memory.local_llm.LocalLLM") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.available = True
            mock_llm.generate.side_effect = ValueError("bad value")
            mock_llm_class.auto.return_value = mock_llm

            result = agent._call_local_llm("q", [])

        assert result is None

    def test_local_llm_generate_raises_os_error(self):
        agent = ContextAgent(_make_client())

        with patch("spacetime_memory.local_llm.LocalLLM") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.available = True
            mock_llm.generate.side_effect = OSError("file not found")
            mock_llm_class.auto.return_value = mock_llm

            result = agent._call_local_llm("q", [])

        assert result is None


# ─────────────────────────────────────────────────────────────────────
# _call_llm_with_gaps
# ─────────────────────────────────────────────────────────────────────


class TestCallLLMWithGaps:
    """Direct tests for _call_llm_with_gaps()."""

    def test_no_api_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        agent = ContextAgent(_make_client())

        result = agent._call_llm_with_gaps("query", [])
        assert result is None

    def test_with_api_key_returns_parsed_json(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        agent = ContextAgent(_make_client())

        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "answer": "synthesized answer",
                        "gaps": ["missing fact 1"],
                        "sources": [1],
                        "confidence": 0.85,
                    })
                }
            }]
        }

        with patch("httpx.post", return_value=mock_resp):
            result = agent._call_llm_with_gaps("q", [{"content": "ctx", "score": 0.8}])

        assert result == {
            "answer": "synthesized answer",
            "gaps": ["missing fact 1"],
            "sources": [1],
            "confidence": 0.85,
        }

    def test_api_call_exception_returns_none(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        agent = ContextAgent(_make_client())

        with patch("httpx.post", side_effect=Exception("fail")):
            result = agent._call_llm_with_gaps("q", [])

        assert result is None

    def test_invalid_json_in_response_returns_none(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        agent = ContextAgent(_make_client())

        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "not json at all"}}]
        }

        with patch("httpx.post", return_value=mock_resp):
            result = agent._call_llm_with_gaps("q", [])

        assert result is None

    def test_litellm_master_key_fallback(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("LITELLM_MASTER_KEY", "master-key")
        agent = ContextAgent(_make_client())

        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"answer": "test", "gaps": [], "sources": [1], "confidence": 1.0}'}}]
        }

        with patch("httpx.post", return_value=mock_resp):
            result = agent._call_llm_with_gaps("q", [])

        assert result["answer"] == "test"

    def test_formats_context_and_calls_correct_endpoint(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        agent = ContextAgent(_make_client())

        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"answer":"a","gaps":[],"sources":[],"confidence":0.5}'}}]
        }

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            agent._call_llm_with_gaps("test query", [{"content": "data", "score": 0.9}])

        call_args = mock_post.call_args
        assert "https://api.openai.com/v1/chat/completions" in call_args[0]
        sent_json = call_args[1]["json"]
        assert sent_json["model"] == "gpt-4o-mini"
        assert sent_json["response_format"] == {"type": "json_object"}
        messages = sent_json["messages"]
        assert messages[0]["role"] == "system"
        assert "gap analysis" in messages[0]["content"].lower()
        assert messages[1]["role"] == "user"
        assert "test query" in messages[1]["content"]
        assert "data" in messages[1]["content"]


# ─────────────────────────────────────────────────────────────────────
# synthesize()
# ─────────────────────────────────────────────────────────────────────


class TestSynthesize:
    """Tests for synthesize() method."""

    def test_synthesize_basic_flow(self):
        client = _make_client()
        pack = _make_pack()
        client._query.return_value = [pack]
        agent = ContextAgent(client)

        with patch.object(agent, "_call_llm_with_gaps") as mock_gaps:
            mock_gaps.return_value = {
                "answer": "synthesized answer",
                "gaps": ["gap1"],
                "sources": [1],
                "confidence": 0.85,
            }
            result = agent.synthesize("q", "ws")

        assert "pack" in result
        assert result["pack"] == pack
        assert result["answer"] == "synthesized answer"
        assert result["gaps"] == ["gap1"]
        assert result["sources"] == [1]
        assert result["confidence"] == 0.85

    def test_synthesize_no_packs_returns_error(self):
        client = _make_client()
        client._query.return_value = []
        agent = ContextAgent(client)

        result = agent.synthesize("q", "ws")
        assert result == {"error": "No context pack generated", "answer": None, "gaps": []}

    def test_synthesize_llm_unavailable(self):
        client = _make_client()
        client._query.return_value = [_make_pack()]
        agent = ContextAgent(client)

        with patch.object(agent, "_call_llm_with_gaps", return_value=None):
            result = agent.synthesize("q", "ws")

        assert result["answer"] is None
        assert result["gaps"] == []
        assert result["sources"] == []
        assert result["confidence"] == 0.0
        assert result["pack"] is not None

    def test_synthesize_calls_generate_context_pack(self):
        client = _make_client()
        client._query.return_value = [_make_pack()]
        agent = ContextAgent(client)

        with patch.object(agent, "_call_llm_with_gaps", return_value=None):
            agent.synthesize("my query", "my-ws", token_budget=2048)

        client._call.assert_called_once_with(
            "generate_context_pack",
            ["my-ws", "my query", 2048, "", ""],
        )

    def test_synthesize_parses_entries_from_dict(self):
        client = _make_client()
        pack = {
            "id": "p1",
            "created_at": 1000,
            "pack_json": json.dumps({"entries": [{"content": "e1", "score": 0.9}]}),
        }
        client._query.return_value = [pack]
        agent = ContextAgent(client)

        with patch.object(agent, "_call_llm_with_gaps") as mock_gaps:
            mock_gaps.return_value = {"answer": "a", "gaps": [], "sources": [1], "confidence": 1.0}
            result = agent.synthesize("q", "ws")

        # Verify the entries were passed to _call_llm_with_gaps
        mock_gaps.assert_called_once()
        call_entries = mock_gaps.call_args[0][1]
        assert len(call_entries) == 1
        assert call_entries[0]["content"] == "e1"

    def test_synthesize_sorts_entries_by_score(self):
        client = _make_client()
        entries = [
            {"content": "low", "score": 0.1},
            {"content": "high", "score": 0.9},
        ]
        client._query.return_value = [_make_pack(entries_data=entries)]
        agent = ContextAgent(client)

        with patch.object(agent, "_call_llm_with_gaps") as mock_gaps:
            mock_gaps.return_value = {"answer": "a", "gaps": [], "sources": [1], "confidence": 1.0}
            agent.synthesize("q", "ws")

        call_entries = mock_gaps.call_args[0][1]
        assert call_entries[0]["content"] == "high"
        assert call_entries[1]["content"] == "low"

    def test_synthesize_pack_json_error_handling(self):
        client = _make_client()
        pack = {
            "id": "p1",
            "created_at": 1000,
            "pack_json": "invalid{{{",
        }
        client._query.return_value = [pack]
        agent = ContextAgent(client)

        with patch.object(agent, "_call_llm_with_gaps") as mock_gaps:
            mock_gaps.return_value = {"answer": "a", "gaps": [], "sources": [], "confidence": 0.0}
            result = agent.synthesize("q", "ws")

        # Should not crash; entries should be empty
        mock_gaps.assert_called_once_with("q", [], pack)

    def test_synthesize_with_aaak_compression(self):
        """synthesize() with aaak=True compresses entries."""
        client = _make_client()
        entries = [
            {"content": "test content here", "summary": "test summary", "score": 0.9},
        ]
        client._query.return_value = [_make_pack(entries_data=entries)]
        agent = ContextAgent(client)

        with patch.object(agent, "_call_llm_with_gaps") as mock_gaps:
            mock_gaps.return_value = {"answer": "a", "gaps": [], "sources": [1], "confidence": 1.0}
            with patch("spacetime_memory.aaak.aaak_compress") as mock_compress:
                mock_compress.return_value = "COMPRESSED"
                result = agent.synthesize("q", "ws", aaak=True)

        assert mock_compress.call_count == 2  # content + summary
        # Verify compressed entries were passed to LLM
        call_entries = mock_gaps.call_args[0][1]
        assert call_entries[0]["content"] == "COMPRESSED"
        assert call_entries[0]["summary"] == "COMPRESSED"


# ─────────────────────────────────────────────────────────────────────
# _esc helper
# ─────────────────────────────────────────────────────────────────────


class TestEsc:
    """Tests for the _esc() helper function."""

    def test_no_quotes(self):
        assert _esc("hello world") == "hello world"

    def test_single_quote(self):
        assert _esc("it's") == "it''s"

    def test_multiple_quotes(self):
        assert _esc("a'b'c") == "a''b''c"

    def test_empty_string(self):
        assert _esc("") == ""


# ─────────────────────────────────────────────────────────────────────
# Edge cases
# ─────────────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Miscellaneous edge cases."""

    def test_ask_with_all_options_enabled(self, monkeypatch):
        """Full kitchen-sink: delta + aaak + LLM."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        client = _make_client()
        entries_data = [
            {"content": "PREFERENCE: dark mode", "summary": "User likes dark mode", "score": 0.9},
        ]
        pack = _make_pack(entries_data=entries_data)
        client._query.side_effect = [
            [pack],
            [{"delta_type": "added"}],
        ]
        agent = ContextAgent(client)

        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Answer with delta"}}]
        }

        # Mock aaak_compress to return shortened text
        real_aaak = __import__("spacetime_memory.aaak", fromlist=["aaak_compress"])
        with patch("httpx.post", return_value=mock_resp):
            result = agent.ask("q", "ws", previous_pack_id="prev", aaak=True)

        assert "pack" in result
        assert "entries" in result
        assert "delta" in result
        assert result["llm_answer"] == "Answer with delta"
        # Content should be compressed
        assert result["entries"][0]["content"] != "PREFERENCE: dark mode"

    def test_ask_repr_no_crash(self):
        """ContextAgent can be repr'd."""
        agent = ContextAgent(_make_client())
        assert "ContextAgent" in repr(agent)

    def test_multiple_entries_with_mixed_presence(self):
        """Entries with varying field presence."""
        client = _make_client()
        entries = [
            {"content": "full entry", "score": 0.9},
            {},  # completely empty entry
            {"content": "no score"},
            {"score": 0.5},  # no content
        ]
        client._query.return_value = [_make_pack(entries_data=entries)]
        agent = ContextAgent(client)

        result = agent.ask("q", "ws")
        assert len(result["entries"]) == 4
        # Sort should not crash on missing fields

    def test_aaak_import_error_handled(self):
        """If aaak module import fails, it should propagate."""
        client = _make_client()
        entries = [{"content": "test", "score": 0.9}]
        client._query.return_value = [_make_pack(entries_data=entries)]
        agent = ContextAgent(client)

        with patch(
            "spacetime_memory.aaak.aaak_compress",
            side_effect=ImportError("no aaak module"),
        ):
            with pytest.raises(ImportError):
                agent.ask("q", "ws", aaak=True)
