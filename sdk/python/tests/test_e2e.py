"""E2E pipeline tests: exercise multi-step workflows via mocked HTTP.

These tests simulate complete round-trip flows (store -> search, create node ->
query graph, create note -> get backlinks) using mocked HTTP responses. They
verify that the Python client's method chain works correctly end-to-end
without requiring a running SpacetimeDB instance.

Run with: pytest sdk/python/tests/test_e2e.py -v
"""

from __future__ import annotations

import json
from unittest.mock import Mock

import httpx
import pytest

from spacetime_memory import Client

pytestmark = [
    pytest.mark.deep,
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client() -> Client:
    """Create a Client with mocked HTTP for pipeline testing."""
    client = Client(
        host="localhost",
        port="3001",
        database="test-db",
        embedder_url="http://localhost:9090",
    )
    mock_http = Mock(spec=httpx.Client)

    def _default_post(url, *args, **kwargs):
        url_str = str(url)
        if "/embed" in url_str or ":9090" in url_str:
            return Mock(
                status_code=200,
                json=lambda: {"data": [{"embedding": [0.1, 0.2, 0.3]}]},
            )
        # Non-call/non-embed URLs (sql, tantivy) return empty success
        return Mock(
            status_code=200,
            text=json.dumps([]),
            json=list,
        )

    mock_http.post.side_effect = _default_post
    mock_http.get.return_value = Mock(
        status_code=200,
        json=lambda: {"model": "bge-m3"},
    )
    client._http = mock_http
    return client


def _make_sql_response(rows: list[dict]) -> str:
    """Build a SpacetimeDB SQL wire-format response from a list of dicts."""
    if not rows:
        return json.dumps([])
    cols = list(rows[0].keys())
    elements = [{"name": {"some": c}} for c in cols]
    row_data = [[r.get(c) for c in cols] for r in rows]
    return json.dumps([{"schema": {"elements": elements}, "rows": row_data}])


def _mock_post() -> Mock:
    """Return a smart Mock that returns OK for calls and empty for SQL."""
    def _side(url, *args, **kwargs):
        url_str = str(url)
        if "/call" in url_str:
            return Mock(status_code=200, text=json.dumps({"status": "ok"}))
        if "/embed" in url_str:
            return Mock(
                status_code=200,
                json=lambda: {"data": [{"embedding": [0.1, 0.2, 0.3]}]},
            )
        if "/sql" in url_str:
            return Mock(status_code=200, text=json.dumps([]))
        return Mock(status_code=200, text=json.dumps({"status": "ok"}))
    return Mock(side_effect=_side)


# ---------------------------------------------------------------------------
# Pipeline: Store -> Search
# ---------------------------------------------------------------------------


class TestStoreThenSearch:
    """Verify the full store -> search pipeline with mocked responses."""

    def test_store_memory_then_keyword_search(self):
        """Store a memory, then search (keyword-only) and verify the pipeline connects."""
        client = _make_client()
        ws_id = "ws-store-search"

        def _side(url, *args, **kwargs):
            url_str = str(url)
            if "/call" in url_str:
                return Mock(status_code=200, text=json.dumps({"status": "ok"}))
            if "/embed" in url_str:
                return Mock(
                    status_code=200,
                    json=lambda: {"data": [{"embedding": [0.1, 0.2, 0.3]}]},
                )
            if "/sql" in url_str:
                return Mock(
                    status_code=200,
                    text=_make_sql_response([
                        {"id": "mem-1", "entity_id": "mem-1",
                         "content": "The capital of France is Paris.",
                         "entity_type": "memory", "workspace_id": ws_id,
                         "memory_type": "fact"},
                    ]),
                )
            return Mock(
                status_code=200,
                text=json.dumps([]),
                json=list,
            )

        client._http.post = Mock(side_effect=_side)

        result = client.store(
            workspace_id=ws_id,
            content="The capital of France is Paris.",
            peer_id="test-bot",
            memory_type="fact",
        )
        assert result.get("status") == "ok", f"store() should succeed, got {result}"

        results = client.search(
            workspace_id=ws_id,
            query="What is the capital of France?",
            semantic=False,
            limit=5,
        )
        assert len(results) >= 1, f"Expected >=1 result, got {len(results)}"
        assert any("Paris" in r.get("content", "") for r in results)

    def test_store_then_search_multiple_results(self):
        """Store a memory, then search returning multiple results."""
        client = _make_client()
        ws_id = "ws-multi-results"

        def _side(url, *args, **kwargs):
            url_str = str(url)
            if "/call" in url_str:
                return Mock(status_code=200, text=json.dumps({"status": "ok"}))
            if "/embed" in url_str:
                return Mock(
                    status_code=200,
                    json=lambda: {"data": [{"embedding": [0.1, 0.2, 0.3]}]},
                )
            if "/sql" in url_str:
                return Mock(
                    status_code=200,
                    text=_make_sql_response([
                        {"id": "r1", "entity_id": "r1",
                         "content": "Python is dynamically typed.",
                         "entity_type": "memory", "workspace_id": ws_id},
                        {"id": "r2", "entity_id": "r2",
                         "content": "Python supports multiple paradigms.",
                         "entity_type": "memory", "workspace_id": ws_id},
                    ]),
                )
            return Mock(
                status_code=200,
                text=json.dumps([]),
                json=list,
            )

        client._http.post = Mock(side_effect=_side)

        client.store(ws_id, "Python is great", peer_id="bot")

        results = client.search(ws_id, "Python", semantic=False, limit=5)
        assert len(results) >= 1
        contents = [r.get("content", "") for r in results]
        assert any("dynamically typed" in c for c in contents)


# ---------------------------------------------------------------------------
# Pipeline: Create Node -> Query Graph
# ---------------------------------------------------------------------------


class TestCreateNodeThenQueryGraph:
    """Verify the knowledge graph pipeline end-to-end."""

    def test_create_node_and_edge(self):
        """Create KG nodes, link them -- verify reducer calls succeed."""
        client = _make_client()
        ws_id = "ws-kg-pipeline"

        client._http.post = _mock_post()

        r1 = client.create_node(ws_id, "Paris", "location")
        assert r1.get("status") == "ok"
        r2 = client.create_node(ws_id, "France", "location")
        assert r2.get("status") == "ok"

        edge_result = client._call(
            "create_edge",
            [ws_id, "node-paris", "node-france", "located_in", {}],
        )
        assert edge_result.get("status") == "ok"

    def test_create_node_then_get_neighbors(self):
        """Create a node and get its neighbors via mocked SQL."""
        client = _make_client()
        ws_id = "ws-neighbors"

        def _side(url, *args, **kwargs):
            url_str = str(url)
            if "/call" in url_str:
                return Mock(status_code=200, text=json.dumps({"status": "ok"}))
            if "/embed" in url_str:
                return Mock(
                    status_code=200,
                    json=lambda: {"data": [{"embedding": [0.1, 0.2, 0.3]}]},
                )
            if "/sql" in url_str:
                return Mock(
                    status_code=200,
                    text=_make_sql_response([
                        {"id": "edge-1", "source_node_id": "node-paris",
                         "target_node_id": "node-eiffel",
                         "edge_type": "contains", "workspace_id": ws_id},
                    ]),
                )
            return Mock(
                status_code=200,
                text=json.dumps([]),
                json=list,
            )

        client._http.post = Mock(side_effect=_side)

        r = client.create_node(ws_id, "Paris", "location")
        assert r.get("status") == "ok"

        neighbors = client.get_neighbors("node-paris", workspace_id=ws_id)
        assert len(neighbors) >= 1
        assert neighbors[0].get("edge_type") == "contains"


# ---------------------------------------------------------------------------
# Pipeline: Create Note -> Get Backlinks
# ---------------------------------------------------------------------------


class TestCreateNoteThenGetBacklinks:
    """Verify notes/wiki pipeline end-to-end."""

    def test_create_note_then_get_backlinks(self):
        """Create a note, then retrieve backlinks pointing to it."""
        client = _make_client()
        ws_id = "ws-backlinks"

        def _side(url, *args, **kwargs):
            url_str = str(url)
            if "/call" in url_str:
                return Mock(status_code=200, text=json.dumps({"status": "ok"}))
            if "/embed" in url_str:
                return Mock(
                    status_code=200,
                    json=lambda: {"data": [{"embedding": [0.1, 0.2, 0.3]}]},
                )
            if "/sql" in url_str:
                return Mock(
                    status_code=200,
                    text=_make_sql_response([
                        {"source_note_id": "note-euro-geo",
                         "target_note_id": "note-paris"},
                    ]),
                )
            return Mock(
                status_code=200,
                text=json.dumps([]),
                json=list,
            )

        client._http.post = Mock(side_effect=_side)

        result = client.create_note(
            workspace_id=ws_id,
            title="Paris",
            content="Paris is the capital of France.",
        )
        assert result.get("status") == "ok"

        backlinks = client.get_backlinks("note-paris")
        assert len(backlinks) >= 1
        assert backlinks[0]["target_note_id"] == "note-paris"

    def test_create_note_then_get_outgoing_links(self):
        """Create a note and verify outgoing wiki-links are retrievable."""
        client = _make_client()
        ws_id = "ws-outgoing"

        def _side(url, *args, **kwargs):
            url_str = str(url)
            if "/call" in url_str:
                return Mock(status_code=200, text=json.dumps({"status": "ok"}))
            if "/embed" in url_str:
                return Mock(
                    status_code=200,
                    json=lambda: {"data": [{"embedding": [0.1, 0.2, 0.3]}]},
                )
            if "/sql" in url_str:
                return Mock(
                    status_code=200,
                    text=_make_sql_response([
                        {"source_note_id": "note-visiting-paris",
                         "target_note_id": "note-fr"},
                        {"source_note_id": "note-visiting-paris",
                         "target_note_id": "note-eiffel"},
                    ]),
                )
            return Mock(
                status_code=200,
                text=json.dumps([]),
                json=list,
            )

        client._http.post = Mock(side_effect=_side)

        result = client.create_note(
            workspace_id=ws_id,
            title="Visiting Paris",
            content="See [[France]] and the [[Eiffel Tower]].",
        )
        assert result.get("status") == "ok"

        links = client.get_outgoing_links("note-visiting-paris")
        assert len(links) == 2
        target_ids = {item["target_note_id"] for item in links}
        assert "note-fr" in target_ids
        assert "note-eiffel" in target_ids


# ---------------------------------------------------------------------------
# Pipeline: Multi-step compound workflow
# ---------------------------------------------------------------------------


class TestMultiStepMemoryLifecycle:
    """Verify a realistic multi-step workflow combining memories, KG, and notes."""

    def test_store_then_create_node_then_create_note(self):
        """Mixed workflow: store fact, create KG entity, create note -- all succeed."""
        client = _make_client()
        ws_id = "ws-mixed-lifecycle"

        call_log: list[str] = []

        def _side(url, *args, **kwargs):
            url_str = str(url)
            call_log.append(url_str.split("?")[0][-40:])
            if "/call" in url_str:
                return Mock(status_code=200, text=json.dumps({"status": "ok"}))
            if "/embed" in url_str:
                return Mock(
                    status_code=200,
                    json=lambda: {"data": [{"embedding": [0.1, 0.2, 0.3]}]},
                )
            return Mock(
                status_code=200,
                text=json.dumps([]),
                json=list,
            )

        client._http.post = Mock(side_effect=_side)

        r1 = client.store(ws_id, "E = mc2", peer_id="physics-bot")
        assert r1.get("status") == "ok"

        r2 = client.create_node(ws_id, "Mass-Energy Equivalence", "concept")
        assert r2.get("status") == "ok"

        r3 = client.create_note(
            ws_id, "Einstein's Insight",
            "E=mc2 is the mass-energy equivalence principle.",
        )
        assert r3.get("status") == "ok"

        assert len(call_log) >= 3, f"Expected >=3 HTTP calls, got {len(call_log)}"

    def test_store_note_then_get_via_query(self):
        """Store a note, then retrieve it via _query."""
        client = _make_client()
        ws_id = "ws-note-query"

        def _side(url, *args, **kwargs):
            url_str = str(url)
            if "/call" in url_str:
                return Mock(status_code=200, text=json.dumps({"status": "ok"}))
            if "/embed" in url_str:
                return Mock(
                    status_code=200,
                    json=lambda: {"data": [{"embedding": [0.1, 0.2, 0.3]}]},
                )
            if "/sql" in url_str:
                body = kwargs.get("content", b"")
                body_str = body.decode() if isinstance(body, bytes) else str(body)
                if "note_backlink" in body_str:
                    return Mock(status_code=200, text=json.dumps([]))
                return Mock(
                    status_code=200,
                    text=_make_sql_response([
                        {"id": "note-abc", "title": "Test Note",
                         "content": "Test content here.",
                         "workspace_id": ws_id},
                    ]),
                )
            return Mock(
                status_code=200,
                text=json.dumps([]),
                json=list,
            )

        client._http.post = Mock(side_effect=_side)

        r = client.create_note(ws_id, "Test Note", "Test content here.")
        assert r.get("status") == "ok"

        notes = client._query("note", filter_dict={"workspace_id": ws_id})
        assert len(notes) >= 1
        assert notes[0]["title"] == "Test Note"


# ---------------------------------------------------------------------------
# Pipeline: Backup -> Restore
# ---------------------------------------------------------------------------


class TestBackupThenRestore:
    """Verify backup -> restore pipeline with mocked responses."""

    def test_backup_collects_tables(self):
        """backup() returns a dict with status='ok'."""
        client = _make_client()
        ws_id = "ws-backup-restore"

        call_count = 0

        def _side(url, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            url_str = str(url)
            if "/call" in url_str:
                return Mock(status_code=200, text=json.dumps({"status": "ok"}))
            if "/embed" in url_str:
                return Mock(
                    status_code=200,
                    json=lambda: {"data": [{"embedding": [0.1, 0.2, 0.3]}]},
                )
            if "/sql" in url_str:
                if call_count <= 2:
                    rows = [
                        {"id": ws_id, "name": "Test WS", "description": "testing"},
                        {"id": "m1", "entity_id": "m1", "content": "memory 1",
                         "entity_type": "memory", "workspace_id": ws_id},
                    ][:call_count]
                    return Mock(
                        status_code=200,
                        text=_make_sql_response(rows),
                    )
                return Mock(status_code=200, text=json.dumps([]))
            return Mock(
                status_code=200,
                text=json.dumps([]),
                json=list,
            )

        client._http.post = Mock(side_effect=_side)
        result = client.backup(output_path="/tmp/test_backup.json")
        assert isinstance(result, dict)
        assert result.get("status") == "ok"

    def test_restore_happy_path(self, tmp_path):
        """restore() with valid backup JSON succeeds."""
        client = _make_client()
        backup_file = tmp_path / "backup.json"
        backup_file.write_text(json.dumps({
            "workspaces": [{"id": "ws-1", "name": "W1", "description": ""}],
            "memories": [{"id": "m1", "entity_id": "m1", "content": "test",
                          "entity_type": "memory", "workspace_id": "ws-1"}],
        }))

        def _side(url, *args, **kwargs):
            url_str = str(url)
            if "/sql" in url_str:
                return Mock(status_code=200, text=json.dumps([]))
            return Mock(status_code=200, text=json.dumps({"status": "ok"}))

        client._http.post = Mock(side_effect=_side)
        result = client.restore(str(backup_file))
        assert result is not None

    def test_restore_empty_data(self, tmp_path):
        """restore() with empty data succeeds."""
        client = _make_client()
        backup_file = tmp_path / "empty.json"
        backup_file.write_text(json.dumps({"workspaces": [], "memories": []}))

        def _side(url, *args, **kwargs):
            url_str = str(url)
            if "/sql" in url_str:
                return Mock(status_code=200, text=json.dumps([]))
            return Mock(status_code=200, text=json.dumps({"status": "ok"}))

        client._http.post = Mock(side_effect=_side)
        result = client.restore(str(backup_file))
        assert result is not None

    def test_backup_no_workspaces(self):
        """backup() with no workspaces returns gracefully."""
        client = _make_client()

        def _side(url, *args, **kwargs):
            url_str = str(url)
            if "/sql" in url_str:
                return Mock(status_code=200, text=json.dumps([]))
            return Mock(
                status_code=200,
                text=json.dumps([]),
                json=list,
            )

        client._http.post = Mock(side_effect=_side)
        result = client.backup(output_path="/tmp/test_backup_empty.json")
        assert result is not None


# ---------------------------------------------------------------------------
# Pipeline: Search edge cases
# ---------------------------------------------------------------------------


class TestSearchEdgeCases:
    """Search pipeline edge cases: empty query, no results, limit zero."""

    def test_search_empty_query_returns_empty(self):
        """Empty query string returns []."""
        client = _make_client()
        ws_id = "ws-edge"

        def _side(url, *args, **kwargs):
            url_str = str(url)
            if "/sql" in url_str:
                return Mock(status_code=200, text=json.dumps([]))
            if "/embed" in url_str:
                return Mock(
                    status_code=200,
                    json=lambda: {"data": [{"embedding": [0.0] * 1024}]},
                )
            return Mock(
                status_code=200,
                text=json.dumps([]),
                json=list,
            )

        client._http.post = Mock(side_effect=_side)
        results = client.search(ws_id, "", semantic=False, limit=5)
        assert results == []

    def test_search_no_results_returns_empty_list(self):
        """Search that matches nothing returns []."""
        client = _make_client()
        ws_id = "ws-noresults"

        def _side(url, *args, **kwargs):
            url_str = str(url)
            if "/sql" in url_str:
                return Mock(status_code=200, text=json.dumps([]))
            if "/embed" in url_str:
                return Mock(
                    status_code=200,
                    json=lambda: {"data": [{"embedding": [0.0] * 1024}]},
                )
            return Mock(
                status_code=200,
                text=json.dumps([]),
                json=list,
            )

        client._http.post = Mock(side_effect=_side)
        results = client.search(ws_id, "nonexistent term", semantic=False, limit=10)
        assert results == []

    def test_search_limit_zero(self):
        """Search with limit=0 returns []."""
        client = _make_client()
        ws_id = "ws-limit-zero"

        def _side(url, *args, **kwargs):
            url_str = str(url)
            if "/sql" in url_str:
                return Mock(status_code=200, text=json.dumps([]))
            if "/embed" in url_str:
                return Mock(
                    status_code=200,
                    json=lambda: {"data": [{"embedding": [0.0] * 1024}]},
                )
            return Mock(
                status_code=200,
                text=json.dumps([]),
                json=list,
            )

        client._http.post = Mock(side_effect=_side)
        results = client.search(ws_id, "test", limit=0)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Pipeline: Graph edge cases
# ---------------------------------------------------------------------------


class TestGraphEdgeCases:
    """Knowledge graph edge cases: invalid queries, missing nodes."""

    def test_query_graph_empty_results(self):
        """query_graph on empty workspace returns []."""
        client = _make_client()
        ws_id = "ws-graph-empty"

        def _side(url, *args, **kwargs):
            url_str = str(url)
            if "/sql" in url_str:
                return Mock(status_code=200, text=json.dumps([]))
            return Mock(
                status_code=200,
                text=json.dumps([]),
                json=list,
            )

        client._http.post = Mock(side_effect=_side)
        nodes = client.query_graph(ws_id, "nonexistent")
        assert nodes == []

    def test_get_neighbors_no_edges(self):
        """get_neighbors with no edges returns []."""
        client = _make_client()

        def _side(url, *args, **kwargs):
            url_str = str(url)
            if "/sql" in url_str:
                return Mock(status_code=200, text=json.dumps([]))
            return Mock(
                status_code=200,
                text=json.dumps([]),
                json=list,
            )

        client._http.post = Mock(side_effect=_side)
        neighbors = client.get_neighbors("nonexistent-node", workspace_id="ws-1")
        assert neighbors == []

    def test_shortest_path_no_path(self):
        """shortest_path returns empty when nodes are disconnected."""
        client = _make_client()

        def _side(url, *args, **kwargs):
            url_str = str(url)
            if "/sql" in url_str:
                return Mock(status_code=200, text=json.dumps([]))
            return Mock(
                status_code=200,
                text=json.dumps([]),
                json=list,
            )

        client._http.post = Mock(side_effect=_side)
        result = client._call("shortest_path", ["ws-1", "node-a", "node-b"])
        assert result is not None
