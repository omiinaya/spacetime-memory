"""Veracity Tiers — Bayesian confidence scoring for memory trustworthiness.

Mnemosyne-style 5-tier veracity system with Bayesian compounding.
Each tier has a base confidence, and multiple independent confirmations
(n sources) compound using::

    confidence = 1 - (1 - base)^n

This means a fact stated twice (base=1.0) stays at 1.0, but a fact inferred
from 5 sources (base=0.7) reaches ~0.998 confidence.

Usage::

    from spacetime_memory.veracity import VeracityTier, compound

    # Compute confidence for a fact
    confidence = compound(VeracityTier.INFERRED, sources=3)
    # → 1 - (1-0.7)^3 = 1 - 0.027 = 0.973

    # Detect tier from source
    tier = detect_tier(source="user", extraction="llm")
    # → VeracityTier.STATED

Integration::
    - ``store()`` accepts ``veracity_tier`` and ``sources`` params
    - ``client.search()`` factors confidence into final scores
    - ``stmem veracity`` CLI for manual calculation
"""

from __future__ import annotations

from enum import Enum


class VeracityTier(str, Enum):
    """Five veracity tiers matching Mnemosyne's system.

    Each tier has a base confidence value representing how trustworthy
    a single uncorroborated source at that tier is.
    """

    STATED = "stated"  # Direct user statement — base 1.0
    UNKNOWN = "unknown"  # Provenance unclear — base 0.8
    INFERRED = "inferred"  # LLM extraction or reasoning — base 0.7
    IMPORTED = "imported"  # External import — base 0.6
    TOOL = "tool"  # Tool output or system-generated — base 0.5

    @property
    def base_confidence(self) -> float:
        """Base confidence for a single unverified source at this tier."""
        return {
            VeracityTier.STATED: 1.0,
            VeracityTier.UNKNOWN: 0.8,
            VeracityTier.INFERRED: 0.7,
            VeracityTier.IMPORTED: 0.6,
            VeracityTier.TOOL: 0.5,
        }[self]

    @classmethod
    def from_source(cls, source: str, extraction: str = "") -> VeracityTier:
        """Detect the most appropriate veracity tier from context clues.

        Args:
            source: Where the memory came from ("user", "import", "tool", "llm")
            extraction: If LLM extraction was used ("llm", "regex", "")

        Returns:
            The best-fit VeracityTier.
        """
        source_lower = source.lower()
        if source_lower in ("user", "stated", "direct", "manual"):
            # Direct user input gets the highest tier regardless of extraction
            return cls.STATED
        if extraction.lower() == "llm" or source_lower in ("inferred", "llm", "extraction"):
            return cls.INFERRED
        if source_lower in ("import", "sync", "migration", "imported", "external"):
            return cls.IMPORTED
        if source_lower in ("tool", "system", "agent", "generated"):
            return cls.TOOL
        return cls.UNKNOWN


# ── Tier label constants for display ────────────────────────────────────────

TIER_LABELS = {
    VeracityTier.STATED: "Stated (user)",
    VeracityTier.UNKNOWN: "Unknown provenance",
    VeracityTier.INFERRED: "Inferred (LLM)",
    VeracityTier.IMPORTED: "Imported (external)",
    VeracityTier.TOOL: "Tool output",
}

TIER_SYMBOLS = {
    VeracityTier.STATED: "✓✓",
    VeracityTier.UNKNOWN: "?",
    VeracityTier.INFERRED: "~",
    VeracityTier.IMPORTED: "↓",
    VeracityTier.TOOL: "⚙",
}


# ── Bayesian Compounding ────────────────────────────────────────────────────


def compound(
    tier: VeracityTier | str | None = None,
    sources: int = 1,
    base: float | None = None,
) -> float:
    """Compute Bayesian compounded confidence.

    Formula: ``confidence = 1 - (1 - base)^sources``

    With a base of 0.7 (inferred) and 3 independent sources:
    ``1 - (1-0.7)^3 = 1 - 0.027 = 0.973``

    With a base of 0.5 (tool) and 5 sources:
    ``1 - (1-0.5)^5 = 1 - 0.03125 = 0.969``

    Args:
        tier: VeracityTier enum or string name. Used to look up base_confidence.
        sources: Number of independent confirmations (default 1 = no compounding).
        base: Override base confidence directly (ignores ``tier`` if set).

    Returns:
        Compounded confidence value in [0.0, 1.0].
    """
    if base is None:
        if isinstance(tier, str):
            tier = VeracityTier(tier)
        base = tier.base_confidence if tier else 0.8
    sources = max(1, int(sources))
    return 1.0 - (1.0 - base) ** sources


def confidence_multiplier(confidence: float) -> float:
    """Convert a confidence value to a score multiplier for search ranking.

    Maps confidence [0.0, 1.0] to a multiplier in [0.5, 1.0]:
    - confidence=1.0 → 1.0x (full weight)
    - confidence=0.8 → 0.9x (moderate)
    - confidence=0.5 → 0.75x (penalized)
    - confidence=0.0 → 0.5x (minimum)

    This is intentionally gentle — we don't hide low-confidence results,
    just rank them lower.
    """
    return 0.5 + confidence * 0.5


# ── Display ─────────────────────────────────────────────────────────────────


def format_veracity(
    tier: VeracityTier | str,
    confidence: float,
    sources: int = 1,
) -> str:
    """Format veracity info as a human-readable string.

    Example: ``"✓✓ Stated (user) | conf=1.00 | 3 sources``
    """
    if isinstance(tier, str):
        tier = VeracityTier(tier)
    symbol = TIER_SYMBOLS.get(tier, "?")
    label = TIER_LABELS.get(tier, tier.value)
    return f"{symbol} {label} | conf={confidence:.2f} | {sources}s"
