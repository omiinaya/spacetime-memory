"""
MMR (Maximal Marginal Relevance) Reranking for search result diversity.

Based on Carbonell & Goldstein (1998). Balances relevance and novelty:
  MMR = λ * relevance - (1-λ) * max_similarity_to_already_selected

A λ of 0.7 means 70% relevance, 30% diversity penalty.

Integrated into Client.search() via mmr_lambda parameter.
"""

import math
from collections.abc import Sequence
from typing import Any


def _jaccard_similarity(a: str, b: str) -> float:
    """Fast token-level Jaccard similarity for content comparison."""
    if not a or not b:
        return 0.0
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def mmr_rerank(
    results: list[dict[str, Any]],
    *,
    lambda_param: float = 0.7,
    content_field: str = "memory_content",
    score_field: str = "score",
) -> list[dict[str, Any]]:
    """Re-rank results using Maximal Marginal Relevance.

    Args:
        results: Search results, each with a ``score`` and content field.
        lambda_param: Relevance-vs-diversity tradeoff (0.0–1.0).
                      1.0 = pure relevance (no change), 0.0 = pure diversity.
                      Default 0.7 is a good balance.
        content_field: Dict key for the content text to compare.
        score_field: Dict key for the relevance score.

    Returns:
        Re-ordered list of results (same objects, new order).
    """
    if len(results) <= 1:
        return results

    lambda_param = max(0.0, min(1.0, lambda_param))
    if lambda_param >= 0.99:
        return sorted(results, key=lambda r: r.get(score_field, 0.0), reverse=True)

    remaining = list(results)
    selected: list[dict[str, Any]] = []

    # First pick: highest relevance score
    remaining.sort(key=lambda r: r.get(score_field, 0.0), reverse=True)
    selected.append(remaining.pop(0))

    while remaining:
        best_idx = 0
        best_mmr = float("-inf")

        for i, candidate in enumerate(remaining):
            relevance = candidate.get(score_field, 0.0)

            # Max similarity to any already-selected result
            candidate_content = str(candidate.get(content_field, ""))
            max_sim = 0.0
            for s in selected:
                s_content = str(s.get(content_field, ""))
                sim = _jaccard_similarity(candidate_content, s_content)
                if sim > max_sim:
                    max_sim = sim

            mmr_score = lambda_param * relevance - (1.0 - lambda_param) * max_sim

            if mmr_score > best_mmr:
                best_mmr = mmr_score
                best_idx = i

        selected.append(remaining.pop(best_idx))

    return selected
