"""Tests for the Mnemosyne-compatible adapter (``spacetime_memory.sdks.mnemosyne``).

Unit tests use a fake Client (no live STDB needed). Integration tests
(marked ``integration``) require a live SpacetimeDB.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import pytest

from spacetime_memory.sdks.mnemosyne import (
    GRADE_FORGOTTEN_MAX,
    Mnemosyne,
    SM2_FIRST_INTERVAL_DAYS,
    SM2_MIN_EASINESS,
    SM2_SECOND_INTERVAL_DAYS,
    process_forgotten_card,
    process_new_card,
    process_remembered_card,
    _sm2_next_interval,
    _sm2_update_easiness,
)


# ---------------------------------------------------------------------------
# Fake Client
# ---------------------------------------------------------------------------


class FakeClient:
    def __init__(self) -> None:
        self.memories: dict[str, list[dict[str, Any]]] = {}
        self.workspaces: dict[str, dict[str, Any]] = {}

    def store(self, workspace_id, content, memory_type="experience", **kw) -> dict[str, Any]:
        row = {
            "id": str(uuid.uuid4()),
            "content": content,
            "memory_type": memory_type,
            "summary": kw.get("summary", ""),
            "source_session_id": kw.get("source_session_id", ""),
            "created_at": "",
        }
        self.memories.setdefault(workspace_id, []).append(row)
        return {"id": row["id"]}

    def _query(self, table, ws, filt=None, cols=None) -> list[dict[str, Any]]:
        filt = filt or {}
        if table == "memory":
            rows = list(self.memories.get(ws, []))
            if filt.get("id"):
                rows = [r for r in rows if r.get("id") == filt["id"]]
            if cols:
                rows = [{k: r.get(k) for k in cols} for r in rows]
            return rows
        if table == "workspace":
            out = [
                {"id": wid, "name": meta.get("name", "")} for wid, meta in self.workspaces.items()
            ]
            if filt.get("id"):
                out = [r for r in out if r.get("id") == filt["id"]]
            if cols:
                out = [{k: r.get(k) for k in cols} for r in out]
            return out
        return []

    def _call(self, reducer: str, args: list[Any]) -> Any:
        if reducer == "create_workspace":
            self.workspaces[args[2]] = {"name": args[0], "description": args[1]}
        elif reducer == "set_workspace_visibility":
            pass
        elif reducer == "update_memory":
            for rows in self.memories.values():
                for r in rows:
                    if r.get("id") == args[0]:
                        r["content"] = args[1]
                        r["summary"] = args[2]
                        return None
            raise RuntimeError("not found")
        elif reducer == "delete_memory":
            for wid, rows in self.memories.items():
                for i, r in enumerate(rows):
                    if r.get("id") == args[0]:
                        del self.memories[wid][i]
                        return None
        return None


@pytest.fixture
def memo(monkeypatch) -> Mnemosyne:
    fake = FakeClient()
    m = Mnemosyne(host="127.0.0.1", port=3001)
    monkeypatch.setattr(m, "_client", fake)
    m._fake = fake  # type: ignore[attr-defined]
    return m


# ---------------------------------------------------------------------------
# SM-2 core
# ---------------------------------------------------------------------------


class TestSM2Core:
    def test_initial_easiness(self) -> None:
        # grade 5: EF' = 2.5 + 0.1 = 2.6
        assert _sm2_update_easiness(2.5, 5) == pytest.approx(2.6)

    def test_easiness_floor(self) -> None:
        assert _sm2_update_easiness(1.3, 0) >= SM2_MIN_EASINESS
        # grade 0: EF' = 2.5 + (0.1 - 5*(0.08 + 5*0.02)) = 2.5 - 0.8 = 1.7
        assert _sm2_update_easiness(2.5, 0) == pytest.approx(1.7)

    def test_first_interval(self) -> None:
        assert _sm2_next_interval(1, 2.6, 0.0) == SM2_FIRST_INTERVAL_DAYS

    def test_second_interval(self) -> None:
        assert _sm2_next_interval(2, 2.6, 0.0) == SM2_SECOND_INTERVAL_DAYS

    def test_interval_grows_by_easiness(self) -> None:
        assert _sm2_next_interval(3, 2.6, 6.0) == pytest.approx(15.6)

    def test_process_new_card_remembered(self) -> None:
        now = 1_000_000
        grade, ef, reps, sl, next_rep = process_new_card(5, 2.5, 0, 0, 0, now=now)
        assert reps == 1
        assert sl == 1
        assert next_rep == now + 86400  # 1 day

    def test_process_new_card_forgotten(self) -> None:
        now = 1_000_000
        grade, ef, reps, sl, next_rep = process_new_card(1, 2.5, 0, 0, 0, now=now)
        assert reps == 0
        assert next_rep == now + 600  # retry in 10 min

    def test_process_remembered_progression(self) -> None:
        now = 1_000_000
        # first successful acquisition rep → interval 1 day
        _, ef1, reps1, _, next1 = process_new_card(5, 2.5, 0, 0, 0, now=now)
        # second acquisition rep → interval 6 days
        _, ef2, reps2, _, next2 = process_new_card(5, ef1, reps1, 1, now, now=now, last_interval_days=1.0)
        assert reps2 == 2
        assert next2 == now + 6 * 86400

    def test_process_forgotten_increments_lapses(self) -> None:
        now = 1_000_000
        grade, ef, lapses, next_rep = process_forgotten_card(2, 2.5, 0, now - 86400, now=now)
        assert lapses == 1
        assert next_rep == now + 600

    def test_grade_threshold(self) -> None:
        assert GRADE_FORGOTTEN_MAX == 2


# ---------------------------------------------------------------------------
# Card lifecycle
# ---------------------------------------------------------------------------


class TestCardLifecycle:
    def test_create_card(self, memo: Mnemosyne) -> None:
        card = memo.create_card("hola", "hello", deck="spanish")
        assert card["question"] == "hola"
        assert card["answer"] == "hello"
        assert card["deck"] == "spanish"
        assert card["easiness"] == 2.5
        assert card["acq_reps"] == 0
        assert card["next_rep"] <= int(time.time())

    def test_create_card_empty_raises(self, memo: Mnemosyne) -> None:
        with pytest.raises(ValueError, match="question must be non-empty"):
            memo.create_card("", "answer")
        with pytest.raises(ValueError, match="answer must be non-empty"):
            memo.create_card("question", "")

    def test_get_card(self, memo: Mnemosyne) -> None:
        card = memo.create_card("q1", "a1")
        got = memo.get_card(card["id"])
        assert got["id"] == card["id"]
        assert got["question"] == "q1"

    def test_get_card_missing_raises(self, memo: Mnemosyne) -> None:
        with pytest.raises(RuntimeError, match="not found"):
            memo.get_card("no-such")

    def test_update_card(self, memo: Mnemosyne) -> None:
        card = memo.create_card("q1", "a1")
        updated = memo.update_card(card["id"], question="q2", answer="a2")
        assert updated["question"] == "q2"
        assert updated["answer"] == "a2"

    def test_update_card_empty_raises(self, memo: Mnemosyne) -> None:
        card = memo.create_card("q1", "a1")
        with pytest.raises(ValueError):
            memo.update_card(card["id"], question="")

    def test_delete_card(self, memo: Mnemosyne) -> None:
        card = memo.create_card("q1", "a1")
        assert memo.delete_card(card["id"]) is True
        with pytest.raises(RuntimeError):
            memo.get_card(card["id"])

    def test_list_cards(self, memo: Mnemosyne) -> None:
        memo.create_card("q1", "a1", deck="d1")
        memo.create_card("q2", "a2", deck="d2")
        assert len(memo.list_cards()) == 2
        assert len(memo.list_cards(deck="d1")) == 1

    def test_get_due_cards(self, memo: Mnemosyne) -> None:
        card = memo.create_card("q1", "a1")
        due = memo.get_due_cards()
        assert any(c["id"] == card["id"] for c in due)


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


class TestReview:
    def test_review_perfect_grade_schedules_tomorrow(self, memo: Mnemosyne) -> None:
        card = memo.create_card("q1", "a1")
        now = int(time.time())
        updated = memo.review_card(card["id"], grade=5, now=now)
        assert updated["grade"] == 5
        assert updated["acq_reps"] == 1
        assert updated["next_rep"] == now + 86400
        assert updated["easiness"] == pytest.approx(2.6)

    def test_review_good_grade_second_interval(self, memo: Mnemosyne) -> None:
        card = memo.create_card("q1", "a1")
        now = int(time.time())
        r1 = memo.review_card(card["id"], grade=5, now=now)
        r2 = memo.review_card(card["id"], grade=4, now=now + 86400)
        assert r2["acq_reps"] == 2
        assert r2["next_rep"] == now + 86400 + 6 * 86400
        # EF after grade 4: 2.6 + (0.1 - 1*(0.08+0.02)) = 2.6
        assert r2["easiness"] == pytest.approx(2.6)

    def test_review_forgotten_resets_and_lapses(self, memo: Mnemosyne) -> None:
        card = memo.create_card("q1", "a1")
        now = int(time.time())
        memo.review_card(card["id"], grade=5, now=now)
        r2 = memo.review_card(card["id"], grade=0, now=now + 100)
        assert r2["lapses"] == 1
        assert r2["acq_reps_since_lapse"] == 0
        assert r2["next_rep"] == now + 100 + 600

    def test_review_invalid_grade_raises(self, memo: Mnemosyne) -> None:
        card = memo.create_card("q1", "a1")
        with pytest.raises(ValueError, match="grade must be an integer"):
            memo.review_card(card["id"], grade=6)
        with pytest.raises(ValueError, match="grade must be an integer"):
            memo.review_card(card["id"], grade=-1)

    def test_review_due(self, memo: Mnemosyne) -> None:
        c1 = memo.create_card("q1", "a1")
        c2 = memo.create_card("q2", "a2")
        updated = memo.review_due(grades={c1["id"]: 5, c2["id"]: 4})
        assert len(updated) == 2
        for c in updated:
            assert c["grade"] in (4, 5)

    def test_after_perfect_review_not_due(self, memo: Mnemosyne) -> None:
        card = memo.create_card("q1", "a1")
        memo.review_card(card["id"], grade=5)
        assert memo.get_due_cards() == []


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


class TestStats:
    def test_stats_empty(self, memo: Mnemosyne) -> None:
        s = memo.stats()
        assert s["cards"] == 0
        assert s["due"] == 0

    def test_stats_counts(self, memo: Mnemosyne) -> None:
        memo.create_card("q1", "a1", deck="d1")
        memo.create_card("q2", "a2", deck="d1")
        memo.create_card("q3", "a3", deck="d2")
        s = memo.stats()
        assert s["cards"] == 3
        assert "d1" in s["decks"]
        assert "d2" in s["decks"]

    def test_stats_retention(self, memo: Mnemosyne) -> None:
        c = memo.create_card("q1", "a1")
        memo.review_card(c["id"], grade=5)
        s = memo.stats()
        assert s["reviewed"] == 1
        assert s["remembered"] == 1
        assert s["retention"] == 100.0

    def test_stats_after_lapse(self, memo: Mnemosyne) -> None:
        c = memo.create_card("q1", "a1")
        memo.review_card(c["id"], grade=0)
        s = memo.stats()
        assert s["total_lapses"] == 1


# ---------------------------------------------------------------------------
# Sync log
# ---------------------------------------------------------------------------


class TestSync:
    def test_review_logged(self, memo: Mnemosyne) -> None:
        c = memo.create_card("q1", "a1")
        memo.review_card(c["id"], grade=5)
        log = memo.sync_log()
        assert len(log) >= 1
        assert log[-1]["card_id"] == c["id"]
        assert log[-1]["grade"] == 5

    def test_sync_push_pull(self, memo: Mnemosyne) -> None:
        c = memo.create_card("q1", "a1")
        memo.review_card(c["id"], grade=4)
        assert memo.sync_push() >= 1
        assert memo.sync_pull() >= 1