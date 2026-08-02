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
        notes = cp._client._query("note", workspace_id=ws, filter_dict={"title": "UpdatableEntity"})
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



