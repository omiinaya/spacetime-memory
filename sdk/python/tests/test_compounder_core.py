"""Unit tests for Compounder core module."""

from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
class TestCompounder:
    """Tests for the Compounder class (core module)."""

    def test_init_stores_client(self):
        """Compounder.__init__ should store the client as _client."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        cp = Compounder(client)
        assert cp._client is client

    def test_init_creates_default_llm_when_none(self):
        """Compounder.__init__ should create an LLMClient when llm is None."""
        from spacetime_memory.compounder.core import Compounder

        cp = Compounder(MagicMock())
        assert cp._llm is not None

    def test_init_uses_provided_llm(self):
        """Compounder.__init__ should store the provided llm instance."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        mock_llm = MagicMock()
        cp = Compounder(client, llm=mock_llm)
        assert cp._llm is mock_llm

    def test_inherits_from_compounder_workflows(self):
        """Compounder should inherit from CompounderWorkflows."""
        from spacetime_memory.compounder.core import Compounder
        from spacetime_memory.compounder.workflows import CompounderWorkflows

        assert issubclass(Compounder, CompounderWorkflows)

    def test_inherits_from_compounder_helpers(self):
        """Compounder should inherit from CompounderHelpers."""
        from spacetime_memory.compounder.core import Compounder
        from spacetime_memory.compounder.helpers import CompounderHelpers

        assert issubclass(Compounder, CompounderHelpers)

    def test_has_workflow_methods(self):
        """Compounder should expose all public workflow methods."""
        from spacetime_memory.compounder.core import Compounder

        assert hasattr(Compounder, "store_answer")
        assert hasattr(Compounder, "store_answers")
        assert hasattr(Compounder, "ingest_source")
        assert hasattr(Compounder, "create_entity_page")
        assert hasattr(Compounder, "update_entity_page")
        assert hasattr(Compounder, "create_concept_page")
        assert hasattr(Compounder, "create_comparison_page")
        assert hasattr(Compounder, "search_entities")
        assert hasattr(Compounder, "find_near_duplicates")
        assert hasattr(Compounder, "cross_link")
        assert hasattr(Compounder, "suggest_connections")
        assert hasattr(Compounder, "lint_workspace")
        assert hasattr(Compounder, "detect_ripple_effects")
        assert hasattr(Compounder, "apply_ripple_updates")
        assert hasattr(Compounder, "mark_stale_for_source")
        assert hasattr(Compounder, "clear_stale_flag")
        assert hasattr(Compounder, "export_workspace")
        assert hasattr(Compounder, "generate_overview_page")

    def test_has_helper_methods(self):
        """Compounder should expose all helper methods."""
        from spacetime_memory.compounder.core import Compounder

        assert hasattr(Compounder, "_generate_title")
        assert hasattr(Compounder, "_resolve_created_note")
        assert hasattr(Compounder, "_format_answer_page")
        assert hasattr(Compounder, "_update_index")
        assert hasattr(Compounder, "_already_linked")
        assert hasattr(Compounder, "_node_label")
        assert hasattr(Compounder, "_ripple_update_entity")
        assert hasattr(Compounder, "_log_activity")
        assert hasattr(Compounder, "_find_orphan_nodes")
        assert hasattr(Compounder, "_find_missing_crossrefs")
        assert hasattr(Compounder, "_find_note_orphans")
        assert hasattr(Compounder, "_find_contradictions")
        assert hasattr(Compounder, "_create_contradiction_notes")
        assert hasattr(Compounder, "_format_source_page")
        assert hasattr(Compounder, "_check_contradictions_on_ingest")
        assert hasattr(Compounder, "_create_ingest_contradiction_note")

    def test_can_call_store_answer_on_compounder(self):
        """Compounder created via core module should work end-to-end."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        client._query.return_value = []
        cp = Compounder(client)
        result = cp.store_answer(query="What is X?", answer="X is a concept.")
        assert "note" in result
        assert result["note"]["id"] == "note_1"

    def test_llm_default_is_llmclient_instance(self):
        """Default LLM should be an LLMClient instance."""
        from spacetime_memory.compounder.core import Compounder
        from spacetime_memory.llm import LLMClient

        cp = Compounder(MagicMock())
        assert isinstance(cp._llm, LLMClient)


@pytest.mark.unit
class TestSynthesizeWithGapAnalysis:
    """GBrain-parity synthesis with explicit gap analysis."""

    def _compounder(self, client=None):
        from spacetime_memory.compounder.core import Compounder

        client = client or MagicMock()
        cp = Compounder(client)
        cp._llm = None  # force grounded fallback path in most tests
        return cp

    def test_empty_workspace_reports_gap(self):
        client = MagicMock()
        client.search.return_value = []
        cp = self._compounder(client)

        result = cp.synthesize_with_gap_analysis("What is X?", "ws-1")

        assert result["method"] == "empty"
        assert result["evidence_count"] == 0
        assert any("No evidence" in g for g in result["gaps"])

    def test_grounded_fallback_with_evidence(self):
        client = MagicMock()
        client.search.return_value = [
            {"content": "X is a concept about data."},
            {"content": "X has three parts."},
        ]
        cp = self._compounder(client)

        result = cp.synthesize_with_gap_analysis("What is X?", "ws-1")

        assert result["method"] == "grounded"
        assert result["evidence_count"] == 2
        assert "data" in result["answer"]
        assert result["gaps"]

    def test_llm_path_uses_parsed_json(self):
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.search.return_value = [{"content": "evidence one"}]
        llm = MagicMock()
        llm.chat.return_value = (
            '{"answer": "X is a data concept.", '
            '"gaps": ["No info on X history"]}'
        )
        cp = Compounder(client, llm=llm)

        result = cp.synthesize_with_gap_analysis("What is X?", "ws-1")

        assert result["method"] == "llm"
        assert result["answer"] == "X is a data concept."
        assert result["gaps"] == ["No info on X history"]
        assert result["evidence_count"] == 1

    def test_llm_failure_falls_back_to_grounded(self):
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.search.return_value = [{"content": "evidence one"}]
        llm = MagicMock()
        llm.chat.side_effect = RuntimeError("llm down")
        cp = Compounder(client, llm=llm)

        result = cp.synthesize_with_gap_analysis("What is X?", "ws-1")

        assert result["method"] == "grounded"
        assert result["evidence_count"] == 1

    def test_parse_gap_json_plain(self):
        from spacetime_memory.compounder.workflows_knowledge import (
            CompounderWorkflowsKnowledge,
        )

        parsed = CompounderWorkflowsKnowledge._parse_gap_json(
            '{"answer": "A", "gaps": ["g1", "g2"]}'
        )
        assert parsed == {"answer": "A", "gaps": ["g1", "g2"]}

    def test_parse_gap_json_fenced(self):
        from spacetime_memory.compounder.workflows_knowledge import (
            CompounderWorkflowsKnowledge,
        )

        parsed = CompounderWorkflowsKnowledge._parse_gap_json(
            '```json\n{"answer": "B", "gaps": []}\n```'
        )
        assert parsed == {"answer": "B", "gaps": []}

    def test_parse_gap_json_garbage(self):
        from spacetime_memory.compounder.workflows_knowledge import (
            CompounderWorkflowsKnowledge,
        )

        assert CompounderWorkflowsKnowledge._parse_gap_json("nope") is None
