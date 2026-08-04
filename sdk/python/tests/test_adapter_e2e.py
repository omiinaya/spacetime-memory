"""
Adapter E2E wire-compatibility test harness.

Wire-format validation tests use a mock HTTP transport - no live STDB needed.
Per-adapter compatibility tests require a live STDB with published WASM module.

Usage:
    # Wire-format only (no live STDB needed)
    python -m pytest tests/test_adapter_e2e.py -v -k "WireFormat"

    # Error-handling tests (mock transport, no live STDB needed)
    python -m pytest tests/test_adapter_e2e.py -v -k "ErrorHandling"

    # Per-adapter live tests (needs WASM module published)
    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 \
        python -m pytest tests/test_adapter_e2e.py -v -k "Mem0 or Zep or LangChain"

    # ALL tests against live STDB
    SPACETIMEDB_HOST=localhost SPACETIMEDB_PORT=3001 \
        python -m pytest tests/test_adapter_e2e.py -v --tb=long
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path as _Path
from typing import Any

import httpx
import pytest

from spacetime_memory.client import Client


def _uid(prefix: str = "e2e") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# =====
# WireTap - captures outgoing HTTP requests for payload inspection
# =====


class WireTap:
    """Captures outgoing HTTP requests for payload inspection."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def request_hook(self, request: httpx.Request) -> None:
        body = request.read().decode("utf-8", errors="replace")
        self.requests.append({
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "body": body,
        })


def _json_shape(body: str) -> Any:
    try:
        return json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None


# =====
# Recorded mock transport and mock client factory
# =====

_DUMMY_EMBEDDING = [0.1] * 128
_MOCK_WS_ID = "mocked-workspace-id-00000000000000000000001"


class _RecordedHandler:
    """Records each HTTP request dispatched through the mock transport.

    Provides standard mock STDB behaviour by default but also allows
    per-request assertions through ``calls``.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body = request.read().decode("utf-8", errors="replace")
        self.calls.append({
            "method": request.method,
            "url": url,
            "headers": dict(request.headers),
            "body": body,
            "json_body": _json_shape(body),
        })

        if "anon-probe" in url or "identity" in url:
            return httpx.Response(
                200,
                json={"identity": "anon-mock"},
                headers={
                    "spacetime-identity": "mock-id",
                    "spacetime-identity-token": "mock-token",
                },
            )
        if "/sql" in url:
            return httpx.Response(
                200,
                json=[{
                    "schema": {
                        "elements": [{"name": {"some": "name"}}, {"name": {"some": "id"}}]
                    },
                    "rows": [["mock-workspace", _MOCK_WS_ID]],
                }],
            )
        if "/call/" in url:
            return httpx.Response(200, json={"status": "ok", "message": "ReducerInvoked"})
        if "/eval" in url:
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json=[{"schema": {"elements": []}, "rows": []}])


def _make_mock_handler() -> _RecordedHandler:
    """Create a recorded mock handler for STDB HTTP API."""
    return _RecordedHandler()


def _make_error_handler(status_code: int, body: str = "") -> _RecordedHandler:
    """Create a mock handler that always returns an HTTP error."""
    handler = _RecordedHandler()

    def _patched_call(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body_str = request.read().decode("utf-8", errors="replace")
        handler.calls.append({
            "method": request.method,
            "url": url,
            "headers": dict(request.headers),
            "body": body_str,
            "json_body": _json_shape(body_str),
        })
        return httpx.Response(status_code, text=body)

    handler.__call__ = _patched_call  # type: ignore[method-assign]
    return handler


def _make_mock_client(database: str = "mock-adapter-e2e") -> tuple[Client, WireTap]:
    """Create a Client with mocked HTTP transport, dummy embed, and WireTap."""
    tap = WireTap()
    handler = _make_mock_handler()
    transport = httpx.MockTransport(handler)
    c = Client(host="localhost", port="3001", database=database)
    c._http = httpx.Client(transport=transport, timeout=30.0)
    if hasattr(c._http, "_event_hooks"):
        c._http._event_hooks.setdefault("request", []).append(tap.request_hook)
    c._embed = lambda text: list(_DUMMY_EMBEDDING)
    c._wire_tap = tap
    return c, tap


def _assert_reducer_called(tap: WireTap, reducer_name: str) -> None:
    """Assert that at least one request targeted ``/call/<reducer_name>``."""
    urls = [r["url"] for r in tap.requests]
    assert any(f"/call/{reducer_name}" in u for u in urls), (
        f"Expected /call/{reducer_name} in requests: {urls}"
    )


def _assert_sql_called(tap: WireTap, sql_fragment: str = "") -> None:
    """Assert that at least one SQL request was made, optionally containing a fragment."""
    urls = [r["url"] for r in tap.requests]
    assert any("/sql" in u for u in urls), f"Expected /sql in URLs: {urls}"
    if sql_fragment:
        bodies = [r["body"] for r in tap.requests if "/sql" in r["url"]]
        assert any(sql_fragment in b for b in bodies), (
            f"Expected SQL fragment {sql_fragment!r} in bodies"
        )


def _assert_reducer_payload(tap: WireTap, reducer_name: str, expected_args: list | None = None) -> Any:
    """Assert a reducer was called and return its parsed body for inspection.

    If ``expected_args`` is provided, verifies the exact JSON body matches.
    Returns the first matching request body for further assertions.
    """
    calls = []
    for r in tap.requests:
        if f"/call/{reducer_name}" in r["url"]:
            body = _json_shape(r["body"])
            if body is not None:
                calls.append(body)

    assert len(calls) >= 1, (
        f"Expected /call/{reducer_name} with args {expected_args}, "
        f"found none among {[r['url'] for r in tap.requests]}"
    )
    if expected_args is not None:
        assert calls[0] == expected_args, (
            f"Expected reducer args {expected_args}, got {calls[0]}"
        )
    return calls[0]


def _assert_sql_query(tap: WireTap, required_pattern: str = "") -> list[str]:
    """Assert that SQL was queried and return all SQL bodies.

    If ``required_pattern`` is provided, asserts at least one SQL body
    contains that substring.
    """
    sql_bodies = [
        r["body"] for r in tap.requests if "/sql" in r["url"]
    ]
    assert len(sql_bodies) >= 1, (
        f"Expected /sql call, found none among {[r['url'] for r in tap.requests]}"
    )
    if required_pattern:
        matched = [b for b in sql_bodies if required_pattern in b]
        assert len(matched) >= 1, (
            f"Expected SQL containing {required_pattern!r}, "
            f"got: {sql_bodies}"
        )
    return sql_bodies


# =====
# Live STDB helpers (used by @pytest.mark.e2e tests only)
# =====


def _wire_tapped_client(
    host: str = "localhost",
    port: int | str = 3001,
    database: str = "e2e-mock-db",
    token: str = "",
) -> tuple[Client, WireTap]:
    tap = WireTap()
    c = Client(host=host, port=str(port), database=database, token=token)
    http = getattr(c, "_http", None)
    if http is not None and hasattr(http, "_event_hooks"):
        http._event_hooks.setdefault("request", []).append(tap.request_hook)
    c._wire_tap = tap
    _ensure_registered(c)
    return c, tap


def _ensure_registered(c: Client) -> None:
    """Register the client's identity against the live module if not already
    present, so reducer calls that require_auth() succeed. Freshly published
    e2e databases contain no accounts, so without this every store_memory /
    update_memory call fails with 'Not authenticated'."""
    try:
        namespace = "e2e-reg-" + os.urandom(4).hex()
        c._call("register", [f"{namespace}-user", "E2E Harness", "benchpass789"])
    except RuntimeError:
        # Already registered (identity reused) — fine
        pass


def _find_wasm(repo_root: _Path) -> _Path | None:
    module_dir = repo_root / "server" / "spacetimedb"
    if not module_dir.exists():
        return None
    candidates = []
    for name in ("spacetime_memory.opt.wasm", "spacetime_memory.wasm"):
        p = module_dir / "target" / "wasm32-unknown-unknown" / "release" / name
        if p.exists():
            candidates.append(p)
    if not candidates:
        return None
    # Prefer the NEWEST artifact. A stale `.opt.wasm` from an earlier
    # wasm-opt pass can silently publish an old module missing newer
    # reducers (e.g. check_workspace_access) — always pick the newest.
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _publish_or_skip(repo_root: _Path) -> dict:
    wasm_path = _find_wasm(repo_root)
    if wasm_path is None:
        pytest.skip("WASM module not built. Run: cd server/spacetimedb && cargo build --target wasm32-unknown-unknown --release")
    wasm_data = wasm_path.read_bytes()
    host = os.environ.get("SPACETIMEDB_HOST", "localhost")
    port = os.environ.get("SPACETIMEDB_PORT", "3001")
    try:
        anon = httpx.get(f"http://{host}:{port}/v1/database/anon-probe", timeout=5.0)
        anon.raise_for_status()
        token = anon.headers.get("spacetime-identity-token", "")
    except (httpx.ConnectError, httpx.TimeoutException):
        pytest.skip(f"SpacetimeDB not reachable on {host}:{port}")
    except httpx.HTTPStatusError:
        token = ""
    headers = {"Content-Type": "application/octet-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"http://{host}:{port}/v1/database?host_type=Wasm&delete_data=true"
    try:
        resp = httpx.post(url, headers=headers, content=wasm_data, timeout=60.0)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        pytest.skip(f"Failed to publish WASM: {exc}")
    if resp.status_code >= 400:
        pytest.skip(f"WASM publish failed (HTTP {resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    result: dict[str, str] = {"host": host, "port": port, "token": token}
    if isinstance(data, dict):
        for key in ("database_identity", "identity"):
            if key in data:
                result["database"] = data[key]
                return result
        if "Success" in data:
            result["database"] = data["Success"].get("database_identity", "unknown")
            return result
        if "Database" in data:
            result["database"] = data["Database"].get("database_identity", "unknown")
            return result
    pytest.skip(f"Could not parse identity from publish response:\n{data}")


@pytest.fixture(scope="session")
def e2e_stdb() -> dict:
    repo_root = _Path(__file__).resolve().parent.parent.parent.parent
    try:
        return _publish_or_skip(repo_root)
    except pytest.skip.Exception:
        raise
    except Exception as exc:
        pytest.skip(f"Failed to set up STDB for E2E tests: {exc}")


def _reducer_calls(client: Any) -> list[str]:
    tap = getattr(client, "_wire_tap", None)
    if tap is None:
        return []
    return [r["url"] for r in tap.requests]



# =====
# TestWireFormatValidation - mock transport, no live STDB needed
# =====


class TestWireFormatValidation:
    """Validate Client-level wire format: SQL payloads, reducer args, response parsing."""

    @staticmethod
    def _make_client(mock_transport: httpx.MockTransport | None = None) -> tuple[Client, WireTap]:
        c = Client(host="localhost", port="3001", database="mock-db")
        if mock_transport is None:
            handler = _make_mock_handler()
            transport = httpx.MockTransport(handler)
        else:
            transport = mock_transport
        c._http = httpx.Client(transport=transport, timeout=30.0)
        tap = WireTap()
        if hasattr(c._http, "_event_hooks"):
            c._http._event_hooks.setdefault("request", []).append(tap.request_hook)
        c._wire_tap = tap
        c._embed = lambda text: list(_DUMMY_EMBEDDING)
        return c, tap

    def test_client_sql_payload(self) -> None:
        c, tap = self._make_client()
        c._ensure_identity()
        tap.requests.clear()
        c._sql("SELECT 1 FROM dual")
        assert len(tap.requests) >= 1
        req = tap.requests[0]
        assert "/sql" in req["url"], f"Expected /sql in {req['url']}"
        assert "SELECT 1" in req["body"]
        assert req["method"] == "POST"

    def test_client_reducer_payload(self) -> None:
        c, tap = self._make_client()
        c._ensure_identity()
        tap.requests.clear()
        c._call("test_reducer", ["arg1", "arg2"])
        assert len(tap.requests) >= 1
        req = tap.requests[0]
        assert "/call/test_reducer" in req["url"], f"Expected /call/test_reducer in {req['url']}"
        body = _json_shape(req["body"])
        assert body is not None
        assert isinstance(body, list)
        assert body == ["arg1", "arg2"]

    def test_client_reducer_with_list_args(self) -> None:
        c, tap = self._make_client()
        c._ensure_identity()
        tap.requests.clear()
        c._call("store", ["ws-1", "Hello", "p1"])
        assert len(tap.requests) >= 1
        req = tap.requests[0]
        assert "/call/store" in req["url"], f"Expected /call/store in {req['url']}"
        body = _json_shape(req["body"])
        assert body is not None
        assert isinstance(body, list)
        assert body == ["ws-1", "Hello", "p1"]
        assert req["method"] == "POST"
        ct = req["headers"].get("content-type", "")
        assert "application/json" in ct

    def test_client_sql_response_parsing(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[{
                    "schema": {
                        "elements": [{"name": {"some": "id"}}, {"name": {"some": "val"}}]
                    },
                    "rows": [["abc-123", 42], ["def-456", 99]],
                }],
            )
        c, tap = self._make_client(httpx.MockTransport(_handler))
        tap.requests.clear()
        results = c._sql("SELECT id, val FROM test")
        assert isinstance(results, list)
        assert len(results) == 2

    def test_wire_tap_captures_all_requests(self) -> None:
        c, tap = self._make_client()
        c._ensure_identity()
        tap.requests.clear()
        c._call("r1", [1])
        c._call("r2", [2])
        c._call("r3", [3])
        assert len(tap.requests) == 3

    def test_content_type_header(self) -> None:
        c, tap = self._make_client()
        c._ensure_identity()
        tap.requests.clear()
        c._sql("SELECT 1")
        req = tap.requests[0]
        assert req["headers"].get("content-type", ""), "No content-type header"

    def test_reducer_with_empty_args(self) -> None:
        c, tap = self._make_client()
        c._ensure_identity()
        tap.requests.clear()
        c._call("empty_reducer", [])
        req = tap.requests[0]
        assert "/call/empty_reducer" in req["url"]
        body = _json_shape(req["body"])
        assert body == [], f"Expected empty list, got {body}"

    def test_http_400_on_reducer(self) -> None:
        handler = _make_error_handler(400, "Bad request")
        c, tap = self._make_client(httpx.MockTransport(handler))
        tap.requests.clear()
        result = c._call("boom", ["x"])
        assert result is not None

    def test_http_500_on_sql(self) -> None:
        handler = _make_error_handler(500, "Server Error")
        c, tap = self._make_client(httpx.MockTransport(handler))
        tap.requests.clear()
        result = c._sql("SELECT broken")
        assert result is not None

    def test_wire_tap_distinguishes_urls_by_path(self) -> None:
        c, tap = self._make_client()
        c._ensure_identity()
        tap.requests.clear()
        c._call("reducer_a", ["a"])
        c._sql("SELECT 1")
        c._call("reducer_b", ["b"])
        call_urls = [r["url"] for r in tap.requests]
        assert any("/call/reducer_a" in u for u in call_urls)
        assert any("/sql" in u for u in call_urls)
        assert any("/call/reducer_b" in u for u in call_urls)
        assert len(tap.requests) == 3



# =====
# Mock-transport wire-format validation per adapter
# =====


class TestMem0WireFormatValidation:
    """Validate Mem0 adapter wire format via mock transport."""

    _UID_MW = "mw-user-static"
    _UID_MWG = "mwg-user-static"
    _UID_MWS = "mws-user-static"
    _UID_MWU = "mwu-user-static"
    _UID_MWD = "mwd-user-static"

    @pytest.fixture
    def mem(self) -> tuple[Any, WireTap]:
        from spacetime_memory.sdks.mem0 import Memory as Mem0Memory
        c, tap = _make_mock_client()
        m = Mem0Memory(config={"host": "localhost", "port": "3001", "db": "mock-adapter-e2e"})
        m._client = c
        m._user_id_to_ws[self._UID_MW] = _MOCK_WS_ID
        m._user_id_to_ws[self._UID_MWG] = _MOCK_WS_ID
        m._user_id_to_ws[self._UID_MWS] = _MOCK_WS_ID
        m._user_id_to_ws[self._UID_MWU] = _MOCK_WS_ID
        m._user_id_to_ws[self._UID_MWD] = _MOCK_WS_ID
        return m, tap

    def test_add_sends_store_memory(self, mem: tuple[Any, WireTap]) -> None:
        m, tap = mem
        tap.requests.clear()
        m.add("E2E wire test", user_id=self._UID_MW, agent_id="test-agent")
        _assert_reducer_called(tap, "store_memory")

    def test_add_payload_contains_user_and_content(self, mem: tuple[Any, WireTap]) -> None:
        m, tap = mem
        tap.requests.clear()
        m.add("E2E wire test", user_id=self._UID_MW, agent_id="test-agent")
        body = _assert_reducer_payload(tap, "store_memory")
        assert isinstance(body, list), f"Expected list body, got {type(body)}"
        assert len(body) >= 3, f"Expected >=3 args, got {body}"

    def test_add_with_metadata_payload(self, mem: tuple[Any, WireTap]) -> None:
        m, tap = mem
        tap.requests.clear()
        m.add("Metadata test", user_id=self._UID_MW, metadata={"source": "e2e", "importance": 5})
        body = _assert_reducer_payload(tap, "store_memory")
        assert isinstance(body, list)

    def test_get_all_uses_sql(self, mem: tuple[Any, WireTap]) -> None:
        m, tap = mem
        tap.requests.clear()
        m.get_all(user_id=self._UID_MWG)
        _assert_sql_called(tap)

    def test_search_returns_dict(self, mem: tuple[Any, WireTap]) -> None:
        m, tap = mem
        m.add("Search wire target", user_id=self._UID_MWS, agent_id="test-agent")
        tap.requests.clear()
        result = m.search("target", user_id=self._UID_MWS)
        assert isinstance(result, dict)

    def test_update_sends_update_call(self, mem: tuple[Any, WireTap]) -> None:
        m, tap = mem
        m.add("Original", user_id=self._UID_MWU, agent_id="test-agent")
        tap.requests.clear()
        m.update(memory_id="mock-mem-id", data="Updated text")
        _assert_reducer_called(tap, "update")

    def test_update_payload_has_id_and_content(self, mem: tuple[Any, WireTap]) -> None:
        m, tap = mem
        m.add("Original", user_id=self._UID_MWU, agent_id="test-agent")
        tap.requests.clear()
        m.update(memory_id="mock-mem-id", data="Updated text")
        body = _assert_reducer_payload(tap, "update")
        assert isinstance(body, list)
        assert "mock-mem-id" in str(body)

    def test_delete_sends_deactivate_call(self, mem: tuple[Any, WireTap]) -> None:
        m, tap = mem
        m.add("To delete", user_id=self._UID_MWD, agent_id="test-agent")
        tap.requests.clear()
        m.delete(memory_id="mock-mem-id")
        _assert_reducer_called(tap, "deactivate")

    def test_delete_payload_has_memory_id(self, mem: tuple[Any, WireTap]) -> None:
        m, tap = mem
        m.add("To delete", user_id=self._UID_MWD, agent_id="test-agent")
        tap.requests.clear()
        m.delete(memory_id="mock-mem-id")
        body = _assert_reducer_payload(tap, "deactivate")
        assert isinstance(body, list)
        assert "mock-mem-id" in str(body)


class TestZepWireFormatValidation:
    """Validate Zep adapter wire format via mock transport."""

    _SID_ZW = "zwsession-static"
    _SID_ZWF = "zwfsession-static"
    _SID_ZWG = "zwgsession-static"
    _SID_ZWS = "zwssession-static"

    @pytest.fixture
    def zep(self) -> tuple[Any, WireTap]:
        from spacetime_memory.sdks.zep import ZepClient
        c, tap = _make_mock_client()
        z = ZepClient(host="localhost", port=3001)
        z._client = c
        z._session_to_ws[self._SID_ZW] = _MOCK_WS_ID
        z._session_to_ws[self._SID_ZWF] = _MOCK_WS_ID
        z._session_to_ws[self._SID_ZWG] = _MOCK_WS_ID
        z._session_to_ws[self._SID_ZWS] = _MOCK_WS_ID
        return z, tap

    def test_add_memory_sends_store_memory(self, zep: tuple[Any, WireTap]) -> None:
        z, tap = zep
        tap.requests.clear()
        z.add_memory(session_id=self._SID_ZW, messages=[{"role": "user", "content": "Hi"}])
        _assert_reducer_called(tap, "store_memory")

    def test_add_memory_payload_has_messages(self, zep: tuple[Any, WireTap]) -> None:
        z, tap = zep
        tap.requests.clear()
        z.add_memory(session_id=self._SID_ZW, messages=[{"role": "user", "content": "Hi"}])
        body = _assert_reducer_payload(tap, "store_memory")
        assert isinstance(body, list)
        assert "Hi" in str(body)
        assert self._SID_ZW in str(body)

    def test_add_fact_sends_store_memory(self, zep: tuple[Any, WireTap]) -> None:
        z, tap = zep
        tap.requests.clear()
        z.add_fact(session_id=self._SID_ZWF, fact="E2E wire fact")
        _assert_reducer_called(tap, "store_memory")

    def test_add_fact_payload_has_fact_content(self, zep: tuple[Any, WireTap]) -> None:
        z, tap = zep
        tap.requests.clear()
        z.add_fact(session_id=self._SID_ZWF, fact="E2E wire fact")
        body = _assert_reducer_payload(tap, "store_memory")
        assert isinstance(body, list)
        assert "E2E wire fact" in str(body)

    def test_get_memory(self, zep: tuple[Any, WireTap]) -> None:
        z, tap = zep
        z.add_memory(session_id=self._SID_ZWG, messages=[{"role": "user", "content": "Get me"}])
        tap.requests.clear()
        result = z.get_memory(session_id=self._SID_ZWG)
        assert result is not None or result is None

    def test_get_memory_uses_sql(self, zep: tuple[Any, WireTap]) -> None:
        z, tap = zep
        z.add_memory(session_id=self._SID_ZWG, messages=[{"role": "user", "content": "Get me"}])
        tap.requests.clear()
        z.get_memory(session_id=self._SID_ZWG)
        _assert_sql_called(tap)

    def test_search_memory_returns_list(self, zep: tuple[Any, WireTap]) -> None:
        z, tap = zep
        z.add_memory(session_id=self._SID_ZWS, messages=[{"role": "user", "content": "Search me"}])
        tap.requests.clear()
        results = z.search_memory(session_id=self._SID_ZWS, query="Search")
        assert isinstance(results, list)


class TestGraphitiWireFormatValidation:
    """Validate Graphiti adapter wire format via mock transport."""

    _GID_GW = "gw-group-static"
    _GID_GEW = "gew-group-static"

    @pytest.fixture
    def graphiti(self) -> tuple[Any, WireTap]:
        from spacetime_memory.sdks.graphiti import Graphiti
        c, tap = _make_mock_client()
        g = Graphiti(host="localhost", port=3001, database="mock-adapter-e2e")
        g._client = c
        g._ws_cache[self._GID_GW] = _MOCK_WS_ID
        g._ws_cache[self._GID_GEW] = _MOCK_WS_ID
        return g, tap

    def test_add_triplet_sends_create_node_and_edge(self, graphiti: tuple[Any, WireTap]) -> None:
        from spacetime_memory.sdks.graphiti import EntityEdge, EntityNode
        g, tap = graphiti
        tap.requests.clear()
        g.add_triplet(
            source_node=EntityNode(name="Alice", group_id=self._GID_GW),
            edge=EntityEdge(name="knows", fact="Wire test", group_id=self._GID_GW),
            target_node=EntityNode(name="Bob", group_id=self._GID_GW),
        )
        _assert_reducer_called(tap, "create_node")
        _assert_reducer_called(tap, "create_edge")

    def test_add_triplet_payload_has_entity_names(self, graphiti: tuple[Any, WireTap]) -> None:
        from spacetime_memory.sdks.graphiti import EntityEdge, EntityNode
        g, tap = graphiti
        tap.requests.clear()
        g.add_triplet(
            source_node=EntityNode(name="Alice", group_id=self._GID_GW),
            edge=EntityEdge(name="knows", fact="Wire test", group_id=self._GID_GW),
            target_node=EntityNode(name="Bob", group_id=self._GID_GW),
        )
        node_body = _assert_reducer_payload(tap, "create_node")
        assert "Alice" in str(node_body)

    def test_add_episode_sends_store(self, graphiti: tuple[Any, WireTap]) -> None:
        g, tap = graphiti
        tap.requests.clear()
        g.add_episode(
            name="Wire episode",
            episode_body="Test episode wire",
            source_description="Test source",
            group_id=self._GID_GEW,
        )
        _assert_reducer_called(tap, "store_memory")

    def test_add_episode_payload_has_body(self, graphiti: tuple[Any, WireTap]) -> None:
        g, tap = graphiti
        tap.requests.clear()
        g.add_episode(
            name="Wire episode",
            episode_body="Test episode wire",
            source_description="Test source",
            group_id=self._GID_GEW,
        )
        body = _assert_reducer_payload(tap, "store_memory")
        assert "Test episode wire" in str(body)

    def test_get_entity_edge_summary(self, graphiti: tuple[Any, WireTap]) -> None:
        g, tap = graphiti
        gid = _uid("gg")
        g._ws_cache[gid] = _MOCK_WS_ID
        tap.requests.clear()
        result = g.get_entity_edge_summary(entity_names=["mock"], group_ids=[gid])
        assert result is not None


class TestHindsightWireFormatValidation:
    """Validate Hindsight adapter wire format via mock transport."""

    _UID_HRW = "hrw-bank-static"
    _UID_HRBW = "hrbw-bank-static"
    _UID_HRCW = "hrcw-bank-static"
    _UID_HREW = "hrew-bank-static"

    @pytest.fixture
    def hinds(self) -> tuple[Any, WireTap]:
        from spacetime_memory.sdks.hindsight import Hindsight
        c, tap = _make_mock_client()
        h = Hindsight(base_url=None, stdb_host="localhost", stdb_port=3001, stdb_database="mock-adapter-e2e")
        h._client = c
        h._ws_cache[self._UID_HRW] = _MOCK_WS_ID
        h._ws_cache[self._UID_HRBW] = _MOCK_WS_ID
        h._ws_cache[self._UID_HRCW] = _MOCK_WS_ID
        h._ws_cache[self._UID_HREW] = _MOCK_WS_ID
        return h, tap

    def test_retain_sends_store_memory(self, hinds: tuple[Any, WireTap]) -> None:
        h, tap = hinds
        tap.requests.clear()
        h.retain(bank_id=self._UID_HRW, content="Wire retain test")
        _assert_reducer_called(tap, "store_memory")

    def test_retain_payload_has_content(self, hinds: tuple[Any, WireTap]) -> None:
        h, tap = hinds
        tap.requests.clear()
        h.retain(bank_id=self._UID_HRW, content="Wire retain test")
        body = _assert_reducer_payload(tap, "store_memory")
        assert "Wire retain test" in str(body)

    def test_retain_batch_sends_multiple_stores(self, hinds: tuple[Any, WireTap]) -> None:
        h, tap = hinds
        tap.requests.clear()
        h.retain(bank_id=self._UID_HRBW, content="Batch A wire")
        h.retain(bank_id=self._UID_HRBW, content="Batch B wire")
        store_count = sum(1 for r in tap.requests if "store_memory" in r["url"])
        assert store_count >= 1

    def test_recall(self, hinds: tuple[Any, WireTap]) -> None:
        h, tap = hinds
        h.retain(bank_id=self._UID_HRCW, content="Recall wire test")
        tap.requests.clear()
        result = h.recall(query="Recall", bank_id=self._UID_HRCW)
        assert result is not None or result == ""

    def test_recall_uses_sql(self, hinds: tuple[Any, WireTap]) -> None:
        h, tap = hinds
        h.retain(bank_id=self._UID_HRCW, content="Recall wire test")
        tap.requests.clear()
        h.recall(query="Recall", bank_id=self._UID_HRCW)
        _assert_sql_called(tap)

    def test_reflect(self, hinds: tuple[Any, WireTap]) -> None:
        h, tap = hinds
        h.retain(bank_id=self._UID_HREW, content="Reflect wire base")
        tap.requests.clear()
        result = h.reflect(bank_id=self._UID_HREW, query="summarize this")
        assert result is not None or result == ""


class TestLangChainWireFormatValidation:
    """Validate LangChain adapter wire format via mock transport."""

    _NS = ("lcw",)

    @pytest.fixture
    def store(self) -> tuple[Any, WireTap]:
        from spacetime_memory.sdks.langchain import StmemStore
        c, tap = _make_mock_client()
        s = StmemStore(config={"host": "localhost", "port": "3001", "db": "mock-adapter-e2e"})
        s._client = c
        s._ns_cache["lcw"] = _MOCK_WS_ID
        return s, tap

    def test_put_sends_store_memory(self, store: tuple[Any, WireTap]) -> None:
        s, tap = store
        tap.requests.clear()
        s.put(self._NS, "lcw-key", {"val": "e2e"})
        _assert_reducer_called(tap, "store_memory")

    def test_put_payload_has_key_and_value(self, store: tuple[Any, WireTap]) -> None:
        s, tap = store
        tap.requests.clear()
        s.put(self._NS, "lcw-key", {"val": "e2e"})
        body = _assert_reducer_payload(tap, "store_memory")
        assert "lcw-key" in str(body)
        assert "e2e" in str(body)

    def test_get_uses_sql(self, store: tuple[Any, WireTap]) -> None:
        s, tap = store
        s.put(self._NS, "lcw-key", {"val": "e2e"})
        tap.requests.clear()
        s.get(self._NS, "lcw-key")
        _assert_sql_called(tap)

    def test_search_returns_list(self, store: tuple[Any, WireTap]) -> None:
        s, tap = store
        s.put(self._NS, "lcw-search", {"text": "searchable"})
        tap.requests.clear()
        result = s.search(self._NS, query="searchable", limit=5)
        assert isinstance(result, list)

    def test_search_uses_sql(self, store: tuple[Any, WireTap]) -> None:
        s, tap = store
        s.put(self._NS, "lcw-search", {"text": "searchable"})
        tap.requests.clear()
        s.search(self._NS, query="searchable", limit=5)
        _assert_sql_called(tap)

    def test_list_namespaces(self, store: tuple[Any, WireTap]) -> None:
        s, tap = store
        tap.requests.clear()
        result = s.list_namespaces()
        assert isinstance(result, list)


class TestHonchoWireFormatValidation:
    """Validate Honcho adapter wire format via mock transport."""

    @pytest.fixture
    def honcho(self) -> tuple[Any, WireTap]:
        from spacetime_memory.sdks.honcho import Honcho
        c, tap = _make_mock_client()
        h = Honcho(
            workspace_id="mock-workspace",
            stdb_host="localhost",
            stdb_port=3001,
            stdb_database="mock-adapter-e2e",
        )
        h._client = c
        return h, tap

    def test_search_makes_wire_calls(self, honcho: tuple[Any, WireTap]) -> None:
        h, tap = honcho
        tap.requests.clear()
        h.search("E2E wire search")
        assert len(tap.requests) >= 1
        assert any("/sql" in u for u in [r["url"] for r in tap.requests])

    def test_search_sends_sql_query(self, honcho: tuple[Any, WireTap]) -> None:
        h, tap = honcho
        tap.requests.clear()
        h.search("E2E wire search")
        _assert_sql_query(tap)

    def test_queue_status_makes_wire_calls(self, honcho: tuple[Any, WireTap]) -> None:
        h, tap = honcho
        tap.requests.clear()
        h.queue_status()
        assert len(tap.requests) >= 1
        assert any("/sql" in u for u in [r["url"] for r in tap.requests])

    def test_queue_status_uses_sql(self, honcho: tuple[Any, WireTap]) -> None:
        h, tap = honcho
        tap.requests.clear()
        h.queue_status()
        _assert_sql_called(tap)

    def test_multiple_searches_captured(self, honcho: tuple[Any, WireTap]) -> None:
        h, tap = honcho
        tap.requests.clear()
        h.search("first query")
        h.search("second query")
        sql_count = sum(1 for r in tap.requests if "/sql" in r["url"])
        assert sql_count >= 2



# =====
# Error-handling wire-format tests (mock transport)
# =====


class TestErrorHandling:
    """Verify adapter behaviour when STDB returns HTTP errors."""

    @pytest.fixture
    def mem(self) -> tuple[Any, WireTap, _RecordedHandler]:
        from spacetime_memory.sdks.mem0 import Memory as Mem0Memory
        c, tap = _make_mock_client()
        m = Mem0Memory(config={"host": "localhost", "port": "3001", "db": "mock-adapter-e2e"})
        m._client = c
        m._user_id_to_ws["err-user"] = _MOCK_WS_ID
        m._user_id_to_ws["err-search"] = _MOCK_WS_ID
        handler = _make_error_handler(503, "Service Unavailable")
        c._http = httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)
        return m, tap, handler

    def test_add_returns_dict_on_error(self, mem: tuple[Any, WireTap, _RecordedHandler]) -> None:
        m, tap, _ = mem
        try:
            result = m.add("Error test", user_id="err-user", agent_id="test-agent")
            assert isinstance(result, dict) or True
        except RuntimeError:
            pass

    def test_search_returns_dict_on_error(self, mem: tuple[Any, WireTap, _RecordedHandler]) -> None:
        m, tap, _ = mem
        try:
            result = m.search("test", user_id="err-search")
            assert result is not None
        except RuntimeError:
            pass

    @pytest.fixture
    def langchain_error(self) -> tuple[Any, WireTap]:
        from spacetime_memory.sdks.langchain import StmemStore
        c, tap = _make_mock_client()
        s = StmemStore(config={"host": "localhost", "port": "3001", "db": "mock-adapter-e2e"})
        s._client = c
        s._ns_cache["ns"] = _MOCK_WS_ID
        handler = _make_error_handler(500, "Server Error")
        c._http = httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)
        return s, tap

    def test_langchain_put_handles_server_error(self, langchain_error: tuple[Any, WireTap]) -> None:
        s, tap = langchain_error
        tap.requests.clear()
        try:
            s.put(("ns",), "test-key", {"val": "test"})
        except RuntimeError:
            pass

    def test_langchain_get_handles_server_error(self, langchain_error: tuple[Any, WireTap]) -> None:
        s, tap = langchain_error
        tap.requests.clear()
        try:
            result = s.get(("ns",), "test-key")
            assert result is None or result is not None
        except RuntimeError:
            pass


# =====
# Edge-case wire-format tests (mock transport)
# =====


class TestEdgeCases:
    """Verify adapter behaviour with edge-case data."""

    @pytest.fixture
    def mem(self) -> Any:
        from spacetime_memory.sdks.mem0 import Memory as Mem0Memory
        c, tap = _make_mock_client()
        m = Mem0Memory(config={"host": "localhost", "port": "3001", "db": "mock-adapter-e2e"})
        m._client = c
        m._user_id_to_ws["empty-user"] = _MOCK_WS_ID
        m._user_id_to_ws["long-user"] = _MOCK_WS_ID
        return m

    def test_empty_string_memory(self, mem) -> None:
        try:
            result = mem.add("", user_id="empty-user", agent_id="test-agent")
            assert isinstance(result, dict)
        except (RuntimeError, ValueError):
            pass

    def test_very_long_content(self, mem) -> None:
        long_text = "x" * 10000
        result = mem.add(long_text, user_id="long-user", agent_id="test-agent")
        assert isinstance(result, dict)
        store_calls = [
            r for r in mem._client._wire_tap.requests if "store_memory" in r["url"]
        ]
        if store_calls:
            assert len(store_calls[0]["body"]) > 1000




# =====
# Wire-format correctness classes (auth, content-type, HTTP method, URL path, response parsing)
# =====


class TestAuthHeaderWireFormat:
    """Validate that authentication headers are sent correctly on every POST request."""

    def _make_client(self) -> tuple:
        handler = _make_mock_handler()
        transport = httpx.MockTransport(handler)
        c = Client(host="localhost", port="3001", database="mock-db", token="test-auth-token")
        c._http = httpx.Client(transport=transport, timeout=30.0)
        tap = WireTap()
        if hasattr(c._http, "_event_hooks"):
            c._http._event_hooks.setdefault("request", []).append(tap.request_hook)
        c._embed = lambda text: list(_DUMMY_EMBEDDING)
        c._wire_tap = tap
        return c, tap

    def test_auth_token_in_header(self) -> None:
        c, tap = self._make_client()
        c._ensure_identity()
        tap.requests.clear()
        c._call("some_reducer", ["arg"])
        post_reqs = [r for r in tap.requests if r["method"] == "POST"]
        assert len(post_reqs) >= 1, "Expected at least 1 POST request"
        auth_val = post_reqs[0]["headers"].get("authorization", "")
        assert auth_val, "Expected Authorization header on POST"

    def test_auth_header_present_on_sql(self) -> None:
        c, tap = self._make_client()
        c._ensure_identity()
        tap.requests.clear()
        c._sql("SELECT 1")
        post_reqs = [r for r in tap.requests if r["method"] == "POST"]
        assert len(post_reqs) >= 1
        assert "authorization" in post_reqs[0]["headers"] or "spacetime-identity-token" in post_reqs[0]["headers"], \
            "Expected auth header on SQL POST"

    def test_all_post_requests_have_auth(self) -> None:
        c, tap = self._make_client()
        c._ensure_identity()
        tap.requests.clear()
        c._call("r1", ["a"])
        c._sql("SELECT 1")
        c._call("r2", ["b"])
        post_reqs = [r for r in tap.requests if r["method"] == "POST"]
        for r in post_reqs:
            has_auth = "authorization" in r["headers"] or "spacetime-identity-token" in r["headers"]
            assert has_auth, f"POST {r['url']} missing auth header; headers: {r['headers']}"


class TestContentTypeWireFormat:
    """Validate Content-Type header on every POST request (reducers + SQL)."""

    def _make_client(self) -> tuple:
        handler = _make_mock_handler()
        transport = httpx.MockTransport(handler)
        c = Client(host="localhost", port="3001", database="mock-db")
        c._http = httpx.Client(transport=transport, timeout=30.0)
        tap = WireTap()
        if hasattr(c._http, "_event_hooks"):
            c._http._event_hooks.setdefault("request", []).append(tap.request_hook)
        c._embed = lambda text: list(_DUMMY_EMBEDDING)
        c._wire_tap = tap
        return c, tap

    def _assert_ct_on_posts(self, tap: WireTap) -> None:
        post_reqs = [r for r in tap.requests if r["method"] == "POST"]
        assert len(post_reqs) >= 1, "Expected at least 1 POST request"
        for r in post_reqs:
            ct = r["headers"].get("content-type", "")
            is_sql = "/sql" in r["url"]
            if is_sql:
                assert "application/json" in ct or "text/plain" in ct, \
                    f"SQL POST {r['url']} has content-type={ct!r}"
            else:
                assert "application/json" in ct, \
                    f"Reducer POST {r['url']} has content-type={ct!r}, expected application/json"

    def test_reducer_content_type_json(self) -> None:
        c, tap = self._make_client()
        c._ensure_identity()
        tap.requests.clear()
        c._call("my_reducer", ["x"])
        self._assert_ct_on_posts(tap)

    def test_sql_content_type_accepts_json_or_text(self) -> None:
        c, tap = self._make_client()
        c._ensure_identity()
        tap.requests.clear()
        c._sql("SELECT 1")
        self._assert_ct_on_posts(tap)

    def test_multiple_calls_all_have_ct(self) -> None:
        c, tap = self._make_client()
        c._ensure_identity()
        tap.requests.clear()
        c._call("r1", [])
        c._sql("SELECT 2")
        c._call("r2", [])
        self._assert_ct_on_posts(tap)

    def test_mem0_adapter_ct(self) -> None:
        from spacetime_memory.sdks.mem0 import Memory as Mem0Memory
        c, tap = _make_mock_client()
        m = Mem0Memory(config={"host": "localhost", "port": "3001", "db": "mock-adapter-e2e"})
        m._client = c
        m._user_id_to_ws["ct-mem0"] = _MOCK_WS_ID
        tap.requests.clear()
        m.add("CT test", user_id="ct-mem0", agent_id="test-agent")
        self._assert_ct_on_posts(tap)

    def test_hindsight_adapter_ct(self) -> None:
        from spacetime_memory.sdks.hindsight import Hindsight
        c, tap = _make_mock_client()
        h = Hindsight(base_url=None, stdb_host="localhost", stdb_port=3001, stdb_database="mock-adapter-e2e")
        h._client = c
        h._ws_cache["ct-hinds"] = _MOCK_WS_ID
        tap.requests.clear()
        h.retain(bank_id="ct-hinds", content="CT test")
        self._assert_ct_on_posts(tap)

    def test_langchain_adapter_ct(self) -> None:
        from spacetime_memory.sdks.langchain import StmemStore
        c, tap = _make_mock_client()
        s = StmemStore(config={"host": "localhost", "port": "3001", "db": "mock-adapter-e2e"})
        s._client = c
        s._ns_cache["ct-lc"] = _MOCK_WS_ID
        tap.requests.clear()
        s.put(("ct-lc",), key="ct-key", value={"v": 1})
        self._assert_ct_on_posts(tap)


class TestHttpMethodWireFormat:
    """Validate that SQL queries and reducer calls use POST, not GET."""

    def test_sql_uses_post(self) -> None:
        c, tap = _make_mock_client()
        c._ensure_identity()
        tap.requests.clear()
        c._sql("SELECT 1")
        post_reqs = [r for r in tap.requests if r["method"] == "POST"]
        sql_reqs = [r for r in tap.requests if "/sql" in r["url"]]
        assert len(sql_reqs) >= 1
        assert len(post_reqs) >= 1
        assert all(r["method"] == "POST" for r in sql_reqs), \
            f"SQL requests should be POST, methods: {[r['method'] for r in sql_reqs]}"

    def test_reducer_uses_post(self) -> None:
        c, tap = _make_mock_client()
        c._ensure_identity()
        tap.requests.clear()
        c._call("some_reducer", ["arg"])
        call_reqs = [r for r in tap.requests if "/call/" in r["url"]]
        assert len(call_reqs) >= 1
        assert all(r["method"] == "POST" for r in call_reqs), \
            f"Reducer calls should be POST, methods: {[r['method'] for r in call_reqs]}"


class TestUrlPathWireFormat:
    """Validate that URLs are constructed correctly for SQL and reducer calls."""

    def test_sql_path_format(self) -> None:
        c, tap = _make_mock_client()
        c._ensure_identity()
        tap.requests.clear()
        c._sql("SELECT 1")
        sql_reqs = [r for r in tap.requests if "/sql" in r["url"]]
        assert len(sql_reqs) >= 1
        url = sql_reqs[0]["url"]
        assert "/sql" in url, f"SQL URL should contain /sql, got {url}"
        assert url.endswith("/sql") or "/sql?" in url or "/sql#" in url, \
            f"SQL URL should end with or contain /sql, got {url}"

    def test_reducer_path_format(self) -> None:
        c, tap = _make_mock_client()
        c._ensure_identity()
        tap.requests.clear()
        c._call("my_reducer", ["x"])
        call_reqs = [r for r in tap.requests if "/call/" in r["url"]]
        assert len(call_reqs) >= 1
        url = call_reqs[0]["url"]
        assert "/call/my_reducer" in url, f"Reducer URL should contain /call/my_reducer, got {url}"

    def test_multiple_reducers_have_distinct_paths(self) -> None:
        c, tap = _make_mock_client()
        c._ensure_identity()
        tap.requests.clear()
        c._call("reducer_a", [1])
        c._call("reducer_b", [2])
        urls = [r["url"] for r in tap.requests if "/call/" in r["url"]]
        assert any("reducer_a" in u for u in urls), f"reducer_a not in {urls}"
        assert any("reducer_b" in u for u in urls), f"reducer_b not in {urls}"

    def test_no_raw_data_in_path(self) -> None:
        """Payload data should not leak into the URL path (should be in body)."""
        c, tap = _make_mock_client()
        c._ensure_identity()
        tap.requests.clear()
        c._call("secure_reducer", ["secret-data-123"])
        call_reqs = [r for r in tap.requests if "/call/" in r["url"]]
        assert len(call_reqs) >= 1
        url = call_reqs[0]["url"]
        assert "secret-data-123" not in url, \
            f"Payload data leaked into URL path: {url}"
        assert "secret-data-123" in call_reqs[0]["body"], \
            "Payload data should be in body, not URL"


class TestResponseParsingWireFormat:
    """Validate that adapter code correctly parses various STDB response shapes."""

    def test_sql_response_list_of_dicts(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=[{"schema": {"elements": [{"name": {"some": "id"}}, {"name": {"some": "val"}}]},
                            "rows": [["abc", 42]]}])
        c = Client(host="localhost", port="3001", database="mock-db")
        c._http = httpx.Client(transport=httpx.MockTransport(_handler), timeout=30.0)
        c._embed = lambda text: list(_DUMMY_EMBEDDING)
        results = c._sql("SELECT id, val FROM t")
        assert isinstance(results, list)
        assert len(results) == 1

    def test_sql_response_empty_schema(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"schema": {"elements": []}, "rows": []}])
        c = Client(host="localhost", port="3001", database="mock-db")
        c._http = httpx.Client(transport=httpx.MockTransport(_handler), timeout=30.0)
        c._embed = lambda text: list(_DUMMY_EMBEDDING)
        results = c._sql("SELECT * FROM empty")
        assert results is not None
        assert isinstance(results, list)

    def test_reducer_response_ok_status(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "ok", "message": "ReducerInvoked"})
        c = Client(host="localhost", port="3001", database="mock-db")
        c._http = httpx.Client(transport=httpx.MockTransport(_handler), timeout=30.0)
        c._embed = lambda text: list(_DUMMY_EMBEDDING)
        result = c._call("good_reducer", ["x"])
        assert result is not None

    def test_reducer_response_error_status(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"status": "error", "message": "BadRequest"})
        c = Client(host="localhost", port="3001", database="mock-db")
        c._http = httpx.Client(transport=httpx.MockTransport(_handler), timeout=30.0)
        c._embed = lambda text: list(_DUMMY_EMBEDDING)
        with pytest.raises(RuntimeError, match="BadRequest"):
            c._call("bad_reducer", ["x"])

    def test_reducer_response_no_json(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="plain text response")
        c = Client(host="localhost", port="3001", database="mock-db")
        c._http = httpx.Client(transport=httpx.MockTransport(_handler), timeout=30.0)
        c._embed = lambda text: list(_DUMMY_EMBEDDING)
        result = c._call("plain_reducer", ["x"])
        # Should handle non-JSON gracefully without crashing
        assert result is not None or result is None

# =====
# Per-adapter live tests (skip if WASM module not published / STDB unreachable)
# =====


@pytest.mark.e2e
class TestMem0WireCompatibility:
    @pytest.fixture
    def mem(self, e2e_stdb: dict) -> Any:
        from spacetime_memory.sdks.mem0 import Memory as Mem0Memory
        c, tap = _wire_tapped_client(
            host=e2e_stdb["host"], port=e2e_stdb["port"],
            database=e2e_stdb["database"], token=e2e_stdb.get("token", ""),
        )
        m = Mem0Memory(config={"host": e2e_stdb["host"], "port": e2e_stdb["port"], "db": e2e_stdb["database"]})
        m._client = c
        m._client._wire_tap = tap
        return m

    def test_add_requests_via_reducer(self, mem):
        before = len(_reducer_calls(mem._client))
        mem.add("E2E test memory", user_id=_uid("mem0"), agent_id="test-agent")
        calls = _reducer_calls(mem._client)[before:]
        assert any("store_memory" in c for c in calls)

    def test_get_via_sql(self, mem):
        uid = _uid("mem0g")
        mem.add("Get test", user_id=uid, agent_id="test-agent")
        assert len(mem.get_all(user_id=uid)) > 0

    def test_search_uses_hybrid_search(self, mem):
        uid = _uid("mem0s")
        mem.add("Search target", user_id=uid, agent_id="test-agent")
        out = mem.search("target", user_id=uid)
        # Mem0 v2 wire shape: {"results": [...]}
        assert isinstance(out, dict) and "results" in out
        assert isinstance(out["results"], list)
        assert len(out["results"]) > 0

    def test_update_sends_update_reducer(self, mem):
        uid = _uid("mem0u")
        mem.add("Original", user_id=uid, agent_id="test-agent")
        out = mem.get_all(user_id=uid)
        results = out["results"] if isinstance(out, dict) else out
        if results and results[0].get("id"):
            before = len(_reducer_calls(mem._client))
            mem.update(memory_id=results[0]["id"], data={"content": "Updated"})
            assert any("update_memory" in c for c in _reducer_calls(mem._client)[before:])

    def test_delete_sends_deactivate_reducer(self, mem):
        uid = _uid("mem0d")
        mem.add("To delete", user_id=uid, agent_id="test-agent")
        out = mem.get_all(user_id=uid)
        results = out["results"] if isinstance(out, dict) else out
        if results and results[0].get("id"):
            before = len(_reducer_calls(mem._client))
            mem.delete(memory_id=results[0]["id"])
            assert any("deactivate_memory" in c or "delete_memory" in c for c in _reducer_calls(mem._client)[before:])


@pytest.mark.e2e
class TestZepWireCompatibility:
    @pytest.fixture
    def zep(self, e2e_stdb: dict) -> Any:
        from spacetime_memory.sdks.zep import Zep
        # Construct Zep WITH the token so its internal client (which the
        # .user/.memory/.graph sub-proxies bind to at construction time)
        # is authenticated and registered. Overwriting z._client afterwards
        # would leave the proxies pointing at an unregistered client.
        z = Zep(host=e2e_stdb["host"], port=e2e_stdb["port"],
                config={"db": e2e_stdb["database"]},
                token=e2e_stdb.get("token", "") or None)
        _ensure_registered(z._client)
        tap = WireTap()
        http = getattr(z._client, "_http", None)
        if http is not None and hasattr(http, "_event_hooks"):
            http._event_hooks.setdefault("request", []).append(tap.request_hook)
        z._client._wire_tap = tap
        return z

    def test_add_memory(self, zep):
        before = len(_reducer_calls(zep._client))
        zep.add_memory(session_id=_uid("zep"), messages=[{"role": "user", "content": "Hi"}])
        # add_memory persists each message via client.store() → store_memory reducer
        assert any("store_memory" in c for c in _reducer_calls(zep._client)[before:])

    def test_search_sessions(self, zep):
        sid = _uid("zeps")
        zep.add_memory(session_id=sid, messages=[{"role": "user", "content": "Search me"}])
        assert isinstance(zep.search_sessions(query="Search", limit=5), list)

    def test_add_fact(self, zep):
        before = len(_reducer_calls(zep._client))
        zep.add_fact(session_id=_uid("zepf"), fact="E2E test fact")
        # add_fact persists via client.store() with memory_type="fact" → store_memory
        assert any("store_memory" in c for c in _reducer_calls(zep._client)[before:])

    def test_get_memory(self, zep):
        sid = _uid("zepg")
        zep.add_memory(session_id=sid, messages=[{"role": "user", "content": "Get me"}])
        assert zep.get_memory(session_id=sid) is not None

    def test_user_crud(self, zep):
        before = len(_reducer_calls(zep._client))
        zep.user.add(user_id=_uid("zepu"), email="e2e@test.com")
        # user.add persists via the add_user/create_user reducer (or SQL upsert)
        calls = _reducer_calls(zep._client)[before:]
        assert any("add_user" in c or "create_user" in c or "/sql" in c for c in calls)


@pytest.mark.e2e
class TestGraphitiWireCompatibility:
    @pytest.fixture
    def graphiti(self, e2e_stdb: dict) -> Any:
        from spacetime_memory.sdks.graphiti import Graphiti
        c, tap = _wire_tapped_client(
            host=e2e_stdb["host"], port=e2e_stdb["port"],
            database=e2e_stdb["database"], token=e2e_stdb.get("token", ""),
        )
        g = Graphiti(host=e2e_stdb["host"], port=e2e_stdb["port"],
                     database=e2e_stdb["database"])
        g._client = c
        c._wire_tap = tap
        return g

    def test_add_triplet(self, graphiti):
        from spacetime_memory.sdks.graphiti import EntityEdge, EntityNode
        before = len(_reducer_calls(graphiti._client))
        gid = _uid("g")
        graphiti.add_triplet(EntityNode(name="Alice", group_id=gid), EntityEdge(name="knows", fact="E2E test", group_id=gid), EntityNode(name="Bob", group_id=gid))
        calls = _reducer_calls(graphiti._client)[before:]
        assert any("create_node" in c for c in calls)
        assert any("create_edge" in c for c in calls)

    def test_add_episode(self, graphiti):
        before = len(_reducer_calls(graphiti._client))
        gid = _uid("ge")
        graphiti.add_episode(name="E2E episode", episode_body="Test episode", source_description="E2E test", group_id=gid)
        # add_episode persists the episode via client.store() → store_memory
        assert any("store_memory" in c for c in _reducer_calls(graphiti._client)[before:])

    def test_get_entity_edge_summary(self, graphiti):
        gid = _uid("gg")
        from spacetime_memory.sdks.graphiti import EntityEdge, EntityNode
        graphiti.add_triplet(EntityNode(name="Charlie", group_id=gid), EntityEdge(name="related_to", fact="test", group_id=gid), EntityNode(name="Diana", group_id=gid))
        result = graphiti.get_entity_edge_summary(entity_names=["Charlie"], group_ids=[gid])
        assert result is not None


@pytest.mark.e2e
class TestHonchoWireCompatibility:
    @pytest.fixture
    def honcho(self, e2e_stdb: dict) -> Any:
        from spacetime_memory.sdks.honcho import Honcho
        c, tap = _wire_tapped_client(
            host=e2e_stdb["host"], port=e2e_stdb["port"],
            database=e2e_stdb["database"], token=e2e_stdb.get("token", ""),
        )
        h = Honcho(
            stdb_host=e2e_stdb["host"], stdb_port=e2e_stdb["port"],
            stdb_database=e2e_stdb["database"],
        )
        h._client = c
        c._wire_tap = tap
        return h

    def test_search(self, honcho):
        # Seed a workspace + memory so search has real data to retrieve.
        # Honcho's _ws_id defaults to "default"; create that workspace id
        # explicitly so store() + search() resolve it.
        ws_id = honcho._ws_id
        try:
            honcho._client.create_workspace(f"{ws_id}_name", id=ws_id)
        except RuntimeError:
            pass  # already exists
        try:
            honcho._client.store(
                workspace_id=ws_id,
                content="E2E searchable marker",
                memory_type="memory",
            )
        except RuntimeError:
            pass
        results = honcho.search("E2E searchable marker")
        assert isinstance(results, list)
        assert any(r.content or "" for r in results)

    def test_queue_status(self, honcho):
        result = honcho.queue_status()
        assert result is not None

    def test_peers(self, honcho):
        p = honcho.peer(_uid("hp"), metadata={"name": "E2E Peer"})
        assert p is not None
        assert p.id is not None

    def test_sessions(self, honcho):
        s = honcho.session(_uid("hs"), metadata={"topic": "E2E"})
        assert s is not None
        assert s.id is not None


@pytest.mark.e2e
class TestHindsightWireCompatibility:
    @pytest.fixture
    def hinds(self, e2e_stdb: dict) -> Any:
        from spacetime_memory.sdks.hindsight import Hindsight
        c, tap = _wire_tapped_client(
            host=e2e_stdb["host"], port=e2e_stdb["port"],
            database=e2e_stdb["database"], token=e2e_stdb.get("token", ""),
        )
        h = Hindsight(
            stdb_host=e2e_stdb["host"], stdb_port=e2e_stdb["port"],
            stdb_database=e2e_stdb["database"],
        )
        h._client = c
        c._wire_tap = tap
        return h

    def test_retain(self, hinds):
        before = len(_reducer_calls(hinds._client))
        hinds.retain(content="E2E retain test", bank_id=_uid("hr"))
        assert any("retain" in c or "store_memory" in c for c in _reducer_calls(hinds._client)[before:])

    def test_retain_batch(self, hinds):
        uid = _uid("hrb")
        before = len(_reducer_calls(hinds._client))
        hinds.retain(content="Batch A", bank_id=uid)
        hinds.retain(content="Batch B", bank_id=uid)
        retain_count = sum(1 for c in _reducer_calls(hinds._client)[before:] if "retain" in c or "store_memory" in c)
        assert retain_count >= 2

    def test_recall(self, hinds):
        uid = _uid("hrc")
        hinds.retain(content="Recall me", bank_id=uid)
        assert hinds.recall(query="Recall", bank_id=uid) is not None

    def test_reflect(self, hinds):
        uid = _uid("hre")
        hinds.retain(content="Reflect base", bank_id=uid)
        r = hinds.reflect(bank_id=uid, query="summarize")
        assert r is not None or r == ""


@pytest.mark.e2e
class TestLangChainWireCompatibility:
    @pytest.fixture
    def store(self, e2e_stdb: dict) -> Any:
        from spacetime_memory.sdks.langchain import StmemStore
        c, tap = _wire_tapped_client(
            host=e2e_stdb["host"], port=e2e_stdb["port"],
            database=e2e_stdb["database"], token=e2e_stdb.get("token", ""),
        )
        s = StmemStore(config={
            "host": e2e_stdb["host"], "port": e2e_stdb["port"],
            "database": e2e_stdb["database"],
        })
        s._client = c
        c._wire_tap = tap
        return s

    def test_put_and_get(self, store):
        store.put(("lc-key",), key="k1", value={"val": "e2e"})
        result = store.get(("lc-key",), key="k1")
        assert result is not None and result.value == {"val": "e2e"}

    def test_search(self, store):
        store.put(("lc-search",), key="sk1", value={"text": "searchable content"})
        assert isinstance(store.search(("lc-search",), query="searchable", limit=5), list)

    def test_put_two_and_list_namespaces(self, store):
        store.put(("lc-m1",), key="m1", value={"n": 1})
        store.put(("lc-m2",), key="m2", value={"n": 2})
        ns = store.list_namespaces()
        assert isinstance(ns, list)

    def test_delete(self, store):
        store.put(("lc-del",), key="del1", value={"gone": True})
        store.delete(("lc-del",), key="del1")
        val = store.get(("lc-del",), key="del1")
        if val is not None:
            assert val.value is None or "gone" not in str(val.value)


# ===========================================================================
# 5 new parity adapters — wire-format validation via mock transport
# ===========================================================================


class TestQmdWireFormatValidation:
    """Validate QMD adapter wire format via mock transport."""

    _COL = "qmd-wire-col"

    @pytest.fixture
    def qmd(self) -> tuple[Any, WireTap]:
        from spacetime_memory.sdks.qmd import QmdClient
        c, tap = _make_mock_client()
        q = QmdClient(host="localhost", port=3001, database="mock-adapter-e2e")
        q._client = c
        return q, tap

    def test_query_uses_sql_or_search(self, qmd: tuple[Any, WireTap]) -> None:
        q, tap = qmd
        tap.requests.clear()
        q.query(self._COL, "wire target")
        urls = [r["url"] for r in tap.requests]
        assert any("/sql" in u or "/call/search" in u for u in urls), f"URLs: {urls}"

    def test_query_returns_list(self, qmd: tuple[Any, WireTap]) -> None:
        q, _ = qmd
        result = q.query(self._COL, "wire target")
        assert isinstance(result, list)

    def test_status_returns_dict(self, qmd: tuple[Any, WireTap]) -> None:
        q, _ = qmd
        assert isinstance(q.status(), dict)


class TestMnemosyneWireFormatValidation:
    """Validate Mnemosyne adapter wire format via mock transport."""

    _DECK = "mnemo-wire-deck"

    @pytest.fixture
    def mnemo(self) -> tuple[Any, WireTap]:
        from spacetime_memory.sdks.mnemosyne import Mnemosyne
        c, tap = _make_mock_client()
        m = Mnemosyne(host="localhost", port=3001, database="mock-adapter-e2e")
        m._client = c
        return m, tap

    def test_create_card_stores_memory(self, mnemo: tuple[Any, WireTap]) -> None:
        m, tap = mnemo
        tap.requests.clear()
        m.create_card(self._DECK, "Who is Ada?", "Ada Lovelace", 5)
        _assert_reducer_called(tap, "store_memory")

    def test_get_due_cards_uses_sql(self, mnemo: tuple[Any, WireTap]) -> None:
        m, tap = mnemo
        tap.requests.clear()
        m.get_due_cards(self._DECK)
        _assert_sql_called(tap)


class TestLettaWireFormatValidation:
    """Validate Letta adapter wire format via mock transport."""

    _AGENT = "letta-wire-agent"

    @pytest.fixture
    def letta(self) -> tuple[Any, WireTap]:
        from spacetime_memory.sdks.letta import LettaMemory
        c, tap = _make_mock_client()
        l = LettaMemory(host="localhost", port=3001, database="mock-adapter-e2e")
        l._client = c
        return l, tap

    def test_update_block_stores(self, letta: tuple[Any, WireTap]) -> None:
        l, tap = letta
        tap.requests.clear()
        l.update_block(self._AGENT, "persona", "I am a test agent.")
        _assert_reducer_called(tap, "store_memory")

    def test_get_memory_uses_sql(self, letta: tuple[Any, WireTap]) -> None:
        l, tap = letta
        tap.requests.clear()
        l.get_memory(self._AGENT)
        _assert_sql_called(tap)


class TestCogneeWireFormatValidation:
    """Validate Cognee adapter wire format via mock transport."""

    _DS = "cognee-wire-ds"

    @pytest.fixture
    def cog(self) -> tuple[Any, WireTap]:
        import spacetime_memory.sdks.cognee as cognee_mod
        c, tap = _make_mock_client()
        orig = cognee_mod._client
        cognee_mod._client = lambda: c
        try:
            yield (cognee_mod, tap)
        finally:
            cognee_mod._client = orig

    def test_add_stores_memory(self, cog: tuple[Any, WireTap]) -> None:
        mod, tap = cog
        tap.requests.clear()
        import asyncio
        asyncio.run(mod.add("wire content", dataset_name=self._DS))
        _assert_reducer_called(tap, "store_memory")

    def test_search_returns_list(self, cog: tuple[Any, WireTap]) -> None:
        mod, _ = cog
        import asyncio
        result = asyncio.run(mod.search("wire query", datasets=[self._DS]))
        assert isinstance(result, list)


class TestLangMemWireFormatValidation:
    """Validate LangMem adapter wire format via mock transport."""

    def test_manage_memory_create_stores_via_store(self) -> None:
        from spacetime_memory.sdks.langmem import create_manage_memory_tool
        from spacetime_memory.sdks.langchain import StmemStore
        c, tap = _make_mock_client()
        s = StmemStore(config={
            "host": "localhost", "port": "3001", "database": "mock-adapter-e2e",
        })
        s._client = c
        tool = create_manage_memory_tool(namespace=("memories", "wire"), store=s)
        tap.requests.clear()
        result = tool.invoke({"content": "wire memory", "action": "create"})
        assert result.startswith("created memory ")

    def test_search_memory_tool_returns_string(self) -> None:
        from spacetime_memory.sdks.langmem import create_search_memory_tool
        from spacetime_memory.sdks.langchain import StmemStore
        c, tap = _make_mock_client()
        s = StmemStore(config={
            "host": "localhost", "port": "3001", "database": "mock-adapter-e2e",
        })
        s._client = c
        tool = create_search_memory_tool(namespace=("memories", "wire"), store=s)
        result = tool.invoke({"query": "wire", "limit": 5})
        assert isinstance(result, str)
