"""Pytest tests for spacetime_memory.local_llm — LocalLLM with mocked deps."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from spacetime_memory.local_llm import RECOMMENDED_MODELS, LocalLLM

# ── Module-level mock for llama_cpp (lazy import inside _load) ─────────


@pytest.fixture(autouse=True)
def _inject_llama_cpp():
    """Inject a mock llama_cpp module into sys.modules.

    local_llm imports ``from llama_cpp import Llama`` inside _load(),
    so we must make llama_cpp importable with a mock Llama class.
    """
    llama_module = types.ModuleType("llama_cpp")
    llama_module.Llama = MagicMock()
    sys.modules["llama_cpp"] = llama_module
    yield
    # Keep in sys.modules for other tests


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_working_llama():
    """Build a Llama mock that returns a valid response dict."""
    instance = MagicMock()
    instance.return_value = {"choices": [{"text": "Mocked response text"}]}
    return instance


@pytest.fixture
def live_llm(tmp_path):
    """LocalLLM instantiated with a real file and mocked Llama load.

    This tests the real _load() path through mocked llama_cpp.
    """
    model_file = tmp_path / "fake_model.gguf"
    model_file.write_text("fake gguf content")

    llama_mock = _make_working_llama()
    sys.modules["llama_cpp"].Llama.return_value = llama_mock

    llm = LocalLLM(model_path=str(model_file))
    return llm


@pytest.fixture
def manual_llm():
    """LocalLLM with _llm and _available set manually (bypasses load)."""
    llm = LocalLLM()
    llm._llm = _make_working_llama()
    llm._available = True
    return llm


# ── LocalLLM.__init__ tests ────────────────────────────────────────────


class TestLocalLLMInit:
    """Construction and auto-load behaviour."""

    def test_default_init_no_path(self):
        llm = LocalLLM()
        assert llm.model_path is None
        assert llm._available is False
        assert llm._llm is None

    def test_init_with_valid_path(self, tmp_path):
        model_file = tmp_path / "model.gguf"
        model_file.write_text("gguf")
        sys.modules["llama_cpp"].Llama.return_value = _make_working_llama()
        llm = LocalLLM(model_path=str(model_file))
        assert llm._available is True
        assert llm._llm is not None
        assert llm.model_path == str(model_file)

    def test_init_with_nonexistent_path(self):
        llm = LocalLLM(model_path="/nonexistent/model.gguf")
        assert llm._available is False

    def test_custom_n_ctx(self):
        llm = LocalLLM(n_ctx=4096)
        assert llm.n_ctx == 4096

    def test_custom_n_threads(self):
        llm = LocalLLM(n_threads=8)
        assert llm.n_threads == 8

    def test_default_n_threads(self):
        llm = LocalLLM()
        assert llm.n_threads >= 1

    def test_verbose_flag(self):
        llm = LocalLLM(verbose=True)
        assert llm.verbose is True

    def test_import_error_graceful(self, tmp_path):
        """If llama_cpp cannot be imported, _load fails gracefully."""
        model_file = tmp_path / "model.gguf"
        model_file.write_text("gguf")
        # Remove llama_cpp from sys.modules to simulate import error
        saved = sys.modules.pop("llama_cpp", None)
        try:
            llm = LocalLLM(model_path=str(model_file))
            assert llm._available is False
        finally:
            if saved:
                sys.modules["llama_cpp"] = saved

    def test_load_exception_graceful(self, tmp_path):
        """Other exceptions during Llama construction are caught."""
        model_file = tmp_path / "model.gguf"
        model_file.write_text("gguf")
        sys.modules["llama_cpp"].Llama.side_effect = RuntimeError("boom")
        llm = LocalLLM(model_path=str(model_file))
        assert llm._available is False
        # Reset side effect
        sys.modules["llama_cpp"].Llama.side_effect = None

    def test_load_early_return_when_no_model_path(self):
        """_load returns early when model_path is None (line 113)."""
        llm = LocalLLM()  # model_path=None, _load not called in __init__
        # Call _load directly — should hit the early return
        llm._load()
        assert llm._available is False
        assert llm._llm is None


# ── LocalLLM.auto() tests ──────────────────────────────────────────────


class TestLocalLLMAuto:
    """auto() classmethod for auto-detecting models."""

    def test_env_var_path(self, monkeypatch, tmp_path):
        model_file = tmp_path / "env_model.gguf"
        model_file.write_text("gguf")
        monkeypatch.setenv("LOCAL_LLM_MODEL_PATH", str(model_file))
        sys.modules["llama_cpp"].Llama.return_value = _make_working_llama()
        llm = LocalLLM.auto()
        assert llm.model_path == str(model_file)
        assert llm._available is True

    def test_env_var_nonexistent_skipped(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LOCAL_LLM_MODEL_PATH", "/nonexistent/model.gguf")
        with patch.object(Path, "home", return_value=tmp_path):
            llm = LocalLLM.auto()
            assert llm._available is False

    def test_home_models_glob(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        model_file = models_dir / "found.gguf"
        model_file.write_text("gguf")
        sys.modules["llama_cpp"].Llama.return_value = _make_working_llama()
        with patch.object(Path, "home", return_value=tmp_path):
            llm = LocalLLM.auto()
            assert llm.model_path == str(model_file)
            assert llm._available is True

    def test_current_dir_glob(self, monkeypatch, tmp_path):
        model_file = tmp_path / "local.gguf"
        model_file.write_text("gguf")
        monkeypatch.chdir(tmp_path)
        sys.modules["llama_cpp"].Llama.return_value = _make_working_llama()
        llm = LocalLLM.auto()
        assert llm._available is True

    def test_cache_dir_glob(self, tmp_path):
        cache_dir = tmp_path / ".cache" / "hermes" / "models"
        cache_dir.mkdir(parents=True)
        model_file = cache_dir / "cached.gguf"
        model_file.write_text("gguf")
        sys.modules["llama_cpp"].Llama.return_value = _make_working_llama()
        with patch.object(Path, "home", return_value=tmp_path):
            llm = LocalLLM.auto()
            assert llm._available is True

    def test_no_model_found(self):
        with patch.object(Path, "home", return_value=Path("/tmp/no_home_dir_12345")):
            llm = LocalLLM.auto()
            assert llm._available is False

    def test_env_beats_glob(self, monkeypatch, tmp_path):
        env_file = tmp_path / "env_first.gguf"
        env_file.write_text("gguf")
        glob_dir = tmp_path / "models"
        glob_dir.mkdir()
        (glob_dir / "second.gguf").write_text("gguf")
        monkeypatch.setenv("LOCAL_LLM_MODEL_PATH", str(env_file))
        sys.modules["llama_cpp"].Llama.return_value = _make_working_llama()
        with patch.object(Path, "home", return_value=tmp_path):
            llm = LocalLLM.auto()
            assert llm.model_path == str(env_file)


# ── LocalLLM.available property ────────────────────────────────────────


class TestAvailable:
    """available property."""

    def test_unloaded_not_available(self):
        llm = LocalLLM()
        assert llm.available is False

    def test_loaded_is_available(self, live_llm):
        assert live_llm.available is True

    def test_null_llm_not_available(self, tmp_path):
        model_file = tmp_path / "model.gguf"
        model_file.write_text("gguf")
        sys.modules["llama_cpp"].Llama.return_value = _make_working_llama()
        llm = LocalLLM(model_path=str(model_file))
        llm._llm = None
        assert llm.available is False


# ── LocalLLM.generate tests ────────────────────────────────────────────


class TestGenerate:
    """generate() method with mocked Llama."""

    def test_generates_text(self, manual_llm):
        result = manual_llm.generate("Hello", max_tokens=100)
        assert result == "Mocked response text"

    def test_unavailable_raises(self):
        llm = LocalLLM()
        with pytest.raises(RuntimeError, match="No local model loaded"):
            llm.generate("prompt")

    def test_passes_parameters(self, manual_llm):
        manual_llm.generate("prompt text", max_tokens=50, temperature=0.5, stop=["END"])
        manual_llm._llm.assert_called_once_with(
            "prompt text",
            max_tokens=50,
            temperature=0.5,
            stop=["END"],
            echo=False,
        )

    def test_default_stop_is_empty_list(self, manual_llm):
        manual_llm.generate("prompt")
        call_kwargs = manual_llm._llm.call_args
        assert call_kwargs[1]["stop"] == []

    def test_strips_response(self, manual_llm):
        manual_llm._llm.return_value = {"choices": [{"text": "  padded response  "}]}
        result = manual_llm.generate("q")
        assert result == "padded response"

    def test_default_temperature(self, manual_llm):
        manual_llm.generate("test")
        call_kwargs = manual_llm._llm.call_args
        assert call_kwargs[1]["temperature"] == 0.3

    def test_default_max_tokens(self, manual_llm):
        manual_llm.generate("test")
        call_kwargs = manual_llm._llm.call_args
        assert call_kwargs[1]["max_tokens"] == 256


# ── LocalLLM.summarize tests ───────────────────────────────────────────


class TestSummarize:
    """summarize() method."""

    def test_unavailable_truncates(self):
        llm = LocalLLM()
        result = llm.summarize("short text")
        assert result == "short text"

    def test_unavailable_truncates_long(self):
        llm = LocalLLM()
        long_text = "x" * 300
        result = llm.summarize(long_text, max_length=100)
        assert len(result) == 103
        assert result.endswith("...")

    def test_unavailable_no_truncation_needed(self):
        llm = LocalLLM()
        result = llm.summarize("hi", max_length=200)
        assert result == "hi"

    def test_short_content_bypasses_llm(self, manual_llm):
        result = manual_llm.summarize("short", max_length=200)
        assert result == "short"
        manual_llm._llm.assert_not_called()

    def test_long_content_uses_llm(self, manual_llm):
        long_text = "word " * 50
        result = manual_llm.summarize(long_text, max_length=200)
        assert result == "Mocked response text"
        manual_llm._llm.assert_called_once()

    def test_boundary_exactly_100(self, manual_llm):
        text = "x" * 100
        result = manual_llm.summarize(text)
        assert result == "Mocked response text"

    def test_boundary_99(self, manual_llm):
        text = "x" * 99
        result = manual_llm.summarize(text)
        assert result == text

    def test_llm_error_fallback(self, manual_llm):
        manual_llm._llm.side_effect = RuntimeError("inference failed")
        long_text = "x" * 200
        result = manual_llm.summarize(long_text, max_length=50)
        assert result == "x" * 50 + "..."

    def test_content_truncated_in_prompt(self, manual_llm):
        long_text = "a " * 1500
        manual_llm.summarize(long_text)
        call_args = manual_llm._llm.call_args
        prompt_text = call_args[0][0]
        content_start = prompt_text.find("Text:\n") + len("Text:\n")
        content_end = prompt_text.find("\n\nSummary:")
        content_in_prompt = prompt_text[content_start:content_end]
        assert len(content_in_prompt) <= 2000

    def test_max_length_respected_on_fallback(self, manual_llm):
        manual_llm._llm.side_effect = RuntimeError("fail")
        long_text = "x" * 500
        result = manual_llm.summarize(long_text, max_length=30)
        assert len(result) == 30 + 3

    def test_max_length_exact_fit_no_ellipsis(self, manual_llm):
        manual_llm._llm.side_effect = RuntimeError("fail")
        result = manual_llm.summarize("hello", max_length=200)
        assert result == "hello"
        assert not result.endswith("...")


# ── LocalLLM.extract_entities tests ────────────────────────────────────


class TestExtractEntities:
    """extract_entities() method."""

    def test_unavailable_returns_empty(self):
        llm = LocalLLM()
        result = llm.extract_entities("some text")
        assert result == []

    def test_extracts_json(self, manual_llm):
        manual_llm._llm.return_value = {
            "choices": [{"text": '[{"name": "Alice", "type": "person"}]'}]
        }
        result = manual_llm.extract_entities("Alice works at Acme")
        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    def test_json_brackets_in_text(self, manual_llm):
        response = (
            "Here are the entities:\n"
            '[{"name": "Acme Corp", "type": "org"}, {"name": "Python", "type": "technology"}]\n'
            "That's all."
        )
        manual_llm._llm.return_value = {"choices": [{"text": response}]}
        result = manual_llm.extract_entities("Acme Corp uses Python")
        assert len(result) == 2
        assert result[0]["name"] == "Acme Corp"
        assert result[1]["name"] == "Python"

    def test_no_json_brackets(self, manual_llm):
        manual_llm._llm.return_value = {"choices": [{"text": "No entities found."}]}
        result = manual_llm.extract_entities("some text")
        assert result == []

    def test_invalid_json(self, manual_llm):
        manual_llm._llm.return_value = {"choices": [{"text": "[{invalid json}]"}]}
        result = manual_llm.extract_entities("text")
        assert result == []

    def test_llm_error_returns_empty(self, manual_llm):
        manual_llm._llm.side_effect = RuntimeError("fail")
        result = manual_llm.extract_entities("text")
        assert result == []

    def test_stop_sequence_passed(self, manual_llm):
        manual_llm._llm.return_value = {"choices": [{"text": "[]"}]}
        manual_llm.extract_entities("text")
        call_kwargs = manual_llm._llm.call_args
        assert call_kwargs[1]["stop"] == ["\n\n"]

    def test_content_truncated_to_1500(self, manual_llm):
        long_text = "x " * 1000
        manual_llm._llm.return_value = {"choices": [{"text": "[]"}]}
        manual_llm.extract_entities(long_text)
        call_args = manual_llm._llm.call_args
        prompt_str = call_args[0][0]
        content_idx = prompt_str.find("Text:\n") + 6
        content = prompt_str[content_idx:].split("\n\nJSON:")[0]
        assert len(content) <= 1500


# ── LocalLLM.download_model tests ──────────────────────────────────────


class TestDownloadModel:
    """download_model() static method."""

    def test_valid_model_url(self, tmp_path):
        out_dir = tmp_path / "models"
        with patch("urllib.request.urlretrieve") as mock_retrieve:
            mock_retrieve.side_effect = lambda url, path: Path(path).write_text("data")
            result = LocalLLM.download_model("minicpm5-1b", output_dir=str(out_dir))
            mock_retrieve.assert_called_once()
            call_args = mock_retrieve.call_args[0]
            assert "MiniCPM5-1B-Q4_K_M.gguf" in call_args[0]
            assert str(out_dir) in str(call_args[1])
            assert result is not None

    def test_invalid_model_name(self):
        result = LocalLLM.download_model("nonexistent-model")
        assert result is None

    def test_default_output_dir(self, tmp_path):
        """Default output dir is ~/models/."""
        out_dir = tmp_path / "home" / "models"
        out_dir.mkdir(parents=True)

        with (
            patch("urllib.request.urlretrieve") as mock_retrieve,
            patch.object(Path, "home", return_value=tmp_path / "home"),
        ):
            mock_retrieve.side_effect = lambda url, path: Path(path).write_text("data")
            LocalLLM.download_model("qwen2.5-0.5b")
            call_args = mock_retrieve.call_args[0]
            assert "models" in str(call_args[1])

    def test_already_downloaded(self, tmp_path):
        out_dir = tmp_path / "models"
        out_dir.mkdir()
        filename = RECOMMENDED_MODELS["minicpm5-1b"]["url"].split("/")[-1]
        existing = out_dir / filename
        existing.write_text("existing model")

        with patch("urllib.request.urlretrieve") as mock_retrieve:
            result = LocalLLM.download_model("minicpm5-1b", output_dir=str(out_dir))
            mock_retrieve.assert_not_called()
            assert result == str(existing)

    def test_import_error_returns_none(self, monkeypatch):
        """If urllib.request cannot be imported, returns None (line 280)."""
        import builtins

        _original_import = builtins.__import__

        def blocking_import(name, *args, **kwargs):
            if name == "urllib.request":
                raise ImportError("Mocked import error for testing")
            return _original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocking_import)
        result = LocalLLM.download_model("minicpm5-1b")
        assert result is None

    def test_download_exception_cleans_up(self, tmp_path):
        out_dir = tmp_path / "models"
        out_dir.mkdir()

        def fake_retrieve(url, path):
            Path(path).write_text("partial")
            raise OSError("network error")

        with patch("urllib.request.urlretrieve", side_effect=fake_retrieve):
            result = LocalLLM.download_model("minicpm5-1b", output_dir=str(out_dir))
            assert result is None
            filename = RECOMMENDED_MODELS["minicpm5-1b"]["url"].split("/")[-1]
            assert not (out_dir / filename).exists()

    def test_qwen_model_info(self):
        info = RECOMMENDED_MODELS["qwen2.5-0.5b"]
        assert "url" in info
        assert "size_gb" in info
        assert "Qwen" in info["url"]
        assert info["size_gb"] == 0.4

    def test_returns_path_on_success(self, tmp_path):
        out_dir = tmp_path / "models"
        out_dir.mkdir()
        filename = RECOMMENDED_MODELS["minicpm5-1b"]["url"].split("/")[-1]
        expected_path = out_dir / filename

        def fake_retrieve(url, path):
            Path(path).write_text("model data")

        with patch("urllib.request.urlretrieve", side_effect=fake_retrieve):
            result = LocalLLM.download_model("minicpm5-1b", output_dir=str(out_dir))
            assert result == str(expected_path)
            assert expected_path.exists()
