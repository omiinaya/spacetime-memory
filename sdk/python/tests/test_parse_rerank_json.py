"""
Unit tests for _parse_rerank_json() — all 6 fallback strategies.
"""

import pytest
from spacetime_memory.client import _parse_rerank_json


# ── Strategy 1: Direct JSON parse ──────────────────────────────────────


class TestStrategy1DirectParse:
    """Strategy 1: json.loads with direct list."""

    def test_valid_json_list(self):
        result = _parse_rerank_json('[{"index":0,"score":9.0}]')
        assert result == [{"index": 0, "score": 9.0}]

    def test_naked_string_fails_all(self):
        """A JSON string (not list/dict) fails all strategies."""
        with pytest.raises(ValueError):
            _parse_rerank_json('"just a string"')


# ── Strategy 2: Find JSON array boundaries ─────────────────────────────


class TestStrategy2ArrayBoundaries:
    """Strategy 2: Regex search for [...] in content."""

    def test_array_embedded_in_text(self):
        """JSON array embedded in markdown/text."""
        content = 'Sure! Here are the scores:\n\n```json\n[{"index":0,"score":8.0},{"index":1,"score":5.0}]\n```'
        result = _parse_rerank_json(content)
        assert result == [{"index": 0, "score": 8.0}, {"index": 1, "score": 5.0}]

    def test_array_with_trailing_text(self):
        content = '[{"index":0,"score":9.0}] Some extra text here'
        result = _parse_rerank_json(content)
        assert result == [{"index": 0, "score": 9.0}]

    def test_array_with_leading_text(self):
        content = 'The results are: [{"index":0,"score":7.5}]'
        result = _parse_rerank_json(content)
        assert result == [{"index": 0, "score": 7.5}]

    def test_array_decode_error_caught(self):
        """Regex finds [ but inner JSON is malformed."""
        content = "Found: [bad json that won't parse]"
        with pytest.raises(ValueError):
            _parse_rerank_json(content)


# ── Strategy 3: Strict=False raw_decode ────────────────────────────────


class TestStrategy3RawDecode:
    """Strategy 3: JSONDecoder.raw_decode with dict→list wrapping."""

    def test_dict_wrapped_to_list(self):
        """raw_decode finds a dict, wraps it in a list."""
        content = '{"index":0,"score":7.0} extra garbage'
        result = _parse_rerank_json(content)
        assert result == [{"index": 0, "score": 7.0}]

    def test_raw_decode_list(self):
        """raw_decode finds a list directly."""
        content = '[{"index":0,"score":6.0}] trailing'
        result = _parse_rerank_json(content)
        assert result == [{"index": 0, "score": 6.0}]


# ── Strategy 4: Aggressive salvage ─────────────────────────────────────


class TestStrategy4AggressiveSalvage:
    """Strategy 4: Strip trailing commas, fix unquoted keys, score-object."""

    def test_trailing_commas_stripped(self):
        """Trailing commas before ] are stripped."""
        content = '[{"index":0,"score":8.0},]'
        result = _parse_rerank_json(content)
        assert result == [{"index": 0, "score": 8.0}]

    def test_isolated_score_object(self):
        """Single object with 'score' key found in text."""
        content = 'blah blah {"index":0,"score":9.5} more text'
        result = _parse_rerank_json(content)
        assert result == [{"index": 0, "score": 9.5}]

    def test_score_object_no_array(self):
        """When array extraction fails, finds single score object."""
        content = 'Here is a result: {"index":1,"score":4.0} end'
        result = _parse_rerank_json(content)
        assert result == [{"index": 1, "score": 4.0}]


# ── Strategy 5: Dict wrapper ───────────────────────────────────────────


class TestStrategy5DictWrapper:
    """Strategy 5: LLM returned {'scores': [...], ...} or similar."""

    def test_scores_key(self):
        content = '{"scores":[{"index":0,"score":8.0},{"index":1,"score":3.0}]}'
        result = _parse_rerank_json(content)
        assert len(result) == 2
        assert result[0]["index"] == 0

    def test_results_key(self):
        content = '{"results":[{"index":0,"score":9.0}]}'
        result = _parse_rerank_json(content)
        assert result == [{"index": 0, "score": 9.0}]

    def test_rankings_key(self):
        content = '{"rankings":[{"index":0,"score":7.0}]}'
        result = _parse_rerank_json(content)
        assert result == [{"index": 0, "score": 7.0}]

    def test_items_key(self):
        content = '{"items":[{"index":0,"score":6.0}]}'
        result = _parse_rerank_json(content)
        assert result == [{"index": 0, "score": 6.0}]

    def test_data_key(self):
        content = '{"data":[{"index":0,"score":5.0}]}'
        result = _parse_rerank_json(content)
        assert result == [{"index": 0, "score": 5.0}]

    def test_single_object_with_index(self):
        """Dict with 'index' key (not matching scores/results/etc) → wrapped."""
        content = '{"index":0,"score":4.0,"reason":"good"}'
        result = _parse_rerank_json(content)
        assert result == [{"index": 0, "score": 4.0, "reason": "good"}]

    def test_dict_wrapper_decode_error(self):
        """Dict wrapper regex finds { but inner JSON fails."""
        content = "{not valid json at all"
        with pytest.raises(ValueError):
            _parse_rerank_json(content)


# ── Strategy 6: Line-by-line extraction ────────────────────────────────


class TestStrategy6LineByLine:
    """Strategy 6: One JSON object per line."""

    def test_line_by_line(self):
        """Lines prefixed with text so raw_decode fails — forces strategy 6."""
        # Strategy 3 fails because first char '#' is not JSON.
        # Strategy 4b fails because we use "rating" not "score".
        # Strategy 5 fails because multi-line {.*} grab isn't valid JSON.
        content = '# results:\n{"index":0,"rating":9.0}\n{"index":1,"rating":7.0}\n{"index":2,"rating":5.0}'
        result = _parse_rerank_json(content)
        assert len(result) == 3
        assert result[0]["index"] == 0
        assert result[2]["index"] == 2

    def test_lines_with_trailing_commas(self):
        content = '# scores:\n{"index":0,"rating":8.0},\n{"index":1,"rating":4.0},'
        result = _parse_rerank_json(content)
        assert len(result) == 2

    def test_mixed_text_lines_ignored(self):
        """Non-JSON lines are skipped."""
        content = '# output:\n{"index":0,"rating":9.0}\nsome text\n{"index":1,"rating":5.0}'
        result = _parse_rerank_json(content)
        assert len(result) == 2

    def test_no_index_key_skipped(self):
        """Line has valid JSON but no 'index' key → skipped."""
        content = '# data:\n{"name":"bob","value":42}\n{"index":0,"rating":5.0}'
        result = _parse_rerank_json(content)
        assert result == [{"index": 0, "rating": 5.0}]

    def test_line_json_error_skipped(self):
        """One bad line doesn't break extraction."""
        content = '# output:\n{bad json}\n{"index":0,"rating":5.0}'
        result = _parse_rerank_json(content)
        assert result == [{"index": 0, "rating": 5.0}]


# ── All strategies fail ────────────────────────────────────────────────


class TestAllStrategiesFail:
    """When all 6 strategies fail, ValueError is raised."""

    def test_all_fail(self):
        with pytest.raises(ValueError, match="JSON parse failed"):
            _parse_rerank_json("completely invalid content")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            _parse_rerank_json("")

    def test_whitespace_only(self):
        with pytest.raises(ValueError):
            _parse_rerank_json("   \n  \t  ")
