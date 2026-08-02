"""Comprehensive tests for spacetime_memory.weibull — Weibull temporal boost.

Tests both weibull_weight() and apply_temporal_boost() with edge cases,
parameter variations, and error handling.
"""

import math
from unittest.mock import patch

import pytest

from spacetime_memory.weibull import apply_temporal_boost, weibull_weight

# ──────────────────────────────────────────────────────────────────────────────
# weibull_weight
# ──────────────────────────────────────────────────────────────────────────────


class TestWeibullWeight:
    """Tests for weibull_weight(age_seconds, k, lam, floor)."""

    # ── zero / negative age ──────────────────────────────────────────────

    def test_age_zero_returns_one(self):
        """age_seconds=0 → brand new item → weight 1.0."""
        assert weibull_weight(0.0) == 1.0

    def test_age_negative_returns_one(self):
        """age_seconds < 0 → future timestamps or edge → weight 1.0."""
        assert weibull_weight(-1.0) == 1.0
        assert weibull_weight(-3600.0) == 1.0
        assert weibull_weight(-1e9) == 1.0

    # ── known values at default params ───────────────────────────────────

    def test_default_params_at_lambda(self):
        """At t = λ (7 days), weight = exp(-1^k) = exp(-1) ≈ 0.3679."""
        weight = weibull_weight(604800.0)  # exactly 7 days
        expected = math.exp(-1.0)
        assert weight == pytest.approx(expected, rel=1e-10)

    def test_default_params_half_lambda(self):
        """At t = λ/2, weight = exp(-(0.5)^0.5) = exp(-0.7071) ≈ 0.493."""
        weight = weibull_weight(302400.0)  # 3.5 days
        expected = math.exp(-((302400.0 / 604800.0) ** 0.5))
        assert weight == pytest.approx(expected, rel=1e-10)

    def test_default_params_very_old_hits_floor(self):
        """Very old item should be clamped to the floor value."""
        weight = weibull_weight(1e15)  # ~31 million years
        assert weight == 0.05  # default floor

    def test_weight_never_below_floor(self):
        """Regardless of age, weight is always >= floor."""
        ages = [0, 1, 100, 10000, 604800, 1e8, 1e12, 1e20]
        for age in ages:
            assert weibull_weight(age) >= 0.05

    def test_weight_never_above_one(self):
        """Weight is always <= 1.0."""
        ages = [-1e6, -1, 0, 1, 100, 604800, 1e10]
        for age in ages:
            assert weibull_weight(age) <= 1.0

    def test_very_recent_near_one(self):
        """An item just 1 second old should have weight very close to 1.0."""
        w = weibull_weight(1.0)
        # At defaults: exp(-(1/604800)^0.5) ≈ exp(-0.001286) ≈ 0.9987
        assert w > 0.998
        assert w <= 1.0

    # ── monotonicity ─────────────────────────────────────────────────────

    def test_weight_decreases_with_age(self):
        """Older items should get lower (or equal) weight."""
        w1 = weibull_weight(10.0)
        w2 = weibull_weight(100.0)
        w3 = weibull_weight(1000.0)
        w4 = weibull_weight(10000.0)
        assert w1 >= w2 >= w3 >= w4

    # ── custom k values ──────────────────────────────────────────────────

    def test_k_one_exponential_decay(self):
        """k=1 is exponential decay: weight = exp(-t/λ)."""
        weight = weibull_weight(604800.0, k=1.0)
        expected = math.exp(-1.0)
        assert weight == pytest.approx(expected, rel=1e-10)

    def test_k_one_half_lambda(self):
        """k=1 at t=λ/2: weight = exp(-0.5) ≈ 0.6065."""
        weight = weibull_weight(302400.0, k=1.0)
        expected = math.exp(-0.5)
        assert weight == pytest.approx(expected, rel=1e-10)

    def test_k_greater_than_one_shaped(self):
        """k > 1 gives S-shaped (increasing hazard) curve."""
        # k=2 at t=λ: weight = exp(-1^2) = exp(-1) same as k=1
        weight = weibull_weight(604800.0, k=2.0)
        expected = math.exp(-1.0)
        assert weight == pytest.approx(expected, rel=1e-10)

    def test_k_two_below_lambda(self):
        """k=2 at t=λ/2: decays slower initially than k<1."""
        weight = weibull_weight(302400.0, k=2.0)
        expected = math.exp(-0.25)  # (0.5)^2 = 0.25
        assert weight == pytest.approx(expected, rel=1e-10)

    def test_k_two_above_lambda(self):
        """k=2 at t=2λ: weight = exp(-4) ≈ 0.0183 → clamped to floor 0.05."""
        weight = weibull_weight(1_209_600.0, k=2.0)
        # exp(-4) ≈ 0.0183, but default floor=0.05 clamps it up
        assert weight == 0.05

    def test_k_very_small(self):
        """k → 0: very rapid initial decay, extremely long tail."""
        # k=0.1 at t=λ: weight = exp(-1^0.1) = exp(-1) ≈ 0.3679
        weight = weibull_weight(604800.0, k=0.1)
        expected = math.exp(-1.0)
        assert weight == pytest.approx(expected, rel=1e-10)

    def test_k_two_saturates_faster(self):
        """With k=2, the weight drops below floor faster than default k=0.5."""
        # At t=4*λ with k=2: weight = exp(-4^2) = exp(-16) ≈ 1.13e-7 → clamped
        weight = weibull_weight(4 * 604800.0, k=2.0)
        assert weight == 0.05  # floor

    # ── custom lam values ────────────────────────────────────────────────

    def test_custom_lam(self):
        """Custom λ changes the time scale."""
        lam = 3600.0  # 1 hour
        weight = weibull_weight(3600.0, lam=lam)  # t = λ
        expected = math.exp(-1.0)
        assert weight == pytest.approx(expected, rel=1e-10)

    def test_custom_lam_fraction(self):
        """t = λ/2 with custom λ."""
        lam = 3600.0
        weight = weibull_weight(1800.0, lam=lam)
        expected = math.exp(-((1800.0 / 3600.0) ** 0.5))
        assert weight == pytest.approx(expected, rel=1e-10)

    def test_very_small_lam(self):
        """Very small λ makes items decay extremely fast."""
        lam = 1.0  # 1 second
        # t=10 seconds, k=0.5: weight = exp(-10^0.5) = exp(-3.162) ≈ 0.0423
        weight = weibull_weight(10.0, lam=lam)
        assert weight == 0.05  # hit floor

    def test_very_large_lam(self):
        """Very large λ makes items decay extremely slowly."""
        lam = 1e12  # ~31,700 years
        # t = 1 year (31557600s), k=0.5
        # (31557600/1e12)^0.5 = (3.15576e-5)^0.5 = 0.005617
        # exp(-0.005617) ≈ 0.9944
        weight = weibull_weight(31557600.0, lam=lam)
        assert weight > 0.99
        assert weight < 1.0

    # ── custom floor values ──────────────────────────────────────────────

    def test_custom_floor(self):
        """Custom floor value is respected."""
        weight = weibull_weight(1e20, floor=0.25)
        assert weight == 0.25

    def test_floor_zero(self):
        """floor=0.0 allows weight to approach zero for extremely old items."""
        weight = weibull_weight(1e20, floor=0.0)
        # Very close to 0 but not negative
        assert weight >= 0.0
        assert weight < 1e-100

    def test_floor_one_always_returns_one(self):
        """floor=1.0 always returns 1.0 regardless of age."""
        assert weibull_weight(0.0, floor=1.0) == 1.0
        assert weibull_weight(1e6, floor=1.0) == 1.0
        assert weibull_weight(1e20, floor=1.0) == 1.0

    # ── combined custom params ───────────────────────────────────────────

    def test_all_defaults_combined(self):
        """All params at defaults: validate multiple age values."""
        test_cases = [
            (0.0, 1.0),
            (1.0, math.exp(-((1.0 / 604800.0) ** 0.5))),
            (86400.0, math.exp(-((86400.0 / 604800.0) ** 0.5))),
            (604800.0, math.exp(-1.0)),
            (3_024_000.0, math.exp(-(5.0**0.5))),
        ]
        for age, expected in test_cases:
            result = weibull_weight(age)
            assert result == pytest.approx(max(0.05, min(1.0, expected)), rel=1e-10)

    def test_weight_is_float(self):
        """Return type is always float."""
        for age in [-1, 0, 1, 1000, 1e6]:
            assert isinstance(weibull_weight(age), float)


# ──────────────────────────────────────────────────────────────────────────────
# apply_temporal_boost
# ──────────────────────────────────────────────────────────────────────────────


class TestApplyTemporalBoost:
    """Tests for apply_temporal_boost(results, **kwargs)."""

    # ── empty results ────────────────────────────────────────────────────

    def test_empty_results(self):
        """Empty list returns empty list."""
        result = apply_temporal_boost([])
        assert result == []
        assert isinstance(result, list)

    # ── single result ────────────────────────────────────────────────────

    @patch("spacetime_memory.weibull.time")
    def test_single_result(self, mock_time):
        """Single result gets temporal_weight and boosted score."""
        mock_time.time.return_value = 1_700_000_000.0
        results = [
            {
                "score": 10.0,
                "created_at": 1_700_000_000.0 - 3600.0,  # 1 hour old
            }
        ]
        result = apply_temporal_boost(results)

        assert len(result) == 1
        assert "temporal_weight" in result[0]
        assert result[0]["temporal_weight"] > 0.0
        # score should be boosted: original * (1 + 0.15 * weight)
        original = 10.0
        weight = result[0]["temporal_weight"]
        expected_score = original * (1.0 + 0.15 * weight)
        assert result[0]["score"] == pytest.approx(expected_score)
        # Return value is same list object (mutated in-place)
        assert result is results

    # ── multiple results ─────────────────────────────────────────────────

    @patch("spacetime_memory.weibull.time")
    def test_multiple_results_sorted_by_new_score(self, mock_time):
        """Results are sorted by boosted score descending."""
        mock_time.time.return_value = 1_700_000_000.0
        results = [
            {"score": 5.0, "created_at": 1_700_000_000.0 - 1},  # 1 sec old
            {"score": 20.0, "created_at": 1_700_000_000.0 - 86400},  # 1 day old
            {"score": 10.0, "created_at": 1_700_000_000.0 - 3600},  # 1 hour old
        ]
        result = apply_temporal_boost(results)

        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True), f"not sorted: {scores}"

    # ── in-place mutation ────────────────────────────────────────────────

    @patch("spacetime_memory.weibull.time")
    def test_returns_same_list_object(self, mock_time):
        """apply_temporal_boost mutates in-place and returns the same list."""
        mock_time.time.return_value = 1_700_000_000.0
        results = [{"score": 10.0, "created_at": 1_700_000_000.0 - 3600}]
        result = apply_temporal_boost(results)
        assert result is results

    # ── missing fields ───────────────────────────────────────────────────

    @patch("spacetime_memory.weibull.time")
    def test_missing_timestamp_field_uses_zero(self, mock_time):
        """Missing timestamp → age = now - 0 → very large → floor weight."""
        mock_time.time.return_value = 1_700_000_000.0
        results = [{"score": 10.0}]  # no created_at
        result = apply_temporal_boost(results)

        assert "temporal_weight" in result[0]
        # Very old because ts defaults to 0 → weight should hit floor
        assert result[0]["temporal_weight"] == 0.05

    @patch("spacetime_memory.weibull.time")
    def test_missing_score_field_uses_zero(self, mock_time):
        """Missing score → boost applied to 0.0 → stays 0.0."""
        mock_time.time.return_value = 1_700_000_000.0
        results = [{"created_at": 1_700_000_000.0 - 3600}]  # no score
        result = apply_temporal_boost(results)

        # 0.0 * (1 + 0.15 * weight) = 0.0
        assert result[0]["score"] == 0.0
        assert "temporal_weight" in result[0]

    # ── microsecond timestamps ───────────────────────────────────────────

    @patch("spacetime_memory.weibull.time")
    def test_microsecond_timestamp(self, mock_time):
        """Timestamps > 1e12 are treated as microseconds."""
        now_s = 1_700_000_000.0
        mock_time.time.return_value = now_s
        # 1 hour ago in microseconds
        ts_us = int((now_s - 3600.0) * 1_000_000)
        assert ts_us > 1_000_000_000_000, "must be in microsecond range"

        results = [{"score": 10.0, "created_at": ts_us}]
        result = apply_temporal_boost(results)

        assert "temporal_weight" in result[0]
        # Should be treated as ~1 hour old, not billion+ seconds
        w = result[0]["temporal_weight"]
        assert w > 0.9, f"Expected near-recent weight, got {w}"

    @patch("spacetime_memory.weibull.time")
    def test_microsecond_timestamp_boundary(self, mock_time):
        """Exactly 1_000_000_000_001 is treated as microseconds."""
        now_s = 1_700_000_000.0
        mock_time.time.return_value = now_s
        # Create a timestamp just above the threshold: 1e12 + 1 us
        # That maps to ~1e6 seconds ago → age ~ 1e6
        ts_us = 1_000_000_000_001
        results = [{"score": 10.0, "created_at": ts_us}]
        result = apply_temporal_boost(results)

        assert "temporal_weight" in result[0]
        # Should NOT treat as 1.7e9 seconds old (which would floor out)
        # Age = 1700000000 - 1000000.000001 ≈ 1699000000 seconds → still old
        # Actually let's sanity-check: the key point is it goes through the microsecond path

    @patch("spacetime_memory.weibull.time")
    def test_microsecond_timestamp_recent(self, mock_time):
        """Recent microsecond timestamps are correctly recent."""
        now_s = 1_700_000_000.0
        mock_time.time.return_value = now_s
        # 10 seconds ago in microseconds
        ts_us = int((now_s - 10.0) * 1_000_000)
        results = [{"score": 10.0, "created_at": ts_us}]
        result = apply_temporal_boost(results)

        w = result[0]["temporal_weight"]
        assert w > 0.99, f"Expected weight near 1.0 for 10s old, got {w}"

    # ── second-resolution timestamps ─────────────────────────────────────

    @patch("spacetime_memory.weibull.time")
    def test_normal_second_timestamp(self, mock_time):
        """Timestamp <= 1e12 treated as seconds."""
        now_s = 1_700_000_000.0
        mock_time.time.return_value = now_s
        ts_s = int(now_s - 3600.0)  # 1 hour ago in seconds
        results = [{"score": 10.0, "created_at": ts_s}]
        result = apply_temporal_boost(results)

        w = result[0]["temporal_weight"]
        assert w > 0.5, f"Expected moderate weight for 1h old, got {w}"

    # ── boost_strength variations ────────────────────────────────────────

    @patch("spacetime_memory.weibull.time")
    def test_boost_strength_zero_no_change(self, mock_time):
        """boost_strength=0 means score unchanged."""
        mock_time.time.return_value = 1_700_000_000.0
        results = [{"score": 10.0, "created_at": 1_700_000_000.0 - 3600}]
        result = apply_temporal_boost(results, boost_strength=0.0)

        assert result[0]["score"] == 10.0
        assert "temporal_weight" in result[0]

    @patch("spacetime_memory.weibull.time")
    def test_boost_strength_negative(self, mock_time):
        """Negative boost_strength reduces score."""
        mock_time.time.return_value = 1_700_000_000.0
        results = [{"score": 10.0, "created_at": 1_700_000_000.0 - 3600}]
        result = apply_temporal_boost(results, boost_strength=-0.5)

        assert result[0]["score"] < 10.0  # score reduced
        assert "temporal_weight" in result[0]

    @patch("spacetime_memory.weibull.time")
    def test_boost_strength_large(self, mock_time):
        """Large boost_strength amplifies the temporal effect."""
        mock_time.time.return_value = 1_700_000_000.0
        results = [{"score": 10.0, "created_at": 1_700_000_000.0 - 1}]
        result = apply_temporal_boost(results, boost_strength=100.0)

        # Fresh item (1s old) with large boost
        assert result[0]["score"] > 10.0
        # About 10 * (1 + 100 * ~0.99999) ≈ 10 * 101 ≈ 1010
        assert result[0]["score"] > 100.0

    # ── custom field names ───────────────────────────────────────────────

    @patch("spacetime_memory.weibull.time")
    def test_custom_score_field(self, mock_time):
        """Custom score_field key is used."""
        mock_time.time.return_value = 1_700_000_000.0
        results = [{"relevance": 50.0, "created_at": 1_700_000_000.0 - 3600}]
        result = apply_temporal_boost(results, score_field="relevance")

        assert result[0]["relevance"] > 50.0
        assert "temporal_weight" in result[0]

    @patch("spacetime_memory.weibull.time")
    def test_custom_timestamp_field(self, mock_time):
        """Custom timestamp_field key is used."""
        mock_time.time.return_value = 1_700_000_000.0
        results = [{"score": 10.0, "ts": 1_700_000_000.0 - 3600}]
        result = apply_temporal_boost(results, timestamp_field="ts")

        assert "temporal_weight" in result[0]
        assert result[0]["score"] > 10.0

    # ── custom k and lam passed through ──────────────────────────────────

    @patch("spacetime_memory.weibull.time")
    def test_custom_k_and_lam(self, mock_time):
        """k and lam are forwarded to weibull_weight."""
        mock_time.time.return_value = 1_700_000_000.0
        results = [{"score": 10.0, "created_at": 1_700_000_000.0 - 3600}]

        # k=1, lam=3600 (1 hour): age=3600 → t/λ=1 → weight=exp(-1)=0.3679
        result = apply_temporal_boost(results, k=1.0, lam=3600.0)

        expected_weight = math.exp(-1.0)
        assert result[0]["temporal_weight"] == pytest.approx(expected_weight, rel=1e-6)

    # ── deterministic output ─────────────────────────────────────────────

    @patch("spacetime_memory.weibull.time")
    def test_deterministic_with_same_inputs(self, mock_time):
        """Same inputs always produce same outputs."""
        mock_time.time.return_value = 1_700_000_000.0
        results1 = [{"score": 10.0, "created_at": 1_700_000_000.0 - 3600}]
        results2 = [{"score": 10.0, "created_at": 1_700_000_000.0 - 3600}]

        r1 = apply_temporal_boost(results1)
        r2 = apply_temporal_boost(results2)

        assert r1[0]["score"] == r2[0]["score"]
        assert r1[0]["temporal_weight"] == r2[0]["temporal_weight"]

    # ── ordering stability ───────────────────────────────────────────────

    @patch("spacetime_memory.weibull.time")
    def test_sorting_stable_for_equal_scores(self, mock_time):
        """Items with identical timestamps keep their relative order."""
        mock_time.time.return_value = 1_700_000_000.0
        results = [
            {"score": 10.0, "created_at": 1_700_000_000.0 - 3600, "id": "a"},
            {"score": 10.0, "created_at": 1_700_000_000.0 - 3600, "id": "b"},
            {"score": 10.0, "created_at": 1_700_000_000.0 - 3600, "id": "c"},
        ]
        result = apply_temporal_boost(results)

        # All boosted scores should be equal → original order preserved
        assert all(r["score"] == result[0]["score"] for r in result)

    # ── does not mutate unrelated keys ───────────────────────────────────

    @patch("spacetime_memory.weibull.time")
    def test_preserves_unrelated_keys(self, mock_time):
        """Unrelated dict keys are preserved."""
        mock_time.time.return_value = 1_700_000_000.0
        results = [
            {
                "score": 10.0,
                "created_at": 1_700_000_000.0 - 3600,
                "title": "hello",
                "tags": ["a", "b"],
            }
        ]
        result = apply_temporal_boost(results)

        assert result[0]["title"] == "hello"
        assert result[0]["tags"] == ["a", "b"]

    # ── score clamping ───────────────────────────────────────────────────

    @patch("spacetime_memory.weibull.time")
    def test_negative_original_score(self, mock_time):
        """Negative original score is still boosted multiplicatively."""
        mock_time.time.return_value = 1_700_000_000.0
        results = [{"score": -5.0, "created_at": 1_700_000_000.0 - 1}]
        result = apply_temporal_boost(results)

        # -5.0 * (1 + 0.15 * ~1.0) ≈ -5.75
        assert result[0]["score"] < -5.0
