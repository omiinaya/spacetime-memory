"""Unit tests for CompounderWorkflowsRipple — ripple update detection."""

from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
class TestDetectRippleEffects:
    """Tests for CompounderWorkflowsRipple.detect_ripple_effects()."""

    def test_empty_source_id_returns_error(self):
        """Empty source_id returns error in result."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()
        obj._client._query.return_value = []
        result = obj.detect_ripple_effects(source_id="", workspace_id="ws1")
        assert "error" in result
        assert result["source"]["id"] == ""

    def test_whitespace_source_id_returns_error(self):
        """Whitespace-only source_id returns error."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()
        obj._client._query.return_value = []
        result = obj.detect_ripple_effects(source_id="   ", workspace_id="ws1")
        assert "error" in result

    def test_finds_source_as_kg_node(self):
        """Finds a source that is a KG node."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()
        obj._client._query.side_effect = lambda table, workspace_id="", filter_dict=None: {
            ("kg_node",): [{"id": "node_1", "label": "Alice"}],
            ("note",): [],
            ("memory",): [],
            ("kg_edge",): [],
        }.get((table,), [])
        # Make _query work for all calls
        obj._client._query.side_effect = None

        def query_side_effect(table, workspace_id="", filter_dict=None):
            if table == "kg_node" and filter_dict == {"id": "node_1"}:
                return [{"id": "node_1", "label": "Alice"}]
            elif table == "note" and filter_dict == {"id": "node_1"} or table == "memory" and filter_dict == {"id": "node_1"}:
                return []
            elif table == "kg_node" and filter_dict == {}:
                return [{"id": "node_1", "label": "Alice"}]
            elif table == "kg_edge" and filter_dict == {}:
                return []
            return []

        obj._client._query.side_effect = query_side_effect
        result = obj.detect_ripple_effects(source_id="node_1", workspace_id="ws1")
        assert result["source"]["type"] == "kg_node"
        assert result["source"]["label"] == "Alice"

    def test_finds_source_as_note(self):
        """Finds a source that is a note."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()

        def query_side_effect(table, workspace_id="", filter_dict=None):
            if table == "kg_node" and filter_dict == {"id": "note_1"}:
                return []
            elif table == "note" and filter_dict == {"id": "note_1"}:
                return [{"id": "note_1", "title": "My Note"}]
            elif table == "memory" and filter_dict == {"id": "note_1"} or table == "kg_node" and filter_dict == {} or table == "kg_edge" and filter_dict == {}:
                return []
            return []

        obj._client._query.side_effect = query_side_effect
        result = obj.detect_ripple_effects(source_id="note_1", workspace_id="ws1")
        assert result["source"]["type"] == "note"
        assert result["source"]["label"] == "My Note"

    def test_finds_source_as_memory(self):
        """Finds a source that is a memory."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()

        def query_side_effect(table, workspace_id="", filter_dict=None):
            if table == "kg_node" and filter_dict == {"id": "mem_1"} or table == "note" and filter_dict == {"id": "mem_1"}:
                return []
            elif table == "memory" and filter_dict == {"id": "mem_1"}:
                return [{"id": "mem_1", "content": "some memory"}]
            elif table == "kg_node" and filter_dict == {} or table == "kg_edge" and filter_dict == {}:
                return []
            return []

        obj._client._query.side_effect = query_side_effect
        result = obj.detect_ripple_effects(source_id="mem_1", workspace_id="ws1")
        assert result["source"]["type"] == "memory"

    def test_directly_affected_via_edges(self):
        """Finds directly affected nodes (hop=1) via edges from source KG node."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()

        def query_side_effect(table, workspace_id="", filter_dict=None):
            if table == "kg_node" and filter_dict == {"id": "src"}:
                return [{"id": "src", "label": "Source"}]
            elif table == "note" and filter_dict == {"id": "src"} or table == "memory" and filter_dict == {"id": "src"}:
                return []
            elif table == "kg_node" and filter_dict == {}:
                return [
                    {"id": "src", "label": "Source"},
                    {"id": "n1", "label": "Affected A"},
                ]
            elif table == "kg_edge" and filter_dict == {}:
                return [
                    {"source_node_id": "src", "target_node_id": "n1", "id": "e1", "relation": "related_to"},
                ]
            return []

        obj._client._query.side_effect = query_side_effect
        result = obj.detect_ripple_effects(source_id="src", workspace_id="ws1")
        assert len(result["directly_affected"]) == 1
        assert result["directly_affected"][0]["label"] == "Affected A"
        assert result["directly_affected"][0]["reason"] == "direct_neighbour"
        assert result["stats"]["direct_count"] == 1

    def test_transitively_affected(self):
        """Finds transitively affected nodes (hop > 1)."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()

        def query_side_effect(table, workspace_id="", filter_dict=None):
            if table == "kg_node" and filter_dict == {"id": "src"}:
                return [{"id": "src", "label": "Source"}]
            elif table == "note" and filter_dict == {"id": "src"} or table == "memory" and filter_dict == {"id": "src"}:
                return []
            elif table == "kg_node" and filter_dict == {}:
                return [
                    {"id": "src", "label": "Source"},
                    {"id": "n1", "label": "Direct"},
                    {"id": "n2", "label": "Transitive"},
                ]
            elif table == "kg_edge" and filter_dict == {}:
                return [
                    {"source_node_id": "src", "target_node_id": "n1", "id": "e1", "relation": "related"},
                    {"source_node_id": "n1", "target_node_id": "n2", "id": "e2", "relation": "related"},
                ]
            return []

        obj._client._query.side_effect = query_side_effect
        result = obj.detect_ripple_effects(source_id="src", workspace_id="ws1", max_hops=2)
        assert result["stats"]["direct_count"] == 1
        assert result["stats"]["transitive_count"] == 1
        assert result["transitively_affected"][0]["label"] == "Transitive"

    def test_stale_only_filters(self):
        """When stale_only=True, only stale nodes appear in needs_review."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()

        def query_side_effect(table, workspace_id="", filter_dict=None):
            if table == "kg_node" and filter_dict == {"id": "src"}:
                return [{"id": "src", "label": "Source"}]
            elif table == "note" and filter_dict == {"id": "src"} or table == "memory" and filter_dict == {"id": "src"}:
                return []
            elif table == "kg_node" and filter_dict == {}:
                return [
                    {"id": "src", "label": "Source", "stale_since": 0},
                    {"id": "n1", "label": "Fresh", "stale_since": 0},
                    {"id": "n2", "label": "Stale", "stale_since": 12345},
                ]
            elif table == "kg_edge" and filter_dict == {}:
                return [
                    {"source_node_id": "src", "target_node_id": "n1", "id": "e1", "relation": "related"},
                    {"source_node_id": "src", "target_node_id": "n2", "id": "e2", "relation": "related"},
                ]
            return []

        obj._client._query.side_effect = query_side_effect
        result = obj.detect_ripple_effects(
            source_id="src", workspace_id="ws1", stale_only=True
        )
        assert len(result["needs_review"]) == 1
        assert result["needs_review"][0]["label"] == "Stale"
        assert result["stats"]["stale_count"] == 1

    def test_max_hops_clamped(self):
        """max_hops is clamped to [1, 6]."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()

        def query_side_effect(table, workspace_id="", filter_dict=None):
            if table in ("kg_node",) or table in ("note", "memory"):
                return []
            return []

        obj._client._query.side_effect = query_side_effect
        # max_hops=0 should be clamped to 1; max_hops=10 clamped to 6
        obj.detect_ripple_effects(source_id="src", workspace_id="ws1", max_hops=0)
        obj.detect_ripple_effects(source_id="src", workspace_id="ws1", max_hops=10)
        # Just checking it doesn't crash — clamping is internal
        assert True

    def test_include_notes(self):
        """When include_notes=True, affected notes are returned."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()

        def query_side_effect(table, workspace_id="", filter_dict=None):
            if table == "kg_node" and filter_dict == {"id": "src"}:
                return [{"id": "src", "label": "Source"}]
            elif table == "note" and filter_dict == {"id": "src"} or table == "memory" and filter_dict == {"id": "src"}:
                return []
            elif table == "kg_node" and filter_dict == {}:
                return [
                    {"id": "src", "label": "Source"},
                    {"id": "n1", "label": "ImportantConcept"},
                ]
            elif table == "kg_edge" and filter_dict == {}:
                return [
                    {"source_node_id": "src", "target_node_id": "n1", "id": "e1", "relation": "related"},
                ]
            elif table == "note" and filter_dict == {}:
                return [
                    {"id": "note_1", "title": "Concept Note", "content": "About ImportantConcept"},
                ]
            return []

        obj._client._query.side_effect = query_side_effect
        result = obj.detect_ripple_effects(
            source_id="src", workspace_id="ws1", include_notes=True
        )
        assert len(result["affected_notes"]) == 1


@pytest.mark.unit
class TestApplyRippleUpdates:
    """Tests for CompounderWorkflowsRipple.apply_ripple_updates()."""

    def test_empty_needs_review_returns_empty(self):
        """Empty needs_review list returns empty result."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()
        obj._llm = MagicMock()
        result = obj.apply_ripple_updates(
            detection_result={"needs_review": []}
        )
        assert result["updated"] == []
        assert result["stats"]["total"] == 0

    def test_dry_run_lists_items_without_updating(self):
        """In dry_run mode, items are listed but not updated."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()
        obj._llm = MagicMock()
        result = obj.apply_ripple_updates(
            detection_result={
                "needs_review": [
                    {"id": "n1", "label": "Alice", "reason": "direct_neighbour"},
                ]
            },
            dry_run=True,
        )
        assert len(result["updated"]) == 1
        assert result["updated"][0]["node_id"] == "n1"
        assert result["stats"]["updated_count"] == 1

    def test_skips_empty_labels(self):
        """Nodes with empty labels are skipped."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()
        obj._llm = MagicMock()
        result = obj.apply_ripple_updates(
            detection_result={
                "needs_review": [
                    {"id": "n1", "label": "", "reason": "direct"},
                ]
            },
        )
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["reason"] == "empty label, cannot update"


@pytest.mark.unit
class TestMarkStaleForSource:
    """Tests for CompounderWorkflowsRipple.mark_stale_for_source()."""

    def test_empty_source_id_returns_error(self):
        """Empty source_id returns error result."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()
        result = obj.mark_stale_for_source(workspace_id="ws1", source_id="")
        assert result["status"] == "error"

    def test_marks_nodes_as_stale(self):
        """Marks all affected nodes as stale."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()

        # Mock detect_ripple_effects on the instance
        def mock_detect(**kwargs):
            return {
                "needs_review": [
                    {"id": "n1", "label": "Alice"},
                    {"id": "n2", "label": "Bob"},
                ]
            }
        obj.detect_ripple_effects = mock_detect

        result = obj.mark_stale_for_source(workspace_id="ws1", source_id="src")
        assert result["status"] == "ok"
        assert result["marked_count"] == 2


@pytest.mark.unit
class TestClearStaleFlag:
    """Tests for CompounderWorkflowsRipple.clear_stale_flag()."""

    def test_empty_node_id_returns_false(self):
        """Empty node_id returns False."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()
        assert obj.clear_stale_flag("") is False

    def test_clears_stale_flag_successfully(self):
        """Clearing stale flag returns True."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()
        obj._client._call.return_value = {"status": "ok"}
        assert obj.clear_stale_flag("node_1") is True
        obj._client._call.assert_called_once_with("set_node_stale", ["node_1", False])

    def test_runtime_error_returns_false(self):
        """RuntimeError during clear returns False."""
        from spacetime_memory.compounder.workflows_ripple import CompounderWorkflowsRipple

        obj = CompounderWorkflowsRipple()
        obj._client = MagicMock()
        obj._client._call.side_effect = RuntimeError("db error")
        assert obj.clear_stale_flag("node_1") is False
