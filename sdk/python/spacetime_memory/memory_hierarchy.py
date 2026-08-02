"""
Memory hierarchy with auto-promotion — Letta parity.

Extends the existing L0/L1/L2 memory tier system (``update_memory_tier``
reducer) with automatic tier promotion based on access frequency and
recency, working memory eviction, tier-aware search, and full memory
lifecycle management.

All per-memory lifecycle metadata (access_count, last_accessed_at,
promotion_count, etc.) is stored in the existing ``memory_meta`` table
using ``category="hierarchy"`` — no schema changes required.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HIERARCHY_META_CATEGORY = "hierarchy"

# Promotion thresholds: at least this many accesses before considering promotion
PROMOTION_MIN_ACCESSES_L2_TO_L1 = 3
PROMOTION_MIN_ACCESSES_L1_TO_L0 = 10

# Recency window (seconds): memory must have been accessed within this window
# to be considered "recent" enough for promotion
PROMOTION_RECENCY_WINDOW = 7 * 86400  # 7 days

# How long (seconds) before an L0 memory is considered "cold" enough to evict
EVICTION_IDLE_THRESHOLD = 30 * 86400  # 30 days

# Default maximum size of L0 (working memory)
DEFAULT_MAX_L0_SIZE = 50

# Default maximum number of promotions per run
DEFAULT_MAX_PROMOTIONS = 20


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_hierarchy_meta(client: Any, memory_id: str) -> dict[str, Any]:
    """Fetch the hierarchy metadata dict for a memory.

    Returns an empty dict if no metadata exists yet.
    """
    try:
        meta: dict[str, Any] | None = client.get_memory_meta(memory_id)
    except Exception:
        meta = None
    if not meta:
        return {}
    raw: Any = meta.get("extra_json", "{}")
    if isinstance(raw, str):
        try:
            parsed: Any = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


def _set_hierarchy_meta(
    client: Any,
    workspace_id: str,
    memory_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Write hierarchy metadata for a memory (upsert)."""
    return client.set_memory_meta(
        workspace_id=workspace_id,
        memory_id=memory_id,
        category=HIERARCHY_META_CATEGORY,
        immutable=False,
        extra_json=json.dumps(data),
    )


def _now() -> float:
    """Current Unix timestamp (seconds)."""
    return time.time()


def _get_tier_score(tier: str) -> int:
    """Map tier name to numeric score for comparison."""
    return {"L0": 0, "L1": 1, "L2": 2}.get(tier, 99)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def track_access(
    client: Any,
    workspace_id: str,
    memory_id: str,
) -> dict[str, Any]:
    """Record an access event for a memory.

    Increments the access counter and updates the ``last_accessed_at``
    timestamp in the hierarchy metadata.  This data is used by
    ``auto_promote`` and ``evict_from_working``.

    Args:
        client: A SpacetimeMemory ``Client`` instance.
        workspace_id: The workspace containing the memory.
        memory_id: The memory being accessed.

    Returns:
        The updated hierarchy metadata dict.
    """
    meta = _get_hierarchy_meta(client, memory_id)
    now = _now()

    meta["access_count"] = meta.get("access_count", 0) + 1
    meta["last_accessed_at"] = now

    # Preserve the creation timestamp if already set
    if "created_at" not in meta:
        # Try to get the memory's actual created_at from the memory table
        try:
            rows = client._query(
                "memory",
                filter_dict={"id": memory_id},
                columns=["created_at"],
            )
            if rows and rows[0].get("created_at"):
                meta["created_at"] = float(rows[0]["created_at"]) / 1_000_000  # μs → s
            else:
                meta["created_at"] = now
        except Exception:
            meta["created_at"] = now

    _set_hierarchy_meta(client, workspace_id, memory_id, meta)
    return meta


def compute_lifecycle(
    client: Any,
    workspace_id: str,
    memory_id: str,
    memory_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute lifecycle metrics for a single memory.

    Returns a dict with:
        - ``memory_id`` — the memory ID
        - ``tier`` — current tier (L0/L1/L2)
        - ``age_days`` — age in days
        - ``days_since_accessed`` — days since last access (inf if never)
        - ``access_count`` — total recorded accesses
        - ``promotion_count`` — number of times promoted
        - ``recency_score`` — 0.0–1.0, how recently accessed
        - ``frequency_score`` — 0.0–1.0, access density over lifetime
        - ``composite_score`` — 0.0–1.0 blend of recency + frequency

    Args:
        client: A ``Client`` instance.
        workspace_id: The workspace containing the memory.
        memory_id: The memory to analyse.
        memory_row: Optional pre-fetched memory row (avoids an extra
            ``_query``). Must contain at least ``tier``, and optionally
            ``confidence``, ``strength``.

    Returns:
        Lifecycle metrics dict.
    """
    now = _now()

    # Fetch memory row if not provided
    if memory_row is None:
        try:
            rows = client._query(
                "memory",
                filter_dict={"id": memory_id},
                columns=["id", "tier", "confidence", "strength", "created_at"],
            )
            memory_row = rows[0] if rows else {}
        except Exception:
            memory_row = {}

    assert memory_row is not None  # guaranteed by logic above
    tier = memory_row.get("tier", "L2")
    meta = _get_hierarchy_meta(client, memory_id)

    access_count = meta.get("access_count", 0)
    promotion_count = meta.get("promotion_count", 0)
    created_at = meta.get("created_at") or (
        float(memory_row.get("created_at", now)) / 1_000_000
        if memory_row.get("created_at")
        else now
    )
    last_accessed_at = meta.get("last_accessed_at")

    age_days = max(0.0, (now - created_at) / 86400) if created_at else 0.0
    days_since_accessed = (
        (now - last_accessed_at) / 86400 if last_accessed_at else float("inf")
    )

    # Recency score: 1.0 if accessed within last day, decays to 0 over 30 days
    if last_accessed_at:
        days_ago = (now - last_accessed_at) / 86400
        recency_score = max(0.0, 1.0 - days_ago / 30.0)
    else:
        recency_score = 0.0

    # Frequency score: accesses per day, normalised to [0, 1]
    if age_days > 0:
        freq_raw = access_count / age_days
        frequency_score = min(1.0, freq_raw / 2.0)  # 2 accesses/day = full score
    else:
        frequency_score = 0.0 if access_count == 0 else 0.5

    # Composite: weighted blend for promotion decisions
    composite_score = 0.6 * recency_score + 0.4 * frequency_score

    return {
        "memory_id": memory_id,
        "tier": tier,
        "age_days": round(age_days, 2),
        "days_since_accessed": round(days_since_accessed, 2) if days_since_accessed != float("inf") else float("inf"),
        "access_count": access_count,
        "promotion_count": promotion_count,
        "recency_score": round(recency_score, 4),
        "frequency_score": round(frequency_score, 4),
        "composite_score": round(composite_score, 4),
        "confidence": memory_row.get("confidence", 0.5),
        "strength": memory_row.get("strength", 0.5),
    }


def promote_memory(
    client: Any,
    workspace_id: str,
    memory_id: str,
    target_tier: str,
) -> dict[str, Any]:
    """Promote (or demote) a single memory to a specific tier.

    Updates both the tier (via ``update_memory_tier`` reducer) and the
    hierarchy metadata with promotion tracking info.

    Args:
        client: A ``Client`` instance.
        workspace_id: The workspace containing the memory.
        memory_id: The memory to promote/demote.
        target_tier: One of ``"L0"``, ``"L1"``, ``"L2"``.

    Returns:
        Dict with ``status``, ``memory_id``, ``previous_tier``,
        ``new_tier``, and updated ``meta``.
    """
    if target_tier not in ("L0", "L1", "L2"):
        raise ValueError(f"Invalid tier '{target_tier}'. Must be L0, L1, or L2.")

    # Fetch current tier
    try:
        rows = client._query(
            "memory",
            filter_dict={"id": memory_id},
            columns=["id", "tier"],
        )
        previous_tier = rows[0].get("tier", "L2") if rows else "L2"
    except Exception:
        previous_tier = "L2"

    # Call the existing reducer
    client.update_memory_tier(memory_id, target_tier)

    # Update hierarchy metadata
    meta = _get_hierarchy_meta(client, memory_id)
    meta["promotion_count"] = meta.get("promotion_count", 0) + 1
    meta["last_promoted_at"] = _now()
    meta["previous_tier"] = previous_tier
    meta["current_tier"] = target_tier

    _set_hierarchy_meta(client, workspace_id, memory_id, meta)

    logger.info(
        "Memory %s promoted %s → %s (promotion #%d)",
        memory_id,
        previous_tier,
        target_tier,
        meta["promotion_count"],
    )

    return {
        "status": "ok",
        "memory_id": memory_id,
        "previous_tier": previous_tier,
        "new_tier": target_tier,
        "meta": meta,
    }


def auto_promote(
    client: Any,
    workspace_id: str,
    max_promotions: int = DEFAULT_MAX_PROMOTIONS,
    l2_to_l1_min_accesses: int = PROMOTION_MIN_ACCESSES_L2_TO_L1,
    l1_to_l0_min_accesses: int = PROMOTION_MIN_ACCESSES_L1_TO_L0,
    recency_window: float = PROMOTION_RECENCY_WINDOW,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Automatically promote memories from L2→L1 and L1→L0.

    Scans all non-L0 memories, computes lifecycle metrics, and promotes
    those that meet frequency + recency thresholds.

    Args:
        client: A ``Client`` instance.
        workspace_id: The workspace to scan.
        max_promotions: Max number of promotions to perform in one run
            (default 20).
        l2_to_l1_min_accesses: Min accesses for L2→L1 promotion (default 3).
        l1_to_l0_min_accesses: Min accesses for L1→L0 promotion (default 10).
        recency_window: Seconds within which a memory must have been
            accessed to be eligible (default 7 days).
        dry_run: If True, only report what would happen; don't actually
            promote.

    Returns:
        Dict with keys:
            - ``promotions`` — list of promotion result dicts
            - ``candidates`` — list of candidates considered
            - ``stats`` — summary counts
    """
    now = _now()

    # Fetch all memories that are not already L0
    try:
        rows = client._query(
            "memory",
            workspace_id=workspace_id,
            filter_dict={},
            columns=["id", "tier", "confidence", "strength", "created_at"],
        )
    except Exception as e:
        logger.warning("auto_promote: failed to query memories: %s", e)
        return {"promotions": [], "candidates": [], "stats": {"error": str(e)}}

    # Separate by tier
    l2_memories = [r for r in rows if r.get("tier") == "L2"]
    l1_memories = [r for r in rows if r.get("tier") == "L1"]

    candidates: list[dict[str, Any]] = []
    promotions: list[dict[str, Any]] = []
    l1_to_l0_queue: list[dict[str, Any]] = []

    # --- L2 → L1: check threshold ---
    for mem in l2_memories:
        mid = mem["id"]
        lifecycle = compute_lifecycle(client, workspace_id, mid, memory_row=mem)
        meta = _get_hierarchy_meta(client, mid)

        access_count = meta.get("access_count", 0)
        last_accessed_at = meta.get("last_accessed_at", 0)

        eligible = (
            access_count >= l2_to_l1_min_accesses
            and last_accessed_at
            and (now - last_accessed_at) <= recency_window
        )

        candidates.append({
            "memory_id": mid,
            "current_tier": "L2",
            "eligible": eligible,
            "access_count": access_count,
            "recency_score": lifecycle["recency_score"],
            "composite_score": lifecycle["composite_score"],
        })

        if eligible and len(promotions) < max_promotions:
            if dry_run:
                promotions.append({
                    "memory_id": mid,
                    "from_tier": "L2",
                    "to_tier": "L1",
                    "dry_run": True,
                    "composite_score": lifecycle["composite_score"],
                })
            else:
                result = promote_memory(client, workspace_id, mid, "L1")
                promotions.append({
                    "memory_id": mid,
                    "from_tier": "L2",
                    "to_tier": "L1",
                    "dry_run": False,
                    "composite_score": lifecycle["composite_score"],
                    "status": result["status"],
                })

    # --- L1 → L0: rank by composite score, promote top N ---
    remaining_budget = max_promotions - len(promotions)
    if remaining_budget > 0:
        for mem in l1_memories:
            mid = mem["id"]
            lifecycle = compute_lifecycle(client, workspace_id, mid, memory_row=mem)
            meta = _get_hierarchy_meta(client, mid)

            access_count = meta.get("access_count", 0)
            last_accessed_at = meta.get("last_accessed_at", 0)

            eligible = (
                access_count >= l1_to_l0_min_accesses
                and last_accessed_at
                and (now - last_accessed_at) <= recency_window
            )

            candidate_entry = {
                "memory_id": mid,
                "current_tier": "L1",
                "eligible": eligible,
                "access_count": access_count,
                "recency_score": lifecycle["recency_score"],
                "composite_score": lifecycle["composite_score"],
            }
            candidates.append(candidate_entry)

            if eligible:
                l1_to_l0_queue.append(candidate_entry)

        # Sort by composite_score descending, take top N
        l1_to_l0_queue.sort(key=lambda x: x["composite_score"], reverse=True)
        for entry in l1_to_l0_queue[:remaining_budget]:
            if dry_run:
                promotions.append({
                    "memory_id": entry["memory_id"],
                    "from_tier": "L1",
                    "to_tier": "L0",
                    "dry_run": True,
                    "composite_score": entry["composite_score"],
                })
            else:
                result = promote_memory(client, workspace_id, entry["memory_id"], "L0")
                promotions.append({
                    "memory_id": entry["memory_id"],
                    "from_tier": "L1",
                    "to_tier": "L0",
                    "dry_run": False,
                    "composite_score": entry["composite_score"],
                    "status": result["status"],
                })

    stats = {
        "total_memories": len(rows),
        "l2_count": len(l2_memories),
        "l1_count": len(l1_memories),
        "total_candidates": len(candidates),
        "total_promotions": len(promotions),
        "promotions_to_l1": sum(1 for p in promotions if p["to_tier"] == "L1"),
        "promotions_to_l0": sum(1 for p in promotions if p["to_tier"] == "L0"),
        "dry_run": dry_run,
    }

    return {
        "promotions": promotions,
        "candidates": candidates,
        "stats": stats,
    }


def evict_from_working(
    client: Any,
    workspace_id: str,
    max_l0_size: int = DEFAULT_MAX_L0_SIZE,
    eviction_idle_threshold: float = EVICTION_IDLE_THRESHOLD,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Evict the least-important L0 memories to L1.

    Keeps working memory (L0) bounded.  Memories that haven't been
    accessed recently and have low composite scores are demoted to L1.

    Args:
        client: A ``Client`` instance.
        workspace_id: The workspace to manage.
        max_l0_size: Maximum number of L0 memories allowed (default 50).
        eviction_idle_threshold: Seconds of inactivity before a memory
            is considered idle (default 30 days).
        dry_run: If True, only report what would happen.

    Returns:
        Dict with keys:
            - ``evictions`` — list of evicted memory dicts
            - ``stats`` — summary counts
    """
    _now()

    try:
        l0_rows = client._query(
            "memory",
            workspace_id=workspace_id,
            filter_dict={},
            columns=["id", "tier", "confidence", "strength", "created_at"],
        )
    except Exception as e:
        logger.warning("evict_from_working: failed to query memories: %s", e)
        return {"evictions": [], "stats": {"error": str(e)}}

    l0_memories = [r for r in l0_rows if r.get("tier") == "L0"]

    if len(l0_memories) <= max_l0_size:
        return {
            "evictions": [],
            "stats": {
                "l0_count": len(l0_memories),
                "max_l0_size": max_l0_size,
                "under_limit": True,
                "note": "L0 is within bounds — no evictions needed",
            },
        }

    # Score each L0 memory by eviction priority (lowest score = evict first)
    scored: list[dict[str, Any]] = []
    for mem in l0_memories:
        mid = mem["id"]
        lifecycle = compute_lifecycle(client, workspace_id, mid, memory_row=mem)

        recency = lifecycle["recency_score"]
        frequency = lifecycle["frequency_score"]

        # Eviction score: low = good candidate for eviction
        # Blend: reverse recency (stale = low), reverse frequency (rare = low)
        eviction_score = 0.5 * recency + 0.3 * frequency + 0.2 * lifecycle.get("confidence", 0.5)

        scored.append({
            "memory_id": mid,
            "tier": "L0",
            "eviction_score": round(eviction_score, 4),
            "recency_score": lifecycle["recency_score"],
            "frequency_score": lifecycle["frequency_score"],
            "days_since_accessed": lifecycle["days_since_accessed"],
            "access_count": lifecycle["access_count"],
            "age_days": lifecycle["age_days"],
        })

    # Sort ascending by eviction score (worst/least-important first)
    scored.sort(key=lambda x: x["eviction_score"])

    # Determine how many to evict
    num_to_evict = len(l0_memories) - max_l0_size
    evict_candidates = scored[:num_to_evict]

    # Further filter: only evict memories that are actually idle
    evict_candidates = [
        e
        for e in evict_candidates
        if e["days_since_accessed"] == float("inf")
        or e["days_since_accessed"] * 86400 >= eviction_idle_threshold
    ]

    evictions: list[dict[str, Any]] = []
    for entry in evict_candidates:
        if dry_run:
            evictions.append({
                "memory_id": entry["memory_id"],
                "eviction_score": entry["eviction_score"],
                "dry_run": True,
            })
        else:
            result = promote_memory(client, workspace_id, entry["memory_id"], "L1")
            evictions.append({
                "memory_id": entry["memory_id"],
                "eviction_score": entry["eviction_score"],
                "dry_run": False,
                "status": result["status"],
            })

    return {
        "evictions": evictions,
        "stats": {
            "l0_count": len(l0_memories),
            "max_l0_size": max_l0_size,
            "over_limit": len(l0_memories) - max_l0_size,
            "evictions_attempted": len(evict_candidates),
            "evictions_executed": len(evictions),
            "dry_run": dry_run,
        },
    }


def tier_aware_search(
    client: Any,
    workspace_id: str,
    query: str = "",
    tier: str = "",
    limit: int = 20,
    semantic: bool = True,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Search memories with optional tier filtering.

    Wraps the existing ``client.search()`` and adds post-filtering by
    tier when the backend search doesn't natively support it, or passes
    the ``tier`` parameter through to the hybrid search reducer.

    Args:
        client: A ``Client`` instance.
        workspace_id: The workspace to search.
        query: The search query string.
        tier: If set to ``"L0"``, ``"L1"``, or ``"L2"``, only return
            memories in that tier.  Empty string means no filter.
        limit: Max results (default 20).
        semantic: Use semantic/hybrid search (default True).
        **kwargs: Additional arguments passed to ``client.search()``.

    Returns:
        List of matching memory dicts.
    """
    if tier and tier not in ("L0", "L1", "L2"):
        raise ValueError(f"Invalid tier '{tier}'. Must be L0, L1, L2, or ''.")

    # The client.search() method already accepts a tier parameter that's
    # passed through to the hybrid_search reducer
    results: Any = client.search(
        workspace_id=workspace_id,
        query=query,
        tier=tier,
        limit=limit,
        semantic=semantic,
        **kwargs,
    )

    # If client.search returned a dict with "results" key (newer format),
    # unwrap it
    if isinstance(results, dict) and "results" in results:
        results = results["results"]

    if not isinstance(results, list):
        return []
    return results


def filter_by_tier(
    client: Any,
    workspace_id: str,
    tiers: str | list[str],
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch all memories belonging to one or more tiers.

    This is a direct query (not a semantic search).  Useful for lifecycle
    management, stats, and bulk operations.

    Args:
        client: A ``Client`` instance.
        workspace_id: The workspace to query.
        tiers: A single tier string (e.g. ``"L0"``) or a list
            (e.g. ``["L0", "L1"]``).
        limit: Max results (default 100).

    Returns:
        List of memory rows.
    """
    if isinstance(tiers, str):
        tiers = [tiers]

    for t in tiers:
        if t not in ("L0", "L1", "L2"):
            raise ValueError(f"Invalid tier '{t}'. Must be L0, L1, or L2.")

    try:
        rows = client._query(
            "memory",
            workspace_id=workspace_id,
            filter_dict={},
            columns=["id", "tier", "content", "summary", "memory_type",
                     "confidence", "strength", "created_at"],
        )
    except Exception as e:
        logger.warning("filter_by_tier: query failed: %s", e)
        return []

    filtered = [r for r in rows if r.get("tier") in tiers]
    filtered.sort(key=lambda r: r.get("created_at", 0), reverse=True)
    return filtered[:limit]


def run_memory_lifecycle(
    client: Any,
    workspace_id: str,
    max_l0_size: int = DEFAULT_MAX_L0_SIZE,
    max_promotions: int = DEFAULT_MAX_PROMOTIONS,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the full memory lifecycle for a workspace.

    Steps:
        1. Auto-promote L2→L1→L0 based on access frequency + recency.
        2. Evict excess L0 memories to L1.

    This is the main entry point that replicates Letta's memory
    lifecycle behaviour: frequently-accessed memories bubble up to
    working memory (L0), while stale ones sink back to L1.

    Args:
        client: A ``Client`` instance.
        workspace_id: The workspace to manage.
        max_l0_size: Max L0 memories before eviction kicks in.
        max_promotions: Max promotions per lifecycle run.
        dry_run: If True, report only — don't make changes.

    Returns:
        Dict with ``promotions``, ``evictions``, and ``stats``.
    """
    promo_result = auto_promote(
        client,
        workspace_id,
        max_promotions=max_promotions,
        dry_run=dry_run,
    )

    evict_result = evict_from_working(
        client,
        workspace_id,
        max_l0_size=max_l0_size,
        dry_run=dry_run,
    )

    combined_stats = {
        "workspace_id": workspace_id,
        "dry_run": dry_run,
        "memories_scanned": promo_result["stats"].get("total_memories", 0),
        "promotions": promo_result["stats"].get("total_promotions", 0),
        "evictions": evict_result["stats"].get("evictions_executed", 0),
        "l0_final_count": evict_result["stats"].get("l0_count", 0),
        "max_l0_size": max_l0_size,
    }

    return {
        "promotions": promo_result["promotions"],
        "evictions": evict_result["evictions"],
        "stats": combined_stats,
    }
