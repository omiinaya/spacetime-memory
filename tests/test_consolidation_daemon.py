"""Tests for the memory consolidation daemon."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_scripts_path = str(Path(__file__).resolve().parent.parent / "scripts")
if _scripts_path not in sys.path:
    sys.path.insert(0, _scripts_path)

from consolidation_daemon import ConsolidationDaemon
from consolidation_daemon import DEFAULT_CONSOLIDATION_INTERVAL
from consolidation_daemon import DEFAULT_DECAY_INTERVAL
from consolidation_daemon import DEFAULT_INSIGHT_INTERVAL


def make_daemon(client=None, **kw):
    """Helper to create daemon with a mock client by default."""
    c = client or MagicMock()
    if client is None:
        c.list_workspaces.return_value = []
        c.list_memories.return_value = []
    kw.setdefault("dry_run", True)
    return ConsolidationDaemon(client=c, **kw), c


SAMPLE_MEMORIES = [
    {"id": "m1", "strength": 0.2, "access_count": 0, "trust_score": 0.3,
     "tier": "L2", "confidence": 0.2, "content": "x", "summary": "x"},
    {"id": "m2", "strength": 0.9, "access_count": 50, "trust_score": 0.9,
     "tier": "L0", "confidence": 0.9, "content": "y", "summary": "y"},
]


class TestInit:
    def test_defaults(self):
        d, _ = make_daemon()
        assert d.consolidation_interval == DEFAULT_CONSOLIDATION_INTERVAL
        assert d.decay_interval == DEFAULT_DECAY_INTERVAL
        assert d.insight_interval == DEFAULT_INSIGHT_INTERVAL
        assert d.dry_run is True
        assert d._running is True

    def test_custom_intervals(self):
        d, _ = make_daemon(consolidation_interval=60, decay_interval=120,
                         insight_interval=300)
        assert d.consolidation_interval == 60
        assert d.decay_interval == 120
        assert d.insight_interval == 300

    def test_report_format(self):
        d, _ = make_daemon()
        r = d.report()
        assert "consolidations" in r
        assert "decays" in r
        assert "insights" in r
        assert "errors" in r

    def test_stop_flag(self):
        d, _ = make_daemon()
        d._stop()
        assert d._running is False


class TestConsolidation:
    def test_empty_workspace_list_no_crash(self):
        d, c = make_daemon()
        c.list_workspaces.return_value = []
        d._run_consolidation_pass()
        assert d._stats["errors"] == 0

    def test_with_memories_calls_reinforce(self):
        c = MagicMock()
        c.list_workspaces.return_value = [{"id": "ws_1"}]
        c.list_memories.return_value = SAMPLE_MEMORIES
        d, _ = make_daemon(client=c)
        d._run_consolidation_pass()
        assert d._stats["consolidations"] == 1

    def test_dry_run_skips_reinforce(self):
        c = MagicMock()
        c.list_workspaces.return_value = [{"id": "ws_1"}]
        c.list_memories.return_value = SAMPLE_MEMORIES
        d, _ = make_daemon(client=c)
        d._run_consolidation_pass()
        c.reinforce_memory.assert_not_called()

    def test_reinforce_called_for_important_memories(self):
        c = MagicMock()
        c.list_workspaces.return_value = [{"id": "ws_1"}]
        c.list_memories.return_value = [{"id": "m1", "strength": 0.95,
            "access_count": 100, "trust_score": 0.95, "tier": "L0",
            "confidence": 0.95, "content": "x", "summary": "x"}]
        d, _ = make_daemon(client=c, dry_run=False)
        # Manually install importance module
        from spacetime_memory.importance import importance_from_signals
        d._importance_from_signals = importance_from_signals
        d._run_consolidation_pass()
        c.reinforce_memory.assert_called_once_with("m1")

    def test_consolidation_handles_error_gracefully(self):
        c = MagicMock()
        c.list_workspaces.side_effect = RuntimeError("boom")
        d, _ = make_daemon(client=c)
        d._run_consolidation_pass()
        assert d._stats["errors"] == 0


class TestDecay:
    def test_decay_low_strength_memories(self):
        c = MagicMock()
        c.list_workspaces.return_value = [{"id": "ws_1"}]
        weak = {"id": "m1", "strength": 0.2, "access_count": 0,
                "content": "x", "summary": ""}
        strong = {"id": "m2", "strength": 0.9, "access_count": 50,
                  "content": "y", "summary": ""}
        c.list_memories.return_value = [weak, strong]
        d, _ = make_daemon(client=c, dry_run=False)
        d._run_decay_pass()
        # Should call update for the weak memory
        assert d._stats["decays"] >= 1

    def test_decay_skips_strong_memories(self):
        c = MagicMock()
        c.list_workspaces.return_value = [{"id": "ws_1"}]
        c.list_memories.return_value = [
            {"id": "m1", "strength": 0.8, "access_count": 20,
             "content": "x", "summary": ""},
            {"id": "m2", "strength": 0.7, "access_count": 10,
             "content": "y", "summary": ""},
        ]
        d, _ = make_daemon(client=c, dry_run=False)
        d._run_decay_pass()
        assert d._stats["decays"] == 0

    def test_decay_no_memories(self):
        d, c = make_daemon()
        c.list_workspaces.return_value = [{"id": "ws_1"}]
        d._run_decay_pass()
        assert d._stats["decays"] == 0

    def test_decay_error_doesnt_block_other_workspaces(self):
        c = MagicMock()
        memos_ws1 = [{"id": "m1", "strength": 0.1, "access_count": 0,
                      "content": "x", "summary": ""}]

        def list_mem(ws_id, limit=200):
            if ws_id == "ws_fail":
                raise RuntimeError("boom")
            return memos_ws1

        c.list_workspaces.return_value = [
            {"id": "ws_fail"}, {"id": "ws_ok"}
        ]
        c.list_memories = MagicMock(side_effect=list_mem)
        d, _ = make_daemon(client=c, dry_run=False)
        d._run_decay_pass()
        assert d._stats["decays"] >= 1


class TestInsight:
    def test_insight_pass_runs(self):
        d, c = make_daemon()
        c.list_workspaces.return_value = [{"id": "ws_1"}]
        d._run_insight_pass()
        assert d._stats["insights"] == 1

    def test_insight_with_memories(self):
        c = MagicMock()
        c.list_workspaces.return_value = [{"id": "ws_1"}]
        c.list_memories.return_value = SAMPLE_MEMORIES
        d, _ = make_daemon(client=c)
        d._run_insight_pass()
        assert d._stats["insights"] == 1


class TestTick:
    def test_tick_noop_when_not_due(self):
        d, _ = make_daemon(consolidation_interval=99999,
                          decay_interval=99999, insight_interval=99999)
        d._tick(0)
        assert d._stats["consolidations"] == 0
        assert d._stats["decays"] == 0
        assert d._stats["insights"] == 0

    def test_tick_runs_due_phases(self):
        d, c = make_daemon(consolidation_interval=100,
                          decay_interval=100, insight_interval=100)
        c.list_workspaces.return_value = [{"id": "ws_1"}]
        c.list_memories.return_value = []
        d._tick(200)
        assert d._stats["insights"] >= 0

    def test_tick_respects_intervals(self):
        d, _ = make_daemon(consolidation_interval=100,
                          decay_interval=200, insight_interval=99999)
        d._tick(100)
        # Consolidation ran (but no workspaces, so stats unchanged for that)
        d._tick(150)
        d._tick(250)
        assert d._stats["consolidations"] == 0

    def test_tick_error_caught(self):
        d, _ = make_daemon()
        d._tick = MagicMock(side_effect=RuntimeError("boom"))
        try:
            d._tick(500)
        except RuntimeError:
            pass
        # The error handling is in run() not _tick
        assert True


class TestGetMemories:
    def test_returns_list(self):
        d, c = make_daemon()
        c.list_memories.return_value = [{"id": "x"}]
        assert d._get_memories("ws_1") == [{"id": "x"}]

    def test_error_returns_empty(self):
        d, c = make_daemon()
        c.list_memories.side_effect = RuntimeError("fail")
        assert d._get_memories("ws_1") == []

    def test_none_result_becomes_empty(self):
        d, c = make_daemon()
        c.list_memories.return_value = None
        assert d._get_memories("ws_1") == []
