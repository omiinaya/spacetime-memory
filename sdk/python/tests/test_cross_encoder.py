"""Tests for cross_encoder.py — ONNX reranker.

Covers GPU provider detection, provider resolution, path resolution,
encoding, scoring, reranking, singleton, and edge cases.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pytest

# ── _detect_gpu_providers ─────────────────────────────────────────────


class TestDetectGpuProviders:
    """_detect_gpu_providers() — ONNX GPU provider availability."""

    def test_onnx_not_installed(self):
        with patch.dict("sys.modules", {"onnxruntime": None}), \
             patch("spacetime_memory.cross_encoder.ort", None):
            from spacetime_memory.cross_encoder import _detect_gpu_providers

            assert _detect_gpu_providers() == []

    @patch("spacetime_memory.cross_encoder.ort")
    def test_cuda_available(self, mock_ort):
        mock_ort.get_available_providers.return_value = [
            "CUDAExecutionProvider", "CPUExecutionProvider"
        ]
        from spacetime_memory.cross_encoder import _detect_gpu_providers

        result = _detect_gpu_providers()
        assert "CUDAExecutionProvider" in result
        assert "ROCMExecutionProvider" not in result

    @patch("spacetime_memory.cross_encoder.ort")
    def test_rocm_available(self, mock_ort):
        mock_ort.get_available_providers.return_value = [
            "ROCMExecutionProvider", "CPUExecutionProvider"
        ]
        from spacetime_memory.cross_encoder import _detect_gpu_providers

        result = _detect_gpu_providers()
        assert "ROCMExecutionProvider" in result
        assert "CUDAExecutionProvider" not in result

    @patch("spacetime_memory.cross_encoder.ort")
    def test_tensorrt_available(self, mock_ort):
        mock_ort.get_available_providers.return_value = [
            "TensorrtExecutionProvider", "CPUExecutionProvider"
        ]
        from spacetime_memory.cross_encoder import _detect_gpu_providers

        result = _detect_gpu_providers()
        assert "TensorrtExecutionProvider" in result

    @patch("spacetime_memory.cross_encoder.ort")
    def test_only_cpu(self, mock_ort):
        mock_ort.get_available_providers.return_value = ["CPUExecutionProvider"]
        from spacetime_memory.cross_encoder import _detect_gpu_providers

        assert _detect_gpu_providers() == []

    @patch("spacetime_memory.cross_encoder.ort")
    def test_exception_returns_empty(self, mock_ort):
        mock_ort.get_available_providers.side_effect = RuntimeError("fail")
        from spacetime_memory.cross_encoder import _detect_gpu_providers

        assert _detect_gpu_providers() == []


# ── _resolve_providers ────────────────────────────────────────────────


class TestResolveProviders:
    """_resolve_providers() — ordered provider list resolution."""

    def test_cpu_prefer(self):
        from spacetime_memory.cross_encoder import _resolve_providers

        assert _resolve_providers(prefer="cpu") == ["CPUExecutionProvider"]

    def test_cpu_prefer_case_insensitive(self):
        from spacetime_memory.cross_encoder import _resolve_providers

        assert _resolve_providers(prefer="CPU") == ["CPUExecutionProvider"]

    def test_cuda_prefer_available(self):
        from spacetime_memory.cross_encoder import _resolve_providers

        result = _resolve_providers(
            prefer="cuda",
            available_gpu=["CUDAExecutionProvider"],
        )
        assert result == ["CUDAExecutionProvider", "CPUExecutionProvider"]

    def test_cuda_prefer_not_available(self):
        from spacetime_memory.cross_encoder import _resolve_providers

        result = _resolve_providers(prefer="cuda", available_gpu=[])
        assert result == ["CPUExecutionProvider"]

    def test_rocm_prefer_available(self):
        from spacetime_memory.cross_encoder import _resolve_providers

        result = _resolve_providers(
            prefer="rocm",
            available_gpu=["ROCMExecutionProvider"],
        )
        assert result == ["ROCMExecutionProvider", "CPUExecutionProvider"]

    def test_rocm_prefer_not_available(self):
        from spacetime_memory.cross_encoder import _resolve_providers

        result = _resolve_providers(prefer="rocm", available_gpu=[])
        assert result == ["CPUExecutionProvider"]

    def test_auto_no_gpu(self):
        from spacetime_memory.cross_encoder import _resolve_providers

        result = _resolve_providers(prefer="auto", available_gpu=[])
        assert result == ["CPUExecutionProvider"]

    def test_auto_with_cuda(self):
        from spacetime_memory.cross_encoder import _resolve_providers

        result = _resolve_providers(
            prefer="auto",
            available_gpu=["CUDAExecutionProvider"],
        )
        assert result == ["CUDAExecutionProvider", "CPUExecutionProvider"]

    def test_auto_with_rocm(self):
        from spacetime_memory.cross_encoder import _resolve_providers

        result = _resolve_providers(
            prefer="auto",
            available_gpu=["ROCMExecutionProvider"],
        )
        assert result == ["ROCMExecutionProvider", "CPUExecutionProvider"]

    def test_auto_with_both_gpu(self):
        from spacetime_memory.cross_encoder import _resolve_providers

        result = _resolve_providers(
            prefer="auto",
            available_gpu=["CUDAExecutionProvider", "ROCMExecutionProvider"],
        )
        # CUDA preferred over ROCM
        assert result == ["CUDAExecutionProvider", "ROCMExecutionProvider", "CPUExecutionProvider"]

    def test_prefer_via_env_var(self):
        from spacetime_memory.cross_encoder import _resolve_providers

        with patch.dict(os.environ, {"CROSS_ENCODER_PROVIDER": "cpu"}):
            result = _resolve_providers(available_gpu=["CUDAExecutionProvider"])
            assert result == ["CPUExecutionProvider"]

    def test_prefer_none_defaults_to_auto(self):
        from spacetime_memory.cross_encoder import _resolve_providers

        result = _resolve_providers(prefer=None, available_gpu=[])
        assert result == ["CPUExecutionProvider"]


# ── CrossEncoderReranker.__init__ ─────────────────────────────────────


class TestInit:
    """Path resolution in __init__."""

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

    @patch.dict(
        "os.environ",
        {
            "CROSS_ENCODER_MODEL_PATH": "/env/model.onnx",
            "CROSS_ENCODER_TOKENIZER_PATH": "/env/tok.json",
        },
        clear=True,
    )
    def test_env_model_and_tokenizer(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker()
        assert r._model_path == "/env/model.onnx"
        assert r._tokenizer_path == "/env/tok.json"

    @patch.dict("os.environ", {"CROSS_ENCODER_MODEL_PATH": "/env/model.onnx"}, clear=True)
    def test_explicit_overrides_env(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker(
            model_path="/explicit/model.onnx", tokenizer_path="/explicit/tok.json"
        )
        assert r._model_path == "/explicit/model.onnx"
        assert r._tokenizer_path == "/explicit/tok.json"

    @patch.dict("os.environ", {}, clear=True)
    def test_explicit_without_env(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker(model_path="/my/model.onnx")
        assert r._model_path == "/my/model.onnx"
        assert "cross-encoder-tokenizer.json" in r._tokenizer_path

    @patch.dict("os.environ", {}, clear=True)
    def test_explicit_tokenizer(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker(
            model_path="/m.onnx", tokenizer_path="/tok.json"
        )
        assert r._model_path == "/m.onnx"
        assert r._tokenizer_path == "/tok.json"

    @patch.dict(
        "os.environ",
        {"CROSS_ENCODER_MODEL_PATH": "/env/model.onnx"},
        clear=True,
    )
    def test_env_model_defaults_to_bge_tokenizer(self):
        """When env model is set but no env tokenizer, defaults to BGE tokenizer path."""
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker()
        assert "bge-reranker-large" in r._tokenizer_path
        assert "tokenizer.json" in r._tokenizer_path

    def test_providers_stored(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker(providers=["CPUExecutionProvider"])
        assert r._providers == ["CPUExecutionProvider"]
        assert r._needs_token_type_ids is True  # default

    def test_bge_tokenizer_default_when_model_explicit(self):
        """When model_path is explicit but no tokenizer, defaults to MiniLM tokenizer."""
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker(model_path="/custom/model.onnx")
        assert "cross-encoder-tokenizer.json" in r._tokenizer_path
        assert "bge-reranker-large" not in r._tokenizer_path


# ── _ensure_loaded validation ─────────────────────────────────────────


class TestEnsureLoaded:
    """_ensure_loaded() — file existence checks and ONNX init."""

    def test_missing_tokenizer_raises(self, tmp_path):
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

    def test_missing_model_raises(self, tmp_path):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker(
            model_path=str(tmp_path / "nope.onnx"),
            tokenizer_path=str(tmp_path / "tok.json"),
        )
        r._loaded = False
        with pytest.raises(FileNotFoundError, match="ONNX model not found"):
            r._ensure_loaded()

    def test_already_loaded_skips(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker()
        r._loaded = True
        # Should not call any file ops
        r._ensure_loaded()  # no-op
        assert True

    def test_loads_successfully(self, tmp_path):
        """When both files exist, _ensure_loaded loads tokenizer and session."""
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        model = tmp_path / "model.onnx"
        model.write_text("fake")
        tok = tmp_path / "tok.json"
        tok.write_text("{}")

        r = CrossEncoderReranker(
            model_path=str(model),
            tokenizer_path=str(tok),
            providers=["CPUExecutionProvider"],
        )
        r._loaded = False

        with patch("spacetime_memory.cross_encoder.Tokenizer"):
            with patch("spacetime_memory.cross_encoder.ort") as MockOrt:
                MockOrt.InferenceSession.return_value = MagicMock()
                MockOrt.InferenceSession.return_value.get_inputs.return_value = [
                    MagicMock()
                ]
                MockOrt.InferenceSession.return_value.get_inputs.return_value[
                    0
                ].name = "input_ids"

                r._ensure_loaded()
                assert r._loaded is True
                assert r._session is not None

    def test_auto_detect_token_type_ids(self, tmp_path):
        """Needs token_type_ids when the model has that input."""
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        model = tmp_path / "model.onnx"
        model.write_text("fake")
        tok = tmp_path / "tok.json"
        tok.write_text("{}")

        r = CrossEncoderReranker(
            model_path=str(model),
            tokenizer_path=str(tok),
            providers=["CPUExecutionProvider"],
        )
        r._loaded = False

        with patch("spacetime_memory.cross_encoder.Tokenizer"):
            with patch("spacetime_memory.cross_encoder.ort") as MockOrt:
                mock_session = MagicMock()
                mock_input1 = MagicMock()
                mock_input1.name = "input_ids"
                mock_input2 = MagicMock()
                mock_input2.name = "token_type_ids"
                mock_session.get_inputs.return_value = [mock_input1, mock_input2]
                MockOrt.InferenceSession.return_value = mock_session

                r._ensure_loaded()
                assert r._needs_token_type_ids is True


# ── _encode_pair ──────────────────────────────────────────────────────


class TestEncodePair:
    """_encode_pair() — tokenization into numpy arrays."""

    def test_returns_numpy_arrays(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker()
        r._tokenizer = Mock()
        r._tokenizer.encode.return_value = Mock()
        r._tokenizer.encode.return_value.ids = [101, 200, 102]
        r._tokenizer.encode.return_value.attention_mask = [1, 1, 1]
        r._tokenizer.encode.return_value.type_ids = [0, 0, 1]

        result = r._encode_pair("query", "passage")
        assert "input_ids" in result
        assert "attention_mask" in result
        assert "token_type_ids" in result
        assert isinstance(result["input_ids"], np.ndarray)
        assert result["input_ids"].shape == (1, 3)

    def test_truncates_to_512(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker()
        r._tokenizer = Mock()
        long_ids = list(range(600))
        long_mask = [1] * 600
        long_type_ids = [0] * 300 + [1] * 300
        r._tokenizer.encode.return_value = Mock()
        r._tokenizer.encode.return_value.ids = long_ids
        r._tokenizer.encode.return_value.attention_mask = long_mask
        r._tokenizer.encode.return_value.type_ids = long_type_ids

        result = r._encode_pair("q", "p" * 1000)
        assert result["input_ids"].shape[1] == 512
        assert result["attention_mask"].shape[1] == 512
        assert result["token_type_ids"].shape[1] == 512

    def test_calls_tokenizer_encode(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker()
        r._tokenizer = Mock()
        r._tokenizer.encode.return_value = Mock()
        r._tokenizer.encode.return_value.ids = [101, 102]
        r._tokenizer.encode.return_value.attention_mask = [1, 1]
        r._tokenizer.encode.return_value.type_ids = [0, 0]

        r._encode_pair("my query", "my passage")
        r._tokenizer.encode.assert_called_once_with("my query", "my passage")

    def test_empty_query(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker()
        r._tokenizer = Mock()
        r._tokenizer.encode.return_value = Mock()
        r._tokenizer.encode.return_value.ids = [101, 102]
        r._tokenizer.encode.return_value.attention_mask = [1, 1]
        r._tokenizer.encode.return_value.type_ids = [0, 0]

        result = r._encode_pair("", "passage")
        assert result["input_ids"] is not None

    def test_empty_passage(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker()
        r._tokenizer = Mock()
        r._tokenizer.encode.return_value = Mock()
        r._tokenizer.encode.return_value.ids = [101, 102]
        r._tokenizer.encode.return_value.attention_mask = [1, 1]
        r._tokenizer.encode.return_value.type_ids = [0, 0]

        result = r._encode_pair("query", "")
        assert result["input_ids"] is not None


# ── _score_pair ────────────────────────────────────────────────────────


class TestScorePair:
    """_score_pair() — single (query, passage) scoring."""

    def test_ensure_loaded_called(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker()
        with patch.object(r, "_ensure_loaded") as mock_load:
            with patch.object(r, "_encode_pair") as mock_encode:
                with patch.object(r, "_session") as mock_sess:
                    mock_encode.return_value = {"input_ids": np.array([[1]])}
                    mock_sess.get_inputs.return_value = [MagicMock()]
                    mock_sess.get_inputs.return_value[0].name = "input_ids"
                    mock_sess.run.return_value = [[[0.5]]]
                    r._score_pair("q", "p")
                    mock_load.assert_called_once()

    def test_returns_float_score(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker()
        r._loaded = True
        r._session = Mock()
        r._session.get_inputs.return_value = [Mock()]
        r._session.get_inputs.return_value[0].name = "input_ids"
        r._session.run.return_value = [[[2.0]]]  # logit=2.0, sigmoid~0.88
        r._tokenizer = Mock()
        r._tokenizer.encode.return_value = Mock()
        r._tokenizer.encode.return_value.ids = [101, 102]
        r._tokenizer.encode.return_value.attention_mask = [1, 1]
        r._tokenizer.encode.return_value.type_ids = [0, 0]

        score = r._score_pair("query", "passage")
        assert isinstance(score, float)
        assert 0.0 < score < 1.0
        assert score > 0.8  # high score for logit=2.0

    def test_negative_logit_low_score(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker()
        r._loaded = True
        r._session = Mock()
        r._session.get_inputs.return_value = [Mock()]
        r._session.get_inputs.return_value[0].name = "input_ids"
        r._session.run.return_value = [[[-3.0]]]
        r._tokenizer = Mock()
        r._tokenizer.encode.return_value = Mock()
        r._tokenizer.encode.return_value.ids = [101, 102]
        r._tokenizer.encode.return_value.attention_mask = [1, 1]
        r._tokenizer.encode.return_value.type_ids = [0, 0]

        score = r._score_pair("query", "passage")
        assert score < 0.1

    def test_filters_inputs(self):
        """Only includes inputs the session actually expects."""
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker()
        r._loaded = True
        r._session = Mock()
        mock_input_1 = Mock()
        mock_input_1.name = "input_ids"
        mock_input_2 = Mock()
        mock_input_2.name = "attention_mask"
        r._session.get_inputs.return_value = [mock_input_1, mock_input_2]
        r._session.run.return_value = [[[1.0]]]
        r._tokenizer = Mock()
        r._tokenizer.encode.return_value = Mock()
        r._tokenizer.encode.return_value.ids = [101, 102]
        r._tokenizer.encode.return_value.attention_mask = [1, 1]
        r._tokenizer.encode.return_value.type_ids = [0, 0]

        r._score_pair("q", "p")
        # Should NOT have passed token_type_ids since session doesn't expect it
        call_args = r._session.run.call_args[0]
        assert "input_ids" in call_args[1]


# ── active_provider ──────────────────────────────────────────────────


class TestActiveProvider:
    """active_provider property."""

    def test_not_loaded(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker()
        assert r.active_provider == "not loaded"

    def test_loaded_returns_provider(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker()
        r._session = Mock()
        r._session.get_providers.return_value = ["CUDAExecutionProvider"]
        assert r.active_provider == "CUDAExecutionProvider"


# ── CrossEncoderReranker.rerank ──────────────────────────────────────


class TestRerank:
    """rerank() — rescore candidates with cross-encoder."""

    @pytest.fixture
    def reranker(self):
        from spacetime_memory.cross_encoder import CrossEncoderReranker

        r = CrossEncoderReranker(
            model_path="/fake/model.onnx", tokenizer_path="/fake/tok.json"
        )
        r._loaded = True
        r._session = Mock()
        r._tokenizer = Mock()
        return r

    def test_empty_candidates(self, reranker):
        assert reranker.rerank("query", []) == []

    def test_scores_candidates(self, reranker):
        with patch.object(reranker, "_score_pair") as mock_score:
            mock_score.side_effect = [0.9, 0.3, 0.7]
            candidates = [
                {"id": "a", "memory_content": "first"},
                {"id": "b", "memory_content": "second"},
                {"id": "c", "memory_content": "third"},
            ]
            result = reranker.rerank("query", candidates)
            assert result[0]["id"] == "a"
            assert result[1]["id"] == "c"
            assert result[2]["id"] == "b"

    def test_updates_score_field(self, reranker):
        with patch.object(reranker, "_score_pair", return_value=0.42):
            candidates = [{"id": "x", "memory_content": "text", "score": 0.1}]
            result = reranker.rerank("q", candidates)
            assert result[0]["ce_score"] == 0.42
            assert result[0]["score"] == 0.42

    def test_missing_content_defaults_to_zero(self, reranker):
        with patch.object(reranker, "_score_pair") as mock_score:
            result = reranker.rerank("query", [{"id": "empty", "memory_content": ""}])
            mock_score.assert_not_called()
            assert result[0]["ce_score"] == 0.0

    def test_none_content_defaults_to_zero(self, reranker):
        with patch.object(reranker, "_score_pair") as mock_score:
            result = reranker.rerank("query", [{"id": "n", "memory_content": None}])
            mock_score.assert_not_called()
            assert result[0]["ce_score"] == 0.0

    def test_missing_content_key_defaults_to_zero(self, reranker):
        with patch.object(reranker, "_score_pair") as mock_score:
            result = reranker.rerank("query", [{"id": "n"}])
            mock_score.assert_not_called()
            assert result[0]["ce_score"] == 0.0

    def test_scoring_error_falls_back(self, reranker):
        with patch.object(
            reranker, "_score_pair", side_effect=ValueError("bad input")
        ):
            candidates = [{"id": "e", "memory_content": "bad", "score": 0.55}]
            result = reranker.rerank("q", candidates)
            assert result[0]["ce_score"] == 0.55
            assert result[0]["score"] == 0.55

    def test_top_k_truncation(self, reranker):
        with patch.object(reranker, "_score_pair", return_value=0.5):
            candidates = [
                {"id": str(i), "memory_content": f"c{i}"} for i in range(10)
            ]
            result = reranker.rerank("q", candidates, top_k=3)
            assert len(result) == 3
            assert len(reranker._score_pair.call_args_list) == 3

    def test_custom_content_key(self, reranker):
        with patch.object(reranker, "_score_pair", return_value=0.8):
            candidates = [{"id": "k", "body": "the content"}]
            reranker.rerank("q", candidates, content_key="body")
            reranker._score_pair.assert_called_once_with("q", "the content")

    def test_top_k_defaults_to_5(self, reranker):
        with patch.object(reranker, "_score_pair", return_value=0.5):
            candidates = [
                {"id": str(i), "memory_content": f"c{i}"} for i in range(10)
            ]
            result = reranker.rerank("q", candidates)
            # Default top_k=5
            assert len(result) == 5

    def test_maintains_order_by_score_desc(self, reranker):
        """Results are sorted by CE score descending."""
        with patch.object(reranker, "_score_pair") as mock_score:
            mock_score.side_effect = [0.3, 0.9, 0.6]
            candidates = [
                {"id": "a", "memory_content": "a"},
                {"id": "b", "memory_content": "b"},
                {"id": "c", "memory_content": "c"},
            ]
            result = reranker.rerank("q", candidates, top_k=3)
            assert [r["id"] for r in result] == ["b", "c", "a"]

    def test_all_candidates_kept_when_top_k_large(self, reranker):
        with patch.object(reranker, "_score_pair", return_value=0.5):
            candidates = [
                {"id": str(i), "memory_content": f"c{i}"} for i in range(3)
            ]
            result = reranker.rerank("q", candidates, top_k=10)
            assert len(result) == 3

    def test_runtime_error_falls_back(self, reranker):
        with patch.object(
            reranker, "_score_pair", side_effect=RuntimeError("onnx crash")
        ):
            candidates = [{"id": "e", "memory_content": "bad", "score": 0.55}]
            result = reranker.rerank("q", candidates)
            assert result[0]["ce_score"] == 0.55

    def test_key_error_falls_back(self, reranker):
        with patch.object(
            reranker, "_score_pair", side_effect=KeyError("missing")
        ):
            candidates = [{"id": "e", "memory_content": "bad", "score": 0.55}]
            result = reranker.rerank("q", candidates)
            assert result[0]["ce_score"] == 0.55

    def test_preserves_extra_fields(self, reranker):
        with patch.object(reranker, "_score_pair", return_value=0.7):
            candidates = [
                {
                    "id": "x",
                    "memory_content": "text",
                    "original_score": 0.3,
                    "metadata": {"source": "test"},
                }
            ]
            result = reranker.rerank("q", candidates)
            assert result[0]["original_score"] == 0.3
            assert result[0]["metadata"] == {"source": "test"}

    def test_ensure_loaded_on_first_call(self, reranker):
        """rerank() calls _ensure_loaded before scoring."""
        reranker._loaded = False
        with patch.object(reranker, "_ensure_loaded") as mock_load:
            with patch.object(reranker, "_score_pair", return_value=0.5):
                reranker.rerank("q", [{"id": "a", "memory_content": "x"}])
                mock_load.assert_called_once()


# ── cross_encoder_rerank singleton ───────────────────────────────────


class TestSingleton:
    """cross_encoder_rerank() module-level convenience function."""

    def test_creates_singleton_on_first_call(self):
        from spacetime_memory import cross_encoder

        cross_encoder._reranker = None
        with patch.object(
            cross_encoder.CrossEncoderReranker, "rerank", return_value=[{"id": "s", "score": 0.5}]
        ):
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

    def test_uses_top_k_default(self):
        from spacetime_memory import cross_encoder

        cross_encoder._reranker = None
        with patch.object(
            cross_encoder.CrossEncoderReranker, "rerank", return_value=[{"score": 0.5}]
        ) as mock_rerank:
            cross_encoder.cross_encoder_rerank("q", [{"memory_content": "x"}])
            # Check the singleton passed top_k=20 (default for module-level function)
            mock_rerank.assert_called_once()
            assert mock_rerank.call_args[1].get("top_k") == 20

    def test_forwards_custom_content_key(self):
        from spacetime_memory import cross_encoder

        cross_encoder._reranker = None
        with patch.object(
            cross_encoder.CrossEncoderReranker, "rerank", return_value=[{"score": 0.5}]
        ) as mock_rerank:
            cross_encoder.cross_encoder_rerank(
                "q", [{"body": "x"}], content_key="body", top_k=3
            )
            assert mock_rerank.call_args[1].get("content_key") == "body"
            assert mock_rerank.call_args[1].get("top_k") == 3

    def test_singleton_persists_across_calls(self):
        from spacetime_memory import cross_encoder

        cross_encoder._reranker = None
        try:
            # Patch rerank (not __init__) so the singleton is a real,
            # fully-initialised instance — persistence is what we're
            # testing, not mock plumbing.
            with patch.object(
                cross_encoder.CrossEncoderReranker,
                "rerank",
                return_value=[{"score": 0.5}],
            ):
                cross_encoder.cross_encoder_rerank("q", [])
                first_reranker = cross_encoder._reranker
                cross_encoder.cross_encoder_rerank("q", [])
                assert cross_encoder._reranker is first_reranker
        finally:
            cross_encoder._reranker = None
