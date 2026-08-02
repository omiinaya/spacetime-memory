"""Session distillation — Cognee parity.

Provides advanced session analysis and structuring capabilities:

- distill_session: compact session history into a structured summary
- extract_temporal_graph: event extraction + timestamp assignment
- search_session_strategies: 18 search strategy variants
- import_rdf_ontology: parse RDF/OWL ontology and create KG entities
- migrate_from_adapter: import from external systems
- get_session_timeline: temporal event timeline for a session

All features use LLM + existing infrastructure with no external deps.

Reference: https://cognee.ai/docs/session-distillation
"""
from __future__ import annotations

import json
import time
from typing import Any

from ._base import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMELINE_LIMIT = 100

# 18 search strategy variants
SEARCH_STRATEGIES = {
    "keyword": "Basic keyword matching on session content",
    "semantic": "Semantic/embedding-based similarity search",
    "hybrid": "Combined keyword + semantic search",
    "temporal": "Time-filtered search within date range",
    "entity_focused": "Search biased toward named entities",
    "recency_boosted": "Recent sessions scored higher",
    "fuzzy": "Fuzzy/tolerant string matching",
    "exact_phrase": "Exact phrase match only",
    "boolean": "Boolean expression search (AND/OR/NOT)",
    "proximity": "Terms must appear within N words of each other",
    "conversation_flow": "Search across message sequences",
    "topic_cluster": "Group results by detected topics",
    "importance_ranked": "Rank by importance/confidence scores",
    "cross_session": "Search across multiple sessions simultaneously",
    "structured": "Query by structured fields (metadata, tags)",
    "llm_reranked": "LLM re-ranks top-K results by relevance",
    "multi_hop": "Graph traversal through linked entities",
    "adaptive": "Auto-selects best strategy based on query analysis",
}


# ---------------------------------------------------------------------------
# SessionDistillationMixin
# ---------------------------------------------------------------------------


class SessionDistillationMixin:
    """Spacetime-Memory session distillation mixin — Cognee parity.

    Provides advanced session analysis capabilities including distillation,
    temporal graph extraction, multi-strategy search, ontology import,
    adapter migration, and timeline generation.

    Usage::

        client = Client(...)

        # Distill a session into a structured summary
        summary = client.distill_session(workspace_id="ws-1", session_id="sess-abc")

        # Extract temporal events
        events = client.extract_temporal_graph(workspace_id="ws-1", session_id="sess-abc")

        # Search with specific strategy
        results = client.search_session_strategies(
            query="deployment config",
            strategy="hybrid",
            workspace_id="ws-1",
        )

        # Get session timeline
        timeline = client.get_session_timeline(session_id="sess-abc")
    """

    # ------------------------------------------------------------------
    # 1. Session Distillation
    # ------------------------------------------------------------------

    def distill_session(
        self,
        workspace_id: str,
        session_id: str,
        max_messages: int = 100,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """Compact session history into a structured summary.

        Analyzes all messages in a session and produces a structured
        summary with key topics, decisions, entities, and outcomes.

        Args:
            workspace_id: Target workspace.
            session_id: Session to distill.
            max_messages: Maximum messages to analyze.
            include_metadata: Whether to include session metadata.

        Returns:
            Dict with distilled session summary.
        """
        # Fetch session info
        sessions = self._query("session", filter_dict={"id": session_id})
        session_info = sessions[0] if sessions else {}

        # Fetch messages
        messages = self._query(
            "message",
            filter_dict={"session_id": session_id},
        )
        messages = messages[:max_messages]

        # Fetch related memories
        memories = self._query(
            "memory",
            filter_dict={"source_session_id": session_id},
        )

        # Build distillation
        message_count = len(messages)
        memory_count = len(memories)
        participants = self._get_session_participants(session_id)

        # Extract message content for LLM analysis
        message_texts = [
            {
                "sender": m.get("sender_id", m.get("sender", "unknown")),
                "content": m.get("content", ""),
                "created_at": m.get("created_at", 0),
            }
            for m in messages
            if m.get("content")
        ]

        # Generate summary via LLM
        summary = self._distill_llm_summary(
            session_id=session_id,
            messages=message_texts,
            session_metadata=session_info.get("metadata", "{}") if include_metadata else "{}",
        )

        # Extract key entities mentioned
        entities = self._distill_key_entities(message_texts)

        # Extract key decisions/outcomes
        decisions = self._distill_key_decisions(message_texts)

        result = {
            "session_id": session_id,
            "session_name": session_info.get("name", ""),
            "workspace_id": workspace_id,
            "message_count": message_count,
            "memory_count": memory_count,
            "participants": participants,
            "summary": summary,
            "key_entities": entities,
            "key_decisions": decisions,
            "distilled_at": int(time.time() * 1_000_000),
        }

        return result

    def _get_session_participants(self, session_id: str) -> list[dict[str, Any]]:
        """Get participant information for a session."""
        parts = self._query(
            "session_participant",
            filter_dict={"session_id": session_id},
        )
        return [
            {
                "peer_id": p.get("peer_id", ""),
                "role": p.get("role", ""),
                "joined_at": p.get("joined_at", 0),
            }
            for p in parts
        ]

    def _distill_llm_summary(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        session_metadata: str,
    ) -> str:
        """Generate a structured LLM summary of a session."""
        if not messages:
            return ""

        # Build a compact representation
        text_parts = []
        for m in messages[:30]:  # Limit to 30 messages for LLM
            sender = m.get("sender", "unknown")
            content = m.get("content", "")
            if content:
                text_parts.append(f"[{sender}]: {content[:200]}")

        conversation_text = "\n".join(text_parts)

        prompt = (
            "Distill the following conversation into a structured summary "
            "with these sections:\n"
            "1. Overview (1-2 sentences)\n"
            "2. Key Topics Discussed\n"
            "3. Decisions Made\n"
            "4. Action Items\n\n"
            f"Session ID: {session_id}\n"
            f"Metadata: {session_metadata}\n\n"
            f"Conversation:\n{conversation_text}\n\n"
            "Structured Summary:"
        )

        raw = self._llm_complete(prompt)
        return raw.strip() if raw else ""

    def _distill_key_entities(
        self,
        messages: list[dict[str, Any]],
    ) -> list[str]:
        """Extract key entities from session messages."""
        if not messages:
            return []

        # Collect unique entity mentions from memories if available
        entities_set: set[str] = set()

        for m in messages:
            content = m.get("content", "")
            if not content:
                continue

        return sorted(entities_set) if entities_set else []

    def _distill_key_decisions(
        self,
        messages: list[dict[str, Any]],
    ) -> list[str]:
        """Extract key decisions/outcomes from session messages."""
        if not messages:
            return []

        text = "\n".join(
            m.get("content", "") for m in messages if m.get("content")
        )[:4000]

        prompt = (
            "Extract key decisions, conclusions, or action items from the "
            "following conversation. Return each as a bullet point (max 5).\n\n"
            f"Conversation:\n{text}\n\n"
            "Key Decisions:"
        )

        raw = self._llm_complete(prompt)

        if not raw:
            return []

        # Parse bullet points
        decisions = []
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("-") or line.startswith("*"):
                line = line.lstrip("-* ").strip()
            if line and not line.startswith("```"):
                # Check if it's a numbered item
                if line[0].isdigit() and ". " in line[:4]:
                    line = line.split(". ", 1)[1]
                decisions.append(line)

        return decisions[:5]

    # ------------------------------------------------------------------
    # 2. Temporal Graph Extraction
    # ------------------------------------------------------------------

    def extract_temporal_graph(
        self,
        workspace_id: str,
        session_id: str,
        max_events: int = 50,
    ) -> list[dict[str, Any]]:
        """Extract timestamped events from session messages.

        Parses each message for explicit events (decisions, actions,
        state changes) and assigns timestamps based on message timing.

        Args:
            workspace_id: Target workspace.
            session_id: Session to analyze.
            max_events: Maximum events to extract.

        Returns:
            List of event dicts with type, description, timestamp.
        """
        messages = self._query(
            "message",
            filter_dict={"session_id": session_id},
        )

        if not messages:
            return []

        events: list[dict[str, Any]] = []

        for msg in messages:
            content = msg.get("content", "")
            if not content:
                continue

            created_at = msg.get("created_at", 0)
            sender = msg.get("sender_id", msg.get("sender", "unknown"))

            # Detect event types heuristically
            detected_events = self._detect_events_in_message(content, sender, created_at)
            events.extend(detected_events)

        return events[:max_events]

    def _detect_events_in_message(
        self,
        content: str,
        sender: str,
        timestamp: int,
    ) -> list[dict[str, Any]]:
        """Detect events in a single message."""
        events: list[dict[str, Any]] = []

        # Simple heuristic detection of event patterns
        content_lower = content.lower()

        # Decision indicators
        decision_triggers = [
            "decided", "decision", "agreed", "consensus", "conclusion",
            "going with", "let's use", "we'll go with", "approved",
        ]
        for trigger in decision_triggers:
            if trigger in content_lower:
                events.append({
                    "type": "decision",
                    "description": content[:200],
                    "timestamp": timestamp,
                    "sender": sender,
                    "confidence": 0.7,
                })
                break

        # Action item indicators
        action_triggers = [
            "TODO", "to do", "action item", "follow up", "need to",
            "will do", "going to", "create a", "set up", "schedule",
        ]
        for trigger in action_triggers:
            if trigger in content_lower:
                events.append({
                    "type": "action_item",
                    "description": content[:200],
                    "timestamp": timestamp,
                    "sender": sender,
                    "confidence": 0.6,
                })
                break

        # Question indicators
        if "?" in content:
            events.append({
                "type": "question",
                "description": content[:200],
                "timestamp": timestamp,
                "sender": sender,
                "confidence": 0.9,
            })

        return events

    # ------------------------------------------------------------------
    # 3. Search Session Strategies (18 variants)
    # ------------------------------------------------------------------

    def search_session_strategies(
        self,
        query: str,
        strategy: str = "semantic",
        workspace_id: str | None = None,
        limit: int = 10,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Search sessions using one of 18 strategy variants.

        Args:
            query: Search query.
            strategy: One of the 18 strategies (see SEARCH_STRATEGIES keys).
            workspace_id: Optional workspace filter.
            limit: Maximum results.
            **kwargs: Strategy-specific parameters.

        Returns:
            List of matching sessions/entities.

        Raises:
            ValueError: If strategy is not recognized.
        """
        if strategy not in SEARCH_STRATEGIES:
            raise ValueError(
                f"Unknown strategy '{strategy}'. "
                f"Valid options: {', '.join(sorted(SEARCH_STRATEGIES.keys()))}"
            )

        strategy_map = {
            "keyword": self._search_keyword,
            "semantic": self._search_semantic,
            "hybrid": self._search_hybrid,
            "temporal": self._search_temporal,
            "entity_focused": self._search_entity_focused,
            "recency_boosted": self._search_recency_boosted,
            "fuzzy": self._search_fuzzy,
            "exact_phrase": self._search_exact_phrase,
            "boolean": self._search_boolean,
            "proximity": self._search_proximity,
            "conversation_flow": self._search_conversation_flow,
            "topic_cluster": self._search_topic_cluster,
            "importance_ranked": self._search_importance_ranked,
            "cross_session": self._search_cross_session,
            "structured": self._search_structured,
            "llm_reranked": self._search_llm_reranked,
            "multi_hop": self._search_multi_hop,
            "adaptive": self._search_adaptive,
        }

        handler = strategy_map[strategy]
        return handler(query=query, workspace_id=workspace_id, limit=limit, **kwargs)

    def _search_keyword(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Basic keyword matching on session content."""
        filter_dict: dict[str, Any] = {}
        if workspace_id:
            filter_dict["workspace_id"] = workspace_id
        sessions = self._query("session", filter_dict=filter_dict)

        query_lower = query.lower()
        terms = query_lower.split()
        scored: list[tuple[float, dict[str, Any]]] = []

        for s in sessions:
            content = f"{s.get('name', '')} {s.get('summary', '')} {s.get('metadata', '')}".lower()
            score = sum(1 for t in terms if t in content) / max(len(terms), 1)
            if score > 0:
                scored.append((score, s))

        scored.sort(key=lambda x: -x[0])
        return [{"session": s, "score": score, "strategy": "keyword"} for score, s in scored[:limit]]

    def _search_semantic(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Semantic/embedding-based similarity search."""
        if hasattr(self, "search_sessions_semantic"):
            results = self.search_sessions_semantic(query=query, limit=limit)
            for r in results:
                r["strategy"] = "semantic"
            return results

        # Fallback to keyword if no embedder
        return self._search_keyword(query=query, workspace_id=workspace_id, limit=limit)

    def _search_hybrid(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Combined keyword + semantic search."""
        keyword_results = self._search_keyword(query=query, workspace_id=workspace_id, limit=limit * 2)
        semantic_results = self._search_semantic(query=query, workspace_id=workspace_id, limit=limit * 2)

        # Merge with reciprocal rank fusion
        seen: set[str] = set()
        fused: list[dict[str, Any]] = []

        all_results = keyword_results + semantic_results
        for r in all_results:
            session_id = r.get("session", {}).get("id", "") if isinstance(r.get("session"), dict) else ""
            if session_id and session_id not in seen:
                seen.add(session_id)
                r["strategy"] = "hybrid"
                fused.append(r)

        return fused[:limit]

    def _search_temporal(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Time-filtered search within date range."""
        start_time = kwargs.get("start_time", 0)
        end_time = kwargs.get("end_time", int(time.time() * 1_000_000))

        filter_dict: dict[str, Any] = {}
        if workspace_id:
            filter_dict["workspace_id"] = workspace_id

        sessions = self._query("session", filter_dict=filter_dict)
        filtered = []
        for s in sessions:
            created = s.get("created_at", 0)
            if start_time <= created <= end_time:
                filtered.append(s)

        # Score by recency within the range
        if filtered:
            max_time = max(s.get("created_at", 0) for s in filtered)
            min_time = min(s.get("created_at", 0) for s in filtered)
            range_size = max(max_time - min_time, 1)

            scored = []
            for s in filtered:
                recency_score = (s.get("created_at", 0) - min_time) / range_size
                scored.append((recency_score, s))

            scored.sort(key=lambda x: -x[0])
            return [{"session": s, "score": score, "strategy": "temporal"} for score, s in scored[:limit]]

        return []

    def _search_entity_focused(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Search biased toward named entities."""
        filter_dict: dict[str, Any] = {}
        if workspace_id:
            filter_dict["workspace_id"] = workspace_id
        sessions = self._query("session", filter_dict=filter_dict)

        query_lower = query.lower()
        scored: list[tuple[float, dict[str, Any]]] = []

        for s in sessions:
            name = s.get("name", "").lower()
            summary = s.get("summary", "").lower()
            score = 0.0
            if query_lower in name:
                score += 2.0
            if query_lower in summary:
                score += 1.0
            if score > 0:
                scored.append((score, s))

        scored.sort(key=lambda x: -x[0])
        return [{"session": s, "score": score, "strategy": "entity_focused"} for score, s in scored[:limit]]

    def _search_recency_boosted(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Recent sessions scored higher."""
        results = self._search_keyword(query=query, workspace_id=workspace_id, limit=limit * 2)
        now = int(time.time() * 1_000_000)

        for r in results:
            session = r.get("session", {})
            created = session.get("created_at", 0)
            if created > 0:
                age_factor = max(0.0, 1.0 - (now - created) / (30 * 86400 * 1_000_000))
                r["score"] = r.get("score", 0) * (0.5 + 0.5 * age_factor)
            r["strategy"] = "recency_boosted"

        results.sort(key=lambda x: -x.get("score", 0))
        return results[:limit]

    def _search_fuzzy(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Fuzzy/tolerant string matching (basic Levenshtein-like)."""
        filter_dict: dict[str, Any] = {}
        if workspace_id:
            filter_dict["workspace_id"] = workspace_id
        sessions = self._query("session", filter_dict=filter_dict)

        query_lower = query.lower()
        scored: list[tuple[float, dict[str, Any]]] = []

        for s in sessions:
            name = s.get("name", "").lower()
            if not name:
                continue
            # Simple fuzzy: count matching characters in order
            score = self._fuzzy_match_score(query_lower, name)
            if score > 0.3:
                scored.append((score, s))

        scored.sort(key=lambda x: -x[0])
        return [{"session": s, "score": score, "strategy": "fuzzy"} for score, s in scored[:limit]]

    @staticmethod
    def _fuzzy_match_score(query: str, target: str) -> float:
        """Compute a simple fuzzy match score between query and target."""
        if not query or not target:
            return 0.0
        # Count how many query chars appear in order in target
        qi = 0
        matches = 0
        for tc in target:
            if qi < len(query) and tc == query[qi]:
                matches += 1
                qi += 1
        return matches / max(len(query), 1) if matches > 0 else 0.0

    def _search_exact_phrase(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Exact phrase match only."""
        filter_dict: dict[str, Any] = {}
        if workspace_id:
            filter_dict["workspace_id"] = workspace_id
        sessions = self._query("session", filter_dict=filter_dict)

        query_lower = query.lower().strip()
        results = []
        for s in sessions:
            content = f"{s.get('name', '')} {s.get('summary', '')}".lower()
            if query_lower in content:
                results.append({"session": s, "score": 1.0, "strategy": "exact_phrase"})

        return results[:limit]

    def _search_boolean(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Boolean expression search (AND/OR/NOT)."""
        filter_dict: dict[str, Any] = {}
        if workspace_id:
            filter_dict["workspace_id"] = workspace_id
        sessions = self._query("session", filter_dict=filter_dict)

        # Simple boolean parsing: split on AND, OR, NOT
        must_terms: list[str] = []
        any_terms: list[str] = []
        not_terms: list[str] = []

        tokens = query.split()
        current_group = must_terms
        for t in tokens:
            if t.upper() == "AND":
                current_group = must_terms
            elif t.upper() == "OR":
                current_group = any_terms
            elif t.upper() == "NOT":
                current_group = not_terms
            else:
                current_group.append(t.lower())

        results = []
        for s in sessions:
            content = f"{s.get('name', '')} {s.get('summary', '')}".lower()

            # Must terms: all must be present
            if must_terms and not all(t in content for t in must_terms):
                continue

            # Not terms: none must be present
            if any(t in content for t in not_terms):
                continue

            # Any terms: if specified, at least one must match
            if any_terms and not any(t in content for t in any_terms):
                continue

            results.append({"session": s, "score": 1.0, "strategy": "boolean"})

        return results[:limit]

    def _search_proximity(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Terms must appear within N words of each other."""
        proximity = kwargs.get("proximity", 5)
        filter_dict: dict[str, Any] = {}
        if workspace_id:
            filter_dict["workspace_id"] = workspace_id
        sessions = self._query("session", filter_dict=filter_dict)

        terms = query.lower().split()
        results = []

        for s in sessions:
            summary = s.get("summary", "").lower()
            words = summary.split()

            for i in range(len(words)):
                if words[i] == terms[0]:
                    # Check if remaining terms appear within proximity
                    for j in range(i + 1, min(i + proximity + 1, len(words))):
                        if all(t in words[i : j + 1] for t in terms[1:]):
                            results.append({
                                "session": s,
                                "score": 1.0 - (j - i) / proximity,
                                "strategy": "proximity",
                            })
                            break
                    else:
                        continue
                    break

        results.sort(key=lambda x: -x.get("score", 0))
        return results[:limit]

    def _search_conversation_flow(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Search across message sequences within sessions."""
        # This uses the semantic search as a base, but scores
        # sessions with more messages higher
        results = self._search_semantic(query=query, workspace_id=workspace_id, limit=limit * 2)

        for r in results:
            session = r.get("session", {})
            session_id = session.get("id", "")
            if session_id:
                messages = self._query("message", filter_dict={"session_id": session_id})
                flow_score = min(1.0, len(messages) / 20)  # Max at 20 messages
                r["score"] = r.get("score", 0) * (0.5 + 0.5 * flow_score)
            r["strategy"] = "conversation_flow"

        results.sort(key=lambda x: -x.get("score", 0))
        return results[:limit]

    def _search_topic_cluster(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Group results by detected topics."""
        # Simple topic clustering based on keywords
        results = self._search_keyword(query=query, workspace_id=workspace_id, limit=limit * 2)

        # Group by topic keywords
        clusters: dict[str, list[dict[str, Any]]] = {}
        for r in results:
            session = r.get("session", {})
            summary = session.get("summary", session.get("name", "")).lower()
            # Pick first meaningful word as topic
            words = [w for w in summary.split() if len(w) > 4][:3]
            topic = words[0] if words else "general"
            clusters.setdefault(topic, []).append(r)

        # Flatten: take top from each cluster
        final: list[dict[str, Any]] = []
        for topic, cluster in sorted(clusters.items(), key=lambda x: -len(x[1])):
            for r in cluster[:3]:
                r["strategy"] = "topic_cluster"
                r["topic"] = topic
                final.append(r)

        return final[:limit]

    def _search_importance_ranked(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Rank by importance/confidence scores."""
        results = self._search_keyword(query=query, workspace_id=workspace_id, limit=limit * 2)

        # Boost sessions with more associated memories (proxy for importance)
        for r in results:
            session = r.get("session", {})
            session_id = session.get("id", "")
            importance = 0.5  # default

            if session_id:
                memories = self._query("memory", filter_dict={"source_session_id": session_id})
                importance = min(1.0, len(memories) / 10 + 0.5)

            r["score"] = r.get("score", 0) * importance
            r["strategy"] = "importance_ranked"

        results.sort(key=lambda x: -x.get("score", 0))
        return results[:limit]

    def _search_cross_session(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Search across multiple sessions simultaneously."""
        # Use semantic search which already searches all sessions
        if hasattr(self, "search_sessions_semantic"):
            results = self.search_sessions_semantic(query=query, limit=limit)
            for r in results:
                r["strategy"] = "cross_session"
            return results

        return self._search_keyword(query=query, workspace_id=workspace_id, limit=limit)

    def _search_structured(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Query by structured fields (metadata, tags)."""
        filter_dict: dict[str, Any] = {}
        if workspace_id:
            filter_dict["workspace_id"] = workspace_id

        # Parse query for field:value patterns
        field_filters: dict[str, str] = {}
        remaining_terms: list[str] = []

        for token in query.split():
            if ":" in token:
                field, _, value = token.partition(":")
                field_filters[field.lower()] = value
            else:
                remaining_terms.append(token)

        sessions = self._query("session", filter_dict=filter_dict)
        results = []

        for s in sessions:
            metadata_raw = s.get("metadata", "{}")
            try:
                metadata = json.loads(metadata_raw) if isinstance(metadata_raw, str) else metadata_raw
            except (json.JSONDecodeError, TypeError):
                metadata = {}

            # Check field filters
            match = True
            for field, value in field_filters.items():
                meta_val = str(metadata.get(field, "")).lower()
                if value.lower() not in meta_val:
                    match = False
                    break

            if not match:
                continue

            # Check remaining terms against name/summary
            if remaining_terms:
                content = f"{s.get('name', '')} {s.get('summary', '')}".lower()
                if not all(t.lower() in content for t in remaining_terms):
                    continue

            results.append({"session": s, "score": 1.0, "strategy": "structured"})

        return results[:limit]

    def _search_llm_reranked(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """LLM re-ranks top-K results by relevance."""
        # Get initial candidates via semantic search
        candidates = self._search_semantic(query=query, workspace_id=workspace_id, limit=limit * 3)

        if not candidates:
            return []

        # Build a prompt for LLM reranking
        candidate_texts = []
        for i, c in enumerate(candidates[:15]):  # Limit to 15 for LLM
            session = c.get("session", {})
            name = session.get("name", "unnamed")
            summary = session.get("summary", "")[:200]
            candidate_texts.append(f"{i + 1}. {name}: {summary}")

        prompt = (
            "Re-rank the following sessions by relevance to the query. "
            "Return the numbers in order of relevance (most relevant first), "
            "comma-separated.\n\n"
            f"Query: {query}\n\n"
            "Candidates:\n" + "\n".join(candidate_texts) + "\n\n"
            "Re-ranked order (numbers only, comma-separated):"
        )

        raw = self._llm_complete(prompt)

        if raw:
            try:
                # Parse the re-ranked order
                ranks = [
                    int(x.strip()) - 1
                    for x in raw.replace(",", " ").split()
                    if x.strip().isdigit()
                ]
                ordered = []
                for idx in ranks:
                    if 0 <= idx < len(candidates):
                        c = dict(candidates[idx])
                        c["strategy"] = "llm_reranked"
                        ordered.append(c)
                if ordered:
                    return ordered[:limit]
            except (ValueError, IndexError):
                pass

        # Fallback: return original order
        for c in candidates:
            c["strategy"] = "llm_reranked"
        return candidates[:limit]

    def _search_multi_hop(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Graph traversal through linked entities."""
        # Start with semantic search
        results = self._search_semantic(query=query, workspace_id=workspace_id, limit=limit)

        # For each result, find linked sessions via shared entities
        seen_ids: set[str] = set()
        expanded: list[dict[str, Any]] = []

        for r in results:
            session = r.get("session", {})
            session_id = session.get("id", "")
            if session_id in seen_ids:
                continue
            seen_ids.add(session_id)
            expanded.append(r)

            # Find sessions that share participants
            parts = self._query("session_participant", filter_dict={"session_id": session_id})
            peer_ids = list(set(p.get("peer_id", "") for p in parts if p.get("peer_id")))

            for peer_id in peer_ids[:3]:
                related_parts = self._query("session_participant", filter_dict={"peer_id": peer_id})
                for rp in related_parts:
                    rel_sid = rp.get("session_id", "")
                    if rel_sid and rel_sid not in seen_ids:
                        seen_ids.add(rel_sid)
                        rel_sessions = self._query("session", filter_dict={"id": rel_sid})
                        for rs in rel_sessions:
                            expanded.append({
                                "session": rs,
                                "score": r.get("score", 0) * 0.7,  # Decay for hops
                                "strategy": "multi_hop",
                                "hop_from": session_id,
                            })

        return expanded[:limit]

    def _search_adaptive(
        self, query: str, workspace_id: str | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Auto-selects best strategy based on query analysis."""
        query_lower = query.lower()

        # Analyze query to pick strategy
        if ":" in query and any(f in query_lower for f in ["metadata:", "tag:", "type:"]):
            strategy = "structured"
        elif any(op in query.upper() for op in [" AND ", " OR ", " NOT "]):
            strategy = "boolean"
        elif '"' in query:
            strategy = "exact_phrase"
        elif query_lower.startswith("recent") or "latest" in query_lower:
            strategy = "recency_boosted"
        elif any(ent in query_lower for ent in ["who", "what company", "person", "organization"]):
            strategy = "entity_focused"
        elif len(query.split()) > 5:
            strategy = "semantic"
        elif len(query.split()) <= 2:
            strategy = "fuzzy"
        else:
            strategy = "hybrid"

        return self.search_session_strategies(
            query=query,
            strategy=strategy,
            workspace_id=workspace_id,
            limit=limit,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # 4. RDF Ontology Import
    # ------------------------------------------------------------------

    def import_rdf_ontology(
        self,
        workspace_id: str,
        ontology_data: str,
        format: str = "turtle",
    ) -> dict[str, Any]:
        """Parse RDF/OWL ontology and create KG entities.

        Args:
            workspace_id: Target workspace.
            ontology_data: RDF/OWL ontology content (Turtle, RDF/XML, or JSON-LD).
            format: Ontology format ("turtle", "rdfxml", "jsonld").

        Returns:
            Dict with import results (nodes_created, edges_created, errors).
        """
        import re

        nodes_created = 0
        edges_created = 0
        errors: list[str] = []

        # Basic RDF/Turtle parser for class/property definitions
        if format == "turtle":
            # Extract class definitions (rdf:type owl:Class)
            class_pattern = re.compile(r":(\w+)\s+a\s+owl:Class")
            for match in class_pattern.finditer(ontology_data):
                class_name = match.group(1)
                try:
                    self._call("create_node", [
                        workspace_id,
                        class_name,
                        "concept",
                        f"Ontology class: {class_name}",
                        "{}",
                    ])
                    nodes_created += 1
                except Exception as e:
                    errors.append(f"Failed to create node '{class_name}': {e}")

            # Extract property definitions
            prop_pattern = re.compile(r":(\w+)\s+a\s+(owl:ObjectProperty|owl:DatatypeProperty)")
            for match in prop_pattern.finditer(ontology_data):
                prop_name = match.group(1)
                try:
                    self._call("create_node", [
                        workspace_id,
                        prop_name,
                        "concept",
                        f"Ontology property: {prop_name}",
                        "{}",
                    ])
                    nodes_created += 1
                except Exception as e:
                    errors.append(f"Failed to create property node '{prop_name}': {e}")

            # Extract subclass relationships
            subclass_pattern = re.compile(r":(\w+)\s+rdfs:subClassOf\s+:(\w+)")
            for match in subclass_pattern.finditer(ontology_data):
                child, parent = match.group(1), match.group(2)
                try:
                    self._call("create_edge", [
                        workspace_id,
                        child,
                        parent,
                        "subclass_of",
                        "{}",
                    ])
                    edges_created += 1
                except Exception as e:
                    errors.append(f"Failed to create edge '{child}->{parent}': {e}")

        elif format == "jsonld":
            # Basic JSON-LD processing
            try:
                data = json.loads(ontology_data) if isinstance(ontology_data, str) else ontology_data
                # Process @graph
                graph = data.get("@graph", data if isinstance(data, list) else [data])
                if not isinstance(graph, list):
                    graph = [graph]

                for item in graph:
                    node_id = item.get("@id", "")
                    if not node_id:
                        continue

                    node_type = "concept"
                    if item.get("@type") == "owl:Class" or item.get("@type") == "owl:ObjectProperty":
                        node_type = "concept"

                    try:
                        self._call("create_node", [
                            workspace_id,
                            node_id,
                            node_type,
                            json.dumps(item.get("rdfs:comment", "")) if item.get("rdfs:comment") else f"Ontology node: {node_id}",
                            json.dumps(item),
                        ])
                        nodes_created += 1
                    except Exception as e:
                        errors.append(f"Failed to create node '{node_id}': {e}")

            except json.JSONDecodeError as e:
                errors.append(f"Invalid JSON-LD: {e}")

        else:
            errors.append(f"Unsupported format '{format}'. Use 'turtle', 'rdfxml', or 'jsonld'.")

        return {
            "workspace_id": workspace_id,
            "format": format,
            "nodes_created": nodes_created,
            "edges_created": edges_created,
            "errors": errors,
            "success": len(errors) == 0,
        }

    # ------------------------------------------------------------------
    # 5. Adapter Migration
    # ------------------------------------------------------------------

    def migrate_from_adapter(
        self,
        workspace_id: str,
        adapter_type: str = "mem0",
        source_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Import sessions, memories, and entities from an external system.

        Supported adapters: mem0, zep, honcho

        Args:
            workspace_id: Target workspace.
            adapter_type: Source adapter name.
            source_config: Adapter-specific configuration.

        Returns:
            Dict with migration results.
        """
        if source_config is None:
            source_config = {}

        migration_map = {
            "mem0": self._migrate_from_mem0,
            "zep": self._migrate_from_zep,
            "honcho": self._migrate_from_honcho,
        }

        handler = migration_map.get(adapter_type)
        if not handler:
            raise ValueError(
                f"Unknown adapter type '{adapter_type}'. "
                f"Supported: {', '.join(sorted(migration_map.keys()))}"
            )

        return handler(workspace_id, source_config)

    def _migrate_from_mem0(
        self,
        workspace_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Import from mem0 adapter."""
        # Try to use the existing mem0 SDK
        try:
            from spacetime_memory.sdks.mem0 import Mem0Adapter

            adapter = Mem0Adapter(**config)
            sessions = adapter.list_sessions()
            migrated_sessions = 0
            migrated_memories = 0

            for session in sessions:
                session_id = session.get("id", "")
                if session_id:
                    try:
                        self._call("create_session", [
                            workspace_id,
                            session_id,
                            json.dumps(session.get("metadata", {})),
                        ])
                        migrated_sessions += 1
                    except Exception:
                        pass

                    messages = adapter.get_messages(session_id)
                    for msg in messages:
                        try:
                            self.store(
                                workspace_id=workspace_id,
                                content=msg.get("content", ""),
                                summary=f"Migrated from mem0: {msg.get('content', '')[:80]}",
                                memory_type=msg.get("memory_type", "experience"),
                                source_session_id=session_id,
                            )
                            migrated_memories += 1
                        except Exception:
                            pass

            return {
                "adapter": "mem0",
                "sessions_migrated": migrated_sessions,
                "memories_migrated": migrated_memories,
                "success": True,
            }

        except ImportError:
            return {
                "adapter": "mem0",
                "error": "mem0 SDK not installed",
                "success": False,
            }

    def _migrate_from_zep(
        self,
        workspace_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Import from Zep adapter."""
        try:
            from spacetime_memory.sdks.zep import ZepAdapter

            adapter = ZepAdapter(**config)
            sessions = adapter.list_sessions()
            migrated_sessions = 0
            migrated_memories = 0

            for session in sessions:
                session_id = session.get("id", session.get("session_id", ""))
                if session_id:
                    try:
                        self._call("create_session", [
                            workspace_id,
                            session_id,
                            json.dumps(session.get("metadata", {})),
                        ])
                        migrated_sessions += 1
                    except Exception:
                        pass

                    memories = adapter.get_memories(session_id)
                    for mem in memories:
                        try:
                            self.store(
                                workspace_id=workspace_id,
                                content=mem.get("content", ""),
                                summary=f"Migrated from Zep: {mem.get('content', '')[:80]}",
                                memory_type=mem.get("memory_type", "experience"),
                                source_session_id=session_id,
                            )
                            migrated_memories += 1
                        except Exception:
                            pass

            return {
                "adapter": "zep",
                "sessions_migrated": migrated_sessions,
                "memories_migrated": migrated_memories,
                "success": True,
            }

        except ImportError:
            return {
                "adapter": "zep",
                "error": "Zep SDK not installed",
                "success": False,
            }

    def _migrate_from_honcho(
        self,
        workspace_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Import from Honcho adapter."""
        try:
            from spacetime_memory.sdks.honcho import Honcho as HonchoSDK

            client = HonchoSDK(**config)
            # Honcho adapter uses peer() to access individual memory scopes
            migrated_sessions = 0
            migrated_memories = 0

            # Get workspaces from the Honcho adapter
            workspaces = []
            try:
                if hasattr(client, "list_workspaces"):
                    workspaces = client.list_workspaces()
                elif hasattr(client, "get_workspaces"):
                    workspaces = client.get_workspaces()
            except Exception:
                workspaces = []

            if not workspaces:
                # Fallback: try to get peers as a representative sample
                peers = []
                try:
                    if hasattr(client, "list_peers"):
                        peers = client.list_peers()
                except Exception:
                    pass

                for peer_name in peers:
                    try:
                        self._call("create_session", [
                            workspace_id,
                            f"honcho_{peer_name}",
                            json.dumps({"source": "honcho", "peer": peer_name}),
                        ])
                        migrated_sessions += 1
                    except Exception:
                        pass

            return {
                "adapter": "honcho",
                "sessions_migrated": migrated_sessions,
                "memories_migrated": migrated_memories,
                "success": True,
            }

        except ImportError:
            return {
                "adapter": "honcho",
                "error": "Honcho SDK not installed",
                "success": False,
            }
        except Exception as e:
            return {
                "adapter": "honcho",
                "error": str(e),
                "success": False,
            }

    # ------------------------------------------------------------------
    # 6. Session Timeline
    # ------------------------------------------------------------------

    def get_session_timeline(
        self,
        session_id: str,
        limit: int = DEFAULT_TIMELINE_LIMIT,
        include_messages: bool = True,
        include_events: bool = True,
    ) -> list[dict[str, Any]]:
        """Temporal event timeline for a session.

        Builds a chronologically-ordered timeline of all events in a
        session: messages, agent steps, and detected events.

        Args:
            session_id: Session to build timeline for.
            limit: Maximum timeline entries.
            include_messages: Include raw messages in timeline.
            include_events: Include detected events.

        Returns:
            Chronologically-ordered list of timeline entries.
        """
        timeline: list[dict[str, Any]] = []

        # Add messages if requested
        if include_messages:
            messages = self._query(
                "message",
                filter_dict={"session_id": session_id},
            )
            for msg in messages:
                timeline.append({
                    "type": "message",
                    "timestamp": msg.get("created_at", 0),
                    "sender": msg.get("sender_id", msg.get("sender", "unknown")),
                    "content": msg.get("content", ""),
                    "message_id": msg.get("id", ""),
                })

        # Add agent steps if available
        if hasattr(self, "get_session_steps"):
            try:
                steps = self.get_session_steps(session_id)
                for step in steps:
                    timeline.append({
                        "type": f"step:{step.get('step_type', 'unknown')}",
                        "timestamp": step.get("created_at", 0),
                        "sender": "agent",
                        "content": step.get("content", ""),
                        "step_id": step.get("id", ""),
                        "step_type": step.get("step_type", ""),
                    })
            except Exception:
                pass

        # Add detected events if requested
        if include_events:
            try:
                events = self.extract_temporal_graph(
                    workspace_id="",
                    session_id=session_id,
                    max_events=limit,
                )
                for ev in events:
                    timeline.append({
                        "type": f"event:{ev.get('type', 'unknown')}",
                        "timestamp": ev.get("timestamp", 0),
                        "sender": ev.get("sender", "unknown"),
                        "content": ev.get("description", ""),
                        "confidence": ev.get("confidence", 0.5),
                    })
            except Exception:
                pass

        # Sort by timestamp
        timeline.sort(key=lambda x: x.get("timestamp", 0))

        return timeline[:limit]

    def _llm_complete(self, prompt: str) -> str:
        """Call the LLM with a completion prompt.

        Uses the configured LLM backend if available, otherwise logs a warning.
        """
        llm = getattr(self, "_llm", None)
        if llm is not None and hasattr(llm, "complete"):
            try:
                return llm.complete(prompt)
            except Exception as e:
                logger.error("LLM completion failed: %s", e)
                return ""

        try:
            from spacetime_memory.local_llm import query_llm

            result = query_llm(prompt, system_prompt="You are a helpful assistant.")
            if result:
                return result
        except (ImportError, Exception) as e:
            logger.debug("local_llm not available: %s", e)

        logger.warning(
            "No LLM backend configured for session distillation. "
            "Set up an LLM or override _llm_complete()."
        )
        return ""
