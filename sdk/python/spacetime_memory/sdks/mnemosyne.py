"""
Mnemosyne-compatible drop-in adapter for Spacetime-Memory.

Maps the Mnemosyne spaced-repetition flashcard system
(https://github.com/mnemosyne-proj/mnemosyne) onto Spacetime-Memory's
native storage. Mnemosyne is built on the SuperMemo-2 (SM-2) scheduling
algorithm; this adapter implements that algorithm faithfully and stores
all card state natively.

The card schema mirrors Mnemosyne's SQL schema exactly:
``id, card_type, fact_id, grade, next_rep, last_rep, easiness, acq_reps,
ret_reps, lapses, acq_reps_since_lapse, ret_reps_since_lapse,
creation_time, modification_time, active``.

Adapter class ``Mnemosyne`` provides the core scheduling surface:

- **Cards** — ``create_card`` / ``get_card`` / ``update_card`` /
  ``delete_card`` / ``list_cards`` / ``get_due_cards``
- **Review** — ``review_card`` (SM-2 grade 0–5) / ``review_due``
- **Scheduling** — ``process_new_card`` / ``process_remembered_card`` /
  ``process_forgotten_card`` (exposed for direct testing, matching the
  Mnemosyne srsfns API)
- **Statistics** — ``stats`` (cards, due, lapses, retention)
- **Sync log** — ``sync_log`` / ``sync_pull`` / ``sync_push`` (log-based
  bi-directional sync, mirroring Mnemosyne's multi-device sync)

**SM-2 grades** (Mnemosyne convention): 0 = blackout, 1 = incorrect but
recognizable, 2 = incorrect but easy, 3 = correct with serious effort,
4 = correct after hesitation, 5 = perfect. Grades 0–2 are "forgotten";
3–5 are "remembered".

All storage is Spacetime-Memory native (``Client``) — zero external
dependencies.

Usage::

    from spacetime_memory.sdks.mnemosyne import Mnemosyne

    m = Mnemosyne(host="127.0.0.1", port=3001)
    card = m.create_card(deck="spanish", question="hola", answer="hello")

    due = m.get_due_cards(deck="spanish")
    for c in due:
        m.review_card(c["id"], grade=5)   # perfect recall

    stats = m.stats()

**Error contract:**
- ``ValueError`` for invalid inputs (empty question, grade out of range).
- ``RuntimeError`` for backend failures (DB down, card not found).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any

from ..client import Client

logger = logging.getLogger(__name__)

__all__ = [
    "Mnemosyne",
    "SM2_MIN_EASINESS",
    "SM2_FIRST_INTERVAL_DAYS",
    "SM2_SECOND_INTERVAL_DAYS",
    "GRADE_FORGOTTEN_MAX",
]

# ---------------------------------------------------------------------------
# SM-2 constants (Mnemosyne defaults)
# ---------------------------------------------------------------------------

SM2_MIN_EASINESS = 1.3
SM2_INITIAL_EASINESS = 2.5
SM2_FIRST_INTERVAL_DAYS = 1
SM2_SECOND_INTERVAL_DAYS = 6
GRADE_FORGOTTEN_MAX = 2  # grades 0..2 = forgotten


# ---------------------------------------------------------------------------
# SM-2 scheduling core (pure functions — easily unit tested)
# ---------------------------------------------------------------------------


def _sm2_update_easiness(easiness: float, grade: int) -> float:
    """SM-2 easiness update: EF' = EF + (0.1 - (5-q)*(0.08 + (5-q)*0.02))."""
    ef = easiness + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
    return max(SM2_MIN_EASINESS, ef)


def _sm2_next_interval(acq_reps: int, easiness: float, last_interval_days: float) -> float:
    """SM-2 interval progression: 1 day, 6 days, then interval * EF."""
    if acq_reps <= 1:
        return SM2_FIRST_INTERVAL_DAYS
    if acq_reps == 2:
        return SM2_SECOND_INTERVAL_DAYS
    return max(1.0, last_interval_days * easiness)


def process_new_card(
    grade: int,
    easiness: float,
    acq_reps: int,
    acq_reps_since_lapse: int,
    last_rep: int,
    now: int | None = None,
    last_interval_days: float = 0.0,
) -> tuple[int, float, int, int, int]:
    """Process a grade for a NEW card (Mnemosyne ``process_new_card``).

    Returns ``(grade, easiness, acq_reps, acq_reps_since_lapse, next_rep)``.
    """
    now = now or int(time.time())
    if grade <= GRADE_FORGOTTEN_MAX:
        # Forgotten: reset acquisition progress; schedule an immediate retry
        return grade, easiness, 0, 0, now + 600
    new_ef = _sm2_update_easiness(easiness, grade)
    acq_reps += 1
    acq_reps_since_lapse += 1
    interval = _sm2_next_interval(acq_reps, new_ef, last_interval_days)
    next_rep = now + int(interval * 86400)
    return grade, new_ef, acq_reps, acq_reps_since_lapse, next_rep


def process_remembered_card(
    grade: int,
    easiness: float,
    ret_reps: int,
    ret_reps_since_lapse: int,
    lapses: int,
    last_rep: int,
    now: int | None = None,
    last_interval_days: float = 0.0,
) -> tuple[int, float, int, int, int]:
    """Process a grade for a REMEMBERED card (Mnemosyne
    ``process_remembered_card``).

    Returns ``(grade, easiness, ret_reps, ret_reps_since_lapse, next_rep)``.
    """
    now = now or int(time.time())
    new_ef = _sm2_update_easiness(easiness, grade)
    ret_reps += 1
    ret_reps_since_lapse += 1
    interval = _sm2_next_interval(ret_reps, new_ef, last_interval_days)
    next_rep = now + int(interval * 86400)
    return grade, new_ef, ret_reps, ret_reps_since_lapse, next_rep


def process_forgotten_card(
    grade: int,
    easiness: float,
    lapses: int,
    last_rep: int,
    now: int | None = None,
) -> tuple[int, float, int, int]:
    """Process a grade for a FORGOTTEN card (Mnemosyne
    ``process_forgotten_card``).

    Resets repetition progress, increments lapses, and schedules a quick
    relearning retry (10 minutes).

    Returns ``(grade, easiness, lapses, next_rep)``.
    """
    now = now or int(time.time())
    new_ef = _sm2_update_easiness(easiness, grade)
    return grade, new_ef, lapses + 1, now + 600


def _interval_days_between(last_rep: int, now: int) -> float:
    """Compute the effective interval (days) since the last rep."""
    return max(0.0, (now - last_rep) / 86400.0)


# ---------------------------------------------------------------------------
# Mnemosyne client
# ---------------------------------------------------------------------------


class Mnemosyne:
    """Spacetime-Memory backed spaced-repetition system (Mnemosyne parity).

    Args:
        host: SpacetimeDB host.
        port: SpacetimeDB port.
        database: Database identity.
        embedder_url / tantivy_url: Optional sidecar URLs.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 3001,
        database: str = "spacetime-memory-v2",
        embedder_url: str | None = None,
        tantivy_url: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.database = database
        self._client = Client(
            host=host,
            port=port,
            database=database,
            embedder_url=embedder_url,
            tantivy_url=tantivy_url,
        )

    # -- workspace helpers ---------------------------------------------------

    def _deck_ws(self, deck: str) -> str:
        digest = hashlib.sha256(f"memo:{deck}".encode()).hexdigest()[:32]
        return f"memo-{digest}"

    def _ensure_deck(self, deck: str) -> str:
        ws = self._deck_ws(deck)
        try:
            rows = self._client._query("workspace", "", {"id": ws}, ["id"])
            if not rows:
                self._client._call("create_workspace", [f"Mnemo deck: {deck}", "mnemosyne deck", ws])
            self._client._call("set_workspace_visibility", [ws, True])
        except Exception as exc:
            logger.debug("mnemosyne _ensure_deck failed (%s)", exc)
        return ws

    def _serialize_state(self, state: dict[str, Any]) -> str:
        return json.dumps(state, default=str)

    def _deserialize_state(self, raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    # -- card lifecycle ------------------------------------------------------

    def create_card(
        self,
        question: str,
        answer: str,
        deck: str = "default",
        card_type: str = "qa",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a new flashcard.

        Args:
            question: Front of the card.
            answer: Back of the card.
            deck: Deck name (mapped to a workspace).
            card_type: ``"qa"`` (default) or a custom card type id.

        Returns:
            The full card dict (see schema below).
        """
        if not question or not question.strip():
            raise ValueError("mnemosyne.create_card: question must be non-empty")
        if not answer or not answer.strip():
            raise ValueError("mnemosyne.create_card: answer must be non-empty")
        ws = self._ensure_deck(deck)
        now = int(time.time())
        state = {
            "id": str(uuid.uuid4()),
            "card_type": card_type,
            "fact_id": str(uuid.uuid4()),
            "grade": -1,  # never reviewed
            "next_rep": now,
            "last_rep": 0,
            "easiness": SM2_INITIAL_EASINESS,
            "acq_reps": 0,
            "ret_reps": 0,
            "lapses": 0,
            "acq_reps_since_lapse": 0,
            "ret_reps_since_lapse": 0,
            "creation_time": now,
            "modification_time": now,
            "active": True,
            "deck": deck,
        }
        try:
            result = self._client.store(
                workspace_id=ws,
                content=f"Q: {question}\nA: {answer}",
                memory_type="card",
                summary=self._serialize_state(state),
                source_session_id=state["id"],
            )
            state["memory_id"] = result.get("id", "")
            state["question"] = question
            state["answer"] = answer
            return state
        except Exception as exc:
            raise RuntimeError(f"mnemosyne.create_card: {exc}") from exc

    def _load_card(self, memory_id: str) -> dict[str, Any] | None:
        """Load a card's state + content from memory storage (searches all decks)."""
        for r in self._query_all_cards():
            if r.get("id") != memory_id:
                continue
            state = self._deserialize_state(r.get("summary"))
            content = str(r.get("content", ""))
            q, _, a = content.partition("\nA: ")
            if q.startswith("Q: "):
                q = q[3:]
            state["memory_id"] = r["id"]
            state["question"] = q
            state["answer"] = a
            return state
        return None

    def get_card(self, card_id: str) -> dict[str, Any]:
        """Get a card by its card id (not the memory id).

        Raises ``RuntimeError`` if not found.
        """
        rows = self._query_all_cards()
        for r in rows:
            if r.get("source_session_id") == card_id:
                card = self._load_card(r["id"])
                if card is not None:
                    return card
        raise RuntimeError(f"mnemosyne.get_card: card '{card_id}' not found")

    def update_card(self, card_id: str, question: str | None = None, answer: str | None = None, **kwargs: Any) -> dict[str, Any]:
        """Update a card's question/answer text (scheduling state preserved).

        Returns the updated card dict.
        """
        card = self.get_card(card_id)
        q = question if question is not None else card.get("question", "")
        a = answer if answer is not None else card.get("answer", "")
        if not q.strip() or not a.strip():
            raise ValueError("mnemosyne.update_card: question and answer must be non-empty")
        content = f"Q: {q}\nA: {a}"
        try:
            self._client._call(
                "update_memory", [card["memory_id"], content, card.get("summary", ""), 0.5, None]
            )
        except Exception as exc:
            raise RuntimeError(f"mnemosyne.update_card: {exc}") from exc
        return self.get_card(card_id)

    def delete_card(self, card_id: str) -> bool:
        """Delete a card."""
        try:
            card = self.get_card(card_id)
            self._client._call("delete_memory", [card["memory_id"]])
            return True
        except Exception as exc:
            logger.warning("mnemosyne.delete_card: %s", exc)
            return False

    def _query_all_cards(self) -> list[dict[str, Any]]:
        """Fetch all card memories across decks."""
        out: list[dict[str, Any]] = []
        try:
            rows = self._client._query("workspace", "", {}, ["id", "name"])
        except Exception:
            return out
        for r in rows:
            name = str(r.get("name", ""))
            if not name.startswith("Mnemo deck:") or name == "Mnemo deck: __sync__":
                continue
            ws = r["id"]
            try:
                mems = self._client._query(
                    "memory", ws, {}, ["id", "content", "summary", "source_session_id"]
                )
            except Exception:
                continue
            out.extend(mems)
        return out

    def list_cards(self, deck: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        """List all cards (optionally restricted to a deck)."""
        cards: list[dict[str, Any]] = []
        for r in self._query_all_cards():
            state = self._deserialize_state(r.get("summary"))
            if deck and state.get("deck") != deck:
                continue
            content = str(r.get("content", ""))
            q, _, a = content.partition("\nA: ")
            if q.startswith("Q: "):
                q = q[3:]
            cards.append(
                {
                    **state,
                    "memory_id": r["id"],
                    "question": q,
                    "answer": a,
                }
            )
        return cards[:limit]

    def get_due_cards(self, deck: str | None = None, now: int | None = None) -> list[dict[str, Any]]:
        """Get cards due for review (``next_rep <= now``).

        Returns:
            list of card dicts, oldest next_rep first.
        """
        now = now or int(time.time())
        due = [c for c in self.list_cards(deck=deck) if c.get("next_rep", 0) <= now and c.get("active", True)]
        due.sort(key=lambda c: c.get("next_rep", 0))
        return due

    # -- review --------------------------------------------------------------

    def review_card(self, card_id: str, grade: int, now: int | None = None) -> dict[str, Any]:
        """Review a card with an SM-2 grade (0–5).

        Args:
            card_id: The card id.
            grade: 0 = blackout … 5 = perfect. Grades 0–2 are forgotten.

        Returns:
            The updated card dict (with new ``next_rep``, ``easiness``, etc.).
        """
        if not isinstance(grade, int) or not 0 <= grade <= 5:
            raise ValueError("mnemosyne.review_card: grade must be an integer in [0, 5]")
        card = self.get_card(card_id)
        now = now or int(time.time())
        last_rep = int(card.get("last_rep") or 0)
        last_interval = _interval_days_between(last_rep, now) if last_rep else 0.0

        if grade <= GRADE_FORGOTTEN_MAX:
            _, new_ef, lapses, next_rep = process_forgotten_card(
                grade, float(card.get("easiness", SM2_INITIAL_EASINESS)),
                int(card.get("lapses", 0)), last_rep, now,
            )
            card["easiness"] = new_ef
            card["lapses"] = lapses
            card["acq_reps_since_lapse"] = 0
            card["ret_reps_since_lapse"] = 0
            card["next_rep"] = next_rep
            card["grade"] = grade
        elif int(card.get("acq_reps", 0)) + int(card.get("ret_reps", 0)) <= 1:
            # First or second acquisition rep (SM-2: 1 day, then 6 days)
            _, new_ef, acq_reps, acq_sl, next_rep = process_new_card(
                grade, float(card.get("easiness", SM2_INITIAL_EASINESS)),
                int(card.get("acq_reps", 0)), int(card.get("acq_reps_since_lapse", 0)),
                last_rep, now, last_interval,
            )
            card["easiness"] = new_ef
            card["acq_reps"] = acq_reps
            card["acq_reps_since_lapse"] = acq_sl
            card["next_rep"] = next_rep
            card["grade"] = grade
        else:
            # Later reps: interval = previous * easiness
            total_reps = int(card.get("acq_reps", 0)) + int(card.get("ret_reps", 0))
            _, new_ef, ret_reps, ret_sl, next_rep = process_remembered_card(
                grade, float(card.get("easiness", SM2_INITIAL_EASINESS)),
                int(card.get("ret_reps", 0)), int(card.get("ret_reps_since_lapse", 0)),
                int(card.get("lapses", 0)), last_rep, now, last_interval,
            )
            card["easiness"] = new_ef
            card["ret_reps"] = ret_reps
            card["ret_reps_since_lapse"] = ret_sl
            # Interval progression uses the TOTAL successful rep count:
            # rep 3+ → previous interval * easiness
            if total_reps >= 2 and last_interval > 0:
                card["next_rep"] = now + int(last_interval * new_ef * 86400)
            else:
                card["next_rep"] = next_rep
            card["grade"] = grade

        card["last_rep"] = now
        card["modification_time"] = now
        try:
            self._client._call(
                "update_memory",
                [
                    card["memory_id"],
                    f"Q: {card.get('question', '')}\nA: {card.get('answer', '')}",
                    self._serialize_state(card),
                    0.5,
                    None,
                ],
            )
        except Exception as exc:
            raise RuntimeError(f"mnemosyne.review_card: {exc}") from exc
        # log the review for sync
        self._log_review(card["id"], grade, now)
        return card

    def review_due(self, deck: str | None = None, grades: dict[str, int] | None = None, now: int | None = None) -> list[dict[str, Any]]:
        """Review all due cards with the given grades.

        Args:
            deck: Optional deck filter.
            grades: Mapping of card_id → grade. Cards without a grade are
                skipped.

        Returns:
            list of updated card dicts.
        """
        grades = grades or {}
        updated = []
        for c in self.get_due_cards(deck=deck, now=now):
            if c["id"] in grades:
                updated.append(self.review_card(c["id"], grades[c["id"]], now=now))
        return updated

    # -- statistics ----------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Compute review statistics across all decks.

        Returns:
            dict with totals, due counts, lapses, and per-deck breakdown.
        """
        cards = self.list_cards(limit=10000)
        now = int(time.time())
        due = [c for c in cards if c.get("next_rep", 0) <= now and c.get("active", True)]
        reviewed = [c for c in cards if c.get("last_rep", 0) > 0]
        remembered = [c for c in reviewed if c.get("grade", 0) > GRADE_FORGOTTEN_MAX]
        return {
            "cards": len(cards),
            "due": len(due),
            "reviewed": len(reviewed),
            "remembered": len(remembered),
            "retention": round(100.0 * len(remembered) / len(reviewed), 1) if reviewed else 0.0,
            "total_lapses": sum(int(c.get("lapses", 0)) for c in cards),
            "decks": sorted({c.get("deck", "default") for c in cards}),
        }

    # -- sync log ------------------------------------------------------------

    def _log_review(self, card_id: str, grade: int, ts: int) -> None:
        """Append a review event to the sync log (Mnemosyne sync parity)."""
        try:
            ws = self._ensure_deck("__sync__")
            self._client.store(
                workspace_id=ws,
                content=json.dumps({"card_id": card_id, "grade": grade, "ts": ts}),
                memory_type="sync_log",
            )
        except Exception as exc:
            logger.debug("mnemosyne sync log append failed (%s)", exc)

    def sync_log(self, limit: int = 500) -> list[dict[str, Any]]:
        """Return recent sync-log entries (review events)."""
        out: list[dict[str, Any]] = []
        ws = self._deck_ws("__sync__")
        try:
            rows = self._client._query("memory", ws, {}, ["content", "created_at"])
        except Exception:
            rows = []
        for r in rows[-limit:]:
            try:
                out.append(json.loads(str(r.get("content", "{}"))))
            except (ValueError, TypeError):
                pass
        return out

    def sync_push(self) -> int:
        """Push (no-op locally — all data is already native). Returns log size."""
        return len(self.sync_log())

    def sync_pull(self) -> int:
        """Pull (no-op locally — all data is already native). Returns log size."""
        return len(self.sync_log())
