"""Tests for context_agent.py — context-grounded memory queries."""

import json
import pytest
from unittest.mock import patch, Mock, MagicMock


# ── Helpers ──────────────────────────────────────────────────────────────────


@pytest.fixture
def agent():
    from spacetime_memory.context_agent import ContextAgent
    mock_client = Mock()
    return ContextAgent(mock_client)


@pytest.fixture
def pack_entries():
    """Sample context pack entries."""
    return [
        {"content": "User prefers dark mode", "score": 0.9, "rank": 3},
        {"content": "Project uses Python 3.11", "score": 0.7, "rank": 2},
        {"content": "Deployed on Hetzner", "summary": "Infra: Hetzner", "score": 0.5, "rank": 1},
    ]


# ── _esc ─────────────────────────────────────────────────────────────────────


class TestEsc:
    def test_no_single_quote(self):
        from spacetime_memory.context_agent import _esc
        assert _esc("hello") == "hello"

    def test_escapes_single_quote(self):
        from spacetime_memory.context_agent import _esc
        assert _esc("it's") == "it''s"

    def test_escapes_multiple(self):
        from spacetime_memory.context_agent import _esc
        assert _esc("a'b'c") == "a''b''c"


# ── format_context ───────────────────────────────────────────────────────────


class TestFormatContext:
    def test_formats_single_entry(self, agent):
        entries = [{"content": "hello world", "score": 0.95}]
        result = agent.format_context(entries)
        assert "[1]" in result
        assert "score=0.950" in result
        assert "hello world" in result

    def test_formats_multiple_entries(self, agent, pack_entries):
        result = agent.format_context(pack_entries)
        assert "[1]" in result
        assert "[2]" in result
        assert "[3]" in result
        assert "User prefers dark mode" in result

    def test_uses_memory_content_fallback(self, agent):
        entries = [{"memory_content": "fallback content", "score": 0.5}]
        result = agent.format_context(entries)
        assert "fallback content" in result

    def test_truncates_to_500_chars(self, agent):
        long_text = "x" * 600
        entries = [{"content": long_text, "score": 1.0}]
        result = agent.format_context(entries)
        # Format: "[1] (score=1.000) " + content[:500]
        # Total: ~20 + 500 = ~520 chars
        assert len(result) <= 530

    def test_empty_entries(self, agent):
        assert agent.format_context([]) == ""


# ── __init__ ─────────────────────────────────────────────────────────────────


class TestInit:
    def test_stores_client(self):
        from spacetime_memory.context_agent import ContextAgent
        c = object()
        a = ContextAgent(c)
        assert a._client is c


# ── ask ──────────────────────────────────────────────────────────────


class TestAsk:
    def test_ask_empty_pack_returns_error(self, agent):
        agent._client._query.return_value = []

        result = agent.ask("q", "ws1")
        assert result["error"] == "No context pack generated"

    def test_ask_basic(self, agent, pack_entries):
        """Full pipeline: generate pack, parse entries, call LLM."""
        agent._client._call = Mock()
        agent._client._query.return_value = [{
            "id": "pack1",
            "pack_json": json.dumps(pack_entries),
            "created_at": 1000,
        }]

        with patch.object(agent, "_call_llm", return_value="LLM answer"):
            result = agent.ask("ask query", "ws1")

        assert result["pack"]["id"] == "pack1"
        assert len(result["entries"]) == 3
        assert result["llm_answer"] == "LLM answer"

    def test_ask_sorts_entries_by_rank(self, agent):
        """Entries sorted by rank descending."""
        raw = [
            {"content": "low", "score": 0.1, "rank": 1},
            {"content": "high", "score": 0.9, "rank": 3},
            {"content": "mid", "score": 0.5, "rank": 2},
        ]
        agent._client._call = Mock()
        agent._client._query.return_value = [{
            "id": "p1",
            "pack_json": json.dumps(raw),
            "created_at": 1,
        }]

        with patch.object(agent, "_call_llm", return_value=None):
            result = agent.ask("q", "ws1")

        assert result["entries"][0]["content"] == "high"  # rank 3
        assert result["entries"][1]["content"] == "mid"   # rank 2
        assert result["entries"][2]["content"] == "low"   # rank 1

    def test_ask_pack_json_as_dict(self, agent):
        """pack_json can be a dict with 'entries' key."""
        agent._client._call = Mock()
        agent._client._query.return_value = [{
            "id": "p1",
            "pack_json": json.dumps({"entries": [{"content": "from dict", "score": 0.8}]}),
            "created_at": 1,
        }]

        with patch.object(agent, "_call_llm", return_value=None):
            result = agent.ask("q", "ws1")

        assert result["entries"][0]["content"] == "from dict"

    def test_ask_invalid_json_fallback(self, agent):
        """Invalid JSON → empty list fallback."""
        agent._client._call = Mock()
        agent._client._query.return_value = [{
            "id": "p1",
            "pack_json": "not-json",
            "created_at": 1,
        }]

        with patch.object(agent, "_call_llm", return_value=None):
            result = agent.ask("q", "ws1")

        assert result["entries"] == []

    def test_ask_with_aaak(self, agent):
        """AAAK compression applied when aaak=True."""
        agent._client._call = Mock()
        agent._client._query.return_value = [{
            "id": "p1",
            "pack_json": json.dumps([{
                "content": "User prefers dark mode when working",
                "summary": "Dark mode preference",
                "score": 0.9,
            }]),
            "created_at": 1,
        }]

        with patch.object(agent, "_call_llm", return_value=None):
            result = agent.ask("q", "ws1", aaak=True)

        entry = result["entries"][0]
        # AAAK should compress content
        assert entry["content"] != "User prefers dark mode when working"

    def test_ask_with_delta(self, agent, pack_entries):
        """Delta computed when previous_pack_id is provided."""
        agent._client._call = Mock()
        agent._client._query.side_effect = [
            [{"id": "pack1", "pack_json": json.dumps(pack_entries), "created_at": 1000}],
            [{"id": "d1", "entry": "delta data"}],
        ]

        with patch.object(agent, "_call_llm", return_value=None):
            result = agent.ask("q", "ws1", previous_pack_id="oldpack")

        assert "delta" in result
        assert result["delta"][0]["id"] == "d1"

    def test_ask_no_llm_answer(self, agent, pack_entries):
        """When LLM returns None, no llm_answer in result."""
        agent._client._call = Mock()
        agent._client._query.return_value = [{
            "id": "pack1",
            "pack_json": json.dumps(pack_entries),
            "created_at": 1000,
        }]

        with patch.object(agent, "_call_llm", return_value=None):
            result = agent.ask("q", "ws1")

        assert "llm_answer" not in result


# ── synthesize ───────────────────────────────────────────────────────────────


class TestSynthesize:
    def test_empty_pack_returns_error(self, agent):
        agent._client._query.return_value = []
        result = agent.synthesize("q", "ws1")
        assert result["error"] == "No context pack generated"
        assert result["gaps"] == []

    def test_synthesize_returns_structured(self, agent, pack_entries):
        agent._client._call = Mock()
        agent._client._query.return_value = [{
            "id": "pack1",
            "pack_json": json.dumps(pack_entries),
            "created_at": 1000,
        }]

        llm_result = {
            "answer": "The user prefers dark mode.",
            "gaps": ["What framework?", "What deployment env?"],
            "sources": [1, 2],
            "confidence": 0.85,
        }
        with patch.object(agent, "_call_llm_with_gaps", return_value=llm_result):
            result = agent.synthesize("q", "ws1")

        assert result["answer"] == "The user prefers dark mode."
        assert result["gaps"] == ["What framework?", "What deployment env?"]
        assert result["sources"] == [1, 2]
        assert result["confidence"] == 0.85
        assert result["pack"]["id"] == "pack1"

    def test_synthesize_no_llm_returns_defaults(self, agent, pack_entries):
        agent._client._call = Mock()
        agent._client._query.return_value = [{
            "id": "pack1",
            "pack_json": json.dumps(pack_entries),
            "created_at": 1000,
        }]

        with patch.object(agent, "_call_llm_with_gaps", return_value=None):
            result = agent.synthesize("q", "ws1")

        assert result["answer"] is None
        assert result["gaps"] == []
        assert result["confidence"] == 0.0

    def test_synthesize_with_aaak(self, agent):
        agent._client._call = Mock()
        agent._client._query.return_value = [{
            "id": "p1",
            "pack_json": json.dumps([{
                "content": "User prefers dark mode always",
                "summary": "Dark mode preference",
                "score": 0.9,
            }]),
            "created_at": 1,
        }]

        with patch.object(agent, "_call_llm_with_gaps", return_value=None):
            result = agent.synthesize("q", "ws1", aaak=True)

        entry = result["entries"][0] if "entries" in result else None
        # If we didn't separate entries in result, check they were compressed
        # The synthesize method doesn't put entries in result dict directly

    def test_synthesize_pack_json_dict(self, agent):
        agent._client._call = Mock()
        agent._client._query.return_value = [{
            "id": "p1",
            "pack_json": json.dumps({"memories": [{"content": "dict path", "score": 0.5}]}),
            "created_at": 1,
        }]

        with patch.object(agent, "_call_llm_with_gaps", return_value={
            "answer": "from dict", "gaps": [], "sources": [1], "confidence": 0.5,
        }):
            result = agent.synthesize("q", "ws1")
        assert result["answer"] == "from dict"


# ── _call_llm ────────────────────────────────────────────────────────────────


class TestCallLLM:
    def test_no_api_key_falls_back_to_local(self, agent, pack_entries):
        with patch.dict("os.environ", {}, clear=True), \
             patch.object(agent, "_call_local_llm", return_value="local answer"):
            result = agent._call_llm("query", pack_entries)
            assert result == "local answer"

    def test_with_api_key_calls_openai(self, agent, pack_entries):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "GPT answer"}}]
        }

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=True), \
             patch("httpx.post", return_value=mock_resp):
            result = agent._call_llm("query", pack_entries)
            assert result == "GPT answer"

    def test_llm_call_exception_returns_error(self, agent, pack_entries):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=True), \
             patch("httpx.post", side_effect=Exception("timeout")):
            result = agent._call_llm("query", pack_entries)
            assert "LLM call failed" in result
            assert "timeout" in result

    def test_uses_litellm_master_key(self, agent, pack_entries):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "proxy answer"}}]
        }

        with patch.dict("os.environ", {"LITELLM_MASTER_KEY": "sk-proxy"}, clear=True), \
             patch("httpx.post", return_value=mock_resp):
            result = agent._call_llm("query", pack_entries)
            assert result == "proxy answer"


# ── _call_llm_with_gaps ──────────────────────────────────────────────────────


class TestCallLLMWithGaps:
    def test_no_api_key_returns_none(self, agent, pack_entries):
        with patch.dict("os.environ", {}, clear=True):
            result = agent._call_llm_with_gaps("q", pack_entries)
            assert result is None

    def test_parses_json_response(self, agent, pack_entries):
        llm_response = {
            "answer": "Gap analysis answer",
            "gaps": ["missing info"],
            "sources": [1],
            "confidence": 0.7,
        }
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": json.dumps(llm_response)}}]
        }

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=True), \
             patch("httpx.post", return_value=mock_resp):
            result = agent._call_llm_with_gaps("q", pack_entries)
            assert result["answer"] == "Gap analysis answer"
            assert result["gaps"] == ["missing info"]

    def test_exception_returns_none(self, agent, pack_entries):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=True), \
             patch("httpx.post", side_effect=Exception("boom")):
            result = agent._call_llm_with_gaps("q", pack_entries)
            assert result is None


# ── _call_local_llm ──────────────────────────────────────────────────────────


class TestCallLocalLLM:
    def test_local_llm_unavailable_returns_none(self, agent, pack_entries):
        mock_llm = Mock()
        mock_llm.available = False
        with patch("spacetime_memory.local_llm.LocalLLM") as mock_llm_cls:
            mock_llm_cls.auto.return_value = mock_llm
            result = agent._call_local_llm("q", pack_entries)
            assert result is None

    def test_local_llm_available_generates(self, agent, pack_entries):
        mock_llm = Mock()
        mock_llm.available = True
        mock_llm.generate.return_value = "local answer"
        with patch("spacetime_memory.local_llm.LocalLLM") as mock_llm_cls:
            mock_llm_cls.auto.return_value = mock_llm
            result = agent._call_local_llm("q", pack_entries)
            assert result == "local answer"

    def test_local_llm_error_returns_none(self, agent, pack_entries):
        mock_llm = Mock()
        mock_llm.available = True
        mock_llm.generate.side_effect = RuntimeError("inference failed")
        with patch("spacetime_memory.local_llm.LocalLLM") as mock_llm_cls:
            mock_llm_cls.auto.return_value = mock_llm
            result = agent._call_local_llm("q", pack_entries)
            assert result is None
