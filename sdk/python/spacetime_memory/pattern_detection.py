"""
Pattern Detection — statistical pattern analysis across memory stores.

Detects recurring themes, topic clusters, temporal patterns, and
co-occurrence relationships from stored memories.

Uses zero-LLM heuristics: term frequency analysis, temporal clustering,
and co-mention graph construction.

Integrated via Client.detect_patterns(workspace_id).
"""

from collections import Counter, defaultdict
from typing import Any


def _tokenize(text: str, min_len: int = 3) -> list[str]:
    """Tokenize and filter text to meaningful terms."""
    import re

    tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return [t for t in tokens if len(t) >= min_len]


def detect_temporal_clusters(
    memories: list[dict[str, Any]],
    bucket_minutes: int = 30,
    min_cluster_size: int = 2,
) -> list[dict[str, Any]]:
    """Find temporal clusters — groups of memories stored close together in time.

    Args:
        memories: List of memory dicts with ``created_at`` (unix seconds/microseconds).
        bucket_minutes: Time bucket size for clustering.
        min_cluster_size: Minimum memories per cluster to report.

    Returns:
        List of cluster dicts with ``start_time``, ``end_time``, ``count``, ``ids``.
    """
    if not memories:
        return []

    # Build time buckets
    bucket_secs = bucket_minutes * 60
    buckets: dict[int, list[dict]] = defaultdict(list)

    for m in memories:
        ts = m.get("created_at", 0)
        if ts > 1_000_000_000_000:
            ts = ts / 1_000_000
        bucket_key = int(ts / bucket_secs)
        buckets[bucket_key].append(m)

    clusters = []
    for bucket_key, items in buckets.items():
        if len(items) >= min_cluster_size:
            start = bucket_key * bucket_secs
            clusters.append(
                {
                    "start_time": start,
                    "end_time": start + bucket_secs,
                    "count": len(items),
                    "ids": [m.get("id", "") for m in items],
                    "summary_terms": _extract_common_terms(items, top_n=5),
                }
            )

    clusters.sort(key=lambda c: c["start_time"], reverse=True)
    return clusters


def detect_frequent_terms(
    memories: list[dict[str, Any]],
    top_n: int = 20,
    min_df: int = 2,
) -> list[dict[str, Any]]:
    """Extract the most frequent meaningful terms from a set of memories.

    Args:
        memories: List of memory dicts with ``content`` field.
        top_n: Number of top terms to return.
        min_df: Minimum document frequency (memories containing the term).

    Returns:
        List of ``{term, frequency, doc_count}`` dicts.
    """
    if not memories:
        return []

    doc_freq: Counter = Counter()
    term_freq: Counter = Counter()

    for m in memories:
        content = m.get("content", "")
        tokens = set(_tokenize(content))  # set for doc frequency
        for t in tokens:
            doc_freq[t] += 1
            term_freq[t] += 1  # per-doc count is 1 in doc_freq mode

    # Filter by min document frequency
    frequent = [
        {"term": term, "frequency": term_freq[term], "doc_count": doc_freq[term]}
        for term, count in doc_freq.most_common(top_n * 2)
        if count >= min_df
    ]
    return frequent[:top_n]


def detect_co_occurrences(
    memories: list[dict[str, Any]],
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """Detect term co-occurrence pairs (terms that frequently appear together).

    Args:
        memories: List of memory dicts with ``content`` field.
        top_n: Number of top co-occurrence pairs to return.

    Returns:
        List of ``{term_a, term_b, count, strength}`` dicts.
    """
    if len(memories) < 2:
        return []

    co_occur: Counter = Counter()
    total_docs = 0

    for m in memories:
        content = m.get("content", "")
        tokens = list(set(_tokenize(content)))  # unique terms per doc
        if len(tokens) < 2:
            continue
        total_docs += 1
        tokens.sort()
        for i in range(len(tokens)):
            for j in range(i + 1, len(tokens)):
                pair = (tokens[i], tokens[j])
                co_occur[pair] += 1

    pairs = []
    for (a, b), count in co_occur.most_common(top_n):
        # Strength = co-occurrence count / total docs (Jaccard-like)
        strength = count / total_docs if total_docs > 0 else 0.0
        pairs.append(
            {
                "term_a": a,
                "term_b": b,
                "count": count,
                "strength": round(strength, 3),
            }
        )

    return pairs


def _extract_common_terms(items: list[dict], top_n: int = 5) -> list[str]:
    """Extract most common terms across a group of memory items."""
    all_tokens: Counter = Counter()
    for item in items:
        content = item.get("content", "")
        all_tokens.update(_tokenize(content))
    return [t for t, _ in all_tokens.most_common(top_n)]


def detect_patterns(
    memories: list[dict[str, Any]],
    *,
    include_clusters: bool = True,
    include_terms: bool = True,
    include_co_occur: bool = True,
) -> dict[str, Any]:
    """Run all pattern detection analyses on a set of memories.

    Args:
        memories: List of memory dicts (from Client._query or search).
        include_clusters: Run temporal clustering.
        include_terms: Run frequent term extraction.
        include_co_occur: Run co-occurrence detection.

    Returns:
        Dict with ``temporal_clusters``, ``frequent_terms``, ``co_occurrences``,
        and ``summary`` fields.
    """
    result: dict[str, Any] = {
        "total_memories": len(memories),
        "summary": "",
    }

    if include_clusters:
        result["temporal_clusters"] = detect_temporal_clusters(memories)

    if include_terms:
        result["frequent_terms"] = detect_frequent_terms(memories)

    if include_co_occur:
        result["co_occurrences"] = detect_co_occurrences(memories)

    # Build a human-readable summary
    parts = []
    if result.get("temporal_clusters"):
        parts.append(f"{len(result['temporal_clusters'])} temporal clusters detected")
    if result.get("frequent_terms"):
        top = [t["term"] for t in result["frequent_terms"][:5]]
        parts.append(f"top terms: {', '.join(top)}")
    if result.get("co_occurrences"):
        parts.append(f"{len(result['co_occurrences'])} co-occurrence pairs")
    result["summary"] = "; ".join(parts) if parts else "no significant patterns detected"

    return result
