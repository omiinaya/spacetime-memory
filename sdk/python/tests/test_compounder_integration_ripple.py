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


class TestRippleEffectsPipeline:
    """Part 16: Ripple effect detection and application."""

    def test_detect_on_kg_node_direct_neighbours(self, stdb_client, ws):
        """detect_ripple_effects on a kg_node finds its directly-connected neighbours."""
        stdb_client.create_node(ws, "Primary", "concept", summary="Primary entity")
        stdb_client.create_node(ws, "Secondary", "concept", summary="Secondary entity")
        stdb_client.create_node(ws, "Unrelated", "concept", summary="Not connected")
        nodes = stdb_client._query("kg_node", workspace_id=ws, filter_dict={})
        node_map = {n["label"]: n["id"] for n in nodes if "label" in n}
        stdb_client._call(
            "create_edge",
            [ws, node_map["Primary"], node_map["Secondary"], "relates_to", 1.0, "EXTRACTED", "{}", ""],
        )
        cp = Compounder(stdb_client)
        result = cp.detect_ripple_effects(source_id=node_map["Primary"], workspace_id=ws)
        assert result["source"]["type"] == "kg_node"
        assert result["source"]["label"] == "Primary"
        assert result["stats"]["direct_count"] == 1
        assert result["stats"]["transitive_count"] == 0
        assert result["directly_affected"][0]["label"] == "Secondary"
        assert result["directly_affected"][0]["reason"] == "direct_neighbour"
        affected_ids = {e["id"] for e in result["directly_affected"]}
        assert node_map["Unrelated"] not in affected_ids

    def test_detect_on_kg_node_transitive(self, stdb_client, ws):
        """detect_ripple_effects with max_hops=2 finds transitive neighbours."""
        stdb_client.create_node(ws, "A", "concept", summary="A")
        stdb_client.create_node(ws, "B", "concept", summary="B")
        stdb_client.create_node(ws, "C", "concept", summary="C")
        nodes = stdb_client._query("kg_node", workspace_id=ws, filter_dict={})
        node_map = {n["label"]: n["id"] for n in nodes if "label" in n}
        stdb_client._call("create_edge", [ws, node_map["A"], node_map["B"], "next", 1.0, "EXTRACTED", "{}", ""])
        stdb_client._call("create_edge", [ws, node_map["B"], node_map["C"], "next", 1.0, "EXTRACTED", "{}", ""])
        cp = Compounder(stdb_client)
        result = cp.detect_ripple_effects(source_id=node_map["A"], workspace_id=ws, max_hops=2)
        assert result["stats"]["direct_count"] == 1  # B
        assert result["stats"]["transitive_count"] == 1  # C
        trans_labels = {e["label"] for e in result["transitively_affected"]}
        assert "C" in trans_labels

    def test_detect_on_note_source(self, stdb_client, ws):
        """A note source finds nodes with matching source_memory_id."""
        note = stdb_client.create_note(ws, "SourceNote", "Source content", embed=False)
        note_id = note.get("id", "")
        if not note_id:
            notes = stdb_client._query("note", workspace_id=ws, filter_dict={"title": "SourceNote"})
            note_id = notes[0]["id"] if notes else ""
        assert note_id, "Note must have an ID"
        stdb_client.create_node(ws, "EntA", "concept", summary="From note", source_memory_id=note_id)
        stdb_client.create_node(ws, "EntB", "concept", summary="Also from note", source_memory_id=note_id)
        cp = Compounder(stdb_client)
        result = cp.detect_ripple_effects(source_id=note_id, workspace_id=ws)
        assert result["source"]["type"] == "note"
        assert result["source"]["label"] == "SourceNote"
        assert result["stats"]["direct_count"] >= 2
        affected_labels = {e["label"] for e in result["directly_affected"]}
        assert "EntA" in affected_labels
        assert "EntB" in affected_labels

    def test_detect_on_memory_source(self, stdb_client, ws):
        """A memory source finds nodes with matching source_memory_id."""
        store_result = stdb_client.store(workspace_id=ws, content="Memory for ripple test", peer_id="test")
        mem_id = store_result.get("id", "")
        if not mem_id:
            memories = stdb_client._query("memory", workspace_id=ws, filter_dict={})
            mem_id = memories[-1]["id"] if memories else ""
        assert mem_id, "Memory must have an ID"
        stdb_client.create_node(ws, "MemEntity", "concept", summary="From memory", source_memory_id=mem_id)
        cp = Compounder(stdb_client)
        result = cp.detect_ripple_effects(source_id=mem_id, workspace_id=ws)
        assert result["source"]["type"] == "memory"
        assert result["stats"]["direct_count"] >= 1
        assert any(e["label"] == "MemEntity" for e in result["directly_affected"])

    def test_detect_no_neighbours(self, stdb_client, ws):
        """A KG node with no edges has no ripple effects."""
        stdb_client.create_node(ws, "Lonely", "concept", summary="Alone")
        nodes = stdb_client._query("kg_node", workspace_id=ws, filter_dict={})
        cp = Compounder(stdb_client)
        result = cp.detect_ripple_effects(source_id=nodes[0]["id"], workspace_id=ws)
        assert result["stats"]["direct_count"] == 0
        assert result["stats"]["transitive_count"] == 0
        assert result["needs_review"] == []

    def test_detect_source_not_found(self, cp, ws):
        """Unknown source_id returns empty result gracefully."""
        result = cp.detect_ripple_effects(source_id="nonexistent", workspace_id=ws)
        assert result["stats"]["direct_count"] == 0
        assert result["stats"]["transitive_count"] == 0
        assert result["needs_review"] == []

    def test_detect_empty_source_id(self, cp, ws):
        """Empty source_id returns an error."""
        result = cp.detect_ripple_effects(source_id="", workspace_id=ws)
        assert "error" in result

    def test_include_notes_finds_textual_matches(self, stdb_client, ws):
        """include_notes=True finds notes that reference affected entity labels."""
        stdb_client.create_node(ws, "RippleEntity", "concept", summary="Entity")
        nodes = stdb_client._query("kg_node", workspace_id=ws, filter_dict={})
        node_map = {n["label"]: n["id"] for n in nodes if "label" in n}
        stdb_client.create_note(ws, "ReferencingNote", "This discusses RippleEntity in context.", embed=False)
        cp = Compounder(stdb_client)
        result = cp.detect_ripple_effects(
            source_id=node_map["RippleEntity"], workspace_id=ws, include_notes=True
        )
        assert len(result.get("affected_notes", [])) >= 1
        note_titles = {n["title"] for n in result["affected_notes"]}
        assert "ReferencingNote" in note_titles

    def test_max_hops_clamping(self, stdb_client, ws):
        """max_hops clamps to [1, 6]; low values restrict reach."""
        stdb_client.create_node(ws, "X", "concept", summary="X")
        stdb_client.create_node(ws, "Y", "concept", summary="Y")
        stdb_client.create_node(ws, "Z", "concept", summary="Z")
        nodes = stdb_client._query("kg_node", workspace_id=ws, filter_dict={})
        node_map = {n["label"]: n["id"] for n in nodes if "label" in n}
        stdb_client._call("create_edge", [ws, node_map["X"], node_map["Y"], "next", 1.0, "EXTRACTED", "{}", ""])
        stdb_client._call("create_edge", [ws, node_map["Y"], node_map["Z"], "next", 1.0, "EXTRACTED", "{}", ""])
        cp = Compounder(stdb_client)
        r1 = cp.detect_ripple_effects(source_id=node_map["X"], workspace_id=ws, max_hops=0)
        assert r1["stats"]["direct_count"] == 1
        assert r1["stats"]["transitive_count"] == 0
        r2 = cp.detect_ripple_effects(source_id=node_map["X"], workspace_id=ws, max_hops=999)
        assert r2["stats"]["transitive_count"] >= 1
        trans_labels = {e["label"] for e in r2["transitively_affected"]}
        assert "Z" in trans_labels

    def test_detect_with_cycles(self, stdb_client, ws):
        """Cycles in the graph do not cause infinite loops or duplicates."""
        for label in ("CycA", "CycB", "CycC"):
            stdb_client.create_node(ws, label, "concept", summary=label)
        nodes = stdb_client._query("kg_node", workspace_id=ws, filter_dict={})
        node_map = {n["label"]: n["id"] for n in nodes if "label" in n}
        for src, tgt in [("CycA", "CycB"), ("CycB", "CycC"), ("CycC", "CycA")]:
            stdb_client._call(
                "create_edge", [ws, node_map[src], node_map[tgt], "related", 1.0, "EXTRACTED", "{}", ""],
            )
        cp = Compounder(stdb_client)
        result = cp.detect_ripple_effects(source_id=node_map["CycA"], workspace_id=ws, max_hops=3)
        assert result["stats"]["kg_nodes_needing_review"] == 2
        assert result["stats"]["direct_count"] == 1  # B
        assert result["stats"]["transitive_count"] == 1  # C

    def test_ripple_path_present(self, stdb_client, ws):
        """Each affected node includes a ripple_path describing the edge traversed."""
        stdb_client.create_node(ws, "Src", "concept", summary="Source")
        stdb_client.create_node(ws, "Dst", "concept", summary="Dest")
        nodes = stdb_client._query("kg_node", workspace_id=ws, filter_dict={})
        node_map = {n["label"]: n["id"] for n in nodes if "label" in n}
        stdb_client._call(
            "create_edge", [ws, node_map["Src"], node_map["Dst"], "informs", 1.0, "EXTRACTED", "{}", ""],
        )
        cp = Compounder(stdb_client)
        result = cp.detect_ripple_effects(source_id=node_map["Src"], workspace_id=ws)
        assert len(result["directly_affected"]) == 1
        entry = result["directly_affected"][0]
        assert "ripple_path" in entry
        assert len(entry["ripple_path"]) >= 1
        step = entry["ripple_path"][0]
        assert "relation" in step
        assert "from" in step
        assert "to" in step

    def test_detect_transitive_ripple_path(self, stdb_client, ws):
        """Transitively-affected nodes have a multi-hop ripple_path."""
        stdb_client.create_node(ws, "P", "concept", summary="P")
        stdb_client.create_node(ws, "Q", "concept", summary="Q")
        stdb_client.create_node(ws, "R", "concept", summary="R")
        nodes = stdb_client._query("kg_node", workspace_id=ws, filter_dict={})
        node_map = {n["label"]: n["id"] for n in nodes if "label" in n}
        stdb_client._call("create_edge", [ws, node_map["P"], node_map["Q"], "next", 1.0, "EXTRACTED", "{}", ""])
        stdb_client._call("create_edge", [ws, node_map["Q"], node_map["R"], "next", 1.0, "EXTRACTED", "{}", ""])
        cp = Compounder(stdb_client)
        result = cp.detect_ripple_effects(source_id=node_map["P"], workspace_id=ws, max_hops=2)
        trans = {e["label"]: e for e in result["transitively_affected"]}
        assert "R" in trans
        rp = trans["R"].get("ripple_path", [])
        assert len(rp) >= 2, f"Expected >=2 hops for R, got {len(rp)}: {rp}"

    def test_detect_structured_result_keys(self, stdb_client, ws):
        """detect_ripple_effects returns the full structured result dict."""
        stdb_client.create_node(ws, "Structured", "concept", summary="Source")
        nodes = stdb_client._query("kg_node", workspace_id=ws, filter_dict={})
        cp = Compounder(stdb_client)
        result = cp.detect_ripple_effects(source_id=nodes[0]["id"], workspace_id=ws)
        assert "source" in result
        assert "directly_affected" in result
        assert "transitively_affected" in result
        assert "needs_review" in result
        assert "stats" in result
        stats = result["stats"]
        assert "total_entities" in stats
        assert "direct_count" in stats
        assert "transitive_count" in stats
        assert "kg_nodes_needing_review" in stats
        assert "max_hops_reached" in stats

    def test_apply_updates_dry_run(self, stdb_client, ws):
        """apply_ripple_updates with dry_run=True reports what it would update."""
        stdb_client.create_node(ws, "TargetNode", "concept", summary="Target")
        nodes = stdb_client._query("kg_node", workspace_id=ws, filter_dict={})
        node_map = {n["label"]: n["id"] for n in nodes if "label" in n}
        detection = {
            "needs_review": [
                {"id": node_map["TargetNode"], "label": "TargetNode", "reason": "direct_neighbour"},
            ],
        }
        cp = Compounder(stdb_client)
        result = cp.apply_ripple_updates(detection, dry_run=True, workspace_id=ws)
        assert result["stats"]["total"] == 1
        assert result["stats"]["updated_count"] == 1
        assert result["updated"][0]["label"] == "TargetNode"

    def test_apply_updates_empty_detection(self, cp, ws):
        """apply_ripple_updates with empty needs_review returns empty stats."""
        result = cp.apply_ripple_updates(detection_result={}, workspace_id=ws)
        assert result["stats"]["total"] == 0
        assert result["stats"]["updated_count"] == 0
        assert result["updated"] == []
        assert result["skipped"] == []
        assert result["errors"] == []

    def test_note_source_with_transitive_edges(self, stdb_client, ws):
        """Note-based source: direct nodes are found AND their neighbours via edges."""
        note = stdb_client.create_note(ws, "NoteSrc", "Note content", embed=False)
        note_id = note.get("id", "")
        if not note_id:
            notes = stdb_client._query("note", workspace_id=ws, filter_dict={"title": "NoteSrc"})
            note_id = notes[0]["id"] if notes else ""
        assert note_id
        stdb_client.create_node(ws, "DirectA", "concept", summary="Direct from note", source_memory_id=note_id)
        stdb_client.create_node(ws, "DirectB", "concept", summary="Also direct", source_memory_id=note_id)
        stdb_client.create_node(ws, "TransitiveC", "concept", summary="Transitive")
        nodes = stdb_client._query("kg_node", workspace_id=ws, filter_dict={})
        node_map = {n["label"]: n["id"] for n in nodes if "label" in n}
        stdb_client._call(
            "create_edge",
            [ws, node_map["DirectA"], node_map["TransitiveC"], "informs", 1.0, "EXTRACTED", "{}", ""],
        )
        cp = Compounder(stdb_client)
        result = cp.detect_ripple_effects(source_id=note_id, workspace_id=ws, max_hops=2)
        assert result["source"]["type"] == "note"
        assert result["stats"]["direct_count"] >= 2  # DirectA, DirectB
        assert result["stats"]["transitive_count"] >= 1  # TransitiveC
        trans_labels = {e["label"] for e in result["transitively_affected"]}
        assert "TransitiveC" in trans_labels

    # ------------------------------------------------------------------
    # mark_stale_for_source / clear_stale_flag / stale_only
    # (reconciled contract: mark_stale_for_source returns a dict with
    #  status + marked_count; clear_stale_flag returns bool)
    # ------------------------------------------------------------------

    def test_mark_stale_for_source_marks_nodes(self, stdb_client, ws):
        """mark_stale_for_source marks all nodes linked to a source as stale."""
        note = stdb_client.create_note(ws, "StaleSrcNote", "Content", embed=False)
        note_id = note.get("id", "")
        if not note_id:
            notes = stdb_client._query("note", workspace_id=ws, filter_dict={"title": "StaleSrcNote"})
            note_id = notes[0]["id"] if notes else ""
        assert note_id
        stdb_client.create_node(ws, "StaleLinkedNode", "concept", summary="Linked", source_memory_id=note_id)
        cp = Compounder(stdb_client)
        result = cp.mark_stale_for_source(workspace_id=ws, source_id=note_id)
        assert result["status"] == "ok"
        assert result["marked_count"] >= 1
        nodes = stdb_client._query("kg_node", workspace_id=ws, filter_dict={"label": "StaleLinkedNode"})
        assert nodes and nodes[0].get("stale_since", 0) > 0

    def test_mark_stale_for_source_empty_id(self, cp, ws):
        """mark_stale_for_source with empty source_id returns an error dict."""
        result = cp.mark_stale_for_source(workspace_id=ws, source_id="")
        assert result["status"] == "error"
        assert result["marked_count"] == 0

    def test_clear_stale_flag_returns_true(self, stdb_client, ws):
        """clear_stale_flag resets stale_since to 0 and returns True."""
        stdb_client.create_node(ws, "ClearStaleNode", "concept", summary="Test")
        nodes = stdb_client._query("kg_node", workspace_id=ws, filter_dict={"label": "ClearStaleNode"})
        node_id = nodes[0]["id"]
        stdb_client._call("set_node_stale", [node_id, True])
        cp = Compounder(stdb_client)
        assert cp.clear_stale_flag(node_id) is True
        nodes = stdb_client._query("kg_node", workspace_id=ws, filter_dict={"label": "ClearStaleNode"})
        assert nodes[0].get("stale_since", 0) == 0

    def test_clear_stale_flag_empty_id(self, cp, ws):
        """clear_stale_flag with empty node_id returns False."""
        assert cp.clear_stale_flag("") is False

    def test_detect_stale_only_filters_non_stale(self, stdb_client, ws):
        """detect_ripple_effects with stale_only=True skips nodes without stale_since."""
        stdb_client.create_node(ws, "StaleSrc", "concept", summary="Source")
        stdb_client.create_node(ws, "FreshNode", "concept", summary="Fresh")
        stdb_client.create_node(ws, "StaleOther", "concept", summary="Also stale")
        nodes = stdb_client._query("kg_node", workspace_id=ws, filter_dict={})
        node_map = {n["label"]: n["id"] for n in nodes if "label" in n}
        stdb_client._call("set_node_stale", [node_map["StaleOther"], True])
        stdb_client._call("create_edge", [ws, node_map["StaleSrc"], node_map["FreshNode"], "informs", 1.0, "EXTRACTED", "{}", ""])
        stdb_client._call("create_edge", [ws, node_map["StaleSrc"], node_map["StaleOther"], "informs", 1.0, "EXTRACTED", "{}", ""])
        cp = Compounder(stdb_client)
        result_all = cp.detect_ripple_effects(source_id=node_map["StaleSrc"], workspace_id=ws, max_hops=2, stale_only=False)
        assert result_all["stats"]["total_entities"] >= 2
        assert result_all["stats"]["stale_count"] >= 1
        result_stale = cp.detect_ripple_effects(source_id=node_map["StaleSrc"], workspace_id=ws, max_hops=2, stale_only=True)
        stale_labels = {e["label"] for e in result_stale["needs_review"]}
        assert "StaleOther" in stale_labels
        assert "FreshNode" not in stale_labels  # not stale

    def test_apply_updates_clear_stale_flag(self, stdb_client, ws):
        """apply_ripple_updates with clear_stale=True resets stale_since."""
        stdb_client.create_node(ws, "ApplyStaleNode", "concept", summary="Stale")
        nodes = stdb_client._query("kg_node", workspace_id=ws, filter_dict={"label": "ApplyStaleNode"})
        node_id = nodes[0]["id"]
        stdb_client._call("set_node_stale", [node_id, True])
        detection = {
            "needs_review": [
                {"id": node_id, "label": "ApplyStaleNode", "reason": "direct_neighbour"},
            ],
        }
        cp = Compounder(stdb_client)
        from unittest.mock import MagicMock
        cp._ripple_update_entity = MagicMock()
        result = cp.apply_ripple_updates(detection, clear_stale=True, workspace_id=ws)
        assert result["stats"]["updated_count"] == 1
        nodes = stdb_client._query("kg_node", workspace_id=ws, filter_dict={"label": "ApplyStaleNode"})
        assert nodes[0].get("stale_since", 0) == 0

