"""Integration tests for Compounder — full pipeline exercised against real STDB.

Requires a running SpacetimeDB standalone on localhost:3001 (handled by
the ``stdb_session`` fixture).  Tests marked ``embedder`` also need the
embedder sidecar at :9090 (or OPENAI_API_KEY pointing at a proxy).

Tests cover the LLM Wiki pipeline end-to-end:
  1. ``store_answer`` — persist a Q&A as a wiki note
  2. ``store_answers`` — batch persistence
  3. Manual node/edge creation → graph-based pipeline
  4. ``suggest_connections`` — pure-graph neighbour analysis
  5. ``lint_workspace`` — orphan/crossref detection
  6. ``export_workspace`` — markdown dump
  7. ``search_entities`` — label/type/semantic entity lookup
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


class TestStoreAnswerPipeline:
    """Part 1: store_answer creates notes, updates _index and _log."""

    def test_store_answer_creates_note(self, cp, ws):
        """A basic store_answer should persist a wiki note."""
        result = cp.store_answer(
            query="What is SpacetimeDB?",
            answer="SpacetimeDB is a database for real-time applications.",
            workspace_id=ws,
        )
        assert "note" in result
        note = result["note"]
        assert isinstance(note, dict), f"Expected dict, got {type(note)}"
        # The note dict should have an id after _resolve_created_note
        assert note.get("id", ""), f"Note has no id: {note}"
        assert note.get("title", ""), f"Note has no title: {note}"

    def test_store_answer_with_source_ids_creates_edges(self, cp, ws, stdb_client):
        """When source_memory_ids are provided, edges should be created."""
        # First store a memory to use as source
        store_result = stdb_client.store(
            workspace_id=ws,
            content="Source memory for edge creation test",
            peer_id="ci-bot",
            memory_type="experience",
        )
        assert store_result["status"] == "ok"
        mems = stdb_client.list_memories(workspace_id=ws, limit=5)
        assert len(mems) >= 1
        source_id = mems[0]["id"]

        result = cp.store_answer(
            query="Test edge creation?",
            answer="This answer references a source memory.",
            workspace_id=ws,
            source_memory_ids=[source_id],
        )
        assert len(result["links"]) >= 1
        assert source_id in result["links"]

    def test_store_answer_updates_index_and_log(self, cp, ws):
        """After store_answer, _index and _log should exist."""
        cp.store_answer(
            query="Index test?",
            answer="This tests the index page.",
            workspace_id=ws,
        )
        # Query for system pages
        notes = cp._client._query("note", workspace_id=ws, filter_dict={})
        titles = [n.get("title", "") for n in notes]
        assert "_index" in titles, f"_index not found in notes: {titles}"
        assert "_log" in titles, f"_log not found in notes: {titles}"

    def test_store_answers_batch(self, cp, ws):
        """Batch store_answers should persist multiple notes."""
        pairs = [
            ("Q1?", "Answer one for batch test."),
            ("Q2?", "Answer two for batch test."),
            ("Q3?", "Answer three for batch test."),
        ]
        results = cp.store_answers(pairs, workspace_id=ws)
        assert len(results) == 3
        for i, r in enumerate(results):
            assert "note" in r
            assert r["note"].get("id", ""), f"Result {i} has no note id: {r}"


# =====================================================================
# Graph Pipeline: nodes → edges → suggest_connections
# =====================================================================


class TestGraphPipeline:
    """Part 2: Knowledge-graph operations that don't need an embedder."""

    def test_create_nodes_and_edges_manually(self, stdb_client, ws):
        """Create a small KG and verify it's stored."""
        n1 = stdb_client.create_node(ws, "NodeA", "concept", summary="First node")
        assert n1["status"] == "ok"
        n2 = stdb_client.create_node(ws, "NodeB", "concept", summary="Second node")
        assert n2["status"] == "ok"

        # Look up node IDs
        rows = stdb_client._query("kg_node", workspace_id=ws, filter_dict={})
        node_map = {r["label"]: r["id"] for r in rows if "label" in r}
        assert "NodeA" in node_map
        assert "NodeB" in node_map

        # Create an edge between them
        edge_result = stdb_client._call(
            "create_edge",
            [
                ws,
                node_map["NodeA"],
                node_map["NodeB"],
                "relates_to",
                1.0,
                "EXTRACTED",
                "{}",
                "",
            ],
        )
        assert edge_result["status"] == "ok"

    def test_suggest_connections_finds_unlinked_nodes(self, stdb_client, ws):
        """suggest_connections should find node pairs sharing neighbours."""
        # Create 4 nodes: A, B, C, D
        # Connect A-B, B-C, C-D
        # A and C share neighbour B, but aren't directly linked
        labels = ["Alpha", "Beta", "Gamma", "Delta"]
        for label in labels:
            stdb_client.create_node(ws, label, "concept", summary=f"Node {label}")

        rows = stdb_client._query("kg_node", workspace_id=ws, filter_dict={})
        node_map = {r["label"]: r["id"] for r in rows if "label" in r}

        # A-B
        stdb_client._call(
            "create_edge",
            [
                ws,
                node_map["Alpha"],
                node_map["Beta"],
                "relates_to",
                1.0,
                "EXTRACTED",
                "{}",
                "",
            ],
        )
        # B-C
        stdb_client._call(
            "create_edge",
            [
                ws,
                node_map["Beta"],
                node_map["Gamma"],
                "relates_to",
                1.0,
                "EXTRACTED",
                "{}",
                "",
            ],
        )
        # C-D
        stdb_client._call(
            "create_edge",
            [
                ws,
                node_map["Gamma"],
                node_map["Delta"],
                "relates_to",
                1.0,
                "EXTRACTED",
                "{}",
                "",
            ],
        )

        cp = Compounder(stdb_client)
        suggestions = cp.suggest_connections(workspace_id=ws)
        assert isinstance(suggestions, list)

        # Alpha and Gamma share Beta as a neighbour → should be suggested
        alpha_gamma = [
            s
            for s in suggestions
            if {s.get("source_label"), s.get("target_label")} == {"Alpha", "Gamma"}
        ]
        assert len(alpha_gamma) >= 1, f"Expected Alpha↔Gamma suggestion, got: {suggestions}"

        # Beta and Delta share Gamma as a neighbour → should be suggested
        beta_delta = [
            s
            for s in suggestions
            if {s.get("source_label"), s.get("target_label")} == {"Beta", "Delta"}
        ]
        assert len(beta_delta) >= 1, f"Expected Beta↔Delta suggestion, got: {suggestions}"

    def test_suggest_connections_empty_workspace(self, cp, ws):
        """Empty workspace should yield no suggestions."""
        suggestions = cp.suggest_connections(workspace_id=ws)
        assert suggestions == []


# =====================================================================
# Lint Pipeline
# =====================================================================


class TestLintPipeline:
    """Part 3: lint_workspace without LLM (orphans + crossrefs)."""

    def test_lint_finds_orphan_nodes(self, stdb_client, ws):
        """A node with no edges should be reported as an orphan."""
        stdb_client.create_node(ws, "OrphanNode", "concept", summary="I have no friends")
        cp = Compounder(stdb_client)
        report = cp.lint_workspace(workspace_id=ws, check_contradictions=False)
        assert report["summary"]["orphan_count"] >= 1
        labels = [o.get("label", "") for o in report["orphans"]]
        assert "OrphanNode" in labels

    def test_lint_no_orphans_when_all_linked(self, stdb_client, ws):
        """If all nodes have edges, orphans should be empty."""
        stdb_client.create_node(ws, "LinkedA", "concept", summary="A")
        stdb_client.create_node(ws, "LinkedB", "concept", summary="B")
        rows = stdb_client._query("kg_node", workspace_id=ws, filter_dict={})
        node_map = {r["label"]: r["id"] for r in rows if "label" in r}
        stdb_client._call(
            "create_edge",
            [
                ws,
                node_map["LinkedA"],
                node_map["LinkedB"],
                "relates_to",
                1.0,
                "EXTRACTED",
                "{}",
                "",
            ],
        )
        cp = Compounder(stdb_client)
        report = cp.lint_workspace(workspace_id=ws, check_contradictions=False)
        assert report["summary"]["orphan_count"] == 0

    def test_lint_finds_missing_crossrefs(self, cp, ws, stdb_client):
        """A note mentioning a known entity without an edge should be flagged."""
        # Create a KG node
        stdb_client.create_node(ws, "ReferencedEntity", "concept", summary="An entity to reference")

        # Create a note that mentions the entity label but has no edge to it
        stdb_client.create_note(
            ws,
            "Note About Entity",
            "This note mentions ReferencedEntity in its content.",
            embed=False,
        )

        report = cp.lint_workspace(workspace_id=ws, check_contradictions=False)
        # We should have at least one missing crossref
        missing = report["missing_crossrefs"]
        assert len(missing) >= 1, f"Expected crossref violations, got: {report}"
        # At least one should reference the entity we created
        labels = [m.get("mentioned_label", "") for m in missing]
        assert "referencedentity" in labels, f"Expected ReferencedEntity in: {labels}"


# =====================================================================
# Export Pipeline
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


# =====================================================================
# search_entities pipeline
# =====================================================================


class TestSearchEntitiesPipeline:
    """Part 5: Compounder.search_entities with real STDB."""

    def test_search_by_label(self, stdb_client, ws):
        """search_entities with exact label should find the node."""
        stdb_client.create_node(ws, "UniqueLabel", "concept", summary="A unique entity")
        cp = Compounder(stdb_client)
        results = cp.search_entities(workspace_id=ws, label="UniqueLabel")
        assert len(results) >= 1
        assert results[0]["label"] == "UniqueLabel"

    def test_search_by_type(self, stdb_client, ws):
        """search_entities with node_type filter should work."""
        stdb_client.create_node(ws, "ConceptA", "concept", summary="A concept")
        stdb_client.create_node(ws, "ConceptB", "concept", summary="Another concept")
        cp = Compounder(stdb_client)
        results = cp.search_entities(workspace_id=ws, node_type="concept")
        assert len(results) >= 2
        types = {r["node_type"] for r in results}
        assert types == {"concept"}

    def test_search_entities_no_match(self, cp, ws):
        """Searching for a non-existent label should return empty."""
        results = cp.search_entities(workspace_id=ws, label="NonExistentEntity")
        assert results == []
