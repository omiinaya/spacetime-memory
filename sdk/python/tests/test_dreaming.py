"""Unit tests for DreamMixin (_dreaming.py).

Tests the dreaming / synthetic memory operations using a mocked
Client so no real SpacetimeDB is needed.
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, Mock

import httpx
import pytest

from spacetime_memory.client._dreaming import (
    DREAM_LOG_MEMORY_TYPE,
    SYNTHETIC_MEMORY_TYPE,
    _compute_memory_age_days,
    _compute_memory_strength,
    _extract_tokens,
    _jaccard_similarity,
    _linear_decay,
    _make_snippet,
    _weibull_decay,
)

# ============================================================================
# Helpers
# ============================================================================


def _make_memory(
    memory_id: str,
    workspace_id: str = "ws_dream",
    content: str = "Alice likes cats and enjoys reading science fiction",
    confidence: float = 0.8,
    memory_type: str = "experience",
    created_at: int | None = None,
    embedding: str = "",
) -> dict:
    """Build a minimal memory dict for testing."""
    now = int(time.time() * 1_000_000)
    return {
        "id": memory_id,
        "workspace_id": workspace_id,
        "memory_type": memory_type,
        "content": content,
        "summary": content[:80],
        "confidence": confidence,
        "entities_json": "{}",
        "created_at": created_at or (now - 86400 * 1_000_000),
        "updated_at": (created_at or now) + 1000,
        "embedding": embedding,
        "is_active": True,
    }


def _reducer_resp() -> Mock:
    """Return a mock response for a successful reducer call (200 + empty body)."""
    resp = Mock(status_code=200)
    resp.text = "{}"
    resp.json = dict
    return resp


def _store_result(memory_id: str) -> Mock:
    """Return a mock response for a successful store call."""
    resp = Mock(status_code=200)
    resp.text = json.dumps({"status": "ok", "id": memory_id})
    resp.json = lambda: {"status": "ok", "id": memory_id}
    return resp


# ============================================================================
# Pure-function tests
# ============================================================================


class TestDecayFunctions:
    def test_weibull_immediate(self):
        """At t=0, strength should be 1.0."""
        assert _weibull_decay(0, 0.6, 30.0) == 1.0

    def test_weibull_monotonic(self):
        """Weibull decay is monotonically decreasing."""
        strengths = [_weibull_decay(d, 0.6, 30.0) for d in [0, 1, 10, 30, 90]]
        for i in range(len(strengths) - 1):
            assert strengths[i] >= strengths[i + 1]

    def test_weibull_at_scale(self):
        """At t=scale, strength should be exp(-1)."""
        expected = 1.0 / 2.71828  # approx 1/e
        actual = _weibull_decay(30.0, 1.0, 30.0)
        assert abs(actual - expected) < 0.01

    def test_linear_immediate(self):
        """At t=0, strength should be 1.0."""
        assert _linear_decay(0, 0.005, 90) == 1.0

    def test_linear_decay_rate(self):
        """After 1 day, strength should be 1 - decay_rate."""
        assert abs(_linear_decay(1, 0.005, 90) - 0.995) < 1e-9

    def test_linear_hits_floor(self):
        """After enough days, strength hits zero."""
        # decay_rate = 0.01, so after 100 days: 1.0 - 0.01*100 = 0.0
        assert _linear_decay(100, 0.01, 150) == 0.0

    def test_linear_past_max(self):
        """Beyond zero, strength stays at 0.0."""
        assert _linear_decay(200, 0.01, 150) == 0.0


class TestMemoryAge:
    def test_zero_age_for_new(self):
        """A memory with no timestamp should return 0 age."""
        mem = _make_memory("m1", created_at=int(time.time() * 1_000_000))
        age = _compute_memory_age_days(mem)
        assert 0 <= age < 0.01  # Effectively zero

    def test_positive_age(self):
        """A memory created 2 days ago should report ~2 days."""
        now = int(time.time() * 1_000_000)
        two_days_ago = now - 2 * 86400 * 1_000_000
        mem = _make_memory("m1", created_at=two_days_ago)
        age = _compute_memory_age_days(mem)
        assert 1.5 < age < 2.5

    def test_no_timestamp_fallback(self):
        """Memory without created_at should not crash, return >= 0."""
        mem = {"id": "m1", "content": "test"}
        age = _compute_memory_age_days(mem)
        assert age >= 0.0


class TestMemoryStrength:
    def test_strength_upper_bound(self):
        """Strength should never exceed 1.0."""
        mem = _make_memory("m1", confidence=0.9, created_at=int(time.time() * 1_000_000))
        s = _compute_memory_strength(mem, model="weibull")
        assert 0.0 <= s <= 1.0

    def test_strength_decreases_with_age(self):
        """Older memory should have lower or equal strength."""
        now = int(time.time() * 1_000_000)
        young = _make_memory("m1", created_at=now - 1 * 86400 * 1_000_000)
        old = _make_memory("m2", created_at=now - 30 * 86400 * 1_000_000)
        s_young = _compute_memory_strength(young)
        s_old = _compute_memory_strength(old)
        assert s_young >= s_old

    def test_strength_with_string_confidence(self):
        """Should handle string-encoded confidence gracefully."""
        mem = _make_memory("m1", confidence=0.8)
        mem["confidence"] = "0.9"
        s = _compute_memory_strength(mem)
        assert s > 0.0


class TestTokenHelpers:
    def test_extract_tokens(self):
        """Should extract meaningful tokens from text."""
        tokens = _extract_tokens("Alice likes cats and dogs")
        assert "alice" in tokens
        assert "cats" in tokens
        assert "likes" in tokens
        assert "and" not in tokens  # Stopword

    def test_extract_tokens_empty(self):
        """Empty text returns empty set."""
        assert _extract_tokens("") == set()

    def test_jaccard_same(self):
        """Identical token sets have Jaccard = 1.0."""
        assert _jaccard_similarity({"a", "b", "c"}, {"a", "b", "c"}) == 1.0

    def test_jaccard_disjoint(self):
        """Disjoint sets have Jaccard = 0.0."""
        assert _jaccard_similarity({"a", "b"}, {"c", "d"}) == 0.0

    def test_jaccard_partial(self):
        """Partially overlapping sets."""
        sim = _jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"})
        # intersection = {b, c} = 2, union = {a, b, c, d} = 4, sim = 0.5
        assert abs(sim - 0.5) < 1e-9

    def test_jaccard_both_empty(self):
        """Both empty returns 0.0."""
        assert _jaccard_similarity(set(), set()) == 0.0


class TestMakeSnippet:
    def test_short_text(self):
        """Text shorter than max_chars passes through."""
        assert _make_snippet("hello world") == "hello world"

    def test_long_text_truncated(self):
        """Long text gets truncated with ellipsis."""
        long = "word " * 50
        result = _make_snippet(long, max_chars=30)
        assert len(result) <= 35
        assert result.endswith("...")

    def test_empty_text(self):
        """Empty text returns empty string."""
        assert _make_snippet("") == ""


# ============================================================================
# DreamMixin tests (mocked HTTP client)
# ============================================================================


@pytest.fixture
def dream_client():
    """Create a DreamMixin with mocked HTTP."""
    from spacetime_memory import Client

    client = Client(
        host="localhost",
        port="3001",
        database="test-db",
        embedder_url="http://localhost:9090",
    )
    mock_http = MagicMock(spec=httpx.Client)

    def _post_side_effect(url, *args, **kwargs):
        url_str = str(url)
        # Reducer calls (/call/...) — return {"status": "ok"}
        if "/call/" in url_str:
            return _store_result("mock_id")
        # Embedder calls
        if ":9090" in url_str or "/embed" in url_str.lower():
            return Mock(
                status_code=200,
                text=json.dumps({"data": [{"embedding": [0.0]}]}),
                json=lambda: {"data": [{"embedding": [0.0]}]},
            )
        # Tantivy / BM25 sidecar
        if ":9091" in url_str or "tantivy" in url_str.lower():
            return Mock(
                status_code=200,
                text=json.dumps([]),
                json=list,
            )
        # Default: SQL or other — return empty SQL result array
        return Mock(
            status_code=200,
            text=json.dumps([]),
            json=lambda: {"result": json.dumps([])},
        )

    mock_http.post.side_effect = _post_side_effect
    mock_http.get.return_value = Mock(
        status_code=200,
        json=lambda: {"model": "mock"},
    )
    client._http = mock_http
    return client


class TestSynthesizeMemories:
    def test_synthesize_empty_workspace(self, dream_client):
        """No memories in workspace returns empty list."""
        # mock returns empty list for _query
        result = dream_client.synthesize_memories("ws_empty", strategy="connect")
        assert result == []

    def test_synthesize_invalid_strategy(self, dream_client):
        """Invalid strategy raises ValueError."""
        with pytest.raises(ValueError, match="Unknown strategy"):
            dream_client.synthesize_memories("ws1", strategy="unknown")

    def test_synthesize_connect_finds_connections(self, dream_client):
        """Connect strategy finds pairs with moderate token overlap."""
        # We need to make the _query return multiple memories
        mem1 = _make_memory("m1", content="Alice loves science fiction books")
        mem2 = _make_memory("m2", content="Bob reads fantasy novels and science fiction")
        mem3 = _make_memory("m3", content="The weather today is sunny and warm")

        dream_client._query = MagicMock(return_value=[mem1, mem2, mem3])
        dream_client._http.post.return_value = _store_result("synth_1")

        result = dream_client.synthesize_memories(
            "ws1", strategy="connect", max_new=3
        )
        # Should find at least one connection (mem1 & mem2 share "science fiction")
        assert len(result) >= 1
        assert result[0]["strategy"] == "connect"
        assert len(result[0]["source_memory_ids"]) >= 2

    def test_synthesize_generalize_finds_patterns(self, dream_client):
        """Generalize strategy finds common patterns across 3+ memories."""
        mems = [
            _make_memory("m1", content="Alice likes cats and feeds them daily"),
            _make_memory("m2", content="Bob has cats and feeds them every morning"),
            _make_memory("m3", content="Carol feeds cats and plays with them"),
            _make_memory("m4", content="The stock market went up today"),
        ]
        dream_client._query = MagicMock(return_value=mems)
        dream_client._http.post.return_value = _store_result("synth_g1")

        result = dream_client.synthesize_memories(
            "ws1", strategy="generalize", max_new=3
        )
        # Should find at least one generalization about cats/feeding
        assert len(result) >= 1
        assert result[0]["strategy"] == "generalize"

    def test_synthesize_fill_gaps(self, dream_client):
        """Fill-gaps strategy infers connections."""
        mems = [
            _make_memory("m1", content="Alice works at Acme Corp")
                | {"entities_json": json.dumps({"user": "alice", "org": "acme"})},
            _make_memory("m2", content="Bob works at Acme Corp too")
                | {"entities_json": json.dumps({"user": "bob", "org": "acme"})},
        ]
        dream_client._query = MagicMock(return_value=mems)
        dream_client._http.post.return_value = _store_result("synth_f1")

        result = dream_client.synthesize_memories(
            "ws1", strategy="fill_gaps", max_new=3
        )
        assert len(result) >= 1
        assert result[0]["strategy"] == "fill_gaps"

    def test_synthesize_contrast(self, dream_client):
        """Contrast strategy finds conflicting perspectives."""
        mems = [
            _make_memory("m1", content="The new policy is excellent for everyone involved"),
            _make_memory("m2", content="The new policy has serious drawbacks for many people"),
        ]
        dream_client._query = MagicMock(return_value=mems)
        dream_client._http.post.return_value = _store_result("synth_c1")

        result = dream_client.synthesize_memories(
            "ws1", strategy="contrast", max_new=3
        )
        assert len(result) >= 1
        assert result[0]["strategy"] == "contrast"

    def test_synthesize_all_strategies(self, dream_client):
        """'all' strategy runs all applicable strategies."""
        mems = [
            _make_memory("m1", content="Alice loves science fiction books about space travel")
                | {"entities_json": json.dumps({"user": "alice"})},
            _make_memory("m2", content="Bob reads science fiction about alien civilizations")
                | {"entities_json": json.dumps({"user": "bob"})},
            _make_memory("m3", content="Carol enjoys classic literature from the 19th century")
                | {"entities_json": json.dumps({"user": "carol"})},
            _make_memory("m4", content="Alice also likes fantasy novels with dragons")
                | {"entities_json": json.dumps({"user": "alice"})},
            _make_memory("m5", content="The solar eclipse will be visible next Tuesday"),
        ]
        dream_client._query = MagicMock(return_value=mems)
        dream_client._http.post.return_value = _store_result("synth_1")

        result = dream_client.synthesize_memories(
            "ws1", strategy="all", max_new=4
        )
        assert len(result) <= 4
        assert len(result) > 0

    def test_synthesize_with_source_ids(self, dream_client):
        """Can pass specific source memory IDs."""
        mems = [
            _make_memory("m1", content="Alice loves cats"),
            _make_memory("m2", content="Bob loves dogs"),
        ]
        dream_client._query = MagicMock(side_effect=lambda table, **kw: (
            [mems[0]] if kw.get("filter_dict", {}).get("id") == "m1"
            else [mems[1]] if kw.get("filter_dict", {}).get("id") == "m2"
            else []
        ))
        dream_client._http.post.return_value = _store_result("synth_s1")

        result = dream_client.synthesize_memories(
            "ws1", source_ids=["m1", "m2"], strategy="connect", max_new=3
        )
        # May or may not find a connection, but should not crash
        assert isinstance(result, list)

    def test_synthesize_no_connections_returns_empty(self, dream_client):
        """Completely unrelated memories return empty for 'connect'."""
        mems = [
            _make_memory("m1", content="Quantum physics equations"),
            _make_memory("m2", content="French cuisine recipes"),
        ]
        dream_client._query = MagicMock(return_value=mems)

        result = dream_client.synthesize_memories(
            "ws1", strategy="connect", max_new=3
        )
        assert result == []  # No overlap -> no connection


class TestGetDreamLog:
    def test_get_dream_log_returns_list(self, dream_client):
        """get_dream_log returns list of dream entries."""
        dream_client._query = MagicMock(return_value=[])
        result = dream_client.get_dream_log("ws1")
        assert isinstance(result, list)

    def test_get_dream_log_parses_content(self, dream_client):
        """Dream log entries have parsed content fields."""
        now = int(time.time() * 1_000_000)
        entries = [{
            "id": "dream_1",
            "workspace_id": "ws1",
            "memory_type": DREAM_LOG_MEMORY_TYPE,
            "content": json.dumps({
                "strategy": "connect",
                "generated_id": "synth_1",
                "source_ids": ["m1", "m2"],
                "summary": "test summary",
                "timestamp": 1000,
            }),
            "summary": "test summary",
            "created_at": now,
        }]
        dream_client._query = MagicMock(return_value=entries)

        result = dream_client.get_dream_log("ws1")
        assert len(result) == 1
        assert result[0]["strategy"] == "connect"
        assert result[0]["generated_id"] == "synth_1"

    def test_get_dream_log_sorted_newest_first(self, dream_client):
        """Entries are sorted newest first."""
        entries = [
            {
                "id": "dream_1",
                "workspace_id": "ws1",
                "memory_type": DREAM_LOG_MEMORY_TYPE,
                "content": "{}",
                "summary": "old",
                "created_at": 1000,
            },
            {
                "id": "dream_2",
                "workspace_id": "ws1",
                "memory_type": DREAM_LOG_MEMORY_TYPE,
                "content": "{}",
                "summary": "new",
                "created_at": 2000,
            },
        ]
        dream_client._query = MagicMock(return_value=entries)
        result = dream_client.get_dream_log("ws1")
        assert result[0]["id"] == "dream_2"


class TestRunDreamCycle:
    def test_run_dream_cycle_default_strategies(self, dream_client):
        """Runs with default strategies."""
        mems = [
            _make_memory("m1", content="Alice loves science fiction and cats"),
            _make_memory("m2", content="Bob reads science fiction and has a cat"),
        ]
        dream_client._query = MagicMock(return_value=mems)
        dream_client._http.post.return_value = _store_result("synth_1")

        result = dream_client.run_dream_cycle("ws1")
        assert "results" in result
        assert result["total_generated"] >= 0
        assert "strategies_run" in result
        assert "timestamp" in result

    def test_run_dream_cycle_custom_strategies(self, dream_client):
        """Can pass custom strategies."""
        dream_client._query = MagicMock(return_value=[
            _make_memory("m1", content="Test content one"),
            _make_memory("m2", content="Test content two"),
        ])
        dream_client._http.post.return_value = _store_result("synth_1")

        result = dream_client.run_dream_cycle(
            "ws1", strategies=["connect"], max_new=3
        )
        assert "results" in result
        assert result["strategies_run"] == ["connect"]

    def test_run_dream_cycle_empty_workspace(self, dream_client):
        """Empty workspace returns empty results."""
        dream_client._query = MagicMock(return_value=[])
        result = dream_client.run_dream_cycle("ws1")
        assert result["total_generated"] == 0
        assert result["results"] == []


class TestScheduleDreaming:
    def test_schedule_dreaming_returns_config(self, dream_client):
        """Schedule returns config dict with timing info."""
        dream_client._http.post.return_value = _store_result("schedule_1")
        result = dream_client.schedule_dreaming("ws1", interval_hours=24)
        assert result["interval_hours"] == 24
        assert result["strategies"] == ["connect"]
        assert result["enabled"] is True
        assert "next_run" in result

    def test_schedule_dreaming_custom_strategies(self, dream_client):
        """Can pass custom strategies."""
        dream_client._http.post.return_value = _store_result("schedule_2")
        result = dream_client.schedule_dreaming(
            "ws1",
            interval_hours=12,
            strategies=["connect", "generalize", "contrast"],
        )
        assert result["interval_hours"] == 12
        assert result["strategies"] == ["connect", "generalize", "contrast"]

    def test_schedule_dreaming_computes_next_run(self, dream_client):
        """next_run is computed from now + interval."""
        dream_client._http.post.return_value = _store_result("schedule_3")
        before = int(time.time())
        result = dream_client.schedule_dreaming("ws1", interval_hours=48)
        assert result["next_run"] >= before + 47 * 3600


class TestGetForgettingCurve:
    def test_get_forgetting_curve_empty(self, dream_client):
        """No memories returns empty list."""
        dream_client._query = MagicMock(return_value=[])
        result = dream_client.get_forgetting_curve("ws1")
        assert result == []

    def test_get_forgetting_curve_has_curve_data(self, dream_client):
        """Returns curve data with daily projections."""
        mem = _make_memory("m1", confidence=0.9)
        dream_client._query = MagicMock(return_value=[mem])
        result = dream_client.get_forgetting_curve("ws1")
        assert len(result) == 1
        assert "curve" in result[0]
        assert len(result[0]["curve"]) == 91  # 0..90 days
        assert "current_strength" in result[0]
        assert "age_days" in result[0]

    def test_get_forgetting_curve_specific_memory(self, dream_client):
        """Can query a specific memory ID."""
        mem = _make_memory("m_specific", confidence=0.8)
        dream_client._query = MagicMock(return_value=[mem])
        result = dream_client.get_forgetting_curve("ws1", memory_id="m_specific")
        assert len(result) == 1
        assert result[0]["memory_id"] == "m_specific"

    def test_forgetting_curve_monotonic(self, dream_client):
        """Strength in curve is monotonically decreasing."""
        mem = _make_memory("m1", confidence=1.0)
        dream_client._query = MagicMock(return_value=[mem])
        result = dream_client.get_forgetting_curve("ws1")
        strengths = [p["strength"] for p in result[0]["curve"]]
        for i in range(len(strengths) - 1):
            assert strengths[i] >= strengths[i + 1] - 1e-9


class TestSimulateCramming:
    def test_simulate_cramming_empty_ids(self, dream_client):
        """Empty memory_ids returns empty list."""
        result = dream_client.simulate_cramming("ws1", [], [1, 7, 30])
        assert result == []

    def test_simulate_cramming_returns_curves(self, dream_client):
        """Returns baseline and simulated curves."""
        mem = _make_memory("m1", confidence=0.8, content="Important fact to remember")
        dream_client._query = MagicMock(return_value=[mem])
        result = dream_client.simulate_cramming(
            "ws1", ["m1"], review_times=[1, 7, 30]
        )
        assert len(result) == 1
        assert "baseline_curve" in result[0]
        assert "simulated_curve" in result[0]
        assert "boost" in result[0]
        assert len(result[0]["baseline_curve"]) == 91
        assert len(result[0]["simulated_curve"]) == 91

    def test_cramming_boost_is_positive(self, dream_client):
        """With reviews, final strength should be >= baseline."""
        mem = _make_memory("m1", confidence=0.8)
        dream_client._query = MagicMock(return_value=[mem])
        result = dream_client.simulate_cramming(
            "ws1", ["m1"], review_times=[1, 3, 7, 14, 30]
        )
        assert result[0]["boost"] >= 0

    def test_cramming_no_review_times(self, dream_client):
        """Default review times used when none provided."""
        mem = _make_memory("m1", confidence=0.8)
        dream_client._query = MagicMock(return_value=[mem])
        result = dream_client.simulate_cramming("ws1", ["m1"], [])
        assert len(result) == 1
        assert len(result[0]["baseline_curve"]) == 91


class TestCalculateMemoryHealth:
    def test_health_empty_workspace(self, dream_client):
        """Empty workspace returns zeroed health."""
        dream_client._query = MagicMock(return_value=[])
        health = dream_client.calculate_memory_health("ws1")
        assert health["total_memories"] == 0
        assert health["health_score"] == 0.0

    def test_health_has_all_keys(self, dream_client):
        """Health report has expected structure."""
        mem = _make_memory("m1", memory_type="experience")
        dream_client._query = MagicMock(return_value=[mem])
        health = dream_client.calculate_memory_health("ws1")
        expected_keys = {
            "total_memories", "active_memories", "synthetic_memories",
            "avg_age_days", "avg_strength", "strength_distribution",
            "freshness_score", "coverage_estimate", "health_score",
            "recommendations",
        }
        assert expected_keys.issubset(health.keys())

    def test_health_counts_synthetic(self, dream_client):
        """Synthetic memories are counted separately."""
        mems = [
            _make_memory("m1", memory_type=SYNTHETIC_MEMORY_TYPE),
            _make_memory("m2", memory_type="experience"),
            _make_memory("m3", memory_type=SYNTHETIC_MEMORY_TYPE),
        ]
        dream_client._query = MagicMock(return_value=mems)
        health = dream_client.calculate_memory_health("ws1")
        assert health["total_memories"] == 3
        assert health["synthetic_memories"] == 2

    def test_health_strength_distribution(self, dream_client):
        """Strength distribution categories are populated."""
        from datetime import datetime
        now = int(datetime.now().timestamp() * 1_000_000)

        mems = [
            # Strong: recently created, high confidence
            _make_memory("m1", confidence=0.95, created_at=now),
            # Medium: some age, moderate confidence
            _make_memory("m2", confidence=0.7, created_at=now - 20 * 86400 * 1_000_000),
            # Weak: old, low confidence
            _make_memory("m3", confidence=0.3, created_at=now - 60 * 86400 * 1_000_000),
        ]
        dream_client._query = MagicMock(return_value=mems)
        health = dream_client.calculate_memory_health("ws1")
        dist = health["strength_distribution"]
        assert "weak" in dist
        assert "medium" in dist
        assert "strong" in dist

    def test_health_recommendations(self, dream_client):
        """Recommendations list is present."""
        mem = _make_memory("m1", confidence=0.1)  # Very weak -> recommendation
        dream_client._query = MagicMock(return_value=[mem])
        health = dream_client.calculate_memory_health("ws1")
        assert isinstance(health["recommendations"], list)
        assert len(health["recommendations"]) > 0

    def test_health_score_between_zero_and_one(self, dream_client):
        """Health score is in [0, 1]."""
        mem = _make_memory("m1")
        dream_client._query = MagicMock(return_value=[mem])
        health = dream_client.calculate_memory_health("ws1")
        assert 0.0 <= health["health_score"] <= 1.0


class TestForgettingCurvePredict:
    def test_predict_returns_expected_keys(self, dream_client):
        """Prediction returns structured result."""
        mem = _make_memory("m1", confidence=0.8)
        result = dream_client.forgetting_curve_predict("ws1", mem, days_from_now=30)
        expected = {
            "memory_id", "current_strength", "predicted_strength",
            "days_from_now", "age_at_prediction", "model", "strength_delta",
        }
        assert expected.issubset(result.keys())

    def test_predict_strength_decreases(self, dream_client):
        """Future strength should be <= current strength."""
        mem = _make_memory("m1", confidence=0.9)
        result = dream_client.forgetting_curve_predict("ws1", mem, days_from_now=30)
        assert result["predicted_strength"] <= result["current_strength"] + 1e-9

    def test_predict_strength_delta_negative(self, dream_client):
        """Strength delta should be negative (strength decays)."""
        mem = _make_memory("m1", confidence=0.9)
        result = dream_client.forgetting_curve_predict("ws1", mem, days_from_now=30)
        assert result["strength_delta"] <= 1e-9

    def test_predict_zero_days(self, dream_client):
        """At 0 days, predicted == current (approximately)."""
        mem = _make_memory("m1", confidence=0.8)
        result = dream_client.forgetting_curve_predict("ws1", mem, days_from_now=0)
        assert abs(result["predicted_strength"] - result["current_strength"]) < 1e-9

    def test_predict_with_config_lookup(self, dream_client):
        """Should attempt to look up workspace config (graceful failure ok)."""
        mem = _make_memory("m1", confidence=0.8)
        # Make _query raise to simulate missing config table
        dream_client._query = MagicMock(side_effect=RuntimeError("no table"))
        result = dream_client.forgetting_curve_predict("ws1", mem, days_from_now=30)
        assert result["memory_id"] == "m1"

    def test_predict_takes_memory_dict(self, dream_client):
        """Works with a plain dict that has created_at and confidence."""
        mem = {"id": "m1", "created_at": int(time.time() * 1_000_000) - 86400 * 1_000_000, "confidence": 0.8}
        result = dream_client.forgetting_curve_predict("ws1", mem, days_from_now=15)
        assert result["memory_id"] == "m1"
        assert result["days_from_now"] == 15


class TestConsolidateWithLLM:
    """LLM-driven consolidation of similar memories (Mnemosyne parity)."""

    def _client(self):
        c = MagicMock()
        rows_by_id = {
            "m1": [{"id": "m1", "content": "Alice likes cats"}],
            "m2": [{"id": "m2", "content": "Alice enjoys science fiction"}],
        }

        def _query(table, **kw):
            fid = (kw.get("filter_dict") or {}).get("id")
            return rows_by_id.get(fid, [])

        c._query.side_effect = _query
        c.consolidate_memories.return_value = {"status": "ok", "id": "cons-1"}
        return c

    def test_llm_path_summarises(self):
        from spacetime_memory.client._dreaming import DreamMixin

        c = self._client()
        dm = DreamMixin()
        dm._query = c._query
        dm.consolidate_memories = c.consolidate_memories

        llm = MagicMock()
        llm.available = True
        llm.chat.return_value = "Alice likes cats and enjoys science fiction."

        result = dm.consolidate_with_llm("ws1", ["m1", "m2"], llm=llm)

        assert result["status"] == "ok"
        assert result["source_count"] == 2
        # LLM called with both sources
        prompt = str(llm.chat.call_args[0][0])
        assert "Alice likes cats" in prompt
        assert "Alice enjoys science fiction" in prompt
        # consolidate_memories called with the LLM summary
        assert "science fiction" in c.consolidate_memories.call_args[0][2]

    def test_no_llm_falls_back_to_grounded(self):
        from spacetime_memory.client._dreaming import DreamMixin

        c = self._client()
        dm = DreamMixin()
        dm._query = c._query
        dm.consolidate_memories = c.consolidate_memories

        llm = MagicMock()
        llm.available = False

        result = dm.consolidate_with_llm("ws1", ["m1", "m2"], llm=llm)

        assert result["status"] == "ok"
        assert result["source_count"] == 2
        # grounded concatenation passed to the reducer
        target = c.consolidate_memories.call_args[0][2]
        assert "Alice likes cats" in target
        assert "Alice enjoys science fiction" in target

    def test_empty_source_ids(self):
        from spacetime_memory.client._dreaming import DreamMixin

        dm = DreamMixin()
        dm._query = Mock()
        dm.consolidate_memories = Mock()

        result = dm.consolidate_with_llm("ws1", [])
        assert result["status"] == "ok"
        assert result["source_count"] == 0
        dm.consolidate_memories.assert_not_called()

    def test_missing_memories_returns_early(self):
        from spacetime_memory.client._dreaming import DreamMixin

        dm = DreamMixin()
        dm._query = Mock(return_value=[])
        dm.consolidate_memories = Mock()

        result = dm.consolidate_with_llm("ws1", ["nope"])
        assert result["status"] == "ok"
        assert result["source_count"] == 0
        dm.consolidate_memories.assert_not_called()
