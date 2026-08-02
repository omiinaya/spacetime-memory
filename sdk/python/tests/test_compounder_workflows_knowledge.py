"""Unit tests for CompounderWorkflowsKnowledge — knowledge base workflows.

Uses Compounder (which combines all mixins) because methods like
store_answer, ingest_source, etc. call helper methods from CompounderHelpers.
"""

from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
class TestStoreAnswer:
    """Tests for Compounder.store_answer()."""

    def test_empty_answer_returns_empty(self):
        """Empty answer returns empty dict."""
        from spacetime_memory.compounder.core import Compounder

        cp = Compounder(MagicMock())
        result = cp.store_answer(query="q", answer="")
        assert result == {}

    def test_creates_note_with_generated_title(self):
        """Creates a note with auto-generated title from the query."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        # Note creation, _index creation, _log creation
        client.create_note.return_value = {"id": "note_1"}
        # No existing _index or _log
        client._query.return_value = []
        cp = Compounder(client)
        result = cp.store_answer(query="What is X?", answer="X is a concept.")
        # At least one create_note call should have the question content
        found = any(
            "## Question" in str(c[1].get("content", ""))
            for c in client.create_note.call_args_list
        )
        assert found
        assert result["note"]["id"] == "note_1"

    def test_uses_explicit_title(self):
        """Explicit title is used instead of auto-generated."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.return_value = {"id": "n1"}
        client._query.return_value = []
        cp = Compounder(client)
        cp.store_answer(query="q", answer="answer", title="My Title")
        # Find the note creation call (not _index or _log)
        note_calls = [
            c for c in client.create_note.call_args_list
            if c[1].get("title") == "My Title"
        ]
        assert len(note_calls) >= 1

    def test_extracts_entities_and_creates_nodes(self):
        """Entities from LLM are created as KG nodes."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        client._query.return_value = []
        # Use return_value instead of side_effect to handle any number of calls
        client.create_node.return_value = {"id": "node_x"}
        mock_llm = MagicMock()
        mock_llm.available = False
        mock_llm.extract_entities_llm.return_value = [
            {"name": "Alice", "entity_type": "person", "description": "A researcher"},
            {"name": "Bob", "entity_type": "person", "description": "A developer"},
        ]
        cp = Compounder(client, llm=mock_llm)
        result = cp.store_answer(
            query="Who are Alice and Bob?",
            answer="Alice and Bob are colleagues.",
        )
        assert client.create_node.call_count >= 2
        assert len(result["entities"]) >= 1

    def test_entity_extraction_failure_graceful(self):
        """None entities from LLM yields empty entities list."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        client._query.return_value = []
        mock_llm = MagicMock()
        mock_llm.available = False
        mock_llm.extract_entities_llm.return_value = None
        cp = Compounder(client, llm=mock_llm)
        result = cp.store_answer(query="q", answer="Some answer.")
        assert client.create_node.call_count == 0
        assert result["entities"] == []

    def test_links_to_source_memories(self):
        """Links source memories via _call('create_edge', ...)."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        client._query.return_value = []
        mock_llm = MagicMock()
        mock_llm.available = False
        mock_llm.extract_entities_llm.return_value = None
        cp = Compounder(client, llm=mock_llm)
        cp.store_answer(
            query="q", answer="ans",
            source_memory_ids=["mem_1", "mem_2"],
        )
        # Should create edges for source memories
        edge_calls = [
            c for c in client._call.call_args_list
            if c[0][0] == "create_edge"
        ]
        assert len(edge_calls) == 2

    def test_skip_duplicates_returns_early_when_found(self):
        """When near-duplicate found, returns early with duplicate info."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.search.return_value = [
            {"entity_id": "existing_1", "content": "Similar content", "score": 0.95, "entity_type": "note"},
        ]
        cp = Compounder(client)
        result = cp.store_answer(
            query="What is X?", answer="X is a concept.",
            skip_duplicates=True, duplicate_threshold=0.92,
        )
        client.create_note.assert_not_called()
        assert result["duplicate_of"] == "existing_1"
        assert result["duplicate_score"] == 0.95

    def test_skip_duplicates_false_creates_note(self):
        """When skip_duplicates is False, creates note even with near-duplicate."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        client._query.return_value = []
        client.search.return_value = [
            {"entity_id": "existing", "content": "similar", "score": 0.95},
        ]
        mock_llm = MagicMock()
        mock_llm.available = False
        mock_llm.extract_entities_llm.return_value = None
        cp = Compounder(client, llm=mock_llm)
        result = cp.store_answer(query="q", answer="ans.", skip_duplicates=False)
        client.create_note.assert_called()
        assert "duplicate_of" not in result


@pytest.mark.unit

class TestStoreAnswers:
    """Tests for Compounder.store_answers()."""

    def test_empty_pairs_returns_empty(self):
        """Empty list of QA pairs returns empty list."""
        from spacetime_memory.compounder.core import Compounder

        cp = Compounder(MagicMock())
        results = cp.store_answers([])
        assert results == []

    def test_stores_multiple_answers(self):
        """Each QA pair is stored via store_answer."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.return_value = []
        client.create_note.return_value = {"id": "note_1"}
        # _llm defaults to not available, so entities extraction returns None
        cp = Compounder(client)
        results = cp.store_answers(
            [("Q1", "A1"), ("Q2", "A2")],
            workspace_id="ws1",
        )
        assert len(results) == 2

    def test_handles_runtime_error_gracefully(self):
        """RuntimeError in one store_answer returns empty dict for that item."""
        from spacetime_memory.compounder.core import Compounder

        # Create a Compounder and monkey-patch store_answer on the instance
        client = MagicMock()
        client.create_note.return_value = {"id": "note_base"}
        client._query.return_value = []
        cp = Compounder(client)

        call_count = [0]

        def mock_store(query, answer, workspace_id="default", source_memory_ids=None,
                       title=None, embed=True, skip_duplicates=True, duplicate_threshold=0.92):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("Simulated failure")
            return {"note": {"id": f"note_{call_count[0]}"}, "entities": [], "links": []}

        cp.store_answer = mock_store

        results = cp.store_answers(
            [("Q1", "A1"), ("Q2", "A2"), ("Q3", "A3")],
            workspace_id="ws1",
        )
        assert len(results) == 3
        assert results[0]["note"]["id"] == "note_1"
        assert results[1] == {"note": {}, "entities": [], "links": []}


@pytest.mark.unit

class TestIngestSource:
    """Tests for Compounder.ingest_source()."""

    def test_empty_text_returns_empty_result(self):
        """Empty source text returns empty dict."""
        from spacetime_memory.compounder.core import Compounder

        cp = Compounder(MagicMock())
        result = cp.ingest_source(source_text="", source_title="Test")
        assert result["note"] == {}
        assert result["entities"] == []

    def test_creates_source_note(self):
        """Creates a source-summary note."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        client._query.return_value = []
        cp = Compounder(client)
        cp.ingest_source(
            source_text="This is a test article about AI.",
            source_title="Test Article",
        )
        # Should have created at least the source note
        source_calls = [
            c for c in client.create_note.call_args_list
            if "Source:" in str(c[1].get("title", ""))
        ]
        assert len(source_calls) >= 1

    def test_uses_llm_summary_when_available(self):
        """LLM summary is used when LLM is available."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.side_effect = [
            {"id": "note_1"},  # source note
            {"id": "idx_1"},   # _index
            {"id": "log_1"},   # _log
        ]
        client._query.return_value = []
        mock_llm = MagicMock()
        mock_llm.available = True
        mock_llm.summarize.return_value = "LLM generated summary."
        mock_llm.extract_entities_llm.return_value = None
        cp = Compounder(client, llm=mock_llm)
        cp.ingest_source(
            source_text="Long article text about machine learning.",
            source_title="ML Article",
        )
        # Find the source note creation call
        source_call = next(
            (c for c in client.create_note.call_args_list
             if "Source:" in str(c[1].get("title", ""))),
            None
        )
        assert source_call is not None
        assert "LLM generated summary" in source_call[1]["content"]

    def test_extracts_entities_when_llm_available(self):
        """Entities are extracted when LLM is available."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.side_effect = [
            {"id": "note_1"},  # source note
            {"id": "idx_1"},   # _index
            {"id": "log_1"},   # _log
        ]
        client.create_node.return_value = {"id": "node_x"}
        client._query.return_value = []
        mock_llm = MagicMock()
        mock_llm.available = True
        mock_llm.summarize.return_value = None
        mock_llm.extract_entities_llm.return_value = [
            {"name": "GPT-4", "entity_type": "product", "description": "A language model"},
            {"name": "OpenAI", "entity_type": "org", "description": "AI company"},
        ]
        cp = Compounder(client, llm=mock_llm)
        result = cp.ingest_source(
            source_text="GPT-4 by OpenAI is a language model.",
            source_title="GPT-4 Overview",
        )
        assert len(result["entities"]) == 2

    def test_links_entities_to_source(self):
        """Entities are linked to source note via create_edge."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        client.create_node.return_value = {"id": "node_1"}
        client._query.return_value = []
        mock_llm = MagicMock()
        mock_llm.available = True
        mock_llm.summarize.return_value = None
        mock_llm.extract_entities_llm.return_value = [
            {"name": "GPT-4", "entity_type": "product"},
        ]
        cp = Compounder(client, llm=mock_llm)
        result = cp.ingest_source(
            source_text="GPT-4 by OpenAI.",
            source_title="Test",
        )
        assert len(result["links"]) == 1

    def test_contradiction_check_on_ingest(self):
        """Contradictions are checked during ingest when LLM available."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        client.search.return_value = [
            {"entity_id": "mem_1", "content": "The sky is blue."},
        ]
        client._query.return_value = []
        mock_llm = MagicMock()
        mock_llm.available = True
        mock_llm.summarize.return_value = "Summary text."
        mock_llm.extract_entities_llm.return_value = None
        mock_llm.chat.return_value = (
            '{"is_contradiction": true, "explanation": "Colors differ."}'
        )
        cp = Compounder(client, llm=mock_llm)
        result = cp.ingest_source(
            source_text="The sky is green.",
            source_title="Test",
        )
        assert len(result["contradictions"]) == 1

    def test_no_contradictions_when_llm_unavailable(self):
        """No contradiction check when LLM is not available."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        client._query.return_value = []
        cp = Compounder(client)
        result = cp.ingest_source(
            source_text="Some content.",
            source_title="Test",
        )
        assert result["contradictions"] == []
