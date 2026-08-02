"""Standalone search helper functions extracted from _memories_search.py.

Provides embedding parsing, cosine similarity, BM25 scoring, query
tokenization, and context formatting — all pure functions with no
dependency on the ClientBase or any mixin class.
"""
from __future__ import annotations

import json
import math
from typing import Any

# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------


def reciprocal_rank_fusion(
    per_strat: dict[str, list[dict]],
    k: int = 60,
    top_k: int = 100,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion — combines ranked lists without score normalization.

    RRF is more robust than min-max fusion when strategies have very different
    score distributions (e.g. semantic cosine scores [0-1] vs BM25 scores [0-20]
    vs substring match scores [0-0.1]).

    Args:
        per_strat: Dict mapping strategy name to list of result dicts with "entity_id"
        k: RRF constant (default 60 — standard from the original paper)
        top_k: Max results to return

    Returns:
        Fused results sorted by RRF score descending, with "fused_score" key populated.
    """
    entity_map: dict[str, dict[str, Any]] = {}
    entity_strategies: dict[str, list[str]] = {}

    for strategy, items in per_strat.items():
        if not items:
            continue
        # Sort by score descending, assign ranks
        sorted_items = sorted(items, key=lambda x: float(x.get("score", 0.0)), reverse=True)
        for rank, item in enumerate(sorted_items):
            eid = item.get("entity_id") or item.get("id") or f"item_{rank}"
            if eid not in entity_map:
                entity_map[eid] = dict(item)
                entity_map[eid]["fused_score"] = 0.0
                entity_strategies[eid] = []
            entity_map[eid]["fused_score"] += 1.0 / (k + rank)
            entity_strategies[eid].append(strategy)

    # Sort by fused score descending
    fused = sorted(entity_map.values(), key=lambda x: -x["fused_score"])
    for item in fused:
        eid = item.get("entity_id") or item.get("id", "")
        item["strategies"] = entity_strategies.get(eid, [])
    return fused[:top_k]


def parse_embedding_json(emb_json: str) -> list[float]:
    """Parse an embedding JSON string into a list of floats.

    Handles common edge cases (empty string, ``[]``, ``null``) gracefully.

    Args:
        emb_json: JSON string of a float array, e.g. ``"[0.1, 0.2, ...]"``.

    Returns:
        List of floats.  Returns an empty list on any parse failure.
    """
    if not emb_json or emb_json in ("[]", "null", ""):
        return []
    try:
        parsed = json.loads(emb_json)
        if isinstance(parsed, list) and all(isinstance(x, (int, float)) for x in parsed):
            return [float(x) for x in parsed]
        return []
    except (ValueError, TypeError, json.JSONDecodeError):
        return []


def cosine_similarity(
    vec1: list[float],
    vec2: list[float],
    epsilon: float = 1e-12,
) -> float:
    """Compute cosine similarity between two embedding vectors.

    Both vectors must have the same length.  Returns a clamped value in
    ``[0.0, 1.0]`` (negative similarities are clamped to zero).

    Args:
        vec1: First embedding vector.
        vec2: Second embedding vector.
        epsilon: Small threshold to treat a vector as zero-magnitude.

    Returns:
        Cosine similarity in ``[0.0, 1.0]``.  Returns ``0.0`` if either
        vector is empty, zero, or the lengths don't match.
    """
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(x * x for x in vec1))
    norm2 = math.sqrt(sum(x * x for x in vec2))
    if norm1 < epsilon or norm2 < epsilon:
        return 0.0
    return max(0.0, min(1.0, dot / (norm1 * norm2)))


# ---------------------------------------------------------------------------
# BM25 scoring helpers
# ---------------------------------------------------------------------------


def bm25_idf(doc_count: int, term_freq: int) -> float:
    """Compute BM25 inverse-document-frequency for a term.

    Uses the standard ``log(1 + (N - n + 0.5) / (n + 0.5))`` formulation.

    Args:
        doc_count: Total number of documents in the corpus.
        term_freq: Number of documents containing the term.

    Returns:
        IDF value.  Returns ``0.0`` if ``term_freq <= 0``.
    """
    if term_freq <= 0 or doc_count <= 0:
        return 0.0
    return math.log(1.0 + (doc_count - term_freq + 0.5) / (term_freq + 0.5))


def bm25_score(
    term_freq: int,
    doc_len: int,
    avg_doc_len: float,
    idf: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    """Compute BM25 score for a single term in a document.

    Args:
        term_freq: Frequency of the term in the document.
        doc_len: Length of the document (in tokens).
        avg_doc_len: Average document length across the corpus.
        idf: IDF value for the term (see :func:`bm25_idf`).
        k1: Saturation parameter (default 1.5).
        b: Length-normalisation parameter (default 0.75).

    Returns:
        BM25 score contribution for this term.
    """
    if doc_len <= 0 or avg_doc_len <= 0:
        return 0.0
    tf_norm = term_freq / (k1 * (1.0 - b + b * doc_len / avg_doc_len) + term_freq)
    return idf * tf_norm


# ---------------------------------------------------------------------------
# Query tokenisation
# ---------------------------------------------------------------------------

_DEFAULT_STOPWORDS: set[str] = {
    "a", "an", "the", "is", "are", "was", "were",
    "be", "been", "who", "what", "where", "when", "why", "how",
    "which", "do", "does", "did", "has", "have", "had",
    "can", "will", "would", "tell", "me", "about",
    "of", "in", "on", "at", "to", "for", "with",
    "and", "or", "not", "we", "our", "us",
    "i", "you", "they", "it", "its", "s",
    "that", "this", "there", "from",
}


def tokenize_query(query: str, stopwords: set[str] | None = None) -> list[str]:
    """Tokenize a search query into keywords, removing stopwords & punctuation.

    Splits on whitespace, lowercases, strips trailing punctuation, and
    filters out stopwords and single-character tokens.

    Args:
        query: The raw search query string.
        stopwords: Set of stopwords to filter.  Defaults to a built-in
            English stopword list if ``None``.

    Returns:
        List of cleaned keyword tokens (lowercased).
    """
    if not query:
        return []
    sw = stopwords if stopwords is not None else _DEFAULT_STOPWORDS
    _PUNCTUATION = "?,.:;!\"'"
    keywords = []
    for w in query.split():
        cleaned = w.lower().rstrip(_PUNCTUATION)
        if len(cleaned) > 1 and cleaned not in sw:
            keywords.append(cleaned)
    return keywords


# ---------------------------------------------------------------------------
# Context formatting
# ---------------------------------------------------------------------------


def make_context_json(
    rows: list[dict[str, Any]],
    max_chars: int = 4000,
    *,
    include_fields: tuple[str, ...] = (
        "memory_content",
        "content",
        "snippet",
        "entity_type",
    ),
) -> str:
    """Format search-result rows into a compact JSON string for LLM context.

    Args:
        rows: Search-result dicts (e.g. from :meth:`SearchMixin.search`).
        max_chars: Maximum character length for the resulting JSON string.
        include_fields: Which fields to include from each result row.

    Returns:
        A JSON string of the trimmed result list, truncated to *max_chars*
        with ``...`` appended if truncated.
    """
    results: list[dict[str, Any]] = []
    for row in rows:
        entry: dict[str, Any] = {}
        for field in include_fields:
            if row.get(field):
                entry[field] = row[field]
        if entry:
            results.append(entry)
    text = json.dumps(results, ensure_ascii=False)
    if len(text) > max_chars:
        text = text[:max_chars] + "..."
    return text
