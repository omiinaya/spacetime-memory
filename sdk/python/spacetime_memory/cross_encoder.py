"""ONNX cross-encoder reranker for search results.

Uses ``cross-encoder/ms-marco-MiniLM-L-6-v2`` exported to ONNX —
zero PyTorch dependency. Tokenizer loaded via the ``tokenizers`` library
(already installed by the Rust embedder sidecar). Thread affinity warnings
are fixed by setting explicit ``intra_op_num_threads`` on the ONNX session.

Install dependencies::

    pip install spacetime-memory[rerank]

Usage::

    from spacetime_memory.cross_encoder import CrossEncoderReranker
    reranker = CrossEncoderReranker()
    reranked = reranker.rerank("query text", [candidate_dicts])
"""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

_MODEL_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "server", "embedder", "model")
)
_DEFAULT_MODEL_PATH = os.path.join(_MODEL_DIR, "ms-marco-MiniLM-L-6-v2-cross.onnx")
_DEFAULT_TOKENIZER_PATH = os.path.join(_MODEL_DIR, "cross-encoder-tokenizer.json")
_BGE_MODEL_PATH = os.path.join(_MODEL_DIR, "bge-reranker-large", "onnx", "model.onnx")
_BGE_TOKENIZER_PATH = os.path.join(_MODEL_DIR, "bge-reranker-large", "tokenizer.json")


class CrossEncoderReranker:
    """ONNX cross-encoder that scores (query, candidate) pairs.

    Lazily loads the model and tokenizer on first use so importing the
    module is cheap.
    """

    def __init__(
        self,
        model_path: str | None = None,
        tokenizer_path: str | None = None,
    ) -> None:
        # Default: MiniLM (fast, proven). BGE-reranker-large is ~20× slower
        # and only viable with GPU — opt in via CROSS_ENCODER_MODEL_PATH env var.
        _env_model = os.environ.get("CROSS_ENCODER_MODEL_PATH", "")
        _env_tok = os.environ.get("CROSS_ENCODER_TOKENIZER_PATH", "")
        if _env_model:
            self._model_path = model_path or _env_model
            self._tokenizer_path = tokenizer_path or _env_tok or _BGE_TOKENIZER_PATH
        elif model_path:
            self._model_path = model_path
            self._tokenizer_path = tokenizer_path or _DEFAULT_TOKENIZER_PATH
        else:
            self._model_path = _DEFAULT_MODEL_PATH
            self._tokenizer_path = _DEFAULT_TOKENIZER_PATH
        self._session: Any = None
        self._tokenizer: Any = None
        self._loaded = False
        self._needs_token_type_ids = True  # MiniLM default; BGE doesn't

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return

        from tokenizers import Tokenizer
        import onnxruntime as ort

        if not os.path.exists(self._model_path):
            raise FileNotFoundError(
                f"Cross-encoder ONNX model not found at {self._model_path}. "
                f"Download it from HuggingFace: "
                f"cross-encoder/ms-marco-MiniLM-L-6-v2 (onnx/model.onnx)"
            )
        if not os.path.exists(self._tokenizer_path):
            raise FileNotFoundError(
                f"Cross-encoder tokenizer not found at {self._tokenizer_path}. "
                f"Download the tokenizer files from HuggingFace: "
                f"cross-encoder/ms-marco-MiniLM-L-6-v2 (tokenizer.json)"
            )

        logger.info("Loading cross-encoder tokenizer: %s", self._tokenizer_path)
        self._tokenizer = Tokenizer.from_file(self._tokenizer_path)

        # Explicit thread count prevents onnxruntime from trying to set
        # per-thread CPU affinity (pthread_setaffinity_np), which fails in
        # container environments where the full CPU mask isn't available.
        sess_opts = ort.SessionOptions()
        sess_opts.intra_op_num_threads = 4
        sess_opts.inter_op_num_threads = 1

        logger.info("Loading cross-encoder ONNX model: %s", self._model_path)
        self._session = ort.InferenceSession(
            self._model_path,
            sess_options=sess_opts,
            providers=["CPUExecutionProvider"],
        )
        self._loaded = True
        logger.info(
            "Cross-encoder ready (inputs: %s)",
            [i.name for i in self._session.get_inputs()],
        )
        # Auto-detect: BGE models don't use token_type_ids
        self._needs_token_type_ids = any(
            i.name == "token_type_ids" for i in self._session.get_inputs()
        )

    def _encode_pair(self, query: str, passage: str) -> dict[str, np.ndarray]:
        """Tokenize a (query, passage) pair into ONNX-ready numpy arrays.

        Uses the ``tokenizers`` library directly (no PyTorch / transformers
        dependency).  The library handles the ``[CLS] query [SEP] passage [SEP]``
        template and produces ``type_ids`` (0 for query segment, 1 for passage).
        """
        encoding = self._tokenizer.encode(query, passage)
        # Truncate to 512 tokens (BERT max)
        max_len = 512
        ids = encoding.ids[:max_len]
        mask = encoding.attention_mask[:max_len]
        type_ids = encoding.type_ids[:max_len]

        return {
            "input_ids": np.array([ids], dtype=np.int64),
            "attention_mask": np.array([mask], dtype=np.int64),
            "token_type_ids": np.array([type_ids], dtype=np.int64),
        }

    def _score_pair(self, query: str, passage: str) -> float:
        """Score a single (query, passage) pair."""
        self._ensure_loaded()

        ort_inputs = {
            k: v
            for k, v in self._encode_pair(query, passage).items()
            if k in {i.name for i in self._session.get_inputs()}
        }

        outputs = self._session.run(None, ort_inputs)
        # Cross-encoder output is a single logit → sigmoid for [0, 1] score
        logit = float(outputs[0][0][0])
        score = 1.0 / (1.0 + np.exp(-logit))
        return float(score)

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        content_key: str = "memory_content",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Rerank search candidates using cross-encoder scores.

        Args:
            query: The original search query.
            candidates: List of result dicts (must have ``content_key`` field).
            content_key: Key in each candidate dict for the text to score.
            top_k: Maximum number of candidates to score (cross-encoder is
                   O(n) per query — keep small).

        Returns:
            Candidates re-sorted by cross-encoder score, with ``score``
            updated and ``ce_score`` added.
        """
        if not candidates:
            return candidates

        self._ensure_loaded()

        # Score each candidate
        scored: list[tuple[dict[str, Any], float]] = []
        for r in candidates[:top_k]:
            content = r.get(content_key, "")
            if not content:
                scored.append((r, 0.0))
                continue
            try:
                s = self._score_pair(query, content)
                scored.append((r, s))
            except (RuntimeError, ValueError, KeyError):  # ONNX inference or tokenizer failure
                logger.exception("Cross-encoder scoring failed for content len=%d", len(content))
                scored.append((r, r.get("score", 0.0)))

        # ── Re-rank by cross-encoder score ──
        # Sort scored candidates by CE score descending and update
        # the 'score' field so downstream consumers (LLM reranker,
        # client.search() result ordering) use CE-scored ranking.
        scored.sort(key=lambda x: x[1], reverse=True)
        result = []
        for r, ce_score in scored:
            r["ce_score"] = ce_score
            r["score"] = ce_score  # replace fusion score with CE score
            result.append(r)
        return result


# ---------------------------------------------------------------------------
# Module-level singleton (lazy)
# ---------------------------------------------------------------------------

_reranker: CrossEncoderReranker | None = None


def cross_encoder_rerank(
    query: str,
    candidates: list[dict[str, Any]],
    content_key: str = "memory_content",
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """Convenience wrapper — rerank candidates with the cross-encoder singleton."""
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoderReranker()
    return _reranker.rerank(query, candidates, content_key=content_key, top_k=top_k)
