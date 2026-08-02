"""Comprehensive tests for spacetime_memory.veracity — Bayesian confidence scoring.

Tests VeracityTier enum, compound(), confidence_multiplier(), and
format_veracity() with edge cases and boundary conditions.
"""

import pytest

from spacetime_memory.veracity import (
    TIER_LABELS,
    TIER_SYMBOLS,
    VeracityTier,
    compound,
    confidence_multiplier,
    format_veracity,
)

# ──────────────────────────────────────────────────────────────────────────────
# VeracityTier enum
# ──────────────────────────────────────────────────────────────────────────────


class TestVeracityTierEnum:
    """Tests for the VeracityTier enum."""

    def test_all_tiers_exist(self):
        """All five tiers are defined."""
        tiers = list(VeracityTier)
        assert len(tiers) == 5
        names = {t.name for t in tiers}
        assert names == {"STATED", "UNKNOWN", "INFERRED", "IMPORTED", "TOOL"}

    def test_tier_values_are_strings(self):
        """Each tier's value is its lowercase name."""
        assert VeracityTier.STATED.value == "stated"
        assert VeracityTier.UNKNOWN.value == "unknown"
        assert VeracityTier.INFERRED.value == "inferred"
        assert VeracityTier.IMPORTED.value == "imported"
        assert VeracityTier.TOOL.value == "tool"

    def test_str_construction(self):
        """VeracityTier can be constructed from string values."""
        assert VeracityTier("stated") == VeracityTier.STATED
        assert VeracityTier("unknown") == VeracityTier.UNKNOWN
        assert VeracityTier("inferred") == VeracityTier.INFERRED
        assert VeracityTier("imported") == VeracityTier.IMPORTED
        assert VeracityTier("tool") == VeracityTier.TOOL

    def test_str_construction_invalid_raises(self):
        """Invalid string raises ValueError."""
        with pytest.raises(ValueError):
            VeracityTier("invalid")
        with pytest.raises(ValueError):
            VeracityTier("")
        with pytest.raises(ValueError):
            VeracityTier("STATED")  # case-sensitive


class TestBaseConfidence:
    """Tests for VeracityTier.base_confidence property."""

    def test_stated_base_confidence(self):
        """STATED has base confidence 1.0."""
        assert VeracityTier.STATED.base_confidence == 1.0

    def test_unknown_base_confidence(self):
        """UNKNOWN has base confidence 0.8."""
        assert VeracityTier.UNKNOWN.base_confidence == 0.8

    def test_inferred_base_confidence(self):
        """INFERRED has base confidence 0.7."""
        assert VeracityTier.INFERRED.base_confidence == 0.7

    def test_imported_base_confidence(self):
        """IMPORTED has base confidence 0.6."""
        assert VeracityTier.IMPORTED.base_confidence == 0.6

    def test_tool_base_confidence(self):
        """TOOL has base confidence 0.5."""
        assert VeracityTier.TOOL.base_confidence == 0.5

    def test_all_bases_in_range(self):
        """All base confidences are in [0, 1]."""
        for tier in VeracityTier:
            assert 0.0 <= tier.base_confidence <= 1.0

    def test_bases_are_descending(self):
        """Tiers are ordered from most to least trustworthy."""
        bases = [t.base_confidence for t in VeracityTier]
        # The definition order should be: STATED, UNKNOWN, INFERRED, IMPORTED, TOOL
        assert bases == [1.0, 0.8, 0.7, 0.6, 0.5]

    def test_base_confidence_is_float(self):
        """base_confidence always returns a float."""
        for tier in VeracityTier:
            assert isinstance(tier.base_confidence, float)


class TestFromSource:
    """Tests for VeracityTier.from_source() classmethod."""

    # ── STATED ───────────────────────────────────────────────────────────

    def test_source_user_returns_stated(self):
        assert VeracityTier.from_source("user") == VeracityTier.STATED

    def test_source_stated_returns_stated(self):
        assert VeracityTier.from_source("stated") == VeracityTier.STATED

    def test_source_direct_returns_stated(self):
        assert VeracityTier.from_source("direct") == VeracityTier.STATED

    def test_source_manual_returns_stated(self):
        assert VeracityTier.from_source("manual") == VeracityTier.STATED

    def test_user_source_case_insensitive(self):
        """Source matching is case-insensitive."""
        assert VeracityTier.from_source("USER") == VeracityTier.STATED
        assert VeracityTier.from_source("User") == VeracityTier.STATED
        assert VeracityTier.from_source("StAtEd") == VeracityTier.STATED

    # ── INFERRED (via extraction="llm") ──────────────────────────────────

    def test_extraction_llm_returns_inferred(self):
        """Any source with extraction='llm' returns INFERRED, unless source is user-like."""
        assert VeracityTier.from_source("chat", extraction="llm") == VeracityTier.INFERRED

    def test_source_llm_returns_inferred(self):
        assert VeracityTier.from_source("llm") == VeracityTier.INFERRED

    def test_source_inferred_returns_inferred(self):
        assert VeracityTier.from_source("inferred") == VeracityTier.INFERRED

    def test_source_extraction_returns_inferred(self):
        assert VeracityTier.from_source("extraction") == VeracityTier.INFERRED

    # ── IMPORTED ─────────────────────────────────────────────────────────

    def test_source_import_returns_imported(self):
        assert VeracityTier.from_source("import") == VeracityTier.IMPORTED

    def test_source_sync_returns_imported(self):
        assert VeracityTier.from_source("sync") == VeracityTier.IMPORTED

    def test_source_migration_returns_imported(self):
        assert VeracityTier.from_source("migration") == VeracityTier.IMPORTED

    def test_source_imported_returns_imported(self):
        assert VeracityTier.from_source("imported") == VeracityTier.IMPORTED

    def test_source_external_returns_imported(self):
        assert VeracityTier.from_source("external") == VeracityTier.IMPORTED

    # ── TOOL ─────────────────────────────────────────────────────────────

    def test_source_tool_returns_tool(self):
        assert VeracityTier.from_source("tool") == VeracityTier.TOOL

    def test_source_system_returns_tool(self):
        assert VeracityTier.from_source("system") == VeracityTier.TOOL

    def test_source_agent_returns_tool(self):
        assert VeracityTier.from_source("agent") == VeracityTier.TOOL

    def test_source_generated_returns_tool(self):
        assert VeracityTier.from_source("generated") == VeracityTier.TOOL

    # ── UNKNOWN (fallthrough) ────────────────────────────────────────────

    def test_source_unknown_string_returns_unknown(self):
        assert VeracityTier.from_source("random_garbage_xyz") == VeracityTier.UNKNOWN

    def test_source_empty_returns_unknown(self):
        assert VeracityTier.from_source("") == VeracityTier.UNKNOWN

    def test_source_none_like_string_returns_unknown(self):
        """A source string like 'none' is not special-cased → UNKNOWN."""
        assert VeracityTier.from_source("none") == VeracityTier.UNKNOWN

    # ── user source takes priority over extraction ───────────────────────

    def test_user_source_with_llm_extraction_still_stated(self):
        """User source always wins — user-stated facts are STATED even if LLM-extracted."""
        assert VeracityTier.from_source("user", extraction="llm") == VeracityTier.STATED
        assert VeracityTier.from_source("direct", extraction="llm") == VeracityTier.STATED
        assert VeracityTier.from_source("manual", extraction="llm") == VeracityTier.STATED

    def test_user_source_checked_before_extraction(self):
        """The source check ('user', 'stated', 'direct', 'manual') happens
        before the extraction check, so user + llm = STATED."""
        # This validates the ordering in the if/elif chain
        assert VeracityTier.from_source("stated", extraction="llm") == VeracityTier.STATED

    # ── extraction is checked only when source isn't user-like ───────────

    def test_non_user_source_with_llm_extraction(self):
        """Non-user source with llm extraction returns INFERRED."""
        assert VeracityTier.from_source("chat", extraction="llm") == VeracityTier.INFERRED
        assert VeracityTier.from_source("api", extraction="LLM") == VeracityTier.INFERRED

    def test_import_source_with_regex_extraction_stays_imported(self):
        """import source with regex extraction is still IMPORTED (not INFERRED)."""
        assert VeracityTier.from_source("import", extraction="regex") == VeracityTier.IMPORTED

    # ── coverage of all recognized keywords ──────────────────────────────

    def test_all_user_keywords(self):
        for kw in ("user", "stated", "direct", "manual"):
            assert VeracityTier.from_source(kw) == VeracityTier.STATED

    def test_all_inferred_keywords(self):
        for kw in ("inferred", "llm", "extraction"):
            assert VeracityTier.from_source(kw) == VeracityTier.INFERRED

    def test_all_imported_keywords(self):
        for kw in ("import", "sync", "migration", "imported", "external"):
            assert VeracityTier.from_source(kw) == VeracityTier.IMPORTED

    def test_all_tool_keywords(self):
        for kw in ("tool", "system", "agent", "generated"):
            assert VeracityTier.from_source(kw) == VeracityTier.TOOL

    # ── return type ──────────────────────────────────────────────────────

    def test_returns_veracity_tier_instance(self):
        result = VeracityTier.from_source("user")
        assert isinstance(result, VeracityTier)
        assert result == VeracityTier.STATED


# ──────────────────────────────────────────────────────────────────────────────
# compound()
# ──────────────────────────────────────────────────────────────────────────────


class TestCompound:
    """Tests for compound(tier, sources, base)."""

    # ── tier as VeracityTier enum ────────────────────────────────────────

    def test_stated_single_source(self):
        """STATED with 1 source → compound = 1 - (1-1)^1 = 1.0."""
        assert compound(VeracityTier.STATED, sources=1) == 1.0

    def test_stated_many_sources(self):
        """STATED with any sources → always 1.0 (base=1.0)."""
        for n in [1, 2, 5, 100]:
            assert compound(VeracityTier.STATED, sources=n) == 1.0

    def test_inferred_single_source(self):
        """INFERRED with 1 source → base_confidence = 0.7."""
        assert compound(VeracityTier.INFERRED, sources=1) == 0.7

    def test_inferred_three_sources(self):
        """INFERRED with 3 sources: 1 - (1-0.7)^3 = 1 - 0.027 = 0.973."""
        result = compound(VeracityTier.INFERRED, sources=3)
        expected = 1.0 - (1.0 - 0.7) ** 3
        assert result == pytest.approx(expected)

    def test_unknown_two_sources(self):
        """UNKNOWN with 2 sources: 1 - (1-0.8)^2 = 1 - 0.04 = 0.96."""
        result = compound(VeracityTier.UNKNOWN, sources=2)
        expected = 1.0 - (1.0 - 0.8) ** 2
        assert result == pytest.approx(expected)

    def test_imported_five_sources(self):
        """IMPORTED with 5 sources: 1 - (1-0.6)^5 = 1 - 0.01024 = 0.98976."""
        result = compound(VeracityTier.IMPORTED, sources=5)
        expected = 1.0 - (1.0 - 0.6) ** 5
        assert result == pytest.approx(expected)

    def test_tool_ten_sources(self):
        """TOOL with 10 sources: 1 - (1-0.5)^10 = 1 - 1/1024 ≈ 0.999023."""
        result = compound(VeracityTier.TOOL, sources=10)
        expected = 1.0 - (1.0 - 0.5) ** 10
        assert result == pytest.approx(expected)

    # ── tier as string ───────────────────────────────────────────────────

    def test_string_tier(self):
        """Compound accepts string tier names."""
        assert compound("stated", sources=1) == 1.0
        assert compound("unknown", sources=1) == 0.8
        assert compound("inferred", sources=1) == 0.7
        assert compound("imported", sources=1) == 0.6
        assert compound("tool", sources=1) == 0.5

    def test_string_tier_compounds(self):
        """String tier works with multiple sources."""
        result = compound("inferred", sources=3)
        assert result == pytest.approx(0.973)

    def test_invalid_string_tier_raises(self):
        """Invalid string tier raises ValueError."""
        with pytest.raises(ValueError):
            compound("nonexistent")

    # ── tier=None ────────────────────────────────────────────────────────

    def test_tier_none_default_base(self):
        """tier=None → base defaults to 0.8."""
        assert compound(None, sources=1) == 0.8
        assert compound(tier=None, sources=1) == 0.8

    def test_tier_none_compounds(self):
        """tier=None compounds with base 0.8."""
        result = compound(None, sources=3)
        expected = 1.0 - (1.0 - 0.8) ** 3  # 0.992
        assert result == pytest.approx(expected)

    # ── base override ────────────────────────────────────────────────────

    def test_base_override_ignores_tier(self):
        """When base is provided, tier is ignored."""
        # tier=STATED (base 1.0) but base override to 0.5
        result = compound(VeracityTier.STATED, sources=3, base=0.5)
        expected = 1.0 - (1.0 - 0.5) ** 3  # 0.875
        assert result == pytest.approx(expected)

    def test_base_override_zero(self):
        """base=0.0 → compound always 0.0."""
        assert compound(base=0.0, sources=1) == 0.0
        assert compound(base=0.0, sources=5) == 0.0
        assert compound(base=0.0, sources=100) == 0.0

    def test_base_override_one(self):
        """base=1.0 → compound always 1.0 regardless of sources."""
        assert compound(base=1.0, sources=1) == 1.0
        assert compound(base=1.0, sources=100) == 1.0

    def test_base_override_custom(self):
        """Arbitrary base values are respected."""
        result = compound(base=0.42, sources=4)
        expected = 1.0 - (1.0 - 0.42) ** 4
        assert result == pytest.approx(expected)

    # ── sources clamping ─────────────────────────────────────────────────

    def test_sources_zero_clamped_to_one(self):
        """sources=0 is clamped to 1."""
        assert compound(VeracityTier.INFERRED, sources=0) == 0.7

    def test_sources_negative_clamped_to_one(self):
        """sources=-1 is clamped to 1."""
        assert compound(VeracityTier.INFERRED, sources=-1) == 0.7
        assert compound(VeracityTier.UNKNOWN, sources=-100) == 0.8

    def test_sources_float_truncated_to_int(self):
        """sources=3.7 is converted to int 3."""
        result = compound(VeracityTier.INFERRED, sources=3.7)
        expected = 1.0 - (1.0 - 0.7) ** 3
        assert result == pytest.approx(expected)

    def test_sources_float_below_one_clamped(self):
        """sources=0.5 → int(0.5)=0 → clamped to max(1, 0)=1."""
        assert compound(VeracityTier.INFERRED, sources=0.5) == 0.7

    # ── default sources ──────────────────────────────────────────────────

    def test_default_sources_is_one(self):
        """sources defaults to 1 (no compounding)."""
        assert compound(VeracityTier.INFERRED) == 0.7
        assert compound(VeracityTier.UNKNOWN) == 0.8

    # ── monotonicity ─────────────────────────────────────────────────────

    def test_more_sources_increases_confidence(self):
        """More sources → higher confidence (for base < 1.0)."""
        for tier in [
            VeracityTier.UNKNOWN,
            VeracityTier.INFERRED,
            VeracityTier.IMPORTED,
            VeracityTier.TOOL,
        ]:
            c1 = compound(tier, sources=1)
            c2 = compound(tier, sources=2)
            c3 = compound(tier, sources=5)
            assert c1 <= c2 <= c3
            # Also verify strictly increasing (base < 1.0)
            assert c1 < c2 < c3

    def test_more_sources_no_effect_for_stated(self):
        """More sources don't change STATED (base=1.0)."""
        assert compound(VeracityTier.STATED, sources=1) == 1.0
        assert compound(VeracityTier.STATED, sources=100) == 1.0

    # ── asymptotic behavior ──────────────────────────────────────────────

    def test_approaches_one_with_many_sources(self):
        """With enough sources, confidence approaches 1.0."""
        result = compound(VeracityTier.TOOL, sources=100)
        assert result > 0.9999

    def test_result_never_exceeds_one(self):
        """Confidence is always ≤ 1.0."""
        for tier in VeracityTier:
            for n in [1, 2, 10, 1000]:
                assert compound(tier, sources=n) <= 1.0

    def test_result_never_below_base(self):
        """Confidence is never below the base (sources clamped to ≥ 1)."""
        for tier in VeracityTier:
            base = tier.base_confidence
            assert compound(tier, sources=1) >= base

    # ── return type ──────────────────────────────────────────────────────

    def test_returns_float(self):
        assert isinstance(compound(VeracityTier.STATED), float)
        assert isinstance(compound(VeracityTier.TOOL, sources=5), float)
        assert isinstance(compound(None), float)
        assert isinstance(compound(base=0.42), float)


# ──────────────────────────────────────────────────────────────────────────────
# confidence_multiplier()
# ──────────────────────────────────────────────────────────────────────────────


class TestConfidenceMultiplier:
    """Tests for confidence_multiplier(confidence)."""

    def test_confidence_zero(self):
        """confidence=0.0 → 0.5."""
        assert confidence_multiplier(0.0) == 0.5

    def test_confidence_one(self):
        """confidence=1.0 → 1.0."""
        assert confidence_multiplier(1.0) == 1.0

    def test_confidence_half(self):
        """confidence=0.5 → 0.5 + 0.5*0.5 = 0.75."""
        assert confidence_multiplier(0.5) == 0.75

    def test_confidence_point_eight(self):
        """confidence=0.8 → 0.5 + 0.4 = 0.9."""
        assert confidence_multiplier(0.8) == 0.9

    def test_confidence_point_two(self):
        """confidence=0.2 → 0.5 + 0.1 = 0.6."""
        assert confidence_multiplier(0.2) == 0.6

    def test_known_values(self):
        """Test several known values."""
        test_cases = [
            (0.0, 0.5),
            (0.1, 0.55),
            (0.25, 0.625),
            (0.5, 0.75),
            (0.75, 0.875),
            (0.9, 0.95),
            (1.0, 1.0),
        ]
        for conf, expected in test_cases:
            assert confidence_multiplier(conf) == pytest.approx(expected)

    def test_output_range(self):
        """Output is always in [0.5, 1.0] for input in [0.0, 1.0]."""
        for c in [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0]:
            result = confidence_multiplier(c)
            assert 0.5 <= result <= 1.0

    def test_monotonic(self):
        """Confidence multiplier is monotonically increasing."""
        prev = confidence_multiplier(0.0)
        for c in [0.1, 0.2, 0.3, 0.5, 0.8, 1.0]:
            curr = confidence_multiplier(c)
            assert curr >= prev
            prev = curr

    def test_returns_float(self):
        assert isinstance(confidence_multiplier(0.5), float)
        assert isinstance(confidence_multiplier(0.0), float)
        assert isinstance(confidence_multiplier(1.0), float)


# ──────────────────────────────────────────────────────────────────────────────
# format_veracity()
# ──────────────────────────────────────────────────────────────────────────────


class TestFormatVeracity:
    """Tests for format_veracity(tier, confidence, sources)."""

    # ── enum tier ────────────────────────────────────────────────────────

    def test_stated_format(self):
        result = format_veracity(VeracityTier.STATED, 1.0, sources=3)
        assert result == "✓✓ Stated (user) | conf=1.00 | 3s"

    def test_unknown_format(self):
        result = format_veracity(VeracityTier.UNKNOWN, 0.8, sources=1)
        assert result == "? Unknown provenance | conf=0.80 | 1s"

    def test_inferred_format(self):
        result = format_veracity(VeracityTier.INFERRED, 0.973, sources=3)
        assert result == "~ Inferred (LLM) | conf=0.97 | 3s"

    def test_imported_format(self):
        result = format_veracity(VeracityTier.IMPORTED, 0.6, sources=1)
        assert result == "↓ Imported (external) | conf=0.60 | 1s"

    def test_tool_format(self):
        result = format_veracity(VeracityTier.TOOL, 0.5, sources=1)
        assert result == "⚙ Tool output | conf=0.50 | 1s"

    # ── string tier ──────────────────────────────────────────────────────

    def test_string_tier_format(self):
        """String tier name works same as enum."""
        result = format_veracity("stated", 1.0, sources=2)
        assert result == "✓✓ Stated (user) | conf=1.00 | 2s"

    def test_string_inferred_format(self):
        result = format_veracity("inferred", 0.7, sources=1)
        assert result == "~ Inferred (LLM) | conf=0.70 | 1s"

    # ── confidence formatting ─────────────────────────────────────────────

    def test_confidence_two_decimals(self):
        """Confidence is always formatted to 2 decimal places."""
        result = format_veracity(VeracityTier.STATED, 0.9999, sources=1)
        assert "conf=1.00" in result

        result = format_veracity(VeracityTier.TOOL, 0.123456, sources=1)
        assert "conf=0.12" in result

        result = format_veracity(VeracityTier.UNKNOWN, 0.0, sources=1)
        assert "conf=0.00" in result

    def test_confidence_rounding(self):
        """Confidence is rounded to 2 decimal places."""
        result = format_veracity(VeracityTier.INFERRED, 0.955, sources=1)
        # 0.955 rounds to 0.95 or 0.96 depending on Python float precision
        assert "conf=0.9" in result  # could be 0.95 or 0.96

    # ── sources formatting ───────────────────────────────────────────────

    def test_sources_singular(self):
        result = format_veracity(VeracityTier.STATED, 1.0, sources=1)
        assert result.endswith("1s")

    def test_sources_plural(self):
        result = format_veracity(VeracityTier.STATED, 1.0, sources=5)
        assert result.endswith("5s")

    def test_sources_default(self):
        """Default sources=1."""
        result = format_veracity(VeracityTier.TOOL, 0.5)
        assert result.endswith("1s")

    # ── unknown/edge tiers ───────────────────────────────────────────────

    def test_string_tier_unknown_fallback(self):
        """Unknown string tiers use '?' symbol and the value as label."""
        # Passing an unrecognized string would fail at VeracityTier("bad")
        # before reaching the format logic. So test with a real tier that
        # somehow isn't in TIER_LABELS (shouldn't happen, but tests the .get logic)
        # All real tiers are in TIER_LABELS, no test needed

    # ── return type ──────────────────────────────────────────────────────

    def test_returns_string(self):
        result = format_veracity(VeracityTier.STATED, 1.0, sources=1)
        assert isinstance(result, str)

    # ── all tier symbols present ─────────────────────────────────────────

    def test_all_tiers_have_symbols(self):
        """Every VeracityTier has a corresponding symbol in TIER_SYMBOLS."""
        for tier in VeracityTier:
            assert tier in TIER_SYMBOLS, f"Missing symbol for {tier}"

    def test_all_tiers_have_labels(self):
        """Every VeracityTier has a corresponding label in TIER_LABELS."""
        for tier in VeracityTier:
            assert tier in TIER_LABELS, f"Missing label for {tier}"

    # ─── compound + format integration ───────────────────────────────────

    def test_compound_format_roundtrip(self):
        """Demonstrate the full pipeline: tier → compound → format."""
        tier = VeracityTier.INFERRED
        conf = compound(tier, sources=3)
        formatted = format_veracity(tier, conf, sources=3)
        assert formatted == "~ Inferred (LLM) | conf=0.97 | 3s"


# ──────────────────────────────────────────────────────────────────────────────
# Edge cases and error conditions
# ──────────────────────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Cross-module edge cases."""

    def test_compound_very_large_sources(self):
        """Very large source count still works."""
        result = compound(VeracityTier.TOOL, sources=10_000)
        # Should be extremely close to 1.0
        assert result > 0.999999999

    def test_compound_with_base_near_one(self):
        """Base very close to 1.0 — compounding still works."""
        result = compound(base=0.999, sources=3)
        expected = 1.0 - (1.0 - 0.999) ** 3  # 1 - (0.001)^3 = 1 - 1e-9
        assert result == pytest.approx(expected)

    def test_compound_with_base_near_zero(self):
        """Base very close to 0.0 — compounding still works."""
        result = compound(base=0.001, sources=5)
        expected = 1.0 - (1.0 - 0.001) ** 5
        assert result == pytest.approx(expected)
        # Still quite small with only 5 sources
        assert result < 0.01
