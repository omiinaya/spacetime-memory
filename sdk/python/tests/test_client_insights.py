"""Unit tests for InsightMixin — insight creation and deletion.

All tests use the ``mock_http_client`` fixture — no live SpacetimeDB required.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestInsightMixin:
    """InsightMixin methods (create_insight, delete_insight)."""

    # ── Existing tests (preserved) ──────────────────────────────

    def test_create_insight(self, mock_http_client):
        result = mock_http_client.create_insight(
            workspace_id="ws-1",
            peer_id="peer-1",
            content="This is an insight",
            insight_type="conclusion",
            source_memory_ids_json='["mem-1", "mem-2"]',
            confidence=0.85,
        )
        assert result == {"status": "ok"}

    def test_create_insight_with_different_type(self, mock_http_client):
        result = mock_http_client.create_insight(
            workspace_id="ws-1",
            peer_id="peer-1",
            content="An observation",
            insight_type="observation",
            source_memory_ids_json="[]",
            confidence=0.5,
        )
        assert result == {"status": "ok"}

    def test_delete_insight(self, mock_http_client):
        result = mock_http_client.delete_insight("insight-1")
        assert result == {"status": "ok"}

    def test_delete_insight_error(self, mock_http_client):
        with patch.object(mock_http_client, "_call", side_effect=RuntimeError("insight not found")):
            with pytest.raises(RuntimeError, match="insight not found"):
                mock_http_client.delete_insight("nonexistent")

    # ── NEW: create_insight parameter edge cases ────────────────

    def test_create_insight_empty_content(self, mock_http_client):
        """Empty content string is accepted."""
        result = mock_http_client.create_insight(
            workspace_id="ws-1",
            peer_id="peer-1",
            content="",
            insight_type="observation",
            source_memory_ids_json="[]",
            confidence=0.5,
        )
        assert result == {"status": "ok"}

    def test_create_insight_very_long_content(self, mock_http_client):
        """Very long content is handled without error."""
        long_content = "x" * 100_000
        result = mock_http_client.create_insight(
            workspace_id="ws-1",
            peer_id="peer-1",
            content=long_content,
            insight_type="conclusion",
            source_memory_ids_json="[]",
            confidence=0.5,
        )
        assert result == {"status": "ok"}

    def test_create_insight_unicode_content(self, mock_http_client):
        """Unicode / emoji content is handled."""
        result = mock_http_client.create_insight(
            workspace_id="ws-1",
            peer_id="peer-1",
            content="观察 Insight with 中文 and 🚀 emoji —测试",
            insight_type="observation",
            source_memory_ids_json="[]",
            confidence=0.5,
        )
        assert result == {"status": "ok"}

    def test_create_insight_confidence_zero(self, mock_http_client):
        """Confidence of 0.0 is accepted."""
        result = mock_http_client.create_insight(
            workspace_id="ws-1",
            peer_id="peer-1",
            content="Zero confidence insight",
            insight_type="observation",
            source_memory_ids_json="[]",
            confidence=0.0,
        )
        assert result == {"status": "ok"}

    def test_create_insight_confidence_one(self, mock_http_client):
        """Confidence of 1.0 is accepted."""
        result = mock_http_client.create_insight(
            workspace_id="ws-1",
            peer_id="peer-1",
            content="Full confidence",
            insight_type="conclusion",
            source_memory_ids_json="[]",
            confidence=1.0,
        )
        assert result == {"status": "ok"}

    def test_create_insight_negative_confidence(self, mock_http_client):
        """Negative confidence is passed through (server-side validation)."""
        result = mock_http_client.create_insight(
            workspace_id="ws-1",
            peer_id="peer-1",
            content="Negative confidence",
            insight_type="observation",
            source_memory_ids_json="[]",
            confidence=-0.5,
        )
        assert result == {"status": "ok"}

    def test_create_insight_confidence_above_one(self, mock_http_client):
        """Confidence > 1.0 is passed through (server-side validation)."""
        result = mock_http_client.create_insight(
            workspace_id="ws-1",
            peer_id="peer-1",
            content="Overconfidence",
            insight_type="conclusion",
            source_memory_ids_json="[]",
            confidence=2.5,
        )
        assert result == {"status": "ok"}

    def test_create_insight_multiple_source_memories(self, mock_http_client):
        """Multiple source memory IDs in JSON array."""
        result = mock_http_client.create_insight(
            workspace_id="ws-1",
            peer_id="peer-1",
            content="Derived from many sources",
            insight_type="synthesis",
            source_memory_ids_json='["mem-1", "mem-2", "mem-3", "mem-4", "mem-5"]',
            confidence=0.75,
        )
        assert result == {"status": "ok"}

    def test_create_insight_empty_source_memories(self, mock_http_client):
        """Empty source_memory_ids_json is accepted."""
        result = mock_http_client.create_insight(
            workspace_id="ws-1",
            peer_id="peer-1",
            content="No source memories",
            insight_type="observation",
            source_memory_ids_json="[]",
            confidence=0.5,
        )
        assert result == {"status": "ok"}

    def test_create_insight_empty_workspace_id(self, mock_http_client):
        """Empty workspace_id is passed through."""
        result = mock_http_client.create_insight(
            workspace_id="",
            peer_id="peer-1",
            content="No workspace",
            insight_type="observation",
            source_memory_ids_json="[]",
            confidence=0.5,
        )
        assert result == {"status": "ok"}

    def test_create_insight_empty_peer_id(self, mock_http_client):
        """Empty peer_id is passed through."""
        result = mock_http_client.create_insight(
            workspace_id="ws-1",
            peer_id="",
            content="No peer",
            insight_type="observation",
            source_memory_ids_json="[]",
            confidence=0.5,
        )
        assert result == {"status": "ok"}

    # ── NEW: Various insight_type values ────────────────────────

    @pytest.mark.parametrize("insight_type", [
        "conclusion",
        "observation",
        "connection",
        "question",
        "hypothesis",
        "summary",
        "anomaly",
        "pattern",
        "recommendation",
    ])
    def test_create_insight_various_types(self, mock_http_client, insight_type):
        """Various insight_type strings are accepted."""
        result = mock_http_client.create_insight(
            workspace_id="ws-1",
            peer_id="peer-1",
            content=f"Insight of type {insight_type}",
            insight_type=insight_type,
            source_memory_ids_json="[]",
            confidence=0.5,
        )
        assert result == {"status": "ok"}

    @pytest.mark.parametrize("confidence", [0.0, 0.25, 0.5, 0.75, 1.0])
    def test_create_insight_various_confidence_values(self, mock_http_client, confidence):
        """Various confidence values are accepted."""
        result = mock_http_client.create_insight(
            workspace_id="ws-1",
            peer_id="peer-1",
            content=f"Confidence {confidence}",
            insight_type="observation",
            source_memory_ids_json='["mem-1"]',
            confidence=confidence,
        )
        assert result == {"status": "ok"}

    # ── NEW: Error cases for create_insight ─────────────────────

    def test_create_insight_call_raises_runtime_error(self, mock_http_client):
        """Server error from _call propagates."""
        with patch.object(
            mock_http_client, "_call", side_effect=RuntimeError("STDB reducer error")
        ), pytest.raises(RuntimeError, match="STDB reducer error"):
            mock_http_client.create_insight(
                workspace_id="ws-1",
                peer_id="peer-1",
                content="test",
                insight_type="observation",
                source_memory_ids_json="[]",
                confidence=0.5,
            )

    def test_create_insight_call_raises_connection_error(self, mock_http_client):
        """Network-level error from _call propagates."""
        with patch.object(
            mock_http_client, "_call", side_effect=ConnectionError("connection refused")
        ), pytest.raises(ConnectionError, match="connection refused"):
            mock_http_client.create_insight(
                workspace_id="ws-1",
                peer_id="peer-1",
                content="test",
                insight_type="observation",
                source_memory_ids_json="[]",
                confidence=0.5,
            )

    def test_create_insight_call_raises_value_error(self, mock_http_client):
        """ValueError from _call propagates (e.g. malformed args)."""
        with patch.object(
            mock_http_client, "_call", side_effect=ValueError("invalid argument")
        ), pytest.raises(ValueError, match="invalid argument"):
            mock_http_client.create_insight(
                workspace_id="ws-1",
                peer_id="peer-1",
                content="test",
                insight_type="observation",
                source_memory_ids_json="[]",
                confidence=0.5,
            )

    def test_create_insight_http_500_error(self, mock_http_client):
        """HTTP 500 from the server propagates as RuntimeError via _call."""
        mock_http_client._http.post.return_value.status_code = 500
        mock_http_client._http.post.return_value.text = "Internal Server Error"

        with pytest.raises(RuntimeError, match="Internal Server Error|500"):
            mock_http_client.create_insight(
                workspace_id="ws-1",
                peer_id="peer-1",
                content="test",
                insight_type="observation",
                source_memory_ids_json="[]",
                confidence=0.5,
            )

    # ── NEW: Error cases for delete_insight ─────────────────────

    def test_delete_insight_http_500(self, mock_http_client):
        """HTTP 500 from server on delete propagates as RuntimeError."""
        mock_http_client._http.post.return_value.status_code = 500
        mock_http_client._http.post.return_value.text = "server error on delete"

        with pytest.raises(RuntimeError, match="server error on delete|500"):
            mock_http_client.delete_insight("insight-1")

    def test_delete_insight_connection_error(self, mock_http_client):
        """Network error on delete propagates."""
        with patch.object(
            mock_http_client, "_call", side_effect=ConnectionError("network unreachable")
        ), pytest.raises(ConnectionError, match="network unreachable"):
            mock_http_client.delete_insight("nonexistent")

    def test_delete_insight_empty_id(self, mock_http_client):
        """Empty insight ID is passed through (server-side validation)."""
        result = mock_http_client.delete_insight("")
        assert result == {"status": "ok"}

    def test_delete_insight_special_chars_id(self, mock_http_client):
        """Insight ID with special characters is handled."""
        result = mock_http_client.delete_insight("insight-id-with-dashes_and_underscores")
        assert result == {"status": "ok"}

    # ── NEW: Verifying _call arguments ──────────────────────────

    def test_create_insight_passes_correct_args(self, mock_http_client):
        """Verify create_insight passes the correct reducer name and args."""
        with patch.object(mock_http_client, "_call", wraps=mock_http_client._call) as spy:
            spy.return_value = {"status": "ok"}
            mock_http_client.create_insight(
                workspace_id="ws-1",
                peer_id="peer-1",
                content="test content",
                insight_type="conclusion",
                source_memory_ids_json='["mem-1"]',
                confidence=0.9,
            )
            spy.assert_called_once()
            args = spy.call_args[0]
            assert args[0] == "create_insight"
            assert args[1] == ["ws-1", "peer-1", "test content", "conclusion", '["mem-1"]', 0.9]

    def test_delete_insight_passes_correct_args(self, mock_http_client):
        """Verify delete_insight passes the correct reducer name and args."""
        with patch.object(mock_http_client, "_call", wraps=mock_http_client._call) as spy:
            spy.return_value = {"status": "ok"}
            mock_http_client.delete_insight("my-insight-id")
            spy.assert_called_once()
            args = spy.call_args[0]
            assert args[0] == "delete_insight"
            assert args[1] == ["my-insight-id"]
