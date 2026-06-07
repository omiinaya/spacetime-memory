"""Pytest fixtures for spacetime-memory SDK tests."""

import json
import pytest
import httpx
from unittest.mock import Mock, MagicMock, patch
from spacetime_memory import Client


def make_sql_response(rows):
    """Convert a list of dicts to the SpacetimeDB SQL wire‑format.

    The SpacetimeDB SQL API returns a JSON array of tables.  Each table
    has a ``schema`` with named ``elements`` and a ``rows`` array of
    positional values.  This helper builds that format from a simple
    list of dicts so tests can set realistic mock responses.

    Example::

        >>> make_sql_response([{"id": "1", "name": "alice"}])
        '[{"schema": {"elements": [{"name": {"some": "id"}}, {"name": {"some": "name"}}]}, "rows": [["1", "alice"]]}]'
    """
    if not rows:
        return json.dumps([])
    cols = list(rows[0].keys())
    elements = [{"name": {"some": c}} for c in cols]
    row_data = [[r.get(c) for c in cols] for r in rows]
    return json.dumps([{"schema": {"elements": elements}, "rows": row_data}])


@pytest.fixture
def mock_http_client():
    """Create a Client with mocked HTTP calls.

    The fixture creates a real Client with test-safe connection parameters,
    then replaces its internal ``_http`` (httpx.Client) with a MagicMock
    so that no real network calls are made.  Tests can control what the
    SQL / reducer / embedder endpoints return by setting::

        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text=json.dumps(my_payload),
        )

    The default response is an empty SQL result set (``[]``).
    """
    client = Client(
        host="localhost",
        port="3001",
        database="test-db",
        embedder_url="http://localhost:9090",
    )
    # Replace the real httpx client with a mock — no actual network I/O.
    mock_http = MagicMock(spec=httpx.Client)
    # Default response: empty SQL result set
    mock_http.post.return_value = Mock(
        status_code=200,
        text=json.dumps([]),
    )
    client._http = mock_http
    yield client


@pytest.fixture
def mock_client():
    """A MagicMock with the interface expected by AgentOrchestrator.

    All methods return sensible defaults so tests don't need to set up
    boilerplate for every call.
    """
    client = MagicMock()
    client._call.return_value = {"status": "ok"}
    client._sql.return_value = []
    client.search.return_value = []
    client.store.return_value = {"status": "ok"}
    client.query_graph.return_value = []
    return client
