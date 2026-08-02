"""Unit tests for CompounderHelpers — private helper methods."""

from unittest.mock import MagicMock

import pytest


@pytest.mark.unit

@pytest.mark.unit
class TestFindContradictions:
    """Tests for CompounderHelpers._find_contradictions()."""

    def test_returns_empty_when_llm_unavailable(self):
        """When LLM is not available, returns empty list."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._llm = MagicMock()
        obj._llm.available = False
        result = obj._find_contradictions("ws1")
        assert result == []

    def test_returns_empty_when_fewer_than_two_memories(self):
        """Fewer than 2 memories returns empty."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._llm = MagicMock()
        obj._llm.available = True
        obj._client._query.return_value = [
            {"id": "m1", "content": "Only memory", "created_at": 100},
        ]
        result = obj._find_contradictions("ws1")
        assert result == []

    def test_detects_contradiction_with_llm(self):
        """LLM-flagged contradiction is returned."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._llm = MagicMock()
        obj._llm.available = True
        obj._llm.chat.return_value = (
            '{"is_contradiction": true, "explanation": "Opposite claims"}'
        )
        obj._client._query.return_value = [
            {"id": "m1", "content": "The sky is blue.", "created_at": 100},
            {"id": "m2", "content": "The sky is green.", "created_at": 200},
        ]
        result = obj._find_contradictions("ws1")
        assert len(result) >= 1
        assert result[0]["explanation"] == "Opposite claims"

    def test_skips_non_contradictory_pairs(self):
        """Non-contradictory pairs are skipped."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._llm = MagicMock()
        obj._llm.available = True
        obj._llm.chat.return_value = (
            '{"is_contradiction": false, "explanation": "They agree"}'
        )
        obj._client._query.return_value = [
            {"id": "m1", "content": "The sky is blue.", "created_at": 100},
            {"id": "m2", "content": "The sky is blue too.", "created_at": 200},
        ]
        result = obj._find_contradictions("ws1")
        assert result == []


@pytest.mark.unit


class TestCreateContradictionNotes:
    """Tests for CompounderHelpers._create_contradiction_notes()."""

    def test_creates_note_for_each_contradiction(self):
        """Each contradiction gets a note."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        contradictions = [
            {
                "id_a": "mem_1", "id_b": "mem_2",
                "content_a": "Sky is blue.", "content_b": "Sky is green.",
                "explanation": "Colors differ.",
            },
        ]
        obj._create_contradiction_notes("ws1", contradictions)
        obj._client.create_note.assert_called_once()
        call_kw = obj._client.create_note.call_args[1]
        assert "Contradiction" in call_kw["title"]
        assert "Colors differ." in call_kw["content"]

    def test_empty_list_does_nothing(self):
        """Empty contradictions list does nothing."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._create_contradiction_notes("ws1", [])
        obj._client.create_note.assert_not_called()

    def test_runtime_error_caught(self):
        """RuntimeError during note creation is caught."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client.create_note.side_effect = RuntimeError("db error")
        contradictions = [
            {
                "id_a": "m1", "id_b": "m2",
                "content_a": "A", "content_b": "B",
                "explanation": "Conflict",
            },
        ]
        obj._create_contradiction_notes("ws1", contradictions)  # Should not raise


@pytest.mark.unit


class TestFormatSourcePage:
    """Tests for CompounderHelpers._format_source_page()."""

    def test_contains_summary_and_source(self):
        """Format source page includes summary and source sections."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        page = obj._format_source_page("Test Title", "Full text content", "Short summary", "article")
        assert "## Summary" in page
        assert "Short summary" in page
        assert "## Source (article)" in page
        assert "Full text content" in page

    def test_truncates_long_text(self):
        """Very long full text is truncated with notice."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        long_text = "A" * 3000
        page = obj._format_source_page("Title", long_text, "summary", "article")
        assert "3000 chars" in page
        assert "truncated" in page


@pytest.mark.unit


class TestCheckContradictionsOnIngest:
    """Tests for CompounderHelpers._check_contradictions_on_ingest()."""

    def test_returns_empty_when_llm_unavailable(self):
        """When LLM is not available, returns empty list."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._llm = MagicMock()
        obj._llm.available = False
        result = obj._check_contradictions_on_ingest("ws1", "new content", "note_1")
        assert result == []

    def test_returns_empty_when_no_similar_memories(self):
        """No similar memories returns empty list."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client.search.return_value = []
        obj._llm = MagicMock()
        obj._llm.available = True
        result = obj._check_contradictions_on_ingest("ws1", "new", "note_1")
        assert result == []

    def test_detects_contradiction(self):
        """LLM-flagged contradiction is returned."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client.search.return_value = [
            {"entity_id": "mem_1", "content": "The sky is blue."},
        ]
        obj._llm = MagicMock()
        obj._llm.available = True
        obj._llm.chat.return_value = (
            '{"is_contradiction": true, "explanation": "Colors differ."}'
        )
        result = obj._check_contradictions_on_ingest("ws1", "The sky is red.", "src_1")
        assert len(result) == 1
        assert result[0]["memory_id"] == "mem_1"

    def test_skips_non_contradictory(self):
        """Non-contradictory pairs are skipped."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client.search.return_value = [
            {"entity_id": "mem_1", "content": "The sky is blue."},
        ]
        obj._llm = MagicMock()
        obj._llm.available = True
        obj._llm.chat.return_value = (
            '{"is_contradiction": false, "explanation": "They agree."}'
        )
        result = obj._check_contradictions_on_ingest("ws1", "The sky is blue.", "src_1")
        assert result == []


@pytest.mark.unit


class TestCreateIngestContradictionNote:
    """Tests for CompounderHelpers._create_ingest_contradiction_note()."""

    def test_creates_contradiction_note(self):
        """Creates a note documenting the ingest contradiction."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._create_ingest_contradiction_note("ws1", "new_note", "existing_mem", "They conflict.")
        obj._client.create_note.assert_called_once()
        call_kw = obj._client.create_note.call_args[1]
        assert "Contradiction" in call_kw["title"]
        assert "existing" in call_kw["title"]
        assert "new source" in call_kw["title"]
        assert "They conflict." in call_kw["content"]


