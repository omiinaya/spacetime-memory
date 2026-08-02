"""Tests for cli.stmem.commands.synthesize.

Covers the synthesize command.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from cli.stmem import cli
from click.testing import CliRunner


@pytest.mark.unit
class TestSynthesize:
    """synthesize command."""

    def test_synthesize_full_result(self, mocked_cli_runner):
        """synthesize shows answer, gaps, sources, and confidence."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.context_agent.ContextAgent") as MockCA:
            inst = MagicMock()
            inst.synthesize.return_value = {
                "answer": "Alice Chen is a researcher in machine learning.",
                "gaps": ["Her birth date", "Her education history"],
                "sources": [0, 1, 2],
                "confidence": 0.85,
                "pack": {"id": "pack123"},
            }
            MockCA.return_value = inst
            result = runner.invoke(
                cli, ["synthesize", "my-workspace", "What do we know about Alice Chen?"]
            )
        assert result.exit_code == 0
        assert "Answer" in result.output
        assert "Alice Chen is a researcher" in result.output
        assert "Knowledge Gaps" in result.output
        assert "Her birth date" in result.output
        assert "Her education history" in result.output
        assert "Sources" in result.output
        assert "85%" in result.output

    def test_synthesize_no_gaps(self, mocked_cli_runner):
        """synthesize shows answer without gaps section when none exist."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.context_agent.ContextAgent") as MockCA:
            inst = MagicMock()
            inst.synthesize.return_value = {
                "answer": "Just the answer.",
                "gaps": [],
                "sources": [],
                "confidence": 0.95,
                "pack": {"id": "pack456"},
            }
            MockCA.return_value = inst
            result = runner.invoke(cli, ["synthesize", "ws", "query"])
        assert result.exit_code == 0
        assert "Answer" in result.output
        assert "Just the answer." in result.output
        assert "Knowledge Gaps" not in result.output

    def test_synthesize_llm_unavailable(self, mocked_cli_runner):
        """synthesize falls back to raw context when LLM is unavailable."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.context_agent.ContextAgent") as MockCA:
            inst = MagicMock()
            inst.synthesize.return_value = {
                "answer": None,
                "gaps": [],
                "sources": [],
                "confidence": 0.0,
                "pack": {"id": "pack789"},
            }
            MockCA.return_value = inst
            result = runner.invoke(cli, ["synthesize", "ws", "query"])
        assert result.exit_code == 0
        assert "LLM unavailable" in result.output
        assert "pack789" in result.output

    def test_synthesize_error(self, mocked_cli_runner):
        """synthesize shows error message when agent returns an error."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.context_agent.ContextAgent") as MockCA:
            inst = MagicMock()
            inst.synthesize.return_value = {
                "error": "No context pack generated",
                "answer": None,
                "gaps": [],
            }
            MockCA.return_value = inst
            result = runner.invoke(cli, ["synthesize", "ws", "query"])
        assert result.exit_code == 0
        assert "No context pack generated" in result.output

    def test_synthesize_passes_budget(self, mocked_cli_runner):
        """synthesize passes --budget to agent.synthesize as token_budget."""
        runner, mock_client = mocked_cli_runner
        with patch("spacetime_memory.context_agent.ContextAgent") as MockCA:
            inst = MagicMock()
            inst.synthesize.return_value = {
                "answer": "Answer",
                "gaps": [],
                "sources": [],
                "confidence": 0.5,
                "pack": {"id": "p1"},
            }
            MockCA.return_value = inst
            result = runner.invoke(
                cli, ["synthesize", "ws", "query", "--budget", "8192"]
            )
        assert result.exit_code == 0
        inst.synthesize.assert_called_once_with(
            "query", workspace_id="ws", token_budget=8192
        )

    def test_synthesize_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["synthesize", "--help"])
        assert result.exit_code == 0
        assert "WORKSPACE_ID" in result.output
        assert "QUERY" in result.output
        assert "budget" in result.output
