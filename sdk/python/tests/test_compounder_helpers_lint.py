"""Unit tests for CompounderHelpers — private helper methods."""

from unittest.mock import MagicMock

import pytest


@pytest.mark.unit

@pytest.mark.unit
class TestRippleUpdateEntity:
    """Tests for CompounderHelpers._ripple_update_entity()."""

    def test_skips_when_llm_unavailable(self):
        """When LLM is not available, does nothing."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._llm = MagicMock()
        obj._llm.available = False
        obj._ripple_update_entity("ws1", "Alice", "new info", "note_1")
        obj._client._query.assert_not_called()

    def test_skips_empty_entity_name(self):
        """Empty entity name is skipped."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._llm = MagicMock()
        obj._llm.available = True
        obj._ripple_update_entity("ws1", "", "info", "note_1")
        obj._client._query.assert_not_called()

    def test_skips_when_no_node_found(self):
        """When no node is found for entity name, does nothing."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._llm = MagicMock()
        obj._llm.available = True
        obj._client._query.return_value = []
        obj._ripple_update_entity("ws1", "Unknown", "info", "n1")
        assert True  # No exception

    def test_updates_node_with_llm_summary(self):
        """When node is found, uses LLM to merge and update."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._llm = MagicMock()
        obj._llm.available = True
        obj._llm.summarize.return_value = "Updated summary with new info integrated."
        obj._client._query.return_value = [
            {
                "id": "node_1",
                "label": "Alice",
                "summary": "Original summary",
                "node_type": "person",
            },
        ]
        obj._ripple_update_entity("ws1", "Alice", "Alice published a new paper.", "note_1")
        obj._client._call.assert_called_once()
        args = obj._client._call.call_args
        assert args[0][0] == "update_node"
        assert "Updated summary" in str(args[0][1])

    def test_no_update_when_summarize_returns_none(self):
        """When LLM summarize returns None, no update is made."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._llm = MagicMock()
        obj._llm.available = True
        obj._llm.summarize.return_value = None
        obj._client._query.return_value = [
            {"id": "node_1", "label": "Alice", "summary": "", "node_type": "person"},
        ]
        obj._ripple_update_entity("ws1", "Alice", "info", "note_1")
        obj._client._call.assert_not_called()

    def test_runtime_error_on_update_caught(self):
        """RuntimeError during update_node call is silently caught."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._llm = MagicMock()
        obj._llm.available = True
        obj._llm.summarize.return_value = "New summary."
        obj._client._query.return_value = [
            {"id": "node_1", "label": "Alice", "summary": "", "node_type": "person"},
        ]
        obj._client._call.side_effect = RuntimeError("db error")
        # Should not raise
        obj._ripple_update_entity("ws1", "Alice", "info", "note_1")


@pytest.mark.unit


class TestLogActivity:
    """Tests for CompounderHelpers._log_activity()."""

    def test_creates_log_when_none_exists(self):
        """Creates a _log note when none exists."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.return_value = []
        obj._log_activity("ws1", "test_event", "some detail")
        obj._client.create_note.assert_called_once()
        call_kw = obj._client.create_note.call_args[1]
        assert call_kw["title"] == "_log"
        assert "test_event" in call_kw["content"]

    def test_appends_to_existing_log(self):
        """Appends to existing _log note."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.return_value = [
            {"id": "log_1", "content": "# Log\n\n## [old] prior | entry\n"}
        ]
        obj._log_activity("ws1", "store_answer", "Created note")
        obj._client.update_note.assert_called_once()
        call_kw = obj._client.update_note.call_args[1]
        assert "prior" in call_kw["content"]
        assert "store_answer" in call_kw["content"]

    def test_runtime_error_on_create_ignored(self):
        """RuntimeError during _log creation is silently ignored."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.return_value = []
        obj._client.create_note.side_effect = RuntimeError("db error")
        obj._log_activity("ws1", "event", "detail")  # Should not raise

    def test_runtime_error_on_update_ignored(self):
        """RuntimeError during _log update is silently ignored."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.return_value = [
            {"id": "log_1", "content": "# Log\n"}
        ]
        obj._client.update_note.side_effect = RuntimeError("db error")
        obj._log_activity("ws1", "event", "detail")  # Should not raise


@pytest.mark.unit


class TestFindOrphanNodes:
    """Tests for CompounderHelpers._find_orphan_nodes()."""

    def test_returns_orphan_nodes(self):
        """Nodes with no edges are returned as orphans."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.side_effect = [
            [
                {"id": "n1", "label": "Connected", "node_type": "concept"},
                {"id": "n2", "label": "Orphan", "node_type": "concept"},
            ],
            [
                {"source_node_id": "n1", "target_node_id": "other"},
            ],
        ]
        orphans = obj._find_orphan_nodes("ws1")
        assert len(orphans) == 1
        assert orphans[0]["label"] == "Orphan"

    def test_empty_result_when_all_connected(self):
        """All nodes connected yields no orphans."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.side_effect = [
            [
                {"id": "n1", "label": "A", "node_type": "concept"},
                {"id": "n2", "label": "B", "node_type": "concept"},
            ],
            [
                {"source_node_id": "n1", "target_node_id": "n2"},
            ],
        ]
        assert obj._find_orphan_nodes("ws1") == []

    def test_no_nodes_returns_empty(self):
        """No nodes at all returns empty list."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.side_effect = [[], []]
        assert obj._find_orphan_nodes("ws1") == []


@pytest.mark.unit


class TestFindMissingCrossrefs:
    """Tests for CompounderHelpers._find_missing_crossrefs()."""

    def test_returns_missing_crossref(self):
        """Memory mentioning KG label with no edge is flagged."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.side_effect = [
            [{"id": "n1", "label": "ImportantConcept"}],  # kg_node
            [],  # kg_edge
            [{"id": "mem_1", "content": "This mentions ImportantConcept"}],  # memory
            [{"id": "note_1", "content": "Also mentions ImportantConcept"}],  # note
        ]
        missing = obj._find_missing_crossrefs("ws1")
        assert len(missing) >= 1
        assert missing[0]["mentioned_label"] == "importantconcept"
        assert missing[0]["entity_type"] == "memory"

    def test_no_label_map_returns_empty(self):
        """No KG nodes means no labels to check against."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.side_effect = [
            [],  # kg_node
            [],  # kg_edge
        ]
        assert obj._find_missing_crossrefs("ws1") == []

    def test_skips_items_with_no_content(self):
        """Memories/notes with no content are skipped."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.side_effect = [
            [{"id": "n1", "label": "AI"}],  # kg_node
            [],  # kg_edge
            [{"id": "mem_1", "content": ""}],  # memory (empty content)
            [{"id": "note_1", "content": ""}],  # note (empty content)
        ]
        assert obj._find_missing_crossrefs("ws1") == []


@pytest.mark.unit


class TestFindNoteOrphans:
    """Tests for CompounderHelpers._find_note_orphans()."""

    def test_note_with_no_label_mention_and_no_edge_is_orphan(self):
        """Note not mentioning any KG label and with no edges is orphan."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.side_effect = [
            [{"id": "n1", "title": "Lonely Note", "content": "Some random text."}],  # notes
            [{"id": "kg1", "label": "AI"}],  # kg_nodes
            [],  # edges
        ]
        orphans = obj._find_note_orphans("ws1")
        assert len(orphans) == 1
        assert orphans[0]["title"] == "Lonely Note"

    def test_note_mentioning_label_is_not_orphan(self):
        """Note that mentions a KG label is not an orphan."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.side_effect = [
            [{"id": "n1", "title": "About AI", "content": "AI is transforming everything."}],  # notes
            [{"id": "kg1", "label": "AI"}],  # kg_nodes
            [],  # edges
        ]
        orphans = obj._find_note_orphans("ws1")
        assert len(orphans) == 0

    def test_note_with_edge_is_not_orphan(self):
        """Note connected via an edge is not an orphan."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.side_effect = [
            [{"id": "n1", "title": "Connected", "content": "Some text."}],  # notes
            [{"id": "kg1", "label": "AI"}],  # kg_nodes
            [{"source_node_id": "n1", "target_node_id": "kg1"}],  # edges
        ]
        orphans = obj._find_note_orphans("ws1")
        assert len(orphans) == 0

    def test_no_notes_returns_empty(self):
        """Empty notes list yields no orphans."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.side_effect = [[], [], []]  # notes empty → early return
        assert obj._find_note_orphans("ws1") == []
