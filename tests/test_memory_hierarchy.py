"""Tests for memory hierarchy with auto-promotion."""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from spacetime_memory.memory_hierarchy import (
    HIERARCHY_META_CATEGORY,
    track_access,
    compute_lifecycle,
    promote_memory,
    auto_promote,
    evict_from_working,
    tier_aware_search,
    filter_by_tier,
    run_memory_lifecycle,
    _get_hierarchy_meta,
    _set_hierarchy_meta,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client() -> MagicMock:
    """Build a standard mock Client for hierarchy tests."""
    client = MagicMock()

    # In-memory store for memory_meta
    _meta_store: dict[str, dict[str, Any]] = {}
    _memory_table: list[dict[str, Any]] = []

    def _mock_get_memory_meta(memory_id: str) -> dict[str, Any] | None:
        return _meta_store.get(memory_id)

    def _mock_set_memory_meta(
        workspace_id: str,
        memory_id: str,
        category: str = "",
        immutable: bool = False,
        extra_json: str = "{}",
    ) -> dict[str, Any]:
        _meta_store[memory_id] = {
            "memory_id": memory_id,
            "workspace_id": workspace_id,
            "category": category,
            "immutable": immutable,
            "extra_json": extra_json,
        }
        return {"status": "ok"}

    def _mock_query(
        table: str,
        workspace_id: str = "",
        filter_dict: dict | None = None,
        columns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if table == "memory":
            results = _memory_table
            if workspace_id:
                results = [r for r in results if r.get("workspace_id") == workspace_id]
            if filter_dict:
                for k, v in filter_dict.items():
                    results = [r for r in results if r.get(k) == v]
            if columns:
                results = [
                    {k: r.get(k) for k in columns if k in r} for r in results
                ]
            return results
        return []

    client.get_memory_meta = MagicMock(side_effect=_mock_get_memory_meta)
    client.set_memory_meta = MagicMock(side_effect=_mock_set_memory_meta)
    client._query = MagicMock(side_effect=_mock_query)
    client.update_memory_tier = MagicMock(return_value={"status": "ok"})
    client.search = MagicMock(return_value=[])

    # Attach store references for test inspection
    client._meta_store = _meta_store
    client._memory_table = _memory_table

    return client


def _add_memory(
    client: MagicMock,
    workspace_id: str,
    memory_id: str,
    tier: str = "L2",
    **overrides: Any,
) -> None:
    """Helper to add a memory to the mock store."""
    entry = {
        "id": memory_id,
        "workspace_id": workspace_id,
        "tier": tier,
        "content": f"content of {memory_id}",
        "summary": f"summary of {memory_id}",
        "memory_type": "experience",
        "confidence": 0.8,
        "strength": 0.5,
        "created_at": int(time.time() * 1_000_000),
    }
    entry.update(overrides)
    client._memory_table.append(entry)


def _add_meta(
    client: MagicMock,
    memory_id: str,
    workspace_id: str,
    **meta_fields: Any,
) -> None:
    """Helper to pre-populate hierarchy metadata."""
    data = {
        "access_count": meta_fields.get("access_count", 0),
        "created_at": meta_fields.get("created_at", time.time()),
        "last_accessed_at": meta_fields.get("last_accessed_at"),
        "promotion_count": meta_fields.get("promotion_count", 0),
    }
    client.set_memory_meta(
        workspace_id=workspace_id,
        memory_id=memory_id,
        category=HIERARCHY_META_CATEGORY,
        extra_json=json.dumps({k: v for k, v in data.items() if v is not None}),
    )


# ===========================================================================
# Tests for _get_hierarchy_meta / _set_hierarchy_meta
# ===========================================================================


class TestHierarchyMeta:
    """Internal metadata helpers."""

    def test_get_meta_empty_when_nonexistent(self):
        client = _make_mock_client()
        result = _get_hierarchy_meta(client, "nonexistent")
        assert result == {}

    def test_get_meta_returns_stored_data(self):
        client = _make_mock_client()
        _add_meta(client, "mem_1", "ws_1", access_count=5)
        result = _get_hierarchy_meta(client, "mem_1")
        assert result.get("access_count") == 5

    def test_get_meta_handles_get_memory_meta_error(self):
        """If get_memory_meta raises, return empty dict."""
        client = _make_mock_client()
        client.get_memory_meta.side_effect = RuntimeError("fail")
        result = _get_hierarchy_meta(client, "mem_1")
        assert result == {}

    def test_set_meta_stores_correctly(self):
        client = _make_mock_client()
        result = _set_hierarchy_meta(client, "ws_1", "mem_1", {"access_count": 3})
        assert result["status"] == "ok"
        meta = _get_hierarchy_meta(client, "mem_1")
        assert meta["access_count"] == 3

    def test_handles_malformed_extra_json(self):
        client = _make_mock_client()
        # Simulate malformed json in store
        client._meta_store["mem_1"] = {
            "memory_id": "mem_1",
            "extra_json": "not valid json",
        }
        result = _get_hierarchy_meta(client, "mem_1")
        assert result == {}


# ===========================================================================
# Tests for track_access
# ===========================================================================


class TestTrackAccess:
    """Recording memory accesses."""

    def test_first_access_creates_meta(self):
        client = _make_mock_client()
        _add_memory(client, "ws_1", "mem_1", tier="L2")
        result = track_access(client, "ws_1", "mem_1")
        assert result["access_count"] == 1
        assert "last_accessed_at" in result
        assert "created_at" in result

    def test_increments_access_count(self):
        client = _make_mock_client()
        _add_memory(client, "ws_1", "mem_1", tier="L2")
        _add_meta(client, "mem_1", "ws_1", access_count=5)
        result = track_access(client, "ws_1", "mem_1")
        assert result["access_count"] == 6

    def test_includes_created_at_from_memory_table(self):
        client = _make_mock_client()
        ts = 1_700_000_000_000_000  # μs
        _add_memory(client, "ws_1", "mem_1", tier="L2", created_at=ts)
        result = track_access(client, "ws_1", "mem_1")
        # Created_at is stored in seconds, converted from μs
        assert result["created_at"] > 0

    def test_falls_back_to_now_when_no_memory_row(self):
        """Accessing a non-existent memory still records access."""
        client = _make_mock_client()
        result = track_access(client, "ws_1", "ghost_mem")
        assert result["access_count"] == 1
        assert result["created_at"] > 0


# ===========================================================================
# Tests for compute_lifecycle
# ===========================================================================


class TestComputeLifecycle:
    """Lifecycle metrics computation."""

    def test_returns_expected_keys(self):
        client = _make_mock_client()
        _add_memory(client, "ws_1", "mem_1", tier="L2")
        result = compute_lifecycle(client, "ws_1", "mem_1")
        expected_keys = {
            "memory_id", "tier", "age_days", "days_since_accessed",
            "access_count", "promotion_count", "recency_score",
            "frequency_score", "composite_score", "confidence", "strength",
        }
        assert expected_keys.issubset(result.keys())
        assert result["tier"] == "L2"
        assert result["memory_id"] == "mem_1"

    def test_never_accessed_has_inf_days_since(self):
        client = _make_mock_client()
        _add_memory(client, "ws_1", "mem_1", tier="L1")
        result = compute_lifecycle(client, "ws_1", "mem_1")
        assert result["days_since_accessed"] == float("inf")
        assert result["recency_score"] == 0.0

    def test_recently_accessed_high_recency(self):
        client = _make_mock_client()
        _add_memory(client, "ws_1", "mem_1", tier="L1")
        _add_meta(client, "mem_1", "ws_1", last_accessed_at=time.time() - 3600)  # 1 hour ago
        result = compute_lifecycle(client, "ws_1", "mem_1")
        assert result["recency_score"] > 0.9  # Very recent

    def test_accepts_prefetched_memory_row(self):
        client = _make_mock_client()
        row = {"id": "mem_1", "tier": "L0", "confidence": 0.9, "strength": 0.8}
        result = compute_lifecycle(client, "ws_1", "mem_1", memory_row=row)
        assert result["tier"] == "L0"
        assert result["confidence"] == 0.9

    def test_composite_high_with_frequent_access(self):
        client = _make_mock_client()
        _add_memory(client, "ws_1", "mem_1", tier="L2")
        now = time.time()
        _add_meta(
            client, "mem_1", "ws_1",
            access_count=50,
            created_at=now - 86400 * 10,  # 10 days old
            last_accessed_at=now - 3600,   # 1 hour ago
        )
        result = compute_lifecycle(client, "ws_1", "mem_1")
        assert result["composite_score"] > 0.5  # Frequently accessed, recent

    def test_query_fallback_on_missing_memory(self):
        """compute_lifecycle handles memory not found gracefully."""
        client = _make_mock_client()
        client._query.side_effect = RuntimeError("table not found")
        # Should not crash
        result = compute_lifecycle(client, "ws_1", "nonexistent")
        assert result["memory_id"] == "nonexistent"
        assert "tier" in result


# ===========================================================================
# Tests for promote_memory
# ===========================================================================


class TestPromoteMemory:
    """Single-memory tier promotion/demotion."""

    def test_promote_l2_to_l1(self):
        client = _make_mock_client()
        _add_memory(client, "ws_1", "mem_1", tier="L2")
        result = promote_memory(client, "ws_1", "mem_1", "L1")
        assert result["status"] == "ok"
        assert result["previous_tier"] == "L2"
        assert result["new_tier"] == "L1"
        client.update_memory_tier.assert_called_with("mem_1", "L1")

    def test_tracks_promotion_count(self):
        client = _make_mock_client()
        _add_memory(client, "ws_1", "mem_1", tier="L2")
        promote_memory(client, "ws_1", "mem_1", "L1")
        promote_memory(client, "ws_1", "mem_1", "L0")
        meta = _get_hierarchy_meta(client, "mem_1")
        assert meta["promotion_count"] == 2

    def test_rejects_invalid_tier(self):
        client = _make_mock_client()
        with pytest.raises(ValueError, match="Invalid tier"):
            promote_memory(client, "ws_1", "mem_1", "L3")

    def test_demote_l0_to_l2(self):
        """promote_memory works in reverse (demotion) too."""
        client = _make_mock_client()
        _add_memory(client, "ws_1", "mem_1", tier="L0")
        result = promote_memory(client, "ws_1", "mem_1", "L2")
        assert result["new_tier"] == "L2"

    def test_memory_not_in_query_table_is_ok(self):
        """If the memory isn't in the query results, still tries."""
        client = _make_mock_client()
        result = promote_memory(client, "ws_1", "unknown_mem", "L1")
        assert result["status"] == "ok"
        assert result["new_tier"] == "L1"


# ===========================================================================
# Tests for auto_promote
# ===========================================================================


class TestAutoPromote:
    """Automatic batch promotion from L2→L1→L0."""

    def test_no_memories_returns_empty(self):
        client = _make_mock_client()
        result = auto_promote(client, "ws_1")
        assert result["promotions"] == []
        assert result["stats"]["total_memories"] == 0

    def test_promotes_eligible_l2_to_l1(self):
        client = _make_mock_client()
        _add_memory(client, "ws_1", "l2_mem_1", tier="L2")
        now = time.time()
        _add_meta(
            client, "l2_mem_1", "ws_1",
            access_count=5,
            last_accessed_at=now - 3600,  # 1 hour ago
        )
        result = auto_promote(
            client, "ws_1",
            l2_to_l1_min_accesses=3,
            max_promotions=10,
        )
        assert len(result["promotions"]) == 1
        assert result["promotions"][0]["from_tier"] == "L2"
        assert result["promotions"][0]["to_tier"] == "L1"

    def test_skips_l2_with_low_access_count(self):
        client = _make_mock_client()
        now = time.time()
        _add_memory(client, "ws_1", "l2_mem_1", tier="L2")
        _add_meta(
            client, "l2_mem_1", "ws_1",
            access_count=1,  # Below threshold of 3
            last_accessed_at=now - 3600,
        )
        result = auto_promote(
            client, "ws_1",
            l2_to_l1_min_accesses=3,
        )
        eligible = [c for c in result["candidates"] if c.get("eligible")]
        assert len(eligible) == 0

    def test_skips_stale_memories(self):
        """Memories accessed outside the recency window are skipped."""
        client = _make_mock_client()
        _add_memory(client, "ws_1", "l2_mem_1", tier="L2")
        _add_meta(
            client, "l2_mem_1", "ws_1",
            access_count=10,
            last_accessed_at=time.time() - 30 * 86400,  # 30 days ago
        )
        result = auto_promote(
            client, "ws_1",
            l2_to_l1_min_accesses=3,
            recency_window=7 * 86400,
        )
        eligible = [c for c in result["candidates"] if c.get("eligible")]
        assert len(eligible) == 0

    def test_promotes_top_l1_to_l0(self):
        """Multiple L1s: only the best ones get promoted."""
        client = _make_mock_client()
        now = time.time()

        # Two L1 memories — one very active, one barely
        for i, (accesses, hours_ago) in enumerate([(20, 1), (2, 720)]):
            mid = f"l1_mem_{i}"
            _add_memory(client, "ws_1", mid, tier="L1")
            _add_meta(
                client, mid, "ws_1",
                access_count=accesses,
                last_accessed_at=now - hours_ago * 3600,
            )

        result = auto_promote(
            client, "ws_1",
            l1_to_l0_min_accesses=5,
        )
        promoted_ids = [p["memory_id"] for p in result["promotions"]]
        assert "l1_mem_0" in promoted_ids
        assert "l1_mem_1" not in promoted_ids  # Below min accesses

    def test_respects_max_promotions(self):
        """Only promote up to max_promotions regardless of eligible count."""
        client = _make_mock_client()
        now = time.time()
        for i in range(10):
            _add_memory(client, "ws_1", f"l2_mem_{i}", tier="L2")
            _add_meta(
                client, f"l2_mem_{i}", "ws_1",
                access_count=10,
                last_accessed_at=now - 3600,
            )
        result = auto_promote(
            client, "ws_1",
            max_promotions=3,
            l2_to_l1_min_accesses=1,
        )
        assert len(result["promotions"]) == 3

    def test_dry_run_does_not_promote(self):
        client = _make_mock_client()
        now = time.time()
        _add_memory(client, "ws_1", "l2_mem_1", tier="L2")
        _add_meta(
            client, "l2_mem_1", "ws_1",
            access_count=10,
            last_accessed_at=now - 3600,
        )
        result = auto_promote(
            client, "ws_1",
            l2_to_l1_min_accesses=1,
            dry_run=True,
        )
        assert len(result["promotions"]) == 1
        assert result["promotions"][0]["dry_run"] is True
        client.update_memory_tier.assert_not_called()
        assert result["stats"]["dry_run"] is True

    def test_stats_report_counts(self):
        client = _make_mock_client()
        now = time.time()
        _add_memory(client, "ws_1", "l2_mem_1", tier="L2")
        _add_meta(
            client, "l2_mem_1", "ws_1",
            access_count=10,
            last_accessed_at=now - 3600,
        )
        result = auto_promote(
            client, "ws_1",
            l2_to_l1_min_accesses=1,
        )
        stats = result["stats"]
        assert stats["total_memories"] >= 1
        assert stats["total_promotions"] >= 1

    def test_handles_query_error(self):
        client = _make_mock_client()
        client._query.side_effect = RuntimeError("STDB down")
        result = auto_promote(client, "ws_1")
        assert "error" in result["stats"]


# ===========================================================================
# Tests for evict_from_working
# ===========================================================================


class TestEvictFromWorking:
    """L0 → L1 eviction when working memory exceeds limit."""

    def test_no_eviction_when_under_limit(self):
        client = _make_mock_client()
        for i in range(3):
            _add_memory(client, "ws_1", f"l0_mem_{i}", tier="L0")
        result = evict_from_working(client, "ws_1", max_l0_size=5)
        assert result["evictions"] == []
        assert result["stats"]["under_limit"] is True

    def test_evicts_excess_idle_memories(self):
        """When L0 exceeds limit, idle memories get evicted."""
        client = _make_mock_client()
        now = time.time()
        # 6 L0 memories but max is 5 — 1 should be evicted
        for i in range(6):
            mid = f"l0_mem_{i}"
            _add_memory(client, "ws_1", mid, tier="L0")
            _add_meta(
                client, mid, "ws_1",
                access_count=1,
                last_accessed_at=now - 60 * 86400,  # 60 days ago (idle)
            )
        result = evict_from_working(
            client, "ws_1",
            max_l0_size=5,
            eviction_idle_threshold=30 * 86400,
        )
        assert len(result["evictions"]) == 1

    def test_skips_recently_accessed_memories(self):
        """Active memories should not be evicted even if over limit."""
        client = _make_mock_client()
        now = time.time()
        # 6 L0 memories, but 1 was accessed recently
        for i in range(5):
            mid = f"old_mem_{i}"
            _add_memory(client, "ws_1", mid, tier="L0")
            _add_meta(
                client, mid, "ws_1",
                access_count=1,
                last_accessed_at=now - 60 * 86400,  # old
            )
        _add_memory(client, "ws_1", "active_mem", tier="L0")
        _add_meta(
            client, "active_mem", "ws_1",
            access_count=50,
            last_accessed_at=now - 3600,  # recent
        )

        result = evict_from_working(
            client, "ws_1",
            max_l0_size=5,
            eviction_idle_threshold=30 * 86400,
        )
        evicted_ids = [e["memory_id"] for e in result["evictions"]]
        assert "active_mem" not in evicted_ids

    def test_dry_run_does_not_evict(self):
        client = _make_mock_client()
        now = time.time()
        for i in range(6):
            _add_memory(client, "ws_1", f"l0_mem_{i}", tier="L0")
            _add_meta(
                client, f"l0_mem_{i}", "ws_1",
                access_count=1,
                last_accessed_at=now - 60 * 86400,
            )
        result = evict_from_working(
            client, "ws_1",
            max_l0_size=5,
            dry_run=True,
        )
        assert len(result["evictions"]) == 1
        assert result["evictions"][0]["dry_run"] is True
        client.update_memory_tier.assert_not_called()

    def test_handles_query_error(self):
        client = _make_mock_client()
        client._query.side_effect = RuntimeError("STDB down")
        result = evict_from_working(client, "ws_1")
        assert "error" in result["stats"]


# ===========================================================================
# Tests for tier_aware_search
# ===========================================================================


class TestTierAwareSearch:
    """Search with tier filtering."""

    def test_passes_tier_to_search(self):
        client = _make_mock_client()
        client.search.return_value = [{"id": "mem_1"}]
        result = tier_aware_search(client, "ws_1", "hello", tier="L0", limit=10)

        # Verify client.search was called with the tier param
        call_kwargs = client.search.call_args[1]
        assert call_kwargs.get("tier") == "L0"
        assert call_kwargs.get("query") == "hello"
        assert call_kwargs.get("limit") == 10

    def test_unwraps_dict_results(self):
        client = _make_mock_client()
        client.search.return_value = {"results": [{"id": "mem_1"}, {"id": "mem_2"}]}
        result = tier_aware_search(client, "ws_1", "test")
        assert len(result) == 2
        assert result[0]["id"] == "mem_1"

    def test_rejects_invalid_tier(self):
        client = _make_mock_client()
        with pytest.raises(ValueError, match="Invalid tier"):
            tier_aware_search(client, "ws_1", "test", tier="L3", limit=10)

    def test_passes_through_kwargs(self):
        client = _make_mock_client()
        client.search.return_value = []
        tier_aware_search(
            client, "ws_1", "test",
            tier="L1",
            semantic=False,
            rerank=True,
        )
        call_kwargs = client.search.call_args[1]
        assert call_kwargs.get("semantic") is False
        assert call_kwargs.get("rerank") is True


# ===========================================================================
# Tests for filter_by_tier
# ===========================================================================


class TestFilterByTier:
    """Direct tier-based memory queries."""

    def test_filters_single_tier(self):
        client = _make_mock_client()
        for i in range(3):
            _add_memory(client, "ws_1", f"l2_{i}", tier="L2")
        for i in range(2):
            _add_memory(client, "ws_1", f"l1_{i}", tier="L1")
        result = filter_by_tier(client, "ws_1", "L2")
        assert len(result) == 3
        assert all(r.get("tier") == "L2" for r in result)

    def test_filters_multiple_tiers(self):
        client = _make_mock_client()
        for i in range(3):
            _add_memory(client, "ws_1", f"l0_{i}", tier="L0")
        for i in range(2):
            _add_memory(client, "ws_1", f"l1_{i}", tier="L1")
        result = filter_by_tier(client, "ws_1", ["L0", "L1"])
        assert len(result) == 5

    def test_returns_empty_for_no_match(self):
        client = _make_mock_client()
        _add_memory(client, "ws_1", "mem_1", tier="L0")
        result = filter_by_tier(client, "ws_1", "L2")
        assert result == []

    def test_respects_limit(self):
        client = _make_mock_client()
        for i in range(20):
            _add_memory(client, "ws_1", f"mem_{i}", tier="L0")
        result = filter_by_tier(client, "ws_1", "L0", limit=5)
        assert len(result) == 5

    def test_rejects_invalid_tier_string(self):
        client = _make_mock_client()
        with pytest.raises(ValueError, match="Invalid tier"):
            filter_by_tier(client, "ws_1", "L3")

    def test_rejects_invalid_tier_in_list(self):
        client = _make_mock_client()
        with pytest.raises(ValueError, match="Invalid tier"):
            filter_by_tier(client, "ws_1", ["L0", "L4"])


# ===========================================================================
# Tests for run_memory_lifecycle
# ===========================================================================


class TestRunMemoryLifecycle:
    """Full lifecycle orchestration."""

    def test_lifecycle_runs_both_promotion_and_eviction(self):
        client = _make_mock_client()
        now = time.time()

        # Some L2 memories eligible for promotion
        _add_memory(client, "ws_1", "l2_active", tier="L2")
        _add_meta(
            client, "l2_active", "ws_1",
            access_count=10,
            last_accessed_at=now - 3600,
        )

        # L0 over limit with idle memories
        for i in range(6):
            _add_memory(client, "ws_1", f"l0_idle_{i}", tier="L0")
            _add_meta(
                client, f"l0_idle_{i}", "ws_1",
                access_count=1,
                last_accessed_at=now - 90 * 86400,
            )

        result = run_memory_lifecycle(
            client, "ws_1",
            max_l0_size=5,
            max_promotions=5,
        )

        assert len(result["promotions"]) >= 1  # L2→L1 happened
        assert len(result["evictions"]) >= 1   # L0 overflow handled
        assert result["stats"]["workspace_id"] == "ws_1"

    def test_dry_run_does_not_mutate(self):
        client = _make_mock_client()
        now = time.time()
        _add_memory(client, "ws_1", "l2_active", tier="L2")
        _add_meta(
            client, "l2_active", "ws_1",
            access_count=10,
            last_accessed_at=now - 3600,
        )
        result = run_memory_lifecycle(
            client, "ws_1",
            max_promotions=5,
            dry_run=True,
        )
        assert result["stats"]["dry_run"] is True
        client.update_memory_tier.assert_not_called()


# ===========================================================================
# Integration: chained operations
# ===========================================================================


class TestIntegration:
    """End-to-end workflow."""

    def test_track_then_promote(self):
        """Track accesses → auto-promote should pick up tracked data."""
        client = _make_mock_client()
        _add_memory(client, "ws_1", "mem_1", tier="L2")

        # Track 5 accesses
        now = time.time()
        _add_meta(
            client, "mem_1", "ws_1",
            access_count=5,
            last_accessed_at=now - 3600,
        )

        # Should be eligible for L2→L1
        result = auto_promote(
            client, "ws_1",
            l2_to_l1_min_accesses=3,
        )
        assert len(result["promotions"]) == 1
        assert result["promotions"][0]["to_tier"] == "L1"

    def test_filter_by_tier_after_promotion(self):
        """After promoting, filter_by_tier shows updated tier."""
        client = _make_mock_client()
        _add_memory(client, "ws_1", "mem_1", tier="L2")

        # Simulate promotion (our mock doesn't actually change the memory
        # table's tier field, so we manually update it)
        promote_memory(client, "ws_1", "mem_1", "L1")
        for row in client._memory_table:
            if row["id"] == "mem_1":
                row["tier"] = "L1"
                break

        result = filter_by_tier(client, "ws_1", "L1")
        assert len(result) == 1
        assert result[0]["id"] == "mem_1"

    def test_full_lifecycle_does_not_crash(self):
        """Run the full lifecycle on a realistic workspace."""
        client = _make_mock_client()
        now = time.time()

        # Mix of tiers with varied access patterns
        tiers = ["L0", "L1", "L2"]
        for i in range(20):
            tier = tiers[i % 3]
            mid = f"mem_{i}"
            _add_memory(client, "ws_1", mid, tier=tier)
            _add_meta(
                client, mid, "ws_1",
                access_count=i * 2,
                last_accessed_at=now - (i + 1) * 3600,
                created_at=now - (i + 10) * 86400,
            )

        # Should not raise
        result = run_memory_lifecycle(
            client, "ws_1",
            max_l0_size=5,
            max_promotions=10,
        )
        assert "promotions" in result
        assert "evictions" in result
        assert "stats" in result
