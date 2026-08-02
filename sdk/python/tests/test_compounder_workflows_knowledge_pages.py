"""Unit tests for CompounderWorkflowsKnowledge — knowledge base workflows.

Uses Compounder (which combines all mixins) because methods like
store_answer, ingest_source, etc. call helper methods from CompounderHelpers.
"""

from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
class TestCreateEntityPage:
    """Tests for Compounder.create_entity_page()."""

    def test_creates_node_and_note(self):
        """Creates a KG node and a wiki note for the entity."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.return_value = []  # No existing node, no _index/_log
        client.create_node.return_value = {"id": "node_1", "label": "Alice"}
        client.create_note.side_effect = [
            {"id": "note_1", "title": "Alice"},  # entity page note
            {"id": "idx_1"},                      # _index creation
            {"id": "log_1"},                      # _log creation
        ]
        cp = Compounder(client)
        result = cp.create_entity_page(
            name="Alice",
            description="A researcher in AI.",
            entity_type="person",
            workspace_id="ws1",
        )
        assert result["node"]["id"] == "node_1"
        assert result["note"]["id"] == "note_1"
        client.create_node.assert_called_once()

    def test_finds_existing_node(self):
        """If a node with the same label exists, reuses it."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            [{"id": "existing_node", "label": "Alice", "node_type": "person"}],  # existing node query
            [],  # _update_index query (no existing index)
            [],  # _log_activity query (no existing log)
        ]
        client.create_note.side_effect = [
            {"id": "note_1"},  # entity page note
            {"id": "idx_1"},   # _index creation
            {"id": "log_1"},   # _log creation
        ]
        cp = Compounder(client)
        result = cp.create_entity_page(
            name="Alice",
            description="A researcher.",
            workspace_id="ws1",
        )
        assert result["node"]["id"] == "existing_node"
        client.create_node.assert_not_called()

    def test_includes_tags_in_frontmatter(self):
        """Tags are included in the note frontmatter."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.return_value = []
        client.create_node.return_value = {"id": "node_1"}
        client.create_note.side_effect = [
            {"id": "note_1"},  # entity page note
            {"id": "idx_1"},   # _index
            {"id": "log_1"},   # _log
        ]
        cp = Compounder(client)
        cp.create_entity_page(
            name="Alice",
            description="A researcher.",
            workspace_id="ws1",
            tags=["person", "ai"],
        )
        # Find the entity page call (not _index or _log)
        page_call = next(
            (c for c in client.create_note.call_args_list
             if c[1].get("title") == "Alice"),
            None
        )
        assert page_call is not None
        assert "tags: [person, ai]" in page_call[1]["content"]

    def test_create_node_runtime_error_handled(self):
        """RuntimeError during node creation sets node to None."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.return_value = []
        client.create_node.side_effect = RuntimeError("db error")
        client.create_note.side_effect = [
            {"id": "note_1"},  # entity page note
            {"id": "idx_1"},   # _index
            {"id": "log_1"},   # _log
        ]
        cp = Compounder(client)
        result = cp.create_entity_page(
            name="Alice",
            description="A researcher.",
            workspace_id="ws1",
        )
        assert result["node"] is None


@pytest.mark.unit

class TestUpdateEntityPage:
    """Tests for Compounder.update_entity_page()."""

    def test_returns_empty_when_not_found(self):
        """When no existing node is found, returns empty dict."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.return_value = []  # No existing node
        cp = Compounder(client)
        result = cp.update_entity_page(name="Unknown", workspace_id="ws1")
        assert result == {}

    def test_updates_node_and_note(self):
        """Updates KG node and associated note."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        # update_entity_page calls _query for node, note, then _update_index calls _query, then _log_activity calls _query
        client._query.side_effect = [
            [{"id": "node_1", "label": "Alice", "node_type": "person", "summary": "Old desc", "metadata_json": "{}", "source_memory_id": ""}],  # existing node
            [{"id": "note_1", "title": "Alice", "content": "---\ntype: person\n---\n\n## Overview\n\nOld desc"}],  # existing note
            [],  # _update_index: query (no existing index)
            [],  # _log_activity: query (no existing log)
        ]
        client.create_note.side_effect = [
            {"id": "idx_1"},  # _index creation
            {"id": "log_1"},  # _log creation
        ]
        client.update_node.return_value = {"id": "node_1"}
        client.update_note.return_value = {"id": "note_1"}
        cp = Compounder(client)
        result = cp.update_entity_page(
            name="Alice",
            workspace_id="ws1",
            description="Updated description.",
            entity_type="person",
        )
        assert result["node"]["id"] == "node_1"
        client.update_node.assert_called_once()

    def test_keeps_existing_fields_when_none(self):
        """Fields set to None keep their existing values."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            [{"id": "node_1", "label": "Alice", "node_type": "person", "summary": "Old desc", "metadata_json": "{}", "source_memory_id": ""}],
            [{"id": "note_1", "title": "Alice", "content": "---\ntype: person\n---\n\n## Overview\n\nOld desc"}],
            [],  # _update_index: query
            [],  # _log_activity: query
        ]
        client.create_note.side_effect = [
            {"id": "idx_1"},  # _index
            {"id": "log_1"},  # _log
        ]
        client.update_node.return_value = {"id": "node_1"}
        client.update_note.return_value = {"id": "note_1"}
        cp = Compounder(client)
        result = cp.update_entity_page(name="Alice", workspace_id="ws1")
        assert result["node"]["id"] == "node_1"


@pytest.mark.unit

class TestCreateConceptPage:
    """Tests for Compounder.create_concept_page()."""

    def test_creates_note_and_node(self):
        """Creates a concept note and KG node."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.side_effect = [
            {"id": "note_1", "title": "Concept: RLHF"},  # concept note
            {"id": "idx_1"},                              # _index
            {"id": "log_1"},                              # _log
        ]
        client.create_node.return_value = {"id": "node_1", "label": "RLHF", "node_type": "concept"}
        client._query.return_value = []
        cp = Compounder(client)
        result = cp.create_concept_page(
            concept="RLHF",
            definition="Reinforcement Learning from Human Feedback.",
            workspace_id="ws1",
        )
        assert result["note"]["id"] == "note_1"
        assert result["node"]["id"] == "node_1"

    def test_includes_related_concepts(self):
        """Related concepts appear in the note content."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.side_effect = [
            {"id": "note_1"},  # concept note
            {"id": "idx_1"},   # _index
            {"id": "log_1"},   # _log
        ]
        client.create_node.return_value = {"id": "node_1"}
        client._query.return_value = []
        cp = Compounder(client)
        cp.create_concept_page(
            concept="RLHF",
            definition="A method.",
            workspace_id="ws1",
            related_concepts=["DPO", "PPO"],
        )
        # Find the concept note call
        concept_call = next(
            (c for c in client.create_note.call_args_list
             if "Concept:" in str(c[1].get("title", ""))),
            None
        )
        assert concept_call is not None
        assert "[[DPO]]" in concept_call[1]["content"]
        assert "[[PPO]]" in concept_call[1]["content"]

    def test_runtime_error_on_node_creation(self):
        """RuntimeError during node creation results in None node."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.side_effect = [
            {"id": "note_1"},  # concept note
            {"id": "idx_1"},   # _index
            {"id": "log_1"},   # _log
        ]
        client.create_node.side_effect = RuntimeError("db error")
        client._query.return_value = []
        cp = Compounder(client)
        result = cp.create_concept_page(
            concept="RLHF",
            definition="A method.",
            workspace_id="ws1",
        )
        assert result["node"] is None

    def test_empty_definition(self):
        """Works with empty definition."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.side_effect = [
            {"id": "note_1"},  # concept note
            {"id": "idx_1"},   # _index
            {"id": "log_1"},   # _log
        ]
        client.create_node.return_value = {"id": "node_1"}
        client._query.return_value = []
        cp = Compounder(client)
        result = cp.create_concept_page(concept="Test", definition="", workspace_id="ws1")
        assert result["note"]["id"] == "note_1"


@pytest.mark.unit

class TestCreateComparisonPage:
    """Tests for Compounder.create_comparison_page()."""

    def test_empty_items_returns_empty(self):
        """Empty items list returns empty dict."""
        from spacetime_memory.compounder.core import Compounder

        cp = Compounder(MagicMock())
        result = cp.create_comparison_page(title="Test", items=[], workspace_id="ws1")
        assert result == {"note": {}}

    def test_creates_comparison_note_with_dict_items(self):
        """Creates a comparison note with dict items."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.side_effect = [
            {"id": "note_1"},  # comparison note
            {"id": "idx_1"},   # _index
            {"id": "log_1"},   # _log
        ]
        client._query.return_value = []
        cp = Compounder(client)
        cp.create_comparison_page(
            title="RLHF vs DPO",
            items=[
                {"name": "RLHF", "type": "reward-based", "complexity": "High"},
                {"name": "DPO", "type": "direct preference", "complexity": "Low"},
            ],
            workspace_id="ws1",
        )
        client.create_note.assert_called()
        # Find the comparison call
        comp_call = next(
            (c for c in client.create_note.call_args_list
             if "Comparison:" in str(c[1].get("title", ""))),
            None
        )
        assert comp_call is not None
        assert "reward-based" in comp_call[1]["content"]
        assert "direct preference" in comp_call[1]["content"]

    def test_normalises_string_items(self):
        """String items are normalised to dicts with optional criteria."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client.create_note.side_effect = [
            {"id": "note_1"},  # comparison note
            {"id": "idx_1"},   # _index
            {"id": "log_1"},   # _log
        ]
        client._query.return_value = []
        cp = Compounder(client)
        cp.create_comparison_page(
            title="Items",
            items=["A", "B"],
            workspace_id="ws1",
            criteria=["Size"],
        )
        comp_call = next(
            (c for c in client.create_note.call_args_list
             if "Comparison:" in str(c[1].get("title", ""))),
            None
        )
        assert comp_call is not None
        assert "Size" in comp_call[1]["content"]

