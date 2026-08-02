"""Unit tests for CompounderHelpers — private helper methods."""

from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
class TestGenerateTitle:
    """Tests for CompounderHelpers._generate_title()."""

    def test_short_query_returns_query(self):
        """When query is under 80 chars, the query is returned."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        title = obj._generate_title("What is RLHF?", "RLHF is a method.")
        assert title == "What is RLHF"

    def test_long_query_uses_first_answer_line(self):
        """When query is >= 80 chars, first answer line is used."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        long_query = "What is the fundamental nature of consciousness in the context of modern neuroscience?" * 3
        title = obj._generate_title(long_query, "First line of answer.\nSecond line.")
        assert len(title) <= 80
        assert "First line of answer" in title

    def test_short_query_trims_punctuation(self):
        """Query trailing ? and . are stripped."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        assert obj._generate_title("What is X??", "") == "What is X"
        assert obj._generate_title("Hello.", "") == "Hello"

    def test_empty_query_and_answer(self):
        """With empty query and answer, returns empty string."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        title = obj._generate_title("", "")
        assert title == ""


@pytest.mark.unit

class TestResolveCreatedNote:
    """Tests for CompounderHelpers._resolve_created_note()."""

    def test_status_not_ok_returns_original(self):
        """When create_result status is not 'ok', returns original."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        result = obj._resolve_created_note("ws1", "Title", {"status": "error"})
        assert result == {"status": "error"}

    def test_matches_by_title_returns_first(self):
        """When get_note_by_title returns matches, returns first match."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client.get_note_by_title.return_value = [
            {"id": "n1", "title": "My Title", "content": "hello"}
        ]
        result = obj._resolve_created_note("ws1", "My Title", {"status": "ok"})
        assert result["id"] == "n1"
        obj._client.get_note_by_title.assert_called_once_with(
            "My Title", workspace_id="ws1"
        )

    def test_get_note_fallback_scans_notes(self):
        """When get_note_by_title fails, falls back to scanning recent notes."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client.get_note_by_title.return_value = []
        obj._client._query.return_value = [
            {"id": "n1", "title": "Wrong Title", "created_at": 100},
            {"id": "n2", "title": "My Title", "created_at": 200},
        ]
        result = obj._resolve_created_note("ws1", "My Title", {"status": "ok"})
        assert result["id"] == "n2"

    def test_empty_title_returns_original(self):
        """When title is empty, returns original result."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        result = obj._resolve_created_note("ws1", "", {"status": "ok"})
        assert result == {"status": "ok"}

    def test_get_note_by_title_runtime_error_fallback(self):
        """RuntimeError in get_note_by_title is caught and falls through to return original."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client.get_note_by_title.side_effect = RuntimeError("db error")
        obj._client._query.return_value = [
            {"id": "n1", "title": "My Title", "created_at": 100}
        ]
        result = obj._resolve_created_note("ws1", "My Title", {"status": "ok"})
        # RuntimeError is caught, function falls through to return create_result
        assert result == {"status": "ok"}


@pytest.mark.unit

class TestFormatAnswerPage:
    """Tests for CompounderHelpers._format_answer_page()."""

    def test_includes_question_and_synthesis(self):
        """Format answer page includes question and synthesis sections."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        page = obj._format_answer_page("What is X?", "X is a concept.")
        assert "## Question" in page
        assert "## Synthesis" in page
        assert "What is X?" in page
        assert "X is a concept." in page

    def test_includes_sources_when_provided(self):
        """Format answer page includes sources section when source_ids given."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        page = obj._format_answer_page("Q?", "A.", source_ids=["mem_1", "mem_2"])
        assert "## Sources" in page
        assert "`mem_1`" in page
        assert "`mem_2`" in page

    def test_omits_sources_when_not_provided(self):
        """Format answer page omits sources section when source_ids is None."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        page = obj._format_answer_page("Q?", "A.")
        assert "## Sources" not in page

    def test_empty_source_ids_list(self):
        """Empty source_ids list omits sources section."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        page = obj._format_answer_page("Q?", "A.", source_ids=[])
        assert "## Sources" not in page


@pytest.mark.unit

class TestUpdateIndex:
    """Tests for CompounderHelpers._update_index()."""

    def test_creates_index_when_none_exists(self):
        """When no index exists, creates a new _index note."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.return_value = []
        obj._update_index("ws1", "My Note", {"id": "n1", "content": "hello world"})
        obj._client.create_note.assert_called_once()
        call_kw = obj._client.create_note.call_args[1]
        assert call_kw["title"] == "_index"
        assert "[My Note](n1)" in call_kw["content"]

    def test_appends_to_existing_index(self):
        """When index exists, appends a new entry."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.return_value = [
            {"id": "idx_1", "content": "# Index\n\n- [Old](old_note)\n"}
        ]
        obj._update_index("ws1", "New Note", {"id": "n2", "content": "new content"})
        obj._client.update_note.assert_called_once()
        call_kw = obj._client.update_note.call_args[1]
        assert "Old" in call_kw["content"]
        assert "New Note" in call_kw["content"]

    def test_uses_provided_summary(self):
        """When summary is provided, it's used in the link entry."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.return_value = []
        obj._update_index(
            "ws1", "My Note", {"id": "n1", "content": "some content"},
            summary="A brief summary"
        )
        call_kw = obj._client.create_note.call_args[1]
        assert "A brief summary" in call_kw["content"]

    def test_generates_summary_from_content(self):
        """When no summary, first non-header line of content is used."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.return_value = []
        # Content with header first, then body text
        note = {"id": "n1", "content": "# Header\n\n---\n\nThis is the first real line of content.\nAnd this is more."}
        obj._update_index("ws1", "Note", note)
        call_kw = obj._client.create_note.call_args[1]
        assert "This is the first real line" in call_kw["content"]

    def test_update_index_runtime_error_ignored(self):
        """RuntimeError during index creation is silently ignored."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.return_value = []
        obj._client.create_note.side_effect = RuntimeError("db error")
        # Should not raise
        obj._update_index("ws1", "Note", {"id": "n1"})


@pytest.mark.unit

class TestAlreadyLinked:
    """Tests for CompounderHelpers._already_linked()."""

    def test_direct_link_found(self):
        """Returns True when A→B edge exists."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.return_value = [
            {"source_node_id": "A", "target_node_id": "B"},
        ]
        assert obj._already_linked("A", "B") is True

    def test_reverse_link_detected(self):
        """Returns True when B→A edge exists (reverse direction)."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.return_value = [
            {"source_node_id": "B", "target_node_id": "A"},
        ]
        assert obj._already_linked("A", "B") is True

    def test_no_link_returns_false(self):
        """Returns False when no edge connects the two IDs."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.return_value = [
            {"source_node_id": "A", "target_node_id": "C"},
        ]
        assert obj._already_linked("A", "B") is False

    def test_no_edges_returns_false(self):
        """Returns False when there are no edges at all."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        obj._client = MagicMock()
        obj._client._query.return_value = []
        assert obj._already_linked("A", "B") is False


@pytest.mark.unit

class TestNodeLabel:
    """Tests for CompounderHelpers._node_label()."""

    def test_finds_label_in_nodes(self):
        """Returns label when node ID is found in list."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        nodes = [
            {"id": "n1", "label": "Alice"},
            {"id": "n2", "label": "Bob"},
        ]
        assert obj._node_label("n1", nodes) == "Alice"

    def test_fallback_to_truncated_id(self):
        """When node ID not found, returns truncated ID."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        nodes = [{"id": "n1", "label": "Alice"}]
        label = obj._node_label("unknown_id_longer_than_12", nodes)
        assert label == "unknown_id_l"[:12]

    def test_empty_nodes_list(self):
        """Empty nodes list returns truncated ID."""
        from spacetime_memory.compounder.helpers import CompounderHelpers

        obj = CompounderHelpers()
        label = obj._node_label("test_id", [])
        assert label == "test_id"[:12]
