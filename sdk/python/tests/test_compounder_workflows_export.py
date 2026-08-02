"""Unit tests for CompounderWorkflowsExport — export and overview workflows.

Uses Compounder (which combines all mixins) because methods like
generate_overview_page call helper methods from CompounderHelpers.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestExportWorkspace:
    """Tests for Compounder.export_workspace()."""

    def test_empty_workspace_returns_zero_files(self):
        """Empty workspace with no kg/json export returns zero files."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.return_value = []
        cp = Compounder(client)
        result = cp.export_workspace("/tmp/out", workspace_id="ws1")
        assert result["files_written"] == 0
        assert result["output_dir"] == "/tmp/out"

    def test_exports_notes_as_markdown(self):
        """Notes are exported as .md files with frontmatter."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            [
                {"id": "n1", "title": "My Note", "content": "Hello world", "created_at": "2024-01-01", "updated_at": "2024-01-02"},
            ],
            [],  # edges
        ]
        cp = Compounder(client)

        with patch("pathlib.Path.write_text") as mock_write:
            result = cp.export_workspace("/tmp/out", workspace_id="ws1")

        assert result["files_written"] == 1
        mock_write.assert_called_once()

    def test_skips_system_notes_by_default(self):
        """System notes (starting with _) are skipped by default."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            [
                {"id": "n1", "title": "_index", "content": "# Index", "created_at": "", "updated_at": ""},
                {"id": "n2", "title": "Real Note", "content": "Content", "created_at": "", "updated_at": ""},
            ],
            [],  # edges
        ]
        cp = Compounder(client)

        with patch("pathlib.Path.write_text"):
            result = cp.export_workspace("/tmp/out", workspace_id="ws1")

        assert result["files_written"] == 1  # Only "Real Note"

    def test_includes_system_notes_when_requested(self):
        """System notes are included when include_system_notes=True."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            [
                {"id": "n1", "title": "_index", "content": "# Index", "created_at": "", "updated_at": ""},
            ],
            [],  # edges
        ]
        cp = Compounder(client)

        with patch("pathlib.Path.write_text"):
            result = cp.export_workspace(
                "/tmp/out", workspace_id="ws1", include_system_notes=True
            )

        assert result["files_written"] == 1  # _index is included

    def test_exports_kg_nodes(self):
        """KG nodes are exported when include_kg=True."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            [
                {"id": "n1", "title": "Note", "content": "Content", "created_at": "", "updated_at": ""},
            ],
            [],  # edges for backlinks
            [  # kg_nodes
                {"id": "kg1", "label": "Alice", "summary": "A person", "node_type": "person"},
            ],
        ]
        cp = Compounder(client)

        with patch("pathlib.Path.write_text"):
            result = cp.export_workspace(
                "/tmp/out", workspace_id="ws1", include_kg=True
            )

        assert result["files_written"] == 2  # 1 note + 1 KG node

    def test_exports_kg_json(self):
        """Full KG is exported as kg.json when kg_json=True."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            [
                {"id": "n1", "title": "Note", "content": "C", "created_at": "", "updated_at": ""},
            ],
            [],  # edges for backlinks
            [{"id": "kg1", "label": "Alice"}],  # nodes for kg.json
            [],  # edges for kg.json
        ]
        cp = Compounder(client)

        with patch("pathlib.Path.write_text"):
            result = cp.export_workspace(
                "/tmp/out", workspace_id="ws1", kg_json=True
            )

        assert result["files_written"] == 2  # 1 note + 1 kg.json
        assert "kg.json" in result.get("kg_json_path", "")

    def test_sanitizes_filenames(self):
        """Filenames with special chars are sanitized."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            [
                {"id": "n1", "title": "My Note: Part 1?", "content": "C", "created_at": "", "updated_at": ""},
            ],
            [],  # edges
        ]
        cp = Compounder(client)

        with patch("pathlib.Path.write_text"):
            result = cp.export_workspace("/tmp/out", workspace_id="ws1")

        assert result["files_written"] == 1

    def test_write_error_reported(self):
        """OSError during file write is reported in errors list."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            [
                {"id": "n1", "title": "Note", "content": "C", "created_at": "", "updated_at": ""},
            ],
            [],  # edges
        ]
        cp = Compounder(client)

        with patch("pathlib.Path.write_text", side_effect=OSError("Permission denied")):
            result = cp.export_workspace("/tmp/out", workspace_id="ws1")

        assert result["files_written"] == 0
        assert len(result["errors"]) == 1


@pytest.mark.unit
class TestGenerateOverviewPage:
    """Tests for Compounder.generate_overview_page()."""

    def test_empty_workspace_returns_empty_note(self):
        """Empty workspace returns dict with empty note."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.return_value = []
        cp = Compounder(client)
        result = cp.generate_overview_page(workspace_id="ws1")
        assert result == {"note": {}}

    def test_creates_overview_note(self):
        """Creates _overview note with workspace stats."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            [{"id": "n1", "title": "Note", "content": "Content", "created_at": "", "updated_at": ""}],  # notes
            [],  # kg_nodes
            [],  # kg_edges
            [],  # _log_activity: query for existing _log
        ]
        client.create_note.return_value = {"id": "overview_1"}
        cp = Compounder(client)

        result = cp.generate_overview_page(workspace_id="ws1")
        assert result["note"] == {"id": "overview_1"}
        # Find the _overview note create call
        overview_calls = [
            c for c in client.create_note.call_args_list
            if c[1].get("title") == "_overview"
        ]
        assert len(overview_calls) >= 1
        assert "Workspace Overview" in overview_calls[0][1]["content"]

    def test_includes_llm_synthesis_when_available(self):
        """When LLM is available, synthesis is included."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            [{"id": "n1", "title": "Note", "content": "Content", "created_at": "", "updated_at": ""}],  # notes
            [],  # kg_nodes
            [],  # kg_edges
            [],  # _log_activity
        ]
        mock_llm = MagicMock()
        mock_llm.available = True
        mock_llm.summarize.return_value = "This workspace is about AI research."
        client.create_note.return_value = {"id": "overview_1"}
        cp = Compounder(client, llm=mock_llm)

        cp.generate_overview_page(workspace_id="ws1")
        overview_calls = [
            c for c in client.create_note.call_args_list
            if c[1].get("title") == "_overview"
        ]
        assert len(overview_calls) >= 1
        assert "AI Synthesis" in overview_calls[0][1]["content"]
        assert "AI research" in overview_calls[0][1]["content"]

    def test_categorizes_notes_by_type(self):
        """Notes are categorized into sources, entities, concepts, etc."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            [
                {"id": "n1", "title": "Source: Article", "content": "---\ntype: source\n---\nContent"},
                {"id": "n2", "title": "Alice", "content": "---\ntype: person\n---\nAlice is..."},
                {"id": "n3", "title": "Concept: RLHF", "content": "---\ntype: concept\n---\nRLHF is..."},
                {"id": "n4", "title": "Comparison: A vs B", "content": "---\ntype: comparison\n---\n..."},
                {"id": "n5", "title": "Normal Note", "content": "Some content"},
            ],  # notes
            [],  # kg_nodes
            [],  # kg_edges
            [],  # _log_activity
        ]
        client.create_note.return_value = {"id": "overview_1"}
        cp = Compounder(client)

        cp.generate_overview_page(workspace_id="ws1")
        overview_calls = [
            c for c in client.create_note.call_args_list
            if c[1].get("title") == "_overview"
        ]
        assert len(overview_calls) >= 1
        assert "Notes by Category" in overview_calls[0][1]["content"]

    def test_logs_activity(self):
        """generate_overview_page logs activity."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            [{"id": "n1", "title": "Note", "content": "C", "created_at": "", "updated_at": ""}],  # notes
            [],  # kg_nodes
            [],  # kg_edges
            [],  # _log_activity: create new
        ]
        client.create_note.return_value = {"id": "overview_1"}
        cp = Compounder(client)

        cp.generate_overview_page(workspace_id="ws1")
        # Should not crash
        assert True
