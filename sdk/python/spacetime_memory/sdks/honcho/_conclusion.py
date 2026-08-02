"""ConclusionScope class for the Honcho-compatible adapter.

Split from the monolithic ``honcho.py`` into a package.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from ...llm import LLMClient
from ._models import (
    Conclusion,
    ConclusionCreateParams,
    SyncPage,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ._honcho import Honcho
    from ._peer import Peer
    from ._session import Session


class ConclusionScope:
    """Scope for managing conclusions about an observed peer by an observer.

    Matches upstream ``honcho.ConclusionScope``.
    """

    def __init__(self, honcho: Honcho, observer: Peer, observed: Peer) -> None:
        """Initialize the store/reference."""
        self._honcho = honcho
        self.observer = observer
        self.observed = observed
        self.workspace_id = honcho._ws_id

    def list(
        self,
        page: int = 1,
        size: int = 50,
        session: Session | str | None = None,
        *,
        reverse: bool = False,
    ) -> SyncPage:
        """List conclusions matching the observer/observed scope."""
        from ._session import Session

        session_id = session.id if isinstance(session, Session) else session
        try:
            results = self._honcho._client.search(
                self.workspace_id,
                query="",
                limit=size * page,
                semantic=False,
            )
        except RuntimeError as exc:
            logger.warning("ConclusionScope.list() search failed: %s", exc)
            results = []

        conclusions: list[Conclusion] = []
        for r in results:
            meta = r.get("metadata", {})
            if meta.get("memory_type") != "conclusion":
                continue
            if meta.get("observer_id") != self.observer.id:
                continue
            if meta.get("observed_id") != self.observed.id:
                continue
            if session_id and meta.get("session_id") != session_id:
                continue
            conclusions.append(
                Conclusion(
                    id=r.get("id", ""),
                    content=r.get("memory_content", r.get("content", "")),
                    observer_id=meta.get("observer_id", self.observer.id),
                    observed_id=meta.get("observed_id", self.observed.id),
                    session_id=meta.get("session_id"),
                    created_at=r.get("created_at"),
                )
            )

        if reverse:
            conclusions = list(reversed(conclusions))

        start = (page - 1) * size
        paged = conclusions[start : start + size]
        return SyncPage(
            data={
                "items": paged,
                "total": len(conclusions),
                "page": page,
                "size": size,
                "pages": max(1, (len(conclusions) + size - 1) // size or 1),
            }
        )

    def query(
        self,
        query: str,
        top_k: int = 10,
        distance: float | None = None,
    ) -> list[Conclusion]:
        """Semantic search for conclusions."""
        try:
            results = self._honcho._client.search(
                self.workspace_id,
                query=query,
                limit=top_k,
                semantic=True,
            )
        except RuntimeError as exc:
            logger.warning("ConclusionScope.query() search failed: %s", exc)
            results = []

        conclusions: list[Conclusion] = []
        for r in results[:top_k]:
            meta = r.get("metadata", {})
            if meta.get("memory_type") != "conclusion":
                continue
            if meta.get("observer_id") != self.observer.id:
                continue
            if meta.get("observed_id") != self.observed.id:
                continue
            conclusions.append(
                Conclusion(
                    id=r.get("id", ""),
                    content=r.get("memory_content", r.get("content", "")),
                    observer_id=meta.get("observer_id", self.observer.id),
                    observed_id=meta.get("observed_id", self.observed.id),
                    session_id=meta.get("session_id"),
                    created_at=r.get("created_at"),
                )
            )
        return conclusions

    def delete(self, conclusion_id: str) -> None:
        """Delete a conclusion by ID."""
        try:
            self._honcho._client._call("delete_memory", [conclusion_id])
        except RuntimeError as exc:
            logger.warning("ConclusionScope.delete() failed: %s", exc)

    def create(
        self,
        conclusions: list[ConclusionCreateParams | dict],
    ) -> list[Conclusion]:
        """Store conclusions as memory records."""
        result: list[Conclusion] = []
        for item in conclusions:
            if isinstance(item, dict):
                item = ConclusionCreateParams(**item)
            meta = {
                "memory_type": "conclusion",
                "observer_id": self.observer.id,
                "observed_id": self.observed.id,
                "session_id": item.session_id or "",
            }
            try:
                self._honcho._client.store(
                    self.workspace_id,
                    content=item.content,
                    summary="",
                    entities_json=json.dumps(meta),
                )
                result.append(
                    Conclusion(
                        id="",  # client doesn't have server-generated ID
                        content=item.content,
                        observer_id=self.observer.id,
                        observed_id=self.observed.id,
                        session_id=item.session_id,
                    )
                )
            except RuntimeError as exc:
                logger.warning("ConclusionScope.create() store failed: %s", exc)
        return result

    def representation(
        self,
        search_query: str | None = None,
        search_top_k: int | None = None,
        search_max_distance: float | None = None,
        include_most_frequent: int | None = None,
        max_conclusions: int | None = None,
    ) -> str:
        """Generate an LLM representation from conclusions."""
        conclusions = self.query(
            search_query or "",
            top_k=search_top_k or max_conclusions or 10,
            distance=search_max_distance,
        )
        if not conclusions:
            return f"No conclusions about {self.observed.id} by {self.observer.id}."

        llm = LLMClient()
        if not llm.available:
            content_parts = [c.content[:100] for c in conclusions[:5]]
            return f"Conclusions about {self.observed.id} by {self.observer.id}: " + "; ".join(
                content_parts
            )

        mem_text = "\n".join(f"- {c.content}" for c in conclusions[:10])
        prompt = (
            f"Synthesize a natural language representation from these conclusions "
            f"about '{self.observed.id}' made by '{self.observer.id}':\n\n"
            f"{mem_text or '(none)'}"
        )
        result_text = llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=512,
        )
        return result_text or f"Conclusions about {self.observed.id} by {self.observer.id}."

    @property
    def aio(self) -> ConclusionScopeAio:
        """Get the async I/O session for async operations."""
        return ConclusionScopeAio(self)


class ConclusionScopeAio:
    """Async wrapper for ConclusionScope."""

    def __init__(self, scope: ConclusionScope) -> None:
        """Initialize the store/reference."""
        self._scope = scope

    async def list(
        self,
        page: int = 1,
        size: int = 50,
        session: Session | str | None = None,
        *,
        reverse: bool = False,
    ) -> SyncPage:
        """List all items."""
        return await asyncio.to_thread(
            self._scope.list,
            page=page,
            size=size,
            session=session,
            reverse=reverse,
        )

    async def query(
        self,
        query: str,
        top_k: int = 10,
        distance: float | None = None,
    ) -> list[Conclusion]:
        """Query items by criteria."""
        return await asyncio.to_thread(
            self._scope.query,
            query,
            top_k=top_k,
            distance=distance,
        )

    async def delete(self, conclusion_id: str) -> None:
        """Delete this resource."""
        return await asyncio.to_thread(self._scope.delete, conclusion_id)

    async def create(
        self,
        conclusions: list[ConclusionCreateParams | dict],
    ) -> list[Conclusion]:
        """Create a new resource."""
        return await asyncio.to_thread(self._scope.create, conclusions)

    async def representation(
        self,
        search_query: str | None = None,
        search_top_k: int | None = None,
        search_max_distance: float | None = None,
        include_most_frequent: int | None = None,
        max_conclusions: int | None = None,
    ) -> str:
        """Get the data representation."""
        return await asyncio.to_thread(
            self._scope.representation,
            search_query=search_query,
            search_top_k=search_top_k,
            search_max_distance=search_max_distance,
            include_most_frequent=include_most_frequent,
            max_conclusions=max_conclusions,
        )


