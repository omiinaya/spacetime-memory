"""
Auto-summarization pipeline for spacetime-memory — Zep/Letta parity.

Provides batch memory summarization, extractive compression, tier-aware
summarization, background summarization triggers, and summary storage as
workspace notes.  All modes support both LLM-based (via a callable or
``LLMClient``) and heuristic (extractive/pattern-based) operation with no
external dependencies beyond stdlib.

Design
------
- **Abstractive summarization** (LLM): batched memories → prompt → narrative summary
- **Extractive compression** (heuristic): text → scored sentences → top-K compression
- **Tier-aware summarization**: L0 (working) → detailed; L1 (medium) → balanced;
  L2 (long-term) → compressed
- **Background trigger**: configurable threshold check against last-summary cursor
- **Summary storage**: persisted as notes via ``create_note`` on any client that
  exposes that method

Usage::

    from spacetime_memory.auto_summarization import (
        summarize_memories,
        extractive_compress,
        tier_summarize,
        check_trigger_summarization,
        store_summary,
    )

    # LLM-based abstractive summarization
    summary = summarize_memories(memories, llm_func=my_llm)

    # Pure heuristic extractive compression
    compressed = extractive_compress(long_text, max_sentences=3)

    # Tier-aware summarization (heuristic fallback)
    summary = tier_summarize(memories, tier="L0")

    # Background trigger check
    if check_trigger_summarization(client, workspace_id, threshold=50):
        store_summary(client, workspace_id, summary)
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

DEFAULT_MAX_SENTENCES = 5
"""Default number of sentences to keep in extractive compress."""

DEFAULT_TRIGGER_THRESHOLD = 50
"""Default number of new memories before triggering background summarization."""

DEFAULT_BATCH_SIZE = 100
"""Default max memories per summarization batch."""

SUMMARIZATION_NOTE_TITLE_PREFIX = "auto-summary-"
"""Prefix for summary note titles."""

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

ABSTRACTIVE_SUMMARY_PROMPT = """You are a memory summarization assistant.  Given the following {count} memory entries, produce a concise, narrative summary that captures the key facts, decisions, preferences, and events described.  The summary should be coherent and self-contained — someone reading only this summary should understand the gist of what happened.

Focus on:
- Important facts and decisions
- User preferences and identity details
- Key events or actions
- Ongoing or recurring patterns

Ignore trivial or redundant details.  Output ONLY the summary as plain text (no markdown, no JSON, no preamble).

Memories:
{memories_text}

Summary:"""

TIER_SUMMARIZATION_PROMPT_L0 = """You are a memory summarization assistant.  Below are recent working memories (L0 — short-term / active context).  Provide a **detailed narrative summary** (3-6 sentences) that captures all significant facts, decisions, and actions.  These are the most recent and actionable memories, so be thorough.

Memories:
{memories_text}

Detailed summary:"""

TIER_SUMMARIZATION_PROMPT_L2 = """You are a memory summarization assistant.  Below are long-term memories (L2 — archival / consolidated).  Produce a **compressed summary** (1-3 sentences) that captures only the most essential, permanent facts.  Omit transient details, timestamps, and minor events.

Memories:
{memories_text}

Compressed summary:"""

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SummaryRecord:
    """Record of a single summarization operation.

    Fields
    ------
    summary_id : str
        Unique identifier (auto-generated via timestamp + hash).
    workspace_id : str
        Workspace this summary belongs to.
    summary_text : str
        The generated summary text.
    source_count : int
        Number of source memories summarised.
    tier : str
        Tier context used (``"L0"``, ``"L1"``, ``"L2"``, or ``"mixed"``).
    method : str
        ``"abstractive"`` (LLM) or ``"extractive"`` (heuristic).
    cursor : int
        Memory cursor / offset used for this batch.
    created_at : float
        Unix timestamp of creation.
    extra : dict
        Arbitrary extra metadata (prompt snippet, token estimates, etc.).
    """
    summary_id: str = ""
    workspace_id: str = "default"
    summary_text: str = ""
    source_count: int = 0
    tier: str = "mixed"
    method: str = "extractive"
    cursor: int = 0
    created_at: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!])\s+(?=[A-Z\"'(])")


def _split_sentences(text: str) -> list[str]:
    """Split *text* into sentences using a simple heuristic regex."""
    sentences = _SENTENCE_SPLIT_RE.split(text.strip())
    return [s.strip() for s in sentences if s.strip()]


def _compute_cursor(
    memories: list[dict[str, Any]],
    key: str = "created_at",
) -> int:
    """Compute the maximum cursor value (e.g. max created_at or seq) from memories."""
    if not memories:
        return 0
    return int(max(m.get(key, 0) or 0 for m in memories))


def _build_memories_text(memories: list[dict[str, Any]], max_chars: int = 8000) -> str:
    """Build a flat text block from a list of memory dicts for inclusion in prompts.

    Each memory is rendered as ``- {content}``.  Truncates to *max_chars*.
    """
    parts: list[str] = []
    total = 0
    for mem in memories:
        content = str(mem.get("content", mem.get("summary", ""))).strip()
        if not content:
            continue
        snippet = f"- {content[:500]}"
        if total + len(snippet) > max_chars:
            remaining = max_chars - total
            if remaining > 20:
                parts.append(snippet[:remaining])
            break
        parts.append(snippet)
        total += len(snippet)
    return "\n".join(parts)


def _words_without_punct(text: str) -> set[str]:
    """Return set of lowercase words with common punctuation stripped."""
    import string
    translator = str.maketrans("", "", string.punctuation)
    return set(text.lower().translate(translator).split())


def _extractive_score_sentences(
    text: str,
    top_n: int = DEFAULT_MAX_SENTENCES,
) -> list[dict[str, Any]]:
    """Score sentences in *text* by heuristic importance and return top-N.

    Scoring signals (all weight-free, purely for ranking):
    - **Length**: penalise very short (< 10 chars) or very long (> 500 chars) sentences.
    - **Keyword presence**: boost sentences containing important markers such as
      ``important``, ``remember``, ``key``, ``prefer``, ``always``, ``never``, etc.
    - **Position bonus**: first and last sentences of a paragraph get a small boost.
    - **Numeric / entity density**: sentences with numbers or named-entity-like
      capitalised words score higher.

    Returns a list of dicts sorted by score descending, each with keys
    ``sentence``, ``score``, ``position``.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return []

    IMPORTANCE_KEYWORDS = {
        "important", "critical", "key", "remember", "vital", "essential",
        "prefer", "preferred", "always", "never", "must", "required",
        "rule", "fact", "decision", "decided", "chosen", "favourite",
        "favorite", "goal", "objective", "identity", "background",
        "significant", "notable", "major", "primary", "main",
    }

    scored: list[dict[str, Any]] = []
    total = len(sentences)

    for pos, sent in enumerate(sentences):
        score = 0.5  # baseline
        n_chars = len(sent)

        # Penalise very short / very long
        if n_chars < 10:
            score -= 0.3
        elif n_chars > 500:
            score -= 0.2

        # Keyword boost
        lower = sent.lower()
        keyword_hits = sum(1 for kw in IMPORTANCE_KEYWORDS if kw in lower)
        score += min(keyword_hits * 0.15, 0.6)

        # Position boost: first and last sentence
        if pos == 0:
            score += 0.1
        if pos == total - 1 and total > 1:
            score += 0.1

        # Numeric / entity density
        numbers = len(re.findall(r"\b\d+\b", sent))
        capitals = len(re.findall(r"\b[A-Z][a-z]{2,}\b", sent))
        density = (numbers + capitals * 0.5) / max(n_chars, 1)
        score += min(density * 20, 0.2)

        # Deduplication penalty: if the sentence is a near-duplicate of one
        # already scored, reduce score (will be enforced during selection).
        score = max(0.0, min(1.0, score))

        scored.append({
            "sentence": sent,
            "score": round(score, 4),
            "position": pos,
        })

    # Remove near-duplicates (sentences with >80% word overlap, ignoring punctuation)
    deduped: list[dict[str, Any]] = []
    for s in sorted(scored, key=lambda x: x["score"], reverse=True):
        words_s = _words_without_punct(s["sentence"])
        is_dup = False
        for kept in deduped:
            words_kept = _words_without_punct(kept["sentence"])
            if not words_s or not words_kept:
                continue
            overlap = len(words_s & words_kept) / max(len(words_s | words_kept), 1)
            if overlap > 0.80:
                is_dup = True
                break
        if not is_dup:
            deduped.append(s)

    # Take top-N by score, then restore original position order
    top = sorted(deduped, key=lambda x: x["score"], reverse=True)[:top_n]
    top.sort(key=lambda x: x["position"])
    return top


def _generate_summary_id(workspace_id: str, cursor: int) -> str:
    """Generate a deterministic-ish summary ID."""
    suffix = f"{int(time.time())}"[-8:]
    return f"sum-{workspace_id}-{cursor}-{suffix}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def summarize_memories(
    memories: list[dict[str, Any]],
    llm_func: Callable[[str], str] | None = None,
    max_sentences: int = DEFAULT_MAX_SENTENCES,
    max_chars: int = 8000,
) -> str:
    """Batch-summarise a list of memory entries into a concise summary.

    Parameters
    ----------
    memories :
        List of memory dicts.  Each dict should have a ``content`` or ``summary`` key.
    llm_func :
        A callable that takes a full prompt string and returns the generated text.
        If ``None``, falls back to extractive compression (heuristic sentence scoring).
    max_sentences :
        Maximum number of sentences for extractive fallback.  Ignored when LLM is used.
    max_chars :
        Maximum characters to include from memories in the prompt.

    Returns
    -------
    str
        The generated summary text.
    """
    if not memories:
        return ""

    text = _build_memories_text(memories, max_chars=max_chars)

    if llm_func is not None:
        prompt = ABSTRACTIVE_SUMMARY_PROMPT.format(
            count=len(memories),
            memories_text=text,
        )
        try:
            result = llm_func(prompt)
            if isinstance(result, str) and result.strip():
                return result.strip()
            logger.warning("LLM summarization returned empty response — falling back to extractive")
        except Exception as e:
            logger.warning("LLM summarization failed: %s — falling back to extractive", e)

    # Heuristic fallback: extractive compression
    top_sentences = _extractive_score_sentences(text, top_n=max_sentences)
    if not top_sentences:
        # Last resort: first N chars
        return text[:500].strip()

    return " ".join(s["sentence"] for s in top_sentences)


def extractive_compress(
    text: str,
    max_sentences: int = DEFAULT_MAX_SENTENCES,
    preserve_order: bool = True,
) -> str:
    """Compress a text block by extracting the most important sentences.

    Pure heuristic — no LLM needed.  Uses keyword scoring, position bias,
    numeric/entity density, and near-duplicate removal.

    Parameters
    ----------
    text :
        The full text to compress.
    max_sentences :
        Maximum number of sentences to keep.
    preserve_order :
        If ``True`` (default), the extracted sentences appear in their original
        order.  If ``False``, they are returned highest-score first.

    Returns
    -------
    str
        The compressed text as a single string.
    """
    top = _extractive_score_sentences(text, top_n=max_sentences)
    if not top:
        # Fallback: first N chars if we can't parse sentences
        return text[:500].strip()

    if preserve_order:
        top.sort(key=lambda x: x["position"])

    return " ".join(s["sentence"] for s in top)


def tier_summarize(
    memories: list[dict[str, Any]],
    tier: str = "L0",
    llm_func: Callable[[str], str] | None = None,
    max_chars: int = 8000,
) -> str:
    """Tier-aware summarization: L0 gets detailed, L2 gets compressed.

    Parameters
    ----------
    memories :
        List of memory dicts to summarise.
    tier :
        One of ``"L0"`` (working / short-term), ``"L1"`` (medium-term), or
        ``"L2"`` (long-term / archival).
    llm_func :
        Optional LLM callable.  If ``None``, uses heuristic compression at all
        tiers with varying sentence limits.
    max_chars :
        Max characters to feed into the prompt / extractor.

    Returns
    -------
    str
        Tier-appropriate summary text.
    """
    if not memories:
        return ""

    text = _build_memories_text(memories, max_chars=max_chars)

    # Sentence limits per tier (for both LLM and heuristic modes)
    tier_sentence_limits = {
        "L0": 8,    # detailed
        "L1": 5,    # balanced
        "L2": 3,    # compressed
    }
    max_sent = tier_sentence_limits.get(tier, 5)

    if llm_func is not None:
        if tier == "L0":
            prompt = TIER_SUMMARIZATION_PROMPT_L0.format(memories_text=text)
        elif tier == "L2":
            prompt = TIER_SUMMARIZATION_PROMPT_L2.format(memories_text=text)
        else:
            # L1 / mixed — use generic abstractive prompt
            prompt = ABSTRACTIVE_SUMMARY_PROMPT.format(
                count=len(memories),
                memories_text=text,
            )
        try:
            result = llm_func(prompt)
            if isinstance(result, str) and result.strip():
                return result.strip()
        except Exception as e:
            logger.warning("LLM tier summarization failed: %s — falling back to heuristic", e)

    # Heuristic fallback — vary sentence count by tier
    return extractive_compress(text, max_sentences=max_sent)


def check_trigger_summarization(
    client: Any,
    workspace_id: str,
    threshold: int = DEFAULT_TRIGGER_THRESHOLD,
    cursor_key: str = "created_at",
    last_cursor: int | None = None,
    summary_note_prefix: str = SUMMARIZATION_NOTE_TITLE_PREFIX,
) -> tuple[bool, int, int]:
    """Check whether enough new memories exist to trigger summarization.

    Queries the last summary cursor from stored summary notes (or accepts an
    explicit *last_cursor*), counts new memories via ``client._query("memory",
    ...)`` with an offset filter, and returns ``(trigger, new_count, cursor)``.

    Parameters
    ----------
    client :
        A client object with a ``_query(table, ...)`` method and optionally
        ``list_notes(...)``.
    workspace_id :
        Target workspace.
    threshold :
        Minimum number of new memories since last summary to trigger.
    cursor_key :
        The field in the memory row used as cursor (default ``"created_at"``).
    last_cursor :
        If provided, use this cursor instead of auto-discovering from stored
        summary notes.
    summary_note_prefix :
        Title prefix used to identify summary notes.

    Returns
    -------
    tuple[bool, int, int]
        ``(trigger, new_count, cursor)`` where *trigger* is ``True`` if
        ``new_count >= threshold``, *new_count* is the number of new memories,
        and *cursor* is the maximum cursor value from those memories (for
        persisting as the next ``last_cursor``).
    """
    # Resolve last cursor from stored summary notes if not explicitly given
    if last_cursor is None:
        last_cursor = _resolve_last_summary_cursor(
            client, workspace_id, prefix=summary_note_prefix,
        )

    # Count new memories since last cursor
    try:
        # We query with a filter: cursor_key > last_cursor
        # The exact approach depends on the STDB query API.
        # Use a simple approach: fetch recent memories and filter client-side.
        filter_dict = {}
        if cursor_key == "created_at" and last_cursor and last_cursor > 0:
            # The memory table has a created_at column; we use a SQL-style
            # WHERE via the client if supported, otherwise fetch and filter.
            pass  # handled below

        all_memories = client._query(
            "memory",
            workspace_id=workspace_id,
            filter_dict=filter_dict,
        )
    except Exception as e:
        logger.warning("Failed to query memories for trigger check: %s", e)
        return False, 0, 0

    if not all_memories:
        return False, 0, 0

    # Filter to only those after last_cursor
    new_memories = []
    for m in all_memories:
        val = m.get(cursor_key, 0) or 0
        if val > last_cursor:
            new_memories.append(m)

    new_count = len(new_memories)
    cursor = _compute_cursor(all_memories, key=cursor_key)
    trigger = new_count >= threshold

    return trigger, new_count, cursor


def _resolve_last_summary_cursor(
    client: Any,
    workspace_id: str,
    prefix: str = SUMMARIZATION_NOTE_TITLE_PREFIX,
) -> int:
    """Read the cursor from the most recent summary note in the workspace.

    Looks for notes whose title starts with *prefix*, parses the cursor from
    the note content (stored as JSON metadata in a code block or first line),
    and returns the highest cursor found.
    """
    try:
        notes = client.list_notes(workspace_id=workspace_id)
    except Exception as e:
        logger.debug("Could not list notes for cursor resolution: %s", e)
        return 0

    max_cursor = 0
    for note in notes:
        title = note.get("title", "")
        if not title.startswith(prefix):
            continue
        content = note.get("content", "")
        cursor = _parse_cursor_from_summary_note(content)
        max_cursor = max(max_cursor, cursor)

    return max_cursor


def _parse_cursor_from_summary_note(content: str) -> int:
    """Extract cursor value from a summary note's content.

    Expected format: first line is ``cursor: <int>``, or contains a JSON
    metadata block with ``"cursor"`` key.
    """
    # Try JSON metadata block (```json ... ```)
    json_match = re.search(r"```json\s*\n(.*?)\n```", content, re.DOTALL)
    if json_match:
        try:
            meta = json.loads(json_match.group(1))
            return int(meta.get("cursor", 0))
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Try plain first line: "cursor: 123"
    first_line = content.strip().split("\n")[0] if content else ""
    match = re.match(r"cursor:\s*(\d+)", first_line)
    if match:
        return int(match.group(1))

    return 0


def store_summary(
    client: Any,
    workspace_id: str,
    summary_text: str,
    source_count: int = 0,
    tier: str = "mixed",
    method: str = "extractive",
    cursor: int = 0,
    extra: dict[str, Any] | None = None,
    embed: bool = False,
) -> str | None:
    """Store a derived summary as a note in the workspace.

    Calls ``client.create_note()`` with a structured title and content
    containing the summary text plus JSON metadata.

    Parameters
    ----------
    client :
        Client with ``create_note()`` method.
    workspace_id :
        Target workspace.
    summary_text :
        The summary text to store.
    source_count :
        Number of source memories.
    tier :
        Tier label (``"L0"``, ``"L1"``, ``"L2"``, or ``"mixed"``).
    method :
        ``"abstractive"`` or ``"extractive"``.
    cursor :
        Max cursor value from source memories (for trigger tracking).
    extra :
        Optional extra metadata.
    embed :
        Whether to compute and store an embedding for searchability.

    Returns
    -------
    str or None
        The note ID of the stored summary, or ``None`` on failure.
    """
    summary_id = _generate_summary_id(workspace_id, cursor)
    title = f"{SUMMARIZATION_NOTE_TITLE_PREFIX}{summary_id}"
    now = time.time()

    meta = {
        "type": "auto_summary",
        "summary_id": summary_id,
        "cursor": cursor,
        "tier": tier,
        "method": method,
        "source_count": source_count,
        "created_at": now,
    }
    if extra:
        meta.update(extra)

    content = (
        f"cursor: {cursor}\n\n"
        f"```json\n{json.dumps(meta, indent=2)}\n```\n\n"
        f"{summary_text}"
    )

    try:
        result = client.create_note(
            workspace_id=workspace_id,
            title=title,
            content=content,
            embed=embed,
        )
        if result.get("status") == "ok":
            # Resolve note ID from the result
            note_id = result.get("note_id", "")
            if not note_id:
                # Fallback: look up by title
                try:
                    notes = client.get_note_by_title(title, workspace_id=workspace_id)
                    if notes:
                        note_id = notes[0].get("id", "")
                except Exception:
                    pass
            logger.info(
                "Stored summary '%s' (%s, %d sources, tier=%s, cursor=%d)",
                summary_id, method, source_count, tier, cursor,
            )
            return note_id or summary_id
        else:
            logger.warning("store_summary: create_note returned status=%s", result.get("status"))
            return None
    except Exception as e:
        logger.warning("Failed to store summary note: %s", e)
        return None


def batch_summarize_and_store(
    client: Any,
    workspace_id: str,
    llm_func: Callable[[str], str] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    threshold: int = DEFAULT_TRIGGER_THRESHOLD,
    tier: str = "L1",
    cursor_key: str = "created_at",
    embed: bool = False,
) -> SummaryRecord | None:
    """High-level pipeline: check trigger, fetch new memories, summarise, store.

    This is the main entry point for a background summarization daemon or cron
    job.  It performs the full auto-summarization cycle:

    1. Check trigger via ``check_trigger_summarization()``
    2. If triggered, fetch new memories since last cursor
    3. Summarise them using the appropriate tier/tool
    4. Store the result as a note
    5. Return a ``SummaryRecord`` describing what was done

    Parameters
    ----------
    client :
        Client with ``_query()``, ``list_notes()``, ``create_note()`` methods.
    workspace_id :
        Target workspace.
    llm_func :
        Optional LLM callable for abstractive summarization.
    batch_size :
        Max memories to summarise in one batch.
    threshold :
        New-memory count to trigger summarization.
    tier :
        Tier for summarization (``"L0"``, ``"L1"``, ``"L2"``).
    cursor_key :
        Memory field used as cursor.
    embed :
        Whether to embed the stored summary note.

    Returns
    -------
    SummaryRecord or None
        Record of the summarization operation, or ``None`` if not triggered.
    """
    # Step 1: check trigger
    triggered, new_count, cursor = check_trigger_summarization(
        client=client,
        workspace_id=workspace_id,
        threshold=threshold,
        cursor_key=cursor_key,
    )

    if not triggered or new_count == 0:
        logger.debug(
            "batch_summarize_and_store: not triggered (%d < %d)",
            new_count, threshold,
        )
        return None

    # Step 2: fetch new memories
    try:
        all_memories = client._query(
            "memory",
            workspace_id=workspace_id,
            filter_dict={},
        )
    except Exception as e:
        logger.warning("Failed to fetch memories: %s", e)
        return None

    if not all_memories:
        return None

    # Filter to only new memories
    last_cursor = cursor - new_count  # approximate: cursor - count gives offset
    # Actually, compute the real last cursor from stored summaries
    resolved_cursor = _resolve_last_summary_cursor(client, workspace_id)
    if resolved_cursor > 0:
        last_cursor = resolved_cursor

    new_memories = []
    for m in all_memories:
        val = m.get(cursor_key, 0) or 0
        if val > last_cursor:
            new_memories.append(m)

    if not new_memories:
        logger.debug("No new memories found after cursor %d", last_cursor)
        return None

    # Limit batch size
    batch = new_memories[:batch_size]
    effective_cursor = _compute_cursor(batch, key=cursor_key)

    # Step 3: summarise
    method = "abstractive" if llm_func is not None else "extractive"
    summary_text = tier_summarize(
        memories=batch,
        tier=tier,
        llm_func=llm_func,
    )

    if not summary_text:
        logger.warning("Summarization produced empty text")
        return None

    # Step 4: store
    note_id = store_summary(
        client=client,
        workspace_id=workspace_id,
        summary_text=summary_text,
        source_count=len(batch),
        tier=tier,
        method=method,
        cursor=effective_cursor,
        embed=embed,
    )

    if note_id is None:
        logger.warning("Failed to store summary, but summarization succeeded")

    return SummaryRecord(
        summary_id=_generate_summary_id(workspace_id, effective_cursor),
        workspace_id=workspace_id,
        summary_text=summary_text,
        source_count=len(batch),
        tier=tier,
        method=method,
        cursor=effective_cursor,
        created_at=time.time(),
        extra={"note_id": note_id} if note_id else {},
    )
