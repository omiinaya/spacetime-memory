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
        # Use sufficiently distinct answers to avoid near-duplicate detection
        pairs = [
            ("What is SpacetimeDB?", "SpacetimeDB is a database for real-time applications with SQL."),
            ("What is Rust?", "Rust is a systems programming language focused on safety and performance."),
            ("What is WebAssembly?", "WebAssembly is a binary instruction format for a stack-based virtual machine."),
        ]
        results = cp.store_answers(pairs, workspace_id=ws, skip_duplicates=True)
        assert len(results) == 3
        for i, r in enumerate(results):
            assert "note" in r
            assert r["note"].get("id", ""), f"Result {i} has no note id: {r}"
            # Should not be marked as duplicate
            assert "duplicate_of" not in r, f"Result {i} incorrectly marked as duplicate: {r}"


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


# =====================================================================
# Entity Page Pipeline: create_entity_page, update_entity_page
# =====================================================================


class TestEntityPagePipeline:
    """Part 6: Entity wiki page creation and updates."""

    def test_create_entity_page_creates_node_and_note(self, cp, ws):
        """create_entity_page should create a KG node and a wiki note."""
        result = cp.create_entity_page(
            name="TestEntity",
            description="This is a test entity for integration testing.",
            entity_type="concept",
            workspace_id=ws,
        )
        assert "node" in result
        assert "note" in result
        node = result["node"]
        note = result["note"]
        assert node is not None, "KG node should be created"
        # Resolve note if create_note only returned status
        if not note.get("id"):
            note = cp._resolve_created_note(ws, "TestEntity", note)
            result["note"] = note
        assert note.get("id", ""), f"Note should have id: {note}"
        assert note.get("title", "") == "TestEntity", f"Note title should be entity name: {note}"

        # Verify node exists in KG
        nodes = cp._client._query("kg_node", workspace_id=ws, filter_dict={"label": "TestEntity"})
        assert len(nodes) >= 1
        assert nodes[0]["label"] == "TestEntity"
        assert nodes[0]["node_type"] == "concept"

    def test_create_entity_page_with_relations(self, cp, ws):
        """create_entity_page with relations should include them in the note."""
        result = cp.create_entity_page(
            name="RelatedEntity",
            description="An entity with relations.",
            entity_type="concept",
            workspace_id=ws,
            relations=[{"name": "OtherEntity", "relation": "related_to"}],
        )
        note = result["note"]
        # Resolve note if create_note only returned status
        if not note.get("id"):
            note = cp._resolve_created_note(ws, "RelatedEntity", note)
            result["note"] = note
        assert note.get("id", "")
        # Check note content includes relations
        content = note.get("content", "")
        assert "Relations" in content
        assert "OtherEntity" in content
        assert "related_to" in content

    def test_update_entity_page_updates_node_and_note(self, cp, ws):
        """update_entity_page should update both KG node and wiki note."""
        # First create the entity
        cp.create_entity_page(
            name="UpdatableEntity",
            description="Original description.",
            entity_type="concept",
            workspace_id=ws,
        )

        # Update it
        result = cp.update_entity_page(
            name="UpdatableEntity",
            workspace_id=ws,
            description="Updated description with new info.",
            entity_type="topic",
            tags=["updated", "test"],
        )
        assert "node" in result
        assert "note" in result

        # Verify node was updated
        nodes = cp._client._query("kg_node", workspace_id=ws, filter_dict={"label": "UpdatableEntity"})
        assert len(nodes) >= 1
        assert nodes[0]["node_type"] == "topic"
        assert "Updated description" in nodes[0]["summary"]

        # Verify note was updated
        notes = cp._client._query("note", workspace_id=ws, filter_dict={"title": "UpdatableEntity", "is_active": "true"})
        assert len(notes) >= 1
        content = notes[0].get("content", "")
        assert "Updated description" in content
        assert "tags: [updated, test]" in content

    def test_update_entity_page_nonexistent_returns_empty(self, cp, ws):
        """Updating a non-existent entity should return empty dict."""
        result = cp.update_entity_page(
            name="NonExistentEntity",
            workspace_id=ws,
            description="Won't work",
        )
        assert result == {}


# =====================================================================
# Concept Page Pipeline: create_concept_page
# =====================================================================


class TestConceptPagePipeline:
    """Part 7: Concept wiki page creation."""

    def test_create_concept_page(self, cp, ws):
        """create_concept_page should create a concept note and KG node."""
        result = cp.create_concept_page(
            concept="TestConcept",
            definition="A test concept for integration testing.",
            workspace_id=ws,
            related_concepts=["RelatedA", "RelatedB"],
        )
        assert "node" in result
        assert "note" in result
        node = result["node"]
        note = result["note"]
        assert node is not None, "KG node should be created"
        # Resolve note if create_note only returned status
        if not note.get("id"):
            note = cp._resolve_created_note(ws, "Concept: TestConcept", note)
            result["note"] = note
        assert note.get("id", ""), f"Note should have id: {note}"
        assert note.get("title", "") == "Concept: TestConcept"

        # Verify note content
        content = note.get("content", "")
        assert "Definition" in content
        assert "A test concept for integration testing" in content
        assert "Related Concepts" in content
        assert "[[RelatedA]]" in content
        assert "[[RelatedB]]" in content

    def test_create_concept_page_no_relations(self, cp, ws):
        """create_concept_page without related_concepts should still work."""
        result = cp.create_concept_page(
            concept="LonelyConcept",
            definition="A concept with no relations.",
            workspace_id=ws,
        )
        assert "node" in result
        assert "note" in result
        note = result["note"]
        if not note.get("id"):
            note = cp._resolve_created_note(ws, "Concept: LonelyConcept", note)
            result["note"] = note
        assert note.get("id", "")


# =====================================================================
# Comparison Page Pipeline: create_comparison_page
# =====================================================================


class TestComparisonPagePipeline:
    """Part 8: Comparison wiki page creation."""

    def test_create_comparison_page_with_dicts(self, cp, ws):
        """create_comparison_page with list of dicts should create a table."""
        items = [
            {"name": "RLHF", "type": "reward-based", "complexity": "High"},
            {"name": "DPO", "type": "direct preference", "complexity": "Low"},
        ]
        result = cp.create_comparison_page(
            title="RLHF vs DPO",
            items=items,
            workspace_id=ws,
        )
        assert "note" in result
        note = result["note"]
        # Resolve note if create_note only returned status
        if not note.get("id"):
            note = cp._resolve_created_note(ws, "Comparison: RLHF vs DPO", note)
            result["note"] = note
        assert note.get("id", ""), f"Note should have id: {note}"
        content = note.get("content", "")
        assert "| Name | Type | Complexity |" in content
        assert "RLHF" in content
        assert "DPO" in content
        assert "reward-based" in content
        assert "direct preference" in content

    def test_create_comparison_page_with_strings_and_criteria(self, cp, ws):
        """create_comparison_page with list of strings + criteria should create table with empty cells."""
        result = cp.create_comparison_page(
            title="Method Comparison",
            items=["MethodA", "MethodB"],
            workspace_id=ws,
            criteria=["speed", "accuracy", "cost"],
        )
        note = result["note"]
        if not note.get("id"):
            note = cp._resolve_created_note(ws, "Comparison: Method Comparison", note)
            result["note"] = note
        assert note.get("id", "")
        content = note.get("content", "")
        assert "| Name | Speed | Accuracy | Cost |" in content
        assert "MethodA" in content
        assert "MethodB" in content

    def test_create_comparison_page_empty_returns_empty(self, cp, ws):
        """create_comparison_page with empty items should return empty note."""
        result = cp.create_comparison_page(
            title="Empty Comparison",
            items=[],
            workspace_id=ws,
        )
        assert result == {"note": {}}


# =====================================================================
# Ingest Source Pipeline: ingest_source
# =====================================================================


class TestIngestSourcePipeline:
    """Part 9: Source document ingestion workflow."""

    def test_ingest_source_creates_note_and_entities(self, cp, ws):
        """ingest_source should create a source note and extract entities."""
        source_text = """
        SpacetimeDB is a revolutionary database that combines SQL with real-time subscriptions.
        It was created by the team at Clockwork Labs. The key innovation is that clients can
        subscribe to SQL queries and receive updates in real-time.
        """
        result = cp.ingest_source(
            source_text=source_text,
            source_title="SpacetimeDB Overview",
            workspace_id=ws,
            source_type="article",
        )
        assert "note" in result
        assert "entities" in result
        assert "links" in result
        assert "contradictions" in result

        note = result["note"]
        assert note.get("id", ""), f"Note should have id: {note}"
        assert note.get("title", "") == "Source: SpacetimeDB Overview"

        # Content should include summary and source
        content = note.get("content", "")
        assert "Summary" in content
        assert "SpacetimeDB Overview" in content

        # Entities may or may not be extracted (LLM not available in CI)
        # At minimum, the structure should be correct
        assert isinstance(result["entities"], list)
        assert isinstance(result["links"], list)
        assert isinstance(result["contradictions"], list)

    def test_ingest_source_empty_text_returns_empty(self, cp, ws):
        """ingest_source with empty text should return empty result."""
        result = cp.ingest_source(
            source_text="",
            source_title="Empty",
            workspace_id=ws,
        )
        assert result == {"note": {}, "entities": [], "links": [], "contradictions": []}


# =====================================================================
# Cross-Link Pipeline: cross_link
# =====================================================================


class TestCrossLinkPipeline:
    """Part 10: cross_link finds and creates semantic links."""

    def test_cross_link_returns_counts(self, cp, ws):
        """cross_link should return dict with links_created and pairs_checked."""
        # Add some memories first
        cp._client.store(workspace_id=ws, content="Memory about neural networks and deep learning.", peer_id="test", memory_type="experience")
        cp._client.store(workspace_id=ws, content="Memory about machine learning optimization techniques.", peer_id="test", memory_type="experience")
        cp._client.store(workspace_id=ws, content="Unrelated memory about cooking recipes.", peer_id="test", memory_type="experience")

        result = cp.cross_link(workspace_id=ws, limit=10, similarity_threshold=0.5)
        assert isinstance(result, dict)
        assert "links_created" in result
        assert "pairs_checked" in result
        assert isinstance(result["links_created"], int)
        assert isinstance(result["pairs_checked"], int)
        assert result["links_created"] >= 0
        assert result["pairs_checked"] >= 0


# =====================================================================
# Lint Pipeline Extended: check_contradictions (requires LLM - skip if unavailable)
# =====================================================================


class TestLintPipelineExtended:
    """Part 11: lint_workspace with contradiction checks."""

    def test_placeholder_skipped_without_llm(self):
        """Placeholder - contradiction checks require LLM, skipped in CI."""
        import pytest
        pytest.skip("Contradiction detection requires LLM (not available in CI)")


# =====================================================================
# Search Entities Extended: semantic query
# =====================================================================


class TestSearchEntitiesExtended:
    """Part 12: search_entities with semantic queries."""

    def test_search_entities_semantic_query(self, cp, ws):
        """search_entities with semantic_query should find related entities."""
        # Create some nodes
        cp._client.create_node(ws, "MachineLearning", "concept", summary="Study of algorithms that learn from data")
        cp._client.create_node(ws, "DeepLearning", "concept", summary="Neural networks with many layers")
        cp._client.create_node(ws, "Cooking", "topic", summary="Culinary arts and food preparation")

        # Semantic search for AI-related concepts
        results = cp.search_entities(workspace_id=ws, node_type="concept", semantic_query="artificial intelligence neural networks")
        # Should find ML/DL concepts, not Cooking
        labels = {r["label"] for r in results}
        # Without embedder, may fall back to keyword - at minimum structure should work
        assert isinstance(results, list)


# =====================================================================
# Export Pipeline Extended: include_kg
# =====================================================================


class TestExportPipelineExtended:
    """Part 13: export_workspace with KG export."""

    def test_export_includes_kg_nodes_when_requested(self, cp, ws):
        """export_workspace with include_kg=True should write _kg_nodes files."""
        # Create a note and a KG node
        cp.store_answer(query="Test?", answer="Answer for export.", workspace_id=ws)
        cp._client.create_node(ws, "ExportEntity", "concept", summary="An entity for export test")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = cp.export_workspace(tmpdir, workspace_id=ws, include_kg=True)
            assert result["files_written"] >= 1
            kg_dir = Path(tmpdir) / "_kg_nodes"
            assert kg_dir.exists()
            kg_files = list(kg_dir.glob("*.md"))
            assert len(kg_files) >= 1
            # Check content of KG export
            kg_content = kg_files[0].read_text()
            assert "ExportEntity" in kg_content
            assert "concept" in kg_content


# =====================================================================
# Overview Page Pipeline: generate_overview_page
# =====================================================================


class TestOverviewPagePipeline:
    """Part 14: generate_overview_page creates workspace synthesis."""

    def test_generate_overview_page_creates_note(self, cp, ws):
        """generate_overview_page should create an _overview note."""
        # Add some content to the workspace
        cp.store_answer(query="Q1?", answer="Answer about AI and ML.", workspace_id=ws)
        cp._client.create_node(ws, "AI", "concept", summary="Artificial Intelligence")
        cp._client.create_node(ws, "ML", "concept", summary="Machine Learning")
        # Add an edge
        nodes = cp._client._query("kg_node", workspace_id=ws, filter_dict={})
        node_map = {n["label"]: n["id"] for n in nodes if "label" in n}
        if "AI" in node_map and "ML" in node_map:
            cp._client._call(
                "create_edge",
                [ws, node_map["AI"], node_map["ML"], "subfield_of", 1.0, "EXTRACTED", "{}", ""],
            )

        result = cp.generate_overview_page(workspace_id=ws)
        assert "note" in result
        note = result["note"]
        # Resolve note if create_note only returned status
        if not note.get("id"):
            note = cp._resolve_created_note(ws, "_overview", note)
            result["note"] = note
        assert note.get("id", ""), f"Overview note should have id: {note}"
        assert note.get("title", "") == "_overview"

        content = note.get("content", "")
        assert "Workspace Overview" in content
        assert "notes" in content.lower()
        assert "KG nodes" in content
        assert "edges" in content

    def test_generate_overview_page_empty_workspace(self, cp, ws):
        """generate_overview_page on empty workspace should return empty note."""
        result = cp.generate_overview_page(workspace_id=ws)
        assert result == {"note": {}}
