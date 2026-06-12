"""Tests for LLM reranking (QMD parity)."""

import json
import pytest
from unittest.mock import MagicMock, patch


_MOCK_RERANK_RESPONSE = {
    "choices": [{
        "message": {
            "content": json.dumps([
                {"index": 0, "score": 9, "reason": "directly about auth"},
                {"index": 1, "score": 3, "reason": "tangential mention only"},
                {"index": 2, "score": 7, "reason": "related login flow"},
            ])
        }
    }]
}


@pytest.fixture
def mock_client():
    """Client with mocked HTTP layer."""
    from unittest.mock import MagicMock
    from spacetime_memory import Client

    c = Client.__new__(Client)
    c._http = MagicMock()
    c.database = "test"
    c._identity_token = "test-token"
    c._identity_established = True
    c._call = MagicMock(return_value={"status": "ok"})
    c._sql = MagicMock(return_value=[])
    c._query = MagicMock(return_value=[])
    c._embed = MagicMock(return_value=[0.1] * 384)
    return c


class TestLLMRerank:
    """LLM reranking: re-score search results via LLM."""

    def _mock_results(self):
        return [
            {"content": "This document describes the OAuth2 authentication flow", "score": 0.80},
            {"content": "Pizza recipe with pepperoni and mushrooms", "score": 0.60},
            {"content": "User login sequence and session management", "score": 0.75},
            {"content": "Weather forecast for Tuesday", "score": 0.55},
        ]

    def test_rerank_no_results(self):
        """Empty results returned as-is."""
        from spacetime_memory.client import llm_rerank
        assert llm_rerank("query", []) == []

    def test_rerank_fallback_on_http_error(self):
        """HTTP failure returns original results unscathed."""
        from spacetime_memory.client import llm_rerank
        results = self._mock_results()
        original_scores = [r["score"] for r in results]

        with patch("httpx.post", side_effect=Exception("connection refused")):
            out = llm_rerank("auth", results, model="test-model",
                             endpoint="http://localhost:1/v1", api_key="sk-test")
        assert out is results  # same list object
        assert [r["score"] for r in out] == original_scores  # unchanged

    def test_rerank_replaces_scores(self):
        """LLM scores replace original scores and result is re-sorted."""
        from spacetime_memory.client import llm_rerank
        results = self._mock_results()

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = _MOCK_RERANK_RESPONSE

        with patch("httpx.post", return_value=mock_resp):
            out = llm_rerank("auth login", results,
                             endpoint="http://mock/v1",
                             model="test-model",
                             api_key="sk-test")

        # Re-sorted by LLM score: index 0 (9 → 0.9), index 2 (7 → 0.7),
        # index 1 (3 → 0.3), index 3 (unranked → 0.275)
        assert out[0]["score"] == 0.9
        assert out[1]["score"] == 0.7
        assert out[2]["score"] == 0.3
        assert out[3]["score"] == 0.55 * 0.5

        # rerank_reason populated
        assert out[0]["rerank_reason"] == "directly about auth"
        assert out[1]["rerank_reason"] == "related login flow"
        assert out[2]["rerank_reason"] == "tangential mention only"
        assert "not reranked" in out[3]["rerank_reason"]

    def test_rerank_strips_markdown_fence(self):
        """LLM response wrapped in ```json``` fences is stripped."""
        from spacetime_memory.client import llm_rerank
        results = self._mock_results()

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '```json\n[{"index":0,"score":5,"reason":"ok"}]\n```'}}]
        }

        with patch("httpx.post", return_value=mock_resp):
            out = llm_rerank("q", results, endpoint="http://mock/v1",
                             model="test", api_key="sk-test")

        assert out[0]["score"] == 0.5
        assert out[0]["rerank_reason"] == "ok"

    def test_rerank_env_fallback(self):
        """Config falls back to env vars."""
        from spacetime_memory.client import llm_rerank
        results = self._mock_results()

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = _MOCK_RERANK_RESPONSE

        with patch("httpx.post", return_value=mock_resp):
            with patch.dict("os.environ", {
                "LLM_RERANK_ENDPOINT": "http://env/v1",
                "LLM_RERANK_MODEL": "env-model",
                "LLM_RERANK_API_KEY": "env-key",
            }):
                out = llm_rerank("test query", results)
                # Should use env defaults, not crash
                assert len(out) == 4

    def test_search_with_rerank_integration(self, mock_client):
        """search(rerank=True) calls llm_rerank and returns re-scored results."""
        from unittest.mock import patch as _patch
        results = [
            {"content": "auth flow", "score": 0.70, "entity_id": "m1",
             "entity_type": "memory", "workspace_id": "ws-1"},
            {"content": "pizza recipe", "score": 0.60, "entity_id": "m2",
             "entity_type": "memory", "workspace_id": "ws-1"},
        ]
        mock_client._sql.return_value = results
        mock_client._embed.return_value = [0.1] * 384

        with _patch("spacetime_memory.client.llm_rerank") as mock_rerank:
            mock_rerank.return_value = results
            out = mock_client.search("ws-1", "auth", rerank=True,
                                     rerank_endpoint="http://mock/v1",
                                     rerank_model="test",
                                     rerank_api_key="sk-test")
            mock_rerank.assert_called_once()
            call_args = mock_rerank.call_args
            assert call_args[0][0] == "auth"  # query
            assert call_args[1]["endpoint"] == "http://mock/v1"

    def test_search_without_rerank_skips(self, mock_client):
        """search(rerank=False) does not call llm_rerank."""
        from unittest.mock import patch as _patch
        results = [
            {"content": "test", "score": 0.80, "entity_id": "m1",
             "entity_type": "memory", "workspace_id": "ws-1"},
        ]
        mock_client._sql.return_value = results
        mock_client._embed.return_value = [0.1] * 384

        with _patch("spacetime_memory.client.llm_rerank") as mock_rerank:
            out = mock_client.search("ws-1", "test", rerank=False)
            mock_rerank.assert_not_called()
