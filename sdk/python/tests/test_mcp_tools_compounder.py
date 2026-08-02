"""Tests for server/mcp/tools/compounder.py — Compounder tools (LLM Wiki workflow)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _patch_get_client():
    """Patch get_client at the module level where compounder.py imports it.

    Compounder-based tools also call get_client() to pass to Compounder();
    this ensures the call returns a mock even when the Compounder class
    itself is separately mocked.
    """
    with patch("server.mcp.tools.compounder.get_client") as mock_fn:
        instance = MagicMock()
        mock_fn.return_value = instance
        yield instance


# ---------------------------------------------------------------------------
# ingest_source
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIngestSource:
    """Tests for the ingest_source MCP tool."""

    def test_ingests(self, _patch_get_client: MagicMock, mock_compounder: MagicMock):
        from server.mcp.tools.compounder import ingest_source

        mock_compounder.ingest_source.return_value = {
            "entities": [{"name": "AI"}, {"name": "ML"}],
            "links": [{"source": "n1", "target": "n2"}],
            "contradictions": [],
        }
        result = ingest_source(
            source_text="Text about AI",
            source_title="AI Overview",
            workspace_id="ws1",
            source_type="article",
        )
        assert "AI Overview" in result
        assert "Entities: 2" in result
        assert "Links: 1" in result
        assert "Contradictions: 0" in result
        mock_compounder.ingest_source.assert_called_once_with(
            source_text="Text about AI",
            source_title="AI Overview",
            workspace_id="ws1",
            source_type="article",
        )

    def test_default_workspace(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import ingest_source

        mock_compounder.ingest_source.return_value = {
            "entities": [],
            "links": [],
            "contradictions": [],
        }
        ingest_source(source_text="test", source_title="test")
        mock_compounder.ingest_source.assert_called_once_with(
            source_text="test",
            source_title="test",
            workspace_id="default",
            source_type="article",
        )


# ---------------------------------------------------------------------------
# create_entity_page
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateEntityPage:
    """Tests for the create_entity_page MCP tool."""

    def test_creates(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import create_entity_page

        mock_compounder.create_entity_page.return_value = {
            "note": {"id": "note_abc1234567890xyz"},
        }
        result = create_entity_page(
            name="Albert Einstein",
            description="A great physicist",
            entity_type="person",
            workspace_id="ws1",
        )
        assert "Albert Einstein" in result
        assert "note_abc12345678" in result
        mock_compounder.create_entity_page.assert_called_once_with(
            name="Albert Einstein",
            description="A great physicist",
            entity_type="person",
            workspace_id="ws1",
        )

    def test_defaults(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import create_entity_page

        mock_compounder.create_entity_page.return_value = {"note": {"id": "n1"}}
        create_entity_page(name="ConceptX", description="A concept")
        mock_compounder.create_entity_page.assert_called_once_with(
            name="ConceptX",
            description="A concept",
            entity_type="concept",
            workspace_id="default",
        )


# ---------------------------------------------------------------------------
# update_entity_page
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateEntityPage:
    """Tests for the update_entity_page MCP tool."""

    def test_updates(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import update_entity_page

        mock_compounder.update_entity_page.return_value = {"status": "updated"}
        result = update_entity_page(
            name="AI",
            description="Artificial Intelligence",
            entity_type="concept",
            workspace_id="ws1",
        )
        assert "updated" in result
        mock_compounder.update_entity_page.assert_called_once_with(
            name="AI",
            description="Artificial Intelligence",
            entity_type="concept",
            workspace_id="ws1",
        )

    def test_not_found(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import update_entity_page

        mock_compounder.update_entity_page.return_value = {}
        result = update_entity_page(name="Nonexistent")
        assert "not found" in result

    def test_partial_update(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import update_entity_page

        mock_compounder.update_entity_page.return_value = {"status": "updated"}
        update_entity_page(name="AI", description="New desc")
        mock_compounder.update_entity_page.assert_called_once_with(
            name="AI",
            description="New desc",
            entity_type=None,
            workspace_id="default",
        )


# ---------------------------------------------------------------------------
# create_concept_page
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateConceptPage:
    """Tests for the create_concept_page MCP tool."""

    def test_creates(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import create_concept_page

        mock_compounder.create_concept_page.return_value = {
            "note": {"id": "note_concept12345"},
        }
        result = create_concept_page(
            concept="Reinforcement Learning",
            definition="A type of ML where agents learn from rewards.",
            workspace_id="ws1",
            related_concepts="Supervised Learning, Unsupervised Learning",
        )
        assert "Reinforcement Learning" in result
        mock_compounder.create_concept_page.assert_called_once_with(
            concept="Reinforcement Learning",
            definition="A type of ML where agents learn from rewards.",
            workspace_id="ws1",
            related_concepts=["Supervised Learning", "Unsupervised Learning"],
        )

    def test_empty_related(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import create_concept_page

        mock_compounder.create_concept_page.return_value = {"note": {"id": "n1"}}
        create_concept_page(concept="ML", definition="Machine Learning")
        mock_compounder.create_concept_page.assert_called_once_with(
            concept="ML",
            definition="Machine Learning",
            workspace_id="default",
            related_concepts=None,
        )


# ---------------------------------------------------------------------------
# create_comparison_page
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateComparisonPage:
    """Tests for the create_comparison_page MCP tool."""

    def test_creates(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import create_comparison_page

        mock_compounder.create_comparison_page.return_value = {
            "note": {"id": "note_cmp_12345"},
        }
        result = create_comparison_page(
            title="LangGraph vs CrewAI",
            items="LangGraph, CrewAI, AutoGen",
            workspace_id="ws1",
            criteria="features, performance",
        )
        assert "LangGraph vs CrewAI" in result
        assert "3 items" in result
        mock_compounder.create_comparison_page.assert_called_once_with(
            title="LangGraph vs CrewAI",
            items=["LangGraph", "CrewAI", "AutoGen"],
            workspace_id="ws1",
            criteria=["features", "performance"],
        )

    def test_default_criteria(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import create_comparison_page

        mock_compounder.create_comparison_page.return_value = {"note": {"id": "n1"}}
        create_comparison_page(title="A vs B", items="A, B")
        mock_compounder.create_comparison_page.assert_called_once_with(
            title="A vs B",
            items=["A", "B"],
            workspace_id="default",
            criteria=["features", "performance", "ecosystem"],
        )


# ---------------------------------------------------------------------------
# lint_workspace
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLintWorkspace:
    """Tests for the lint_workspace MCP tool."""

    def test_lints(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import lint_workspace

        mock_compounder.lint_workspace.return_value = {
            "summary": {
                "orphan_count": 2,
                "missing_crossref_count": 1,
                "note_orphan_count": 0,
                "contradiction_count": 0,
                "total_issues": 3,
            }
        }
        result = lint_workspace(workspace_id="ws1", check_contradictions=True)
        assert "Orphans: 2" in result
        assert "Missing crossrefs: 1" in result
        assert "Total issues: 3" in result
        mock_compounder.lint_workspace.assert_called_once_with(
            workspace_id="ws1",
            check_contradictions=True,
        )

    def test_defaults(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import lint_workspace

        mock_compounder.lint_workspace.return_value = {"summary": {}}
        lint_workspace()
        mock_compounder.lint_workspace.assert_called_once_with(
            workspace_id="default",
            check_contradictions=False,
        )


# ---------------------------------------------------------------------------
# generate_overview
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateOverview:
    """Tests for the generate_overview MCP tool."""

    def test_generates(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import generate_overview

        mock_compounder.generate_overview_page.return_value = {
            "note": {"id": "note_overview_1234567890abc"}
        }
        result = generate_overview(workspace_id="ws1")
        assert "Overview generated" in result
        mock_compounder.generate_overview_page.assert_called_once_with(
            workspace_id="ws1"
        )

    def test_empty_workspace(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import generate_overview

        mock_compounder.generate_overview_page.return_value = {"note": {}}
        result = generate_overview(workspace_id="empty")
        assert "Nothing to generate" in result


# ---------------------------------------------------------------------------
# search_entities
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchEntities:
    """Tests for the search_entities MCP tool."""

    def test_finds_entities(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import search_entities

        mock_compounder.search_entities.return_value = [
            {"id": "ent1", "label": "AI", "node_type": "concept", "summary": "Artificial Intelligence"},
            {"id": "ent2", "label": "ML", "node_type": "concept", "summary": "Machine Learning"},
        ]
        result = search_entities(
            workspace_id="ws1",
            label="AI",
            node_type="concept",
            semantic_query="intelligence",
            limit=10,
        )
        assert "Found 2 entities" in result
        assert "AI" in result
        assert "ML" in result
        mock_compounder.search_entities.assert_called_once_with(
            workspace_id="ws1",
            label="AI",
            node_type="concept",
            semantic_query="intelligence",
            limit=10,
        )

    def test_no_results(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import search_entities

        mock_compounder.search_entities.return_value = []
        result = search_entities(workspace_id="ws1")
        assert "No entities found" in result

    def test_defaults(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import search_entities

        mock_compounder.search_entities.return_value = []
        search_entities()
        mock_compounder.search_entities.assert_called_once_with(
            workspace_id="default",
            label=None,
            node_type=None,
            semantic_query=None,
            limit=20,
        )


# ---------------------------------------------------------------------------
# find_near_duplicates
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFindNearDuplicates:
    """Tests for the find_near_duplicates MCP tool."""

    def test_finds_dupes(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import find_near_duplicates

        mock_compounder.find_near_duplicates.return_value = [
            {"entity_id": "ent1", "entity_type": "memory", "score": 0.95, "content": "Some similar content"},
        ]
        result = find_near_duplicates(
            content="Some content",
            workspace_id="ws1",
            threshold=0.9,
            limit=3,
        )
        assert "Found 1" in result
        assert "ent1" in result
        assert "0.9500" in result
        mock_compounder.find_near_duplicates.assert_called_once_with(
            content="Some content",
            workspace_id="ws1",
            threshold=0.9,
            limit=3,
        )

    def test_no_results(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import find_near_duplicates

        mock_compounder.find_near_duplicates.return_value = []
        result = find_near_duplicates(content="Unique text")
        assert "No near-duplicates found" in result


# ---------------------------------------------------------------------------
# cross_link
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCrossLink:
    """Tests for the cross_link MCP tool."""

    def test_cross_links(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import cross_link

        mock_compounder.cross_link.return_value = {
            "links_created": 5,
            "pairs_checked": 100,
        }
        result = cross_link(workspace_id="ws1")
        assert "Links created: 5" in result
        assert "Pairs checked: 100" in result
        mock_compounder.cross_link.assert_called_once_with(workspace_id="ws1")

    def test_default(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import cross_link

        mock_compounder.cross_link.return_value = {
            "links_created": 0, "pairs_checked": 0
        }
        cross_link()
        mock_compounder.cross_link.assert_called_once_with(workspace_id="default")


# ---------------------------------------------------------------------------
# suggest_connections
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuggestConnections:
    """Tests for the suggest_connections MCP tool."""

    def test_suggests(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import suggest_connections

        mock_compounder.suggest_connections.return_value = [
            {"source_label": "Node A", "target_label": "Node B", "common_count": 3},
            {"source_label": "Node C", "target_label": "Node D", "common_count": 1},
        ]
        result = suggest_connections(workspace_id="ws1")
        assert "2 connection suggestion" in result
        assert "Node A" in result
        assert "Node B" in result
        mock_compounder.suggest_connections.assert_called_once_with(
            workspace_id="ws1"
        )

    def test_no_suggestions(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import suggest_connections

        mock_compounder.suggest_connections.return_value = []
        result = suggest_connections(workspace_id="ws1")
        assert "No connection suggestions" in result


# ---------------------------------------------------------------------------
# store_answer
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStoreAnswer:
    """Tests for the store_answer MCP tool."""

    def test_stores(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import store_answer

        mock_compounder.store_answer.return_value = {
            "note": {"id": "note_ans_12345"},
            "entities": [{"name": "RLHF"}, {"name": "PPO"}],
        }
        result = store_answer(
            query="What is RLHF?",
            answer="RLHF is reinforcement learning from human feedback.",
            workspace_id="ws1",
            source_memory_ids="mem1, mem2",
        )
        assert "Answer stored" in result
        assert "Entities extracted: 2" in result
        mock_compounder.store_answer.assert_called_once_with(
            query="What is RLHF?",
            answer="RLHF is reinforcement learning from human feedback.",
            workspace_id="ws1",
            source_memory_ids=["mem1", "mem2"],
        )

    def test_empty_source_ids(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import store_answer

        mock_compounder.store_answer.return_value = {
            "note": {"id": "n1"}, "entities": []
        }
        store_answer(query="Q", answer="A")
        mock_compounder.store_answer.assert_called_once_with(
            query="Q", answer="A", workspace_id="default", source_memory_ids=None
        )


# ---------------------------------------------------------------------------
# store_answers_batch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStoreAnswersBatch:
    """Tests for the store_answers_batch MCP tool."""

    def test_stores_batch(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import store_answers_batch

        mock_compounder.store_answers.return_value = [
            {"entities": [{"name": "E1"}, {"name": "E2"}]},
            {"entities": [{"name": "E3"}]},
        ]
        qa_json = json.dumps([
            ["What is RLHF?", "RLHF is..."],
            ["What is PPO?", "PPO is..."],
        ])
        result = store_answers_batch(
            qa_pairs_json=qa_json,
            workspace_id="ws1",
            source_memory_ids="mem1",
        )
        assert "Batch stored 2 answers" in result
        assert "Total entities extracted: 3" in result
        mock_compounder.store_answers.assert_called_once_with(
            qa_pairs=[
                ["What is RLHF?", "RLHF is..."],
                ["What is PPO?", "PPO is..."],
            ],
            workspace_id="ws1",
            source_memory_ids=["mem1"],
        )

    def test_invalid_json(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import store_answers_batch

        result = store_answers_batch(qa_pairs_json="not json")
        assert "Error" in result

    def test_wrong_structure(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import store_answers_batch

        result = store_answers_batch(qa_pairs_json='"just a string"')
        assert "Error" in result

    def test_no_source_ids(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import store_answers_batch

        mock_compounder.store_answers.return_value = [{"entities": []}]
        qa_json = json.dumps([["Q1", "A1"]])
        store_answers_batch(qa_pairs_json=qa_json)
        mock_compounder.store_answers.assert_called_once_with(
            qa_pairs=[["Q1", "A1"]],
            workspace_id="default",
            source_memory_ids=None,
        )


# ---------------------------------------------------------------------------
# export_workspace
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExportWorkspace:
    """Tests for the export_workspace MCP tool."""

    def test_exports(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import export_workspace

        mock_compounder.export_workspace.return_value = {
            "files_written": 10,
            "output_dir": "/tmp/export",
            "errors": [],
        }
        result = export_workspace(
            output_dir="/tmp/export",
            workspace_id="ws1",
            include_kg=True,
            include_system_notes=False,
        )
        assert "Exported 10 file(s)" in result
        assert "/tmp/export" in result
        mock_compounder.export_workspace.assert_called_once_with(
            output_dir="/tmp/export",
            workspace_id="ws1",
            include_kg=True,
            include_system_notes=False,
        )

    def test_with_errors(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import export_workspace

        mock_compounder.export_workspace.return_value = {
            "files_written": 8,
            "output_dir": "/tmp/export",
            "errors": ["Could not write note_5"],
        }
        result = export_workspace(output_dir="/tmp/export")
        assert "Errors: 1" in result
        assert "Could not write note_5" in result

    def test_defaults(
        self, _patch_get_client: MagicMock, mock_compounder: MagicMock
    ):
        from server.mcp.tools.compounder import export_workspace

        mock_compounder.export_workspace.return_value = {
            "files_written": 0,
            "output_dir": "/tmp/out",
            "errors": [],
        }
        export_workspace(output_dir="/tmp/out")
        mock_compounder.export_workspace.assert_called_once_with(
            output_dir="/tmp/out",
            workspace_id="default",
            include_kg=False,
            include_system_notes=False,
        )


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBackup:
    """Tests for the backup MCP tool."""

    def test_backs_up(self, _patch_get_client: MagicMock):
        from server.mcp.tools.compounder import backup

        _patch_get_client.backup.return_value = {
            "path": "/tmp/backup.json",
            "table_count": 12,
            "total_rows": 500,
        }
        result = backup(workspace_id="ws1", output_path="/tmp/backup.json")
        assert "Backup written" in result
        assert "Tables: 12" in result
        assert "Total rows: 500" in result
        _patch_get_client.backup.assert_called_once_with(
            output_path="/tmp/backup.json"
        )

    def test_auto_path(self, _patch_get_client: MagicMock):
        from server.mcp.tools.compounder import backup

        _patch_get_client.backup.return_value = {
            "path": "spacetime-memory-backup-2024-01-01.json",
            "table_count": 5,
            "total_rows": 100,
        }
        result = backup()
        assert "Backup written" in result
        _patch_get_client.backup.assert_called_once_with(output_path=None)


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRestore:
    """Tests for the restore MCP tool."""

    def test_restores(self, _patch_get_client: MagicMock):
        from server.mcp.tools.compounder import restore

        _patch_get_client.restore.return_value = {
            "restored": ["memory", "note", "kg_node"],
            "total_rows": 250,
        }
        result = restore(input_path="/tmp/backup.json")
        assert "3 table(s)" in result
        assert "250 row(s)" in result
        _patch_get_client.restore.assert_called_once_with("/tmp/backup.json")

    def test_no_restored_rows(self, _patch_get_client: MagicMock):
        from server.mcp.tools.compounder import restore

        _patch_get_client.restore.return_value = {
            "restored": [],
            "total_rows": 0,
        }
        result = restore(input_path="/tmp/empty.json")
        assert "0 row(s)" in result
