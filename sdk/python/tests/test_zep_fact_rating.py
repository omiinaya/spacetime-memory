"""Unit tests for Zep LLM fact extraction + rating (Zep Cloud parity).

Pure unit tests — mocked storage + mocked LLM, no live SpacetimeDB needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from spacetime_memory.sdks.zep import ZepClient

pytestmark = pytest.mark.unit


class TestFactRatingParser:
    """JSON parser for LLM fact-rating responses."""

    def _client(self) -> ZepClient:
        return ZepClient(host="127.0.0.1", port=3001)

    def test_parse_plain_array(self) -> None:
        zep = self._client()
        raw = '[{"fact": "User likes pizza", "rating": 0.8}]'
        assert zep._parse_fact_rating_json(raw) == [
            {"fact": "User likes pizza", "rating": 0.8}
        ]

    def test_parse_wrapped_object(self) -> None:
        zep = self._client()
        raw = '{"facts": [{"fact": "A", "rating": 0.9}, {"fact": "B", "rating": 0.4}]}'
        facts = zep._parse_fact_rating_json(raw)
        assert len(facts) == 2
        assert facts[0] == {"fact": "A", "rating": 0.9}

    def test_parse_code_fenced(self) -> None:
        zep = self._client()
        raw = '```json\n[{"fact": "Fenced", "rating": 0.6}]\n```'
        assert zep._parse_fact_rating_json(raw) == [
            {"fact": "Fenced", "rating": 0.6}
        ]

    def test_parse_regex_fallback(self) -> None:
        zep = self._client()
        raw = 'Here: {"fact": "Fallback fact", "rating": 0.55} end'
        assert zep._parse_fact_rating_json(raw) == [
            {"fact": "Fallback fact", "rating": 0.55}
        ]

    def test_parse_garbage_returns_empty(self) -> None:
        zep = self._client()
        assert zep._parse_fact_rating_json("not json at all") == []
        assert zep._parse_fact_rating_json("") == []

    def test_parse_empty_array(self) -> None:
        zep = self._client()
        assert zep._parse_fact_rating_json("[]") == []


class TestFactRatingExtraction:
    """LLM fact extraction + rating with mocked LLM and storage."""

    def _make_client(self) -> ZepClient:
        zep = ZepClient(host="127.0.0.1", port=3001)
        zep._client = Mock()
        zep._client.store.return_value = {"status": "ok", "id": "fact-1"}
        zep._client.list_memories.return_value = []
        zep._session_to_ws = {"s1": "ws-1"}
        zep._ws_cache = {}
        return zep

    def test_extract_stores_rated_facts(self) -> None:
        zep = self._make_client()
        with patch("spacetime_memory.llm.LLMClient") as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.available = True
            mock_llm.chat.return_value = (
                '[{"fact": "User likes pizza", "rating": 0.8}, '
                '{"fact": "User hates mushrooms", "rating": 0.2}]'
            )
            mock_llm_cls.return_value = mock_llm

            facts = zep._extract_and_rate_facts(
                "ws-1", "s1", [{"role": "user", "content": "I like pizza"}]
            )

        assert len(facts) == 2
        assert zep._client.store.call_count == 2
        summaries = [
            c.kwargs.get("summary", "") for c in zep._client.store.call_args_list
        ]
        assert any("0.80" in s for s in summaries)
        assert any("0.20" in s for s in summaries)

    def test_extract_llm_unavailable_noop(self) -> None:
        zep = self._make_client()
        with patch("spacetime_memory.llm.LLMClient") as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.available = False
            mock_llm_cls.return_value = mock_llm

            facts = zep._extract_and_rate_facts(
                "ws-1", "s1", [{"role": "user", "content": "hello"}]
            )

        assert facts == []
        zep._client.store.assert_not_called()

    def test_extract_llm_error_noop(self) -> None:
        zep = self._make_client()
        with patch("spacetime_memory.llm.LLMClient") as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.available = True
            mock_llm.chat.side_effect = RuntimeError("llm down")
            mock_llm_cls.return_value = mock_llm

            facts = zep._extract_and_rate_facts(
                "ws-1", "s1", [{"role": "user", "content": "hello"}]
            )

        assert facts == []
        zep._client.store.assert_not_called()

    def test_extract_uses_custom_instruction(self) -> None:
        zep = self._make_client()
        with patch("spacetime_memory.llm.LLMClient") as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.available = True
            mock_llm.chat.return_value = '[]'
            mock_llm_cls.return_value = mock_llm

            zep._extract_and_rate_facts(
                "ws-1",
                "s1",
                [{"role": "user", "content": "hello"}],
                instruction="Focus on preferences",
            )

            prompt_parts = str(mock_llm.chat.call_args[0][0])
            assert "Focus on preferences" in prompt_parts

    def test_add_memory_extracts_facts_by_default(self) -> None:
        zep = self._make_client()
        with patch.object(zep, "_extract_and_rate_facts") as mock_extract:
            mock_extract.return_value = [{"fact": "x", "rating": 0.5}]

            zep.add_memory(
                session_id="s1",
                messages=[{"role": "user", "content": "I like pizza"}],
            )

        mock_extract.assert_called_once()
        args = mock_extract.call_args[0]
        assert args[0] == "ws-1"
        assert args[1] == "s1"
        assert args[2] == [{"role": "user", "content": "I like pizza"}]

    def test_add_memory_skips_extraction_when_disabled(self) -> None:
        zep = self._make_client()
        with patch.object(zep, "_extract_and_rate_facts") as mock_extract:
            zep.add_memory(
                session_id="s1",
                messages=[{"role": "user", "content": "hello"}],
                extract_facts=False,
            )

        mock_extract.assert_not_called()

    def test_add_memory_forwards_fact_instruction(self) -> None:
        zep = self._make_client()
        with patch.object(zep, "_extract_and_rate_facts") as mock_extract:
            mock_extract.return_value = []

            zep.add_memory(
                session_id="s1",
                messages=[{"role": "user", "content": "hello"}],
                fact_instruction="Steer extraction",
            )

        # instruction passed as 4th positional arg
        assert mock_extract.call_args[0][3] == "Steer extraction"
