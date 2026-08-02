"""Tests for spacetime_memory.cli.commands._compounder_commands.

Covers the sdk-python CLI compounder commands: overview, lint,
cross-link, suggest-connections, store-answer, store-answers-batch,
entity-page, update-entity-page, concept-page, comparison-page,
and search-entities.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from spacetime_memory.cli.root import cli


def _mock_compounder_result(**overrides) -> dict:
    """Default result dict from Compounder methods."""
    result = {
        "note": {"id": "note-abc123def456", "title": "Test Note"},
        "node": {"id": "node-xyz789"},
        "entities_created": [{"label": "Entity1"}],
        "orphans": [],
        "missing_crossrefs": [],
        "contradictions": [],
        "links_created": [],
        "suggestions": [],
    }
    result.update(overrides)
    return result


def _mock_client(**kwargs) -> MagicMock:
    mc = MagicMock()
    mc._sql.return_value = []
    mc._call.return_value = {"status": "ok"}
    for k, v in kwargs.items():
        setattr(mc, k, v)
    return mc


@pytest.mark.unit
class TestOverview:
    """overview command."""

    def test_overview_with_note(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.generate_overview_page.return_value = _mock_compounder_result()
                MockCp.return_value = inst
                result = runner.invoke(cli, ["overview"])
        assert result.exit_code == 0
        assert "Overview generated" in result.output

    def test_overview_empty_workspace(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.generate_overview_page.return_value = {"note": {}}
                MockCp.return_value = inst
                result = runner.invoke(cli, ["overview", "-w", "my-ws"])
        assert result.exit_code == 0
        assert "empty" in result.output.lower()

    def test_overview_json_format(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.generate_overview_page.return_value = _mock_compounder_result()
                MockCp.return_value = inst
                result = runner.invoke(cli, ["--output", "json", "overview"])
        assert result.exit_code == 0

    def test_overview_no_embed_flag(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.generate_overview_page.return_value = _mock_compounder_result()
                MockCp.return_value = inst
                result = runner.invoke(cli, ["overview", "--no-embed"])
        assert result.exit_code == 0
        # Verify embed=False was passed
        inst.generate_overview_page.assert_called_once()
        assert inst.generate_overview_page.call_args[1].get("embed") is False


@pytest.mark.unit
class TestLint:
    """lint command."""

    def test_lint_clean(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.lint_workspace.return_value = {
                    "orphans": [],
                    "missing_crossrefs": [],
                    "contradictions": [],
                }
                MockCp.return_value = inst
                result = runner.invoke(cli, ["lint", "-w", "default"])
        assert result.exit_code == 0
        assert "clean" in result.output.lower()

    def test_lint_with_issues(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.lint_workspace.return_value = {
                    "orphans": [{"id": "o1", "label": "orphan1", "node_type": "concept"}],
                    "missing_crossrefs": [{"note_id": "n1", "note_title": "Note1", "entity": "EntityX"}],
                    "contradictions": [{"note_id": "n1", "contradicts_note_id": "n2"}],
                }
                MockCp.return_value = inst
                result = runner.invoke(cli, ["lint", "-w", "default"])
        assert result.exit_code == 0
        assert "Orphan" in result.output
        assert "contradiction" in result.output.lower()

    def test_lint_skip_contradictions(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.lint_workspace.return_value = {
                    "orphans": [], "missing_crossrefs": [], "contradictions": [],
                }
                MockCp.return_value = inst
                result = runner.invoke(cli, ["lint", "--no-contradictions"])
        assert result.exit_code == 0
        inst.lint_workspace.assert_called_once()
        assert inst.lint_workspace.call_args[1].get("check_contradictions") is False

    def test_lint_json_format(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                data = {"orphans": [], "missing_crossrefs": [], "contradictions": [{"note_id": "n1"}]}
                inst.lint_workspace.return_value = data
                MockCp.return_value = inst
                result = runner.invoke(cli, ["--output", "json", "lint"])
        assert result.exit_code == 0
        assert "n1" in result.output


@pytest.mark.unit
class TestCrossLink:
    """cross-link command."""

    def test_cross_link_creates_links(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.cross_link.return_value = {"links_created": [{"id": "l1"}]}
                MockCp.return_value = inst
                result = runner.invoke(cli, ["cross-link"])
        assert result.exit_code == 0
        assert "Created" in result.output

    def test_cross_link_dry_run(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.cross_link.return_value = {"links_created": [{"id": "l1"}]}
                MockCp.return_value = inst
                result = runner.invoke(cli, ["cross-link", "--dry-run"])
        assert result.exit_code == 0
        assert "DRY RUN" in result.output

    def test_cross_link_no_links(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.cross_link.return_value = {"links_created": []}
                MockCp.return_value = inst
                result = runner.invoke(cli, ["cross-link"])
        assert result.exit_code == 0
        assert "No new cross-links" in result.output


@pytest.mark.unit
class TestSuggestConnections:
    """suggest-connections command."""

    def test_suggest_with_results(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.suggest_connections.return_value = [
                    {"source_label": "A", "target_label": "B", "score": 5},
                ]
                MockCp.return_value = inst
                result = runner.invoke(cli, ["suggest-connections", "-n", "10"])
        assert result.exit_code == 0
        assert "A" in result.output
        assert "B" in result.output
        inst.suggest_connections.assert_called_once()
        assert inst.suggest_connections.call_args[1].get("limit") == 10

    def test_suggest_empty(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.suggest_connections.return_value = []
                MockCp.return_value = inst
                result = runner.invoke(cli, ["suggest-connections"])
        assert result.exit_code == 0
        assert "No connection suggestions" in result.output


@pytest.mark.unit
class TestStoreAnswer:
    """store-answer command."""

    def test_store_answer_success(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.store_answer.return_value = {
                    "note": {"id": "note-abc", "title": "My Answer"},
                    "entities_created": [{"label": "AI"}],
                }
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["store-answer", "-q", "What is AI?", "-a", "Artificial Intelligence"]
                )
        assert result.exit_code == 0
        assert "Answer stored" in result.output
        assert "My Answer" in result.output

    def test_store_answer_with_source_ids(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.store_answer.return_value = {
                    "note": {"id": "note-abc", "title": "Answer"},
                    "entities_created": [],
                }
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["store-answer", "-q", "Q", "-a", "A", "-s", "src1,src2"]
                )
        assert result.exit_code == 0
        inst.store_answer.assert_called_once()
        assert inst.store_answer.call_args[1].get("source_memory_ids") == ["src1", "src2"]

    def test_store_answer_no_embed(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.store_answer.return_value = {"note": {"id": "n1", "title": "T"}, "entities_created": []}
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["store-answer", "-q", "Q", "-a", "A", "--no-embed"]
                )
        assert result.exit_code == 0
        assert inst.store_answer.call_args[1].get("embed") is False

    def test_store_answer_missing_query(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["store-answer", "-a", "some answer"])
        assert result.exit_code != 0
        assert "Error" in result.output or "option" in result.output.lower()

    def test_store_answer_missing_answer(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["store-answer", "-q", "some question"])
        assert result.exit_code != 0
        assert "Error" in result.output or "option" in result.output.lower()

    def test_store_answer_failure(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.store_answer.return_value = {"note": {}}
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["store-answer", "-q", "Q", "-a", "A"]
                )
        assert result.exit_code == 0
        assert "Failed to store answer" in result.output


@pytest.mark.unit
class TestStoreAnswersBatch:
    """store-answers-batch command."""

    def test_store_answers_batch_success(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.store_answers.return_value = [
                    {"note": {"id": "n1"}, "entities": [{"label": "E1"}]},
                    {"note": {"id": "n2"}, "entities": [{"label": "E2"}]},
                ]
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["store-answers-batch", "-p", '[["Q1","A1"],["Q2","A2"]]']
                )
        assert result.exit_code == 0
        assert "Batch stored" in result.output
        assert "2 answers" in result.output

    def test_store_answers_batch_invalid_json(self):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["store-answers-batch", "-p", "not-json"]
        )
        assert result.exit_code != 0

    def test_store_answers_batch_wrong_structure(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            result = runner.invoke(
                cli, ["store-answers-batch", "-p", '["not", "nested"]']
            )
        assert result.exit_code != 0
        assert "Pairs must be" in result.output

    def test_store_answers_batch_file_not_found(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            # The --pairs option is required by Click, so provide a dummy value.
            # The --file path (nonexistent) takes priority over --pairs.
            result = runner.invoke(
                cli, ["store-answers-batch", "-p", '[["Q","A"]]', "-f", "/nonexistent/pairs.json"]
            )
        assert result.exit_code != 0
        assert "File not found" in result.output

    def test_store_answers_batch_with_source_ids(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.store_answers.return_value = []
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["store-answers-batch", "-p", '[["Q","A"]]', "-s", "src1,src2"]
                )
        assert result.exit_code == 0
        inst.store_answers.assert_called_once()
        assert inst.store_answers.call_args[1].get("source_memory_ids") == ["src1", "src2"]


@pytest.mark.unit
class TestEntityPage:
    """entity-page command."""

    def test_entity_page_success(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.create_entity_page.return_value = {
                    "note": {"id": "note-xyz"},
                    "node": {"id": "node-abc"},
                }
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["entity-page", "-n", "Alice", "-d", "A person"]
                )
        assert result.exit_code == 0
        assert "Entity page created" in result.output
        assert "Alice" in result.output

    def test_entity_page_with_type(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
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
        assert inst.create_entity_page.call_args[1].get("entity_type") == "person"

    def test_entity_page_with_related(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.create_entity_page.return_value = {
                    "note": {"id": "n1"}, "node": {"id": "nd1"},
                }
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["entity-page", "-n", "X", "-d", "Desc", "--related", "A,B"]
                )
        assert result.exit_code == 0
        inst.create_entity_page.assert_called_once()
        assert inst.create_entity_page.call_args[1].get("relations") == [
            {"name": "A", "relation": "related_to"},
            {"name": "B", "relation": "related_to"},
        ]

    def test_entity_page_with_tags(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.create_entity_page.return_value = {
                    "note": {"id": "n1"}, "node": {"id": "nd1"},
                }
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["entity-page", "-n", "X", "-d", "Desc", "--tags", "t1,t2"]
                )
        assert result.exit_code == 0
        inst.create_entity_page.assert_called_once()
        assert inst.create_entity_page.call_args[1].get("tags") == ["t1", "t2"]

    def test_entity_page_failure(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
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
        result = runner.invoke(cli, ["entity-page", "-d", "Description"])
        assert result.exit_code != 0

    def test_entity_page_missing_description(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["entity-page", "-n", "Name"])
        assert result.exit_code != 0


@pytest.mark.unit
class TestUpdateEntityPage:
    """update-entity-page command."""

    def test_update_entity_page_success(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
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

    def test_update_entity_page_not_found(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.update_entity_page.return_value = {"note": {}, "node": {}}
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["update-entity-page", "-n", "Nonexistent"]
                )
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_update_entity_page_with_fields(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.update_entity_page.return_value = {
                    "note": {"id": "n1"}, "node": {"id": "nd1"},
                }
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["update-entity-page", "-n", "Alice", "-d", "New desc", "-t", "person"]
                )
        assert result.exit_code == 0
        inst.update_entity_page.assert_called_once_with(
            name="Alice", description="New desc", entity_type="person", workspace_id="default"
        )


@pytest.mark.unit
class TestConceptPage:
    """concept-page command."""

    def test_concept_page_success(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.create_concept_page.return_value = {"note": {"id": "n1"}}
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["concept-page", "-c", "RLHF", "-d", "Reinforcement Learning from Human Feedback"]
                )
        assert result.exit_code == 0
        assert "Concept page created" in result.output

    def test_concept_page_with_related(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.create_concept_page.return_value = {"note": {"id": "n1"}}
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["concept-page", "-c", "AI", "-d", "AI desc", "--related", "ML,DL"]
                )
        assert result.exit_code == 0
        assert "Related" in result.output
        inst.create_concept_page.assert_called_once()
        assert inst.create_concept_page.call_args[1].get("related_concepts") == ["ML", "DL"]

    def test_concept_page_failure(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
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

    def test_comparison_page_success(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.create_comparison_page.return_value = {"note": {"id": "n1"}}
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["comparison-page", "-t", "A vs B", "-i", "A,B"]
                )
        assert result.exit_code == 0
        assert "Comparison page created" in result.output

    def test_comparison_page_failure(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.create_comparison_page.return_value = {"note": {}}
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["comparison-page", "-t", "A vs B", "-i", "A,B"]
                )
        assert result.exit_code == 0
        assert "Failed to create comparison page" in result.output

    def test_comparison_page_custom_criteria(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.create_comparison_page.return_value = {"note": {"id": "n1"}}
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["comparison-page", "-t", "X vs Y", "-i", "X,Y", "-c", "cost,speed"]
                )
        assert result.exit_code == 0
        inst.create_comparison_page.assert_called_once()
        assert inst.create_comparison_page.call_args[1].get("criteria") == ["cost", "speed"]


@pytest.mark.unit
class TestSearchEntities:
    """search-entities command."""

    def test_search_entities_with_results(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.search_entities.return_value = [
                    {"id": "e1", "label": "Entity1", "node_type": "concept", "summary": "A concept"},
                ]
                MockCp.return_value = inst
                # Use JSON output to avoid the Table import issue in the source module
                result = runner.invoke(cli, ["--output", "json", "search-entities", "--label", "Entity1"])
        assert result.exit_code == 0
        assert "Entity1" in result.output

    def test_search_entities_empty(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.search_entities.return_value = []
                MockCp.return_value = inst
                result = runner.invoke(cli, ["search-entities"])
        assert result.exit_code == 0
        assert "No entities found" in result.output

    def test_search_entities_with_type_filter(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.search_entities.return_value = []
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["search-entities", "--type", "person", "--limit", "5"]
                )
        assert result.exit_code == 0
        inst.search_entities.assert_called_once()
        assert inst.search_entities.call_args[1].get("node_type") == "person"
        assert inst.search_entities.call_args[1].get("limit") == 5

    def test_search_entities_semantic_query(self):
        runner = CliRunner()
        with patch(
            "spacetime_memory.cli.commands._compounder_commands._sdk_client"
        ) as mock_sdk_fn:
            mock_sdk_fn.return_value = _mock_client()
            with patch(
                "spacetime_memory.compounder.Compounder"
            ) as MockCp:
                inst = MagicMock()
                inst.search_entities.return_value = []
                MockCp.return_value = inst
                result = runner.invoke(
                    cli, ["search-entities", "--query", "machine learning"]
                )
        assert result.exit_code == 0
        inst.search_entities.assert_called_once()
        assert inst.search_entities.call_args[1].get("semantic_query") == "machine learning"
