"""ClientBase — SpacetimeDB connection, auth, HTTP helpers, and health.

Module split from monolithic client.py.
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import secrets
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any

import httpx
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import Client

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

from .._protocols import (  # noqa: E402
    EventBusProtocol,
    LocalLLMProtocol,
    MetricsCollectorProtocol,
    PluginManagerProtocol,
    QueryCacheProtocol,
)
from ._utils import _esc, _parse_sql_response  # noqa: E402

try:
    from ..tracer import get_tracer
    from ..tracer import start_span as _start_span
    _TRACER = get_tracer(setup=True)
    def _tracing_span(name: str, **attrs: Any) -> Any:
        return _start_span(name, attributes=attrs if attrs else None)
except ImportError:
    def _tracing_span(name: str, **attrs: Any) -> Any:
        from contextlib import nullcontext
        return nullcontext()
    _TRACER = None

# Error maps
_SQL_ERROR_MAP: dict[str, str] = {
    "table.*does not exist": "Table not found. Check that the module is published.",
    "column.*does not exist": "Column not found. Check the field name.",
    "duplicate key value": "Duplicate record. A record with this ID already exists.",
    "violates foreign key": "Referenced record not found. Check that the related record exists.",
    "syntax error": "SQL syntax error. Check your query syntax.",
    "permission denied": "Permission denied. You may not have access to this resource.",
}

_REDUCER_ERROR_MAP: dict[str, str] = {
    "not found": "Record not found. Check the ID. Try: stmem list-memories --workspace <id>",
    "unauthorized": "Authentication required. Login first: stmem login --username <user> --password <pass>",
    "already exists": "Record already exists with this identifier. Use a different ID or delete the existing one: stmem delete-memory <id>",
    "validation error": "Invalid input. Check the format of your data. Run 'stmem <command> --help' for usage.",
    "rate limit": "Too many requests. Wait before retrying, or reduce concurrency with --max-concurrent N",
}


class EmbedderUnavailableError(ConnectionError):
    """Raised when the embedding sidecar is unreachable and no fallback is configured."""


class SpacetimeDBError(RuntimeError):
    """Base exception for SpacetimeDB backend failures."""


# Backward-compatible alias — legacy code (CLI admin tools, restore error
# handlers) references ``spacetime_memory.ClientError``.
ClientError = SpacetimeDBError


class NotFoundError(SpacetimeDBError):
    """Raised when a requested resource (session, memory, workspace) is not found."""


class ApiError(SpacetimeDBError):
    """Raised when SpacetimeDB returns an unexpected API error."""


class JSONFormatter(logging.Formatter):
    """JSON log formatter. Outputs structured log records as newline-delimited JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": self.formatTime(record, self.datefmt or "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and (record.exc_info is True or record.exc_info[0]):
            log_entry["exception"] = self.formatException(record.exc_info)
        for key, value in getattr(record, "extra_fields", {}).items():
            log_entry[key] = value
        return json.dumps(log_entry, default=str)


def configure_logging(
    level: str | None = None,
    json_format: bool = True,
    log_file: str | None = None,
) -> None:
    """Configure structured logging for the SDK."""
    level = (level or os.environ.get("SPACETIMEDB_MEMORY_LOG_LEVEL", "INFO")).upper()
    logger = logging.getLogger("spacetime_memory")
    logger.setLevel(getattr(logging, level, logging.INFO))
    logger.handlers.clear()
    if log_file:
        handler: logging.Handler = logging.FileHandler(log_file)
    else:
        handler = logging.StreamHandler()
    if json_format:
        formatter: logging.Formatter = JSONFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


@dataclass
class MemoryRecord:
    """Typed record of a memory row, used by ``Client.MemoryRecord``.

    Fields mirror the STDB ``memory`` table columns.  ``from_dict``
    filters input dictionaries to the recognised field names so callers
    can pass a raw SQL row (which may include extra keys) directly.
    """

    id: str
    workspace_id: str
    peer_id: str
    observer_id: str
    memory_type: str
    content: str
    summary: str
    entities_json: str
    confidence: float
    is_active: bool
    created_at: int
    expires_at: int
    updated_at: int
    tier: str
    access_count: int
    strength: float
    version: int
    trust_score: float
    feedback_count: int
    consolidated_to: str

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryRecord":
        """Create a MemoryRecord from a dictionary, filtering to field names only.

        Args:
            d: Dictionary of memory record fields.

        Returns:
            A MemoryRecord instance with only recognised fields populated.
        """
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})




class ClientBase:
    """Spacetime-Memory client base class.

    Provides connection, HTTP helpers, and embedding infrastructure.
    All domain mixins inherit from this.
    """
    # Circuit breaker defaults (class-level so Mock(spec=Client) includes them)
    _circuit_open_until: float = 0.0
    _consecutive_failures: int = 0
    _tantivy_circuit_open_until: float = 0.0
    _tantivy_consecutive_failures: int = 0
    _embedder_consecutive_failures: int = 0
    _embedder_last_failure_ts: float = 0.0
    _embedder_alert_threshold: int = 3
    _embedder_alerted: bool = False
    _embedder_was_degraded: bool = False
    _binary_cache: dict[str, bytes] = {}
    _circuit_breaker_threshold: int = 5
    _circuit_breaker_reset_secs: float = 30.0
    max_retries: int = 3
    def __init__(
        self,
        host: str | None = None,
        port: int | str | None = None,
        database: str | None = None,
        embedder_url: str | None = None,
        tantivy_url: str | None = None,
        timeout: float = 30.0,
        verbose: bool = False,
        token: str | None = None,
        plugin_manager: PluginManagerProtocol | None = None,
        event_bus: EventBusProtocol | None = None,
        query_cache: QueryCacheProtocol | None = None,
        local_llm: LocalLLMProtocol | None = None,
    ):
        """Initialise a SpacetimeDB client connection.

        Args:
            host: STDB hostname (default: env ``SPACETIMEDB_HOST`` or ``127.0.0.1``).
            port: STDB port (default: env ``SPACETIMEDB_PORT`` or ``3001``).
            database: STDB database hash (default: env ``SPACETIMEDB_DB``).
            embedder_url: Embedding service URL (default: env ``EMBEDDER_URL``).
            tantivy_url: Tantivy BM25 sidecar URL (default: env ``TANTIVY_URL``).
            timeout: HTTP request timeout in seconds.
            verbose: Enable verbose logging.
            token: Auth token (default: env ``SPACETIMEDB_TOKEN``).
            plugin_manager: Optional plugin manager instance (duck-typed, accepts
                any object that satisfies ``PluginManagerProtocol``).
            event_bus: Optional event bus instance (``EventBusProtocol``).
            query_cache: Optional query cache instance (``QueryCacheProtocol``).
            local_llm: Optional local LLM instance (``LocalLLMProtocol``).
        """
        self.host = host or os.environ.get("SPACETIMEDB_HOST", "127.0.0.1")
        self.port = str(port or os.environ.get("SPACETIMEDB_PORT", "3001"))
        self.database = database or os.environ.get(
            "SPACETIMEDB_DB", "c20082e7643347e8d36302b550bb98c7343f9ea2a268f3bee58ee58d3c3dcbf1"
        )
        # Bypass HTTP proxy for localhost — the system http_proxy
        # routes through isp.decodo.com which blocks STDB reducer calls.
        os.environ.setdefault("no_proxy", "localhost,127.0.0.1,.local")
        self.embedder_url = (
            embedder_url
            or os.environ.get("EMBEDDER_URL")
            or "http://127.0.0.1:9090/v1"
        )
        self.tantivy_url = tantivy_url or os.environ.get("TANTIVY_URL", "http://127.0.0.1:9091")
        self.verbose = verbose
        # Wire verbose flag into logging configuration
        if verbose:
            configure_logging(level="DEBUG")
        self.token = token or os.environ.get("SPACETIMEDB_TOKEN")
        self.max_retries = int(os.environ.get("STMEM_MAX_RETRIES", "3"))
        self._circuit_breaker_threshold = int(os.environ.get("STMEM_CIRCUIT_THRESHOLD", "5"))
        self._circuit_breaker_reset_secs = float(os.environ.get("STMEM_CIRCUIT_RESET_SECS", "30.0"))
        self._consecutive_failures: int = 0
        # Tantivy BM25 sidecar circuit breaker — isolated from STDB so
        # Tantivy failures don't trip the STDB circuit breaker.
        self._tantivy_consecutive_failures: int = 0
        self._tantivy_circuit_open_until: float = 0.0
        # Embedder error tracking for rate alerting — tracks consecutive
        # failures so the SDK can surface degradation warnings instead of
        # silently returning empty embeddings.
        self._embedder_consecutive_failures: int = 0
        self._embedder_last_failure_ts: float = 0.0
        self._embedder_alert_threshold: int = int(
            os.environ.get("STMEM_EMBEDDER_ALERT_THRESHOLD", "3")
        )
        self._embedder_alerted: bool = False
        self._embedder_was_degraded: bool = False
        # MIB binary vector cache — entity_id → packed bytes
        self._binary_cache: dict[str, bytes] = {}
        self._circuit_open_until: float = 0.0
        self._metrics: MetricsCollectorProtocol | None = None  # Set via set_metrics_collector()
        self._delta_sync: Any = None  # Lazy DeltaSync instance
        self._compounder: Any = None  # Lazy Compounder instance
        self.request_id: str = os.urandom(4).hex()  # Unique per-client instance
        self._identity_token: str | None = None
        self._identity_established: bool = False

        # P2 polish: plugins, events, caching, local LLM
        self.plugin_manager = plugin_manager
        self.event_bus = event_bus
        self._query_cache = query_cache
        self.local_llm = local_llm

        # ---- Multi-region / failover host list ----
        hosts_env = os.environ.get("SPACETIMEDB_HOSTS", "")
        if hosts_env:
            self._hosts = [h.strip() for h in hosts_env.split(",") if h.strip()]
        else:
            self._hosts = [f"{self.host}:{self.port}"]
        self._current_host_index = 0
        self._apply_current_host(timeout)
        self._http = httpx.Client(timeout=timeout)
        self._update_urls()

    def _apply_current_host(self, timeout: float = 30.0) -> None:
        """Set self.host and self.port from the current host list entry.

        Does NOT recreate ``self._http`` — the existing client is reused
        (the target host is determined by the URL we send).  Callers that
        need a fresh client (e.g. after a host switch) can do so explicitly.
        """
        hostport = self._hosts[self._current_host_index]
        if ":" in hostport:
            self.host, self.port = hostport.split(":", 1)
        else:
            self.host = hostport
            self.port = "3001"

    def _update_urls(self) -> None:
        """Rebuild sql_url and reducer_url for the current host."""
        base = f"http://{self.host}:{self.port}"
        self.sql_url = f"{base}/v1/database/{self.database}/sql"
        self.reducer_url = f"{base}/v1/database/{self.database}/call"

    def _try_failover(self) -> bool:
        """Switch to the next host in the list.

        Returns True if a new host was selected, False if there is
        only one host configured (no failover possible).
        """
        if len(self._hosts) <= 1:
            return False
        next_idx = (self._current_host_index + 1) % len(self._hosts)
        # Don't cycle back to ourselves if there are exactly 2 hosts — try the other
        if next_idx == self._current_host_index:
            return False
        self._current_host_index = next_idx
        self._apply_current_host()
        self._update_urls()
        # Reset circuit breaker state for the new host
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        logger.info(
            "Failed over to %s:%s (host #%d/%d)",
            self.host,
            self.port,
            self._current_host_index + 1,
            len(self._hosts),
        )
        return True

    def _headers(self) -> dict[str, str]:
        """Return common HTTP headers, including auth if a token is set."""
        headers: dict[str, str] = {}
        # Use explicit JWT token if provided, otherwise use captured identity token
        auth_token = self.token or self._identity_token
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        return headers

    def _emit_event(self, event_type: str, data: dict[str, Any], workspace_id: str = "") -> None:
        """Emit a memory lifecycle event to the configured event bus."""
        if self.event_bus is not None:
            from ..streaming import MemoryEvent

            self.event_bus.emit(
                MemoryEvent(
                    event_type=event_type,
                    data=data,
                    workspace_id=workspace_id,
                )
            )

    def _ensure_identity(self) -> None:
        """Establish a consistent identity with SpacetimeDB.

        Makes an anonymous request to capture the identity token
        from the response, then uses it for all subsequent calls.
        Tries all configured hosts (for multi-region failover).
        Only needed when no explicit JWT token is configured.

        IMPORTANT: on failure we do NOT permanently give up. A transient
        load window (HTTP 500 / connection refused) must not leave the
        client unauthenticated for the rest of the process — that turns
        benchmark questions into "Not authenticated" zero-retrieval
        failures. `_identity_established` stays False so the next call
        retries the handshake.
        """
        if self._identity_established or self.token:
            return
        for host_idx in range(len(self._hosts)):
            hostport = self._hosts[host_idx]
            if ":" in hostport:
                h, p = hostport.split(":", 1)
            else:
                h, p = hostport, "3001"
            try:
                resp = self._http.get(
                    f"http://{h}:{p}/v1/database/{self.database}",
                    timeout=5.0,
                )
                if resp.status_code >= 500:
                    # Transient server error — treat like connect failure so
                    # we can retry on the next call instead of proceeding
                    # unauthenticated.
                    logger.info(
                        "Identity handshake got HTTP %s on %s (host #%d/%d), trying next...",
                        resp.status_code, hostport, host_idx + 1, len(self._hosts),
                    )
                    continue
                token = resp.headers.get("spacetime-identity-token", "")
                if token:
                    self._identity_token = token
                # Pin to the first responsive host
                self.host = h
                self.port = p
                self._current_host_index = host_idx
                self._update_urls()
                self._identity_established = True
                return
            except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError):
                logger.info(
                    "Identity handshake failed for %s (host #%d/%d), trying next...",
                    hostport,
                    host_idx + 1,
                    len(self._hosts),
                )
                continue
        # All hosts failed — do NOT mark identity as established. Keep it
        # unset so the next _call() retries the handshake once STDB recovers.
        logger.warning(
            "Identity handshake failed on all %d hosts — will retry on next call",
            len(self._hosts),
        )

    def _whoami(self) -> str:
        """Return the SpacetimeDB identity used by this client."""
        self._ensure_identity()
        try:
            resp = self._http.get(
                f"http://{self.host}:{self.port}/v1/database/{self.database}",
                headers=self._headers(),
                timeout=5.0,
            )
            return resp.headers.get("spacetime-identity", "")
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError):
            return ""

    # -------------------------------------------------------------------
    # Metrics integration
    # -------------------------------------------------------------------

    def set_metrics_collector(self, collector: Any) -> None:
        """Attach a ``MetricsCollector`` instance to track request metrics.

        The collector must have ``record(endpoint, fn)`` and ``record_latency``
        methods.  See ``spacetime_memory.metrics.MetricsCollector``.
        """
        self._metrics = collector

    def get_metrics(self) -> dict[str, Any] | None:
        """Export collected metrics as a dict, or None if not configured."""
        if self._metrics is None:
            return None
        return self._metrics.to_dict()

    @classmethod
    def from_token_file(
        cls,
        token_path: str,
        host: str | None = None,
        port: int | str | None = None,
        database: str | None = None,
        **kwargs: Any,
    ) -> Client:
        """Create a Client using a JWT token stored in a file.

        The token file can be created with:
            python -c "from spacetime_memory.auth import generate_token; \\
                print(generate_token('data/id_ecdsa_pkcs8.pem'))" > /path/to/token.jwt
        """
        token = Path(token_path).read_text().strip()
        return cls(host=host, port=port, database=database, token=token, **kwargs)

    # -----------------------------------------------------------------------
    # HTTP helpers
    # -----------------------------------------------------------------------

    def _request_with_retry(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Make an HTTP request with retry on connection/timeout errors.

        Retries up to ``self.max_retries`` times with exponential backoff + jitter.
        Does NOT retry on 4xx responses (client errors).

        Includes circuit breaker: after ``_circuit_breaker_threshold`` consecutive
        failures, further requests fail fast (without attempting) for
        ``_circuit_breaker_reset_secs`` seconds.

        When all retries to the current host are exhausted, automatically
        fails over to the next host in ``self._hosts`` (if configured via
        the ``SPACETIMEDB_HOSTS`` environment variable).
        """
        # Circuit breaker check
        now = time.time()
        if self._circuit_open_until > now:
            raise RuntimeError(
                f"SpacetimeDB circuit breaker is open "
                f"(retry in {self._circuit_open_until - now:.0f}s). "
                f"Circuit resets at STMEM_CIRCUIT_RESET_SECS="
                f"{self._circuit_breaker_reset_secs}.\n"
                f"  → Is STDB overloaded? Reduce concurrency. Check: stmem doctor"
            )

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                if method == "POST":
                    resp = self._http.post(url, **kwargs)
                elif method == "GET":
                    resp = self._http.get(url, **kwargs)
                else:
                    resp = self._http.request(method, url, **kwargs)
                # Don't retry client errors (4xx) or application errors (530)
                code = int(getattr(resp, "status_code", 500))
                if code < 500 or code >= 600 or code == 530:
                    # Success or client error — reset circuit breaker
                    self._consecutive_failures = 0
                    self._circuit_open_until = 0.0
                    return resp
                # Server error — retry (502/503/504)
                last_exc = RuntimeError(f"Server error (HTTP {code}) on {url}")
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_exc = e
            except httpx.RemoteProtocolError as e:
                last_exc = e
            if attempt < self.max_retries:
                delay = 0.5 * (2**attempt) * (1 + random.random())
                logger.warning(
                    "Request failed (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1,
                    self.max_retries + 1,
                    last_exc,
                    delay,
                )
                time.sleep(delay)

        # All retries exhausted — try failover to next host before giving up
        if self._try_failover():
            logger.info(
                "Failover to %s:%s — re-trying %s %s",
                self.host,
                self.port,
                method,
                url,
            )
            # Rebuild URL for the new host by replacing the host:port portion
            new_url = re.sub(
                r"http://[^/]+",
                f"http://{self.host}:{self.port}",
                url,
            )
            return self._request_with_retry(method, new_url, **kwargs)

        # No more hosts to try — trip circuit breaker
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._circuit_breaker_threshold:
            self._circuit_open_until = time.time() + self._circuit_breaker_reset_secs
            logger.warning(
                "Circuit breaker opened for %.0fs after %d consecutive failures",
                self._circuit_breaker_reset_secs,
                self._consecutive_failures,
            )
        raise RuntimeError(
            f"Request failed after {self.max_retries + 1} attempts: {last_exc}\n"
            f"  → Is SpacetimeDB running? Check: stmem doctor"
        ) from last_exc

    def _sql(self, query: str) -> list[dict[str, Any]]:
        """Run a SELECT query against the SpacetimeDB SQL API.

        DEPRECATED for content tables — use _query() instead. Content tables
        are now private and SQL queries against them will fail. This method
        remains for public result tables (hybrid_result, etc.).
        """
        with _tracing_span("sql", query=query[:200]):
            self._ensure_identity()
            headers = self._headers()
            headers["Content-Type"] = "text/plain"

            def _do_sql() -> httpx.Response:
                """Execute a raw SQL query via HTTP POST with retry."""
                return self._request_with_retry(
                    "POST",
                    self.sql_url,
                    content=query,
                    headers=headers,
                )

            if self._metrics is not None:
                resp = self._metrics.record("sql", _do_sql)
            else:
                resp = _do_sql()

            if resp.status_code >= 400:
                error_text = resp.text[:500]
                if self.verbose:
                    raise RuntimeError(f"SQL error (HTTP {resp.status_code}): {error_text}")
                friendly = self._map_sql_error(error_text)
                raise RuntimeError(friendly)
            return _parse_sql_response(resp.text)

    def _sql_param(self, query_template: str, *args: Any) -> list[dict[str, Any]]:
        """Parameterized SQL query — `?` placeholders are replaced with
        properly escaped values and run through :meth:`_sql`.

        Escaping rules: strings are single-quoted with embedded quotes
        doubled; bools become 1/0; None becomes NULL; numbers pass through
        unchanged; anything else is stringified and quoted.
        """
        def _fmt(val: Any) -> str:
            if val is None:
                return "NULL"
            if isinstance(val, bool):
                return "1" if val else "0"
            if isinstance(val, (int, float)):
                return str(val)
            s = str(val).replace("'", "''")
            return f"'{s}'"

        parts = query_template.split("?")
        if len(parts) - 1 != len(args):
            raise ValueError(
                f"_sql_param: template has {len(parts) - 1} placeholders but {len(args)} args were given"
            )
        query = parts[0]
        for i, arg in enumerate(args):
            query += _fmt(arg) + parts[i + 1]
        return self._sql(query)

    def _query(
        self,
        table: str,
        workspace_id: str = "",
        filter_dict: dict[str, Any] | None = None,
        columns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Query a private content table through the query_table reducer.

        The reducer checks auth + workspace access and stores results in
        the public query_result table, scoped by a random query_id.
        """

        query_id = secrets.token_hex(16)
        filter_json = json.dumps(filter_dict or {})
        columns_json = json.dumps(columns or [])

        self._call(
            "query_table",
            [
                query_id,
                table,
                workspace_id,
                filter_json,
                columns_json,
            ],
        )

        # Read results from the public query_result table
        rows = self._sql(
            f"SELECT table_name, row_json FROM query_result WHERE query_id = '{_esc(query_id)}'"
        )
        results = []
        for r in rows:
            if "row_json" in r:
                results.append(json.loads(r["row_json"]))
            else:
                # Legacy/mock fallback: row itself is the data
                results.append(r)
        return results

    def _map_sql_error(self, error_text: str) -> str:
        """Map raw SQL error text to a human-friendly message."""
        for pattern, message in _SQL_ERROR_MAP.items():
            if re.search(pattern, error_text, re.IGNORECASE):
                return f"{message} (raw: {error_text[:200]})"
        return f"Database error: {error_text[:300]}"

    def _map_reducer_error(self, error_text: str) -> str:
        """Map raw reducer error text to a human-friendly message."""
        for pattern, message in _REDUCER_ERROR_MAP.items():
            if re.search(pattern, error_text, re.IGNORECASE):
                return f"{message} (raw: {error_text[:200]})"
        return f"Reducer error: {error_text[:300]}"

    def _call(self, reducer: str, args: list[Any]) -> dict[str, Any]:
        """Call a SpacetimeDB reducer with positional JSON args."""
        with _tracing_span(f"reducer:{reducer}", reducer=reducer, arg_count=len(args)):
            self._ensure_identity()
            headers = self._headers()
            headers["Content-Type"] = "application/json"

            def _do_call() -> httpx.Response:
                """Invoke a STDB reducer via HTTP POST with retry."""
                return self._request_with_retry(
                    "POST",
                    f"{self.reducer_url}/{reducer}",
                    content=json.dumps(args),
                    headers=headers,
                )

            if self._metrics is not None:
                resp = self._metrics.record(f"reducer:{reducer}", _do_call)
            else:
                resp = _do_call()

            if resp.status_code >= 400:
                error_text = resp.text[:500]
                if self.verbose:
                    raise RuntimeError(f"Reducer error (HTTP {resp.status_code}): {error_text}")
                friendly = self._map_reducer_error(error_text)
                raise RuntimeError(friendly)

        # Capture updated identity token from response (e.g. after register/login).
        # IMPORTANT: only adopt a new token from auth-relevant reducers, or when
        # we don't yet have one. STDB may echo a fresh *anonymous* identity
        # token on arbitrary responses; adopting it would silently swap the
        # registered account identity for an anonymous one and break
        # workspace-scoped access mid-run ("Not authenticated" / "Access denied"
        # on every later call).
        new_token = resp.headers.get("spacetime-identity-token", "")
        auth_reducers = {"register", "login", "create_auth_session", "verify_login"}
        if new_token and (reducer in auth_reducers or not self.token):
            if new_token != self._identity_token:
                self._identity_token = new_token
                self._identity_established = True
                # Also update self.token so _headers() uses the new token
                self.token = new_token

        return {"status": "ok"}

    def _call_with_result(self, reducer: str, args: list[Any]) -> Any | None:
        """Call a reducer that returns data in the response body.

        Some reducers (e.g. ``get_results``, ``verify_login``) write their
        result directly in the HTTP response JSON under a ``result`` key
        rather than writing to a result table.  This method parses that
        response and returns the result value.

        Returns:
            The parsed result value, or ``None`` if the reducer succeeded
            with no result.
        """
        with _tracing_span(
            f"reducer:{reducer}:with_result",
            reducer=reducer,
            arg_count=len(args),
        ):
            self._ensure_identity()
            headers = self._headers()
            headers["Content-Type"] = "application/json"

            def _do_call() -> httpx.Response:
                return self._request_with_retry(
                    "POST",
                    f"{self.reducer_url}/{reducer}",
                    content=json.dumps(args),
                    headers=headers,
                )

            if self._metrics is not None:
                resp = self._metrics.record(f"reducer:{reducer}", _do_call)
            else:
                resp = _do_call()

            if resp.status_code >= 400:
                error_text = resp.text[:500]
                if self.verbose:
                    raise RuntimeError(
                        f"Reducer error (HTTP {resp.status_code}): {error_text}"
                    )
                friendly = self._map_reducer_error(error_text)
                raise RuntimeError(friendly)

            # Capture updated identity token from response (only from
            # auth-relevant reducers or when no token exists yet — see _call).
            new_token = resp.headers.get("spacetime-identity-token", "")
            auth_reducers = {"register", "login", "create_auth_session", "verify_login"}
            if new_token and (reducer in auth_reducers or not self.token):
                if new_token != self._identity_token:
                    self._identity_token = new_token
                    self._identity_established = True
                    self.token = new_token

            # Parse response body for result data
            try:
                data = resp.json()
            except (json.JSONDecodeError, Exception):
                return None

            if isinstance(data, dict) and "error" in data:
                raise RuntimeError(data["error"])

            if isinstance(data, dict) and data.get("status") == "error":
                msg = data.get("message", "Unknown reducer error")
                raise RuntimeError(msg)

            if isinstance(data, dict) and "result" in data:
                result_val = data["result"]
                if isinstance(result_val, str):
                    try:
                        return json.loads(result_val)
                    except (json.JSONDecodeError, Exception):
                        return result_val
                return result_val

            return None

    def ping(self) -> dict[str, Any]:
        """Quick connectivity check against SpacetimeDB.

        Hits the database info endpoint and reports latency.
        """
        start = time.monotonic()
        try:
            resp = self._request_with_retry(
                "GET",
                f"http://{self.host}:{self.port}/v1/database/{self.database}",
                headers=self._headers(),
                timeout=5.0,
            )
            elapsed = time.monotonic() - start
            if resp.status_code < 400:
                return {"status": "ok", "latency_ms": round(elapsed * 1000, 1)}
            return {
                "status": "error",
                "message": f"HTTP {resp.status_code}",
                "latency_ms": round(elapsed * 1000, 1),
            }
        except (httpx.ConnectError, httpx.TimeoutException, RuntimeError) as e:
            elapsed = time.monotonic() - start
            return {"status": "error", "message": str(e), "latency_ms": round(elapsed * 1000, 1)}

    def health(self) -> dict[str, Any]:
        """Comprehensive health check: SpacetimeDB + embedder + Tantivy sidecar.

        Returns a dict with status for each component including the
        Tantivy BM25 sidecar (port 9091 / ``self.tantivy_url``).
        """
        db_check = self.ping()
        emb_check = self.check_embedder_health()
        tan_check = self.check_tantivy_health()

        all_ok = (
            db_check.get("status") == "ok"
            and emb_check.get("reachable", False)
            and tan_check.get("reachable", False)
        )

        return {
            "status": "ok" if all_ok else "degraded",
            "database": db_check,
            "embedder": emb_check,
            "tantivy": tan_check,
            "token_configured": bool(self.token),
        }

    # -----------------------------------------------------------------------
    # Workspace
    # -----------------------------------------------------------------------

    @property
    def delta_sync(self):
        """Lazy-initialised ``DeltaSync`` instance for change-event polling.

        Usage::

            client.delta_sync.on("memory", "insert", lambda e: print(e))
            client.delta_sync.start()
        """
        if self._delta_sync is None:
            from ..delta_sync import DeltaSync

            self._delta_sync = DeltaSync(self)
        return self._delta_sync

    @property
    def compounder(self):
        """Lazy-initialised ``Compounder`` instance for compound knowledge.

        Usage::

            client.compounder.store_answer(
                query="What is RLHF?",
                answer="Reinforcement Learning from Human Feedback is...",
                source_memory_ids=["mem_123"],
            )

        The ``Compounder`` uses the ``LLMClient`` for entity extraction
        and summary generation.  All methods degrade gracefully when no
        API key is configured.
        """
        if self._compounder is None:
            from ..compounder import Compounder

            self._compounder = Compounder(self)
        return self._compounder

