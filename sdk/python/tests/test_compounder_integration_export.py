"""Integration tests for Compounder — full pipeline exercised against real STDB.

Requires a running SpacetimeDB standalone on localhost:3001 (handled by
the ``stdb_session`` fixture).  Tests marked ``embedder`` also need the
embedder sidecar at :9090 (or OPENAI_API_KEY pointing at a proxy).

Tests cover the LLM Wiki pipeline end-to-end:
  1. ``store_answer`` — persist a Q&A as a wiki note
  2. ``store_answers`` — batch persistence
  3. Manual node/edge creation → graph-based pipeline
  4. ``suggest_connections`` — pure-graph neighbour analysis
  5. ``lint_workspace`` — orphan/crossref/note-orphan detection
  6. ``export_workspace`` — markdown dump (backlinks, system notes, sanitized filenames)
  7. ``search_entities`` — label/type/semantic entity lookup
  8. ``find_near_duplicates`` — semantic duplicate detection
  9. ``cross_link`` — auto-link semantically similar memories
 10. ``create_entity_page`` / ``update_entity_page`` — entity wiki pages
 11. ``create_concept_page`` — concept definitions with cross-references
 12. ``create_comparison_page`` — comparison table pages
 13. ``ingest_source`` — document ingestion workflow
 14. ``generate_overview_page`` — workspace synthesis page
 15. ``export_workspace`` with ``include_kg`` / ``kg_json`` — KG node export
 16. ``detect_ripple_effects`` / ``apply_ripple_updates`` — ripple effect detection & application
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from spacetime_memory import Client
from spacetime_memory.compounder import Compounder

pytestmark = [
    pytest.mark.integration,
]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _unique(prefix: str = "ci") -> str:
    """Return a unique name for test entities."""
    suffix = os.urandom(4).hex()
    return f"{prefix}-{suffix}"


def _make_ws(client: Client) -> str:
    """Create a unique workspace and return its ID."""
    ws_name = _unique("ci-ws")
    result = client.create_workspace(ws_name)
    assert result["status"] == "ok"
    workspaces = client.list_workspaces()
    for ws in workspaces:
        if ws.get("name") == ws_name:
            return ws["id"]
    pytest.fail(f"Workspace '{ws_name}' not found after creation")


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def ws(stdb_client):
    """Unique workspace per test."""
    return _make_ws(stdb_client)


@pytest.fixture
def cp(stdb_client):
    """Compounder instance tied to the real STDB client (no LLM)."""
    return Compounder(stdb_client)


# =====================================================================
# Pipeline: store_answer → search → suggest_connections → export
# =====================================================================


class TestExportPipeline:
    """Part 4: export_workspace produces markdown files."""

    def test_export_creates_md_files(self, cp, ws):
        """Export should write .md files to the output directory."""
        # Add a note first
        cp.store_answer(
            query="Export test?",
            answer="This note should appear in the export.",
            workspace_id=ws,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = cp.export_workspace(tmpdir, workspace_id=ws)
            assert result["files_written"] >= 1
            md_files = list(Path(tmpdir).glob("*.md"))
            assert len(md_files) >= 1

    def test_export_excludes_system_notes_by_default(self, cp, ws):
        """System notes (_index, _log) should be excluded by default."""
        cp.store_answer(
            query="Export system?",
            answer="Note for system exclusion test.",
            workspace_id=ws,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cp.export_workspace(tmpdir, workspace_id=ws)
            written = [f.name for f in Path(tmpdir).glob("*.md")]
            system_prefixes = ["_index", "_log"]
            for prefix in system_prefixes:
                assert not any(f.startswith(prefix) for f in written), (
                    f"System note '{prefix}' leaked into export: {written}"
                )

    def test_export_includes_system_notes_when_requested(self, cp, ws):
        """With include_system_notes=True, _index and _log should be exported."""
        cp.store_answer(
            query="Export system 2?",
            answer="Note for system inclusion test.",
            workspace_id=ws,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cp.export_workspace(
                tmpdir,
                workspace_id=ws,
                include_system_notes=True,
            )
            written = [f.name for f in Path(tmpdir).glob("*.md")]
            assert "_index.md" in written or any("_index" in f for f in written), (
                f"Expected _index in export: {written}"
            )

    def test_export_empty_workspace(self, cp, ws):
        """Exporting an empty workspace should not error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = cp.export_workspace(tmpdir, workspace_id=ws)
            assert result["files_written"] >= 0
            assert isinstance(result["errors"], list)

    def test_export_sanitizes_special_chars_in_filenames(self, cp, ws):
        """Export should sanitize special characters in note titles."""
        cp._client.create_note(
            ws,
            "Special: chars/here?",
            "This title has special characters.",
            embed=False,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cp.export_workspace(tmpdir, workspace_id=ws)
            written = [f.name for f in Path(tmpdir).glob("*.md")]
            assert len(written) >= 1
            for fname in written:
                assert "?" not in fname, f"Special char '?' in filename: {fname}"
                assert "/" not in fname, f"Special char '/' in filename: {fname}"



    def test_export_includes_backlinks_in_frontmatter(self, cp, ws):
        """export_workspace should include backlinks in YAML frontmatter."""
        import tempfile
        from pathlib import Path as _Path

        # Create a note via client directly (no LLM needed)
        note = cp._client.create_note(ws, "BacklinkSource", "Content for backlink test", embed=False)
        note_id = note.get("id", "")

        # Create a KG node
        cp._client.create_node(ws, "ReferencedEntity", "concept", summary="Entity that is referenced")

        # Create an edge linking the note to the KG node
        if note_id:
            rows = cp._client._query("kg_node", workspace_id=ws, filter_dict={})
            node_map = {r["label"]: r["id"] for r in rows if "label" in r}
            if "ReferencedEntity" in node_map:
                cp._client._call(
                    "create_edge",
                    [ws, note_id, node_map["ReferencedEntity"], "references", 1.0, "EXTRACTED", "{}", ""],
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            cp.export_workspace(tmpdir, workspace_id=ws)
            export_files = list(_Path(tmpdir).glob("*.md"))
            note_content = None
            for f in export_files:
                if "BacklinkSource" in f.name:
                    note_content = f.read_text()
                    break
            assert note_content is not None, (
                f"BacklinkSource.md not found in {[f.name for f in export_files]}"
            )
            # Frontmatter should contain the backlinks section
            assert "backlinks:" in note_content, f"Missing backlinks in frontmatter:\n{note_content[:300]}"
            # The backlinks list should have at least one entry
            assert "    - " in note_content, (
                f"Expected at least one backlink entry in frontmatter:\n{note_content[:400]}"
            )

# =====================================================================
# search_entities pipeline
# =====================================================================



