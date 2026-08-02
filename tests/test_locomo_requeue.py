"""Regression tests for the LoCoMo checkpoint re-queue logic.

Covers the fix where judge/answerer errors (notably HTTP 402 free-tier
rate-limits) were recorded as is_correct=False and permanently skipped on
resume, silently deflating the benchmark score. The fix re-queues any result
whose judgment never genuinely happened.
"""
import sys
from pathlib import Path

import pytest

# Make run_locomo importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "benchmarks"))
import run_locomo
from run_locomo import judgment_failed, requeue_failed_judgments, search_stdb


def _result(q_idx_placeholder: int, *, reasoning: str = "", answer: str = "", is_correct: bool = False) -> dict:
    return {"conv": 0, "question": f"q{q_idx_placeholder}", "expected": "e",
            "answer": answer, "is_correct": is_correct, "reasoning": reasoning}


class TestJudgmentFailed:
    def test_http_402_judge_error(self):
        assert judgment_failed(_result(0, reasoning="api error: HTTP 402")) is True

    def test_other_judge_api_error(self):
        assert judgment_failed(_result(0, reasoning="api error: HTTP 500")) is True

    def test_system_error(self):
        assert judgment_failed(_result(0, reasoning="system error")) is True

    def test_answerer_error(self):
        assert judgment_failed(_result(0, answer="ERROR: proxy down", reasoning="")) is True

    def test_answer_contains_api_error(self):
        assert judgment_failed(_result(0, answer="api error occurred", reasoning="...")) is True

    def test_genuine_wrong_answer_not_failed(self):
        # A real wrong answer (judged correctly as wrong) must NOT be re-queued
        assert judgment_failed(_result(0, reasoning="The answer is missing the key fact",
                                       answer="some wrong text")) is False

    def test_correct_answer_not_failed(self):
        assert judgment_failed(_result(0, reasoning="Correctly identifies the fact",
                                       answer="right answer", is_correct=True)) is False

    def test_empty_judge_response_is_failed(self):
        # HTTP 200 with empty judge content was silently recorded as a wrong
        # answer. Must be treated as a failed judgment and re-queued.
        assert judgment_failed(_result(0, reasoning="", answer="basketball")) is True
        assert judgment_failed(_result(0, reasoning="   ", answer="a gorgeous forest")) is True

    def test_whitespace_only_reasoning_is_failed(self):
        assert judgment_failed(_result(0, reasoning="\n\t ", answer="x")) is True


class TestRequeueFailedJudgments:
    def test_requeues_only_failed(self):
        results = [
            _result(0, reasoning="Correct", is_correct=True),   # idx 0 - keep
            _result(1, reasoning="api error: HTTP 402"),          # idx 1 - requeue
            _result(2, reasoning="genuine wrong"),                # idx 2 - keep
        ]
        kept, kept_idx, fail_idx = requeue_failed_judgments(results, {0, 1, 2})
        assert kept_idx == {0, 2}
        assert fail_idx == [1]
        assert [r["question"] for r in kept] == ["q0", "q2"]

    def test_all_clean_keeps_everything(self):
        results = [_result(i, reasoning="ok", is_correct=(i % 2 == 0)) for i in range(5)]
        kept, kept_idx, fail_idx = requeue_failed_judgments(results, set(range(5)))
        assert kept_idx == set(range(5))
        assert fail_idx == []
        assert len(kept) == 5

    def test_index_mapping_preserved_under_gaps(self):
        # completed_indices may have gaps (question 1 never completed)
        results = [
            _result(0, reasoning="Correct", is_correct=True),   # q_idx 0
            _result(2, reasoning="api error: HTTP 402"),         # q_idx 2
            _result(3, reasoning="Correct", is_correct=True),    # q_idx 3
        ]
        kept, kept_idx, fail_idx = requeue_failed_judgments(results, {0, 2, 3})
        assert kept_idx == {0, 3}
        assert fail_idx == [2]
        assert [r["question"] for r in kept] == ["q0", "q3"]

    def test_empty_input(self):
        kept, kept_idx, fail_idx = requeue_failed_judgments([], set())
        assert kept == [] and kept_idx == set() and fail_idx == []


class TestLlmJudgeEmptyRetry:
    """The judge LLM returning an empty (HTTP 200, no content) response must
    be retried and, if still empty, marked as a judge error — never silently
    recorded as is_correct=False."""

    def _fake_llm(self, monkeypatch, responses):
        calls = {"n": 0}

        def fake_call(body, extra_params=None):
            calls["n"] += 1
            # If a response is a string, treat as content; if dict, it's a raw error payload
            if isinstance(responses[calls["n"] - 1], str):
                return {"choices": [{"message": {"content": responses[calls["n"] - 1]}}]}
            return responses[calls["n"] - 1]

        monkeypatch.setattr(run_locomo, "_llm_call", fake_call)
        return calls

    def test_empty_then_valid_retries(self, monkeypatch):
        calls = self._fake_llm(monkeypatch, ["", "", '{"label": "CORRECT", "reasoning": "matches"}'])
        result = run_locomo.llm_judge("q", "expected", "answer text")
        assert result["is_correct"] is True
        assert calls["n"] == 3  # two empty retries, then a real judgment

    def test_all_empty_marks_as_judge_error(self, monkeypatch):
        calls = self._fake_llm(monkeypatch, ["", "", ""])
        result = run_locomo.llm_judge("q", "expected", "answer")
        assert result["is_correct"] is False
        assert "empty response" in result["reasoning"]
        assert calls["n"] == 3  # consumed all empty retries
        # And critically, this result IS flagged for re-queue on the next resume
        assert judgment_failed(result) is True

    def test_judge_error_exception_flags_as_failed(self):
        # llm_judge exception path ("judge error: ...") must also re-queue
        assert judgment_failed(_result(0, reasoning="judge error: connection reset")) is True


class TestSearchStdbCircuitBreakerResilience:
    """The SDK raises RuntimeError('SpacetimeDB circuit breaker is open')
    under concurrent overload. search_stdb must back off and retry instead of
    letting the transient overload crash the whole benchmark run (this was a
    live crash that killed the self-heal launcher)."""

    class _FakeClient:
        def __init__(self, failures_before_success):
            self.failures_before_success = failures_before_success
            self.calls = 0
        def search(self, workspace_id, question, limit=200, semantic=True):
            self.calls += 1
            if self.calls <= self.failures_before_success:
                raise RuntimeError("SpacetimeDB circuit breaker is open (retry in 20s). "
                                   "Circuit resets at STMEM_CIRCUIT_RESET_SECS=30.0.")
            return [{"id": "r1"}]

    def test_retries_through_circuit_breaker(self, monkeypatch):
        client = self._FakeClient(failures_before_success=2)
        monkeypatch.setattr(run_locomo, "time", _FakeTime())
        result = search_stdb(client, "ws", "q")
        assert result == [{"id": "r1"}]
        assert client.calls == 3  # 2 breaker trips + 1 success

    def test_non_breaker_runtime_error_propagates(self, monkeypatch):
        class BadClient:
            def search(self, *a, **k):
                raise RuntimeError("some other failure")
        monkeypatch.setattr(run_locomo, "time", _FakeTime())
        import pytest
        with pytest.raises(RuntimeError, match="some other failure"):
            search_stdb(BadClient(), "ws", "q")

    def test_breaker_stays_open_raises_after_retries(self, monkeypatch):
        class AlwaysOpen:
            def search(self, *a, **k):
                raise RuntimeError("SpacetimeDB circuit breaker is open (retry in 1s).")
        monkeypatch.setattr(run_locomo, "time", _FakeTime())
        import pytest
        with pytest.raises(RuntimeError, match="stayed open"):
            search_stdb(AlwaysOpen(), "ws", "q")

    def test_retries_through_http_500(self, monkeypatch):
        """STDB HTTP 500 ('Request failed after N attempts: Server error
        (HTTP 500)') is a transient overload signal, same class as the circuit
        breaker — search_stdb must back off and retry, not crash the run."""
        class Flaky500:
            def __init__(self, failures_before_success):
                self.failures_before_success = failures_before_success
                self.calls = 0
            def search(self, workspace_id, question, limit=200, semantic=True):
                self.calls += 1
                if self.calls <= self.failures_before_success:
                    raise RuntimeError(
                        "Request failed after 4 attempts: Server error (HTTP 500) on "
                        "http://127.0.0.1:3001/v1/database/spacetime-memory-v2/call/"
                        "check_workspace_access\n  → Is SpacetimeDB running? Check: stmem doctor"
                    )
                return [{"id": "r1"}]
        client = Flaky500(failures_before_success=2)
        monkeypatch.setattr(run_locomo, "time", _FakeTime())
        result = search_stdb(client, "ws", "q")
        assert result == [{"id": "r1"}]
        assert client.calls == 3

    def test_http_500_stays_down_raises_after_retries(self, monkeypatch):
        class Always500:
            def search(self, *a, **k):
                raise RuntimeError("Request failed after 4 attempts: Server error (HTTP 500)")
        monkeypatch.setattr(run_locomo, "time", _FakeTime())
        import pytest
        with pytest.raises(RuntimeError, match="stayed open"):
            search_stdb(Always500(), "ws", "q")


class _FakeTime:
    """Fake time module whose sleep() is instant (keeps the test fast)."""
    def sleep(self, *a): pass
    def __getattr__(self, name): return getattr(__import__("time"), name)