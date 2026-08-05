"""Tests for the QMD-compatible adapter (``spacetime_memory.sdks.qmd``).

Unit tests use a fake Client (no live STDB needed). Integration tests
(marked ``integration``) require a live SpacetimeDB.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from spacetime_memory.sdks.qmd import (
    Document,
    QmdClient,
    Query,
    SubQuery,
    _collection_ws,
    _docid,
    _glob_match,
    _snippet,
    _slug,
)


# ---------------------------------------------------------------------------
# Helpers to expose the private scoring for direct testing
# ---------------------------------------------------------------------------
def _bm25_score_caller(qclient, query, content):
    return qclient._bm25_score(query, content)


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
            "source_session_id": kw.get("source_session_id", ""),
        }
        self.memories.setdefault(workspace_id, []).append(row)
        return {"id": row["id"]}

    def search(self, workspace_id, query, limit=15, semantic=True, cross_encoder=True, **kw):
        rows = self.memories.get(workspace_id, [])
        hits = []
        for r in rows:
            score = 0.8 if query.lower() in str(r.get("content", "")).lower() else 0.1
            hits.append({**r, "score": score})
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:limit]

    def _query(self, table, ws, filt=None, cols=None) -> list[dict[str, Any]]:
        filt = filt or {}
        if table == "memory":
            rows = list(self.memories.get(ws, []))
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
        elif reducer == "delete_memory":
            for wid, rows in self.memories.items():
                for i, r in enumerate(rows):
                    if r.get("id") == args[0]:
                        del self.memories[wid][i]
                        return None
        return None


@pytest.fixture
def qmd(monkeypatch) -> QmdClient:
    fake = FakeClient()
    q = QmdClient(host="127.0.0.1", port=3001)
    monkeypatch.setattr(q, "_client", fake)
    q._fake = fake  # type: ignore[attr-defined]
    return q


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


class TestCollections:
    def test_collection_add(self, qmd: QmdClient) -> None:
        out = qmd.collection_add("/path/to/notes", name="notes")
        assert out["name"] == "notes"
        ws = _collection_ws("notes")
        assert ws in qmd._fake.workspaces  # type: ignore[attr-defined]

    def test_collection_add_empty_paths_raises(self, qmd: QmdClient) -> None:
        with pytest.raises(ValueError, match="at least one path"):
            qmd.collection_add([])

    def test_collection_list(self, qmd: QmdClient) -> None:
        qmd.collection_add("/x", name="alpha")
        qmd.collection_add("/y", name="beta")
        names = [c["name"] for c in qmd.collection_list()]
        assert "alpha" in names
        assert "beta" in names

    def test_collection_remove(self, qmd: QmdClient) -> None:
        qmd.collection_add("/x", name="gamma")
        assert qmd.collection_remove("gamma") is True

    def test_collection_rename(self, qmd: QmdClient) -> None:
        qmd.collection_add("/x", name="oldname")
        qmd.add(collection="oldname", path="doc.md", content="hello world")
        assert qmd.collection_rename("oldname", "newname") is True
        got = qmd.get("doc.md")
        assert got.collection == "newname"


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class TestDocuments:
    def test_add(self, qmd: QmdClient) -> None:
        out = qmd.add(collection="docs", path="journal/2025.md", content="# Title\ncontent")
        assert out["path"] == "journal/2025.md"
        assert out["docid"] == _docid("# Title\ncontent")

    def test_add_empty_raises(self, qmd: QmdClient) -> None:
        with pytest.raises(ValueError, match="content must be non-empty"):
            qmd.add(collection="docs", path="x", content="")

    def test_get_by_path(self, qmd: QmdClient) -> None:
        qmd.collection_add("/d", name="docs")
        qmd.add(collection="docs", path="file.md", content="the file content")
        doc = qmd.get("file.md")
        assert isinstance(doc, Document)
        assert doc.path == "file.md"
        assert "file content" in doc.content

    def test_get_by_docid(self, qmd: QmdClient) -> None:
        qmd.collection_add("/d", name="docs")
        content = "distinct content abc123"
        qmd.add(collection="docs", path="f.md", content=content)
        doc = qmd.get(_docid(content))
        assert isinstance(doc, Document)
        assert doc.path == "f.md"

    def test_get_not_found(self, qmd: QmdClient) -> None:
        assert qmd.get("missing.md") == {"error": "not_found", "path": "missing.md"}

    def test_multi_get(self, qmd: QmdClient) -> None:
        qmd.collection_add("/d", name="docs")
        qmd.add(collection="docs", path="a.md", content="aaa")
        qmd.add(collection="docs", path="b.md", content="bbb")
        out = qmd.multi_get("a.md,b.md")
        assert len(out["docs"]) == 2
        paths = {d.path for d in out["docs"]}
        assert paths == {"a.md", "b.md"}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_keyword(self, qmd: QmdClient) -> None:
        qmd.collection_add("/d", name="notes")
        qmd.add(collection="notes", path="a.md", content="connection pool timeout issue")
        qmd.add(collection="notes", path="b.md", content="the weather is sunny today")
        hits = qmd.search("connection pool", collection="notes")
        assert len(hits) >= 1
        assert hits[0]["path"] == "a.md"

    def test_search_phrase(self, qmd: QmdClient) -> None:
        qmd.collection_add("/d", name="notes")
        qmd.add(collection="notes", path="a.md", content="the quick brown fox")
        hits = qmd.search('"quick brown"', collection="notes")
        assert len(hits) == 1

    def test_search_negation(self, qmd: QmdClient) -> None:
        qmd.collection_add("/d", name="notes")
        qmd.add(collection="notes", path="a.md", content="python is great")
        qmd.add(collection="notes", path="b.md", content="python is terrible")
        hits = qmd.search("python -terrible", collection="notes")
        assert len(hits) == 1
        assert hits[0]["path"] == "a.md"

    def test_search_by_collection(self, qmd: QmdClient) -> None:
        qmd.collection_add("/a", name="c1")
        qmd.collection_add("/b", name="c2")
        qmd.add(collection="c1", path="x.md", content="unique token zz9")
        qmd.add(collection="c2", path="y.md", content="unique token zz9")
        hits = qmd.search("unique token zz9", collection="c1")
        assert len(hits) == 1

    def test_search_empty_raises(self, qmd: QmdClient) -> None:
        with pytest.raises(ValueError, match="query must be non-empty"):
            qmd.search("")

    def test_vsearch(self, qmd: QmdClient) -> None:
        qmd.collection_add("/d", name="notes")
        qmd.add(collection="notes", path="a.md", content="how rate limiting works")
        hits = qmd.vsearch("rate limiting", collection="notes")
        assert len(hits) >= 1


class TestQuery:
    def test_query_string_auto_expands(self, qmd: QmdClient) -> None:
        qmd.collection_add("/d", name="notes")
        qmd.add(collection="notes", path="a.md", content="product launch is next month")
        qmd.add(collection="notes", path="b.md", content="unrelated diary entry")
        results = qmd.query("product launch next month", collection="notes")
        assert len(results) >= 1
        assert results[0]["path"] == "a.md"

    def test_query_with_subqueries(self, qmd: QmdClient) -> None:
        qmd.collection_add("/d", name="notes")
        qmd.add(collection="notes", path="a.md", content="the cap theorem is important")
        q = Query(sub_queries=[SubQuery(type="lex", query="cap theorem")])
        results = qmd.query(q, collection="notes")
        assert len(results) == 1

    def test_query_empty_raises(self, qmd: QmdClient) -> None:
        with pytest.raises(ValueError, match="query must be non-empty"):
            qmd.query("")

    def test_query_no_subqueries_raises(self, qmd: QmdClient) -> None:
        with pytest.raises(ValueError, match="at least one sub-query"):
            qmd.query(Query(sub_queries=[]))


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


class TestContext:
    def test_context_add(self, qmd: QmdClient) -> None:
        out = qmd.context_add("/docs", "These contain meeting transcripts")
        assert out["path"] == "/docs"
        assert out["context"] == "These contain meeting transcripts"

    def test_context_add_empty_raises(self, qmd: QmdClient) -> None:
        with pytest.raises(ValueError, match="text must be non-empty"):
            qmd.context_add("/docs", "")

    def test_context_list(self, qmd: QmdClient) -> None:
        qmd.context_add("/docs", "meeting notes")
        qmd.context_add("/api", "API reference")
        ctxs = qmd.context_list()
        assert len(ctxs) == 2

    def test_context_remove(self, qmd: QmdClient) -> None:
        qmd.context_add("/docs", "hello")
        assert qmd.context_remove("/docs") is True
        remaining = [c["path"] for c in qmd.context_list()]
        assert "/docs" not in remaining


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status(self, qmd: QmdClient) -> None:
        qmd.collection_add("/a", name="s1")
        qmd.add(collection="s1", path="x.md", content="hello")
        stat = qmd.status()
        assert stat["healthy"] is True
        assert stat["collections_count"] >= 1
        assert stat["documents"] >= 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_docid_deterministic(self) -> None:
        assert _docid("same") == _docid("same")
        assert _docid("same") != _docid("diff")
        assert _docid("x").startswith("#")

    def test_slug(self) -> None:
        assert _slug("/path/to/notes") == "notes"
        assert _slug("journal.md") == "journal"

    def test_glob_match(self) -> None:
        assert _glob_match("journal/*.md", "journal/2025-05-01.md")
        assert _glob_match("a.md", "a.md")
        assert not _glob_match("a.md", "b.md")

    def test_snippet(self) -> None:
        content = "The quick brown fox jumps over the lazy dog"
        snip = _snippet(content, "brown fox")
        assert "brown fox" in snip
        assert len(snip) <= len(content) + 100

    def test_bm25_scoring(self, qmd: QmdClient) -> None:
        assert _bm25_score_caller(qmd, "pool", "the pool is deep") > 0
        assert _bm25_score_caller(qmd, "zzyzx", "the pool is deep") == 0.0
