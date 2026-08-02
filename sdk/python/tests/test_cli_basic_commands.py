"""Unit tests for stmem CLI basic commands.

Tests the Click commands defined in _basic_commands.py: recommend,
peer_reputation.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from spacetime_memory.cli.root import cli


@pytest.mark.unit
class TestRecommend:
    def test_recommend_with_results(self):
        """Recommend command shows memory recommendations."""
        runner = CliRunner()
        mc = MagicMock()
        mc.recommend_memories.return_value = [
            {"action": "discard", "urgency": 0.8, "content": "old memory", "trust_score": 0.5, "feedback_count": 3},
            {"action": "review", "urgency": 0.6, "content": "needs review", "trust_score": 0.7, "feedback_count": 1},
        ]
        with patch("spacetime_memory.cli.commands._basic_commands._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            result = runner.invoke(cli, ["recommend", "ws-1"])
        assert result.exit_code == 0
        assert "DISCARD" in result.output
        assert "REVIEW" in result.output

    def test_recommend_empty(self):
        """Recommend command shows 'all clear' when no results."""
        runner = CliRunner()
        mc = MagicMock()
        mc.recommend_memories.return_value = []
        with patch("spacetime_memory.cli.commands._basic_commands._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            result = runner.invoke(cli, ["recommend", "ws-1"])
        assert result.exit_code == 0
        assert "all clear" in result.output.lower()

    def test_recommend_with_options(self):
        """Recommend command accepts --limit and --min-urgency."""
        runner = CliRunner()
        mc = MagicMock()
        mc.recommend_memories.return_value = []
        with patch("spacetime_memory.cli.commands._basic_commands._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            result = runner.invoke(cli, ["recommend", "ws-1", "--limit", "10", "--min-urgency", "0.5"])
        assert result.exit_code == 0
        mc.recommend_memories.assert_called_once_with("ws-1", limit=10, min_urgency=0.5)


@pytest.mark.unit
class TestPeerReputation:
    def test_peer_reputation_with_data(self):
        """Peer-reputation shows reputation stats."""
        runner = CliRunner()
        mc = MagicMock()
        mc.get_peer_reputation.return_value = {
            "reputation_score": 0.85,
            "helpful_count": 42,
            "unhelpful_count": 3,
            "total_feedback": 45,
        }
        with patch("spacetime_memory.cli.commands._basic_commands._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            result = runner.invoke(cli, ["peer-reputation", "peer-12345678901234567890"])
        assert result.exit_code == 0
        assert "Reputation" in result.output
        assert "Helpful" in result.output
        assert "Unhelpful" in result.output

    def test_peer_reputation_empty(self):
        """Peer-reputation shows 'no data' when no reputation found."""
        runner = CliRunner()
        mc = MagicMock()
        mc.get_peer_reputation.return_value = {}
        with patch("spacetime_memory.cli.commands._basic_commands._sdk_client") as mock_fn:
            mock_fn.return_value = mc
            result = runner.invoke(cli, ["peer-reputation", "peer-12345678"])
        assert result.exit_code == 0
        assert "No reputation" in result.output
