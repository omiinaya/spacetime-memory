"""Pytest fixtures for spacetime-memory SDK tests.

Auto-publishes the SpacetimeDB module before integration tests.
Provides mock fixtures for unit tests that don't need a real backend.

Markers
-------
- ``unit`` — tests that use mocked HTTP, no SpacetimeDB required (default when
  no marker is set on the test), runs ``pytest -m unit``.
- ``integration`` — tests that require a running SpacetimeDB standalone and
  the module published, runs ``pytest -m integration``.
- ``embedder`` — subset of integration tests that also require the proxy
  embedder. Set ``OPENAI_API_KEY`` + ``OPENAI_BASE_URL`` + ``EMBEDDING_MODEL``
  before running these tests.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import httpx
import pytest

# Add repo root to sys.path so tests can import the CLI and other modules
# that live outside the SDK package (e.g., cli/stmem.py).
_repo_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from spacetime_memory import Client

# ---------------------------------------------------------------------------
# Pytest marker registration
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line("markers", "unit: tests that mock HTTP (no SpacetimeDB needed)")
    config.addinivalue_line("markers", "integration: tests that need a running SpacetimeDB standalone")
    config.addinivalue_line("markers", "embedder: tests that also need the proxy embedder (set OPENAI_API_KEY)")


def pytest_collection_modifyitems(config, items):
    """If a test file is in the tests/ dir but has no explicit marker,
    auto-tag it based on the file name convention.

    test_*.py files whose first test class inherits from the integration
    marker group get tagged ``integration`` automatically.  Files that
    import ``conftest.mock_http_client`` or ``conftest.mock_client`` are
    tagged ``unit`` automatically.
    """
    for item in items:
        # Already has an explicit marker — leave it
        if list(item.iter_markers()):
            continue

        path = str(item.fspath)
        # Convention: test files whose names end in _integration or
        # test files that import mock fixtures get unit marker.
        # We let the per-file markers handle this — bare tests
        # without a marker run in unit mode by default.
        item.add_marker(pytest.mark.unit)


# ---------------------------------------------------------------------------
# Test helper: build a mock SQL response from a list of dicts
# ---------------------------------------------------------------------------


def make_sql_response(rows):
    """Convert a list of dicts to the SpacetimeDB SQL wire-format.

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


# ---------------------------------------------------------------------------
# Mock fixtures (unit tests)
# ---------------------------------------------------------------------------


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
        json=lambda: [],
    )
    # Embedder health endpoint mock: return 200 so health checks pass
    mock_http.get.return_value = Mock(
        status_code=200,
        json=lambda: {"model": "bge-m3"},
    )
    client._http = mock_http
    return client


@pytest.fixture
def mock_client():
    """A MagicMock with the interface expected by AgentOrchestrator.

    All methods return sensible defaults so tests don't need to set up
    boilerplate for every call.
    """
    client = MagicMock()
    client._call.return_value = {"status": "ok"}
    client._sql.return_value = []
    client._query.return_value = []
    client.search.return_value = []
    client.store.return_value = {"status": "ok"}
    client.query_graph.return_value = []
    return client


# ---------------------------------------------------------------------------
# Integration-test fixtures (require a running SpacetimeDB standalone)
# ---------------------------------------------------------------------------


def _running_stdb() -> bool:
    """Check whether a SpacetimeDB standalone is listening on localhost:3001."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(1)
        s.connect(("127.0.0.1", 3001))
        return True
    except (ConnectionRefusedError, OSError):
        return False
    finally:
        s.close()


def _publish_module(delete_data: str = "on-conflict") -> str:
    """Publish the WASM module via HTTP API and return the database identity.

    Uses the SpacetimeDB HTTP API directly (``POST /v1/database``) with
    anonymous identity establishment, bypassing the ``spacetime`` CLI which
    requires a valid JWT token.

    Assumes the WASM artifact is at ``server/spacetimedb/target/…/release/``.

    Returns the identity hex of the published (or existing) database.
    """
    module_dir = _repo_root / "server" / "spacetimedb"
    if not module_dir.exists():
        raise RuntimeError(
            f"Module directory {module_dir} not found — cannot publish. "
            "Run pytest from the repo root or set SPACETIMEDB_DB manually."
        )

    wasm_path = (
        module_dir / "target" / "wasm32-unknown-unknown" / "release"
        / "spacetime_memory.opt.wasm"
    )
    if not wasm_path.exists():
        wasm_path = (
            module_dir / "target" / "wasm32-unknown-unknown" / "release"
            / "spacetime_memory.wasm"
        )
    if not wasm_path.exists():
        raise RuntimeError(f"WASM module not found at {wasm_path}. Build first.")

    wasm_data = wasm_path.read_bytes()

    import httpx

    # Establish anonymous identity
    anon = httpx.get(
        "http://127.0.0.1:3001/v1/database/anon-probe",
        timeout=5.0,
    )
    token = anon.headers.get("spacetime-identity-token", "")

    headers = {"Content-Type": "application/octet-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Set delete-data parameter if requested
    url = "http://127.0.0.1:3001/v1/database?host_type=Wasm"
    if delete_data == "always":
        url += "&delete_data=true"

    resp = httpx.post(
        url,
        headers=headers,
        content=wasm_data,
        timeout=60.0,
    )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Publish via HTTP API failed (HTTP {resp.status_code}):\n{resp.text[:500]}"
        )

    data = resp.json()
    if "Success" in data:
        return data["Success"].get("database_identity", "unknown")
    if "Database" in data:
        # "Updated database …" response shape
        return data["Database"].get("database_identity", "unknown")
    # Fallback: try to parse any identity field
    if isinstance(data, dict):
        for key in ("database_identity", "identity"):
            if key in data:
                return data[key]
    raise RuntimeError(f"Could not parse identity from publish response:\n{data}")


@pytest.fixture(scope="session")
def stdb_session() -> dict:
    """Session-scoped: ensure SpacetimeDB is running and module is published.

    Returns ``{"host": "localhost", "port": "3001", "database": "<identity>"}``
    for use by test fixtures.

    Skips the entire integration test suite if no SpacetimeDB is reachable
    (respects ``SPACETIMEDB_HOST`` env var to force-enable).
    """
    force = os.environ.get("SPACETIMEDB_HOST", "")
    if not force and not _running_stdb():
        pytest.skip("SpacetimeDB standalone not running on localhost:3001. "
                     "Set SPACETIMEDB_HOST to force-enable integration tests.")

    # Always publish the module with --delete-data=always so each test run
    # starts with a clean database.  The WASM build is fast (0.1s when the
    # artifact is current); the HTTP publish takes ~1s.
    db_identity = _publish_module(delete_data="always")

    return {
        "host": os.environ.get("SPACETIMEDB_HOST", "localhost"),
        "port": os.environ.get("SPACETIMEDB_PORT", "3001"),
        "database": db_identity,
    }


@pytest.fixture
def stdb_client(stdb_session) -> Client:
    """Create a Client connected to the published database, auto-registered as admin.

    Registers a test account and promotes to admin on first use so that
    authenticated reducers (require_auth) work for integration tests.
    """
    c = Client(
        host=stdb_session["host"],
        port=stdb_session["port"],
        database=stdb_session["database"],
    )

    # Register and self-promote to admin for test access
    import os
    suffix = os.urandom(4).hex()
    uname = f"test_{suffix}"
    try:
        c._call("register", [uname, "Test User", "testpass"])
    except RuntimeError:
        pass  # already registered from a prior test in this session

    my_id = c._whoami()
    if my_id:
        try:
            c._call("set_initial_admin", [my_id])
        except RuntimeError:
            pass  # admin already exists

    return c


def _generate_test_token() -> str:
    """Generate a JWT token for integration tests from the project's key pair."""
    key_path = _repo_root / "data" / "id_ecdsa_pkcs8.pem"
    if not key_path.exists():
        return ""
    try:
        from spacetime_memory.auth import generate_token
        return generate_token(str(key_path))
    except ImportError:
        return ""


@pytest.fixture
def cli_mock_client():
    """Return a real Client with mocked HTTP for CLI testing.

    Uses the same pattern as test_cli.py's mock_client fixture.
    """
    client = Client(
        host="localhost",
        port="3001",
        database="test-db",
        embedder_url="http://localhost:9090",
    )
    mock_http = MagicMock(spec=httpx.Client)
    mock_http.post.return_value = Mock(
        status_code=200,
        text=json.dumps([]),
        json=lambda: [],
    )
    mock_http.get.return_value = Mock(
        status_code=200,
        json=lambda: {"model": "mock"},
    )
    client._http = mock_http
    return client


@pytest.fixture
def mocked_cli_runner(monkeypatch, cli_mock_client):
    """A CliRunner where the CLI's ``_sdk_client`` returns a mocked Client.

    Returns (runner, mock_client) tuple.
    """
    from click.testing import CliRunner
    monkeypatch.setattr("cli.stmem._sdk_client", lambda **kw: cli_mock_client)
    return CliRunner(), cli_mock_client
