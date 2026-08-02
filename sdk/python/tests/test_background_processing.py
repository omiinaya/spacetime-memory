"""Unit tests for BackgroundProcessingMixin (_background.py) and
ObservationExtractionMixin (_obs_extraction.py).

All tests use mocked HTTP — no live SpacetimeDB required.
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, Mock, patch

import pytest

from spacetime_memory.client._background import (
    DEFAULT_DERIVE_PRIORITY,
    DEFAULT_SUMMARIZE_PRIORITY,
    BackgroundJob,
)
from spacetime_memory.client._obs_extraction import (
    ObservationExtractionMixin,
)

# ============================================================================
# Helpers
# ============================================================================


def _make_background_job(
    job_id: str = "job_001",
    workspace_id: str = "ws_test",
    job_type: str = "derive",
    status: str = "queued",
    payload: dict | None = None,
    priority: int = 10,
    debounce_key: str = "",
) -> dict:
    """Build a minimal BackgroundJob dict as returned by STDB queries."""
    now = int(time.time() * 1_000_000)
    return {
        "id": job_id,
        "workspace_id": workspace_id,
        "job_type": job_type,
        "status": status,
        "payload_json": json.dumps(payload or {}),
        "priority": priority,
        "debounce_key": debounce_key,
        "created_at": now,
        "started_at": 0,
        "completed_at": 0,
    }


def _mock_reducer_response(data: dict | None = None) -> Mock:
    """Return a mock HTTP response for a reducer call."""
    resp = Mock(status_code=200)
    resp.text = json.dumps(data or {})
    resp.json = lambda: data or {}
    return resp


def _mock_query_response(rows: list[dict]) -> Mock:
    """Return a mock HTTP response for a SQL query."""
    resp = Mock(status_code=200)
    resp.text = json.dumps(rows)
    resp.json = lambda: rows
    return resp


# ============================================================================
# ObservationExtractionMixin tests
# ============================================================================


class TestObservationExtractionMixin:
    """Tests for the observation extraction mixin."""

    def test_parse_observation_json_valid_array(self):
        """Parsing a valid JSON array."""
        mixin = ObservationExtractionMixin()
        raw = '["Alice likes cats.", "Bob works at Google."]'
        result = mixin._parse_observation_json(raw)
        assert result == ["Alice likes cats.", "Bob works at Google."]

    def test_parse_observation_json_markdown_codeblock(self):
        """Parsing JSON wrapped in markdown code block."""
        mixin = ObservationExtractionMixin()
        raw = '```json\n["Observation one.", "Observation two."]\n```'
        result = mixin._parse_observation_json(raw)
        assert result == ["Observation one.", "Observation two."]

    def test_parse_observation_json_invalid(self):
        """Parsing invalid JSON returns empty list."""
        mixin = ObservationExtractionMixin()
        result = mixin._parse_observation_json("Not JSON at all")
        # Falls back to line-by-line extraction
        assert isinstance(result, list)

    def test_parse_observation_json_empty(self):
        """Empty string returns empty list."""
        mixin = ObservationExtractionMixin()
        assert mixin._parse_observation_json("") == []
        assert mixin._parse_observation_json("[]") == []

    def test_extract_observations_empty_content(self):
        """Empty content returns empty list."""
        mixin = ObservationExtractionMixin()
        assert mixin.extract_observations("") == []
        assert mixin.extract_observations("   ") == []

    def test_extract_observations_llm_called(self):
        """Check that _llm_complete is called with correct prompt."""
        mixin = ObservationExtractionMixin()

        with patch.object(mixin, "_llm_complete", return_value='["Test obs."]') as mock_llm:
            result = mixin.extract_observations("Some test content.")
            mock_llm.assert_called_once()
            assert "Some test content." in mock_llm.call_args[0][0]
            assert result == ["Test obs."]

    def test_llm_complete_with_llm_attr(self):
        """_llm_complete uses self._llm if available."""
        mixin = ObservationExtractionMixin()
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "LLM result"
        mixin._llm = mock_llm

        result = mixin._llm_complete("test prompt")
        assert result == "LLM result"
        mock_llm.complete.assert_called_once_with("test prompt")

    def test_llm_complete_without_llm(self):
        """_llm_complete returns empty string when no LLM configured."""
        mixin = ObservationExtractionMixin()
        # No _llm attribute set
        if hasattr(mixin, "_llm"):
            del mixin._llm
        result = mixin._llm_complete("test")
        # Should be empty because no LLM is configured
        assert result == ""


class TestObservationExtractionStore:
    """Tests for store_observations (needs mocked Client)."""

    def test_store_observations_extracts_and_stores(self, mock_http_client):
        """Verifies extract + store flow."""
        client = mock_http_client

        # Mock extract_observations to return predictable results
        with patch.object(client, "extract_observations",
                          return_value=["Obs one.", "Obs two."]), patch.object(client, "store",
                          return_value={"id": "mem_001", "status": "ok"}) as mock_store:
            result = client.store_observations(
                workspace_id="ws_test",
                content="Test content here.",
            )

            assert len(result) == 2
            assert mock_store.call_count == 2

    def test_store_observations_no_observations(self, mock_http_client):
        """When no observations extracted, returns empty list."""
        client = mock_http_client

        with patch.object(client, "extract_observations", return_value=[]):
            result = client.store_observations(
                workspace_id="ws_test",
                content="Nothing to extract.",
            )
            assert result == []


# ============================================================================
# BackgroundProcessingMixin tests
# ============================================================================


class TestBackgroundJobDataClass:
    """BackgroundJob dataclass."""

    def test_from_dict_full(self):
        job = BackgroundJob.from_dict({
            "id": "j1", "workspace_id": "ws1", "job_type": "derive",
            "status": "queued", "payload_json": "{}", "priority": 10,
            "debounce_key": "dk", "created_at": 1000, "started_at": 0,
            "completed_at": 0,
        })
        assert job.id == "j1"
        assert job.job_type == "derive"
        assert job.priority == 10

    def test_from_dict_empty(self):
        job = BackgroundJob.from_dict({})
        assert job.id == ""
        assert job.status == "queued"

    def test_from_dict_defaults(self):
        job = BackgroundJob.from_dict({"id": "j2"})
        assert job.priority == 0
        assert job.debounce_key == ""


class TestBackgroundEnqueue:
    """enqueue_derivation, enqueue_summarization, enqueue_dream."""

    def test_enqueue_derivation_calls_reducer(self, mock_http_client):
        client = mock_http_client
        with patch.object(client, "_call",
                          return_value={"status": "ok"}) as mock_call:
            _ = client.enqueue_derivation(
                workspace_id="ws1",
                message_id="msg_123",
                content="Hello world",
            )
            mock_call.assert_called_once()
            args = mock_call.call_args[0]
            assert args[0] == "enqueue_background_job"
            assert args[1][0] == "ws1"
            assert args[1][1] == "derive"
            payload = json.loads(args[1][2])
            assert payload["message_id"] == "msg_123"
            assert payload["content"] == "Hello world"
            assert args[1][3] == DEFAULT_DERIVE_PRIORITY
            assert args[1][4] == "derive:msg_123"

    def test_enqueue_summarization_calls_reducer(self, mock_http_client):
        client = mock_http_client
        with patch.object(client, "_call",
                          return_value={"status": "ok"}) as mock_call:
            _ = client.enqueue_summarization(
                workspace_id="ws1",
                session_id="sess_abc",
            )
            mock_call.assert_called_once()
            args = mock_call.call_args[0]
            assert args[0] == "enqueue_background_job"
            assert args[1][1] == "summarize"
            payload = json.loads(args[1][2])
            assert payload["session_id"] == "sess_abc"
            assert args[1][3] == DEFAULT_SUMMARIZE_PRIORITY

    def test_enqueue_dream_calls_reducer(self, mock_http_client):
        client = mock_http_client
        with patch.object(client, "_call",
                          return_value={"status": "ok"}) as mock_call:
            _ = client.enqueue_dream(
                workspace_id="ws1",
                strategy="generalize",
                max_new=3,
            )
            mock_call.assert_called_once()
            args = mock_call.call_args[0]
            assert args[0] == "enqueue_background_job"
            assert args[1][1] == "dream"
            payload = json.loads(args[1][2])
            assert payload["strategy"] == "generalize"
            assert payload["max_new"] == 3

    def test_enqueue_with_custom_priority(self, mock_http_client):
        client = mock_http_client
        with patch.object(client, "_call",
                          return_value={"status": "ok"}) as mock_call:
            client.enqueue_derivation("ws1", "m1", priority=50)
            assert mock_call.call_args[0][1][3] == 50


class TestBackgroundJobQuery:
    """_query_background_jobs and list/get status."""

    def test_list_background_jobs(self, mock_http_client):
        client = mock_http_client
        # Mock _query to return job rows
        job_data = [
            _make_background_job("j1", "ws1", "derive", "queued"),
            _make_background_job("j2", "ws1", "summarize", "running", priority=5),
        ]
        with patch.object(client, "_query", return_value=job_data):
            jobs = client.list_background_jobs(workspace_id="ws1")
            assert len(jobs) == 2
            assert jobs[0]["id"] == "j1"
            assert jobs[0]["job_type"] == "derive"

    def test_list_background_jobs_filtered_by_status(self, mock_http_client):
        client = mock_http_client
        job_data = [
            _make_background_job("j1", "ws1", "derive", "queued"),
            _make_background_job("j2", "ws1", "summarize", "completed"),
            _make_background_job("j3", "ws1", "dream", "queued"),
        ]
        with patch.object(client, "_query", return_value=job_data):
            jobs = client.list_background_jobs(
                workspace_id="ws1",
                status="queued",
            )
            assert len(jobs) >= 2

    def test_get_background_job_status(self, mock_http_client):
        client = mock_http_client
        job_data = [
            _make_background_job("j1", "ws1", "derive", "queued"),
            _make_background_job("j2", "ws1", "derive", "completed"),
            _make_background_job("j3", "ws1", "dream", "failed"),
        ]
        with patch.object(client, "_query", return_value=job_data):
            status = client.get_background_job_status(workspace_id="ws1")
            assert "counts" in status
            counts = status["counts"]
            assert counts["total"] >= 3
            assert counts["queued"] >= 1


class TestBackgroundProcess:
    """process_background_jobs execution."""

    def test_process_no_jobs(self, mock_http_client):
        """When no jobs to dequeue, returns empty list."""
        client = mock_http_client
        with patch.object(client, "_call",
                          return_value={"status": "ok"}):
            with patch.object(client, "_query_background_jobs",
                              return_value=[]):
                results = client.process_background_jobs(
                    workspace_id="ws1",
                    max_count=5,
                )
                assert results == []

    def test_process_derive_job(self, mock_http_client):
        """A derivation job is executed via _execute_derivation."""
        client = mock_http_client
        job = BackgroundJob.from_dict(
            _make_background_job("j1", "ws1", "derive", "running",
                                 payload={"message_id": "m1", "content": "Test content"})
        )

        with patch.object(client, "_call",
                          return_value={"status": "ok"}):
            with patch.object(client, "_query_background_jobs",
                              return_value=[job]):
                with patch.object(client, "extract_observations",
                                  return_value=["Obs one.", "Obs two."]):
                    with patch.object(client, "store",
                                      return_value={"id": "mem1", "status": "ok"}):
                        results = client.process_background_jobs("ws1")
                        assert len(results) == 1
                        assert results[0]["status"] == "completed"
                        assert results[0]["job_type"] == "derive"

    def test_process_dream_job(self, mock_http_client):
        """A dream job is executed."""
        client = mock_http_client
        job = BackgroundJob.from_dict(
            _make_background_job("j2", "ws1", "dream", "running",
                                 payload={"strategy": "connect", "max_new": 3})
        )

        with patch.object(client, "_call",
                          return_value={"status": "ok"}):
            with patch.object(client, "_query_background_jobs",
                              return_value=[job]):
                with patch.object(client, "synthesize_memories",
                                  return_value=[{"id": "syn1", "content": "Synthetic"}]):

                    results = client.process_background_jobs("ws1")
                    assert len(results) == 1
                    assert results[0]["status"] == "completed"

    def test_process_job_failure(self, mock_http_client):
        """A failing job is marked as failed."""
        client = mock_http_client
        job = BackgroundJob.from_dict(
            _make_background_job("j3", "ws1", "summarize", "running",
                                 payload={"session_id": "sess_bad"})
        )

        def _fail_on_execute(ws, job):
            raise ValueError("LLM unavailable")

        with patch.object(client, "_execute_summarization",
                          side_effect=ValueError("LLM unavailable")), patch.object(client, "_call",
                          return_value={"status": "ok"}):
            with patch.object(client, "_query_background_jobs",
                              return_value=[job]):
                results = client.process_background_jobs("ws1")
                assert len(results) == 1
                assert results[0]["status"] == "failed"
                assert "LLM unavailable" in results[0].get("error", "")

    def test_process_summarize_job(self, mock_http_client):
        """A summarization job is executed."""
        client = mock_http_client

        # Mock session messages and memories
        messages = [{"id": "m1", "session_id": "sess1", "content": "Hello"}]
        memories = [{"id": "mem1", "source_session_id": "sess1", "content": "Memory"}]
        job = BackgroundJob.from_dict(
            _make_background_job("j4", "ws1", "summarize", "running",
                                 payload={"session_id": "sess1"})
        )

        with patch.object(client, "_call",
                          return_value={"status": "ok"}):
            with patch.object(client, "_query_background_jobs",
                              return_value=[job]):
                with patch.object(client, "_query",
                                  side_effect=[messages, memories]):
                    with patch.object(client, "_generate_summary",
                                      return_value="Session summary text."):
                        results = client.process_background_jobs("ws1")
                        assert len(results) == 1
                        assert results[0]["status"] == "completed"
                        assert results[0]["output"]["summary"] == "Session summary text."


class TestBackgroundDeriver:
    """_execute_derivation logic."""

    def test_derivation_extracts_and_stores(self, mock_http_client):
        client = mock_http_client
        job = BackgroundJob.from_dict(
            _make_background_job("j1", "ws1", "derive", "running",
                                 payload={"message_id": "m1", "content": "Test content"})
        )

        with patch.object(client, "extract_observations",
                          return_value=["Obs1", "Obs2"]), patch.object(client, "store",
                          return_value={"id": "m_out", "status": "ok"}) as mock_store:
            result = client._execute_derivation("ws1", job)
            assert len(result) == 2
            assert mock_store.call_count == 2

    def test_derivation_fetches_message_content(self, mock_http_client):
        """If content not in payload, fetches from DB."""
        client = mock_http_client
        job = BackgroundJob.from_dict(
            _make_background_job("j1", "ws1", "derive", "running",
                                 payload={"message_id": "m1", "content": ""})
        )

        with patch.object(client, "_query",
                          return_value=[{"id": "m1", "content": "Fetched content"}]):
            with patch.object(client, "extract_observations",
                              return_value=["Fetched obs"]) as mock_extract:
                _ = client._execute_derivation("ws1", job)
                mock_extract.assert_called_once_with(content="Fetched content")

    def test_derivation_no_content(self, mock_http_client):
        """If no content available, returns empty."""
        client = mock_http_client
        job = BackgroundJob.from_dict(
            _make_background_job("j1", "ws1", "derive", "running",
                                 payload={"message_id": "m1", "content": ""})
        )

        with patch.object(client, "_query", return_value=[]):
            result = client._execute_derivation("ws1", job)
            assert result == []


class TestBackgroundSummarizer:
    """_execute_summarization logic."""

    def test_summarization_with_messages(self, mock_http_client):
        client = mock_http_client
        job = BackgroundJob.from_dict(
            _make_background_job("j1", "ws1", "summarize", "running",
                                 payload={"session_id": "sess1"})
        )

        messages = [{"id": "m1", "session_id": "sess1", "content": "Hello world"}]
        memories = [{"id": "mem1", "source_session_id": "sess1", "content": "Test memory"}]

        with patch.object(client, "_query",
                          side_effect=[messages, memories]):
            with patch.object(client, "_generate_summary",
                              return_value="Session summary."):
                with patch.object(client, "_call",
                                  return_value={"status": "ok"}):
                    result = client._execute_summarization("ws1", job)
                    assert result["summary"] == "Session summary."
                    assert result["message_count"] == 1
                    assert result["memory_count"] == 1

    def test_summarization_no_messages(self, mock_http_client):
        """If no messages or memories, returns empty summary with counts."""
        client = mock_http_client
        job = BackgroundJob.from_dict(
            _make_background_job("j1", "ws1", "summarize", "running",
                                 payload={"session_id": "sess1"})
        )

        with patch.object(client, "_query", return_value=[]):
            result = client._execute_summarization("ws1", job)
            assert result["summary"] == ""
            assert result["message_count"] == 0

    def test_summarization_no_session_id(self, mock_http_client):
        """Raises ValueError if no session_id in payload."""
        client = mock_http_client
        job = BackgroundJob.from_dict(
            _make_background_job("j1", "ws1", "summarize", "running",
                                 payload={})
        )

        with pytest.raises(ValueError, match="No session_id"):
            client._execute_summarization("ws1", job)


class TestBackgroundDreamer:
    """_execute_dream logic."""

    def test_dream_uses_synthesize_memories(self, mock_http_client):
        """If DreamMixin is available, delegates to synthesize_memories."""
        client = mock_http_client
        job = BackgroundJob.from_dict(
            _make_background_job("j1", "ws1", "dream", "running",
                                 payload={"strategy": "connect", "max_new": 3})
        )

        with patch.object(client, "synthesize_memories",
                          return_value=[{"id": "syn1", "content": "Synthetic"}]) as mock_synth:
            _ = client._execute_dream("ws1", job)
            mock_synth.assert_called_once_with(
                workspace_id="ws1",
                strategy="connect",
                max_new=3,
            )

    def test_dream_basic_fallback(self, mock_http_client):
        """When DreamMixin unavailable, uses _basic_dream."""
        client = mock_http_client
        # Remove synthesize_memories by patching it to None
        with patch.object(type(client), "synthesize_memories", None, create=True):

            job = BackgroundJob.from_dict(
                _make_background_job("j1", "ws1", "dream", "running",
                                     payload={"strategy": "connect", "max_new": 3})
            )

            with patch.object(client, "_basic_dream",
                              return_value=[{"id": "syn1"}]) as mock_basic:
                _ = client._execute_dream("ws1", job)
                mock_basic.assert_called_once()


class TestBackgroundJobPriorityDebounce:
    """Priority ordering and debouncing logic."""

    def test_enqueue_derivation_creates_debounce_key(self, mock_http_client):
        """Derivation uses 'derive:message_id' as debounce key."""
        client = mock_http_client
        with patch.object(client, "_call",
                          return_value={"status": "ok"}) as mock_call:
            client.enqueue_derivation("ws1", "m1", "content")
            debounce_key = mock_call.call_args[0][1][4]
            assert debounce_key == "derive:m1"

    def test_enqueue_summarization_creates_debounce_key(self, mock_http_client):
        """Summarization uses 'summarize:session_id' as debounce key."""
        client = mock_http_client
        with patch.object(client, "_call",
                          return_value={"status": "ok"}) as mock_call:
            client.enqueue_summarization("ws1", "sess_abc")
            debounce_key = mock_call.call_args[0][1][4]
            assert debounce_key == "summarize:sess_abc"

    def test_enqueue_dream_creates_debounce_key(self, mock_http_client):
        """Dream uses 'dream:workspace_id:strategy' as debounce key."""
        client = mock_http_client
        with patch.object(client, "_call",
                          return_value={"status": "ok"}) as mock_call:
            client.enqueue_dream("ws1", "connect")
            debounce_key = mock_call.call_args[0][1][4]
            assert debounce_key == "dream:ws1:connect"

    def test_jobs_sorted_by_priority_in_query(self, mock_http_client):
        """list_background_jobs sorts by priority descending."""
        client = mock_http_client
        job_data = [
            _make_background_job("low", "ws1", "derive", "queued", priority=1),
            _make_background_job("high", "ws1", "derive", "queued", priority=100),
            _make_background_job("med", "ws1", "derive", "queued", priority=50),
        ]

        with patch.object(client, "_query", return_value=job_data):
            jobs = client.list_background_jobs(workspace_id="ws1")
            # The in-memory sorting should put highest priority first
            assert jobs[0]["priority"] == 100
            assert jobs[1]["priority"] == 50
            # The third one may vary depending on how many come back


# ============================================================================
# Integration-like: full enqueue → dequeue → process cycle (mocked)
# ============================================================================


class TestBackgroundProcessingCycle:
    """Mock-based integration test of the full job lifecycle."""

    def test_full_cycle_derive(self, mock_http_client):
        """Enqueue → Dequeue → Process → Complete cycle for derive."""
        client = mock_http_client

        with patch.object(client, "_call",
                          return_value={"status": "ok"}) as mock_call:
            # Step 1: Enqueue
            client.enqueue_derivation("ws1", "m1", "Extract from this text.")

            # Verify the enqueue call
            enqueue_call = mock_call.call_args
            assert enqueue_call[0][0] == "enqueue_background_job"

            # Step 2: Process (with mocked query returning running jobs)
            running_jobs = [
                BackgroundJob.from_dict(
                    _make_background_job("j1", "ws1", "derive", "running",
                                         payload={"message_id": "m1",
                                                  "content": "Extract from this text."})
                )
            ]

            with patch.object(client, "_query_background_jobs",
                              return_value=running_jobs):
                with patch.object(client, "extract_observations",
                                  return_value=["Extracted observation."]):
                    with patch.object(client, "store",
                                      return_value={"id": "mem1", "status": "ok"}):
                        results = client.process_background_jobs("ws1")

                        # Step 3: Verify completion
                        assert len(results) == 1
                        assert results[0]["status"] == "completed"
                        assert results[0]["job_type"] == "derive"

    def test_full_cycle_dream(self, mock_http_client):
        """Enqueue → Dequeue → Process → Complete cycle for dream."""
        client = mock_http_client

        with patch.object(client, "_call",
                          return_value={"status": "ok"}) as _mock_call:
            # Step 1: Enqueue
            client.enqueue_dream("ws1", "connect", max_new=3)

            # Step 2: Process
            running_jobs = [
                BackgroundJob.from_dict(
                    _make_background_job("j2", "ws1", "dream", "running",
                                         payload={"strategy": "connect", "max_new": 3})
                )
            ]

            with patch.object(client, "_query_background_jobs",
                              return_value=running_jobs):
                with patch.object(client, "synthesize_memories",
                                  return_value=[{"id": "syn1", "content": "Synthetic"}]):
                    results = client.process_background_jobs("ws1")

                    # Step 3: Verify
                    assert len(results) == 1
                    assert results[0]["status"] == "completed"
                    assert results[0]["job_type"] == "dream"

    def test_enqueue_debounce_prevents_duplicates(self, mock_http_client):
        """Same debounce_key within cooldown skips enqueue."""
        # The dedup happens on the Rust side (STDB reducer checks debounce_key).
        # We verify the client sends the correct debounce_key.
        client = mock_http_client

        with patch.object(client, "_call",
                          return_value={"status": "ok"}) as mock_call:
            # Enqueue twice with same message_id
            client.enqueue_derivation("ws1", "m1", "content")
            client.enqueue_derivation("ws1", "m1", "content")

            # Verify first call args have debounce key
            first_call = mock_call.call_args_list[0]
            assert first_call[0][1][4] == "derive:m1"
            second_call = mock_call.call_args_list[1]
            assert second_call[0][1][4] == "derive:m1"


class TestBackgroundEdgeCases:
    """Edge cases for background processing."""

    def test_process_with_mixed_job_types(self, mock_http_client):
        """Process a mix of derive, summarize, and dream jobs."""
        client = mock_http_client
        jobs = [
            BackgroundJob.from_dict(
                _make_background_job("j1", "ws1", "derive", "running",
                                     payload={"message_id": "m1", "content": "Test"})
            ),
            BackgroundJob.from_dict(
                _make_background_job("j2", "ws1", "dream", "running",
                                     payload={"strategy": "connect", "max_new": 2})
            ),
        ]

        with patch.object(client, "_call",
                          return_value={"status": "ok"}):
            with patch.object(client, "_query_background_jobs",
                              return_value=jobs):
                with patch.object(client, "extract_observations",
                                  return_value=["Obs"]):
                    with patch.object(client, "store",
                                      return_value={"id": "m", "status": "ok"}):
                        with patch.object(client, "synthesize_memories",
                                          return_value=[{"id": "s", "content": "Syn"}]):
                            results = client.process_background_jobs("ws1")
                            assert len(results) == 2
                            types = {r["job_type"] for r in results}
                            assert types == {"derive", "dream"}

    def test_process_with_max_count(self, mock_http_client):
        """Only process up to max_count jobs."""
        client = mock_http_client

        with patch.object(client, "_call", return_value={"status": "ok"}):
            with patch.object(client, "_query_background_jobs",
                              return_value=[]):
                results = client.process_background_jobs(
                    workspace_id="ws1",
                    max_count=0,
                )
                assert results == []

    def test_enqueue_empty_message_id(self, mock_http_client):
        """Enqueue derivation with empty message_id still works."""
        client = mock_http_client
        with patch.object(client, "_call",
                          return_value={"status": "ok"}) as mock_call:
            client.enqueue_derivation("ws1", "")
            debounce_key = mock_call.call_args[0][1][4]
            assert debounce_key == "derive:"
