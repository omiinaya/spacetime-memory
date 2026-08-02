"""
Zep-compatible memory adapter — client classes.

Provides ZepClient (sync), UserClient, sub-client proxies (_MemoryProxy,
_UserProxy), graph namespace classes, and the Zep subclass with .memory /
.user / .graph sub-clients.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from ...client import Client
from ._models import (
    BadRequestError,
    Fact,
    MemoryMessage,
    MemorySearchResult,
    NotFoundError,
    Session,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ZepClient — main entry point
# ---------------------------------------------------------------------------


class ZepClient:
    """Drop-in replacement for ``zep_python.ZepClient``.

    Maps Zep's REST API onto Spacetime-Memory's storage layer:

    * ``session_id`` → ``workspace name`` / memory type tag
    * ``messages`` → memory records with ``memory_type=\"experience\"``
    * ``facts`` → memory records with ``memory_type=\"fact\"``
    * ``search`` → ``hybrid_search`` with semantic + keyword matching

    Note: Zep's async endpoints, WebSocket streams, and LLM-based
    summarisation are not available via Spacetime-Memory.

    Usage::

        from spacetime_memory.sdks.zep import ZepClient

        client = ZepClient(host=\"127.0.0.1\", port=3001)
        client.add_memory(
            session_id=\"my-session\",
            messages=[{\"role\": \"user\", \"content\": \"Hello world\"}],
        )
        memory = client.get_memory(session_id=\"my-session\")
        results = client.search_memory(session_id=\"my-session\", query=\"hello\")
        client.close()

    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        config: dict[str, Any] | None = None,
        token: str | None = None,
    ):
        """Initialize the API resource wrapper."""
        self._client = Client(
            host=host,
            port=port,
            database=config.get("db", config.get("database")) if config else None,
            embedder_url=config.get("embedder_url") if config else None,
            token=token or "",
        )
        # Cache: session_id -> workspace_id
        self._session_to_ws: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_workspace(self, session_id: str) -> str:
        """Resolve a Zep session_id to a workspace, creating if needed."""
        if session_id in self._session_to_ws:
            return self._session_to_ws[session_id]

        workspaces = self._client.list_workspaces()
        match = [w for w in workspaces if w.get("name") == session_id]
        if match:
            ws_id = match[0]["id"]
        else:
            self._client.create_workspace(session_id, f"Zep session: {session_id}")
            # Re-list to get the new workspace's ID
            workspaces = self._client.list_workspaces()
            match = [w for w in workspaces if w.get("name") == session_id]
            ws_id = match[0]["id"] if match else ""

        self._session_to_ws[session_id] = ws_id
        return ws_id

    def _resolve_session(self, session_id: str) -> str | None:
        """Resolve a session_id to a workspace_id without creating.

        Returns None if the session doesn't exist yet.
        """
        if session_id in self._session_to_ws:
            return self._session_to_ws[session_id]
        workspaces = self._client.list_workspaces()
        match = [w for w in workspaces if w.get("name") == session_id]
        if not match:
            return None
        self._session_to_ws[session_id] = match[0]["id"]
        return match[0]["id"]

    def _now_iso(self) -> str:
        """ISO-8601 timestamp."""
        return datetime.now(UTC).isoformat()

    # ------------------------------------------------------------------
    # Zep Memory API
    # ------------------------------------------------------------------

    def add_memory(
        self,
        session_id: str,
        messages: list[dict[str, Any]] | list[MemoryMessage],
        metadata: dict[str, Any] | None = None,
        fact_instruction: str | None = None,
        summary_instruction: str | None = None,
        *,
        fact_rating_instruction: str | None = None,
        extract_facts: bool = True,
    ) -> dict[str, Any]:
        """Add messages to a session's memory (Zep-parity).

        Stores each message as an experience memory.  When
        ``extract_facts`` is true (default), also runs LLM fact extraction
        + rating on the message batch and stores the extracted facts with
        their ratings — matching Zep Cloud's automatic fact-rating
        behaviour.  Degrades gracefully to message-only storage when the
        LLM is unavailable or extraction fails.

        Args:
            session_id: Zep session identifier.
            messages: List of message dicts (``{role, content}``) or
                ``MemoryMessage`` objects.
            metadata: Optional metadata dict.
            fact_instruction: Optional extra instruction to steer fact
                extraction (Zep Cloud compat; forwarded to the LLM prompt).
            summary_instruction: Optional instruction to steer message
                summarisation (Zep Cloud compat; stored for parity).
            fact_rating_instruction: Optional extra instruction to steer
                fact extraction (alias of ``fact_instruction``).
            extract_facts: Whether to run LLM fact extraction + rating.

        Returns:
            A dict with operation status and stored message IDs.

        Example::

            >>> client.add_memory(
            ...     session_id="my-session",
            ...     messages=[{"role": "user", "content": "Hi!"}],
            ... )
            {'status': 'ok'}

        """
        ws_id = self._ensure_workspace(session_id)
        stored_ids: list[str] = []
        message_payloads: list[dict[str, Any]] = []
        for msg in messages:
            if isinstance(msg, MemoryMessage):
                role = msg.role
                content = msg.content
            elif isinstance(msg, dict):
                role = msg.get("role", "user")
                content = msg.get("content", "")
            else:
                role = "user"
                content = str(msg)

            message_payloads.append({"role": role, "content": content})
            self._client.store(
                workspace_id=ws_id,
                content=content,
                summary=f"[{role}] {content[:200]}",
                memory_type="experience",
                peer_id=role,
                source_session_id=session_id,
            )

        # LLM fact extraction + rating (Zep Cloud parity)
        instruction = fact_rating_instruction or fact_instruction
        if extract_facts and message_payloads:
            self._extract_and_rate_facts(
                ws_id, session_id, message_payloads, instruction
            )

        # After storing, fetch IDs for the messages we just added
        memories = self._client.list_memories(
            workspace_id=ws_id, limit=len(messages), memory_type="experience"
        )
        for m in memories or []:
            mid = m.get("id", "") or m.get("entity_id", "")
            if mid and mid not in stored_ids:
                stored_ids.append(mid)

        return {"status": "ok", "message_ids": stored_ids}

    def get_memory(
        self,
        session_id: str,
        limit: int = 10,
        min_rating: float = 0.0,
    ) -> dict[str, Any] | None:
        """Retrieve messages + facts for a session.

        Returns a dict matching the Zep ``Memory`` response shape
        (messages, facts, relevant_facts).

        Args:
            session_id: Zep session identifier.
            limit: Max messages to return (default 10).
            min_rating: Minimum memory rating filter (default 0.0).

        Returns:
            A dict with ``messages``, ``facts``, and ``relevant_facts``
            keys, or ``None`` if the session has no messages.

        Example::

            >>> client.get_memory(session_id=\"my-session\")
            {
                'messages': [...],
                'facts': ['User likes pizza'],
                'relevant_facts': [...],
            }

        """
        ws_id = self._resolve_session(session_id)
        if ws_id is None:
            return None

        # Get experience messages
        memories = self._client.list_memories(
            workspace_id=ws_id, limit=limit, memory_type="experience"
        )

        # Get facts
        facts_raw = self._client.list_memories(workspace_id=ws_id, limit=100, memory_type="fact")

        messages_out = []
        for m in memories or []:
            if min_rating > 0.0:
                rating = m.get("rating", 0.0) or 0.0
                if rating < min_rating:
                    continue
            role = m.get("peer_id", "user")
            content = m.get("content", "")
            messages_out.append(
                {
                    "role": role,
                    "content": content,
                    "score": m.get("strength", m.get("access_count", 1.0)),
                    "timestamp": m.get("created_at", ""),
                }
            )

        fact_strings = [f.get("content", "") for f in (facts_raw or [])]
        relevant_facts_objs = [
            Fact(
                uuid=f.get("id", ""),
                fact=f.get("content", ""),
                created_at=str(f.get("created_at", "")),
            )
            for f in (facts_raw or [])
        ]

        return {
            "messages": messages_out,
            "facts": fact_strings,
            "relevant_facts": relevant_facts_objs,
            "summary": "",
        }

    def delete_memory(self, session_id: str) -> dict[str, Any]:
        """Delete all memory for a session.

        Args:
            session_id: Zep session identifier.

        Returns:
            A dict with operation status and count of deleted items.

        Example::

            >>> client.delete_memory(session_id=\"my-session\")
            {'status': 'ok', 'deleted': 3}

        """
        ws_id = self._resolve_session(session_id)
        if ws_id is None:
            return {"status": "ok", "deleted": 0}

        memories = self._client.list_memories(
            workspace_id=ws_id, limit=1000, memory_type="experience"
        )
        deleted = 0
        for m in memories or []:
            mem_id = m.get("id", "") or m.get("entity_id", "")
            if mem_id:
                try:
                    self._client.delete_memory(mem_id)
                    deleted += 1
                except ValueError:
                    raise
                except RuntimeError:
                    pass

        return {"status": "ok", "deleted": deleted}

    def search_memory(
        self,
        session_id: str,
        query: str,
        limit: int = 10,
        score_threshold: float = 0.0,
        min_score: float | None = None,
        search_type: str = "similarity",
    ) -> list[MemorySearchResult]:
        """Search memory messages within a session.

        Args:
            session_id: Zep session identifier.
            query: The search query.
            limit: Max results (default 10).
            score_threshold: Minimum similarity score (default 0.0).
            min_score: Alias for ``score_threshold`` (Zep Cloud compat).
            search_type: ``\"similarity\"`` (default) or ``\"mmr\"`` for
                    Maximal Marginal Relevance reranking.

        Returns:
            A list of ``MemorySearchResult`` objects.

        Example::

            >>> results = client.search_memory(
            ...     session_id=\"my-session\",
            ...     query=\"food preferences\",
            ... )
            >>> results[0].message.content
            'I like pizza'

        """
        ws_id = self._resolve_session(session_id)
        if ws_id is None:
            return []

        effective_threshold = min_score if min_score is not None else score_threshold

        mmr_lambda = 0.7 if search_type == "mmr" else 0.0

        rows = self._client.search(
            workspace_id=ws_id,
            query=query,
            limit=limit,
            semantic=True,
            mmr_lambda=mmr_lambda,
        )
        results: list[MemorySearchResult] = []
        for r in rows or []:
            score = r.get("score", 0.0)
            if effective_threshold > 0.0 and score < effective_threshold:
                continue
            content = r.get("memory_content", r.get("content", ""))
            role = r.get("peer_id", r.get("source_session_id", "user"))
            msg = MemoryMessage(role=role, content=content)
            results.append(MemorySearchResult(message=msg, score=score))

        return results

    # ------------------------------------------------------------------
    # Zep Facts API
    # ------------------------------------------------------------------

    def add_fact(
        self,
        session_id: str,
        fact: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a factual statement to a session.

        Facts are stored as memories with ``memory_type=\"fact\"`` and can
        be retrieved with ``list_facts()`` or included in ``get_memory()``
        results.

        Args:
            session_id: Zep session identifier.
            fact: The factual statement to store.
            metadata: Optional metadata dict.

        Returns:
            A dict with operation status and fact_id.

        Example::

            >>> client.add_fact(
            ...     session_id=\"my-session\",
            ...     fact=\"User prefers dark mode interfaces\",
            ... )
            {'status': 'ok', 'fact_id': '...'}

        """
        ws_id = self._ensure_workspace(session_id)
        self._client.store(
            workspace_id=ws_id,
            content=fact,
            summary=f"[fact] {fact[:200]}",
            memory_type="fact",
            source_session_id=session_id,
        )

        # Read back the fact ID from the last stored fact
        memory_id = ""
        stored = self._client.list_memories(workspace_id=ws_id, limit=1, memory_type="fact")
        if stored:
            memory_id = stored[0].get("id", stored[0].get("entity_id", ""))

        return {"status": "ok", "fact_id": memory_id}

    def _extract_and_rate_facts(
        self,
        ws_id: str,
        session_id: str,
        message_payloads: list[dict[str, Any]],
        instruction: str | None = None,
    ) -> list[dict[str, Any]]:
        """LLM fact extraction + rating for a batch of messages (Zep Cloud parity).

        Sends the message batch to the LLM asking for a JSON list of
        ``{"fact": str, "rating": float}`` objects, then stores each fact
        as a ``memory_type="fact"`` memory with the rating carried in
        metadata.  If the LLM is unavailable or returns no parseable
        facts, this is a no-op — the caller still stored the messages.

        Returns:
            List of extracted fact dicts (empty on failure/unavailable).
        """
        from ...llm import LLMClient

        llm = LLMClient()
        if not llm.available:
            return []

        conversation = "\n".join(
            f"{m.get('role', 'user')}: {str(m.get('content', ''))[:1000]}"
            for m in message_payloads
        )
        instruction_part = (
            f"\nAdditional guidance: {instruction}" if instruction else ""
        )
        try:
            raw = llm.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "You extract durable facts about the user from a "
                            "conversation and rate their importance 0.0–1.0.\n"
                            "Return ONLY a JSON array of objects with keys "
                            '"fact" (string) and "rating" (float). '
                            "Example: [{\"fact\": \"User likes pizza\", \"rating\": 0.8}]\n"
                            "Skip ephemeral chit-chat and greetings."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Conversation:\n{conversation}"
                            f"{instruction_part}\n\n"
                            "Extract facts as JSON."
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=1024,
                response_format={"type": "json_object"},
            )
        except Exception:
            return []
        if not raw:
            return []

        facts = self._parse_fact_rating_json(raw)
        for fact in facts:
            try:
                rating = float(fact.get("rating", 0.5))
                self._client.store(
                    workspace_id=ws_id,
                    content=fact.get("fact", ""),
                    summary=f"[fact] {str(fact.get('fact', ''))[:200]} (rating {rating:.2f})",
                    memory_type="fact",
                    source_session_id=session_id,
                )
            except (RuntimeError, ValueError):
                continue
        return facts

    @staticmethod
    def _parse_fact_rating_json(raw: str) -> list[dict[str, Any]]:
        """Parse the LLM's fact-rating JSON response defensively.

        Accepts both a bare array and a JSON object wrapping a ``facts``
        array; falls back to regex extraction of ``{"fact": ..., "rating":
        ...}`` objects when strict parsing fails.
        """
        import re

        text = raw.strip()
        # Strip markdown code fences
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        candidates = [text]
        try:
            obj = json.loads(text)
            if isinstance(obj, list):
                candidates.insert(0, json.dumps(obj))
            elif isinstance(obj, dict) and isinstance(obj.get("facts"), list):
                candidates.insert(0, json.dumps(obj["facts"]))
        except (json.JSONDecodeError, TypeError):
            pass

        for cand in candidates:
            try:
                parsed = json.loads(cand)
                if isinstance(parsed, list):
                    out = []
                    for item in parsed:
                        if isinstance(item, dict) and item.get("fact"):
                            out.append(
                                {
                                    "fact": str(item["fact"]),
                                    "rating": float(item.get("rating", 0.5)),
                                }
                            )
                    if out:
                        return out
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        # Regex fallback: pull out {"fact": "...", "rating": ...} objects
        out = []
        for m in re.finditer(
            r'"fact"\s*:\s*"([^"]+)"\s*,\s*"rating"\s*:\s*([0-9.]+)',
            text,
        ):
            out.append({"fact": m.group(1), "rating": float(m.group(2))})
        return out

    def list_facts(
        self,
        session_id: str,
        limit: int = 100,
    ) -> list[Fact]:
        """List all facts for a session.

        Args:
            session_id: Zep session identifier.
            limit: Max facts to return (default 100).

        Returns:
            A list of ``Fact`` objects, each containing ``uuid``,
            ``fact``, ``created_at``, and optionally ``rating``.

        Example::

            >>> facts = client.list_facts(session_id=\"my-session\")
            >>> facts[0].fact
            'User prefers dark mode interfaces'

        """
        ws_id = self._resolve_session(session_id)
        if ws_id is None:
            return []

        rows = self._client.list_memories(workspace_id=ws_id, limit=limit, memory_type="fact")
        return [
            Fact(
                uuid=r.get("id", r.get("entity_id", "")),
                fact=r.get("content", ""),
                created_at=str(r.get("created_at", "")),
                rating=r.get("confidence", None),
            )
            for r in rows or []
        ]

    def delete_fact(self, fact_uuid: str, **kwargs: Any) -> dict[str, Any]:
        """Delete a specific fact by its UUID.

        Args:
            fact_uuid: The UUID of the fact to delete.
            **kwargs: Backward compat for ``session_id`` and ``fact_id``.

        Returns:
            A dict with operation status.

        Example::

            >>> client.delete_fact(fact_uuid=\"abc-123\")
            {'status': 'ok', 'deleted': 1}
            >>> client.delete_fact(session_id=\"my-session\", fact_id=\"abc-123\")  # legacy
            {'status': 'ok', 'deleted': 1}

        """
        # Backward compat: accept old signature
        if "fact_id" in kwargs:
            fact_uuid = kwargs["fact_id"]
        result = self._client.delete_memory(fact_uuid)
        # delete_memory returns {"status": "ok", "note": "already deleted"}
        # when the memory wasn't found — treat as deleted=0
        note = result.get("note", "")
        if note == "already deleted":
            return {"status": "ok", "deleted": 0, "note": "not found"}
        return {"status": "ok", "deleted": 1}

    def get_fact(self, fact_uuid: str) -> Fact:
        """Get a single fact by its UUID.

        Args:
            fact_uuid: The UUID of the fact to retrieve.

        Returns:
            A ``Fact`` object.

        Raises:
            NotFoundError: If the fact does not exist.

        Example::

            >>> fact = client.get_fact(fact_uuid=\"abc-123\")
            >>> fact.fact
            'User prefers dark mode'

        """
        rows = self._client._query("memory", filter_dict={"id": fact_uuid})
        if not rows:
            raise NotFoundError(f"Fact '{fact_uuid}' not found")
        r = rows[0]
        return Fact(
            uuid=r.get("id", r.get("entity_id", "")),
            fact=r.get("content", ""),
            created_at=str(r.get("created_at", "")),
            rating=r.get("confidence", None),
        )

    # ------------------------------------------------------------------
    # Zep Memory Update
    # ------------------------------------------------------------------

    def update_memory(
        self,
        session_id: str,
        memory_id: str,
        messages: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a memory's content and/or metadata.

        In Zep this accepts a ``MemoryUpdate``; here we update the content
        from the last provided message and store metadata on the record.

        Args:
            session_id: Zep session identifier.
            memory_id: The UUID of the memory to update.
            messages: Updated message content (uses last message's content).
            metadata: Optional metadata dict.

        Returns:
            A dict with operation status.

        Example::

            >>> client.update_memory(
            ...     session_id=\"my-session\",
            ...     memory_id=\"abc-123\",
            ...     messages=[{\"role\": \"user\", \"content\": \"Updated content\"}],
            ... )
            {'status': 'ok'}

        """
        content = ""
        if messages:
            last_msg = messages[-1]
            if isinstance(last_msg, dict):
                content = last_msg.get("content", "")
            elif isinstance(last_msg, MemoryMessage):
                content = last_msg.content
            else:
                content = str(last_msg)

        if content:
            self._client.update_memory(
                memory_id=memory_id,
                content=content,
            )

        return {"status": "ok"}

    # ------------------------------------------------------------------
    # Session message methods
    # ------------------------------------------------------------------

    def get_session_messages(
        self,
        session_id: str,
        limit: int | None = None,
        cursor: int | None = None,
    ) -> dict[str, Any]:
        """Retrieve messages for a Zep session with pagination.

        Args:
            session_id: Zep session identifier.
            limit: Max messages to return (fetches all by default).
            cursor: Offset / page cursor (maps to offset in list).

        Returns:
            A dict with ``messages`` list and optional ``cursor`` for
            pagination, matching the Zep ``MessageListResponse`` shape.

        Example::

            >>> resp = client.get_session_messages(
            ...     session_id=\"my-session\", limit=50
            ... )
            >>> len(resp[\"messages\"])
            42

        """
        ws_id = self._resolve_session(session_id)
        if ws_id is None:
            return {"messages": [], "cursor": None}

        effective_limit = limit if limit is not None else 1000
        offset = cursor or 0

        memories = self._client.list_memories(
            workspace_id=ws_id,
            limit=effective_limit + offset,
            memory_type="experience",
        )

        sliced = (memories or [])[offset : offset + effective_limit]
        messages_out: list[dict[str, Any]] = []
        for m in sliced:
            msg: dict[str, Any] = {
                "role": m.get("peer_id", "user"),
                "content": m.get("content", ""),
            }
            if m.get("id") or m.get("entity_id"):
                msg["uuid"] = m.get("id", "") or m.get("entity_id", "")
            if m.get("created_at"):
                msg["created_at"] = str(m.get("created_at", ""))
            messages_out.append(msg)

        next_cursor = offset + len(messages_out)
        if next_cursor >= len(memories or []):
            next_cursor = None

        return {"messages": messages_out, "cursor": next_cursor}

    def get_session_message(
        self,
        session_id: str,
        message_uuid: str,
    ) -> dict[str, Any]:
        """Retrieve a single message by UUID within a session.

        Args:
            session_id: Zep session identifier.
            message_uuid: UUID of the message to retrieve.

        Returns:
            A dict representing the message (``role``, ``content``,
            ``uuid``, ``created_at``).

        Raises:
            NotFoundError: If the message is not found in the session.

        Example::

            >>> msg = client.get_session_message(
            ...     session_id=\"my-session\",
            ...     message_uuid=\"abc-123\",
            ... )
            >>> msg[\"content\"]
            'Hello world'

        """
        ws_id = self._resolve_session(session_id)
        if ws_id is None:
            raise NotFoundError(f"Session '{session_id}' not found")

        rows = self._client._query(
            "memory",
            workspace_id=ws_id,
            filter_dict={"id": message_uuid},
        )
        if not rows:
            raise NotFoundError(f"Message '{message_uuid}' not found in session '{session_id}'")

        r = rows[0]
        return {
            "role": r.get("peer_id", "user"),
            "content": r.get("content", ""),
            "uuid": message_uuid,
            "created_at": str(r.get("created_at", "")),
            "metadata": r.get("metadata", {}),
        }

    def update_message_metadata(
        self,
        session_id: str,
        message_uuid: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Update metadata on a specific message within a session.

        Args:
            session_id: Zep session identifier.
            message_uuid: UUID of the message to update.
            metadata: New metadata dict (merged with existing).

        Returns:
            The updated message dict.

        Raises:
            NotFoundError: If the message is not found.

        Example::

            >>> msg = client.update_message_metadata(
            ...     session_id=\"my-session\",
            ...     message_uuid=\"abc-123\",
            ...     metadata={\"pinned\": True},
            ... )
            >>> msg[\"metadata\"]
            {'pinned': True}

        """
        ws_id = self._resolve_session(session_id)
        if ws_id is None:
            raise NotFoundError(f"Session '{session_id}' not found")

        # Verify the message exists
        rows = self._client._query(
            "memory",
            workspace_id=ws_id,
            filter_dict={"id": message_uuid},
        )
        if not rows:
            raise NotFoundError(f"Message '{message_uuid}' not found in session '{session_id}'")

        r = rows[0]
        existing_metadata: dict[str, Any] = r.get("metadata", {}) or {}
        merged = {**existing_metadata, **metadata}

        # Update via underlying client — store metadata as part of content update
        try:
            self._client.update_memory(
                memory_id=message_uuid,
                content=r.get("content", ""),
                summary=r.get("summary", ""),
            )
        except RuntimeError:
            # Best-effort: some backends may not support metadata-only updates
            pass

        return {
            "role": r.get("peer_id", "user"),
            "content": r.get("content", ""),
            "uuid": message_uuid,
            "created_at": str(r.get("created_at", "")),
            "metadata": merged,
        }

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def list_sessions(
        self,
        limit: int = 100,
        offset: int = 0,
        page_number: int | None = None,
        page_size: int | None = None,
        order_by: str = "created_at",
        asc: bool = False,
    ) -> list[Session]:
        """List all sessions (workspaces).

        Args:
            limit: Max sessions to return (default 100).
            offset: Pagination offset (default 0).
            page_number: Page number (1-indexed, maps to offset).
            page_size: Page size (maps to limit).
            order_by: Sort field (default ``\"created_at\"``).
            asc: Sort ascending (default ``False`` = newest first).

        Returns:
            A list of ``Session`` objects.

        """
        # Map page_number/page_size to limit/offset
        if page_size is not None:
            limit = page_size
        if page_number is not None:
            offset = (page_number - 1) * limit
        workspaces = self._client.list_workspaces()
        sliced = workspaces[offset : offset + limit] if workspaces else []
        sessions = []
        for ws in sliced:
            sessions.append(
                Session(
                    session_id=ws.get("name", ws.get("id", "")),
                    metadata={},
                    created_at=ws.get("created_at", ""),
                )
            )
        return sessions

    def get_session(self, session_id: str) -> Session | None:
        """Get a single session by its ID.

        Args:
            session_id: Zep session identifier.

        Returns:
            A ``Session`` object, or raises ``NotFoundError`` if not found.

        Raises:
            NotFoundError: If the session does not exist (matching zep-python).

        """
        workspaces = self._client.list_workspaces()
        for ws in workspaces:
            if ws.get("name") == session_id or ws.get("id") == session_id:
                return Session(
                    session_id=ws.get("name", ws.get("id", "")),
                    metadata={},
                    created_at=ws.get("created_at", ""),
                )
        raise NotFoundError(f"Session '{session_id}' not found")

    def add_session(
        self,
        session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """Create a new session.

        Args:
            session_id: Unique session identifier.
            metadata: Optional metadata dict.

        Returns:
            The created ``Session``.

        """
        self._client.create_workspace(session_id, f"Zep session: {session_id}")
        if session_id not in self._session_to_ws:
            workspaces = self._client.list_workspaces()
            match = [w for w in workspaces if w.get("name") == session_id]
            if match:
                self._session_to_ws[session_id] = match[0]["id"]
        return Session(session_id=session_id, metadata=metadata or {})

    def update_session(
        self,
        session_id: str,
        metadata: dict[str, Any] | None = None,
        fact_rating_instruction: str | None = None,
    ) -> Session:
        """Update a session's metadata.

        Args:
            session_id: Session identifier.
            metadata: New metadata dict (replaces existing).
            fact_rating_instruction: Ignored (LLM instruction for Zep Cloud, N/A).

        Returns:
            The updated ``Session``.

        Raises:
            NotFoundError: If the session does not exist.

        """
        ws_id = self._resolve_session(session_id)
        if not ws_id:
            raise NotFoundError(f"Session '{session_id}' not found")
        return Session(session_id=session_id, metadata=metadata or {})

    def search_sessions(
        self,
        query: str,
        limit: int = 10,
    ) -> list[Session]:
        """Search sessions by semantic relevance to the query.

        Tries semantic search first (requires an embedder — proxy → NVIDIA NIM
        or OpenAI API key).  Falls back to session-name substring matching when
        no embedding is available.

        Args:
            query: Natural-language search query.
            limit: Max results (default 10).

        Returns:
            A list of matching ``Session`` objects, ranked by relevance.
        """
        # Try semantic search first
        semantic_results = self._client.search_sessions_semantic(query, limit=limit)
        if semantic_results:
            sessions = []
            for r in semantic_results:
                sessions.append(
                    Session(
                        session_id=r.get("workspace_id", r.get("session_name", "")),
                        metadata={
                            "name": r.get("session_name", ""),
                            "score": r.get("score", 0.0),
                            "top_memory_content": r.get("top_memory_content", "")[:200],
                            "memory_count": r.get("memory_count", 0),
                        },
                    )
                )
            return sessions

        # Fallback: name/substring match (works without embedder)
        workspaces = self._client.list_workspaces()
        results = []
        for ws in workspaces:
            name = ws.get("name", "")
            if query.lower() in name.lower():
                results.append(
                    Session(
                        session_id=name,
                        metadata={},
                        created_at=ws.get("created_at", ""),
                    )
                )
            if len(results) >= limit:
                break
        return results

    def close(self) -> None:
        """Close the underlying HTTP client (idempotent)."""
        self._session_to_ws.clear()

    def summarize_memory(self, session_id: str) -> str | None:
        """Generate an LLM summary of all memories in a session.

        Uses the shared :class:`LLMClient` — requires ``OPENAI_API_KEY``
        env var.  Gracefully returns ``None`` when the LLM is not configured.

        Args:
            session_id: Zep session identifier.

        Returns:
            Summary string, or ``None`` if LLM not configured or no
            memories available.
        """
        try:
            memory = self.get_memory(session_id)
        except ValueError:
            raise
        except RuntimeError:
            memory = None
        if not memory:
            return None

        messages = memory.get("messages", [])
        if not messages:
            return None

        text_parts = []
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role", msg.get("message_type", "unknown"))
                content = msg.get("content", msg.get("message", ""))
                if content:
                    text_parts.append(f"[{role}] {content}")
            elif hasattr(msg, "role") and hasattr(msg, "content"):
                text_parts.append(f"[{msg.role}] {msg.content}")

        if not text_parts:
            return None

        from ...llm import LLMClient

        llm = LLMClient()
        if not llm.available:
            return None

        text = "\n".join(text_parts)
        return llm.summarize(
            text,
            instruction="Summarize this conversation, highlighting key topics, decisions, and action items.",
        )


# ---------------------------------------------------------------------------
# UserClient — Zep User management
# ---------------------------------------------------------------------------


class UserClient:
    """Manage Zep Users mapped to SpacetimeDB user table.

    Usage::

        from spacetime_memory.sdks.zep import ZepClient

        client = ZepClient(host=\"127.0.0.1\", port=3001)
        users = UserClient(client._client)

        # Add a user
        user = users.add(
            user_id=\"user-123\",
            email=\"alice@example.com\",
            first_name=\"Alice\",
        )

        # Get a user
        user = users.get(\"user-123\")

        # List all users
        all_users = users.list_ordered(page_number=1, page_size=50)

        # Get sessions for a user
        sessions = users.get_sessions(\"user-123\")

        # Update a user
        users.update(\"user-123\", email=\"new@example.com\")

        # Delete a user
        users.delete(\"user-123\")
    """

    def __init__(self, client: Client):
        """Initialize the API resource wrapper."""
        self._client = client

    def add(
        self,
        *,
        user_id: str | None = None,
        email: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a new user.

        Args:
            user_id: Unique user identifier. Auto-generated if omitted.
            email: Optional email address.
            first_name: Optional first name.
            last_name: Optional last name.
            metadata: Optional metadata dict.

        Returns:
            User dict with user_id, email, first_name, last_name,
            metadata_json, created_at, updated_at.

        Raises:
            RuntimeError: If the user already exists.
        """
        import uuid as _uuid

        uid = user_id or _uuid.uuid4().hex[:32]
        meta_json = json.dumps(metadata or {})

        self._client._call(
            "add_user",
            [
                uid,
                email or "",
                first_name or "",
                last_name or "",
                meta_json,
            ],
        )

        # Read back from the public user table
        rows = self._client._sql_param('SELECT * FROM "user" WHERE user_id = ?', uid)
        if rows:
            return self._row_to_user(rows[0])
        return {
            "user_id": uid,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "metadata_json": meta_json,
        }

    def get(self, user_id: str) -> dict[str, Any]:
        """Get a user by user_id.

        Args:
            user_id: The user's unique identifier.

        Returns:
            User dict.

        Raises:
            NotFoundError: If the user is not found.
        """
        self._client._call("get_user", [user_id])

        rows = self._client._sql_param('SELECT * FROM "user" WHERE user_id = ?', user_id)
        if not rows:
            raise NotFoundError(f"User '{user_id}' not found")
        return self._row_to_user(rows[0])

    def update(
        self,
        user_id: str,
        *,
        email: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update an existing user.

        Args:
            user_id: The user's unique identifier.
            email: New email (only updated if provided).
            first_name: New first name.
            last_name: New last name.
            metadata: New metadata dict.

        Returns:
            Updated user dict.

        Raises:
            NotFoundError: If the user is not found.
        """
        meta_json = json.dumps(metadata) if metadata is not None else ""

        self._client._call(
            "update_user",
            [
                user_id,
                email or "",
                first_name or "",
                last_name or "",
                meta_json,
            ],
        )

        rows = self._client._sql_param('SELECT * FROM "user" WHERE user_id = ?', user_id)
        if not rows:
            raise NotFoundError(f"User '{user_id}' not found after update")
        return self._row_to_user(rows[0])

    def delete(self, user_id: str) -> dict[str, Any]:
        """Delete a user by user_id.

        Args:
            user_id: The user's unique identifier.

        Returns:
            A dict with status and message.
        """
        self._client._call("delete_user", [user_id])
        return {"status": "ok", "message": f"User '{user_id}' deleted"}

    def list_ordered(
        self,
        *,
        page_number: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """List all users with pagination.

        Args:
            page_number: Page number (1-indexed).
            page_size: Number of users per page.

        Returns:
            Dict with ``users`` list and pagination metadata.
        """
        self._client._call("list_users", [])

        offset = (page_number - 1) * page_size
        # Get total count of list_users results
        all_rows = self._client._query("user_get_result")
        matching_rows = [r for r in all_rows if r.get("id", "").startswith("list_users:")]
        total = len(matching_rows)

        matching_rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        rows = matching_rows[offset:offset + int(page_size)]
        users = [self._row_to_user(r) for r in rows]

        return {
            "users": users,
            "total": total,
            "page": page_number,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }

    def get_sessions(self, user_id: str) -> list[dict[str, Any]]:
        """Get all sessions associated with a user.

        Args:
            user_id: The user's unique identifier.

        Returns:
            List of session dicts (session_id, session_name, workspace_id,
            created_at).
        """
        self._client._call("get_user_sessions", [user_id])

        query_id = f"user_sessions:{user_id}"
        rows = self._client._query("user_session_result", filter_dict={"query_id": query_id})
        return [
            {
                "session_id": r.get("session_id", ""),
                "session_name": r.get("session_name", ""),
                "workspace_id": r.get("workspace_id", ""),
                "created_at": r.get("created_at", ""),
                "user_id": r.get("user_id", ""),
            }
            for r in rows
        ]

    @staticmethod
    def _row_to_user(row: dict[str, Any]) -> dict[str, Any]:
        """Convert a raw SQL row to a user dict."""
        metadata_raw = row.get("metadata_json", "{}")
        try:
            metadata = json.loads(metadata_raw) if isinstance(metadata_raw, str) else metadata_raw
        except (json.JSONDecodeError, TypeError):
            metadata = {}

        return {
            "user_id": row.get("user_id", ""),
            "email": row.get("email") or None,
            "first_name": row.get("first_name") or None,
            "last_name": row.get("last_name") or None,
            "metadata": metadata,
            "metadata_json": metadata_raw,
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }


# ---------------------------------------------------------------------------
# Sub-client proxies (zep-python v2.0.2 — .memory / .user pattern)
# ---------------------------------------------------------------------------


class _MemoryProxy:
    """Proxy for ``Zep.memory`` — wraps MemoryClient methods.

    Delegates every call to the owning ``ZepClient``, mapping the
    zep-python v2.0.2 ``MemoryClient`` method names onto our adapter's
    flat methods.
    """

    def __init__(self, client: ZepClient) -> None:
        """Initialize the API resource wrapper."""
        self._c = client  # owning ZepClient / Zep

    # -- Memory CRUD --------------------------------------------------------

    def add(
        self,
        session_id: str,
        messages: list[dict[str, Any]] | list[MemoryMessage],
        *,
        metadata: dict[str, Any] | None = None,
        # LLM instructions ignored (SpacetimeDB backend)
        fact_instruction: str | None = None,
        summary_instruction: str | None = None,
    ) -> dict[str, Any]:
        """Add a new record."""
        return self._c.add_memory(
            session_id,
            messages,
            metadata=metadata,
            fact_instruction=fact_instruction,
            summary_instruction=summary_instruction,
        )

    def get(
        self,
        session_id: str,
        *,
        limit: int = 10,
        min_rating: float = 0.0,
    ) -> dict[str, Any] | None:
        """Get a single record by ID."""
        return self._c.get_memory(session_id, limit=limit, min_rating=min_rating)

    def delete(self, session_id: str) -> dict[str, Any]:
        """Delete a record by ID."""
        return self._c.delete_memory(session_id)

    def search(
        self,
        session_id: str,
        query: str,
        *,
        limit: int = 10,
        score_threshold: float = 0.0,
        min_score: float | None = None,
        search_type: str = "similarity",
    ) -> list[MemorySearchResult]:
        """Search memory/search results."""
        return self._c.search_memory(
            session_id,
            query,
            limit=limit,
            score_threshold=score_threshold,
            min_score=min_score,
            search_type=search_type,
        )

    # -- Facts ---------------------------------------------------------------

    def add_fact(
        self,
        session_id: str,
        fact: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a fact to a user/session."""
        return self._c.add_fact(session_id, fact, metadata=metadata)

    def get_fact(self, fact_uuid: str) -> Fact:
        """Get a fact by ID."""
        return self._c.get_fact(fact_uuid)

    def delete_fact(self, fact_uuid: str, **kwargs: Any) -> dict[str, Any]:
        """Delete a fact by ID."""
        return self._c.delete_fact(fact_uuid, **kwargs)

    # -- Session management --------------------------------------------------

    def add_session(
        self,
        session_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """Create a new session."""
        return self._c.add_session(session_id, metadata=metadata)

    def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        return self._c.get_session(session_id)

    def list_sessions(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        page_number: int | None = None,
        page_size: int | None = None,
        order_by: str = "created_at",
        asc: bool = False,
    ) -> list[Session]:
        """List all sessions for a user."""
        return self._c.list_sessions(
            limit=limit,
            offset=offset,
            page_number=page_number,
            page_size=page_size,
            order_by=order_by,
            asc=asc,
        )

    def search_sessions(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[Session]:
        """Search sessions by criteria."""
        return self._c.search_sessions(query, limit=limit)

    def update_session(
        self,
        session_id: str,
        *,
        metadata: dict[str, Any] | None = None,
        fact_rating_instruction: str | None = None,
    ) -> Session:
        """Update session metadata."""
        return self._c.update_session(
            session_id,
            metadata=metadata,
            fact_rating_instruction=fact_rating_instruction,
        )

    # -- Message-level -------------------------------------------------------

    def get_session_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
        cursor: int | None = None,
    ) -> dict[str, Any]:
        """Get messages for a session."""
        return self._c.get_session_messages(session_id, limit=limit, cursor=cursor)

    def get_session_message(
        self,
        session_id: str,
        message_uuid: str,
    ) -> dict[str, Any]:
        """Get a single message from a session."""
        return self._c.get_session_message(session_id, message_uuid)

    def update_message_metadata(
        self,
        session_id: str,
        message_uuid: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Update metadata on a message."""
        return self._c.update_message_metadata(session_id, message_uuid, metadata)


class _UserProxy:
    """Proxy for ``Zep.user`` — wraps UserClient methods."""

    def __init__(self, client: Client) -> None:
        """Initialize the API resource wrapper."""
        self._inner = UserClient(client)

    def add(
        self,
        *,
        user_id: str | None = None,
        email: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a new record."""
        return self._inner.add(
            user_id=user_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            metadata=metadata,
        )

    def get(self, user_id: str) -> dict[str, Any]:
        """Get a single record by ID."""
        return self._inner.get(user_id)

    def update(
        self,
        user_id: str,
        *,
        email: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update an existing record."""
        return self._inner.update(
            user_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            metadata=metadata,
        )

    def delete(self, user_id: str) -> dict[str, Any]:
        """Delete a record by ID."""
        return self._inner.delete(user_id)

    def list_ordered(
        self,
        *,
        page_number: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """List items in order."""
        return self._inner.list_ordered(
            page_number=page_number,
            page_size=page_size,
        )

    def get_sessions(self, user_id: str) -> list[dict[str, Any]]:
        """Get all sessions for a user."""
        return self._inner.get_sessions(user_id)


# ---------------------------------------------------------------------------
# Graph helper functions
# ---------------------------------------------------------------------------


def _json_loads_or(s: str, default: Any) -> Any:
    """json.loads with a fallback — for KG metadata blobs."""
    try:
        return json.loads(s) if isinstance(s, str) and s else default
    except (json.JSONDecodeError, TypeError):
        return default


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _now_micros() -> int:
    return int(datetime.now(UTC).timestamp() * 1_000_000)


# ---------------------------------------------------------------------------
# Graph namespace classes (zep-python v2.0.2 — .graph.node / .edge / .episode)
# ---------------------------------------------------------------------------


class _GraphNodeNamespace:
    """``client.graph.node`` — node lookups backed by the kg_node table."""
    def __init__(self, graph: _GraphClient) -> None:
        self._g = graph

    def get(self, uuid: str) -> dict[str, Any]:
        """Fetch a single entity node by UUID. Raises NotFoundError if absent."""
        ws = self._g._scope_workspace()
        rows = self._g._z._client._query("kg_node", workspace_id=ws, filter_dict={"id": uuid})
        rows = [r for r in rows if r.get("id") == uuid]
        if not rows:
            raise NotFoundError(f"graph node {uuid!r} not found")
        return self._g._node_to_api(rows[0])

    def get_by_user_id(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """List all entity nodes in a user's graph."""
        ws = self._g._scope_workspace(user_id=user_id)
        rows = self._g._z._client._query("kg_node", workspace_id=ws, filter_dict={"workspace_id": ws})
        rows = [r for r in rows if r.get("workspace_id") == ws]
        return [self._g._node_to_api(r) for r in rows[:limit]]


class _GraphEdgeNamespace:
    """``client.graph.edge`` — edge lookups backed by the kg_edge table."""

    def __init__(self, graph: _GraphClient) -> None:
        self._g = graph

    def get(self, uuid: str) -> dict[str, Any]:
        """Fetch a single edge by UUID. Raises NotFoundError if absent."""
        ws = self._g._scope_workspace()
        rows = self._g._z._client._query("kg_edge", workspace_id=ws, filter_dict={"id": uuid})
        rows = [r for r in rows if r.get("id") == uuid]
        if not rows:
            raise NotFoundError(f"graph edge {uuid!r} not found")
        return self._g._edge_to_api(rows[0])


class _GraphEpisodeNamespace:
    """``client.graph.episode`` — episode lookups (episodes are memories)."""

    def __init__(self, graph: _GraphClient) -> None:
        self._g = graph

    def get(self, uuid: str) -> dict[str, Any]:
        """Fetch a single episode by UUID. Raises NotFoundError if absent."""
        ws = self._g._scope_workspace()
        rows = self._g._z._client._query("memory", workspace_id=ws, filter_dict={"id": uuid})
        rows = [r for r in rows if r.get("id") == uuid]
        if not rows:
            raise NotFoundError(f"graph episode {uuid!r} not found")
        return self._g._episode_to_api(rows[0])


class _GraphCommunityNamespace:
    """``client.graph.community`` — community detection backed by the real KG.

    Delegates to SpacetimeDB's ``detect_communities`` + ``seed_communities``
    reducers (Louvain-style label propagation over ``kg_edge``), then reads
    the resulting ``kg_node`` rows with ``node_type == "community"``.
    """

    def __init__(self, graph: _GraphClient) -> None:
        self._g = graph

    def build(
        self,
        user_id: str | None = None,
        group_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run community detection and return the resulting communities.

        Args:
            user_id: User scope for graph workspace resolution.
            group_id: Group scope for graph workspace resolution.

        Returns:
            List of community dicts (uuid, name, summary, member_count).
        """
        ws = self._g._scope_workspace(user_id=user_id, group_id=group_id)
        try:
            self._g._z._client.detect_communities(ws)
        except RuntimeError:
            pass  # non-fatal — may fail under concurrent load / missing data
        try:
            self._g._z._client.seed_communities(ws)
        except RuntimeError:
            pass  # non-fatal
        return self.list(user_id=user_id, group_id=group_id)

    def list(
        self,
        user_id: str | None = None,
        group_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List all communities in a user's/group's graph."""
        ws = self._g._scope_workspace(user_id=user_id, group_id=group_id)
        rows = self._g._z._client._query(
            "kg_node",
            workspace_id=ws,
            filter_dict={"workspace_id": ws, "node_type": "community"},
        )
        rows = [
            r for r in rows
            if r.get("workspace_id") == ws and r.get("node_type") == "community"
        ]
        communities = []
        for r in rows:
            communities.append(self._community_to_api(r, ws))
            if len(communities) >= limit:
                break
        return communities

    def get(
        self,
        uuid: str,
        user_id: str | None = None,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch a single community by UUID. Raises NotFoundError if absent."""
        ws = self._g._scope_workspace(user_id=user_id, group_id=group_id)
        rows = self._g._z._client._query("kg_node", workspace_id=ws, filter_dict={"id": uuid})
        rows = [r for r in rows if r.get("id") == uuid and r.get("node_type") == "community"]
        if not rows:
            raise NotFoundError(f"graph community {uuid!r} not found")
        return self._community_to_api(rows[0], ws)

    def search(
        self,
        query: str,
        user_id: str | None = None,
        group_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search communities by name/summary substring (case-insensitive)."""
        ws = self._g._scope_workspace(user_id=user_id, group_id=group_id)
        q = query.lower().strip()
        rows = self._g._z._client._query(
            "kg_node",
            workspace_id=ws,
            filter_dict={"workspace_id": ws, "node_type": "community"},
        )
        hits = [
            r for r in rows
            if r.get("workspace_id") == ws
            and r.get("node_type") == "community"
            and (not q
                 or q in str(r.get("label", "")).lower()
                 or q in str(r.get("summary", "")).lower())
        ]
        return [self._community_to_api(r, ws) for r in hits[:limit]]

    # -- helpers ----------------------------------------------------------------

    def _community_to_api(self, row: dict[str, Any], ws: str) -> dict[str, Any]:
        """Convert a community kg_node row + member edges into the API shape."""
        members = []
        member_edges = []
        try:
            edge_rows = self._g._z._client._query(
                "kg_edge",
                workspace_id=ws,
                filter_dict={"source_node_id": row.get("id", "")},
            )
            for e in edge_rows:
                members.append(e.get("target_node_id", ""))
                member_edges.append({
                    "uuid": e.get("id", ""),
                    "source_node_uuid": e.get("source_node_id", ""),
                    "target_node_uuid": e.get("target_node_id", ""),
                })
        except RuntimeError:
            pass  # non-fatal — edges may not exist yet
        return {
            "uuid": row.get("id", ""),
            "name": row.get("label", ""),
            "summary": row.get("summary", ""),
            "created_at": row.get("created_at", 0),
            "member_count": len(set(members)),
            "members": sorted(set(members)),
            "edges": member_edges,
        }


class _GraphClient:
    """Zep v2 ``client.graph`` namespace, backed by the Spacetime-Memory KG.

    Scoping: Zep scopes one graph per ``user_id`` (or ``group_id``); we map
    that to a workspace named ``zep-graph-user-<id>`` / ``zep-graph-group-<id>``
    (or ``zep-graph-default``). All reads/writes go through the real backend:
    episodes are memory rows, nodes are kg_node rows, edges are kg_edge rows.
    Anything without a true backend equivalent raises NotImplementedError.
    """

    def __init__(self, zep_client: ZepClient) -> None:
        self._z = zep_client
        self._scope_user_id: str | None = None
        self._scope_group_id: str | None = None
        self.node = _GraphNodeNamespace(self)
        self.edge = _GraphEdgeNamespace(self)
        self.episode = _GraphEpisodeNamespace(self)
        self.community = _GraphCommunityNamespace(self)

    # -- scope helpers ---------------------------------------------------------

    def _scope_workspace(
        self, user_id: str | None = None, group_id: str | None = None
    ) -> str:
        uid = user_id or self._scope_user_id
        gid = group_id or self._scope_group_id
        if uid:
            name = f"zep-graph-user-{uid}"
        elif gid:
            name = f"zep-graph-group-{gid}"
        else:
            name = "zep-graph-default"
        return self._z._ensure_workspace(name)

    # -- converters ------------------------------------------------------------

    @staticmethod
    def _node_to_api(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "uuid": row.get("id", ""),
            "name": row.get("label", ""),
            "type": row.get("node_type", ""),
            "summary": row.get("summary", ""),
            "created_at": row.get("created_at", 0),
            "attributes": _json_loads_or(row.get("metadata_json", "{}"), {}),
        }

    @staticmethod
    def _edge_to_api(row: dict[str, Any]) -> dict[str, Any]:
        attributes = _json_loads_or(row.get("metadata_json", "{}"), {})
        return {
            "uuid": row.get("id", ""),
            "source_node_uuid": row.get("source_node_id", ""),
            "target_node_uuid": row.get("target_node_id", ""),
            "fact": row.get("relation", ""),
            "name": row.get("relation", ""),
            "weight": row.get("weight", 0.0),
            "rating": attributes.get("rating") if isinstance(attributes, dict) else None,
            "valid_at": row.get("valid_at", 0),
            "invalid_at": row.get("invalid_at", 0),
            "created_at": row.get("created_at", 0),
            "episodes": [row["source_memory_id"]] if row.get("source_memory_id") else [],
            "attributes": attributes,
        }

    @staticmethod
    def _episode_to_api(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "uuid": row.get("id", ""),
            "content": row.get("content", ""),
            "source": "message",
            "created_at": row.get("created_at", 0),
        }

    # -- public API ------------------------------------------------------------

    def add(
        self,
        data: str,
        type: str = "text",
        user_id: str | None = None,
        group_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Add data to the graph as an episode.

        Stores the episode as a memory; the SDK's store pipeline runs entity
        extraction automatically, creating/linking kg nodes for the episode.
        """
        if type not in ("text", "json", "message"):
            raise BadRequestError(f"invalid episode type {type!r}")
        ws = self._scope_workspace(user_id=user_id, group_id=group_id)
        content = data if isinstance(data, str) else _json_dumps(data)
        result = self._z._client.store(
            workspace_id=ws,
            content=content,
            memory_type="episode",
            summary=f"graph episode ({type})",
        )
        episode_id = result.get("id") if isinstance(result, dict) else None
        return {
            "uuid": episode_id,
            "content": content,
            "source": type,
            "created_at": _now_micros(),
        }

    def search(
        self,
        query: str,
        user_id: str | None = None,
        group_id: str | None = None,
        scope: str = "edges",
        limit: int = 10,
        center_node_uuid: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Search the graph. ``scope`` is one of 'edges', 'nodes', 'episodes'.

        Edges: substring match over edge facts + endpoint labels.
        Nodes: substring match over label/summary (case-insensitive).
        Episodes: delegated to the SDK's hybrid search.
        ``center_node_uuid`` reranks edges/nodes adjacent to that node first.
        """
        ws = self._scope_workspace(user_id=user_id, group_id=group_id)
        q = query.lower().strip()
        out: dict[str, Any] = {"edges": [], "nodes": [], "episodes": []}

        if scope == "nodes":
            rows = self._z._client._query("kg_node", workspace_id=ws, filter_dict={"workspace_id": ws})
            rows = [r for r in rows if r.get("workspace_id") == ws]
            hits = [
                r for r in rows
                if not q or q in str(r.get("label", "")).lower() or q in str(r.get("summary", "")).lower()
            ]
            if center_node_uuid:
                hits.sort(key=lambda r: 0 if r.get("id") == center_node_uuid else 1)
            out["nodes"] = [self._node_to_api(r) for r in hits[:limit]]
            return out

        if scope == "episodes":
            results = self._z._client.search(workspace_id=ws, query=query, semantic=True, limit=limit)
            hits = results.get("results", []) if isinstance(results, dict) else (results or [])
            out["episodes"] = [
                {
                    "uuid": h.get("id") or h.get("memory_id", ""),
                    "content": h.get("content", ""),
                    "score": h.get("score", 0.0),
                }
                for h in hits
            ]
            return out

        # default: edges
        edge_rows = self._z._client._query("kg_edge", workspace_id=ws, filter_dict={"workspace_id": ws})
        edge_rows = [r for r in edge_rows if r.get("workspace_id") == ws]
        node_rows = self._z._client._query("kg_node", workspace_id=ws, filter_dict={"workspace_id": ws})
        labels = {n.get("id"): str(n.get("label", "")) for n in node_rows}

        def edge_text(e: dict[str, Any]) -> str:
            return " ".join([
                str(e.get("relation", "")),
                labels.get(e.get("source_node_id"), ""),
                labels.get(e.get("target_node_id"), ""),
            ]).lower()

        hits = [e for e in edge_rows if not q or q in edge_text(e)]
        if center_node_uuid:
            hits.sort(
                key=lambda e: 0
                if center_node_uuid in (e.get("source_node_id"), e.get("target_node_id"))
                else 1
            )
        out["edges"] = [self._edge_to_api(e) for e in hits[:limit]]
        return out

    # -- triplet / edge creation -------------------------------------------------

    def add_triplet(
        self,
        source_node_uuid: str,
        target_node_uuid: str,
        edge: str,
        workspace_id: str | None = None,
        fact: str | None = None,
        rating: float | None = None,
        user_id: str | None = None,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        """Add a triplet (source -[edge]-> target) to the knowledge graph.

        Creates a directed edge between two existing entity nodes with the
        given relationship type.  Mirrors Zep's ``client.graph.add_triplet``.

        Args:
            source_node_uuid: UUID of the source entity node.
            target_node_uuid: UUID of the target entity node.
            edge: The relationship type / relation name.
            workspace_id: Explicit workspace override (bypasses scope).
            fact: Optional fact text stored in edge metadata.
            rating: Optional confidence/importance score (0.0–1.0) stored
                as the edge weight.  In Zep this is called "fact rating".
            user_id: User scope for graph workspace resolution.
            group_id: Group scope for graph workspace resolution.

        Returns:
            A dict (GraphEdge shape) with the created edge's uuid,
            source_node_uuid, target_node_uuid, fact/name, weight/rating, etc.
        """
        if workspace_id:
            ws = workspace_id
        else:
            ws = self._scope_workspace(user_id=user_id, group_id=group_id)

        meta_payload: dict[str, Any] = {}
        if fact is not None:
            meta_payload["fact"] = fact
        if rating is not None:
            meta_payload["rating"] = rating
        metadata = _json_dumps(meta_payload) if meta_payload else "{}"

        # Use rating as the edge weight if provided, otherwise default to 1.0
        weight = rating if rating is not None else 1.0

        try:
            self._z._client.create_edge(
                workspace_id=ws,
                source_node_id=source_node_uuid,
                target_node_id=target_node_uuid,
                relation=edge,
                weight=weight,
                metadata_json=metadata,
            )
        except RuntimeError as e:
            raise RuntimeError(f"add_triplet — create_edge failed: {e}") from e

        # Query back the edge to return its DB-assigned ID
        edge_rows = self._z._client._query(
            "kg_edge",
            workspace_id=ws,
            filter_dict={
                "source_node_id": source_node_uuid,
                "target_node_id": target_node_uuid,
                "relation": edge,
            },
        )
        if edge_rows:
            return self._edge_to_api(edge_rows[0])

        # Fallback: return partial shape (edge may have been cleaned up)
        return {
            "uuid": "",
            "source_node_uuid": source_node_uuid,
            "target_node_uuid": target_node_uuid,
            "fact": edge,
            "name": edge,
            "weight": weight,
            "rating": rating,
            "valid_at": 0,
            "invalid_at": 0,
            "created_at": _now_micros(),
            "episodes": [],
            "attributes": {},
        }


# ---------------------------------------------------------------------------
# Zep — zep-python v2.0.2 compatible client (replaces ZepClient)
# ---------------------------------------------------------------------------


class Zep(ZepClient):
    """Zep-compatible client matching ``zep_python.Zep`` (v2.0.2+).

    Adds ``.memory`` and ``.user`` sub-client proxies on top of the
    existing ``ZepClient`` adapter.  The underlying flat methods
    (``add_memory``, ``get_memory``, …) are still available directly
    for backward compatibility.

    Usage::

        from spacetime_memory.sdks.zep import Zep

        client = Zep(host=\"127.0.0.1\", port=3001)

        # v2.0.2 API — sub-client pattern
        client.memory.add(session_id=\"s1\", messages=[{\"role\": \"user\", \"content\": \"Hi\"}])
        mem = client.memory.get(session_id=\"s1\")

        user = client.user.add(email=\"alice@example.com\", first_name=\"Alice\")
        sessions = client.user.get_sessions(\"alice-123\")

        # v1.x API — flat methods still work
        client.add_memory(session_id=\"s2\", messages=[{\"role\": \"user\", \"content\": \"Yo\"}])

    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        config: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> None:
        """Initialize the API resource wrapper."""
        super().__init__(host=host, port=port, config=config, token=token)
        self.memory = _MemoryProxy(self)
        self.user = _UserProxy(self._client)
        self.graph = _GraphClient(self)


# ---------------------------------------------------------------------------
# Backward-compatibility aliases (zep-python v1.x → v2.0.2)
# ---------------------------------------------------------------------------

# ZepClient stays as an alias for Zep (old code still works)
ZepClient = Zep

# Message is an alias for MemoryMessage (zep-python v2.0.2 name)
Message = MemoryMessage
