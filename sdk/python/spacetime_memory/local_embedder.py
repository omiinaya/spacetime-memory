"""Pure-Python ONNX embedder using onnxruntime.

Replaces the Rust ONNX sidecar (tract-onnx serving all-MiniLM-L6-v2).
Tokenization uses HuggingFace ``tokenizers``, inference uses ``onnxruntime``,
and model download uses ``huggingface_hub``.

Matches the exact inference pipeline from ``server/embedder/src/main.rs``:

    1. Tokenize -> input_ids / attention_mask / token_type_ids
    2. ONNX forward -> last_hidden_state (shape ``[1, seq_len, 384]``)
    3. Mean pooling weighted by attention mask
    4. L2 normalization
    5. Return 384-dim ``float32`` vector
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt
    import onnxruntime as ort
    from tokenizers import Tokenizer as HFTokenizer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HF_REPO_ID = "Xenova/all-MiniLM-L6-v2"
HF_MODEL_FILENAME = "onnx/model.onnx"
DEFAULT_MODEL_FILENAME = "all-MiniLM-L6-v2.onnx"
MODEL_DIMENSION = 384
TOKENIZER_ID = "sentence-transformers/all-MiniLM-L6-v2"


def _get_default_model_dir() -> Path:
    """Return the default directory for storing the ONNX model."""
    xdg = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    return Path(xdg) / "spacetime-memory"


# ---------------------------------------------------------------------------
# LocalEmbedder
# ---------------------------------------------------------------------------


class LocalEmbedder:
    """In-process ONNX embedder for all-MiniLM-L6-v2.

    Uses ``onnxruntime`` for inference and HuggingFace ``tokenizers`` for
    tokenization.  The ONNX model is downloaded from HuggingFace Hub on first
    use if not found locally.

    Usage::

        embedder = LocalEmbedder()
        vec = embedder.embed("Hello world")        # list[float] length 384
        batch = embedder.embed_batch(["a", "b"])   # list[list[float]]
    """

    def __init__(self, model_path: str | os.PathLike | None = None) -> None:
        """Initialize the embedder.

        Args:
            model_path: Path to the ONNX model file.  If ``None``, uses
                ``~/.cache/spacetime-memory/all-MiniLM-L6-v2.onnx`` (the
                default location after auto-download).
        """
        self._model_path: Path
        if model_path is not None:
            self._model_path = Path(model_path)
        else:
            default_dir = _get_default_model_dir()
            self._model_path = default_dir / DEFAULT_MODEL_FILENAME

        self._session: ort.InferenceSession | None = None
        self._tokenizer: HFTokenizer | None = None
        self._loaded: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed(self, text: str) -> list[float]:
        """Return a single 384-dim embedding vector for *text*."""
        return self._embed_batch_inner([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings for a list of texts.

        Args:
            texts: List of input strings.

        Returns:
            List of embedding vectors, one per input text.
        """
        if not texts:
            return []
        return self._embed_batch_inner(texts)

    # ------------------------------------------------------------------
    # Lazy-loading helpers
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Load the tokenizer and ONNX session on first call."""
        if self._loaded:
            return

        # Lazy imports -- heavy deps not imported at module level
        try:
            import onnxruntime as ort
        except ImportError:
            raise ImportError(
                "onnxruntime is required for LocalEmbedder. "
                "Install it with: pip install 'spacetime-memory[local-embed]'"
            ) from None

        try:
            from tokenizers import Tokenizer as HFTokenizer
        except ImportError:
            raise ImportError(
                "tokenizers is required for LocalEmbedder. "
                "Install it with: pip install 'spacetime-memory[local-embed]'"
            ) from None

        # ---- Download model if missing ----
        if not self._model_path.exists():
            self._download_model()

        # ---- Load tokenizer ----
        logger.info("Loading tokenizer from %s ...", TOKENIZER_ID)
        self._tokenizer = HFTokenizer.from_pretrained(TOKENIZER_ID)
        logger.info("Tokenizer loaded.")

        # ---- Load ONNX session ----
        logger.info("Loading ONNX model from %s ...", self._model_path)
        so = ort.SessionOptions()
        so.log_severity_level = 3  # suppress ONNX runtime logging
        self._session = ort.InferenceSession(
            str(self._model_path),
            sess_options=so,
            providers=["CPUExecutionProvider"],
        )
        logger.info(
            "ONNX model loaded. Inputs: %s",
            [inp.name for inp in self._session.get_inputs()],
        )
        self._loaded = True

    def _download_model(self) -> None:
        """Download the ONNX model from HuggingFace Hub."""
        try:
            from huggingface_hub import hf_hub_download
        except ImportError:
            raise ImportError(
                "huggingface-hub is required to download the ONNX model. "
                "Install it with: pip install 'spacetime-memory[local-embed]'"
            ) from None

        self._model_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            "Downloading model %s (%s) to %s ...",
            HF_REPO_ID,
            HF_MODEL_FILENAME,
            self._model_path,
        )
        downloaded = hf_hub_download(
            repo_id=HF_REPO_ID,
            filename=HF_MODEL_FILENAME,
        )
        shutil.copy2(downloaded, str(self._model_path))
        size_mb = self._model_path.stat().st_size / (1024 * 1024)
        logger.info("Model downloaded (%.1f MB).", size_mb)

    # ------------------------------------------------------------------
    # Inference internals
    # ------------------------------------------------------------------

    def _embed_batch_inner(self, texts: list[str]) -> list[list[float]]:
        """Run inference for a batch of texts.

        Matches the Rust sidecar pipeline exactly:

        1. Tokenize (``add_special_tokens=True``, matching Rust's
           ``tokenizer.encode(text, true)``)
        2. ONNX forward pass
        3. Mean pooling weighted by ``attention_mask``
        4. L2 normalization
        """
        self._ensure_loaded()

        from typing import cast as _typecast

        import numpy as np

        # Unwrap lazy-loaded objects for type-narrowing
        session = self._session
        tokenizer = self._tokenizer
        assert session is not None and tokenizer is not None

        # Cache input names
        input_ids_name = session.get_inputs()[0].name
        attention_mask_name = session.get_inputs()[1].name
        token_type_ids_name = session.get_inputs()[2].name

        results: list[list[float]] = []

        for text in texts:
            # ---- 1. Tokenize ----
            encoding = tokenizer.encode(text)
            ids: list[int] = encoding.ids
            mask: list[int] = encoding.attention_mask

            seq_len = len(ids)
            if seq_len == 0:
                results.append([0.0] * MODEL_DIMENSION)
                continue

            # Token type IDs are all zeros (matches Rust: ``vec![0i64; ids.len()]``)
            type_ids: list[int] = [0] * seq_len

            # ---- 2. Build ONNX inputs ----
            # Shape: [1, seq_len], dtype: int64 (matches Rust i64)
            inp_ids: npt.NDArray[np.int64] = np.array(
                ids, dtype=np.int64
            ).reshape(1, seq_len)
            attn_mask: npt.NDArray[np.int64] = np.array(
                mask, dtype=np.int64
            ).reshape(1, seq_len)
            tok_type: npt.NDArray[np.int64] = np.array(
                type_ids, dtype=np.int64
            ).reshape(1, seq_len)

            # ---- 3. Run ONNX inference ----
            # Output: last_hidden_state, shape [1, seq_len, 384]
            last_hidden: npt.NDArray[np.float32] = _typecast(
                npt.NDArray[np.float32],
                session.run(
                    None,
                    {
                        input_ids_name: inp_ids,
                        attention_mask_name: attn_mask,
                        token_type_ids_name: tok_type,
                    },
                )[0],
            )

            # ---- 4. Mean pooling weighted by attention mask ----
            # Expand mask to [1, seq_len, 1] for broadcasting against
            # last_hidden [1, seq_len, 384]
            mask_expanded: npt.NDArray[np.float32] = (
                attn_mask.astype(np.float32).reshape(1, seq_len, 1)
            )
            mask_sum: float = float(mask_expanded.sum())

            if mask_sum == 0.0:
                results.append([0.0] * MODEL_DIMENSION)
                continue

            # Weighted sum over sequence dimension, divided by mask_sum
            pooled: npt.NDArray[np.float32] = (
                (last_hidden * mask_expanded).sum(axis=1) / mask_sum
            )  # shape [1, 384]

            # ---- 5. L2 normalize ----
            norm: float = float(np.sqrt((pooled**2).sum()))
            if norm > 0.0:
                pooled = pooled / norm

            results.append(pooled[0].tolist())

        return results
