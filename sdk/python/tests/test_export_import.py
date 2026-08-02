"""Tests for ExportImportMixin — export_memories, import_memories, export_workspace_bundle, import_workspace.

Unit tests use ``patch.object`` to mock ``_query`` and ``_call`` directly
(no SpacetimeDB required), following the pattern from ``test_client_kg.py``.
"""
from __future__ import annotations

import csv
import io
import json
from unittest.mock import patch

import pytest

# ============================================================================
# Helpers — sample data rows
# ============================================================================

def _memory_row(
    mid: str = "mem-1",
    workspace_id: str = "ws1",
    content: str = "The quick brown fox jumps over the lazy dog.",
    memory_type: str = "experience",
    confidence: float = 0.9,
    summary: str = "Fox and dog story",
    peer_id: str = "peer-1",
    created_at: int = 1000000000,
):
    return {
        "id": mid,
        "workspace_id": workspace_id,
        "peer_id": peer_id,
        "observer_id": "",
        "memory_type": memory_type,
        "content": content,
        "summary": summary,
        "entities_json": "[]",
        "confidence": confidence,
        "tier": "L1",
        "source_session_id": "",
        "source_message_id": "",
        "images_json": "",
        "created_at": created_at,
        "updated_at": created_at,
    }


def _kg_node_row(
    nid: str = "node-1",
    workspace_id: str = "ws1",
    label: str = "Fox",
    node_type: str = "entity",
    summary: str = "Quick brown fox",
):
    return {
        "id": nid,
        "workspace_id": workspace_id,
        "label": label,
        "node_type": node_type,
        "summary": summary,
        "metadata_json": "{}",
        "created_at": 1000000000,
    }


def _kg_edge_row(
    eid: str = "edge-1",
    workspace_id: str = "ws1",
    source_node_id: str = "node-1",
    target_node_id: str = "node-2",
    relation: str = "related_to",
    weight: float = 1.0,
):
    return {
        "id": eid,
        "workspace_id": workspace_id,
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "relation": relation,
        "weight": weight,
        "confidence": "EXTRACTED",
        "metadata_json": "{}",
        "created_at": 1000000000,
    }


def _note_row(
    nid: str = "note-1",
    workspace_id: str = "ws1",
    title: str = "Test Note",
    content: str = "This is a note.",
    embed: bool = True,
):
    return {
        "id": nid,
        "workspace_id": workspace_id,
        "title": title,
        "content": content,
        "embed": embed,
        "tags_json": "[]",
        "created_at": 1000000000,
        "updated_at": 1000000000,
    }


def _profile_row(
    peer_id: str = "peer-1",
    static_facts: str = '["fact1"]',
    dynamic_context: str = '["ctx1"]',
    preferences: str = '{"theme":"dark"}',
    tags: str = '["tag1"]',
):
    return {
        "peer_id": peer_id,
        "static_facts_json": static_facts,
        "dynamic_context_json": dynamic_context,
        "preferences_json": preferences,
        "tags_json": tags,
    }


# ============================================================================
# Export Memories
# ============================================================================

class TestExportMemories:
    """export_memories — JSON, CSV, markdown formats."""

    def test_export_memories_json(self, mock_http_client):
        """Export memories as JSON returns a JSON array string."""
        memories = [
            _memory_row(mid="mem-1", content="First memory"),
            _memory_row(mid="mem-2", content="Second memory"),
        ]
        with patch.object(mock_http_client, "_query", return_value=memories):
            result = mock_http_client.export_memories(workspace_id="ws1", fmt="json")

        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["id"] == "mem-1"
        assert parsed[0]["content"] == "First memory"
        assert parsed[1]["id"] == "mem-2"
        assert parsed[1]["content"] == "Second memory"

    def test_export_memories_csv(self, mock_http_client):
        """Export memories as CSV returns valid CSV text."""
        memories = [
            _memory_row(mid="mem-1", content="CSV memory 1"),
            _memory_row(mid="mem-2", content="CSV memory 2"),
        ]
        with patch.object(mock_http_client, "_query", return_value=memories):
            result = mock_http_client.export_memories(workspace_id="ws1", fmt="csv")

        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["content"] == "CSV memory 1"
        assert rows[0]["id"] == "mem-1"
        assert rows[1]["content"] == "CSV memory 2"

    def test_export_memories_markdown(self, mock_http_client):
        """Export memories as markdown returns formatted markdown."""
        memories = [
            _memory_row(mid="mem-1", content="Markdown memory", memory_type="experience"),
        ]
        with patch.object(mock_http_client, "_query", return_value=memories):
            result = mock_http_client.export_memories(workspace_id="ws1", fmt="markdown")

        assert "Markdown memory" in result
        assert "**Type:** experience" in result
        assert "**ID:** mem-1" in result

    def test_export_memories_with_filters(self, mock_http_client):
        """Export memories with client-side filters."""
        memories = [
            _memory_row(mid="mem-1", content="Experience 1", memory_type="experience"),
            _memory_row(mid="mem-2", content="Observation 1", memory_type="observation"),
        ]
        with patch.object(mock_http_client, "_query", return_value=memories):
            result = mock_http_client.export_memories(
                workspace_id="ws1", fmt="json",
                filters={"memory_type": "observation"},
            )

        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["memory_type"] == "observation"

    def test_export_memories_unknown_format(self, mock_http_client):
        """Unknown format raises ValueError."""
        with patch.object(mock_http_client, "_query", return_value=[]):
            with pytest.raises(ValueError, match="Unknown export format"):
                mock_http_client.export_memories(workspace_id="ws1", fmt="xml")


# ============================================================================
# Import Memories
# ============================================================================

class TestImportMemories:
    """import_memories — strategy handling and format parsing."""

    def test_import_memories_json_merge(self, mock_http_client):
        """Import JSON memories with merge strategy imports all when no existing."""
        data = json.dumps([
            {"content": "New memory one", "memory_type": "experience"},
            {"content": "New memory two", "memory_type": "observation"},
        ])

        def _call_side(reducer, args):
            assert reducer == "store_memory"
            return {"status": "ok"}

        with patch.object(mock_http_client, "_query", return_value=[]), \
             patch.object(mock_http_client, "_call", side_effect=_call_side):
            result = mock_http_client.import_memories(
                workspace_id="ws1", data=data, fmt="json", strategy="merge",
            )

        assert result["imported"] == 2
        assert result["skipped"] == 0
        assert result["errors"] == []

    def test_import_memories_json_skip_duplicates(self, mock_http_client):
        """Import with skip strategy skips existing content."""
        data = json.dumps([
            {"content": "Existing memory"},
            {"content": "Brand new memory"},
        ])

        call_count = [0]

        def _call_side(reducer, args):
            call_count[0] += 1
            assert reducer == "store_memory"
            return {"status": "ok"}

        with patch.object(
            mock_http_client, "_query",
            return_value=[_memory_row(mid="mem-1", content="Existing memory")],
        ), patch.object(mock_http_client, "_call", side_effect=_call_side):
            result = mock_http_client.import_memories(
                workspace_id="ws1", data=data, fmt="json", strategy="skip",
            )

        assert result["imported"] == 1
        assert result["skipped"] == 1
        assert result["errors"] == []

    def test_import_memories_json_replace(self, mock_http_client):
        """Import with replace strategy overwrites existing content."""
        data = json.dumps([
            {"content": "Replace me"},
        ])

        calls = []

        def _call_side(reducer, args):
            calls.append((reducer, args))
            return {"status": "ok"}

        with patch.object(
            mock_http_client, "_query",
            return_value=[_memory_row(mid="mem-1", content="Replace me")],
        ), patch.object(mock_http_client, "_call", side_effect=_call_side):
            result = mock_http_client.import_memories(
                workspace_id="ws1", data=data, fmt="json", strategy="replace",
            )

        assert result["imported"] == 1
        assert result["skipped"] == 0
        # Verify delete was called before store
        reducers = [c[0] for c in calls]
        assert "delete_memory" in reducers
        assert "store_memory" in reducers

    def test_import_memories_invalid_strategy(self, mock_http_client):
        """Unknown strategy raises ValueError."""
        with pytest.raises(ValueError, match="Unknown strategy"):
            mock_http_client.import_memories(
                workspace_id="ws1", data="[]", strategy="invalid",
            )

    def test_import_memories_missing_content(self, mock_http_client):
        """Entry without content field raises ValueError."""
        data = json.dumps([{"summary": "No content here"}])

        with pytest.raises(ValueError, match="missing required field 'content'"):
            mock_http_client.import_memories(
                workspace_id="ws1", data=data, fmt="json",
            )


# ============================================================================
# Export Workspace Bundle
# ============================================================================

class TestExportWorkspaceBundle:
    """export_workspace_bundle — full workspace bundle."""

    def test_export_workspace_all_domains(self, mock_http_client):
        """Export all domains returns a complete JSON bundle."""
        memories = [_memory_row(mid="mem-1", content="Bundle memory")]
        nodes = [_kg_node_row(nid="node-1", label="Entity1")]
        edges = [_kg_edge_row(eid="edge-1")]
        notes = [_note_row(nid="note-1", title="Bundle Note")]
        profiles = [_profile_row(peer_id="peer-1")]

        def _query_side(table, **kw):
            if table == "memory":
                return memories
            if table == "kg_node":
                return nodes
            if table == "kg_edge":
                return edges
            if table == "note":
                return notes
            if table == "profile":
                return profiles
            return []

        with patch.object(mock_http_client, "_query", side_effect=_query_side):
            result = mock_http_client.export_workspace_bundle(
                workspace_id="ws1",
                include=["memories", "kg", "notes", "profiles"],
            )

        bundle = json.loads(result)
        assert bundle["_workspace_id"] == "ws1"
        assert bundle["_version"] == "1.0"
        assert "_exported_at" in bundle
        assert len(bundle["memories"]) == 1
        assert bundle["memories"][0]["content"] == "Bundle memory"
        assert len(bundle["kg_nodes"]) == 1
        assert bundle["kg_nodes"][0]["label"] == "Entity1"
        assert len(bundle["kg_edges"]) == 1
        assert len(bundle["notes"]) == 1
        assert bundle["notes"][0]["title"] == "Bundle Note"
        assert len(bundle["profiles"]) == 1
        assert bundle["profiles"][0]["peer_id"] == "peer-1"

    def test_export_workspace_partial(self, mock_http_client):
        """Export only selected domains."""
        def _query_side(table, **kw):
            return []

        with patch.object(mock_http_client, "_query", side_effect=_query_side):
            result = mock_http_client.export_workspace_bundle(
                workspace_id="ws1",
                include=["memories", "notes"],
            )

        bundle = json.loads(result)
        assert "memories" in bundle
        assert "notes" in bundle
        assert "kg_nodes" not in bundle
        assert "kg_edges" not in bundle
        assert "profiles" not in bundle

    def test_export_workspace_unknown_domain(self, mock_http_client):
        """Unknown domain in include list raises ValueError."""
        with pytest.raises(ValueError, match="Unknown domain"):
            mock_http_client.export_workspace_bundle(
                workspace_id="ws1",
                include=["memories", "widgets"],
            )


# ============================================================================
# Import Workspace
# ============================================================================

class TestImportWorkspace:
    """import_workspace — full workspace bundle import."""

    def test_import_workspace_all_domains(self, mock_http_client):
        """Import a full workspace bundle imports all domains."""
        bundle = {
            "_version": "1.0",
            "_workspace_id": "ws1",
            "_exported_at": "2026-07-27T00:00:00+00:00",
            "memories": [
                {"content": "Imported memory 1", "memory_type": "experience"},
                {"content": "Imported memory 2", "memory_type": "observation"},
            ],
            "kg_nodes": [
                {"label": "Imported Node", "node_type": "entity", "summary": "Test"},
            ],
            "kg_edges": [
                {
                    "source_node_id": "node-1",
                    "target_node_id": "node-2",
                    "relation": "informed_by",
                },
            ],
            "notes": [
                {"title": "Imported Note", "content": "Note content", "embed": True},
            ],
            "profiles": [
                {"peer_id": "imported-peer", "static_facts_json": '["f1"]'},
            ],
        }

        data = json.dumps(bundle)

        def _call_side(reducer, args):
            return {"status": "ok"}

        with patch.object(mock_http_client, "_query", return_value=[]), \
             patch.object(mock_http_client, "_call", side_effect=_call_side):
            result = mock_http_client.import_workspace(
                workspace_id="ws2", data=data, strategy="merge",
            )

        assert result["memories"]["imported"] == 2
        assert result["kg_nodes"]["imported"] == 1
        assert result["kg_edges"]["imported"] == 1
        assert result["notes"]["imported"] == 1
        assert result["profiles"]["imported"] == 1
        assert result["errors"] == []

    def test_import_workspace_empty(self, mock_http_client):
        """Importing an empty bundle succeeds (no-op)."""
        bundle = {
            "_version": "1.0",
            "_workspace_id": "ws1",
            "_exported_at": "2026-07-27T00:00:00+00:00",
        }

        result = mock_http_client.import_workspace(
            workspace_id="ws2", data=json.dumps(bundle), strategy="merge",
        )

        assert result["memories"]["imported"] == 0
        assert result["errors"] == []
