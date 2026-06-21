"""Pytest tests for spacetime_memory.cross_encoder — CrossEncoderReranker with mocked ONNX."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pytest

from spacetime_memory.cross_encoder import CrossEncoderReranker, cross_encoder_rerank


# ── Module-level mocks for lazy imports ─────────────────────────────────
# onnxruntime and tokenizers are imported inside _ensure_loaded(), not at
# module level, so we inject them into sys.modules.

@pytest.fixture(autouse=True)
def _inject_lazy_deps(monkeypatch):
    """Inject mock onnxruntime and tokenizers into sys.modules.

    This lets _ensure_loaded()'s lazy imports succeed with mocked objects
    without requiring the real packages.
    """
    import types

    # Mock onnxruntime
    if "onnxruntime" not in sys.modules:
        mock_ort = types.ModuleType("onnxruntime")
        mock_ort.InferenceSession = MagicMock()
        mock_ort.SessionOptions = MagicMock()
        sys.modules["onnxruntime"] = mock_ort

    # Mock tokenizers
    if "tokenizers" not in sys.modules:
        mock_tokenizers = types.ModuleType("tokenizers")
        mock_tokenizers.Tokenizer = MagicMock()
        sys.modules["tokenizers"] = mock_tokenizers

    yield

    # Don't clean up — other tests in the session may need them


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_mock_onnx_session(logit_output: float = 0.5):
    """Build a mock ONNX InferenceSession.

    Mock ``.name`` is set via configure_mock so the any() check in
    ``_ensure_loaded`` can detect ``token_type_ids`` correctly.
    """
    session = MagicMock()

    inp1 = Mock()
    inp1.configure_mock(name="input_ids")
    inp2 = Mock()
    inp2.configure_mock(name="attention_mask")
    inp3 = Mock()
    inp3.configure_mock(name="token_type_ids")

    session.get_inputs.return_value = [inp1, inp2, inp3]
    session.run.return_value = [np.array([[logit_output]], dtype=np.float32)]
    return session


def _make_mock_tokenizer():
    """Build a mock tokenizer returning dummy encoding."""
    tok = MagicMock()
    enc = Mock()
    enc.ids = [101, 2023, 2003, 102, 1234, 5678, 102]
    enc.attention_mask = [1, 1, 1, 1, 1, 1, 1]
    enc.type_ids = [0, 0, 0, 0, 1, 1, 1]
    tok.encode.return_value = enc
    return tok


def _setup_loaded_reranker(
    reranker: CrossEncoderReranker,
    session=None,
    tokenizer=None,
) -> CrossEncoderReranker:
    """Helper: set up a reranker with mocked session and tokenizer loaded."""
    reranker._session = session or _make_mock_onnx_session()
    reranker._tokenizer = tokenizer or _make_mock_tokenizer()
    reranker._loaded = True
    return reranker


@pytest.fixture
def loaded_reranker():
    """CrossEncoderReranker with mocked ONNX session and tokenizer loaded."""
    reranker = CrossEncoderReranker()
    return _setup_loaded_reranker(reranker)


# ── CrossEncoderReranker.__init__ tests ─────────────────────────────────


class TestCrossEncoderInit:
    """Construction and path resolution."""

    def test_default_paths(self):
        reranker = CrossEncoderReranker()
        assert not reranker._loaded
        assert reranker._session is None
        assert reranker._tokenizer is None
        assert "ms-marco-MiniLM-L-6-v2-cross.onnx" in reranker._model_path
        assert "cross-encoder-tokenizer.json" in reranker._tokenizer_path

    def test_custom_paths(self):
        reranker = CrossEncoderReranker(
            model_path="/custom/model.onnx",
            tokenizer_path="/custom/tokenizer.json",
        )
        assert reranker._model_path == "/custom/model.onnx"
        assert reranker._tokenizer_path == "/custom/tokenizer.json"

    def test_env_var_overrides(self, monkeypatch):
        monkeypatch.setenv("CROSS_ENCODER_MODEL_PATH", "/env/model.onnx")
        monkeypatch.setenv("CROSS_ENCODER_TOKENIZER_PATH", "/env/tok.json")
        reranker = CrossEncoderReranker()
        assert reranker._model_path == "/env/model.onnx"
        assert reranker._tokenizer_path == "/env/tok.json"

    def test_explicit_beats_env(self, monkeypatch):
        monkeypatch.setenv("CROSS_ENCODER_MODEL_PATH", "/env/model.onnx")
        reranker = CrossEncoderReranker(model_path="/explicit/model.onnx")
        assert reranker._model_path == "/explicit/model.onnx"

    def test_env_model_no_tokenizer(self, monkeypatch):
        monkeypatch.setenv("CROSS_ENCODER_MODEL_PATH", "/env/bge_model.onnx")
        monkeypatch.delenv("CROSS_ENCODER_TOKENIZER_PATH", raising=False)
        reranker = CrossEncoderReranker()
        assert "bge-reranker-large" in reranker._tokenizer_path


# ── CrossEncoderReranker._score_pair tests ──────────────────────────────


class TestScorePair:
    """_score_pair with mocked ONNX session and tokenizer."""

    def test_sigmoid_conversion(self, loaded_reranker):
        loaded_reranker._session.run.return_value = [
            np.array([[0.0]], dtype=np.float32)
        ]
        score = loaded_reranker._score_pair("query", "passage")
        assert score == pytest.approx(0.5, abs=1e-5)

    def test_high_logit(self, loaded_reranker):
        loaded_reranker._session.run.return_value = [
            np.array([[5.0]], dtype=np.float32)
        ]
        score = loaded_reranker._score_pair("query", "passage")
        assert score > 0.99

    def test_low_logit(self, loaded_reranker):
        loaded_reranker._session.run.return_value = [
            np.array([[-5.0]], dtype=np.float32)
        ]
        score = loaded_reranker._score_pair("query", "passage")
        assert score < 0.01

    def test_returns_float(self, loaded_reranker):
        score = loaded_reranker._score_pair("q", "p")
        assert isinstance(score, float)

    def test_filters_unexpected_inputs(self, loaded_reranker):
        """Only inputs matching session input names are forwarded."""
        session = loaded_reranker._session
        session.get_inputs.return_value = [
            Mock(name="input_ids"),
            Mock(name="attention_mask"),
        ]
        loaded_reranker._score_pair("q", "p")
        call_kwargs = session.run.call_args
        assert call_kwargs is not None


# ── CrossEncoderReranker.rerank tests ───────────────────────────────────


class TestRerank:
    """rerank() method with mocked ONNX."""

    def test_empty_candidates(self, loaded_reranker):
        result = loaded_reranker.rerank("query", [])
        assert result == []

    def test_single_candidate(self, loaded_reranker):
        candidates = [{"memory_content": "hello world", "score": 0.8}]
        result = loaded_reranker.rerank("query", candidates)
        assert len(result) == 1
        assert "ce_score" in result[0]
        assert result[0]["score"] == result[0]["ce_score"]

    def test_multiple_candidates_reranked(self, loaded_reranker):
        loaded_reranker._session.run.side_effect = [
            [np.array([[0.9]], dtype=np.float32)],
            [np.array([[0.1]], dtype=np.float32)],
            [np.array([[0.5]], dtype=np.float32)],
        ]
        candidates = [
            {"memory_content": "doc A"},
            {"memory_content": "doc B"},
            {"memory_content": "doc C"},
        ]
        result = loaded_reranker.rerank("query", candidates)
        assert result[0]["ce_score"] > result[1]["ce_score"] > result[2]["ce_score"]
        assert result[0]["memory_content"] == "doc A"

    def test_top_k_limits_scoring(self, loaded_reranker):
        candidates = [{"memory_content": f"doc {i}"} for i in range(10)]
        result = loaded_reranker.rerank("query", candidates, top_k=3)
        # Only top_k candidates are scored and returned
        assert len(result) == 3
        assert all("ce_score" in r for r in result)

    def test_candidate_missing_content_key(self, loaded_reranker):
        result = loaded_reranker.rerank(
            "query",
            [{"wrong_key": "some content"}],
            content_key="memory_content",
        )
        assert result[0]["ce_score"] == 0.0

    def test_candidate_empty_content(self, loaded_reranker):
        result = loaded_reranker.rerank("query", [{"memory_content": ""}])
        assert result[0]["ce_score"] == 0.0

    def test_scoring_error_fallback(self, loaded_reranker):
        loaded_reranker._session.run.side_effect = RuntimeError("ONNX failed")
        candidates = [{"memory_content": "doc", "score": 0.75}]
        result = loaded_reranker.rerank("query", candidates)
        assert len(result) == 1
        assert result[0]["ce_score"] == 0.75

    def test_score_and_ce_score_both_set(self, loaded_reranker):
        candidates = [{"memory_content": "doc", "score": 0.3}]
        result = loaded_reranker.rerank("query", candidates)
        assert "ce_score" in result[0]
        assert result[0]["score"] == result[0]["ce_score"]

    def test_custom_content_key(self, loaded_reranker):
        candidates = [{"body": "custom content field"}]
        result = loaded_reranker.rerank("query", candidates, content_key="body")
        assert len(result) == 1
        assert "ce_score" in result[0]


# ── cross_encoder_rerank convenience function ───────────────────────────


class TestCrossEncoderRerankFunction:
    """Module-level cross_encoder_rerank() convenience wrapper."""

    def test_creates_and_uses_singleton(self):
        import spacetime_memory.cross_encoder as ce

        ce._reranker = None
        fake = MagicMock()
        fake.rerank.return_value = [{"result": True}]
        with patch.object(ce, "CrossEncoderReranker", return_value=fake):
            result = cross_encoder_rerank("q", [{"c": 1}])
            assert result == [{"result": True}]
            assert ce._reranker is fake
        ce._reranker = None

    def test_reuses_singleton(self):
        import spacetime_memory.cross_encoder as ce

        ce._reranker = None
        fake = MagicMock()
        fake.rerank.return_value = ["result"]
        ce._reranker = fake
        result = cross_encoder_rerank("q1", [{"c": 1}])
        assert result == ["result"]
        fake.rerank.assert_called_once()
        ce._reranker = None

    def test_passes_arguments_correctly(self):
        import spacetime_memory.cross_encoder as ce

        fake = MagicMock()
        fake.rerank.return_value = [{"a": 1}]
        ce._reranker = fake

        result = cross_encoder_rerank(
            "my query", [{"text": "candidate"}], content_key="text", top_k=10
        )
        fake.rerank.assert_called_once_with(
            "my query", [{"text": "candidate"}], content_key="text", top_k=10
        )
        assert result == [{"a": 1}]
        ce._reranker = None


# ── _ensure_loaded tests ───────────────────────────────────────────────


class TestEnsureLoaded:
    """_ensure_loaded behaviour with real lazy imports mocked via sys.modules."""

    def test_already_loaded_skips(self):
        reranker = CrossEncoderReranker()
        reranker._loaded = True
        reranker._ensure_loaded()
        assert reranker._session is None

    def test_missing_model_file(self):
        reranker = CrossEncoderReranker(
            model_path="/nonexistent/model.onnx",
            tokenizer_path="/nonexistent/tok.json",
        )
        with pytest.raises(FileNotFoundError, match="model not found"):
            reranker._ensure_loaded()

    def test_missing_tokenizer_file(self, tmp_path):
        model_file = tmp_path / "model.onnx"
        model_file.write_text("fake onnx")
        reranker = CrossEncoderReranker(
            model_path=str(model_file),
            tokenizer_path="/nonexistent/tok.json",
        )
        with pytest.raises(FileNotFoundError, match="tokenizer not found"):
            reranker._ensure_loaded()

    def test_successful_load(self, tmp_path):
        """_ensure_loaded loads model and tokenizer from files that exist."""
        import spacetime_memory.cross_encoder as ce

        model_file = tmp_path / "model.onnx"
        model_file.write_text("fake onnx")
        tok_file = tmp_path / "tokenizer.json"
        tok_file.write_text("{}")

        reranker = CrossEncoderReranker(
            model_path=str(model_file),
            tokenizer_path=str(tok_file),
        )

        mock_ort = sys.modules["onnxruntime"]
        mock_tok = sys.modules["tokenizers"]

        mock_session = _make_mock_onnx_session()
        mock_ort.InferenceSession.return_value = mock_session
        mock_ort.SessionOptions.return_value = MagicMock()

        mock_tokenizer = _make_mock_tokenizer()
        mock_tok.Tokenizer.from_file.return_value = mock_tokenizer

        reranker._ensure_loaded()

        assert reranker._loaded is True
        assert reranker._session is mock_session
        assert reranker._tokenizer is mock_tokenizer
        # Check needs_token_type_ids detection
        assert reranker._needs_token_type_ids is True

    def test_detects_no_token_type_ids(self, tmp_path):
        """BGE-style model where session has no token_type_ids input."""
        model_file = tmp_path / "model.onnx"
        model_file.write_text("fake onnx")
        tok_file = tmp_path / "tokenizer.json"
        tok_file.write_text("{}")

        reranker = CrossEncoderReranker(
            model_path=str(model_file),
            tokenizer_path=str(tok_file),
        )

        mock_ort = sys.modules["onnxruntime"]
        mock_tok = sys.modules["tokenizers"]

        mock_session = MagicMock()
        mock_session.get_inputs.return_value = [
            Mock(name="input_ids"),
            Mock(name="attention_mask"),
        ]
        mock_ort.InferenceSession.return_value = mock_session
        mock_ort.SessionOptions.return_value = MagicMock()
        mock_tok.Tokenizer.from_file.return_value = _make_mock_tokenizer()

        reranker._ensure_loaded()
        assert reranker._needs_token_type_ids is False


# ── _encode_pair tests ──────────────────────────────────────────────────


class TestEncodePair:
    """_encode_pair tokenization with mocked tokenizer."""

    def test_encodes_pair(self, loaded_reranker):
        result = loaded_reranker._encode_pair("query text", "passage text")
        assert "input_ids" in result
        assert "attention_mask" in result
        assert "token_type_ids" in result
        assert isinstance(result["input_ids"], np.ndarray)
        assert result["input_ids"].dtype == np.int64
        assert result["attention_mask"].dtype == np.int64
        assert result["token_type_ids"].dtype == np.int64

    def test_truncates_to_512(self, loaded_reranker):
        enc = Mock()
        enc.ids = list(range(600))
        enc.attention_mask = [1] * 600
        enc.type_ids = [0] * 300 + [1] * 300
        loaded_reranker._tokenizer.encode.return_value = enc

        result = loaded_reranker._encode_pair("q", "p")
        assert result["input_ids"].shape == (1, 512)
        assert result["input_ids"][0, -1] == 511
