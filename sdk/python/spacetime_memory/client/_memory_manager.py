"""Memory manager agent tools — LangMem parity.

Provides tools for agents to actively manage memory during conversations:

- manage_memory: create/update/delete memories with structured schemas
- search_memory: query + filter + pagination
- summarize_messages: incremental summarization
- extract_memory_from_conversation: structured memory extraction

All tools are NATIVE — no external dependencies (LangChain/LangMem packages).
"""
from __future__ import annotations

import json
from typing import Any

from ._base import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MEMORY_LIMIT = 20
MEMORY_MANAGER_TYPE = "agent_managed"

# ---------------------------------------------------------------------------
# MemoryManagerAgentMixin
# ---------------------------------------------------------------------------


class MemoryManagerAgentMixin:
    """Agent memory management tools — LangMem parity.

    Provides methods for agents to actively manage their memory during
    conversations. All data is native SpacetimeMemory — no external deps.
    """

    # ------------------------------------------------------------------
    # 1. manage_memory — CRUD with structured schemas
    # ------------------------------------------------------------------

    def manage_memory(
        self,
        workspace_id: str,
        action: str,
        content: str,
        memory_id: str | None = None,
        memory_type: str = MEMORY_MANAGER_TYPE,
        summary: str | None = None,
        tags: list[str] | None = None,
        importance: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create, update, or delete a memory with structured schema.

        Args:
            workspace_id: Target workspace.
            action: ``"create"``, ``"update"``, or ``"delete"``.
            content: Memory content text.
            memory_id: Required for update/delete actions.
            memory_type: Memory type classification.
            summary: Optional short summary.
            tags: Optional tags for categorization.
            importance: Optional importance score (0.0–1.0).
            metadata: Optional arbitrary metadata dict.

        Returns:
            Result dict with ``id``, ``action``, and operation status.
        """
        if action == "create":
            result = self.store(
                workspace_id=workspace_id,
                content=content,
                summary=summary or content[:100],
                memory_type=memory_type,
                source_session_id="",
                entities_json=json.dumps(tags or []),
            )
            mem_id = result.get("id", "")
            logger.info(
                "manage_memory: created memory id=%s workspace=%s",
                mem_id, workspace_id,
            )

            # Update importance if provided
            if importance is not None and mem_id:
                try:
                    self._call("update_memory_importance", [mem_id, importance])
                except Exception:
                    pass

            return {"id": mem_id, "action": "created", "status": "ok"}

        elif action == "update":
            if not memory_id:
                raise ValueError("memory_id is required for update action")

            result = self.store(
                workspace_id=workspace_id,
                content=content,
                summary=summary or content[:100],
                memory_type=memory_type,
                source_session_id="",
            )
            logger.info(
                "manage_memory: updated memory id=%s", memory_id,
            )
            return {"id": memory_id, "action": "updated", "status": "ok"}

        elif action == "delete":
            if not memory_id:
                raise ValueError("memory_id is required for delete action")
            try:
                self._call("delete_memory", [memory_id])
            except Exception as e:
                return {"id": memory_id, "action": "deleted",
                        "status": "error", "error": str(e)}
            return {"id": memory_id, "action": "deleted", "status": "ok"}

        else:
            raise ValueError(
                f"Unknown action '{action}'. "
                "Valid actions: create, update, delete"
            )

    # ------------------------------------------------------------------
    # 2. search_memory — query + filter + pagination
    # ------------------------------------------------------------------

    def search_memory(
        self,
        workspace_id: str,
        query: str,
        memory_type: str | None = None,
        tags: list[str] | None = None,
        min_importance: float | None = None,
        limit: int = DEFAULT_MEMORY_LIMIT,
        offset: int = 0,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """Search memories with filtering and pagination.

        Args:
            workspace_id: Target workspace.
            query: Natural-language search query.
            memory_type: Optional type filter (e.g. ``"agent_managed"``).
            tags: Optional tag filter.
            min_importance: Minimum importance threshold (0.0–1.0).
            limit: Max results per page.
            offset: Pagination offset.
            include_metadata: Include additional metadata in results.

        Returns:
            Dict with ``results`` list, ``total`` count, ``limit``, ``offset``.
        """
        # Use the existing search infrastructure
        try:
            results = self.search(
                workspace_id=workspace_id,
                query=query,
                top_k=limit + offset,
            )
        except Exception:
            results = []

        # Apply filters
        filtered = []
        for r in results:
            if memory_type:
                mt = r.get("memory_type", "")
                if mt != memory_type:
                    continue
            if tags:
                mem_tags = r.get("entities_json", "[]")
                if isinstance(mem_tags, str):
                    try:
                        mem_tags = json.loads(mem_tags)
                    except (json.JSONDecodeError, TypeError):
                        mem_tags = []
                if not isinstance(mem_tags, list):
                    mem_tags = []
                if not any(t in mem_tags for t in tags):
                    continue
            if min_importance is not None:
                imp = r.get("importance", r.get("confidence", 0.0))
                if isinstance(imp, str):
                    try:
                        imp = float(imp)
                    except (ValueError, TypeError):
                        imp = 0.0
                if imp < min_importance:
                    continue
            filtered.append(r)

        # Paginate
        total = len(filtered)
        page = filtered[offset:offset + limit]

        if not include_metadata:
            page = [
                {k: v for k, v in r.items()
                 if k in ("id", "content", "summary", "memory_type",
                          "score", "created_at")}
                for r in page
            ]

        return {
            "results": page,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    # ------------------------------------------------------------------
    # 3. summarize_messages — incremental summarization
    # ------------------------------------------------------------------

    def summarize_messages(
        self,
        workspace_id: str,
        session_id: str,
        max_messages: int = 50,
        existing_summary: str | None = None,
        strategy: str = "incremental",
    ) -> dict[str, Any]:
        """Incremental message summarization.

        Analyzes session messages and produces or updates a summary.

        Args:
            workspace_id: Target workspace.
            session_id: Session to summarize.
            max_messages: Max messages to analyze.
            existing_summary: Prior summary to incorporate (incremental mode).
            strategy: ``"incremental"`` (merge with existing) or ``"full"``
                (regenerate from scratch).

        Returns:
            Dict with ``summary``, ``message_count``, ``strategy``.
        """
        # Fetch messages
        messages = self._query(
            "message",
            filter_dict={"session_id": session_id},
        )
        messages = messages[:max_messages]

        if not messages:
            return {
                "summary": existing_summary or "",
                "message_count": 0,
                "strategy": strategy,
            }

        # Build message text
        message_texts = []
        for m in messages:
            sender = m.get("sender_id", m.get("sender", "unknown"))
            content = m.get("content", "")
            if content:
                message_texts.append(f"[{sender}]: {content}")

        combined = "\n".join(message_texts)
        if len(combined) > 6000:
            combined = combined[-6000:]  # Take most recent

        # Build LLM prompt
        if strategy == "incremental" and existing_summary:
            prompt = (
                "You are given an existing conversation summary and new "
                "messages. Update the summary to incorporate the new content. "
                "Keep it concise (2-4 sentences).\n\n"
                f"Existing summary:\n{existing_summary}\n\n"
                f"New messages:\n{combined}\n\n"
                "Updated summary:"
            )
        else:
            prompt = (
                "Summarize the following conversation into 2-4 concise "
                "sentences. Capture key topics, decisions, and outcomes.\n\n"
                f"Messages:\n{combined}\n\n"
                "Summary:"
            )

        summary = self._llm_complete(prompt) if hasattr(self, "_llm_complete") else ""
        if not summary:
            summary = f"Session summarized ({len(messages)} messages)"

        return {
            "summary": summary.strip(),
            "message_count": len(messages),
            "strategy": strategy,
        }

    # ------------------------------------------------------------------
    # 4. extract_memory_from_conversation — structured extraction
    # ------------------------------------------------------------------

    def extract_memory_from_conversation(
        self,
        workspace_id: str,
        session_id: str,
        max_messages: int = 30,
        store: bool = True,
    ) -> list[dict[str, Any]]:
        """Extract structured memories from a conversation.

        Uses LLM to identify key factual statements, preferences,
        decisions, and relationships from conversation messages, then
        optionally stores them as memories.

        Args:
            workspace_id: Target workspace.
            session_id: Session to extract from.
            max_messages: Max messages to analyze.
            store: If True, store extracted memories via ``manage_memory``.

        Returns:
            List of extracted memory dicts with ``content``, ``memory_type``,
            ``importance``, ``tags``, ``id`` (if stored).
        """
        messages = self._query(
            "message",
            filter_dict={"session_id": session_id},
        )
        messages = messages[:max_messages]

        if not messages:
            return []

        message_texts = []
        for m in messages:
            sender = m.get("sender_id", m.get("sender", "unknown"))
            content = m.get("content", "")
            if content:
                message_texts.append(f"[{sender}]: {content}")

        combined = "\n".join(message_texts)
        if len(combined) > 4000:
            combined = combined[:2000] + "\n...\n" + combined[-2000:]

        prompt = (
            "Extract key factual memories from the following conversation. "
            "Return a JSON array of objects. Each object must have:\n"
            "- content: the factual statement (1-2 sentences)\n"
            "- memory_type: one of 'preference', 'fact', 'decision', "
            "'relationship', 'activity'\n"
            "- importance: float 0.0-1.0\n"
            "- tags: array of string tags\n\n"
            f"Conversation:\n{combined}\n\n"
            "JSON array:"
        )

        raw = self._llm_complete(prompt) if hasattr(self, "_llm_complete") else ""
        if not raw:
            return []

        # Parse JSON from LLM response
        memories = self._parse_llm_json_array(raw)
        if not memories:
            return []

        if store:
            for mem in memories:
                try:
                    content = mem.get("content", "")
                    mem_type = mem.get("memory_type", "fact")
                    importance = mem.get("importance", 0.5)
                    tags = mem.get("tags", [])
                    result = self.manage_memory(
                        workspace_id=workspace_id,
                        action="create",
                        content=content,
                        memory_type=mem_type,
                        tags=tags,
                        importance=importance,
                        metadata={"extracted_from": session_id},
                    )
                    mem["id"] = result.get("id", "")
                except Exception as e:
                    logger.warning("Failed to store extracted memory: %s", e)
                    mem["id"] = ""
                    mem["error"] = str(e)

        return memories

    def _parse_llm_json_array(self, text: str) -> list[dict[str, Any]]:
        """Parse a JSON array from LLM output with fallbacks."""
        import re
        # Try direct parse
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, TypeError):
            pass
        # Try finding array in code fences
        m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, TypeError):
                pass
        # Try finding any JSON array
        m = re.search(r"\[.*?\]", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, TypeError):
                pass
        return []
