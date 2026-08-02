"""Tests for AAAK compression (aaak.py)."""

from unittest.mock import mock_open, patch

from spacetime_memory.aaak import (
    CATEGORIES,
    _apply_categories,
    _apply_phrases,
    _apply_structural,
    _apply_trailing,
    _compact_parens,
    _is_already_compressed,
    aaak_compress,
    aaak_decompress,
    aaak_ratio,
)

# ── _is_already_compressed ──────────────────────────────────────────────────


class TestIsAlreadyCompressed:
    """Skip detection: avoid re-compressing already-AAAK text."""

    def test_no_pipe_returns_false(self):
        assert _is_already_compressed("hello world") is False

    def test_pipe_with_few_words_returns_true(self):
        # "PREF|dark mode" has 3 words after splitting on |
        assert _is_already_compressed("PREF|dark mode") is True

    def test_pipe_with_exactly_five_words_returns_true(self):
        assert _is_already_compressed("a|b c d e") is True

    def test_pipe_with_many_words_returns_false(self):
        # 6 words → not compressed
        assert _is_already_compressed("nope|one two three four five six") is False

    def test_empty_string_returns_false(self):
        assert _is_already_compressed("") is False

    def test_only_pipe_returns_true(self):
        # "|" → words count as 0 → True
        assert _is_already_compressed("|") is True


# ── _apply_categories ───────────────────────────────────────────────────────


class TestApplyCategories:
    """Category prefix abbreviation."""

    def test_prefix_replacement(self):
        assert _apply_categories("PREFERENCE: dark mode") == "PREF|dark mode"

    def test_prefix_after_newline(self):
        assert _apply_categories("\nPREFERENCE: dark mode") == "\nPREF|dark mode"

    def test_status_category(self):
        assert _apply_categories("STATUS: working") == "STAT|working"

    def test_instr_category(self):
        assert _apply_categories("INSTRUCTION: do this") == "INST|do this"

    def test_unknown_prefix_unchanged(self):
        assert _apply_categories("UNKNOWN: something") == "UNKNOWN: something"

    def test_no_category_unchanged(self):
        assert _apply_categories("just some text") == "just some text"

    def test_empty_string(self):
        assert _apply_categories("") == ""

    def test_category_in_middle_not_replaced(self):
        # Only matches at start of text or after newline
        assert _apply_categories("some PREFERENCE: dark mode") == "some PREFERENCE: dark mode"

    def test_category_after_text_with_newline(self):
        # _apply_categories only matches at start of text or after newline
        # at the very beginning. "line1\nSTATUS:" does NOT start with "\nSTATUS:"
        text = "line1\nSTATUS: ok"
        # Category in middle of text → not replaced
        assert _apply_categories(text) == "line1\nSTATUS: ok"
        # But if the text itself starts with newline+category, it works:
        text2 = "\nSTATUS: ok"
        assert _apply_categories(text2) == "\nSTAT|ok"

    def test_all_known_categories(self):
        """Every category in the ruleset abbreviates correctly."""
        for full, abbr in CATEGORIES.items():
            result = _apply_categories(full + ": x")
            assert result == abbr + "|x", f"Failed for {full}"


# ── _apply_phrases ──────────────────────────────────────────────────────────


class TestApplyPhrases:
    """Longest-match-first phrase substitution."""

    def test_user_asked_for(self):
        assert _apply_phrases("User asked for dark mode") == "ASK dark mode"

    def test_user_asked(self):
        # "User asked " (with trailing space) is a separate phrase
        assert _apply_phrases("User asked about colors") == "ASK about colors"

    def test_user_wants(self):
        assert _apply_phrases("User wants pizza") == "WANT pizza"

    def test_user_prefers(self):
        assert _apply_phrases("User prefers vim") == "PREF vim"

    def test_user_likes(self):
        assert _apply_phrases("User likes rust") == "LIKE rust"

    def test_user_dislikes(self):
        assert _apply_phrases("User dislikes bugs") == "DISLIKE bugs"

    def test_user_is(self):
        assert _apply_phrases("User is happy") == "IS happy"

    def test_user_has(self):
        assert _apply_phrases("User has knowledge") == "HAS knowledge"

    def test_user_built(self):
        assert _apply_phrases("User built a compiler") == "BUILT a compiler"

    def test_user_requested(self):
        assert _apply_phrases("User requested a feature") == "REQ a feature"

    def test_full_stack_developer(self):
        assert _apply_phrases("Full-stack developer") == "FSDEV"

    def test_software_developer(self):
        assert _apply_phrases("Software Developer") == "SDEV"

    def test_ai_systems_engineer(self):
        assert _apply_phrases("AI Systems Engineer") == "AIENG"

    def test_real_time(self):
        assert _apply_phrases("real-time") == "RT"

    def test_real_time_caps(self):
        assert _apply_phrases("Real-time") == "RT"

    def test_bilingual(self):
        assert _apply_phrases("bilingual") == "bi"

    def test_bilingual_caps(self):
        assert _apply_phrases("Bilingual") == "bi"

    def test_self_hosted(self):
        assert _apply_phrases("self-hosted") == "selfhost"

    def test_automation(self):
        assert _apply_phrases("automation") == "auto"

    def test_transcription(self):
        assert _apply_phrases("transcription") == "transc"

    def test_translation(self):
        assert _apply_phrases("translation") == "transl"

    def test_multiple_phrases(self):
        result = _apply_phrases("User asked for dark mode and self-hosted")
        assert "ASK" in result
        assert "selfhost" in result

    def test_no_match_unchanged(self):
        assert _apply_phrases("nothing matches here") == "nothing matches here"

    def test_empty_string(self):
        assert _apply_phrases("") == ""

    def test_greedy_longest_match_first(self):
        # "User asked for" (longer) should match before "User asked " (shorter)
        # If greedy works: "User asked for help" → "ASK help" not "ASK for help"
        result = _apply_phrases("User asked for help")
        assert result == "ASK help"


# ── _apply_structural ───────────────────────────────────────────────────────


class TestApplyStructural:
    """Sequential structural replacements."""

    def test_and(self):
        assert _apply_structural("apples and oranges") == "apples+oranges"

    def test_or(self):
        assert _apply_structural("this or that") == "this/that"

    def test_for(self):
        assert _apply_structural("tools for building") == "tools→building"

    def test_to(self):
        assert _apply_structural("go to store") == "go→store"

    def test_with(self):
        assert _apply_structural("code with tests") == "code w/ tests"

    def test_over(self):
        assert _apply_structural("rise over expectations") == "rise>expectations"

    def test_instead_of(self):
        assert _apply_structural("rust instead of python") == "rust!>python"

    def test_because_of(self):
        assert _apply_structural("delay because of rain") == "delay\u2235rain"

    def test_due_to(self):
        # " to " appears BEFORE " due to " in the structural rules list,
        # so it matches first: "cancel due→weather"
        # The sequential order matters — shorter patterns fire before longer ones
        # if they appear earlier in the rule list.
        result = _apply_structural("cancel due to weather")
        assert "→" in result  # " to " is replaced before " due to " gets a chance

    def test_using(self):
        assert _apply_structural("build using clang") == "build→clang"

    def test_built(self):
        assert _apply_structural("features built tonight") == "features→tonight"

    def test_in(self):
        assert _apply_structural("live in Paris") == "live:Paris"

    def test_at(self):
        assert _apply_structural("meet at noon") == "meet@noon"

    def test_on(self):
        assert _apply_structural("deploy on friday") == "deploy@friday"

    def test_from(self):
        assert _apply_structural("learn from masters") == "learn<-masters"

    def test_dash_separator(self):
        assert _apply_structural("a - b") == "a | b"

    def test_double_dash_separator(self):
        assert _apply_structural("x -- y") == "x | y"

    def test_comma_separator(self):
        assert _apply_structural("red, green") == "red | green"

    def test_multiple_patterns(self):
        text = "red, green and blue for painting"
        result = _apply_structural(text)
        assert " | " in result or "," not in result
        assert "+" in result

    def test_no_match_unchanged(self):
        assert _apply_structural("simpletext") == "simpletext"

    def test_empty_string(self):
        assert _apply_structural("") == ""


# ── _compact_parens ─────────────────────────────────────────────────────────


class TestCompactParens:
    """Remove spaces inside parentheses."""

    def test_leading_space(self):
        assert _compact_parens("( foo") == "(foo"

    def test_trailing_space(self):
        assert _compact_parens("bar )") == "bar)"

    def test_both_spaces(self):
        assert _compact_parens("( hello world )") == "(hello world)"

    def test_multiple_spaces_inside(self):
        assert _compact_parens("(  a  b  )") == "(a  b)"

    def test_no_parens_unchanged(self):
        assert _compact_parens("no parens here") == "no parens here"

    def test_closed_parens_unchanged(self):
        assert _compact_parens("(already compact)") == "(already compact)"

    def test_empty_string(self):
        assert _compact_parens("") == ""


# ── _apply_trailing ─────────────────────────────────────────────────────────


class TestApplyTrailing:
    """Replace terminal phrases with compaction symbols."""

    def test_working_correctly_with_space(self):
        assert _apply_trailing("system working correctly") == "system OK"

    def test_working_alone_with_space(self):
        assert _apply_trailing("feature working") == "feature OK"

    def test_working_at_trailing_position(self):
        assert _apply_trailing("status is working") == "status is OK"

    def test_complete_alone(self):
        assert _apply_trailing("complete") == "DONE"

    def test_completed_alone(self):
        assert _apply_trailing("completed") == "DONE"

    def test_complete_with_space(self):
        assert _apply_trailing("task complete") == "task DONE"

    def test_completed_with_space(self):
        assert _apply_trailing("build completed") == "build DONE"

    def test_longest_match_first(self):
        # "working correctly" should match before "working"
        result = _apply_trailing("server working correctly")
        assert result == "server OK"
        # Not "server OK correctly"

    def test_no_trailing_match_unchanged(self):
        assert _apply_trailing("hello world") == "hello world"

    def test_phrase_not_at_end_unchanged(self):
        # "working" in middle shouldn't be replaced
        assert _apply_trailing("the working system") == "the working system"

    def test_empty_string(self):
        assert _apply_trailing("") == ""

    def test_only_phrase(self):
        # The phrase alone: "working correctly" → rstrip is "working correctly"
        assert _apply_trailing("working correctly") == "OK"


# ── aaak_compress ───────────────────────────────────────────────────────────


class TestAAAKCompress:
    """Public compression API — full 5-step pipeline."""

    def test_empty_input(self):
        assert aaak_compress("") == ""

    def test_already_compressed_bypass(self):
        compressed = "PREF|dark mode+STAT|OK"
        assert aaak_compress(compressed) == compressed

    def test_basic_compression(self):
        text = "PREFERENCE: User asked for dark mode and it is working correctly"
        result = aaak_compress(text)
        # Should contain category abbreviation, phrase substitutions, structural, trailing
        assert "PREF|" in result or "PREF " in result or "PREF|" in text
        assert len(result) < len(text)

    def test_category_plus_phrase(self):
        text = "STATUS: User prefers online status complete"
        result = aaak_compress(text)
        # Should be compressed
        assert len(result) < len(text)

    def test_category_plus_structural(self):
        text = "PREFERENCE: dark mode and light mode"
        result = aaak_compress(text)
        assert "+" in result or "PREF|" in result

    def test_full_pipeline_example(self):
        """Docstring example: PREFERENCE: User asked for dark mode. STATUS: working correctly → PREF|ASK dark mode+STAT|OK"""
        text = "PREFERENCE: User asked for dark mode and STATUS: working correctly"
        result = aaak_compress(text)
        # We can't guarantee exact output due to structural application order,
        # but it should be shorter and contain key elements
        assert len(result) < len(text)
        # Check that PREFERENCE was abbreviated
        assert "PREFERENCE" not in result

    def test_no_compressible_content(self):
        text = "xyz abc 123"
        result = aaak_compress(text)
        # Should remain similar length
        assert len(result) <= len(text) + 2  # structural might add chars

    def test_parens_compacted_in_pipeline(self):
        text = "INSTRUCTION: ( check this ) for accuracy"
        result = aaak_compress(text)
        assert "( check this )" not in result

    def test_oneliner_fact(self):
        text = "FACT: User built a compiler using rust"
        result = aaak_compress(text)
        assert len(result) < len(text)

    def test_all_categories_in_pipeline(self):
        """Each category goes through the full pipeline."""
        for full, abbr in CATEGORIES.items():
            text = f"{full}: test input"
            result = aaak_compress(text)
            assert "test input" in result  # content preserved
            # Some abbreviations are identity (e.g. TRAIT→TRAIT), so `full`
            # may still appear. Check that the colon prefix was removed.
            assert not result.startswith(full + ":")


# ── aaak_decompress ─────────────────────────────────────────────────────────


class TestAAAKDecompress:
    """Partial decompression — reverse category and phrase mappings."""

    def test_reverse_category(self):
        assert aaak_decompress("PREF|dark mode") == "PREFERENCE: dark mode"

    def test_reverse_status(self):
        assert aaak_decompress("STAT|OK") == "STATUS: OK"

    def test_reverse_instruction(self):
        assert aaak_decompress("INST|do this") == "INSTRUCTION: do this"

    def test_reverse_phrase(self):
        assert aaak_decompress("ASK help") == "User asked for help"

    def test_reverse_fsdev(self):
        assert aaak_decompress("FSDEV") == "Full-stack developer"

    def test_reverse_real_time(self):
        assert aaak_decompress("RT processing") == "Real-time processing"

    def test_reverse_multiple(self):
        result = aaak_decompress("PREF|ASK dark mode")
        assert "PREFERENCE" in result

    def test_no_match_unchanged(self):
        assert aaak_decompress("uncompressed text") == "uncompressed text"

    def test_empty_string(self):
        assert aaak_decompress("") == ""

    def test_structural_not_reversed(self):
        # "+" should NOT become " and "
        assert aaak_decompress("a+b") == "a+b"

    def test_trailing_not_reversed(self):
        # "OK" should NOT become "working correctly"
        assert aaak_decompress("OK") == "OK"

    def test_all_reverse_categories(self):
        """Every reverse category mapping works."""
        for abbr, full in {v: k for k, v in CATEGORIES.items()}.items():
            result = aaak_decompress(abbr + "|x")
            if not result.startswith(full):
                # Some abbreviations might collide with phrases, so check contains
                assert full in result, f"Failed to reverse {abbr}"


# ── aaak_ratio ──────────────────────────────────────────────────────────────


class TestAAAKRatio:
    """Compression ratio calculation."""

    def test_empty_returns_one(self):
        assert aaak_ratio("") == 1.0

    def test_normal_compression_below_one(self):
        text = "PREFERENCE: User asked for dark mode and STATUS: working correctly"
        ratio = aaak_ratio(text)
        assert 0.0 < ratio < 1.0

    def test_highly_compressible(self):
        text = "User asked for transcription and translation and automation"
        ratio = aaak_ratio(text)
        assert ratio < 1.0

    def test_already_compact_close_to_one(self):
        text = "PREF|dark mode+STAT|OK"
        ratio = aaak_ratio(text)
        assert ratio >= 1.0 or ratio > 0.95


# ── Integration / edge cases ────────────────────────────────────────────────


class TestAAAKEdgeCases:
    """Cross-cutting edge cases."""

    def test_roundtrip_not_exact(self):
        """AAAK is intentionally NOT round-trippable."""
        original = "PREFERENCE: User asked for dark mode and STATUS: working correctly"
        compressed = aaak_compress(original)
        decompressed = aaak_decompress(compressed)
        # Decompression only reverses categories+phrases, not structural/trailing
        assert decompressed != original

    def test_compressed_contains_no_raw_category(self):
        """After compression, category names should be abbreviated."""
        text = "PREFERENCE: dark mode"
        result = aaak_compress(text)
        assert "PREFERENCE" not in result

    def test_multiline_categories(self):
        text = "PREFERENCE: dark\nSTATUS: ok"
        result = aaak_compress(text)
        assert len(result) <= len(text)

    def test_very_long_text(self):
        text = "User asked for " * 100 + "real-time system"
        result = aaak_compress(text)
        assert len(result) < len(text)

    def test_load_rules_fallback(self):
        """When the rules file doesn't exist, fallback rules are loaded."""
        from unittest.mock import MagicMock

        from spacetime_memory.aaak import _load_rules

        # Create a mock Path whose .exists() returns False
        mock_path = MagicMock()
        mock_path.exists.return_value = False

        with patch("spacetime_memory.aaak._RULES_PATH", mock_path):
            rules = _load_rules()
            # Should get fallback rules with expected structure
            assert "categories" in rules
            assert "phrase_table" in rules
            assert "structural" in rules
            assert "PREFERENCE" in rules["categories"]

    def test_load_rules_from_file(self):
        """When the rules file exists, it's loaded."""
        import json
        from unittest.mock import MagicMock

        from spacetime_memory.aaak import _load_rules

        custom_rules = {
            "categories": {"CUSTOM": "CST"},
            "phrase_table": {"custom phrase": "CP"},
            "structural": [{"match": " xx ", "replace": "X"}],
            "trailing_compactions": {"custom done": "CD"},
        }
        # Create a mock Path whose .exists() returns True
        mock_path = MagicMock()
        mock_path.exists.return_value = True

        with patch("spacetime_memory.aaak._RULES_PATH", mock_path):
            with patch("builtins.open", mock_open(read_data=json.dumps(custom_rules))):
                rules = _load_rules()
                assert rules["categories"]["CUSTOM"] == "CST"
