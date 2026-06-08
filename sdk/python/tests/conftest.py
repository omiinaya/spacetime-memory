"""Pytest fixtures for spacetime-memory SDK tests.

Auto-publishes the SpacetimeDB module before integration tests.
Provides mock fixtures for unit tests that don't need a real backend.

Markers
-------
- ``unit`` — tests that use mocked HTTP, no SpacetimeDB required (default when
  no marker is set on the test), runs ``pytest -m unit``.
- ``integration`` — tests that require a running SpacetimeDB standalone and
  the module published, runs ``pytest -m integration``.
- ``embedder`` — subset of integration tests that also require the Rust ONNX
  embedder sidecar running on :9090.
"""

from __future__ import annotations

import json
import os
import subprocess
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
    config.addinivalue_line("markers", "embedder: tests that also need the ONNX embedder sidecar")


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
    """Run ``spacetime publish`` and return the database identity hex string.

    Assumes the Cargo project is at ``server/spacetimedb/`` relative to
    the repo root.  Uses ``--delete-data=on-conflict`` so CI cleans don't
    pile up but local dev doesn't nuke data unnecessarily.

    Returns the identity hex of the published database.
    """
    module_dir = _repo_root / "server" / "spacetimedb"
    if not module_dir.exists():
        raise RuntimeError(
            f"Module directory {module_dir} not found — cannot publish. "
            "Run pytest from the repo root or set SPACETIMEDB_DB manually."
        )

    result = subprocess.run(
        [
            "spacetime", "publish",
            "--server", "http://127.0.0.1:3001",
            "--yes=all",
            f"--delete-data={delete_data}",
            "spacetime-memory",
        ],
        cwd=str(module_dir),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"spacetime publish failed (exit={result.returncode}):\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    # Parse the identity from output: "Updated database with name: spacetime-memory, identity: <hex>"
    for line in result.stdout.splitlines():
        if "identity:" in line:
            return line.split("identity:")[-1].strip()
    raise RuntimeError(
        f"Could not parse identity from publish output:\n{result.stdout}"
    )


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
    # starts with a clean database.  The CLI build is fast (0.1s when the
    # WASM is current); the deletion takes negligible time.
    _publish_module(delete_data="always")
    _database = "spacetime-memory"

    return {
        "host": os.environ.get("SPACETIMEDB_HOST", "localhost"),
        "port": os.environ.get("SPACETIMEDB_PORT", "3001"),
        "database": _database,
    }


@pytest.fixture
def stdb_client(stdb_session) -> Client:
    """Create a Client connected to the published database.

    Uses the token file from the repo's JWT key pair for consistent
    identity across test runs.
    """
    token = _generate_test_token()
    return Client(
        host=stdb_session["host"],
        port=stdb_session["port"],
        database=stdb_session["database"],
        token=token,
    )


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
