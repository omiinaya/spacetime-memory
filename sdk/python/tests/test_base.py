"""Tests for client/_base.py — ClientBase, error handling, auth, circuit breaker.

These tests use mock httpx transport — no live SpacetimeDB connection needed.
"""

from __future__ import annotations

import json
import logging
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from spacetime_memory.client._base import (
    _REDUCER_ERROR_MAP,
    _SQL_ERROR_MAP,
    ApiError,
    ClientBase,
    EmbedderUnavailableError,
    JSONFormatter,
    NotFoundError,
    SpacetimeDBError,
    configure_logging,
)
from spacetime_memory.client._embed import EmbedderMixin

# ── Helpers ──────────────────────────────────────────────────────────────────


def _mock_response(status_code: int = 200, json_data: dict | None = None,
                   text: str = "", headers: dict | None = None) -> MagicMock:
    """Build a mock httpx.Response-like object."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.headers = headers or {"Content-Type": "application/json",
                               "spacetime-identity-token": ""}
    return resp


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def client_base() -> ClientBase:
    """ClientBase with mocked HTTP transport, bypassing real __init__."""
    from spacetime_memory import Client
    cb = Client.__new__(Client)
    # -- HTTP mock --
    cb._http = MagicMock(spec=httpx.Client)
    cb._http.get.return_value = _mock_response()
    cb._http.post.return_value = _mock_response()

    # -- Identity --
    cb._identity_token = "test-identity-token"
    cb._identity_established = True
    cb.token = "test-jwt-token"
    cb._identity_peer_id = "test-peer"
    cb._last_identity_refresh = 0.0
    cb._identity_refresh_interval = 300.0

    # -- Connection params --
    cb.host = "127.0.0.1"
    cb.port = "3001"
    cb.database = "test_db"
    cb.sql_url = f"http://{cb.host}:{cb.port}/v1/database/{cb.database}/sql"
    cb.reducer_url = f"http://{cb.host}:{cb.port}/v1/database/{cb.database}/call"
    cb.embedder_url = "http://127.0.0.1:4000"
    cb.tantivy_url = "http://127.0.0.1:9091"
    cb.verbose = False

    # -- Circuit breaker (shared between STDB and Tantivy) --
    cb.max_retries = 3
    cb._consecutive_failures = 0
    cb._circuit_open_until = 0.0
    cb._circuit_breaker_threshold = 5
    cb._circuit_breaker_reset_secs = 30.0
    cb._hosts = ["127.0.0.1:3001"]
    cb._current_host_index = 0

    # -- Embedder alerting --
    cb._embedder_consecutive_failures = 0
    cb._embedder_last_failure_ts = 0.0
    cb._embedder_alert_threshold = 3
    cb._init_embedder_counters = lambda: None

    # -- Caches / lazy services --
    cb._query_cache = None
    cb._binary_cache = {}
    cb._metrics = None
    cb._delta_sync = None
    cb._compounder = None

    # -- Plugins / events / LLM --
    cb.plugin_manager = None
    cb.event_bus = None
    cb.local_llm = None
    cb._plugin = None
    cb._observability = None

    # -- Other state --
    cb.request_id = "abcdef01"
    cb._call_counter = 0
    cb._pending_reconnect = False
    return cb


# ── Error class tests ────────────────────────────────────────────────────────


class TestErrors:
    """Custom exception hierarchy."""

    def test_embedder_unavailable_error(self):
        err = EmbedderUnavailableError("embedder down")
        assert isinstance(err, ConnectionError)

    def test_spacetimedb_error_is_runtime_error(self):
        err = SpacetimeDBError("db error")
        assert isinstance(err, RuntimeError)

    def test_not_found_error_inherits(self):
        err = NotFoundError("not found")
        assert isinstance(err, SpacetimeDBError)

    def test_api_error_inherits(self):
        err = ApiError("api error")
        assert isinstance(err, SpacetimeDBError)

    def test_error_stringification(self):
        assert str(EmbedderUnavailableError("down")) == "down"
        assert str(SpacetimeDBError("fail")) == "fail"
        assert str(NotFoundError("gone")) == "gone"
        assert str(ApiError("bad")) == "bad"


# ── SQL / Reducer error map tests ────────────────────────────────────────────


class TestErrorMaps:
    """Coverage for _SQL_ERROR_MAP and _REDUCER_ERROR_MAP."""

    def test_sql_error_map_has_known_keys(self):
        assert "table.*does not exist" in _SQL_ERROR_MAP
        assert "column.*does not exist" in _SQL_ERROR_MAP
        assert "duplicate key value" in _SQL_ERROR_MAP
        assert "syntax error" in _SQL_ERROR_MAP
        assert "permission denied" in _SQL_ERROR_MAP

    def test_sql_map_entries_are_strings(self):
        for k, v in _SQL_ERROR_MAP.items():
            assert isinstance(k, str)
            assert isinstance(v, str)
            assert len(v) > 10  # meaningful message

    def test_reducer_error_map_has_known_keys(self):
        assert "not found" in _REDUCER_ERROR_MAP
        assert "unauthorized" in _REDUCER_ERROR_MAP
        assert "already exists" in _REDUCER_ERROR_MAP
        assert "validation error" in _REDUCER_ERROR_MAP
        assert "rate limit" in _REDUCER_ERROR_MAP

    def test_reducer_map_entries_are_strings(self):
        for k, v in _REDUCER_ERROR_MAP.items():
            assert isinstance(k, str)
            assert isinstance(v, str)
            assert len(v) > 10


# ── JSONFormatter tests ──────────────────────────────────────────────────────


class TestJSONFormatter:
    """Structured JSON log output."""

    def test_format_basic(self):
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="test_logger", level=logging.INFO,
            pathname="test.py", lineno=1,
            msg="hello world", args=(), exc_info=None,
        )
        parsed = json.loads(fmt.format(record))
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test_logger"
        assert parsed["message"] == "hello world"
        assert "ts" in parsed

    def test_format_with_exception(self):
        fmt = JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys as _sys
            record = logging.LogRecord(
                name="exc_logger", level=logging.ERROR,
                pathname="test.py", lineno=1,
                msg="error occurred", args=(), exc_info=_sys.exc_info(),
            )
        parsed = json.loads(fmt.format(record))
        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]

    def test_format_extra_fields(self):
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="extra_logger", level=logging.WARNING,
            pathname="test.py", lineno=1,
            msg="with extras", args=(), exc_info=None,
        )
        record.extra_fields = {"request_id": "abc123", "user": "test"}
        parsed = json.loads(fmt.format(record))
        assert parsed["request_id"] == "abc123"
        assert parsed["user"] == "test"


# ── configure_logging tests ──────────────────────────────────────────────────


class TestConfigureLogging:
    """Logging setup via configure_logging()."""

    def setup_method(self):
        logging.getLogger("spacetime_memory").handlers.clear()

    def test_default_level(self):
        with patch.dict("os.environ", {}, clear=True):
            configure_logging()
            logger = logging.getLogger("spacetime_memory")
            assert logger.level == logging.INFO

    def test_env_var_level(self):
        with patch.dict("os.environ", {"SPACETIMEDB_MEMORY_LOG_LEVEL": "DEBUG"}, clear=True):
            configure_logging()
            logger = logging.getLogger("spacetime_memory")
            assert logger.level == logging.DEBUG
            assert len(logger.handlers) > 0

    def test_log_file(self, tmp_path):
        logging.getLogger("spacetime_memory").handlers.clear()
        configure_logging(log_file=str(tmp_path / "test.log"))
        assert len(logging.getLogger("spacetime_memory").handlers) > 0

    def test_non_json_format(self):
        configure_logging(json_format=False)
        assert len(logging.getLogger("spacetime_memory").handlers) > 0


# ── ClientBase construction ──────────────────────────────────────────────────


class TestClientBaseInit:
    """Instance creation and __init__ defaults."""

    def test_init_minimal(self):
        """Can construct ClientBase with no args (env defaults)."""
        with patch.dict("os.environ", {}, clear=True):
            cb = ClientBase()
            assert cb.host == "127.0.0.1"
            assert cb.port == "3001"
            assert cb.database is not None
            assert cb.embedder_url is not None
            assert cb.tantivy_url is not None

    def test_init_custom_host_port(self):
        cb = ClientBase(host="localhost", port=8080, database="test")
        assert cb.host == "localhost"
        assert cb.port == "8080"
        assert cb.database == "test"

    def test_init_with_token(self):
        cb = ClientBase(token="my-jwt-token")
        assert cb.token == "my-jwt-token"

    def test_init_with_plugin_manager(self):
        pm = MagicMock()
        cb = ClientBase(plugin_manager=pm)
        assert cb.plugin_manager is pm

    def test_init_sets_http_client(self):
        cb = ClientBase()
        assert isinstance(cb._http, httpx.Client)

    def test_verbose_sets_debug_logging(self):
        with patch("spacetime_memory.client._base.configure_logging") as mock_cfg:
            ClientBase(verbose=True)
            mock_cfg.assert_called_once_with(level="DEBUG")


# ── _headers tests ───────────────────────────────────────────────────────────


class TestHeaders:
    """_headers() returns auth headers."""

    def test_includes_authorization_with_jwt(self, client_base):
        """When token is set, it's used for auth."""
        client_base.token = "my-jwt"
        client_base._identity_token = "identity-tok"
        headers = client_base._headers()
        assert headers["Authorization"] == "Bearer my-jwt"

    def test_falls_back_to_identity_token(self, client_base):
        """When token is None, _identity_token is used."""
        client_base.token = None
        client_base._identity_token = "identity-tok"
        headers = client_base._headers()
        assert headers["Authorization"] == "Bearer identity-tok"

    def test_no_auth_when_no_token(self, client_base):
        """When no token at all, no Authorization header."""
        client_base.token = None
        client_base._identity_token = None
        headers = client_base._headers()
        assert "Authorization" not in headers


# ── ping tests ───────────────────────────────────────────────────────────────


class TestPing:
    """ping() returns status dict."""

    def test_ping_success(self, client_base):
        client_base._http.get.return_value = _mock_response(status_code=200)
        result = client_base.ping()
        assert result["status"] == "ok"
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], (int, float))

    def test_ping_http_error(self, client_base):
        client_base._http.get.return_value = _mock_response(status_code=503)
        result = client_base.ping()
        assert result["status"] == "error"
        assert "HTTP 503" in result.get("message", "")

    def test_ping_connection_error(self, client_base):
        client_base._http.get.side_effect = httpx.ConnectError("refused")
        result = client_base.ping()
        assert result["status"] == "error"
        assert "latency_ms" in result

    def test_ping_timeout(self, client_base):
        client_base._http.get.side_effect = httpx.TimeoutException("timed out")
        result = client_base.ping()
        assert result["status"] == "error"

    def test_ping_circuit_breaker_open(self, client_base):
        client_base._circuit_open_until = time.time() + 60
        result = client_base.ping()
        assert result["status"] == "error"
        assert "circuit" in result.get("message", "").lower()


# ── health tests ─────────────────────────────────────────────────────────────


class TestHealth:
    """health() aggregates component checks."""

    def test_health_returns_all_components(self, client_base):
        """All three component checks are present."""
        ok_resp = _mock_response(status_code=200)
        client_base._http.get.return_value = ok_resp
        health = client_base.health()
        assert "status" in health
        assert "database" in health
        assert "embedder" in health
        assert "tantivy" in health
        assert "token_configured" in health

    def test_health_token_configured_true(self, client_base):
        client_base.token = "tok"
        client_base._http.get.return_value = _mock_response(status_code=200)
        assert client_base.health()["token_configured"] is True

    def test_health_token_configured_false(self, client_base):
        client_base.token = None
        client_base._identity_token = None
        client_base._http.get.return_value = _mock_response(status_code=200)
        assert client_base.health()["token_configured"] is False


# ── _call tests ──────────────────────────────────────────────────────────────


class TestCall:
    """_call(reducer, args) — reducer invocation."""

    def test_call_success(self, client_base):
        client_base._http.post.return_value = _mock_response(status_code=200)
        result = client_base._call("my_reducer", ["arg1", "arg2"])
        assert result["status"] == "ok"

    def test_call_sends_post(self, client_base):
        client_base._http.post.return_value = _mock_response(status_code=200)
        client_base._call("r", [1, 2])
        assert client_base._http.post.called

    def test_call_sends_auth(self, client_base):
        client_base._http.post.return_value = _mock_response(status_code=200)
        client_base._call("r", [])
        call_kwargs = client_base._http.post.call_args[1]
        assert "Authorization" in call_kwargs.get("headers", {})

    def test_call_raises_api_error_on_422(self, client_base):
        client_base._http.post.return_value = _mock_response(status_code=422,
            json_data={"detail": "validation failed"})
        with pytest.raises(RuntimeError, match="Reducer error"):
            client_base._call("r", [])

    def test_call_raises_not_found_on_404(self, client_base):
        client_base._http.post.return_value = _mock_response(status_code=404)
        with pytest.raises(RuntimeError, match="Reducer error"):
            client_base._call("r", [])

    def test_call_sql_table_not_found(self, client_base):
        """SQL error about missing table gets a helpful message."""
        client_base._http.post.return_value = _mock_response(
            status_code=400, text="table 'foo' does not exist")
        with pytest.raises(RuntimeError) as exc:
            client_base._call("sql", ["SELECT * FROM foo"])
        assert "does not exist" in str(exc.value) or "Table not found" in str(exc.value)

    def test_call_duplicate_key(self, client_base):
        client_base._http.post.return_value = _mock_response(
            status_code=400, text="duplicate key value violates unique constraint")
        with pytest.raises(RuntimeError) as exc:
            client_base._call("sql", ["INSERT INTO t VALUES (1)"])
        assert "Duplicate" in str(exc.value) or "duplicate key" in str(exc.value)

    def test_call_reducer_not_found(self, client_base):
        client_base._http.post.return_value = _mock_response(
            status_code=400, text="not found")
        with pytest.raises(RuntimeError) as exc:
            client_base._call("get_memory", ["mem_1"])
        assert "Check the ID" in str(exc.value)

    def test_call_reducer_unauthorized(self, client_base):
        client_base._http.post.return_value = _mock_response(
            status_code=400, text="unauthorized")
        with pytest.raises(RuntimeError) as exc:
            client_base._call("r", [])
        assert "Login first" in str(exc.value)


class TestCallWithResult:
    """_call_with_result(reducer, args) — reducers that return data."""

    def test_call_with_result_returns_value(self, client_base):
        client_base._http.post.return_value = _mock_response(
            status_code=200,
            json_data={"status": "ok", "result": '[{"x": 1}]'},
        )
        result = client_base._call_with_result("get_results", ["qid"])
        assert result == [{"x": 1}]

    def test_call_with_result_none_on_empty(self, client_base):
        """Reducer returning None/unit gets None from .result."""
        client_base._http.post.return_value = _mock_response(
            status_code=200,
            json_data={"status": "ok"},
        )
        result = client_base._call_with_result("noop", [])
        assert result is None

    def test_call_with_result_raises_on_error(self, client_base):
        """STDB-level error message is surfaced."""
        client_base._http.post.return_value = _mock_response(
            status_code=200,
            json_data={"status": "error", "message": "bad things"},
        )
        with pytest.raises(RuntimeError, match="bad things"):
            client_base._call_with_result("failing", [])

    def test_call_with_result_raises_http_error(self, client_base):
        client_base._http.post.return_value = _mock_response(
            status_code=422, text="validation failed")
        with pytest.raises(RuntimeError):
            client_base._call_with_result("bad", [])


# ── Circuit breaker tests ────────────────────────────────────────────────────


class TestCircuitBreaker:
    """_request_with_retry circuit breaker."""

    def test_opens_after_threshold_failures(self, client_base):
        """Circuit opens after consecutive ConnectErrors hit the threshold."""
        client_base.max_retries = 0
        client_base._circuit_breaker_threshold = 3
        client_base._http.get.side_effect = httpx.ConnectError("timeout")
        for i in range(3):
            with pytest.raises((httpx.ConnectError, RuntimeError)):
                client_base._request_with_retry("GET", "http://localhost/ping", timeout=1)
        assert client_base._circuit_open_until > time.time()

    def test_consecutive_failures_tracking(self, client_base):
        """Each ConnectError increments consecutive_failures."""
        client_base.max_retries = 0
        client_base._circuit_breaker_threshold = 10  # don't trip
        client_base._http.get.side_effect = httpx.ConnectError("timeout")
        for _ in range(3):
            try:
                client_base._request_with_retry("GET", "http://localhost/ping", timeout=1)
            except (httpx.ConnectError, RuntimeError):
                pass
        assert client_base._consecutive_failures == 3

    def test_open_circuit_raises_fast(self, client_base):
        """Open circuit raises RuntimeError without attempting the request."""
        client_base._circuit_open_until = time.time() + 60
        client_base._http.get.side_effect = AssertionError("must not be called")
        with pytest.raises(RuntimeError, match="circuit breaker"):
            client_base._request_with_retry("GET", "http://localhost/ping", timeout=1)

    def test_resets_after_open_expires(self, client_base):
        """Circuit is bypassed when open_until is in the past."""
        client_base._circuit_open_until = time.time() - 1.0
        client_base._http.get.return_value = _mock_response(status_code=200)
        result = client_base._request_with_retry("GET", "http://localhost/ping", timeout=1)
        assert result.status_code == 200

    def test_success_resets_circuit(self, client_base):
        """Successful request resets consecutive_failures to 0."""
        client_base._consecutive_failures = 3
        client_base._http.get.return_value = _mock_response(status_code=200)
        client_base._request_with_retry("GET", "http://localhost/ping", timeout=1)
        assert client_base._consecutive_failures == 0

    def test_4xx_does_not_open_circuit(self, client_base):
        """Client errors (4xx) don't count toward circuit breaker."""
        client_base._circuit_breaker_threshold = 3
        client_base._http.get.return_value = _mock_response(status_code=422)
        for _ in range(5):
            client_base._request_with_retry("GET", "http://localhost/ping", timeout=1)
        # 4xx doesn't count as failure
        assert client_base._consecutive_failures == 0
        assert client_base._circuit_open_until == 0.0


# ── from_token_file tests ────────────────────────────────────────────────────


class TestFromTokenFile:
    """ClientBase.from_token_file — classmethod.

    Fixed 2026-08-02: the method was missing @classmethod, so every call via
    the class raised TypeError. Now it's a proper classmethod: calling via the
    class reads the token file and constructs a Client.
    """

    def test_class_call_missing_token_path(self):
        """Calling via the class with no token_path → TypeError (arg missing)."""
        with pytest.raises(TypeError):
            ClientBase.from_token_file()

    def test_class_call_with_token_path(self):
        """Class call reads the file and constructs the client."""
        from unittest.mock import patch
        with patch("pathlib.Path.read_text", return_value="dummy-token"):
            client = ClientBase.from_token_file("/nonexistent/file", host="h1", port="42", database="db1")
            assert client.token == "dummy-token"
            assert client.host == "h1"
            assert client.port == "42"
            assert client.database == "db1"


# ── delta_sync / compounder ──────────────────────────────────────────────────


class TestDeltaSync:
    """delta_sync lazy property."""

    def test_returns_delta_sync_instance(self, client_base):
        ds = client_base.delta_sync
        assert ds is not None

    def test_memoized(self, client_base):
        ds1 = client_base.delta_sync
        ds2 = client_base.delta_sync
        assert ds1 is ds2


class TestCompounder:
    """compounder lazy property."""

    def test_returns_compounder_instance(self, client_base):
        c = client_base.compounder
        assert c is not None
        assert client_base._compounder is c

    def test_memoized(self, client_base):
        c1 = client_base.compounder
        c2 = client_base.compounder
        assert c1 is c2


# ── _map_sql_error / _map_reducer_error ─────────────────────────────────────


class TestSQLErrorMapping:
    """_map_sql_error maps error texts to user-friendly messages."""

    def test_map_table_not_found(self, client_base):
        msg = client_base._map_sql_error("table 'foo' does not exist")
        assert "Table not found" in msg

    def test_map_duplicate_key(self, client_base):
        msg = client_base._map_sql_error("duplicate key value")
        assert "Duplicate" in msg

    def test_map_unknown(self, client_base):
        msg = client_base._map_sql_error("some unknown error")
        assert "unknown" in msg.lower()

    def test_map_syntax_error(self, client_base):
        msg = client_base._map_sql_error("syntax error at line 1")
        assert "syntax" in msg.lower()

    def test_map_permission_denied(self, client_base):
        msg = client_base._map_sql_error("permission denied for table")
        assert "permission" in msg.lower()


class TestReducerErrorMapping:
    """_map_reducer_error maps error texts to user-friendly messages."""

    def test_map_not_found(self, client_base):
        msg = client_base._map_reducer_error("not found")
        assert "Check the ID" in msg

    def test_map_unauthorized(self, client_base):
        msg = client_base._map_reducer_error("unauthorized")
        assert "Login first" in msg

    def test_map_already_exists(self, client_base):
        msg = client_base._map_reducer_error("already exists")
        assert "already exists" in msg

    def test_map_validation_error(self, client_base):
        msg = client_base._map_reducer_error("validation error")
        assert "Invalid input" in msg

    def test_map_rate_limit(self, client_base):
        msg = client_base._map_reducer_error("rate limit exceeded")
        assert "Too many requests" in msg

    def test_map_unknown(self, client_base):
        msg = client_base._map_reducer_error("some weird error")
        assert "Reducer error" in msg
        assert "weird" in msg


# ══════════════════════════════════════════════════════════════════════
# Cross-tripping: shared circuit breaker (STDB + Tantivy)
# ══════════════════════════════════════════════════════════════════════


class TestSharedCircuitBreaker:
    """Cross-tripping: shared circuit breaker between STDB and Tantivy.

    Both _request_with_retry (STDB) and _request_with_retry_tantivy
    use the same _consecutive_failures / _circuit_open_until state.
    A failure from either side trips both -- verifying that here.
    """

    def test_stdb_failure_opens_shared_breaker(self, client_base):
        """STDB failure increments _consecutive_failures and opens circuit breaker."""
        client_base.max_retries = 0
        client_base._circuit_breaker_threshold = 2
        client_base._http.get.side_effect = httpx.ConnectError('stdb timeout')
        for _ in range(2):
            with pytest.raises((httpx.ConnectError, RuntimeError)):
                client_base._request_with_retry('GET', 'http://localhost/ping', timeout=1)

        assert client_base._circuit_open_until > time.time()
        assert client_base._consecutive_failures >= 2

    def test_tantivy_own_breaker_independent(self, client_base):
        """Tantivy has its own _tantivy_circuit_open_until — STDB failures don't trip it."""
        # Trip STDB circuit breaker
        client_base.max_retries = 0
        client_base._circuit_breaker_threshold = 1
        client_base._http.get.side_effect = httpx.ConnectError('stdb down')
        with pytest.raises((httpx.ConnectError, RuntimeError)):
            client_base._request_with_retry('GET', 'http://localhost/ping', timeout=1)

        assert client_base._circuit_open_until > time.time()

        # EmbedderMixin using its OWN Tantivy state (separate from STDB)
        mixin = EmbedderMixin()
        mixin.max_retries = 0
        mixin._http = MagicMock(spec=httpx.Client)
        mixin._tantivy_consecutive_failures = 0
        mixin._tantivy_circuit_open_until = 0.0
        mixin._circuit_breaker_threshold = 2
        mixin._circuit_breaker_reset_secs = 30.0

        # Tantivy should NOT be blocked by STDB circuit — should reach mock
        mixin._http.get.side_effect = httpx.ConnectError('tantivy down')
        with pytest.raises((httpx.ConnectError, RuntimeError)):
            mixin._request_with_retry_tantivy('GET', 'http://tantivy/search')

        # Only Tantivy's counter should be incremented, not STDB's
        assert mixin._tantivy_consecutive_failures >= 1
        # STDB circuit state unaffected
        assert client_base._circuit_open_until > time.time()
