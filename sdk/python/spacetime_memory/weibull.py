"""
Weibull Temporal Boost — recency-weighted scoring via Weibull distribution.

Unlike linear decay, the Weibull distribution models natural memory decay:
fast initial drop-off followed by a long tail. This matches how human memory
works — recent items fade quickly, but older items persist at low weight.

Shape parameter k controls the decay curve:
  - k < 1: rapid initial decay, long tail (default — natural memory)
  - k = 1: exponential decay
  - k > 1: S-shaped (increasing hazard rate)

Scale parameter λ controls the time scale (default: 7 days = 604800s).

Integrated into Client.search() scoring pipeline.
"""

import math
import time
from typing import Any


def weibull_weight(
    age_seconds: float,
    k: float = 0.5,
    lam: float = 604800.0,  # 7 days
    floor: float = 0.05,  # 5% minimum — never zero out
) -> float:
    """Compute Weibull survival weight for a given age.

    Args:
        age_seconds: Age of the item in seconds (now - created_at).
        k: Shape parameter (default 0.5 = fast decay, long tail).
        lam: Scale parameter in seconds (default 7 days).
        floor: Minimum weight cap (default 0.05).

    Returns:
        Weight in [floor, 1.0] where 1.0 = brand new.
    """
    if age_seconds <= 0:
        return 1.0
    # Weibull survival: exp(-(t/λ)^k)
    weight = math.exp(-((age_seconds / lam) ** k))
    return max(floor, min(1.0, weight))


def apply_temporal_boost(
    results: list[dict[str, Any]],
    *,
    score_field: str = "score",
    timestamp_field: str = "created_at",
    k: float = 0.5,
    lam: float = 604800.0,
    boost_strength: float = 0.15,
) -> list[dict[str, Any]]:
    """Apply Weibull temporal boost to search results in-place.

    Each result's score is multiplied by (1 + strength * weight),
    where weight is the Weibull survival value for the item's age.

    Args:
        results: Search results with score and timestamp fields.
        score_field: Dict key for the relevance score.
        timestamp_field: Dict key for the creation timestamp (unix seconds or microseconds).
        k: Weibull shape parameter.
        lam: Weibull scale parameter in seconds.
        boost_strength: Multiplier for the boost (0.0 = no boost, 0.15 = mild).

    Returns:
        Same list (mutated in-place, sorted by new score descending).
    """
    now = time.time()

    for r in results:
        ts = r.get(timestamp_field, 0)
        # Handle microsecond timestamps (STDB convention)
        if ts > 1_000_000_000_000:  # > year 33658 — definitely microseconds
            age = now - ts / 1_000_000
        else:
            age = now - ts

        weight = weibull_weight(age, k=k, lam=lam)
        original = r.get(score_field, 0.0)
        r[score_field] = original * (1.0 + boost_strength * weight)
        r["temporal_weight"] = weight

    results.sort(key=lambda r: r.get(score_field, 0.0), reverse=True)
    return results
