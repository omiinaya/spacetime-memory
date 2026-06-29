"""Pytest tests for shmr_resonate() and _call_client_llm() in shmr.py.

Mocks the Client (MagicMock) and httpx to cover the full resonance flow.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from spacetime_memory.shmr import (
    ResonanceResult,
    _call_client_llm,
    shmr_resonate,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_client():
    """A MagicMock with the interface expected by shmr_resonate()."""
    client = MagicMock()
    client._call.return_value = {"status": "ok"}
    return client


@pytest.fixture
def sample_memories():
    """Return a list of memory dicts as client.search() would."""
    return [
        {
            "entity_id": "mem-1",
            "content": "The user prefers Python over JavaScript",
            "memory_type": "fact",
            "trust_score": 0.9,
            "created_at": 1719000000,
        },
        {
            "entity_id": "mem-2",
            "content": "Python is great for data science",
            "memory_type": "observation",
            "trust_score": 0.8,
            "created_at": 1719000100,
        },
    ]


@pytest.fixture
def sample_embedding():
    """A sample embedding vector."""
    return [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]


@pytest.fixture
def sample_llm_response():
    """A valid LLM harmonization JSON response."""
    return json.dumps(
        [
            {
                "subject": "User",
                "predicate": "prefers",
                "object": "Python for data science",
                "confidence": 0.9,
                "action": "create",
                "source_memory_ids": ["mem-1", "mem-2"],
                "rationale": "Both memories corroborate Python preference",
            },
            {
                "subject": "User",
                "predicate": "dislikes",
                "object": "JavaScript verbosity",
                "confidence": 0.6,
                "action": "dampen",
                "source_memory_ids": ["mem-1"],
                "rationale": "Implicit from preference contrast",
            },
        ]
    )


# ── Tests: _call_client_llm ────────────────────────────────────────────────


class TestCallClientLLM:
    """Tests for _call_client_llm() — the LLM API caller via httpx."""

    def test_no_api_key_returns_none(self, mock_client):
        """When OPENAI_API_KEY is not set, returns None."""
        with patch.dict(os.environ, {}, clear=True):
            result = _call_client_llm(mock_client, "test prompt")
            assert result is None

    def test_empty_api_key_returns_none(self, mock_client):
        """When OPENAI_API_KEY is empty string, returns None."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=True):
            result = _call_client_llm(mock_client, "test prompt")
            assert result is None

    def test_successful_llm_call(self, mock_client):
        """A successful httpx POST returns the content string."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"result": "harmonized"}'}}],
        }

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-test",
                "OPENAI_BASE_URL": "https://api.example.com/v1",
            },
            clear=True,
        ):
            with patch("httpx.post", return_value=mock_response) as mock_post:
                result = _call_client_llm(mock_client, "harmonize these memories")
                assert result == '{"result": "harmonized"}'
                mock_post.assert_called_once()
                # Verify the URL includes /chat/completions
                call_args = mock_post.call_args[0]
                assert "/chat/completions" in call_args[0]

    def test_connect_error_returns_none(self, mock_client):
        """httpx.ConnectError is caught and returns None."""
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            with patch(
                "httpx.post",
                side_effect=httpx.ConnectError("connection refused"),
            ):
                result = _call_client_llm(mock_client, "test")
                assert result is None

    def test_timeout_returns_none(self, mock_client):
        """httpx.TimeoutException is caught and returns None."""
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            with patch(
                "httpx.post",
                side_effect=httpx.TimeoutException("timed out"),
            ):
                result = _call_client_llm(mock_client, "test")
                assert result is None

    def test_remote_protocol_error_returns_none(self, mock_client):
        """httpx.RemoteProtocolError is caught and returns None."""
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            with patch(
                "httpx.post",
                side_effect=httpx.RemoteProtocolError("protocol error"),
            ):
                result = _call_client_llm(mock_client, "test")
                assert result is None

    def test_http_error_raises(self, mock_client):
        """Non-caught HTTP errors propagate (e.g., HTTPStatusError)."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Server Error", request=MagicMock(), response=MagicMock(status_code=500)
        )

        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            with patch("httpx.post", return_value=mock_response):
                with pytest.raises(httpx.HTTPStatusError):
                    _call_client_llm(mock_client, "test")

    def test_uses_shmr_model_env_var(self, mock_client):
        """When SHMR_MODEL is set on the module, it overrides the default model."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
        }

        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            with patch("spacetime_memory.shmr.SHMR_MODEL", "custom-shmr-model"):
                with patch("httpx.post", return_value=mock_response) as mock_post:
                    _call_client_llm(mock_client, "test")
                    call_kwargs = mock_post.call_args[1]
                    assert call_kwargs["json"]["model"] == "custom-shmr-model"

    def test_llm_model_fallback(self, mock_client):
        """When STMEM_SHMR_MODEL is unset, uses LLM_MODEL or default."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
        }

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-test",
                "LLM_MODEL": "gpt-4",
            },
            clear=True,
        ):
            with patch("httpx.post", return_value=mock_response) as mock_post:
                _call_client_llm(mock_client, "test")
                call_kwargs = mock_post.call_args[1]
                assert call_kwargs["json"]["model"] == "gpt-4"

    def test_base_url_strip_trailing_slash(self, mock_client):
        """The base_url has trailing slashes stripped before use."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
        }

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-test",
                "OPENAI_BASE_URL": "https://api.example.com/v1///",
            },
            clear=True,
        ):
            with patch("httpx.post", return_value=mock_response) as mock_post:
                _call_client_llm(mock_client, "test")
                call_args = mock_post.call_args[0]
                assert call_args[0] == "https://api.example.com/v1/chat/completions"

    def test_temperature_and_max_tokens_sent(self, mock_client):
        """The request includes temperature and max_tokens."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
        }

        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            with patch("httpx.post", return_value=mock_response) as mock_post:
                _call_client_llm(mock_client, "test")
                call_kwargs = mock_post.call_args[1]
                assert call_kwargs["json"]["temperature"] == 0.2
                assert call_kwargs["json"]["max_tokens"] == 2048


# ── Tests: shmr_resonate ───────────────────────────────────────────────────


class TestShmrResonate:
    """Tests for shmr_resonate() — the main resonance engine function."""

    def test_empty_memories_early_return(self, mock_client):
        """When client.search() returns no memories, return early."""
        mock_client.search.return_value = []

        result = shmr_resonate(mock_client, workspace_id="ws-test")

        assert isinstance(result, ResonanceResult)
        assert result.workspace_id == "ws-test"
        assert result.clusters_found == 0
        assert result.beliefs_generated == 0
        assert result.errors == 0
        assert result.duration_ms >= 0

    def test_no_indexed_memories_early_return(self, mock_client):
        """When no memories have embeddings, return early."""
        mock_client.search.return_value = [
            {"entity_id": "m1", "content": "hello"},
            {"entity_id": "m2", "content": "world"},
        ]
        # _embed returns empty list for all
        mock_client._embed.return_value = []

        result = shmr_resonate(mock_client, workspace_id="ws-test")

        assert result.clusters_found == 0
        assert result.beliefs_generated == 0
        assert result.errors == 0

    def test_no_clusters_early_return(self, mock_client):
        """When indexed memories don't form clusters, return early."""
        mock_client.search.return_value = [
            {"entity_id": "m1", "content": "completely different topic A"},
            {"entity_id": "m2", "content": "completely different topic B"},
        ]
        # Make embeddings orthogonal → no clusters at default threshold
        mock_client._embed.side_effect = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ]

        result = shmr_resonate(mock_client, workspace_id="ws-test")

        assert result.clusters_found == 0
        assert result.beliefs_generated == 0
        assert result.errors == 0
        assert result.duration_ms >= 0

    def test_dry_run_skips_llm_and_storage(self, mock_client):
        """dry_run=True should find clusters but skip LLM calls and storage."""
        mock_client.search.return_value = [
            {"entity_id": "m1", "content": "Python is great", "trust_score": 0.9},
            {"entity_id": "m2", "content": "I love Python programming", "trust_score": 0.8},
        ]
        mock_client._embed.side_effect = [
            [1.0, 0.1, 0.0],
            [0.95, 0.05, 0.0],
        ]

        result = shmr_resonate(mock_client, workspace_id="ws-dry", dry_run=True)

        # Should find 1 cluster with 2 items
        assert result.clusters_found == 1
        # dry_run estimates 3 beliefs per cluster
        assert result.beliefs_generated == 3
        assert result.errors == 0
        assert result.duration_ms >= 0

        # _call_client_llm should NOT have been invoked via any mechanism
        # _call should NOT have been called (no storage happens)
        assert mock_client._call.call_count == 0

    def test_successful_resonance_flow(self, mock_client, sample_llm_response):
        """Full happy path: search → embed → cluster → LLM → store → log."""
        mock_client.search.return_value = [
            {"entity_id": "mem-1", "content": "User likes Python", "trust_score": 0.9},
            {
                "entity_id": "mem-2",
                "content": "Python is great for data science",
                "trust_score": 0.8,
            },
        ]
        mock_client._embed.side_effect = [
            [1.0, 0.1, 0.0],
            [0.95, 0.05, 0.0],
        ]

        # Mock _call_client_llm via patching the module function
        with patch(
            "spacetime_memory.shmr._call_client_llm",
            return_value=sample_llm_response,
        ) as mock_llm:
            result = shmr_resonate(mock_client, workspace_id="ws-success")

        assert result.clusters_found == 1
        assert result.beliefs_generated == 2  # 2 beliefs in sample_llm_response
        assert result.contradictions_resolved == 1  # 1 dampen action
        assert result.errors == 0
        assert result.harmony_score_avg > 0
        assert result.duration_ms >= 0

        # LLM was called once
        mock_llm.assert_called_once()

        # Check _call was used for store_harmonic_beliefs
        store_calls = [
            c for c in mock_client._call.call_args_list if c[0][0] == "store_harmonic_beliefs"
        ]
        assert len(store_calls) == 1

        # Check log_resonance_session was called
        log_calls = [
            c for c in mock_client._call.call_args_list if c[0][0] == "log_resonance_session"
        ]
        assert len(log_calls) == 1

    def test_llm_call_failure_increments_errors(self, mock_client):
        """When LLM call raises an exception, error count increases."""
        mock_client.search.return_value = [
            {"entity_id": "m1", "content": "Python is great", "trust_score": 0.9},
            {"entity_id": "m2", "content": "I love Python programming", "trust_score": 0.8},
        ]
        mock_client._embed.side_effect = [
            [1.0, 0.1, 0.0],
            [0.95, 0.05, 0.0],
        ]

        with patch(
            "spacetime_memory.shmr._call_client_llm",
            side_effect=RuntimeError("LLM failure"),
        ):
            result = shmr_resonate(mock_client, workspace_id="ws-error")

        assert result.clusters_found == 1
        assert result.beliefs_generated == 0
        assert result.errors == 1
        assert result.duration_ms >= 0

    def test_llm_returns_none_skips_cluster(self, mock_client):
        """When LLM returns None, cluster is skipped without error."""
        mock_client.search.return_value = [
            {"entity_id": "m1", "content": "Python is great", "trust_score": 0.9},
            {"entity_id": "m2", "content": "I love Python", "trust_score": 0.8},
        ]
        mock_client._embed.side_effect = [
            [1.0, 0.1, 0.0],
            [0.95, 0.05, 0.0],
        ]

        with patch(
            "spacetime_memory.shmr._call_client_llm",
            return_value=None,
        ):
            result = shmr_resonate(mock_client, workspace_id="ws-none")

        assert result.clusters_found == 1
        assert result.beliefs_generated == 0
        assert result.errors == 0

    def test_empty_json_from_llm_skips_cluster(self, mock_client):
        """When LLM returns unparseable text (empty beliefs), cluster is skipped."""
        mock_client.search.return_value = [
            {"entity_id": "m1", "content": "Python is great", "trust_score": 0.9},
            {"entity_id": "m2", "content": "I love Python", "trust_score": 0.8},
        ]
        mock_client._embed.side_effect = [
            [1.0, 0.1, 0.0],
            [0.95, 0.05, 0.0],
        ]

        with patch(
            "spacetime_memory.shmr._call_client_llm",
            return_value="this is not json at all",
        ):
            result = shmr_resonate(mock_client, workspace_id="ws-empty")

        assert result.clusters_found == 1
        assert result.beliefs_generated == 0
        assert result.errors == 0

    def test_store_failure_increments_errors(self, mock_client):
        """When client._call('store_harmonic_beliefs') raises, error is counted."""
        mock_client.search.return_value = [
            {"entity_id": "m1", "content": "Python is great", "trust_score": 0.9},
            {"entity_id": "m2", "content": "I love Python programming", "trust_score": 0.8},
        ]
        mock_client._embed.side_effect = [
            [1.0, 0.1, 0.0],
            [0.95, 0.05, 0.0],
        ]

        # Make store fail
        def _call_side_effect(reducer, args):
            if reducer == "store_harmonic_beliefs":
                raise RuntimeError("store failed")
            return {"status": "ok"}

        mock_client._call.side_effect = _call_side_effect

        with patch(
            "spacetime_memory.shmr._call_client_llm",
            return_value=json.dumps(
                [{"subject": "X", "predicate": "Y", "confidence": 0.9, "action": "create"}]
            ),
        ):
            result = shmr_resonate(mock_client, workspace_id="ws-storefail")

        assert result.clusters_found == 1
        assert result.errors == 1  # store failed

    def test_log_resonance_session_failure_is_swallowed(self, mock_client):
        """When log_resonance_session fails, the error is silently caught."""
        mock_client.search.return_value = [
            {"entity_id": "m1", "content": "Python is great", "trust_score": 0.9},
            {"entity_id": "m2", "content": "I love Python programming", "trust_score": 0.8},
        ]
        mock_client._embed.side_effect = [
            [1.0, 0.1, 0.0],
            [0.95, 0.05, 0.0],
        ]

        call_count = [0]

        def _call_side_effect(reducer, args):
            call_count[0] += 1
            if reducer == "log_resonance_session":
                raise RuntimeError("log failed")
            return {"status": "ok"}

        mock_client._call.side_effect = _call_side_effect

        with patch(
            "spacetime_memory.shmr._call_client_llm",
            return_value=json.dumps(
                [{"subject": "X", "predicate": "Y", "confidence": 0.9, "action": "create"}]
            ),
        ):
            result = shmr_resonate(mock_client, workspace_id="ws-logfail")

        # Should still succeed — log failure is swallowed
        assert result.clusters_found == 1
        assert result.beliefs_generated == 1
        assert result.errors == 0  # log failure is not counted as error

    def test_no_log_when_no_clusters(self, mock_client):
        """When no clusters are found, log_resonance_session is not called."""
        mock_client.search.return_value = []

        shmr_resonate(mock_client, workspace_id="ws-empty")

        log_calls = [
            c for c in mock_client._call.call_args_list if c[0][0] == "log_resonance_session"
        ]
        assert len(log_calls) == 0

    def test_multiple_clusters_all_harmonized(self, mock_client, sample_llm_response):
        """Multiple clusters each get harmonized."""
        mock_client.search.return_value = [
            # Cluster 1: Python
            {"entity_id": "m1", "content": "Python is great", "trust_score": 0.9},
            {"entity_id": "m2", "content": "I love Python", "trust_score": 0.8},
            # Cluster 2: JavaScript (orthogonal to Python)
            {"entity_id": "m3", "content": "JavaScript is verbose", "trust_score": 0.7},
            {"entity_id": "m4", "content": "JS has many quirks", "trust_score": 0.6},
        ]
        mock_client._embed.side_effect = [
            [1.0, 0.1],  # m1
            [0.95, 0.05],  # m2 (similar to m1)
            [0.0, 1.0],  # m3
            [0.0, 0.95],  # m4 (similar to m3)
        ]

        with patch(
            "spacetime_memory.shmr._call_client_llm",
            return_value=sample_llm_response,
        ):
            result = shmr_resonate(mock_client, workspace_id="ws-multi")

        assert result.clusters_found == 2
        assert result.beliefs_generated == 4  # 2 beliefs × 2 clusters
        assert result.contradictions_resolved == 2  # 1 dampen × 2 clusters
        assert result.harmony_score_avg > 0

    def test_dry_run_no_log_session(self, mock_client):
        """dry_run=True does not call log_resonance_session."""
        mock_client.search.return_value = [
            {"entity_id": "m1", "content": "Python is great", "trust_score": 0.9},
            {"entity_id": "m2", "content": "I love Python", "trust_score": 0.8},
        ]
        mock_client._embed.side_effect = [
            [1.0, 0.1, 0.0],
            [0.95, 0.05, 0.0],
        ]

        result = shmr_resonate(mock_client, workspace_id="ws-dry-log", dry_run=True)

        log_calls = [
            c for c in mock_client._call.call_args_list if c[0][0] == "log_resonance_session"
        ]
        assert len(log_calls) == 0
        assert result.clusters_found == 1

    def test_custom_threshold_and_iterations(self, mock_client):
        """Custom similarity_threshold and max_iterations are accepted."""
        mock_client.search.return_value = [
            {"entity_id": "m1", "content": "Python", "trust_score": 0.9},
            {"entity_id": "m2", "content": "Python programming", "trust_score": 0.8},
        ]
        mock_client._embed.side_effect = [
            [1.0, 0.0],
            [0.99, 0.01],
        ]

        with patch(
            "spacetime_memory.shmr._call_client_llm",
            return_value=json.dumps([{"subject": "X", "predicate": "Y", "confidence": 0.9}]),
        ):
            result = shmr_resonate(
                mock_client,
                workspace_id="ws-custom",
                days=14,
                max_iterations=5,
                similarity_threshold=0.95,
            )

        assert result.clusters_found >= 0
        assert result.errors == 0

    def test_memories_with_no_entity_id_still_work(self, mock_client):
        """Memories without entity_id are still harmonized."""
        mock_client.search.return_value = [
            {"content": "Python is great", "trust_score": 0.9},
            {"content": "I love Python", "trust_score": 0.8},
        ]
        mock_client._embed.side_effect = [
            [1.0, 0.1, 0.0],
            [0.95, 0.05, 0.0],
        ]

        with patch(
            "spacetime_memory.shmr._call_client_llm",
            return_value=json.dumps(
                [{"subject": "X", "predicate": "Y", "confidence": 0.9, "action": "create"}]
            ),
        ):
            result = shmr_resonate(mock_client, workspace_id="ws-noid")

        assert result.clusters_found == 1
        assert result.beliefs_generated == 1
        assert result.errors == 0

    def test_result_contains_duration_ms(self, mock_client):
        """The result always has a non-negative duration_ms."""
        mock_client.search.return_value = []

        result = shmr_resonate(mock_client, workspace_id="ws-dur")
        assert isinstance(result.duration_ms, int)
        assert result.duration_ms >= 0

    def test_harmony_score_avg_zero_when_no_beliefs(self, mock_client):
        """When no beliefs are generated, harmony_score_avg stays 0.0."""
        mock_client.search.return_value = []

        result = shmr_resonate(mock_client, workspace_id="ws-hzero")
        assert result.harmony_score_avg == 0.0


# ── Tests: Integration edge cases ──────────────────────────────────────────


class TestShmrResonateEdgeCases:
    """Additional edge case tests for shmr_resonate()."""

    def test_single_indexed_memory_no_cluster(self, mock_client):
        """Single indexed memory below SHMR_MIN_CLUSTER_SIZE yields no cluster."""
        mock_client.search.return_value = [
            {"entity_id": "m1", "content": "solitary memory", "trust_score": 0.5},
        ]
        mock_client._embed.return_value = [1.0, 0.1, 0.0]

        result = shmr_resonate(mock_client, workspace_id="ws-single")
        assert result.clusters_found == 0

    def test_some_embeddings_missing_some_present(self, mock_client):
        """Only memories with embeddings are indexed and clustered."""
        mock_client.search.return_value = [
            {"entity_id": "m1", "content": "A"},
            {"entity_id": "m2", "content": "B"},
            {"entity_id": "m3", "content": "C"},
        ]
        # Only m1 and m3 get embeddings; m2 returns empty
        mock_client._embed.side_effect = [
            [1.0, 0.0],  # m1
            [],  # m2 — no embedding
            [0.95, 0.0],  # m3
        ]

        result = shmr_resonate(mock_client, workspace_id="ws-mixed")

        # m1 and m3 are similar, should form 1 cluster
        assert result.clusters_found == 1

    def test_llm_error_and_store_error_same_run(self, mock_client):
        """Multiple errors in the same run are both counted."""
        mock_client.search.return_value = [
            {"entity_id": "m1", "content": "A", "trust_score": 0.9},
            {"entity_id": "m2", "content": "A similar", "trust_score": 0.8},
            {"entity_id": "m3", "content": "B", "trust_score": 0.7},
            {"entity_id": "m4", "content": "B similar", "trust_score": 0.6},
        ]
        mock_client._embed.side_effect = [
            [1.0, 0.1, 0.0],
            [0.95, 0.05, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.95, 0.0],
        ]

        # Cluster 0: LLM fails; Cluster 1: store fails
        llm_call_count = [0]

        def llm_side_effect(client, prompt):
            llm_call_count[0] += 1
            if llm_call_count[0] == 1:
                raise RuntimeError("LLM failed")
            return json.dumps(
                [{"subject": "X", "predicate": "Y", "confidence": 0.9, "action": "create"}]
            )

        def _call_side_effect(reducer, args):
            if reducer == "store_harmonic_beliefs":
                raise RuntimeError("store failed")
            return {"status": "ok"}

        mock_client._call.side_effect = _call_side_effect

        with patch(
            "spacetime_memory.shmr._call_client_llm",
            side_effect=llm_side_effect,
        ):
            result = shmr_resonate(mock_client, workspace_id="ws-mixed-err")

        assert result.clusters_found == 2
        assert result.errors == 2  # 1 LLM fail + 1 store fail
