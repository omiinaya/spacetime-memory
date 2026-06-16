"""
Local LLM — bundled local model for offline memory consolidation.

Supports GGUF models via llama-cpp-python for running sleep/consolidation
cycles without network access. Falls back to remote API when no local
model is available.

Usage:
    from spacetime_memory.local_llm import LocalLLM

    llm = LocalLLM(model_path="/path/to/model.gguf")
    summary = llm.summarize("Long text to compress...")

Or auto-detect a downloaded model:
    llm = LocalLLM.auto()  # checks ~/models/, CWD, env var
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default download URLs for recommended models
RECOMMENDED_MODELS = {
    "minicpm5-1b": {
        "url": "https://huggingface.co/bartowski/MiniCPM5-1B-GGUF/resolve/main/MiniCPM5-1B-Q4_K_M.gguf",
        "size_gb": 0.8,
        "description": "MiniCPM5-1B Q4_K_M — smallest capable model, ~800MB",
    },
    "qwen2.5-0.5b": {
        "url": "https://huggingface.co/bartowski/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
        "size_gb": 0.4,
        "description": "Qwen2.5-0.5B Q4 — ultra-light, ~400MB",
    },
}


class LocalLLM:
    """Local GGUF model for offline memory operations.

    Wraps llama-cpp-python with a simple interface for summarization,
    entity extraction, and consolidation tasks.
    """

    def __init__(
        self,
        model_path: str | None = None,
        n_ctx: int = 2048,
        n_threads: int | None = None,
        verbose: bool = False,
    ):
        """
        Args:
            model_path: Path to .gguf model file. If None, tries auto-detect.
            n_ctx: Context window size in tokens.
            n_threads: CPU threads (default: os.cpu_count() // 2).
            verbose: Enable llama.cpp debug output.
        """
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_threads = n_threads or max(1, (os.cpu_count() or 4) // 2)
        self.verbose = verbose
        self._llm: Any = None
        self._available = False

        if model_path and os.path.exists(model_path):
            self._load()

    @classmethod
    def auto(cls, n_ctx: int = 2048) -> LocalLLM:
        """Auto-detect a GGUF model from standard locations.

        Checks:
            1. LOCAL_LLM_MODEL_PATH env var
            2. ~/models/*.gguf
            3. Current directory *.gguf
            4. ~/.cache/hermes/models/*.gguf

        Returns:
            LocalLLM instance (may be unavailable if no model found).
        """
        search_paths = []

        env_path = os.environ.get("LOCAL_LLM_MODEL_PATH", "")
        if env_path and os.path.exists(env_path):
            search_paths.append(env_path)

        search_dirs = [
            Path.home() / "models",
            Path.cwd(),
            Path.home() / ".cache" / "hermes" / "models",
        ]
        for d in search_dirs:
            if d.exists():
                for f in sorted(d.glob("*.gguf")):
                    search_paths.append(str(f))

        for path in search_paths:
            if os.path.exists(path):
                logger.info("Auto-detected local model: %s", path)
                return cls(model_path=path, n_ctx=n_ctx)

        logger.warning("No GGUF model found in standard locations")
        return cls(n_ctx=n_ctx)

    def _load(self):
        """Load the GGUF model via llama-cpp-python."""
        if not self.model_path:
            return
        try:
            from llama_cpp import Llama
            self._llm = Llama(
                model_path=self.model_path,
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
                verbose=self.verbose,
            )
            self._available = True
            logger.info(
                "Loaded local model: %s (ctx=%d, threads=%d)",
                self.model_path, self.n_ctx, self.n_threads,
            )
        except ImportError:
            logger.warning(
                "llama-cpp-python not installed. "
                "Install with: pip install llama-cpp-python"
            )
        except Exception as e:
            logger.warning("Failed to load model %s: %s", self.model_path, e)

    @property
    def available(self) -> bool:
        """Whether a local model is loaded and ready."""
        return self._available and self._llm is not None

    def generate(
        self,
        prompt: str,
        max_tokens: int = 256,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        """Generate text from a prompt.

        Args:
            prompt: The input prompt.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature (0.0 = deterministic).
            stop: Stop sequences.

        Returns:
            Generated text, or empty string if unavailable.

        Raises:
            RuntimeError: If no model is loaded.
        """
        if not self.available:
            raise RuntimeError(
                "No local model loaded. Install llama-cpp-python and provide a .gguf file."
            )

        result = self._llm(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop or [],
            echo=False,
        )
        return result["choices"][0]["text"].strip()

    def summarize(
        self,
        content: str,
        max_length: int = 200,
    ) -> str:
        """Summarize a block of memory content.

        Args:
            content: Text content to summarize.
            max_length: Target summary length in characters.

        Returns:
            Summary string, or original content truncated if unavailable.
        """
        if not self.available or len(content) < 100:
            return content[:max_length] + ("..." if len(content) > max_length else "")

        prompt = (
            "Summarize the following text in 2-3 concise sentences. "
            "Focus on the key facts and main points.\n\n"
            f"Text:\n{content[:2000]}\n\n"
            "Summary:"
        )

        try:
            return self.generate(prompt, max_tokens=100, temperature=0.2)
        except Exception as e:
            logger.warning("Local summarization failed: %s", e)
            # Fallback: truncated content
            return content[:max_length] + "..." if len(content) > max_length else content

    def extract_entities(
        self,
        content: str,
    ) -> list[dict[str, str]]:
        """Extract named entities from content.

        Args:
            content: Text to analyze.

        Returns:
            List of ``{name, type}`` dicts (person/org/product/technology).
        """
        if not self.available:
            return []

        prompt = (
            "Extract named entities from the following text. "
            "Return a JSON array with objects containing 'name' and 'type' fields. "
            "Types: person, org, product, technology, other.\n\n"
            f"Text:\n{content[:1500]}\n\n"
            "JSON:"
        )

        try:
            import json as _json
            raw = self.generate(prompt, max_tokens=200, temperature=0.1, stop=["\n\n"])
            # Try to extract JSON array
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                return _json.loads(raw[start:end])
            return []
        except Exception as e:
            logger.warning("Local entity extraction failed: %s", e)
            return []

    @staticmethod
    def download_model(
        model_name: str = "minicpm5-1b",
        output_dir: str | None = None,
    ) -> str | None:
        """Download a recommended GGUF model from HuggingFace.

        Args:
            model_name: Key from RECOMMENDED_MODELS (minicpm5-1b or qwen2.5-0.5b).
            output_dir: Directory to save the model (default: ~/models/).

        Returns:
            Path to downloaded model, or None on failure.
        """
        if model_name not in RECOMMENDED_MODELS:
            logger.error("Unknown model: %s. Available: %s",
                         model_name, list(RECOMMENDED_MODELS.keys()))
            return None

        model_info = RECOMMENDED_MODELS[model_name]
        url = model_info["url"]
        filename = url.split("/")[-1]

        out_dir = Path(output_dir) if output_dir else Path.home() / "models"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename

        if out_path.exists():
            logger.info("Model already downloaded: %s", out_path)
            return str(out_path)

        try:
            from urllib.request import urlretrieve
            logger.info("Downloading %s (%s)...", model_name, model_info["description"])
            urlretrieve(url, out_path)
            logger.info("Downloaded to: %s", out_path)
            return str(out_path)
        except ImportError:
            logger.warning("urllib not available — install Python stdlib or use wget/curl")
        except Exception as e:
            logger.warning("Download failed: %s", e)
            if out_path.exists():
                out_path.unlink()  # remove partial download

        return None
