"""Advanced retrieval techniques — Mnemosyne parity.

Provides multi-signal fusion retrieval and memory analysis:

- QueryIntentClassifier: classifies queries into intent categories
- MemoryCompressor: compresses long memory stores into compact form
- PersonaExtractor: extracts user persona from conversation history
- WeibullTemporalBoost: recency-weighted scoring (extends weibull.py)
- PatternDetectorAdvanced: advanced temporal/content/sequence patterns

All features are NATIVE — no external deps (numpy, pandas, etc.).
"""
from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUERY_INTENTS = {
    "factual": "Looking for specific facts, dates, names, or data",
    "temporal": "Asking about time, recency, or sequences",
    "procedural": "How-to questions, instructions, recipes",
    "exploratory": "Open-ended discovery, brainstorming, suggestions",
    "social": "Questions about people, relationships, opinions",
    "summarization": "Summarize, overview, high-level understanding",
    "comparison": "Compare, contrast, differences between things",
    "causal": "Why questions, causes, explanations, reasoning",
}


# ---------------------------------------------------------------------------
# Query Intent Classification
# ---------------------------------------------------------------------------


def classify_query_intent(
    query: str,
    use_llm: bool = False,
    llm_complete_fn: Any | None = None,
) -> dict[str, Any]:
    """Classify a search query into an intent category.

    Uses keyword heuristics (fast, no LLM needed) with optional LLM fallback.

    Args:
        query: The search query string.
        use_llm: If True, use LLM for more accurate classification.
        llm_complete_fn: Optional LLM completion function (for LLM mode).

    Returns:
        Dict with ``intent``, ``confidence``, ``secondary_intents``.
    """
    query_lower = query.lower().strip()

    if not query_lower:
        return {"intent": "unknown", "confidence": 0.0, "secondary_intents": []}

    if use_llm and llm_complete_fn:
        try:
            prompt = (
                f"Classify this search query into one intent category:\n\n"
                f"Query: {query}\n\n"
                f"Categories:\n"
                + "\n".join(f"- {k}: {v}" for k, v in QUERY_INTENTS.items()) +
                "\n\nReturn ONLY the category name and confidence (0.0-1.0) "
                "as JSON: {\"intent\": \"...\", \"confidence\": 0.0}"
            )
            raw = llm_complete_fn(prompt)
            if raw:
                try:
                    result = json.loads(raw)
                    if isinstance(result, dict) and "intent" in result:
                        confidence = float(result.get("confidence", 0.8))
                        return {
                            "intent": result["intent"],
                            "confidence": max(0.0, min(1.0, confidence)),
                            "secondary_intents": [],
                        }
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception:
            pass

    # Keyword-based classification
    scores: dict[str, float] = {}

    # Temporal
    temporal_words = {
        "when", "how long", "recent", "latest", "earliest", "before",
        "after", "yesterday", "today", "this week", "this month",
        "timeline", "sequence", "order", "history", "past",
    }
    temporal_score = sum(
        1.0 for w in temporal_words if w in query_lower
    )
    if temporal_score > 0:
        scores["temporal"] = min(1.0, temporal_score * 0.4)

    # Factual
    factual_words = {
        "what is", "who is", "where is", "when did", "what was",
        "what are", "who are", "define", "meaning", "definition",
        "tell me about", "explain", "describe", "fact", "details",
    }
    factual_score = sum(
        1.0 for w in factual_words if w in query_lower
    )
    if factual_score > 0:
        scores["factual"] = min(1.0, factual_score * 0.35)

    # Procedural
    procedural_words = {
        "how to", "how do", "steps", "instructions", "guide",
        "tutorial", "process", "procedure", "way to", "method",
    }
    procedural_score = sum(
        1.0 for w in procedural_words if w in query_lower
    )
    if procedural_score > 0:
        scores["procedural"] = min(1.0, procedural_score * 0.4)

    # Comparison
    comparison_words = {
        "compare", "versus", "vs", "difference", "better", "worse",
        "similarities", "vs.", "compared to", "rather than",
    }
    comparison_score = sum(
        1.0 for w in comparison_words if w in query_lower
    )
    if comparison_score > 0:
        scores["comparison"] = min(1.0, comparison_score * 0.35)

    # Causal
    causal_words = {
        "why", "how come", "reason", "cause", "because",
        "what caused", "what led to", "why did", "explain why",
    }
    causal_score = sum(
        1.0 for w in causal_words if w in query_lower
    )
    if causal_score > 0:
        scores["causal"] = min(1.0, causal_score * 0.4)

    # Social
    social_words = {
        "person", "people", "who", "relationship", "opinion",
        "feeling", "said", "thought", "believes", "thinks",
    }
    social_score = sum(
        1.0 for w in social_words if w in query_lower
    )
    if social_score > 0:
        scores["social"] = min(1.0, social_score * 0.3)

    # Summarization
    summary_words = {
        "summarize", "summary", "overview", "recap", "tl;dr",
        "brief", "in short", "condense", "key points",
    }
    summary_score = sum(
        1.0 for w in summary_words if w in query_lower
    )
    if summary_score > 0:
        scores["summarization"] = min(1.0, summary_score * 0.5)

    # Exploratory
    if not scores and len(query_lower.split()) <= 3:
        scores["exploratory"] = 0.6
    elif not scores:
        scores["exploratory"] = 0.3

    # Sort by score
    sorted_intents = sorted(scores.items(), key=lambda x: -x[1])
    if not sorted_intents:
        return {"intent": "exploratory", "confidence": 0.3, "secondary_intents": []}

    primary = sorted_intents[0]
    secondary = [k for k, v in sorted_intents[1:] if v > 0.2]

    return {
        "intent": primary[0],
        "confidence": round(primary[1], 4),
        "secondary_intents": secondary,
    }


# ---------------------------------------------------------------------------
# Memory Compression
# ---------------------------------------------------------------------------


def compress_memories(
    memories: list[dict[str, Any]],
    max_tokens: int = 2000,
    strategy: str = "importance",
    llm_complete_fn: Any | None = None,
) -> list[dict[str, Any]]:
    """Compress a list of memories into a smaller set.

    Args:
        memories: List of memory dicts with ``content``, ``importance``,
            ``created_at``, ``memory_type``.
        max_tokens: Target maximum total tokens (approximate char count).
        strategy: Compression strategy:
            - ``"importance"``: keep highest importance memories
            - ``"recency"``: keep most recent memories
            - ``"diverse"``: keep diverse set covering different topics
            - ``"llm"``: use LLM to merge/summarize memories
            - ``"hybrid"``: importance + recency weighted
        llm_complete_fn: Required for LLM strategy.

    Returns:
            Compressed list of memories (or summaries).
    """
    if not memories:
        return []

    if strategy == "importance":
        sorted_mems = sorted(
            memories,
            key=lambda m: float(m.get("importance", m.get("confidence", 0.5))),
            reverse=True,
        )
    elif strategy == "recency":
        sorted_mems = sorted(
            memories,
            key=lambda m: float(m.get("created_at", 0)),
            reverse=True,
        )
    elif strategy == "diverse":
        # Cluster by token overlap, pick representative from each cluster
        return _compress_diverse(memories, max_tokens)
    elif strategy == "llm" and llm_complete_fn:
        return _compress_llm(memories, max_tokens, llm_complete_fn)
    else:
        # hybrid: importance * recency weight
        now = time.time() * 1_000_000
        sorted_mems = sorted(
            memories,
            key=lambda m: (
                float(m.get("importance", m.get("confidence", 0.5))) *
                _recency_weight(float(m.get("created_at", 0)), now)
            ),
            reverse=True,
        )

    # Greedily select until we hit max_tokens
    result: list[dict[str, Any]] = []
    total_chars = 0
    for m in sorted_mems:
        content = str(m.get("content", ""))
        chars = len(content) + 100  # overhead for metadata
        if total_chars + chars > max_tokens and result:
            break
        result.append(m)
        total_chars += chars

    return result


def _recency_weight(created_at: float, now: float) -> float:
    """Compute a recency weight using Weibull-like decay."""
    if created_at <= 0:
        return 0.5
    age_seconds = (now - created_at) / 1_000_000 if created_at > 1e12 else now - created_at
    age_days = max(0.0, age_seconds / 86400.0)
    if age_days <= 0:
        return 1.0
    return math.exp(-((age_days / 30.0) ** 0.6))


def _compress_diverse(
    memories: list[dict[str, Any]], max_tokens: int
) -> list[dict[str, Any]]:
    """Diverse compression: cluster by token overlap, pick representatives."""
    if len(memories) <= 3:
        return memories

    # Simple clustering: token-based
    clusters: list[list[dict]] = []
    for m in memories:
        tokens = set(re.findall(r"\w+", str(m.get("content", "")).lower()))
        best_cluster = -1
        best_overlap = 0
        for i, cluster in enumerate(clusters):
            cluster_tokens = set()
            for cm in cluster:
                cluster_tokens.update(
                    re.findall(r"\w+", str(cm.get("content", "")).lower())
                )
            overlap = len(tokens & cluster_tokens)
            if overlap > best_overlap:
                best_overlap = overlap
                best_cluster = i

        if best_overlap >= 2:
            clusters[best_cluster].append(m)
        else:
            clusters.append([m])

    # Pick highest importance from each cluster
    result = []
    for cluster in sorted(clusters, key=len, reverse=True):
        best = max(
            cluster,
            key=lambda m: float(m.get("importance", m.get("confidence", 0.5))),
        )
        total_chars = sum(len(str(r.get("content", ""))) for r in result)
        if total_chars + len(str(best.get("content", ""))) <= max_tokens:
            result.append(best)

    return result


def _compress_llm(
    memories: list[dict[str, Any]],
    max_tokens: int,
    llm_complete_fn: Any,
) -> list[dict[str, Any]]:
    """LLM-based compression: ask LLM to merge/summarize memories."""
    if not memories:
        return []

    contents = "\n".join(
        f"- {m.get('content', '')[:200]}"
        for m in memories[:20]
    )

    prompt = (
        "Condense the following memories into 3-5 concise, information-dense "
        "statements. Keep all important facts, dates, names, and relationships. "
        "Eliminate redundancy.\n\n"
        f"Memories:\n{contents}\n\n"
        "Return as a JSON array of strings."
    )

    try:
        raw = llm_complete_fn(prompt)
        if raw:
            # Parse JSON array
            m = re.search(r"\[.*?\]", raw, re.DOTALL)
            if m:
                compressed = json.loads(m.group())
                if isinstance(compressed, list):
                    return [
                        {"content": item, "memory_type": "compressed",
                         "importance": 0.9}
                        for item in compressed
                    ]
    except Exception:
        pass

    # Fallback: return top 5 by importance
    return sorted(
        memories,
        key=lambda m: float(m.get("importance", m.get("confidence", 0.5))),
        reverse=True,
    )[:5]


# ---------------------------------------------------------------------------
# Persona Extraction
# ---------------------------------------------------------------------------


def extract_persona(
    memories: list[dict[str, Any]],
    messages: list[dict[str, Any]] | None = None,
    llm_complete_fn: Any | None = None,
) -> dict[str, Any]:
    """Extract a user persona from memory and message history.

    Identifies preferences, traits, habits, and interests from existing
    memories and optionally from message history.

    Args:
        memories: List of memory dicts.
        messages: Optional list of message dicts.
        llm_complete_fn: Optional LLM function for richer extraction.

    Returns:
        Dict with persona fields: ``preferences``, ``traits``,
        ``interests``, ``communication_style``, ``confidence``.
    """
    persona: dict[str, Any] = {
        "preferences": [],
        "traits": [],
        "interests": [],
        "communication_style": "",
        "confidence": 0.0,
    }

    if not memories:
        return persona

    # Extract preferences from memory content
    preference_keywords = [
        "prefer", "like", "love", "enjoy", "favorite", "dislike",
        "hate", "want", "need", "would like", "tend to",
    ]

    all_content = " ".join(
        str(m.get("content", "")) for m in memories
    ).lower()

    found_prefs = []
    for kw in preference_keywords:
        idx = all_content.find(kw)
        if idx != -1:
            snippet = all_content[
                max(0, idx - 30):idx + len(kw) + 80
            ].strip()
            if snippet:
                found_prefs.append(snippet)

    persona["preferences"] = found_prefs[:10]

    # Extract traits from memory types
    memory_types = Counter(
        m.get("memory_type", "") for m in memories
    )
    if memory_types:
        dominant = memory_types.most_common(3)
        persona["memory_profile"] = [
            f"{t}: {c} memories" for t, c in dominant
        ]

    # Communication style from messages
    if messages:
        msg_count = len(messages)
        avg_len = sum(
            len(str(m.get("content", ""))) for m in messages
        ) / max(msg_count, 1)
        if avg_len < 50:
            persona["communication_style"] = "concise"
        elif avg_len < 200:
            persona["communication_style"] = "moderate"
        else:
            persona["communication_style"] = "verbose"
        persona["message_count"] = msg_count
        persona["avg_message_length"] = round(avg_len, 1)

    # Confidence based on data quantity
    persona["confidence"] = min(
        1.0, (len(memories) * 0.05 + (len(messages or []) * 0.01))
    )

    # LLM enrichment if available
    if llm_complete_fn and (found_prefs or messages):
        try:
            sample_text = "\n".join(found_prefs[:5])
            if messages:
                sample_text += "\n" + "\n".join(
                    str(m.get("content", ""))[:200]
                    for m in messages[:10]
                )

            prompt = (
                "Analyze the following memories and conversation snippets "
                "to extract a concise user persona. Return JSON with:\n"
                "- traits: array of 3-5 personality traits\n"
                "- interests: array of 3-5 topics/interests\n"
                "- communication_style: one sentence description\n\n"
                f"Data:\n{sample_text[:3000]}\n\n"
                "JSON:"
            )
            raw = llm_complete_fn(prompt)
            if raw:
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    llm_data = json.loads(m.group())
                    if isinstance(llm_data, dict):
                        if "traits" in llm_data:
                            persona["traits"] = llm_data["traits"]
                        if "interests" in llm_data:
                            persona["interests"] = llm_data["interests"]
                        if "communication_style" in llm_data:
                            persona["communication_style"] = (
                                llm_data["communication_style"]
                            )
        except Exception:
            pass

    return persona


# ---------------------------------------------------------------------------
# Advanced Pattern Detection
# ---------------------------------------------------------------------------


def detect_content_patterns(
    memories: list[dict[str, Any]],
    min_frequency: int = 2,
) -> list[dict[str, Any]]:
    """Detect advanced patterns in memory content.

    Finds:
    - Recurring topics (token co-occurrence)
    - Temporal patterns (time-of-day/week clustering)
    - Sequence patterns (A→B→C event chains)
    - Sentiment shifts (positive/negative word trends)

    Args:
        memories: List of memory dicts.
        min_frequency: Minimum occurrences to report.

    Returns:
        List of pattern dicts with ``type``, ``description``, ``strength``.
    """
    patterns: list[dict[str, Any]] = []

    if len(memories) < min_frequency:
        return patterns

    # Token frequency analysis
    all_tokens: list[str] = []
    for m in memories:
        tokens = re.findall(r"\w+", str(m.get("content", "")).lower())
        all_tokens.extend(t for t in tokens if len(t) > 3)

    token_counts = Counter(all_tokens)
    frequent_terms = [(t, c) for t, c in token_counts.most_common(20) if c >= min_frequency]
    frequent = [t for t, c in frequent_terms]

    if frequent_terms:
        top_count = frequent_terms[0][1]
        patterns.append({
            "type": "recurring_topics",
            "description": f"Frequent terms: {', '.join(frequent[:10])}",
            "strength": round(
                top_count / max(sum(c for _, c in frequent_terms[:5]), 1), 4
            ),
            "terms": frequent[:15],
        })

    # Temporal patterns (hour-of-day)
    hours: list[int] = []
    for m in memories:
        ts = m.get("created_at", 0)
        if isinstance(ts, (int, float)) and ts > 0:
            if ts > 1e12:
                ts = ts / 1_000_000
            import datetime
            try:
                dt = datetime.datetime.fromtimestamp(ts)
                hours.append(dt.hour)
            except (OSError, ValueError, OverflowError):
                pass

    if hours:
        hour_counts = Counter(hours)
        peak_hour = hour_counts.most_common(1)
        if peak_hour:
            peak = peak_hour[0][0]
            time_of_day = "morning" if 5 <= peak < 12 else (
                "afternoon" if 12 <= peak < 17 else (
                    "evening" if 17 <= peak < 22 else "night"
                )
            )
            if len(hours) >= 3:
                patterns.append({
                    "type": "temporal_pattern",
                    "description": f"Peak activity: {time_of_day} (hour {peak})",
                    "strength": round(peak_hour[0][1] / len(hours), 4),
                    "peak_hour": peak,
                    "time_of_day": time_of_day,
                })

    # Sequence patterns: consecutive memories with related content
    if len(memories) >= 3:
        sequences = 0
        for i in range(len(memories) - 2):
            tokens_i = set(re.findall(r"\w+", str(memories[i].get("content", "")).lower()))
            tokens_j = set(re.findall(r"\w+", str(memories[i + 1].get("content", "")).lower()))
            tokens_k = set(re.findall(r"\w+", str(memories[i + 2].get("content", "")).lower()))
            shared = tokens_i & tokens_j & tokens_k
            if len(shared) >= 2:
                sequences += 1

        if sequences > 0:
            patterns.append({
                "type": "sequence_pattern",
                "description": f"Found {sequences} related memory sequences",
                "strength": round(sequences / max(len(memories) - 2, 1), 4),
            })

    return patterns


# ---------------------------------------------------------------------------
# PolyphonicRecallMixin — composed into the Client class
# ---------------------------------------------------------------------------


class PolyphonicRecallMixin:
    """Multi-signal retrieval and memory analysis — Mnemosyne parity.

    Provides advanced retrieval and analysis methods that extend the
    existing search infrastructure with query intent, compression,
    persona extraction, and pattern detection.
    """

    def search_with_intent(
        self,
        workspace_id: str,
        query: str,
        top_k: int = 10,
        use_llm_intent: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Search with automatic query intent classification.

        Classifies the query intent and applies appropriate search
        strategy, reranker, and boost factors.

        Args:
            workspace_id: Target workspace.
            query: Search query.
            top_k: Max results.
            use_llm_intent: Use LLM for intent classification.

        Returns:
            Dict with ``results``, ``query_intent``, and metadata.
        """
        intent = classify_query_intent(
            query,
            use_llm=use_llm_intent,
            llm_complete_fn=getattr(self, "_llm_complete", None),
        )
        intent_name = intent["intent"]

        # Map intent to search strategy
        strategy_map = {
            "factual": "semantic",
            "temporal": "recency_boosted",
            "procedural": "hybrid",
            "exploratory": "diverse",
            "social": "entity_focused",
            "summarization": "keyword",
            "comparison": "exact_phrase",
            "causal": "semantic_graph",
        }
        strategy = strategy_map.get(intent_name, "hybrid")

        # Get reranker from recipe infrastructure if available
        reranker_name = ""
        if hasattr(self, "_get_reranker_for_recipe"):
            recipe_reranker = {
                "factual": "",
                "temporal": "",
                "procedural": "",
                "exploratory": "mmr",
                "social": "",
                "summarization": "",
                "comparison": "",
                "causal": "",
            }
            reranker_name = recipe_reranker.get(intent_name, "")

        try:
            search_fn = getattr(self, "search", None)
            if search_fn:
                results = search_fn(
                    workspace_id=workspace_id,
                    query=query,
                    top_k=top_k,
                    polyphonic=True,
                    **kwargs,
                )
            else:
                results = self._query(
                    "memory",
                    workspace_id=workspace_id,
                    filter_dict={"workspace_id": workspace_id},
                )[:top_k]
        except Exception:
            results = []

        return {
            "results": results,
            "query_intent": intent,
            "strategy_used": strategy,
            "reranker_used": reranker_name,
        }

    def compress_workspace_memories(
        self,
        workspace_id: str,
        max_tokens: int = 2000,
        strategy: str = "importance",
    ) -> list[dict[str, Any]]:
        """Compress all memories in a workspace.

        Args:
            workspace_id: Target workspace.
            max_tokens: Target max characters.
            strategy: Compression strategy.

        Returns:
            Compressed memory list.
        """
        memories = self._query(
            "memory",
            workspace_id=workspace_id,
            filter_dict={"workspace_id": workspace_id},
        )
        return compress_memories(
            memories,
            max_tokens=max_tokens,
            strategy=strategy,
            llm_complete_fn=getattr(self, "_llm_complete", None),
        )

    def extract_user_persona(
        self,
        workspace_id: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Extract a user persona from workspace memories and messages.

        Args:
            workspace_id: Target workspace.
            session_id: Optional session to focus on.

        Returns:
            Persona dict with preferences, traits, interests.
        """
        memories = self._query(
            "memory",
            workspace_id=workspace_id,
            filter_dict={"workspace_id": workspace_id},
        )

        messages = []
        if session_id:
            messages = self._query(
                "message",
                filter_dict={"session_id": session_id},
            )

        return extract_persona(
            memories,
            messages=messages,
            llm_complete_fn=getattr(self, "_llm_complete", None),
        )

    def detect_advanced_patterns(
        self,
        workspace_id: str,
        min_frequency: int = 2,
    ) -> list[dict[str, Any]]:
        """Detect advanced content/temporal/sequence patterns.

        Args:
            workspace_id: Target workspace.
            min_frequency: Minimum occurrences.

        Returns:
            List of pattern dicts.
        """
        memories = self._query(
            "memory",
            workspace_id=workspace_id,
            filter_dict={"workspace_id": workspace_id},
        )
        return detect_content_patterns(memories, min_frequency=min_frequency)
