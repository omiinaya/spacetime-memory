"""Tests for cli.stmem.commands.wiki_pages.

Covers entity-page, update-entity-page, concept-page, comparison-page,
and search-entities commands.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from cli.stmem import cli
from click.testing import CliRunner


@pytest.mark.unit
class TestEntityPage:
    """entity-page command."""

    def test_entity_page_success(self, mocked_cli_runner):
        """entity-page creates page and shows success message."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.compounder.Compounder") as MockCp:
            inst = MagicMock()
            inst.create_entity_page.return_value = {
                "note": {"id": "note-xyz"},
                "node": {"id": "node-abc"},
            }
            MockCp.return_value = inst
            result = runner.invoke(
                cli, ["entity-page", "-n", "Alice", "-d", "A researcher"]
            )
        assert result.exit_code == 0
        assert "Entity page created" in result.output
        assert "Alice" in result.output

    def test_entity_page_with_type(self, mocked_cli_runner):
        """entity-page passes --type to Compounder."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.compounder.Compounder") as MockCp:
            inst = MagicMock()
            inst.create_entity_page.return_value = {
                "note": {"id": "n1"}, "node": {"id": "nd1"},
            }
            MockCp.return_value = inst
            result = runner.invoke(
                cli, ["entity-page", "-n", "Bob", "-d", "A person", "-t", "person"]
            )
        assert result.exit_code == 0
        inst.create_entity_page.assert_called_once()
        assert inst.create_entity_page.call_args[1]["entity_type"] == "person"

    def test_entity_page_with_related(self, mocked_cli_runner):
        """entity-page passes --related as relations list."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.compounder.Compounder") as MockCp:
            inst = MagicMock()
            inst.create_entity_page.return_value = {
                "note": {"id": "n1"}, "node": {"id": "nd1"},
            }
            MockCp.return_value = inst
            result = runner.invoke(
                cli,
                ["entity-page", "-n", "X", "-d", "Desc", "--related", "A,B"],
            )
        assert result.exit_code == 0
        inst.create_entity_page.assert_called_once()
        assert inst.create_entity_page.call_args[1]["relations"] == [
            {"name": "A", "relation": "related_to"},
            {"name": "B", "relation": "related_to"},
        ]

    def test_entity_page_failure(self, mocked_cli_runner):
        """entity-page shows failure when note has no id."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.compounder.Compounder") as MockCp:
            inst = MagicMock()
            inst.create_entity_page.return_value = {"note": {}, "node": {}}
            MockCp.return_value = inst
            result = runner.invoke(
                cli, ["entity-page", "-n", "X", "-d", "Desc"]
            )
        assert result.exit_code == 0
        assert "Failed to create entity page" in result.output

    def test_entity_page_missing_name(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["entity-page", "-d", "Desc"])
        assert result.exit_code != 0


@pytest.mark.unit
class TestUpdateEntityPage:
    """update-entity-page command."""

    def test_update_entity_page_success(self, mocked_cli_runner):
        """update-entity-page updates and shows success."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.compounder.Compounder") as MockCp:
            inst = MagicMock()
            inst.update_entity_page.return_value = {
                "note": {"id": "note-xyz"},
                "node": {"id": "node-abc"},
            }
            MockCp.return_value = inst
            result = runner.invoke(
                cli, ["update-entity-page", "-n", "Alice"]
            )
        assert result.exit_code == 0
        assert "Entity page updated" in result.output

    def test_update_entity_page_not_found(self, mocked_cli_runner):
        """update-entity-page shows not-found when note empty."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.compounder.Compounder") as MockCp:
            inst = MagicMock()
            inst.update_entity_page.return_value = {"note": {}, "node": {}}
            MockCp.return_value = inst
            result = runner.invoke(
                cli, ["update-entity-page", "-n", "Nonexistent"]
            )
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_update_entity_page_with_fields(self, mocked_cli_runner):
        """update-entity-page passes description and type."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.compounder.Compounder") as MockCp:
            inst = MagicMock()
            inst.update_entity_page.return_value = {
                "note": {"id": "n1"}, "node": {"id": "nd1"},
            }
            MockCp.return_value = inst
            result = runner.invoke(
                cli,
                [
                    "update-entity-page",
                    "-n", "Alice",
                    "-d", "New desc",
                    "-t", "person",
                ],
            )
        assert result.exit_code == 0
        inst.update_entity_page.assert_called_once_with(
            name="Alice",
            description="New desc",
            entity_type="person",
            workspace_id="default",
        )


@pytest.mark.unit
class TestConceptPage:
    """concept-page command."""

    def test_concept_page_success(self, mocked_cli_runner):
        """concept-page creates page and shows success."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.compounder.Compounder") as MockCp:
            inst = MagicMock()
            inst.create_concept_page.return_value = {"note": {"id": "n1"}}
            MockCp.return_value = inst
            result = runner.invoke(
                cli,
                [
                    "concept-page",
                    "-c", "RLHF",
                    "-d", "Reinforcement Learning from Human Feedback",
                ],
            )
        assert result.exit_code == 0
        assert "Concept page created" in result.output

    def test_concept_page_with_related(self, mocked_cli_runner):
        """concept-page passes --related as related_concepts."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.compounder.Compounder") as MockCp:
            inst = MagicMock()
            inst.create_concept_page.return_value = {"note": {"id": "n1"}}
            MockCp.return_value = inst
            result = runner.invoke(
                cli,
                ["concept-page", "-c", "AI", "-d", "AI desc", "--related", "ML,DL"],
            )
        assert result.exit_code == 0
        assert "Related" in result.output
        inst.create_concept_page.assert_called_once_with(
            concept="AI",
            definition="AI desc",
            workspace_id="default",
            related_concepts=["ML", "DL"],
        )

    def test_concept_page_failure(self, mocked_cli_runner):
        """concept-page shows failure when note has no id."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.compounder.Compounder") as MockCp:
            inst = MagicMock()
            inst.create_concept_page.return_value = {"note": {}}
            MockCp.return_value = inst
            result = runner.invoke(
                cli, ["concept-page", "-c", "X", "-d", "Y"]
            )
        assert result.exit_code == 0
        assert "Failed to create" in result.output


@pytest.mark.unit
class TestComparisonPage:
    """comparison-page command."""

    def test_comparison_page_success(self, mocked_cli_runner):
        """comparison-page creates page and shows success."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.compounder.Compounder") as MockCp:
            inst = MagicMock()
            inst.create_comparison_page.return_value = {"note": {"id": "n1"}}
            MockCp.return_value = inst
            result = runner.invoke(
                cli, ["comparison-page", "-t", "A vs B", "-i", "A,B"]
            )
        assert result.exit_code == 0
        assert "Comparison page created" in result.output

    def test_comparison_page_failure(self, mocked_cli_runner):
        """comparison-page shows failure when note has no id."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.compounder.Compounder") as MockCp:
            inst = MagicMock()
            inst.create_comparison_page.return_value = {"note": {}}
            MockCp.return_value = inst
            result = runner.invoke(
                cli, ["comparison-page", "-t", "A vs B", "-i", "A,B"]
            )
        assert result.exit_code == 0
        assert "Failed to create comparison page" in result.output

    def test_comparison_page_custom_criteria(self, mocked_cli_runner):
        """comparison-page passes --criteria to Compounder."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.compounder.Compounder") as MockCp:
            inst = MagicMock()
            inst.create_comparison_page.return_value = {"note": {"id": "n1"}}
            MockCp.return_value = inst
            result = runner.invoke(
                cli,
                ["comparison-page", "-t", "X vs Y", "-i", "X,Y", "-c", "cost,speed"],
            )
        assert result.exit_code == 0
        inst.create_comparison_page.assert_called_once_with(
            title="X vs Y",
            items=["X", "Y"],
            workspace_id="default",
            criteria=["cost", "speed"],
        )


@pytest.mark.unit
class TestSearchEntities:
    """search-entities command."""

    def test_search_entities_with_results(self, mocked_cli_runner):
        """search-entities shows results in JSON format."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.compounder.Compounder") as MockCp:
            inst = MagicMock()
            inst.search_entities.return_value = [
                {
                    "id": "e1",
                    "label": "Entity1",
                    "node_type": "concept",
                    "summary": "A concept",
                },
            ]
            MockCp.return_value = inst
            result = runner.invoke(
                cli, ["--output", "json", "search-entities", "--label", "Entity1"]
            )
        assert result.exit_code == 0
        assert "Entity1" in result.output

    def test_search_entities_empty(self, mocked_cli_runner):
        """search-entities shows 'No entities found' when empty."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.compounder.Compounder") as MockCp:
            inst = MagicMock()
            inst.search_entities.return_value = []
            MockCp.return_value = inst
            result = runner.invoke(cli, ["search-entities"])
        assert result.exit_code == 0
        assert "No entities found" in result.output

    def test_search_entities_with_type_and_limit(self, mocked_cli_runner):
        """search-entities passes type and limit to Compounder."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.compounder.Compounder") as MockCp:
            inst = MagicMock()
            inst.search_entities.return_value = []
            MockCp.return_value = inst
            result = runner.invoke(
                cli,
                [
                    "search-entities",
                    "--type", "person",
                    "--query", "engineer",
                    "--limit", "5",
                ],
            )
        assert result.exit_code == 0
        inst.search_entities.assert_called_once_with(
            workspace_id="default",
            label=None,
            node_type="person",
            semantic_query="engineer",
            limit=5,
        )
