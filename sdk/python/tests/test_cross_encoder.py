"""Tests for cross_encoder.py — ONNX reranker."""

import pytest
from unittest.mock import patch, Mock, MagicMock


# ── CrossEncoderReranker.__init__ ────────────────────────────────────────────


class TestInit:
    """Path resolution in __init__."""

    @patch.dict("os.environ", {}, clear=True)
    def test_default_paths(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker()
        assert "ms-marco-MiniLM-L-6-v2-cross.onnx" in r._model_path
        assert "cross-encoder-tokenizer.json" in r._tokenizer_path
        assert r._session is None
        assert r._loaded is False

    @patch.dict("os.environ", {"CROSS_ENCODER_MODEL_PATH": "/env/model.onnx"}, clear=True)
    def test_env_model_path(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker()
        assert r._model_path == "/env/model.onnx"

    @patch.dict("os.environ", {
        "CROSS_ENCODER_MODEL_PATH": "/env/model.onnx",
        "CROSS_ENCODER_TOKENIZER_PATH": "/env/tok.json",
    }, clear=True)
    def test_env_model_and_tokenizer(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker()
        assert r._model_path == "/env/model.onnx"
        assert r._tokenizer_path == "/env/tok.json"

    @patch.dict("os.environ", {"CROSS_ENCODER_MODEL_PATH": "/env/model.onnx"}, clear=True)
    def test_explicit_overrides_env(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker(model_path="/explicit/model.onnx",
                                 tokenizer_path="/explicit/tok.json")
        assert r._model_path == "/explicit/model.onnx"
        assert r._tokenizer_path == "/explicit/tok.json"

    @patch.dict("os.environ", {}, clear=True)
    def test_explicit_without_env(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker(model_path="/my/model.onnx")
        assert r._model_path == "/my/model.onnx"
        assert "cross-encoder-tokenizer.json" in r._tokenizer_path


# ── _ensure_loaded validation ─────────────────────────────────────────────────


class TestEnsureLoaded:
    """_ensure_loaded() — file existence checks."""

    def test_missing_tokenizer_raises(self, tmp_path):
        """When model exists but tokenizer is missing, FileNotFoundError."""
        import os
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        model = tmp_path / "model.onnx"
        model.write_text("fake onnx")
        tokenizer = tmp_path / "no_such_file.json"

        r = CrossEncoderReranker(
            model_path=str(model),
            tokenizer_path=str(tokenizer),
        )
        r._loaded = False
        with pytest.raises(FileNotFoundError, match="tokenizer not found"):
            r._ensure_loaded()


# ── CrossEncoderReranker.rerank ──────────────────────────────────────────────


class TestRerank:
    """rerank() — rescore candidates with cross-encoder."""

    @pytest.fixture
    def reranker(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker
        r = CrossEncoderReranker(model_path="/fake/model.onnx",
                                 tokenizer_path="/fake/tok.json")
        # Prevent real model loading
        r._loaded = True
        r._session = Mock()
        r._tokenizer = Mock()
        return r

    def test_empty_candidates(self, reranker):
        assert reranker.rerank("query", []) == []

    def test_scores_candidates(self, reranker):
        """Scores each candidate and re-sorts by CE score."""
        with patch.object(reranker, "_score_pair") as mock_score:
            mock_score.side_effect = [0.9, 0.3, 0.7]

            candidates = [
                {"id": "a", "memory_content": "first"},
                {"id": "b", "memory_content": "second"},
                {"id": "c", "memory_content": "third"},
            ]
            result = reranker.rerank("query", candidates)

            # Sorted by CE score descending
            assert result[0]["id"] == "a"  # 0.9
            assert result[1]["id"] == "c"  # 0.7
            assert result[2]["id"] == "b"  # 0.3
            assert result[0]["ce_score"] == 0.9
            assert result[0]["score"] == 0.9

    def test_updates_score_field(self, reranker):
        """ce_score and score are both updated."""
        with patch.object(reranker, "_score_pair", return_value=0.42):
            candidates = [{"id": "x", "memory_content": "text", "score": 0.1}]
            result = reranker.rerank("q", candidates)

            assert result[0]["ce_score"] == 0.42
            assert result[0]["score"] == 0.42  # overwritten

    def test_missing_content_defaults_to_zero(self, reranker):
        """Candidates without content get score 0.0."""
        r = Mock()
        r.get.return_value = ""  # empty content
        with patch.object(reranker, "_score_pair") as mock_score:
            result = reranker.rerank("query", [{"id": "empty", "memory_content": ""}])
            mock_score.assert_not_called()
            assert result[0]["ce_score"] == 0.0

    def test_scoring_error_falls_back(self, reranker):
        """ONNX errors fall back to original score."""
        with patch.object(reranker, "_score_pair",
                          side_effect=ValueError("bad input")):
            candidates = [{"id": "e", "memory_content": "bad", "score": 0.55}]
            result = reranker.rerank("q", candidates)

            assert result[0]["ce_score"] == 0.55
            assert result[0]["score"] == 0.55

    def test_top_k_truncation(self, reranker):
        """Only scores top_k candidates."""
        with patch.object(reranker, "_score_pair", return_value=0.5):
            candidates = [
                {"id": str(i), "memory_content": f"c{i}"} for i in range(10)
            ]
            result = reranker.rerank("q", candidates, top_k=3)
            assert len(result) == 3
            assert len(reranker._score_pair.call_args_list) == 3

    def test_custom_content_key(self, reranker):
        """Uses content_key param to extract text."""
        with patch.object(reranker, "_score_pair", return_value=0.8):
            candidates = [{"id": "k", "body": "the content"}]
            result = reranker.rerank("q", candidates, content_key="body")
            reranker._score_pair.assert_called_once_with("q", "the content")


# ── cross_encoder_rerank singleton ───────────────────────────────────────────


class TestSingleton:
    """cross_encoder_rerank() module-level convenience function."""

    def test_creates_singleton_on_first_call(self):
        from spacetime_memory import cross_encoder
        # Reset singleton
        cross_encoder._reranker = None

        with patch.object(cross_encoder.CrossEncoderReranker, "rerank",
                          return_value=[{"id": "s", "score": 0.5}]):
            result = cross_encoder.cross_encoder_rerank("q", [{"memory_content": "x"}])
            assert result == [{"id": "s", "score": 0.5}]
            assert cross_encoder._reranker is not None

    def test_reuses_singleton(self):
        from spacetime_memory import cross_encoder
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker(model_path="/x")
        cross_encoder._reranker = r

        with patch.object(r, "rerank", return_value=[{"score": 1.0}]):
            result = cross_encoder.cross_encoder_rerank("q", [])
            assert result == [{"score": 1.0}]
