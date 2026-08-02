"""Unit tests for StatsMixin — memory stats, decay config, recommendations.

All tests use the ``mock_http_client`` fixture — no live SpacetimeDB required.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestStatsMixin:
    """StatsMixin methods (decay, recommendations, bridge nodes, KG stats, memory stats)."""

    # --- Decay ---

    def test_set_decay_model_linear(self, mock_http_client):
        result = mock_http_client.set_decay_model(
            "ws-1", model="linear", decay_rate=0.005, max_days=90,
        )
        assert result == {"status": "ok"}

    def test_set_decay_model_weibull(self, mock_http_client):
        result = mock_http_client.set_decay_model(
            "ws-1", model="weibull", weibull_shape=0.6, weibull_scale=30.0,
        )
        assert result == {"status": "ok"}

    def test_set_decay_model_invalid(self, mock_http_client):
        with pytest.raises(ValueError, match="Unknown decay model"):
            mock_http_client.set_decay_model("ws-1", model="unknown")

    def test_get_decay_config(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[{"id": "ws-1", "model": "linear"}]):
            result = mock_http_client.get_decay_config("ws-1")
        assert result is not None
        assert result["model"] == "linear"

    def test_get_decay_config_none(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.get_decay_config("ws-1")
        assert result is None

    # --- Recommendations ---

    def test_recommend_memories(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"workspace_id": "ws-1", "memory_id": "mem-1", "score": 0.9}
             ]):
            result = mock_http_client.recommend_memories("ws-1", limit=20, min_urgency=0.3)
        assert len(result) == 1

    def test_recommend_memories_empty(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.recommend_memories("ws-1")
        assert result == []

    # --- Peer reputation ---

    def test_get_peer_reputation(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"peer_id": "peer-1", "trust_score": 0.85}
             ]):
            result = mock_http_client.get_peer_reputation("peer-1")
        assert result is not None
        assert result["trust_score"] == 0.85

    def test_get_peer_reputation_none(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.get_peer_reputation("peer-1")
        assert result is None

    # --- Bridge nodes ---

    def test_detect_bridge_nodes(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"workspace_id": "ws-1", "node_id": "n1", "bridge_score": 0.9}
             ]):
            result = mock_http_client.detect_bridge_nodes("ws-1", limit=20, min_communities=2)
        assert len(result) == 1

    def test_detect_bridge_nodes_empty(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.detect_bridge_nodes("ws-1")
        assert result == []

    # --- KG stats ---

    def test_compute_kg_stats(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"workspace_id": "ws-1", "node_count": 10, "edge_count": 25}
             ]):
            result = mock_http_client.compute_kg_stats("ws-1")
        assert result is not None
        assert result["node_count"] == 10

    def test_compute_kg_stats_none(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.compute_kg_stats("ws-1")
        assert result is None

    # --- Memory stats ---

    def test_get_memory_stats(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"stat_key": "total_memories", "stat_value": "100"},
                 {"stat_key": "active_memories", "stat_value": "80"},
             ]):
            result = mock_http_client.get_memory_stats("ws-1")
        assert result is not None
        assert result["total_memories"] == "100"
        assert result["active_memories"] == "80"

    def test_get_memory_stats_none(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.get_memory_stats("ws-1")
        assert result is None
