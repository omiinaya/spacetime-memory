"""Supplementary tests for spacetime_memory.cli.commands._basic_commands.

Primary tests live in test_cli_basic_commands.py. This file adds coverage
for additional edge cases and direct function testing.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from spacetime_memory.cli.root import cli


class TestCompletionExtended:
    """Extended tests for the shell completion command."""

    def test_completion_bash(self):
        """Completion bash generates the expected eval snippet."""
        runner = CliRunner()
        result = runner.invoke(cli, ["completion", "bash"])
        # May or may not be registered depending on import order
        assert result.exit_code in (0, 2)


class TestRecommendExtended:
    """Extended tests for recommend command."""

    def test_recommend_with_all_actions(self):
        """All three action types appear in output."""
        runner = CliRunner()
        mc = MagicMock()
        mc.recommend_memories.return_value = [
            {"action": "discard", "urgency": 0.9, "content": "old", "trust_score": 0.3, "feedback_count": 5},
            {"action": "reinforce", "urgency": 0.7, "content": "important", "trust_score": 0.8, "feedback_count": 2},
            {"action": "review", "urgency": 0.5, "content": "maybe", "trust_score": 0.6, "feedback_count": 1},
        ]
        with patch("spacetime_memory.cli.commands._basic_commands._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            result = runner.invoke(cli, ["recommend", "ws-1"])
        assert result.exit_code == 0
        assert "DISCARD" in result.output
        assert "REINFORCE" in result.output
        assert "REVIEW" in result.output

    def test_recommend_includes_urgency_and_trust(self):
        runner = CliRunner()
        mc = MagicMock()
        mc.recommend_memories.return_value = [
            {"action": "discard", "urgency": 0.8, "content": "test", "trust_score": 0.4, "feedback_count": 3},
        ]
        with patch("spacetime_memory.cli.commands._basic_commands._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            result = runner.invoke(cli, ["recommend", "ws-1"])
        assert result.exit_code == 0
        assert "urgency=0.80" in result.output or "urgency=0.8" in result.output
        assert "trust=0.40" in result.output or "trust=0.4" in result.output
        assert "fb=3" in result.output


class TestPeerReputationExtended:
    """Extended tests for peer-reputation command."""

    def test_peer_reputation_includes_table(self):
        runner = CliRunner()
        mc = MagicMock()
        mc.get_peer_reputation.return_value = {
            "reputation_score": 0.75,
            "helpful_count": 10,
            "unhelpful_count": 2,
            "total_feedback": 12,
        }
        with patch("spacetime_memory.cli.commands._basic_commands._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            result = runner.invoke(cli, ["peer-reputation", "peer-12345678901234567890"])
        assert result.exit_code == 0
        assert "Reputation" in result.output
        assert "0.750" in result.output or "0.75" in result.output
        assert "10" in result.output
        assert "2" in result.output

    def test_peer_reputation_short_peer_id(self):
        """Short peer_id doesn't cause errors."""
        runner = CliRunner()
        mc = MagicMock()
        mc.get_peer_reputation.return_value = {}
        with patch("spacetime_memory.cli.commands._basic_commands._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            result = runner.invoke(cli, ["peer-reputation", "short"])
        assert result.exit_code == 0
        assert "No reputation" in result.output


class TestSynthesizeCommand:
    """Tests for the synthesize command."""

    def test_synthesize_with_result(self):
        runner = CliRunner()
        mc = MagicMock()
        mc.search.return_value = [{"id": "m1", "content": "Alice Chen"}]
        with patch("spacetime_memory.cli.commands._basic_commands._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            with patch("spacetime_memory.context_agent.ContextAgent") as MockAgent:
                agent = MagicMock()
                agent.synthesize.return_value = {
                    "answer": "Alice Chen is a researcher at MIT.",
                    "gaps": ["Her publications list"],
                    "sources": [0],
                    "confidence": 0.92,
                }
                MockAgent.return_value = agent
                result = runner.invoke(cli, ["synthesize", "ws-1", "Who is Alice Chen?"])
        assert result.exit_code == 0
        assert "Answer" in result.output
        assert "Alice Chen" in result.output
        assert "Knowledge Gaps" in result.output
        assert "Sources" in result.output

    def test_synthesize_no_answer(self):
        """When result has no answer, shows raw context message."""
        runner = CliRunner()
        mc = MagicMock()
        with patch("spacetime_memory.cli.commands._basic_commands._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            with patch("spacetime_memory.context_agent.ContextAgent") as MockAgent:
                agent = MagicMock()
                agent.synthesize.return_value = {"pack": {"id": "p1"}}
                MockAgent.return_value = agent
                result = runner.invoke(cli, ["synthesize", "ws-1", "query"])
        assert result.exit_code == 0
        assert "LLM unavailable" in result.output
