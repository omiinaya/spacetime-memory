"""Agent self-editing for spacetime-memory — Letta/MemGPT parity.

Provides four core self-editing capabilities that allow an agent to
autonomously maintain, correct, and deduplicate its memory:

1. **Memory merging** — detect similar/duplicate memories and merge them
   (combine content, preserve metadata).
2. **Contradiction detection** — compare pairs of memories for semantic
   contradictions using LLM or heuristic signals.
3. **Memory rewriting** — rewrite a memory to improve clarity/correctness
   given new evidence.
4. **Entity resolution** — detect when two KG nodes refer to the same
   real-world entity and merge them.

Each capability supports both LLM-based and heuristic (pure-Python) modes.
When an LLM client is provided, the more accurate LLM path is used; when
it is ``None`` or unavailable, the heuristic fallback is used automatically.

Usage::

    from spacetime_memory.self_editing import (
        merge_similar_memories,
        detect_contradictions,
        rewrite_memory,
        resolve_entities,
    )
    from spacetime_memory.llm import LLMClient

    llm = LLMClient()
    result = merge_similar_memories(client, "ws-123", llm_client=llm)
    for merged in result["merges"]:
        print(f"Merged {merged['kept_id']} <- {merged['removed_ids']}")
"""

from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Similarity threshold for heuristic memory merging (0.0 - 1.0)
DEFAULT_MERGE_SIMILARITY_THRESHOLD = 0.75

# Contradiction signal thresholds
DEFAULT_CONTRADICTION_SCORE_THRESHOLD = 0.6

# Entity resolution similarity threshold
DEFAULT_RESOLUTION_SIMILARITY_THRESHOLD = 0.70

# ---------------------------------------------------------------------------
# Prompt templates (LLM mode)
# ---------------------------------------------------------------------------

MERGE_ANALYSIS_PROMPT = """You are an intelligent memory curator. Given two memories from an agent's memory store, decide whether they should be merged into a single, consolidated memory.

Memory A (id={mem_a_id}):
{mem_a_content}

Memory B (id={mem_b_id}):
{mem_b_content}

Respond with a JSON object (no markdown, no explanation):
{{
    "should_merge": true/false,
    "confidence": <0.0-1.0>,
    "merged_content": "<consolidated text combining both memories, or '' if should_merge is false>",
    "reasoning": "<brief justification>"
}}"""

CONTRADICTION_PROMPT = """You are a rigorous fact-checker for an agent's memory store. Determine whether the following two memories contain contradictory or conflicting information.

Memory A:
{mem_a_content}

Memory B:
{mem_b_content}

Respond with a JSON object (no markdown, no explanation):
{{
    "contradicts": true/false,
    "contradiction_score": <0.0-1.0>,
    "explanation": "<if contradictory, describe the conflict; otherwise empty string>",
    "verdict": "<'contradiction' | 'consistent' | 'unrelated'>"
}}"""

REWRITE_PROMPT = """You are an agent memory editor. Rewrite the following memory to incorporate new evidence, improving clarity and correctness.

Current memory:
{current_content}

New evidence:
{new_evidence}

Instructions:
- Preserve all accurate information from the current memory.
- Incorporate relevant new evidence.
- Remove or correct any information superseded by the new evidence.
- Keep the same tone and format.
- Be concise but complete.

Respond with a JSON object (no markdown, no explanation):
{{
    "rewritten_content": "<rewritten memory>",
    "changes": "<summary of what changed>",
    "confidence": <0.0-1.0>
}}"""

ENTITY_RESOLUTION_PROMPT = """You are a knowledge graph curator. Determine whether the following two entities refer to the same real-world entity and should be merged.

Entity A (id={entity_a_id}):
  Label: {entity_a_label}
  Type: {entity_a_type}
  Summary: {entity_a_summary}

Entity B (id={entity_b_id}):
  Label: {entity_b_label}
  Type: {entity_b_type}
  Summary: {entity_b_summary}

Respond with a JSON object (no markdown, no explanation):
{{
    "same_entity": true/false,
    "confidence": <0.0-1.0>,
    "canonical_label": "<the best label for the merged entity>",
    "merged_summary": "<combined summary>",
    "entity_type": "<best type for merged entity>",
    "reasoning": "<brief justification>"
}}"""

# ---------------------------------------------------------------------------
# Text similarity helpers (heuristic)
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Lowercase, strip, collapse whitespace."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _word_overlap_ratio(text_a: str, text_b: str) -> float:
    """Jaccard-like word overlap ratio between two texts."""
    words_a = set(_normalize(text_a).split())
    words_b = set(_normalize(text_b).split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def _char_similarity(text_a: str, text_b: str) -> float:
    """Character-level sequence similarity using SequenceMatcher."""
    if not text_a and not text_b:
        return 1.0
    if not text_a or not text_b:
        return 0.0
    return SequenceMatcher(None, _normalize(text_a), _normalize(text_b)).ratio()


def _combined_similarity(text_a: str, text_b: str) -> float:
    """Blend of word-overlap and character-sequence similarity (0.0 - 1.0)."""
    word_score = _word_overlap_ratio(text_a, text_b)
    char_score = _char_similarity(text_a, text_b)
    return 0.4 * word_score + 0.6 * char_score


# ---------------------------------------------------------------------------
# LLM call helpers
# ---------------------------------------------------------------------------


def _call_llm_parse_json(
    llm_client: Any,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
    max_tokens: int = 1024,
) -> dict[str, Any] | None:
    """Call an LLM and parse its response as JSON.

    Supports both ``spacetime_memory.llm.LLMClient`` (with a ``chat`` method)
    and raw callable functions/lambdas for testing.
    """
    if llm_client is None:
        return None

    try:
        if hasattr(llm_client, "chat"):
            # spacetime_memory.llm.LLMClient
            response = llm_client.chat(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        elif callable(llm_client):
            # Raw callable (e.g. lambda for testing)
            response = llm_client(messages)
        else:
            logger.warning("llm_client has no 'chat' method and is not callable")
            return None

        if not response:
            return None

        # If it's already a dict (from a test mock that returns parsed JSON)
        if isinstance(response, dict):
            return response

        # Clean markdown fences if present
        text = str(response).strip()
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()

        result = json.loads(text)
        return result if isinstance(result, dict) else None

    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning("LLM JSON parse failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# 1. Memory Merging
# ---------------------------------------------------------------------------


def _compute_merge_candidates(
    memories: list[dict[str, Any]],
    threshold: float = DEFAULT_MERGE_SIMILARITY_THRESHOLD,
) -> list[tuple[int, int, float]]:
    """Find pairs of memories whose content similarity exceeds *threshold*.

    Returns list of ``(i, j, similarity)`` tuples sorted by similarity
    descending.
    """
    candidates: list[tuple[int, int, float]] = []
    for i in range(len(memories)):
        content_i = (memories[i].get("content") or memories[i].get("summary") or "").strip()
        if not content_i:
            continue
        for j in range(i + 1, len(memories)):
            content_j = (memories[j].get("content") or memories[j].get("summary") or "").strip()
            if not content_j:
                continue
            sim = _combined_similarity(content_i, content_j)
            if sim >= threshold:
                candidates.append((i, j, sim))
    candidates.sort(key=lambda t: t[2], reverse=True)
    return candidates


def _merge_two_memories(
    mem_a: dict[str, Any],
    mem_b: dict[str, Any],
    merged_content: str,
) -> dict[str, Any]:
    """Combine two memory dicts into one, preserving all metadata."""
    # Prefer the first memory's id as the survivor
    merged: dict[str, Any] = dict(mem_a)
    merged["content"] = merged_content or mem_a.get("content", "")
    # Combine metadata
    for key in ("tags", "labels", "categories"):
        if isinstance(mem_a.get(key, []), list) or isinstance(mem_b.get(key, []), list):
            combined = list(mem_a.get(key, []) or [])
            for item in mem_b.get(key, []) or []:
                if item not in combined:
                    combined.append(item)
            merged[key] = combined
    # Numeric metadata — take the max
    for key in ("importance", "strength", "confidence", "access_count"):
        val_a = mem_a.get(key) or 0
        val_b = mem_b.get(key) or 0
        if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
            merged[key] = max(val_a, val_b)
    # Timestamps — take the oldest created_at and newest updated_at
    for ts_key in ("created_at", "created"):
        if mem_a.get(ts_key) and mem_b.get(ts_key):
            merged[ts_key] = min(
                str(mem_a.get(ts_key, "")),
                str(mem_b.get(ts_key, "")),
            )
    for ts_key in ("updated_at", "updated", "last_accessed"):
        if mem_a.get(ts_key) and mem_b.get(ts_key):
            merged[ts_key] = max(
                str(mem_a.get(ts_key, "")),
                str(mem_b.get(ts_key, "")),
            )
    merged["source_ids"] = list(
        set(
            (mem_a.get("source_ids") or [mem_a.get("id", "")])
            + (mem_b.get("source_ids") or [mem_b.get("id", "")])
        )
    )
    return merged


def merge_similar_memories(
    client: Any,
    workspace_id: str,
    *,
    threshold: float = DEFAULT_MERGE_SIMILARITY_THRESHOLD,
    llm_client: Any = None,
    dry_run: bool = False,
    memory_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Find and merge similar/duplicate memories.

    In heuristic mode (default), uses word-overlap and character-sequence
    similarity to find candidates, then merges the most similar pairs first.
    In LLM mode, uses the LLM to judge whether each candidate pair should
    be merged, and to generate consolidated content.

    Args:
        client: Spacetime Memory Client instance.
        workspace_id: Target workspace.
        threshold: Similarity threshold (0.0-1.0) for heuristic mode.
            Default 0.75.
        llm_client: Optional ``LLMClient`` or callable. When provided,
            LLM-based merging is used for higher accuracy.
        dry_run: If True, only report what would be merged without
            performing any mutations.
        memory_ids: Optional subset of memory IDs to consider (scoped merge).

    Returns:
        Dict with keys:
            merges: List of merge result dicts.
            total_before: Original memory count.
            total_after: Memory count after merges.
            candidates_considered: Number of candidate pairs evaluated.
            mode: ``"llm"``, ``"heuristic"``, or ``"none"``.
    """
    # Fetch memories
    try:
        memories = client._query(
            "memory",
            workspace_id=workspace_id,
            columns=["id", "content", "summary", "tags", "created_at",
                     "updated_at", "importance", "strength", "confidence",
                     "access_count"],
        )
    except Exception as e:
        logger.warning("merge_similar_memories: failed to query memories: %s", e)
        return {
            "merges": [],
            "total_before": 0,
            "total_after": 0,
            "candidates_considered": 0,
            "mode": "none",
            "error": str(e),
        }

    if not memories:
        return {
            "merges": [],
            "total_before": 0,
            "total_after": 0,
            "candidates_considered": 0,
            "mode": "none",
        }

    # Filter to specified IDs if given
    if memory_ids:
        id_set = set(memory_ids)
        memories = [m for m in memories if m.get("id", "") in id_set]

    total_before = len(memories)

    # Find candidate pairs
    candidates = _compute_merge_candidates(memories, threshold=threshold)
    if not candidates:
        return {
            "merges": [],
            "total_before": total_before,
            "total_after": total_before,
            "candidates_considered": 0,
            "mode": "none",
        }

    # Track which indices have been consumed
    consumed: set[int] = set()
    merges: list[dict[str, Any]] = []

    use_llm = bool(llm_client)

    for i, j, sim in candidates:
        if i in consumed or j in consumed:
            continue

        mem_a = memories[i]
        mem_b = memories[j]
        mem_a_id = mem_a.get("id", "")
        mem_b_id = mem_b.get("id", "")

        should_merge = True
        merged_content = ""
        confidence = sim
        reasoning = ""

        if use_llm:
            # LLM-based merge decision
            content_a = mem_a.get("content") or mem_a.get("summary", "")
            content_b = mem_b.get("content") or mem_b.get("summary", "")
            prompt_text = MERGE_ANALYSIS_PROMPT.format(
                mem_a_id=mem_a_id,
                mem_a_content=content_a,
                mem_b_id=mem_b_id,
                mem_b_content=content_b,
            )
            llm_result = _call_llm_parse_json(
                llm_client,
                [{"role": "user", "content": prompt_text}],
            )
            if llm_result is not None:
                should_merge = llm_result.get("should_merge", False)
                merged_content = llm_result.get("merged_content", "")
                confidence = float(llm_result.get("confidence", 0.5))
                reasoning = llm_result.get("reasoning", "")
                if not isinstance(should_merge, bool):
                    should_merge = bool(should_merge)
            else:
                # LLM failed — fall back to heuristic decision
                should_merge = sim >= threshold
                merged_content = ""
                reasoning = "LLM unavailable, used heuristic fallback"

        if not should_merge:
            continue

        # Build merged record
        merged = _merge_two_memories(mem_a, mem_b, merged_content)
        merged_id = merged.get("id", mem_a_id)

        merge_record = {
            "kept_id": merged_id,
            "removed_ids": [mem_a_id, mem_b_id] if mem_a_id != merged_id else [mem_b_id],
            "content_before_a": mem_a.get("content", ""),
            "content_before_b": mem_b.get("content", ""),
            "content_after": merged.get("content", ""),
            "similarity": sim,
            "confidence": confidence,
            "reasoning": reasoning,
        }

        if not dry_run:
            try:
                # Update the surviving memory
                client._call(
                    "update_memory",
                    [workspace_id, merged_id, merged.get("content", "")],
                )
                # Delete the consumed memory
                if mem_b_id != merged_id:
                    client._call("delete_memory", [workspace_id, mem_b_id])
                if mem_a_id != merged_id and mem_a_id != mem_b_id:
                    client._call("delete_memory", [workspace_id, mem_a_id])
            except Exception as e:
                logger.warning("merge_similar_memories: persistence failed: %s", e)
                merge_record["persist_error"] = str(e)

        merges.append(merge_record)
        consumed.add(i)
        consumed.add(j)

    total_after = total_before - len(consumed)

    return {
        "merges": merges,
        "total_before": total_before,
        "total_after": total_after,
        "candidates_considered": len(candidates),
        "mode": "llm" if use_llm else "heuristic",
    }


# ---------------------------------------------------------------------------
# 2. Contradiction Detection
# ---------------------------------------------------------------------------


def _heuristic_contradiction_score(mem_a: dict[str, Any], mem_b: dict[str, Any]) -> float:
    """Estimate contradiction likelihood using heuristics.

    Looks for signal words (negation, temporal qualifiers, contradictory
    conjunctions) and numerical discrepancies.  Returns 0.0-1.0.
    """
    content_a = _normalize(mem_a.get("content", "") or mem_a.get("summary", ""))
    content_b = _normalize(mem_b.get("content", "") or mem_b.get("summary", ""))

    if not content_a or not content_b:
        return 0.0

    score = 0.0

    # Signal words that suggest contradiction
    contradiction_signals = {
        "but", "however", "although", "nevertheless", "nonetheless",
        "contrary", "instead", "rather", "unlike", "actually",
        "despite", "while", "whereas", "not", "never", "no",
        "cannot", "can't", "doesn't", "don't", "won't", "wouldn't",
        "shouldn't", "isn't", "aren't", "wasn't", "weren't",
        "contradicts", "conflicts", "disagrees", "dispute",
    }

    words_a = set(content_a.split())
    words_b = set(content_b.split())

    # High word overlap + contradiction signals suggests contradiction
    overlap = words_a & words_b
    if len(overlap) >= 3:
        signals_in_a = words_a & contradiction_signals
        signals_in_b = words_b & contradiction_signals
        signal_count = len(signals_in_a) + len(signals_in_b)
        if signal_count > 0:
            score += min(0.3, signal_count * 0.05)

    # Numerical discrepancies
    numbers_a = set(re.findall(r"\d+(?:\.\d+)?", content_a))
    numbers_b = set(re.findall(r"\d+(?:\.\d+)?", content_b))
    shared_numbers = numbers_a & numbers_b
    if shared_numbers:
        # Same numbers appearing in both could indicate same fact being
        # asserted differently — mild signal
        score += 0.1

    # Temporal qualifiers suggesting change over time
    temporal_a = {"formerly", "previously", "used to", "old", "past", "before"}
    temporal_b = {"currently", "now", "today", "recently", "new", "after", "later"}
    if (words_a & temporal_a and words_b & temporal_b) or (words_b & temporal_a and words_a & temporal_b):
        score += 0.15

    # Direct negation patterns: "X is Y" vs "X is not Y"
    for num, word in enumerate(words_a):
        for other_word in words_b:
            if word == other_word and num > 0:
                prev = list(words_a)[num - 1] if num > 0 else ""
                # Check if one side has negation and the other doesn't
                prev_b = list(words_b)[list(words_b).index(other_word) - 1] if list(words_b).index(other_word) > 0 else ""
                if ("not" in (prev, prev_b) or "no" in (prev, prev_b)) and prev != prev_b:
                    score += 0.2
                    break

    # Time-based: if both express an opinion/preference about the same topic
    # and use different sentiment
    sentiment_positive = {"like", "likes", "love", "loves", "loved",
                          "enjoy", "enjoys", "enjoyed",
                          "good", "great", "excellent",
                          "prefer", "prefers", "preferred",
                          "favorite", "awesome", "amazing"}
    sentiment_negative = {"dislike", "dislikes", "disliked",
                          "hate", "hates", "hated",
                          "bad", "terrible", "awful",
                          "worst", "poor", "mediocre", "boring"}
    pos_a = bool(words_a & sentiment_positive)
    pos_b = bool(words_b & sentiment_positive)
    neg_a = bool(words_a & sentiment_negative)
    neg_b = bool(words_b & sentiment_negative)
    if (pos_a and neg_b) or (neg_a and pos_b):
        score += 0.35

    # Cap at 0.95
    return min(0.95, score)


def detect_contradictions(
    client: Any,
    workspace_id: str,
    *,
    threshold: float = DEFAULT_CONTRADICTION_SCORE_THRESHOLD,
    similarity_threshold: float = 0.3,
    llm_client: Any = None,
    memory_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Detect contradictory memories in a workspace.

    Compares all pairs of memories (or a subset if ``memory_ids`` is given)
    and flags those that appear to contradict each other.

    In heuristic mode, uses word-level signal detection (negation words,
    sentiment polarity, temporal qualifiers).  In LLM mode, uses the LLM
    for semantic contradiction analysis.

    Args:
        client: Spacetime Memory Client instance.
        workspace_id: Target workspace.
        threshold: Minimum contradiction score (0.0-1.0) to flag a pair.
            Default 0.6.
        similarity_threshold: Minimum text similarity to even consider a
            pair for contradiction (avoids comparing unrelated memories).
            Default 0.3.
        llm_client: Optional ``LLMClient`` or callable for LLM mode.
        memory_ids: Optional subset of memory IDs to check.

    Returns:
        Dict with keys:
            contradictions: List of contradiction dicts.
            pairs_analyzed: Number of memory pairs compared.
            contradictions_found: Count.
            mode: ``"llm"``, ``"heuristic"``, or ``"none"``.
    """
    try:
        memories = client._query(
            "memory",
            workspace_id=workspace_id,
            columns=["id", "content", "summary", "created_at", "memory_type"],
        )
    except Exception as e:
        logger.warning("detect_contradictions: failed to query memories: %s", e)
        return {
            "contradictions": [],
            "pairs_analyzed": 0,
            "contradictions_found": 0,
            "mode": "none",
            "error": str(e),
        }

    if not memories:
        return {
            "contradictions": [],
            "pairs_analyzed": 0,
            "contradictions_found": 0,
            "mode": "none",
        }

    if memory_ids:
        id_set = set(memory_ids)
        memories = [m for m in memories if m.get("id", "") in id_set]

    use_llm = bool(llm_client)
    contradictions: list[dict[str, Any]] = []
    pairs_analyzed = 0

    for i in range(len(memories)):
        mem_a = memories[i]
        content_a = mem_a.get("content", "") or mem_a.get("summary", "")
        if not content_a:
            continue
        for j in range(i + 1, len(memories)):
            mem_b = memories[j]
            content_b = mem_b.get("content", "") or mem_b.get("summary", "")
            if not content_b:
                continue

            # Quick relevance filter — skip unrelated pairs
            sim = _combined_similarity(content_a, content_b)
            if sim < similarity_threshold:
                continue

            pairs_analyzed += 1
            mem_a_id = mem_a.get("id", "")
            mem_b_id = mem_b.get("id", "")

            if use_llm:
                prompt_text = CONTRADICTION_PROMPT.format(
                    mem_a_content=content_a,
                    mem_b_content=content_b,
                )
                llm_result = _call_llm_parse_json(
                    llm_client,
                    [{"role": "user", "content": prompt_text}],
                    temperature=0.1,
                )
                if llm_result is not None:
                    contradicts = llm_result.get("contradicts", False)
                    score = float(llm_result.get("contradiction_score", 0.0))
                    explanation = llm_result.get("explanation", "")
                    verdict = llm_result.get("verdict", "")
                    if not isinstance(contradicts, bool):
                        contradicts = bool(contradicts)
                    if contradicts and score >= threshold:
                        contradictions.append({
                            "memory_a_id": mem_a_id,
                            "memory_b_id": mem_b_id,
                            "content_a": content_a,
                            "content_b": content_b,
                            "contradiction_score": score,
                            "explanation": explanation,
                            "verdict": verdict or "contradiction",
                            "method": "llm",
                        })
                    continue

            # Heuristic fallback
            score = _heuristic_contradiction_score(mem_a, mem_b)
            if score >= threshold:
                contradictions.append({
                    "memory_a_id": mem_a_id,
                    "memory_b_id": mem_b_id,
                    "content_a": content_a,
                    "content_b": content_b,
                    "contradiction_score": score,
                    "explanation": _heuristic_contradiction_explanation(mem_a, mem_b),
                    "verdict": "contradiction" if score >= 0.7 else "possible_contradiction",
                    "method": "heuristic",
                })

    return {
        "contradictions": contradictions,
        "pairs_analyzed": pairs_analyzed,
        "contradictions_found": len(contradictions),
        "mode": "llm" if use_llm else "heuristic",
    }


def _heuristic_contradiction_explanation(mem_a: dict[str, Any], mem_b: dict[str, Any]) -> str:
    """Generate a human-readable explanation for a heuristic contradiction."""
    reasons: list[str] = []
    content_a = _normalize(mem_a.get("content", "") or "")
    content_b = _normalize(mem_b.get("content", "") or "")

    words_a = set(content_a.split())
    words_b = set(content_b.split())

    # Check for sentiment clash
    sentiment_positive = {"like", "likes", "love", "loves", "loved",
                          "enjoy", "enjoys", "enjoyed",
                          "good", "great", "prefer", "prefers", "favorite"}
    sentiment_negative = {"dislike", "dislikes", "disliked",
                          "hate", "hates", "hated",
                          "bad", "terrible", "awful", "worst"}
    pos_a = bool(words_a & sentiment_positive)
    neg_b = bool(words_b & sentiment_negative)
    if pos_a and neg_b:
        reasons.append("Memory A expresses positive sentiment while Memory B expresses negative sentiment")
    neg_a = bool(words_a & sentiment_negative)
    pos_b = bool(words_b & sentiment_positive)
    if neg_a and pos_b:
        reasons.append("Memory B expresses positive sentiment while Memory A expresses negative sentiment")

    # Temporal clash
    temporal_a_past = {"formerly", "previously", "used to", "old"}
    temporal_b_present = {"currently", "now", "today", "recently", "new"}
    if words_a & temporal_a_past and words_b & temporal_b_present:
        reasons.append("Memory A describes a past state while Memory B describes a current/contrary state")
    if words_b & temporal_a_past and words_a & temporal_b_present:
        reasons.append("Memory B describes a past state while Memory A describes a current/contrary state")

    # Negation
    overlap = words_a & words_b
    if overlap:
        negation_words = {"not", "no", "never", "without"}
        a_has_neg = bool(words_a & negation_words)
        b_has_neg = bool(words_b & negation_words)
        if a_has_neg != b_has_neg:
            shared = list(overlap)[:3]
            reasons.append(f"Shared topic ({', '.join(shared)}) asserted in one with negation but not the other")

    if not reasons:
        reasons.append("Heuristic signals suggest conflicting information")

    return "; ".join(reasons)


# ---------------------------------------------------------------------------
# 3. Memory Rewriting
# ---------------------------------------------------------------------------


def _basic_rewrite(current_content: str, new_evidence: str) -> str:
    """Heuristic text merge: concatenate with dedup.

    A simple fallback that combines the two texts, removing any sentences
    from the current content that are contradicted or duplicated by the
    new evidence.
    """
    if not current_content:
        return new_evidence
    if not new_evidence:
        return current_content

    # Split into sentences (simple heuristic)
    sentence_end = re.compile(r"(?<=[.!?])\s+")
    current_sentences = sentence_end.split(current_content)
    evidence_sentences = sentence_end.split(new_evidence)

    # Filter out sentences from current that are near-duplicates of evidence
    kept: list[str] = []
    for sent in current_sentences:
        sent_stripped = sent.strip()
        if not sent_stripped:
            continue
        is_duplicate = False
        for ev_sent in evidence_sentences:
            ev_stripped = ev_sent.strip()
            if not ev_stripped:
                continue
            if _combined_similarity(sent_stripped, ev_stripped) > 0.85:
                is_duplicate = True
                break
        if not is_duplicate:
            kept.append(sent_stripped)

    # Join kept sentences with evidence
    if kept:
        result = " ".join(kept) + " " + new_evidence
    else:
        result = new_evidence

    return result.strip()


def rewrite_memory(
    client: Any,
    workspace_id: str,
    memory_id: str,
    new_evidence: str,
    *,
    llm_client: Any = None,
    dry_run: bool = False,
    content_override: str | None = None,
) -> dict[str, Any]:
    """Rewrite a single memory given new evidence.

    In LLM mode, uses the LLM to intelligently merge old and new information,
    preserving what's still accurate and updating what's outdated.
    In heuristic mode, performs a simple sentence-level merge with dedup.

    Args:
        client: Spacetime Memory Client instance.
        workspace_id: Target workspace.
        memory_id: ID of the memory to rewrite.
        new_evidence: Text containing new information to incorporate.
        llm_client: Optional ``LLMClient`` or callable for LLM mode.
        dry_run: If True, return the rewritten content without persisting.
        content_override: If provided, use this as the current memory
            content instead of fetching from the database (for testing).

    Returns:
        Dict with keys:
            memory_id: The memory that was rewritten.
            old_content: Content before rewriting.
            new_content: Content after rewriting.
            changes: Description of changes made.
            confidence: Confidence in the rewrite (0.0-1.0).
            mode: ``"llm"``, ``"heuristic"``, or ``"none"``.
    """
    if content_override is not None:
        current_content = content_override
    else:
        try:
            results = client._query(
                "memory",
                workspace_id=workspace_id,
                filter_dict={"id": memory_id},
                columns=["id", "content", "summary"],
            )
            if not results:
                return {
                    "memory_id": memory_id,
                    "old_content": "",
                    "new_content": "",
                    "changes": "",
                    "confidence": 0.0,
                    "mode": "none",
                    "error": "Memory not found",
                }
            current_content = results[0].get("content", "") or results[0].get("summary", "")
        except Exception as e:
            logger.warning("rewrite_memory: failed to fetch memory: %s", e)
            return {
                "memory_id": memory_id,
                "old_content": "",
                "new_content": "",
                "changes": "",
                "confidence": 0.0,
                "mode": "none",
                "error": str(e),
            }

    old_content = current_content
    new_content = ""
    changes = ""
    confidence = 0.5

    if llm_client:
        prompt_text = REWRITE_PROMPT.format(
            current_content=current_content,
            new_evidence=new_evidence,
        )
        llm_result = _call_llm_parse_json(
            llm_client,
            [{"role": "user", "content": prompt_text}],
            temperature=0.2,
        )
        if llm_result is not None:
            new_content = llm_result.get("rewritten_content", "")
            changes = llm_result.get("changes", "")
            confidence = float(llm_result.get("confidence", 0.5))
        else:
            # LLM fallback
            new_content = _basic_rewrite(current_content, new_evidence)
            changes = "Heuristic merge (LLM unavailable)"
            confidence = 0.5
    else:
        new_content = _basic_rewrite(current_content, new_evidence)
        changes = "Heuristic sentence-level merge"
        confidence = 0.5

    if not new_content:
        new_content = new_evidence
        changes = "Replaced with new evidence (empty after rewrite)"
        confidence = 0.3

    if not dry_run and new_content:
        try:
            client._call(
                "update_memory",
                [workspace_id, memory_id, new_content],
            )
        except Exception as e:
            logger.warning("rewrite_memory: persistence failed: %s", e)
            return {
                "memory_id": memory_id,
                "old_content": old_content,
                "new_content": new_content,
                "changes": changes,
                "confidence": confidence,
                "mode": "llm" if llm_client else "heuristic",
                "error": str(e),
            }

    return {
        "memory_id": memory_id,
        "old_content": old_content,
        "new_content": new_content,
        "changes": changes,
        "confidence": confidence,
        "mode": "llm" if llm_client else "heuristic",
    }


# ---------------------------------------------------------------------------
# 4. Entity Resolution
# ---------------------------------------------------------------------------


def _entity_label_similarity(
    label_a: str,
    summary_a: str,
    label_b: str,
    summary_b: str,
) -> float:
    """Compute heuristic similarity between two KG entities."""
    label_sim = _combined_similarity(label_a, label_b)
    summary_sim = _combined_similarity(summary_a, summary_b)
    # Label similarity is more important
    return 0.6 * label_sim + 0.4 * summary_sim


def resolve_entities(
    client: Any,
    workspace_id: str,
    *,
    threshold: float = DEFAULT_RESOLUTION_SIMILARITY_THRESHOLD,
    llm_client: Any = None,
    dry_run: bool = False,
    node_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Detect when two KG nodes refer to the same real-world entity and merge them.

    In heuristic mode, compares entity labels and summaries using string
    similarity.  In LLM mode, uses the LLM to make semantically informed
    resolution decisions.

    Args:
        client: Spacetime Memory Client instance.
        workspace_id: Target workspace.
        threshold: Similarity threshold (0.0-1.0) for heuristic mode.
            Default 0.70.
        llm_client: Optional ``LLMClient`` or callable for LLM mode.
        dry_run: If True, only report what would be resolved.
        node_ids: Optional subset of KG node IDs to consider.

    Returns:
        Dict with keys:
            resolutions: List of resolution result dicts.
            pairs_analyzed: Number of entity pairs evaluated.
            resolutions_found: Count.
            mode: ``"llm"``, ``"heuristic"``, or ``"none"``.
    """
    try:
        nodes = client._query(
            "kg_node",
            workspace_id=workspace_id,
            columns=["id", "label", "node_type", "summary", "name"],
        )
    except Exception as e:
        logger.warning("resolve_entities: failed to query kg_node: %s", e)
        return {
            "resolutions": [],
            "pairs_analyzed": 0,
            "resolutions_found": 0,
            "mode": "none",
            "error": str(e),
        }

    if not nodes:
        return {
            "resolutions": [],
            "pairs_analyzed": 0,
            "resolutions_found": 0,
            "mode": "none",
        }

    if node_ids:
        id_set = set(node_ids)
        nodes = [n for n in nodes if n.get("id", "") in id_set]

    use_llm = bool(llm_client)
    resolutions: list[dict[str, Any]] = []
    consumed: set[int] = set()
    pairs_analyzed = 0

    for i in range(len(nodes)):
        if i in consumed:
            continue
        node_a = nodes[i]
        label_a = node_a.get("label", "") or node_a.get("name", "")
        summary_a = node_a.get("summary", "")
        type_a = node_a.get("node_type", "")
        id_a = node_a.get("id", "")

        for j in range(i + 1, len(nodes)):
            if j in consumed:
                continue
            node_b = nodes[j]
            label_b = node_b.get("label", "") or node_b.get("name", "")
            summary_b = node_b.get("summary", "")
            type_b = node_b.get("node_type", "")
            id_b = node_b.get("id", "")

            # Skip empty labels
            if not label_a or not label_b:
                continue

            pairs_analyzed += 1

            if use_llm:
                prompt_text = ENTITY_RESOLUTION_PROMPT.format(
                    entity_a_id=id_a,
                    entity_a_label=label_a,
                    entity_a_type=type_a,
                    entity_a_summary=summary_a or "(no summary)",
                    entity_b_id=id_b,
                    entity_b_label=label_b,
                    entity_b_type=type_b,
                    entity_b_summary=summary_b or "(no summary)",
                )
                llm_result = _call_llm_parse_json(
                    llm_client,
                    [{"role": "user", "content": prompt_text}],
                    temperature=0.1,
                )
                if llm_result is not None:
                    same = llm_result.get("same_entity", False)
                    confidence = float(llm_result.get("confidence", 0.0))
                    canonical_label = llm_result.get("canonical_label", label_a)
                    merged_summary = llm_result.get("merged_summary", "")
                    entity_type = llm_result.get("entity_type", type_a)
                    reasoning = llm_result.get("reasoning", "")
                    if not isinstance(same, bool):
                        same = bool(same)

                    if same and confidence >= 0.5:
                        resolutions.append({
                            "kept_id": id_a,
                            "removed_id": id_b,
                            "label_a": label_a,
                            "label_b": label_b,
                            "canonical_label": canonical_label,
                            "merged_summary": merged_summary,
                            "entity_type": entity_type,
                            "confidence": confidence,
                            "reasoning": reasoning,
                            "method": "llm",
                        })
                        consumed.add(j)
                    continue

            # Heuristic fallback
            sim = _entity_label_similarity(label_a, summary_a, label_b, summary_b)
            if sim >= threshold:
                # Pick the more descriptive label as canonical
                canonical_label = label_a if len(label_a) >= len(label_b) else label_b
                merged_summary = _merge_entity_summaries(summary_a, summary_b)
                entity_type = type_a if type_a else type_b

                resolutions.append({
                    "kept_id": id_a,
                    "removed_id": id_b,
                    "label_a": label_a,
                    "label_b": label_b,
                    "canonical_label": canonical_label,
                    "merged_summary": merged_summary,
                    "entity_type": entity_type,
                    "confidence": sim,
                    "reasoning": f"Label similarity: {sim:.2f}",
                    "method": "heuristic",
                })
                consumed.add(j)

    # Persist resolutions (if not dry run)
    if not dry_run:
        for res in resolutions:
            kept_id = res["kept_id"]
            removed_id = res["removed_id"]
            canonical_label = res["canonical_label"]
            merged_summary = res["merged_summary"]
            entity_type = res["entity_type"]

            try:
                # Update the surviving node
                client._call(
                    "update_kg_node",
                    [workspace_id, kept_id, canonical_label, entity_type, merged_summary],
                )
            except Exception as e:
                logger.warning("resolve_entities: update_kg_node failed: %s", e)
                res["persist_error"] = str(e)

            try:
                # Re-point edges from the removed node to the survivor
                client._call(
                    "migrate_entity_edges",
                    [workspace_id, removed_id, kept_id],
                )
            except Exception as e:
                logger.warning("resolve_entities: migrate edges failed: %s", e)
                res["migrate_error"] = str(e)

            try:
                # Delete the removed node
                client._call("delete_kg_node", [workspace_id, removed_id])
            except Exception as e:
                logger.warning("resolve_entities: delete_kg_node failed: %s", e)
                res["delete_error"] = str(e)

    return {
        "resolutions": resolutions,
        "pairs_analyzed": pairs_analyzed,
        "resolutions_found": len(resolutions),
        "mode": "llm" if use_llm else "heuristic",
    }


def _merge_entity_summaries(summary_a: str, summary_b: str) -> str:
    """Combine two entity summaries, deduplicating and concatenating."""
    if not summary_a:
        return summary_b
    if not summary_b:
        return summary_a
    if _combined_similarity(summary_a, summary_b) > 0.8:
        # Very similar — keep the longer one
        return summary_a if len(summary_a) >= len(summary_b) else summary_b
    return f"{summary_a} {summary_b}".strip()
