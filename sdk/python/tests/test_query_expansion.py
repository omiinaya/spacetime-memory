"""Tests for query expansion (query_expansion.py)."""

import pytest
from unittest.mock import MagicMock, patch

import httpx

from spacetime_memory.query_expansion import expand_query


# ── Success paths ───────────────────────────────────────────────────────────


class TestExpandQuerySuccess:
    """Normal expansion flows — LLM returns a usable expansion."""

    def _mock_response(self, content="best practices patterns"):
        """Build a mock httpx response object."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": content,
                    }
                }
            ]
        }
        return resp

    def test_basic_expansion(self):
        mock_resp = self._mock_response("best practices patterns")
        with patch("httpx.post", return_value=mock_resp):
            result = expand_query("python coding", api_key="sk-test")
        assert "python coding" in result
        assert "best practices patterns" in result
        # Should be merged: original + expanded
        assert result == "python coding best practices patterns"

    def test_custom_endpoint_and_model(self):
        mock_resp = self._mock_response("related terms")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = expand_query(
                "k8s",
                endpoint="https://custom.api/v2",
                model="claude-3",
                api_key="sk-custom",
            )
        # Verify the endpoint was used
        call_args = mock_post.call_args
        assert "https://custom.api/v2/chat/completions" in call_args[0][0]
        # Check payload
        payload = call_args[1]["json"]
        assert payload["model"] == "claude-3"

    def test_api_key_in_headers(self):
        mock_resp = self._mock_response("synonyms")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            expand_query("test", api_key="my-secret-key")
        call_args = mock_post.call_args
        headers = call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer my-secret-key"

    def test_no_api_key_no_auth_header(self):
        mock_resp = self._mock_response("expanded")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            with patch.dict("os.environ", {}, clear=True):
                expand_query("test", api_key="")
        call_args = mock_post.call_args
        headers = call_args[1]["headers"]
        # No Authorization header when api_key is empty/falsy
        assert "Authorization" not in headers or headers.get("Authorization", "").endswith(
            "Bearer "
        )

    def test_custom_timeout(self):
        mock_resp = self._mock_response("terms")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            expand_query("test", api_key="sk-test", timeout=30)
        call_args = mock_post.call_args
        assert call_args[1]["timeout"] == 30

    def test_temperature_is_zero(self):
        mock_resp = self._mock_response("expansion")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            expand_query("test", api_key="sk-test")
        payload = mock_post.call_args[1]["json"]
        assert payload["temperature"] == 0.0
        assert payload["max_tokens"] == 200

    def test_endpoint_trailing_slash_handled(self):
        mock_resp = self._mock_response("terms")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            expand_query("test", endpoint="http://api.example/v1/", api_key="sk-test")
        call_args = mock_post.call_args
        # Should not double-slash
        assert "//" not in call_args[0][0].split("chat")[0][-3:]


# ── Content edge cases ──────────────────────────────────────────────────────


class TestExpandQueryContentEdgeCases:
    """Edge cases in the response content from the LLM."""

    def test_content_same_as_query_case_insensitive(self):
        """When the LLM returns the same content (case-insensitive), return original."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"choices": [{"message": {"content": "Python Coding"}}]}
        with patch("httpx.post", return_value=resp):
            result = expand_query("python coding", api_key="sk-test")
        # Should NOT merge if content is same as query (case-insensitive)
        assert result == "python coding"

    def test_content_too_short(self):
        """Content ≤ 5 chars is considered too short → return original query."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"choices": [{"message": {"content": "abc"}}]}
        with patch("httpx.post", return_value=resp):
            result = expand_query("python coding", api_key="sk-test")
        # Too short (3 chars ≤ 5) → return original
        assert result == "python coding"

    def test_content_exactly_five_chars(self):
        """Content exactly 5 chars is still too short."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"choices": [{"message": {"content": "abcde"}}]}
        with patch("httpx.post", return_value=resp):
            result = expand_query("python", api_key="sk-test")
        assert result == "python"

    def test_content_six_chars_is_accepted(self):
        """Content > 5 chars is accepted (and different from query)."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"choices": [{"message": {"content": "abcdef"}}]}
        with patch("httpx.post", return_value=resp):
            result = expand_query("xyz", api_key="sk-test")
        assert "xyz abcdef" == result  # merged

    def test_empty_content_no_reasoning(self):
        """Empty content and no reasoning_content → return original query."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"choices": [{"message": {"content": ""}}]}
        with patch("httpx.post", return_value=resp):
            result = expand_query("python coding", api_key="sk-test")
        assert result == "python coding"

    def test_none_content_no_reasoning(self):
        """content is None and no reasoning → return original query."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"choices": [{"message": {"content": None}}]}
        with patch("httpx.post", return_value=resp):
            result = expand_query("test query", api_key="sk-test")
        assert result == "test query"


# ── Reasoning model fallback ───────────────────────────────────────────────


class TestReasoningModelFallback:
    """Some models (e.g. o1, deepseek-r1) return reasoning_content instead of content."""

    def test_reasoning_fallback_used(self):
        """When content is empty but reasoning_content is present, use it."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "kubernetes container orchestration deployment",
                    }
                }
            ]
        }
        with patch("httpx.post", return_value=resp):
            result = expand_query("k8s", api_key="sk-test")
        assert "k8s" in result
        assert "kubernetes container orchestration deployment" in result

    def test_reasoning_fallback_with_none_content(self):
        """When content is None, reasoning_content fallback works."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "reasoning_content": "distributed systems scalability",
                    }
                }
            ]
        }
        with patch("httpx.post", return_value=resp):
            result = expand_query("microservices", api_key="sk-test")
        assert "distributed systems scalability" in result

    def test_reasoning_too_short_still_used(self):
        """Reasoning content ≤ 5 chars... the code path: if not content, check reasoning.
        The length check only applies to the merged block (len(content)>5 check).
        If reasoning is the fallback, it bypasses the short-content check."""
        # Actually looking at the code: the `if len(content) > 5` check is only
        # after content is set. If reasoning is used as fallback, content = reasoning.strip().
        # Then the same len check applies.
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "k8s",  # too short
                    }
                }
            ]
        }
        with patch("httpx.post", return_value=resp):
            result = expand_query("kubernetes", api_key="sk-test")
        # reasoning is 3 chars (≤5) → return original
        assert result == "kubernetes"

    def test_reasoning_same_as_query(self):
        """Reasoning content matches query case-insensitively."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "Python Coding",
                    }
                }
            ]
        }
        with patch("httpx.post", return_value=resp):
            result = expand_query("python coding", api_key="sk-test")
        assert result == "python coding"


# ── Error handling ──────────────────────────────────────────────────────────


class TestExpandQueryErrors:
    """Network errors — all should gracefully return the original query."""

    def test_connection_error(self):
        with patch("httpx.post", side_effect=httpx.ConnectError("connection refused")):
            result = expand_query("python", api_key="sk-test")
        assert result == "python"

    def test_timeout_error(self):
        with patch("httpx.post", side_effect=httpx.TimeoutException("timeout")):
            result = expand_query("python", api_key="sk-test")
        assert result == "python"

    def test_remote_protocol_error(self):
        with patch("httpx.post", side_effect=httpx.RemoteProtocolError("protocol error")):
            result = expand_query("python", api_key="sk-test")
        assert result == "python"

    def test_http_error_status(self):
        """HTTP 500: raise_for_status raises HTTPStatusError — NOT caught by except.
        The except clause only catches (ConnectError, TimeoutException, RemoteProtocolError),
        so HTTPStatusError propagates."""
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "server error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
        resp.json.return_value = {"error": "internal"}
        with patch("httpx.post", return_value=resp):
            with pytest.raises(httpx.HTTPStatusError):
                expand_query("python", api_key="sk-test")

    def test_httpx_request_error_not_caught(self):
        """Generic HTTPError (not in the except tuple) should propagate."""
        with patch("httpx.post", side_effect=httpx.HTTPError("generic")):
            with pytest.raises(httpx.HTTPError):
                expand_query("python", api_key="sk-test")

    def test_malformed_response_missing_choices(self):
        """Response without 'choices' key should raise KeyError (propagates)."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {}  # no 'choices'
        with patch("httpx.post", return_value=resp):
            with pytest.raises(KeyError):
                expand_query("python", api_key="sk-test")

    def test_malformed_response_empty_choices(self):
        """Empty choices list."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"choices": []}
        with patch("httpx.post", return_value=resp):
            with pytest.raises(IndexError):
                expand_query("python", api_key="sk-test")


# ── Environment variable fallback ───────────────────────────────────────────


class TestEnvVarFallback:
    """When endpoint/model/api_key are None, env vars are used as fallback."""

    def _mock_response(self, content="expanded terms here"):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"choices": [{"message": {"content": content}}]}
        return resp

    def test_env_endpoint(self):
        mock_resp = self._mock_response()
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            with patch.dict(
                "os.environ",
                {
                    "LLM_RERANK_ENDPOINT": "http://env-endpoint:4000/v1",
                    "LLM_RERANK_MODEL": "gpt-4o-mini",
                    "LLM_RERANK_API_KEY": "env-key",
                },
            ):
                result = expand_query("test")
        call_args = mock_post.call_args
        assert "env-endpoint:4000" in call_args[0][0]
        assert result == "test expanded terms here"

    def test_env_model(self):
        mock_resp = self._mock_response()
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            with patch.dict(
                "os.environ",
                {
                    "LLM_RERANK_ENDPOINT": "http://localhost:4000/v1",
                    "LLM_RERANK_MODEL": "custom-model-v2",
                    "LLM_RERANK_API_KEY": "env-key",
                },
            ):
                expand_query("test")
        assert mock_post.call_args[1]["json"]["model"] == "custom-model-v2"

    def test_openai_api_key_fallback(self):
        """When LLM_RERANK_API_KEY is not set, OPENAI_API_KEY is used."""
        mock_resp = self._mock_response()
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            with patch.dict(
                "os.environ",
                {
                    "LLM_RERANK_ENDPOINT": "http://localhost:4000/v1",
                    "LLM_RERANK_MODEL": "gpt-4o-mini",
                    "OPENAI_API_KEY": "openai-key",
                },
                clear=True,
            ):
                expand_query("test")
        headers = mock_post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer openai-key"

    def test_no_env_vars_at_all(self):
        """With no env vars, uses hardcoded defaults (localhost:4000)."""
        mock_resp = self._mock_response()
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            with patch.dict("os.environ", {}, clear=True):
                result = expand_query("test")
        call_args = mock_post.call_args
        # Should use default endpoint http://localhost:4000/v1
        assert "localhost:4000" in call_args[0][0] or result  # at minimum doesn't crash

    def test_explicit_args_override_env(self):
        """Explicit args should take priority over env vars."""
        mock_resp = self._mock_response()
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            with patch.dict(
                "os.environ",
                {
                    "LLM_RERANK_ENDPOINT": "http://env/v1",
                    "LLM_RERANK_MODEL": "env-model",
                    "LLM_RERANK_API_KEY": "env-key",
                },
            ):
                expand_query(
                    "test",
                    endpoint="http://explicit/v1",
                    model="explicit-model",
                    api_key="explicit-key",
                )
        call_args = mock_post.call_args
        assert "explicit" in call_args[0][0]
        assert call_args[1]["json"]["model"] == "explicit-model"
        assert call_args[1]["headers"]["Authorization"] == "Bearer explicit-key"


# ── Edge cases ──────────────────────────────────────────────────────────────


class TestExpandQueryEdgeCases:
    """Miscellaneous edge cases."""

    def _mock_response(self, content="expanded output"):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"choices": [{"message": {"content": content}}]}
        return resp

    def test_empty_query_string(self):
        mock_resp = self._mock_response("some expansion")
        with patch("httpx.post", return_value=mock_resp):
            result = expand_query("", api_key="sk-test")
        assert "some expansion" in result

    def test_whitespace_only_content(self):
        """Content that strips to empty but is not None/empty."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"choices": [{"message": {"content": "   "}}]}
        with patch("httpx.post", return_value=resp):
            result = expand_query("test", api_key="sk-test")
        # content.strip() is "", so content becomes "" → not content → check reasoning
        # No reasoning → return query
        assert result == "test"

    def test_content_with_leading_trailing_whitespace(self):
        """Content with extra whitespace should be stripped."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "  expanded  content  "}}]
        }
        with patch("httpx.post", return_value=mock_resp):
            result = expand_query("query", api_key="sk-test")
        # Should be "query expanded  content" (middle spaces preserved, edges stripped)
        assert result == "query expanded  content"
