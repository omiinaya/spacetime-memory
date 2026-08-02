"""Unit tests for CompounderWorkflows re-export module."""

from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
class TestCompounderWorkflows:
    """Tests for the CompounderWorkflows class (re-export from 5 mixins)."""

    def test_inherits_from_all_mixin_classes(self):
        """CompounderWorkflows should inherit from all five workflow mixins."""
        from spacetime_memory.compounder.workflows import CompounderWorkflows
        from spacetime_memory.compounder.workflows_export import CompounderWorkflowsExport
        from spacetime_memory.compounder.workflows_graph import CompounderWorkflowsGraph
        from spacetime_memory.compounder.workflows_knowledge import CompounderWorkflowsKnowledge
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        assert issubclass(CompounderWorkflows, CompounderWorkflowsSearch)
        assert issubclass(CompounderWorkflows, CompounderWorkflowsKnowledge)
        assert issubclass(CompounderWorkflows, CompounderWorkflowsGraph)
        assert issubclass(CompounderWorkflows, CompounderWorkflowsRipple)
        assert issubclass(CompounderWorkflows, CompounderWorkflowsExport)

    def test_has_search_methods(self):
        """CompounderWorkflows should expose search_entities and find_near_duplicates."""
        from spacetime_memory.compounder.workflows import CompounderWorkflows

        assert hasattr(CompounderWorkflows, "search_entities")
        assert hasattr(CompounderWorkflows, "find_near_duplicates")

    def test_has_knowledge_methods(self):
        """CompounderWorkflows should expose knowledge-base methods."""
        from spacetime_memory.compounder.workflows import CompounderWorkflows

        assert hasattr(CompounderWorkflows, "store_answer")
        assert hasattr(CompounderWorkflows, "store_answers")
        assert hasattr(CompounderWorkflows, "ingest_source")
        assert hasattr(CompounderWorkflows, "create_entity_page")
        assert hasattr(CompounderWorkflows, "update_entity_page")
        assert hasattr(CompounderWorkflows, "create_concept_page")
        assert hasattr(CompounderWorkflows, "create_comparison_page")

    def test_has_graph_methods(self):
        """CompounderWorkflows should expose graph workflow methods."""
        from spacetime_memory.compounder.workflows import CompounderWorkflows

        assert hasattr(CompounderWorkflows, "cross_link")
        assert hasattr(CompounderWorkflows, "suggest_connections")
        assert hasattr(CompounderWorkflows, "lint_workspace")

    def test_has_ripple_methods(self):
        """CompounderWorkflows should expose ripple workflow methods."""
        from spacetime_memory.compounder.workflows import CompounderWorkflows

        assert hasattr(CompounderWorkflows, "detect_ripple_effects")
        assert hasattr(CompounderWorkflows, "apply_ripple_updates")
        assert hasattr(CompounderWorkflows, "mark_stale_for_source")
        assert hasattr(CompounderWorkflows, "clear_stale_flag")

    def test_has_export_methods(self):
        """CompounderWorkflows should expose export workflow methods."""
        from spacetime_memory.compounder.workflows import CompounderWorkflows

        assert hasattr(CompounderWorkflows, "export_workspace")
        assert hasattr(CompounderWorkflows, "generate_overview_page")

    def test_mro_order(self):
        """MRO should include all mixin classes in order."""
        from spacetime_memory.compounder.workflows import CompounderWorkflows
        from spacetime_memory.compounder.workflows_export import CompounderWorkflowsExport
        from spacetime_memory.compounder.workflows_graph import CompounderWorkflowsGraph
        from spacetime_memory.compounder.workflows_knowledge import CompounderWorkflowsKnowledge
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple
        from spacetime_memory.compounder.workflows_search import CompounderWorkflowsSearch

        mro = CompounderWorkflows.__mro__
        assert CompounderWorkflowsSearch in mro
        assert CompounderWorkflowsKnowledge in mro
        assert CompounderWorkflowsGraph in mro
        assert CompounderWorkflowsRipple in mro
        assert CompounderWorkflowsExport in mro

    def test_can_instantiate_on_class_with_client(self):
        """CompounderWorkflows can be instantiated on a simple class with _client."""
        from spacetime_memory.compounder.workflows import CompounderWorkflows

        obj = CompounderWorkflows()
        obj._client = MagicMock()
        # Should be able to call search_entities
        obj._client._query.return_value = []
        obj._client.search.return_value = []
        result = obj.search_entities(workspace_id="ws1")
        assert result == []
