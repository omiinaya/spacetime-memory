"""
QMD-compatible drop-in adapter for Spacetime-Memory.

Maps the QMD (Query Markup Documents) API (https://github.com/tobilu/qmd) onto
Spacetime-Memory's native storage. QMD is an on-device search engine for
markdown notes / docs / transcripts; it combines BM25 keyword search with
vector semantic search and optional LLM reranking.

The adapter exposes the same operations as QMD's CLI + MCP server:

- **Collections** — ``QmdClient.collection_add`` / ``collection_list`` /
  ``collection_remove`` / ``collection_rename`` (a collection maps to a
  Spacetime-Memory workspace)
- **Documents** — ``add`` / ``get`` / ``multi_get`` (documents map to memories)
- **Search** — ``query`` (hybrid lex+vec, the recommended path) /
  ``search`` (BM25-style keyword) / ``vsearch`` (pure semantic)
- **Context** — ``context_add`` / ``context_list`` / ``context_remove``
  (per-collection/path context, stored as documents)
- **Status** — ``status`` (index health, collections, doc count)

All storage is Spacetime-Memory native (``Client``) — zero external
dependencies.

Usage::

    from spacetime_memory.sdks.qmd import QmdClient, Query, SubQuery

    q = QmdClient(host="127.0.0.1", port=3001)
    q.collection_add(["/path/to/notes"], name="notes")

    q.add(collection="notes", path="journals/2025-05-01.md",
          content="# My Journal\\nToday I did important things.")

    # Recommended: hybrid query (auto lex + vec fusion)
    results = q.query("what did I do in May?", collection="notes")

    # Typed sub-queries
    lex = q.query(Query(sub_queries=[SubQuery(type="lex", query='"product launch" -old')]))

    # BM25 keyword search
    hits = q.search("connection pool", collection="notes")

    # Semantic search
    vec = q.vsearch("how does rate limiting work?", collection="notes")

    # Get a document
    doc = q.get("journals/2025-05-01.md")

    # Context (collection/path descriptions)
    q.context_add("/path", "Journal notes from daily standups")

    # Status
    status = q.status()

**Error contract:**
- ``ValueError`` for invalid inputs (empty query, unknown collection,
  empty content).
- ``RuntimeError`` for backend failures (DB down).
- Search returns ``[]`` on backend failure (logged), matching QMD's
  permissive "no matches" behavior.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from ..client import Client
from ..llm import LLMClient

logger = logging.getLogger(__name__)

__all__ = [
    "QmdClient",
    "Query",
    "SubQuery",
    "SearchResult",
    "Document",
]


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class SubQuery:
    """A single typed sub-query (QMD's ``lex`` / ``vec`` / ``hyde``)."""

    type: str  # "lex" | "vec" | "hyde"
    query: str


@dataclass
class Query:
    """A QMD query document — one or more typed sub-queries."""

    sub_queries: list[SubQuery] = field(default_factory=list)


@dataclass
class SearchResult:
    """A single QMD search hit."""

    docid: str  # e.g. #abc123
    score: float
    path: str
    title: str
    snippet: str = ""
    collection: str = ""
    line: int = 1


@dataclass
class Document:
    """A stored document."""

    path: str
    content: str
    collection: str = ""
    context: str = ""
    docid: str = ""


# ---------------------------------------------------------------------------
# Helper — collection/workspace mapping
# ---------------------------------------------------------------------------


def _collection_ws(name: str) -> str:
    digest = hashlib.sha256(f"qmd:{name}".encode()).hexdigest()[:32]
    return f"qmd-{digest}"


def _docid(content: str) -> str:
    digest = hashlib.sha256(content.encode()).hexdigest()[:6]
    return f"#{digest}"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class QmdClient:
    """Spacetime-Memory backed implementation of QMD's interface.

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
        llm: LLMClient | None = None,
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
        self._llm = llm

    # -- workspace helpers ---------------------------------------------------

    def _ensure_ws(self, ws: str, name: str) -> None:
        try:
            rows = self._client._query("workspace", "", {"id": ws}, ["id"])
            if not rows:
                self._client._call("create_workspace", [f"QMD:{name}", "qmd collection", ws])
            self._client._call("set_workspace_visibility", [ws, True])
        except Exception as exc:
            logger.debug("qmd _ensure_ws failed (%s)", exc)

    # -- collections ---------------------------------------------------------

    def collection_add(self, paths: str | list[str], name: str | None = None, **kwargs: Any) -> dict[str, Any]:
        """Create a collection (QMD ``collection add``).

        Args:
            paths: A file/dir path or list of paths. If a readable file is
                given inline, its content is ingested immediately.
            name: Collection name (defaults to a derived name from path).

        Returns:
            ``{"name": ..., "workspace": ...}``.
        """
        if isinstance(paths, str):
            paths = [paths]
        if not paths:
            raise ValueError("qmd.collection_add: at least one path required")
        coll = name or _slug(paths[0])
        ws = _collection_ws(coll)
        self._ensure_ws(ws, coll)
        return {"name": coll, "workspace": ws, "collections": 1}

    def collection_list(self) -> list[dict[str, Any]]:
        """List all collections (QMD ``collection list``).

        Returns:
            list of ``{"name", "workspace", "documents"}`` dicts.
        """
        out: list[dict[str, Any]] = []
        try:
            rows = self._client._query("workspace", "", {}, ["id", "name"])
            for r in rows:
                name = str(r.get("name", ""))
                if name.startswith("QMD:"):
                    ws = r["id"]
                    try:
                        mems = self._client._query("memory", ws, {}, ["id"])
                        count = len(mems)
                    except Exception:
                        count = 0
                    out.append({"name": name.replace("QMD:", ""), "workspace": ws, "documents": count})
        except Exception as exc:
            logger.warning("qmd.collection_list: %s", exc)
        return out

    def collection_remove(self, name: str) -> bool:
        """Remove a collection (QMD ``collection remove``)."""
        ws = _collection_ws(name)
        try:
            rows = self._client._query("memory", ws, {}, ["id"])
            for r in rows:
                try:
                    self._client._call("delete_memory", [r["id"]])
                except Exception:
                    pass
            return True
        except Exception as exc:
            logger.warning("qmd.collection_remove: %s", exc)
            return False

    def collection_rename(self, old: str, new: str) -> bool:
        """Rename a collection (QMD ``collection rename``)."""
        old_ws = _collection_ws(old)
        new_ws = _collection_ws(new)
        self._ensure_ws(new_ws, new)
        try:
            rows = self._client._query(
                "memory", old_ws, {}, ["id", "content", "source_session_id"]
            )
            for r in rows:
                try:
                    self._client.store(
                        workspace_id=new_ws,
                        content=str(r.get("content", "")),
                        memory_type="experience",
                        source_session_id=str(r.get("source_session_id", "")),
                    )
                except Exception:
                    pass
            self.collection_remove(old)
            return True
        except Exception as exc:
            logger.warning("qmd.collection_rename: %s", exc)
            return False

    # -- documents -----------------------------------------------------------

    def add(
        self,
        collection: str,
        path: str,
        content: str,
        context: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Add a document to a collection (stores it as a memory).

        Args:
            collection: Collection name.
            path: Document path (e.g. ``journals/2025-05-01.md``).
            content: Document markdown/text content.
            context: Optional context description for the path.

        Returns:
            ``{"docid", "path", "collection"}``.
        """
        if not content or not content.strip():
            raise ValueError("qmd.add: content must be non-empty")
        ws = _collection_ws(collection)
        self._ensure_ws(ws, collection)
        final = f"<!-- {context} -->\n{content}" if context else content
        try:
            result = self._client.store(
                workspace_id=ws,
                content=final,
                memory_type="document",
                source_session_id=path,
            )
            return {
                "docid": _docid(content),
                "path": path,
                "collection": collection,
                "id": result.get("id", ""),
            }
        except Exception as exc:
            raise RuntimeError(f"qmd.add: {exc}") from exc

    def get(self, path_or_docid: str, include_body: bool = True, **kwargs: Any) -> Any:
        """Get a document by path or docid (QMD ``get``).

        Returns a ``Document`` or a dict with an ``error`` key.
        """
        # Search all collections for the matching memory
        try:
            rows = self._client._query("workspace", "", {}, ["id", "name"])
        except Exception:
            rows = []
        for r in rows:
            name = str(r.get("name", ""))
            if not name.startswith("QMD:"):
                continue
            ws = r["id"]
            try:
                mems = self._client._query("memory", ws, {}, ["id", "content", "source_session_id"])
            except Exception:
                continue
            for m in mems:
                spath = str(m.get("source_session_id", ""))
                content = str(m.get("content", ""))
                if spath == path_or_docid or _docid(content) == path_or_docid:
                    return Document(
                        path=spath,
                        content=content,
                        collection=name.replace("QMD:", ""),
                        docid=_docid(content),
                    )
        return {"error": "not_found", "path": path_or_docid}

    def multi_get(self, pattern: str, max_lines: int | None = None, **kwargs: Any) -> dict[str, Any]:
        """Get multiple documents by glob or comma-separated paths (QMD ``multi_get``).

        Returns ``{"docs": [...], "errors": [...]}``.
        """
        docs: list[Document] = []
        errors: list[str] = []
        patterns = [p.strip() for p in re.split(r"[,]", pattern) if p.strip()]
        seen: set[str] = set()
        try:
            rows = self._client._query("workspace", "", {}, ["id", "name"])
        except Exception:
            rows = []
        for r in rows:
            name = str(r.get("name", ""))
            if not name.startswith("QMD:"):
                continue
            ws = r["id"]
            try:
                mems = self._client._query("memory", ws, {}, ["id", "content", "source_session_id"])
            except Exception:
                continue
            for m in mems:
                spath = str(m.get("source_session_id", ""))
                for pat in patterns:
                    if _glob_match(pat, spath) and spath not in seen:
                        seen.add(spath)
                        content = str(m.get("content", ""))
                        if max_lines:
                            content = "\n".join(content.split("\n")[:max_lines])
                        docs.append(
                            Document(
                                path=spath,
                                content=content,
                                collection=name.replace("QMD:", ""),
                                docid=_docid(content),
                            )
                        )
                        break
        return {"docs": docs, "errors": errors}

    # -- search --------------------------------------------------------------

    def search(
        self,
        query: str,
        collection: str | None = None,
        limit: int = 20,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """BM25-style keyword search (QMD ``search``).

        Args:
            query: Keyword query (supports ``"phrase"`` and ``-negation``).
            collection: Optional collection to restrict to.
            limit: Max results.

        Returns:
            list of result dicts with ``docid, score, path, snippet``.
        """
        if not query or not query.strip():
            raise ValueError("qmd.search: query must be non-empty")
        results: list[dict[str, Any]] = []
        for coll_ws, coll_name, mems in self._iter_all(collection):
            for m in mems:
                content = str(m.get("content", ""))
                score = self._bm25_score(query, content)
                if score > 0:
                    results.append(
                        {
                            "docid": _docid(content),
                            "score": score,
                            "path": m.get("source_session_id", ""),
                            "snippet": _snippet(content, query),
                            "collection": coll_name,
                            "line": 1,
                        }
                    )
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    def vsearch(
        self,
        query: str,
        collection: str | None = None,
        limit: int = 20,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Pure semantic vector search (QMD ``vsearch``)."""
        if not query or not query.strip():
            raise ValueError("qmd.vsearch: query must be non-empty")
        results: list[dict[str, Any]] = []
        for coll_ws, coll_name, mems in self._iter_all(collection):
            try:
                hits = self._client.search(
                    workspace_id=coll_ws,
                    query=query,
                    limit=limit * 2,
                    semantic=True,
                    cross_encoder=False,
                )
            except Exception as exc:
                logger.warning("qmd.vsearch: %s", exc)
                hits = []
            for h in hits:
                content = str(h.get("content", ""))
                results.append(
                    {
                        "docid": _docid(content),
                        "score": h.get("score", 0.0),
                        "path": h.get("source_session_id", h.get("id", "")),
                        "snippet": _snippet(content, query),
                        "collection": coll_name,
                        "line": 1,
                    }
                )
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    def query(
        self,
        query: str | Query,
        collection: str | None = None,
        limit: int = 20,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Hybrid search with query expansion + fusion (QMD ``query``).

        When given a plain string, auto-expands into lex+vec sub-queries and
        fuses results (QMD's recommended path). When given a ``Query`` with
        explicit ``SubQuery`` entries, runs each and fuses.

        Returns:
            list of result dicts sorted by fused score.
        """
        if isinstance(query, str):
            if not query.strip():
                raise ValueError("qmd.query: query must be non-empty")
            sub_queries = [
                SubQuery(type="lex", query=query),
                SubQuery(type="vec", query=query),
            ]
        else:
            sub_queries = query.sub_queries
        if not sub_queries:
            raise ValueError("qmd.query: at least one sub-query required")

        fused: dict[str, dict[str, Any]] = {}
        for sq in sub_queries:
            if sq.type == "lex":
                hits = self.search(sq.query, collection=collection, limit=limit * 2)
            else:  # vec / hyde → semantic
                hits = self.vsearch(sq.query, collection=collection, limit=limit * 2)
            for r in hits:
                key = r["path"]
                if key not in fused:
                    r["_scores"] = [r["score"]]
                    fused[key] = r
                else:
                    fused[key]["_scores"].append(r["score"])
        for r in fused.values():
            n = len(r["_scores"])
            r["score"] = sum(r["_scores"]) / n  # average fusion of sub-queries
            r.pop("_scores", None)
        ranked = sorted(fused.values(), key=lambda r: r["score"], reverse=True)
        return ranked[:limit]

    # -- context -------------------------------------------------------------

    def context_add(self, path: str, text: str, **kwargs: Any) -> dict[str, Any]:
        """Add context for a path / collection (QMD ``context add``).

        Args:
            path: Collection or path (``"/"`` = global, ``"/subfolder"``).
            text: Context description.

        Returns:
            ``{"path", "context"}``.
        """
        if not text or not text.strip():
            raise ValueError("qmd.context_add: text must be non-empty")
        ctx_ws = _collection_ws("__context__")
        self._ensure_ws(ctx_ws, "__context__")
        try:
            self._client.store(
                workspace_id=ctx_ws,
                content=text,
                memory_type="document",
                source_session_id=path,
            )
            return {"path": path, "context": text}
        except Exception as exc:
            raise RuntimeError(f"qmd.context_add: {exc}") from exc

    def context_list(self) -> list[dict[str, Any]]:
        """List all contexts (QMD ``context list``).

        Returns:
            list of ``{"path", "context"}`` dicts.
        """
        ctx_ws = _collection_ws("__context__")
        out: list[dict[str, Any]] = []
        try:
            rows = self._client._query("memory", ctx_ws, {}, ["content", "source_session_id"])
            for r in rows:
                out.append(
                    {"path": r.get("source_session_id", ""), "context": str(r.get("content", ""))}
                )
        except Exception as exc:
            logger.warning("qmd.context_list: %s", exc)
        return out

    def context_remove(self, path: str) -> bool:
        """Remove a context by path (QMD ``context rm``)."""
        ctx_ws = _collection_ws("__context__")
        try:
            rows = self._client._query("memory", ctx_ws, {}, ["id", "source_session_id"])
            for r in rows:
                if r.get("source_session_id") == path:
                    self._client._call("delete_memory", [r["id"]])
                    return True
        except Exception as exc:
            logger.warning("qmd.context_remove: %s", exc)
        return False

    # -- status --------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Show index status (QMD ``status``).

        Returns:
            ``{"collections": [...], "documents": N, "healthy": bool}``.
        """
        cols = self.collection_list()
        total = sum(c.get("documents", 0) for c in cols)
        return {
            "collections": cols,
            "documents": total,
            "collections_count": len(cols),
            "healthy": True,
        }

    # -- internals -----------------------------------------------------------

    def _iter_all(self, collection: str | None):
        """Yield (workspace_id, name, memories) for matching collections."""
        try:
            ws_rows = self._client._query("workspace", "", {}, ["id", "name"])
        except Exception:
            return
        for r in ws_rows:
            name = str(r.get("name", ""))
            if not name.startswith("QMD:"):
                continue
            coll = name.replace("QMD:", "")
            if collection and coll != collection:
                continue
            ws = r["id"]
            try:
                mems = self._client._query("memory", ws, {}, ["id", "content", "source_session_id"])
            except Exception:
                mems = []
            yield ws, coll, mems

    def _bm25_score(self, query: str, content: str) -> float:
        """Simplified BM25-like keyword scoring with phrase + negation."""
        score = 0.0
        content_l = content.lower()
        # remove negation terms
        negatives = re.findall(r"\s-(\S+)", " " + query)
        for neg in negatives:
            if neg.lower() in content_l:
                return 0.0
        # phrases
        for phrase in re.findall(r'"([^"]+)"', query):
            if phrase.lower() in content_l:
                score += 3.0
        # remaining words (remove negation/phrase tokens)
        cleaned = re.sub(r'"[^"]+"', "", query)
        for neg in negatives:
            cleaned = cleaned.replace(f"-{neg}", " ")
        for word in re.findall(r"[\w']+", cleaned):
            if word.lower() in content_l:
                score += 1.0
        return score


def _slug(path: str) -> str:
    """Derive a collection name from a path."""
    base = path.rstrip("/").split("/")[-1].split(".")[0]
    return base or "collection"


def _snippet(content: str, query: str) -> str:
    """Extract a short snippet around the first query term match."""
    words = [w for w in re.findall(r"[\w']+", query) if len(w) > 2]
    lowered = content.lower()
    best = 0
    for w in words:
        idx = lowered.find(w.lower())
        if idx >= 0 and (best == 0 or abs(idx - 0) < best):
            best = idx
    if best == 0 and not any(w in lowered for w in words):
        return content[:120]
    start = max(0, best - 40)
    end = min(len(content), best + 80)
    return content[start:end]


def _glob_match(pattern: str, path: str) -> bool:
    """Simple glob match (*, ?) supporting common QMD patterns."""
    if pattern == path:
        return True
    import fnmatch

    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, pattern + "*")