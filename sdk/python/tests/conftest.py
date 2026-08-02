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
import uuid
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest

# Add repo root to sys.path so tests can import the CLI and other modules
# that live outside the SDK package (e.g., cli/stmem.py).
_repo_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from spacetime_memory import Client
from spacetime_memory.sdks import Honcho

# ---------------------------------------------------------------------------
# Pytest marker registration
# ---------------------------------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line("markers", "unit: tests that mock HTTP (no SpacetimeDB needed)")
    config.addinivalue_line(
        "markers", "integration: tests that need a running SpacetimeDB standalone"
    )
    config.addinivalue_line(
        "markers", "embedder: tests that also need the proxy embedder (set OPENAI_API_KEY)"
    )
    config.addinivalue_line(
        "markers", "deep: pipeline/E2E tests that exercise multiple components end-to-end via mocked HTTP"
    )
    config.addinivalue_line(
        "markers", "e2e: adapter wire-compatibility tests that need a running SpacetimeDB standalone"
    )


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
    # Default response: handle both SQL text path and reducer json() path
    # The _call_with_result method calls resp.json()["result"]
    mock_http.post.return_value = Mock(
        status_code=200,
        text=json.dumps([]),
        json=lambda: {"result": json.dumps([])},
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

    wasm_opt = (
        module_dir / "target" / "wasm32-unknown-unknown" / "release" / "spacetime_memory.opt.wasm"
    )
    wasm_plain = (
        module_dir / "target" / "wasm32-unknown-unknown" / "release" / "spacetime_memory.wasm"
    )
    # Prefer the NEWEST artifact — .opt.wasm can be a stale leftover.
    if wasm_opt.exists() and wasm_plain.exists():
        wasm_path = wasm_plain if wasm_plain.stat().st_mtime > wasm_opt.stat().st_mtime else wasm_opt
    elif wasm_plain.exists():
        wasm_path = wasm_plain
    else:
        wasm_path = wasm_opt
    if not wasm_path.exists():
        raise RuntimeError(
            f"WASM module not found at {wasm_path}. "
            "Build it first with: "
            "cd server/spacetimedb && cargo build --target wasm32-unknown-unknown --release "
            "(or `make build` from the repo root), or set SPACETIMEDB_DB to the "
            "name/identity of an already-published database to skip publishing."
        )

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
        pytest.skip(
            "SpacetimeDB standalone not running on localhost:3001. "
            "Set SPACETIMEDB_HOST to force-enable integration tests."
        )

    # Honour SPACETIMEDB_DB: when set, use the already-published database
    # instead of publishing a fresh anonymous one.  Useful when the WASM
    # artifact is unavailable (e.g. no Rust toolchain) but a compatible
    # database is already running.
    db_override = os.environ.get("SPACETIMEDB_DB", "")
    if db_override:
        db_identity = db_override
    else:
        # Check WASM binary exists before attempting to publish — prefer the
        # NEWEST artifact. The .opt.wasm can be a stale leftover from an
        # earlier wasm-opt pass and would silently publish outdated code.
        module_dir = _repo_root / "server" / "spacetimedb"
        wasm_opt = module_dir / "target" / "wasm32-unknown-unknown" / "release" / "spacetime_memory.opt.wasm"
        wasm_plain = module_dir / "target" / "wasm32-unknown-unknown" / "release" / "spacetime_memory.wasm"
        if wasm_opt.exists() and wasm_plain.exists():
            wasm_path = wasm_plain if wasm_plain.stat().st_mtime > wasm_opt.stat().st_mtime else wasm_opt
        elif wasm_plain.exists():
            wasm_path = wasm_plain
        else:
            wasm_path = wasm_opt
        if not wasm_path.exists():
            pytest.skip(
                "WASM module not built -- run 'cd server/spacetimedb && cargo build --target wasm32-unknown-unknown --release' (or set SPACETIMEDB_DB to an already-published database identity to skip publishing)."
            )
        # Publish the module -- each test session creates its own anonymous
        # database identity so it NEVER touches the production database.
        # Use --delete-data=never to be safe (the anonymous identity is unique
        # per session anyway, so deletion is a no-op, but this guards against
        # any future code changes that could reuse the same identity).
        db_identity = _publish_module(delete_data="never")

    return {
        "host": os.environ.get("SPACETIMEDB_HOST", "localhost"),
        "port": os.environ.get("SPACETIMEDB_PORT", "3001"),
        "database": db_identity,
    }


@pytest.fixture(scope="session")
def _admin_token(stdb_session) -> str:
    """Session-scoped: register a single admin identity for all tests.

    Returns the identity token that should be injected into every stdb_client
    fixture. This ensures *all* tests in the session share the same admin
    identity, so admin-requiring reducers (dedup, maintenance, communities,
    etc.) work beyond the first test.
    """
    c = Client(
        host=stdb_session["host"],
        port=stdb_session["port"],
        database=stdb_session["database"],
    )

    import os

    suffix = os.urandom(4).hex()
    uname = f"admin_test_{suffix}"
    try:
        c._call("register", [uname, "Test Admin", "testpass"])
    except RuntimeError:
        pass  # already registered

    my_id = c._whoami()
    if my_id:
        try:
            c._call("set_initial_admin", [my_id])
        except RuntimeError:
            pass  # admin already exists

    return c._identity_token if c._identity_token else "anonymous"


@pytest.fixture
def stdb_client(stdb_session, _admin_token) -> Client:
    """Create a Client connected to the published database, pre-authenticated
    as admin.

    All tests in the session share the same admin identity, so admin-requiring
    reducers work regardless of test execution order.
    """
    c = Client(
        host=stdb_session["host"],
        port=stdb_session["port"],
        database=stdb_session["database"],
    )

    # Inject the session-scoped admin identity token
    if _admin_token and _admin_token != "anonymous":
        c._identity_token = _admin_token
        c._identity_established = True

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
def mock_compounder():
    """Mock the ``Compounder`` class used inside MCP tools.

    Patches ``spacetime_memory.compounder.Compounder`` so that
    ``Compounder(get_client())`` returns a MagicMock in MCP tool bodies.
    Tests can set return values and assert calls on the yielded instance.
    """
    with patch("spacetime_memory.compounder.Compounder") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        yield instance


@pytest.fixture
def mock_mcp_client():
    """Mock ``get_client()`` in MCP tools for testing graph/pagerank tools.

    Patches ``server.mcp.tools.app.get_client`` so MCP tools that call
    ``get_client().<method>()`` get a MagicMock.  Tests can set return
    values and assert calls on ``get_client().<method>`` via the yielded
    instance.
    """
    with patch("server.mcp.tools.app.get_client") as mock_fn:
        instance = MagicMock()
        mock_fn.return_value = instance
        yield instance


@pytest.fixture
def mock_app_get_client():
    """Mock ``get_client()`` from ``server.mcp.tools.app``.

    The domain tool modules (context, admin, agent, directory, documents)
    import ``get_client`` from ``server.mcp.tools.app``.  This fixture
    patches that specific import path so unit tests can verify delegation
    without a real SpacetimeDB connection.
    """
    with patch("server.mcp.tools.app.get_client") as mock_fn:
        instance = MagicMock()
        mock_fn.return_value = instance
        yield instance


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

    def _post_side_effect(url, *args, **kwargs):
        """Return different mock responses depending on the URL."""
        url_str = str(url)
        # Tantivy search expects a JSON list
        if ":9091" in url_str or "tantivy" in url_str.lower():
            return Mock(
                status_code=200,
                text=json.dumps([]),
                json=list,
            )
        # All other POST (STDB reducers, embedder) — return the
        # embedding response that _embed_openai expects
        return Mock(
            status_code=200,
            text=json.dumps([]),
            # Return a valid OpenAI embedding structure so _embed_openai
            # doesn't choke on resp.json()["data"][0]["embedding"].
            json=lambda: {"data": [{"embedding": [0.0]}]},
        )

    mock_http.post.side_effect = _post_side_effect
    mock_http.get.return_value = Mock(
        status_code=200,
        json=lambda: {"model": "mock"},
    )
    client._http = mock_http
    return client


@pytest.fixture
def mocked_cli_runner(monkeypatch, cli_mock_client):
    """A CliRunner where the CLI's ``_sdk_client`` returns a mocked Client.

    Patches ``_sdk_client`` in the root module AND in every already-imported
    command module (which import ``_sdk_client`` at load time into their own
    namespace via ``from ..root import _sdk_client``).

    Returns (runner, mock_client) tuple.
    """
    import sys
    import types

    from click.testing import CliRunner

    def mock_fn(**kw):
        return cli_mock_client

    # Patch the canonical source
    monkeypatch.setattr("cli.stmem._sdk_client", mock_fn)
    monkeypatch.setattr("cli.stmem.root._sdk_client", mock_fn)

    # Patch every already-imported command module that holds a local reference
    for mod_name, mod in list(sys.modules.items()):
        if (mod_name.startswith("cli.stmem.commands")
                or mod_name == "cli.stmem.root"
                or mod_name == "cli.stmem"
                or mod_name.startswith("spacetime_memory.")):
            if isinstance(mod, types.ModuleType) and hasattr(mod, "_sdk_client"):
                monkeypatch.setattr(mod, "_sdk_client", mock_fn)

    return CliRunner(), cli_mock_client


# ---------------------------------------------------------------------------
# Shared connector test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def connector_clean_cursors():
    """Remove cursor dir so each connector test starts fresh.

    Connector cursor state persists across test runs in
    ``~/.spacetime-memory/connectors/``.  This fixture tears it down
    before every test so dedup / state-dependent assertions are reliable.
    Returns the cursor directory path for assertion use.
    """
    import shutil

    cursor_dir = os.path.expanduser("~/.spacetime-memory/connectors")
    if os.path.exists(cursor_dir):
        shutil.rmtree(cursor_dir, ignore_errors=True)
    return cursor_dir


def make_mock_response(status_code=200, json_data=None, text="", headers=None):
    """Build a standardised ``Mock(spec=httpx.Response)`` for connector tests.

    Parameters
    ----------
    status_code : int
        HTTP status code (default 200).
    json_data : any, optional
        Value returned by ``.json()``.  If a plain dict is passed,
        ``.json()`` returns it directly.  If it's a callable the callable
        is used as ``side_effect``.
    text : str
        Raw text for ``.text`` attribute (default ``""``).
    headers : dict, optional
        Response headers (default ``{}``).

    Returns
    -------
    Mock
        A mock with ``status_code``, ``text``, and ``json`` set up.
    """
    from unittest.mock import Mock

    resp = Mock(status_code=status_code)
    resp.text = text
    if callable(json_data):
        resp.json.side_effect = json_data
    else:
        resp.json.return_value = json_data
    resp.headers = headers or {}
    return resp


# ---------------------------------------------------------------------------
# Honcho adapter integration-test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def honcho_host() -> str:
    return os.environ.get("SPACETIMEDB_HOST", "localhost")


@pytest.fixture(scope="module")
def honcho_port() -> int:
    return int(os.environ.get("SPACETIMEDB_PORT", "3001"))


@pytest.fixture
def honcho(honcho_host: str, honcho_port: int, stdb_session: dict) -> Iterator[Honcho]:
    """Fresh Honcho client with unique workspace per test."""
    uid = uuid.uuid4().hex[:12]
    ws_id = f"test-{uid}"

    # Register identity and create workspace so store_memory's ACL passes
    reg = Client(
        host=honcho_host,
        port=honcho_port,
        database=stdb_session["database"],
    )
    try:
        reg._call("register", [f"honcho-{uid}", "Honcho Test", "pw"])
    except RuntimeError:
        pass
    try:
        reg._call("create_workspace", ["honcho-test", "auto", ws_id])
    except RuntimeError:
        pass
    identity_token = reg._identity_token or ""

    h = Honcho(
        workspace_id=ws_id,
        stdb_host=honcho_host,
        stdb_port=honcho_port,
        stdb_database=stdb_session["database"],
        api_key=identity_token or None,
    )
    yield h
    h.close()


def honcho_uid(prefix: str = "honcho-test") -> str:
    """Generate a unique ID for Honcho adapter tests."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
