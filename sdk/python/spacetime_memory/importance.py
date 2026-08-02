"""
Memory importance scoring — Mem0, LangMem, Letta parity.

Estimates how important a memory is using combining LLM judgement
with behavioral signals (access count, recency, strength, feedback).

Stored via existing ``memory_meta`` table as:
  category = "importance"
  extra_json = {"score": 0.87, "label": "important", "reasoning": "..."}
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default prompt for LLM-based importance estimation
IMPORTANCE_PROMPT = """You are a memory importance evaluator. Given a memory entry and its metadata, assign an importance score from 0.0 (completely trivial — safe to forget immediately) to 1.0 (critically important — must be preserved permanently).

Consider:
- Does this memory affect the user's identity, preferences, or goals?
- Is it about a significant life event?
- Does it contain information the user would need to reference later?
- Is it a one-time fact vs. an ongoing/persistent truth?
- Would forgetting it cause harm or confusion?

Respond with a JSON object:
{{
  "score": 0.0-1.0,
  "label": "critical" | "important" | "normal" | "trivial",
  "reasoning": "Brief justification"
}}

Memory content: {content}
Memory summary: {summary}
Memory type: {memory_type}
Access count: {access_count}
Strength: {strength}
Tier: {tier}
"""


def importance_from_signals(
    strength: float,
    access_count: int,
    trust_score: float,
    tier: str,
    confidence: float,
    n_days_since_created: float = 0,
    n_days_since_accessed: float = 0,
) -> dict[str, Any]:
    """Compute importance purely from behavioral signals (no LLM needed).

    Returns dict with ``score``, ``label``, and ``reasoning``.
    """
    recency_boost = max(0.0, 1.0 - n_days_since_created / 365.0)
    access_decay = max(0.0, 1.0 - n_days_since_accessed / 90.0) if n_days_since_accessed > 0 else 0.5

    # Tier multiplier
    tier_mult = {"L0": 1.0, "L1": 0.7, "L2": 0.4}.get(tier, 0.5)

    # Access volume (up to 50 accesses = full bonus)
    access_bonus = min(1.0, access_count / 50.0) * 0.2

    raw = (
        strength * 0.35
        + trust_score * 0.15
        + confidence * 0.10
        + recency_boost * 0.15
        + access_decay * 0.10
        + access_bonus * 0.10
        + tier_mult * 0.05
    )

    score = max(0.0, min(1.0, raw))

    if score >= 0.85:
        label = "critical"
    elif score >= 0.65:
        label = "important"
    elif score >= 0.35:
        label = "normal"
    else:
        label = "trivial"

    return {
        "score": round(score, 4),
        "label": label,
        "reasoning": (
            f"strength={strength:.2f}, trust={trust_score:.2f}, "
            f"confidence={confidence:.2f}, access_count={access_count}, "
            f"tier={tier}, recency_boost={recency_boost:.2f}, "
            f"access_decay={access_decay:.2f}"
        ),
    }


def llm_estimate_importance(
    content: str,
    summary: str,
    memory_type: str,
    access_count: int,
    strength: float,
    tier: str,
    llm_func: Any = None,
) -> dict[str, Any]:
    """Use an LLM to estimate memory importance.

    Args:
        llm_func: A callable that takes a prompt string and returns
                  the response text. If None, falls back to signal-based scoring.
    """
    if llm_func is None:
        logger.info("No LLM function provided — falling back to signal-based importance")
        return importance_from_signals(
            strength=strength,
            access_count=access_count,
            trust_score=0.5,
            tier=tier,
            confidence=0.5,
        )

    prompt = IMPORTANCE_PROMPT.format(
        content=content[:500],
        summary=summary[:200],
        memory_type=memory_type,
        access_count=access_count,
        strength=strength,
        tier=tier,
    )

    try:
        response = llm_func(prompt)
        # Parse JSON from response
        result = json.loads(response)
        score = max(0.0, min(1.0, float(result.get("score", 0.5))))
        label = result.get("label", "normal")
        if label not in ("critical", "important", "normal", "trivial"):
            label = "normal"
        return {"score": round(score, 4), "label": label, "reasoning": result.get("reasoning", "")}
    except Exception as e:
        logger.warning("LLM importance estimation failed: %s — falling back", e)
        return importance_from_signals(
            strength=strength,
            access_count=access_count,
            trust_score=0.5,
            tier=tier,
            confidence=0.5,
        )


def importance_search_boost(results: list[dict], importance_weight: float = 0.15) -> list[dict]:
    """Boost search results by their importance score.

    Each result dict must have ``extra_json`` (parsed) or we fall back to
    score = 0.5.
    """
    for r in results:
        score = 0.5
        try:
            meta = json.loads(r.get("extra_json", "{}"))
            if isinstance(meta, dict):
                score = float(meta.get("score", 0.5))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        # Blend original score with importance boost
        original_score = float(r.get("score", r.get("_score", 0.5)))
        r["_score"] = original_score * (1 - importance_weight) + score * importance_weight
    return sorted(results, key=lambda r: r.get("_score", 0), reverse=True)
