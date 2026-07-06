"""Python client for spacetime-memory.

Provides a high-level Client class that wraps the SpacetimeDB HTTP SQL API,
the reducer-call endpoint, and embedder support (OpenAI-compatible proxy → NVIDIA NIM).
API fallback.
"""

from __future__ import annotations

import json
import os
import random
import secrets
import time
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

import logging
import re

logger = logging.getLogger(__name__)

from .query_expansion import expand_query  # noqa: E402 — intentional late import
from ._protocols import (  # noqa: E402 — intentional late import
    EventBusProtocol,
    LocalLLMProtocol,
    MetricsCollectorProtocol,
    PluginManagerProtocol,
    QueryCacheProtocol,
)

# ---------------------------------------------------------------------------
# OpenTelemetry tracer — optional, degrades gracefully
# ---------------------------------------------------------------------------

try:
    from .tracer import get_tracer, start_span as _start_span

    _TRACER = get_tracer(setup=True)

    def _tracing_span(name: str, **attrs: Any) -> Any:
        """Start a span with the given attributes. No-op if OTel unavailable."""
        return _start_span(name, attributes=attrs if attrs else None)

except ImportError:

    def _tracing_span(name: str, **attrs: Any) -> Any:
        from contextlib import nullcontext

        return nullcontext()

    _TRACER = None

# ---------------------------------------------------------------------------
# Error message mapping (human-readable)
# ---------------------------------------------------------------------------

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
    """Base exception for SpacetimeDB backend failures.

    Raised when a request to SpacetimeDB fails after retries are exhausted,
    the circuit breaker is open, or the backend returns a non-recoverable
    error.  All adapter code should catch and propagate this (or a more
    specific subclass) rather than returning ``None`` / ``[]`` silently.
    """


class NotFoundError(SpacetimeDBError):
    """Raised when a requested resource (session, memory, workspace) is not found."""


class ApiError(SpacetimeDBError):
    """Raised when SpacetimeDB returns an unexpected API error."""


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------


class JSONFormatter(logging.Formatter):
    """JSON log formatter. Outputs structured log records as newline-delimited JSON."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as newline-delimited JSON.

        Produces structured JSON output with timestamp, level, logger name,
        message, and optional exception info / extra fields.
        """
        log_entry = {
            "ts": self.formatTime(record, self.datefmt or "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Include exception info if present
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Attach extra fields passed via the `extra` parameter
        for key, value in getattr(record, "extra_fields", {}).items():
            log_entry[key] = value
        return json.dumps(log_entry, default=str)


def configure_logging(
    level: str = "INFO",
    json_format: bool = True,
    log_file: str | None = None,
) -> None:
    """Configure structured logging for the SDK.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR).
        json_format: If True, output newline-delimited JSON. If False, plain text.
        log_file: Optional path to a log file. If None, logs to stderr.
    """
    logger = logging.getLogger("spacetime_memory")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
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


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class Client:
    """Spacetime-Memory client.

    Minimal config — point at a running SpacetimeDB instance + embedder.
    All methods return parsed dicts: {"status": "ok"} for writes, or
    list[dict] / dict for reads.

    Embedder type can be one of:

    - ``"openai"`` — use the OpenAI-compatible proxy (HTTP → NVIDIA NIM, default when API key is set)
    - ``"auto"`` — try the sidecar first, fall back to OpenAI if unavailable

    When using ``"openai"`` or ``"auto"`` fallback, set ``OPENAI_API_KEY``
    environment variable.

    Example::

        client = Client()
        ws_id = client.create_workspace("test")["id"]
        client.store(ws_id, "I like pizza", memory_type="experience")
        results = client.search(ws_id, "food preferences", semantic=True)
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | str | None = None,
        database: str | None = None,
        embedder_url: str | None = None,
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
        os.environ.setdefault("no_proxy", "localhost,127.0.0.1,127.0.0.1,.local")
        self.embedder_url = embedder_url or os.environ.get("EMBEDDER_URL", "http://127.0.0.1:4000")
        self.tantivy_url = os.environ.get("TANTIVY_URL", "http://127.0.0.1:9091")
        self.verbose = verbose
        self.token = token or os.environ.get("SPACETIMEDB_TOKEN")
        self.max_retries = int(os.environ.get("STMEM_MAX_RETRIES", "3"))
        self._circuit_breaker_threshold = int(os.environ.get("STMEM_CIRCUIT_THRESHOLD", "5"))
        self._circuit_breaker_reset_secs = float(os.environ.get("STMEM_CIRCUIT_RESET_SECS", "30.0"))
        self._consecutive_failures: int = 0
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
            from .streaming import MemoryEvent

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
        # All hosts failed — proceed without identity
        logger.warning(
            "Identity handshake failed on all %d hosts — proceeding without identity",
            len(self._hosts),
        )
        self._identity_established = True

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
    ) -> "Client":
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

        # Capture updated identity token from response (e.g. after register/login)
        new_token = resp.headers.get("spacetime-identity-token", "")
        if new_token and new_token != self._identity_token:
            self._identity_token = new_token
            self._identity_established = True

        return {"status": "ok"}

    _DEFAULT_EMBEDDER_URL = "http://127.0.0.1:4000"

    def _embed(self, text: str) -> list[float]:
        """Get an embedding vector via the configured embedding API.

        Uses the OpenAI-compatible proxy path (bge-m3 through
        spacetime-llm proxy → NVIDIA NIM, 1024-dim).
        """
        with _tracing_span("embed", text_length=len(text)):
            return self._embed_openai(text)

    def _embed_openai(self, text: str) -> list[float]:
        """Embed via OpenAI API."""
        with _tracing_span("embed.openai", text_length=len(text)):
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                logger.warning("OPENAI_API_KEY not set, cannot use OpenAI embedder fallback")
                return []
            try:
                base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip(
                    "/"
                )
                resp = self._request_with_retry_simple(
                    "POST",
                    f"{base_url}/embeddings",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "input": text,
                        "model": os.environ.get("EMBEDDING_MODEL", "text-embedding-3-large"),
                    }
                    | (
                        {}
                        if not os.environ.get("EMBEDDING_DIMENSIONS")
                        else {"dimensions": int(os.environ["EMBEDDING_DIMENSIONS"])}
                    ),
                    timeout=30,
                )
                if resp is None:
                    logger.warning("OpenAI embedder failed for text (len=%d) — all retries exhausted", len(text))
                    return []
                resp.raise_for_status()
                data = resp.json()
                return data["data"][0]["embedding"]
            except httpx.TimeoutException:
                logger.warning("OpenAI embedder timed out for text (len=%d)", len(text))
                return []
            except (json.JSONDecodeError, httpx.HTTPError, KeyError, IndexError, ValueError):
                logger.exception("OpenAI embedder failed for text (len=%d)", len(text))
                return []

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for multiple texts.

        Uses the OpenAI-compatible proxy path through _embed_batch_openai.
        """
        if not texts:
            return []
        with _tracing_span("embed.batch", batch_size=len(texts)):
            return self._embed_batch_openai(texts)

    def _embed_batch_openai(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for multiple texts via OpenAI API."""
        if not texts:
            return []
        with _tracing_span("embed.batch.openai", batch_size=len(texts)):
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                logger.warning("OPENAI_API_KEY not set, cannot use OpenAI embedder fallback")
                return []
            try:
                base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip(
                    "/"
                )
                resp = self._request_with_retry_simple(
                    "POST",
                    f"{base_url}/embeddings",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "input": texts,
                        "model": os.environ.get("EMBEDDING_MODEL", "text-embedding-3-large"),
                    }
                    | (
                        {}
                        if not os.environ.get("EMBEDDING_DIMENSIONS")
                        else {"dimensions": int(os.environ["EMBEDDING_DIMENSIONS"])}
                    ),
                    timeout=60,
                )
                if resp is None:
                    logger.warning("OpenAI embedder failed for batch (count=%d) — all retries exhausted", len(texts))
                    return []
                resp.raise_for_status()
                data = resp.json()
                # OpenAI returns data in order matching input
                results = [item["embedding"] for item in data["data"]]
                return results
            except httpx.TimeoutException:
                logger.warning("OpenAI embedder timed out for batch (count=%d)", len(texts))
                return []
            except (json.JSONDecodeError, httpx.HTTPError, KeyError, IndexError, ValueError):
                logger.exception("OpenAI embedder failed for batch (count=%d)", len(texts))
                return []

    def check_embedder_health(self) -> dict[str, Any]:
        """Check if the embedder sidecar is running. Returns status info."""
        with _tracing_span("embedder.health"):
            try:
                resp = self._request_with_retry(
                    "GET", f"{self.embedder_url}/health", timeout=5.0
                )
                if resp.status_code == 200:
                    embedder_status = resp.json()
                    embedder_status["reachable"] = True
                    return embedder_status
                return {"status": "error", "code": resp.status_code, "reachable": True}
            except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError, RuntimeError) as e:
                return {"status": "error", "message": str(e), "reachable": False}

    def _request_with_retry_simple(
        self, method: str, url: str, **kwargs: Any
    ) -> httpx.Response | None:
        """Make an HTTP request with retry, WITHOUT touching the circuit breaker.

        Used for external APIs (OpenAI) where failures should NOT trip the
        SpacetimeDB circuit breaker. Returns ``None`` if all retries fail.
        """
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                if method == "POST":
                    resp = self._http.post(url, **kwargs)
                elif method == "GET":
                    resp = self._http.get(url, **kwargs)
                else:
                    resp = self._http.request(method, url, **kwargs)
                return resp
            except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as e:
                last_exc = e
            if attempt < self.max_retries:
                delay = 0.5 * (2**attempt) * (1 + random.random())
                logger.warning(
                    "Request failed (attempt %d/%d) — %s. Retrying in %.1fs...",
                    attempt + 1,
                    self.max_retries + 1,
                    last_exc,
                    delay,
                )
                time.sleep(delay)
        logger.warning(
            "Request failed after %d attempts (no circuit): %s",
            self.max_retries + 1,
            last_exc,
        )
        return None

    # ── Tantivy BM25 keyword search sidecar ──

    def _tantivy_index(
        self,
        workspace_id: str,
        entity_id: str,
        content: str,
        entity_type: str = "memory",
    ) -> bool:
        """Index a document into the Tantivy BM25 sidecar."""
        try:
            resp = self._request_with_retry(
                "POST",
                f"{self.tantivy_url}/index",
                json={
                    "workspace_id": workspace_id,
                    "entity_id": entity_id,
                    "content": content,
                    "entity_type": entity_type,
                },
                timeout=5.0,
            )
            return resp.status_code < 400
        except (httpx.ConnectError, httpx.TimeoutException, RuntimeError):
            return False

    def _tantivy_index_batch(
        self,
        items: list[dict[str, str]],
    ) -> bool:
        """Index multiple documents into the Tantivy BM25 sidecar in a single HTTP call.

        Args:
            items: List of dicts, each with keys: workspace_id, entity_id, content, entity_type.

        Returns:
            True if the batch call succeeded (HTTP < 400).
        """
        if not items:
            return True
        try:
            resp = self._request_with_retry(
                "POST",
                f"{self.tantivy_url}/index/batch",
                json={"items": items},
                timeout=max(5.0 * len(items), 30.0),
            )
            return resp.status_code < 400
        except (httpx.ConnectError, httpx.TimeoutException, RuntimeError):
            return False

    def _tantivy_search(
        self,
        workspace_id: str,
        query: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search Tantivy BM25 index and return scored results.

        Returns list of dicts with keys: entity_id, score, content, entity_type.
        Scores are raw BM25 — already in a useful range (typically 0-20+).
        """
        try:
            resp = self._request_with_retry(
                "POST",
                f"{self.tantivy_url}/search",
                json={
                    "workspace_id": workspace_id,
                    "query": query,
                    "limit": limit,
                },
                timeout=5.0,
            )
            if resp.status_code >= 400:
                return []
            return resp.json()
        except (httpx.ConnectError, httpx.TimeoutException, RuntimeError):
            return []

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
        """Comprehensive health check: SpacetimeDB + embedder.

        Returns a dict with status for each component.
        """
        db_check = self.ping()
        emb_check = self.check_embedder_health()

        all_ok = db_check.get("status") == "ok" and emb_check.get("reachable", False)

        return {
            "status": "ok" if all_ok else "degraded",
            "database": db_check,
            "embedder": emb_check,
            "token_configured": bool(self.token),
        }

    # -----------------------------------------------------------------------
    # Workspace
    # -----------------------------------------------------------------------

    def create_workspace(
        self, name: str, description: str = "", id: str | None = None
    ) -> dict[str, Any]:
        """Create a new workspace. Returns reducer status plus the workspace id.
        If *id* is omitted, generates a UUID client-side matching the reducer's
        UUID v4 format so callers can discover it immediately via list_workspaces.
        """
        import uuid

        ws_id = id if id else uuid.uuid4().hex[:32]
        self._call("create_workspace", [name, description, ws_id])
        return {"status": "ok", "id": ws_id}

    def list_workspaces(self) -> list[dict[str, Any]]:
        """List all workspaces."""
        return self._query("workspace")

    def delete_workspace(self, workspace_id: str) -> dict[str, Any]:
        """Delete a workspace and all its data."""
        return self._call("delete_workspace", [workspace_id])

    def update_workspace(self, id: str, name: str, description: str) -> dict[str, Any]:
        """Update a workspace's name and description. Requires owner access.

        Args:
            id: The workspace ID.
            name: New name for the workspace.
            description: New description for the workspace.

        Returns:
            Dict with reducer response status.
        """
        return self._call("update_workspace", [id, name, description])

    def set_workspace_visibility(self, workspace_id: str, is_public: bool) -> dict[str, Any]:
        """Toggle whether a workspace is public or private. Requires owner access.

        Args:
            workspace_id: The workspace to update.
            is_public: True to make public, False to make private.

        Returns:
            Dict with reducer response status.
        """
        return self._call("set_workspace_visibility", [workspace_id, is_public])

    def get_workspace_context(self, workspace_id: str) -> dict[str, Any]:
        """Get the context string attached to a workspace.

        Calls the ``get_workspace_context`` reducer which writes to the
        ``workspace_context_result`` table, then queries that table.

        Args:
            workspace_id: The workspace to retrieve context for.

        Returns:
            Dict with workspace_id, context, and queried_at fields.
        """
        self._call("get_workspace_context", [workspace_id])
        rows = self._query("workspace_context_result")
        if rows:
            return rows[0]
        return {"workspace_id": workspace_id, "context": "", "queried_at": 0}

    def list_space_members(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all members with their permissions for a workspace.

        Calls the ``list_space_members`` reducer which writes to the
        ``space_member_result`` table, then queries that table.

        Args:
            workspace_id: The workspace (space) ID.

        Returns:
            A list of dicts with keys: id, workspace_id, peer_id, permission,
            granted_by, created_at, queried_at.
        """
        self._call("list_space_members", [workspace_id])
        rows = self._query("space_member_result")
        rows.sort(key=lambda r: r.get("created_at", 0))
        return rows

    def grant_space_access(
        self, workspace_id: str, peer_id: str, permission: str
    ) -> dict[str, Any]:
        """Grant a peer access to a workspace with a specific permission level.

        Only an existing owner or admin can grant access.

        Args:
            workspace_id: The workspace (space) ID.
            peer_id: The peer ID to grant access to.
            permission: One of ``'owner'``, ``'editor'``, or ``'viewer'``.

        Returns:
            Reducer status.
        """
        return self._call("grant_space_access", [workspace_id, peer_id, permission])

    def revoke_space_access(self, workspace_id: str, peer_id: str) -> dict[str, Any]:
        """Revoke a peer's access to a workspace.

        Only an existing owner or admin can revoke access. Owners cannot
        revoke their own access (use a separate escalation process).

        Args:
            workspace_id: The workspace (space) ID.
            peer_id: The peer ID to revoke access from.

        Returns:
            Reducer status.
        """
        return self._call("revoke_space_access", [workspace_id, peer_id])

    # -----------------------------------------------------------------------
    # Auth / Account
    # -----------------------------------------------------------------------

    def register(
        self, username: str, display_name: str = "", password: str = ""
    ) -> dict[str, Any]:
        """Register a new account. First user becomes admin.

        Args:
            username: Unique username for the account.
            display_name: Optional display name (defaults to username).
            password: Password (minimum 6 characters). If empty, generates
                a warning — the Rust reducer enforces >=6 chars.

        Returns:
            Reducer status dict.
        """
        return self._call("register", [username, display_name, password])

    def login(self, username: str, password: str) -> dict[str, Any]:
        """Login with username + password. Links this identity to the account.

        After a successful login, the caller's identity is associated with
        this account. A new identity token is captured from the response
        headers automatically by :meth:`_call`.

        Args:
            username: Account username.
            password: Account password.

        Returns:
            Reducer status dict.
        """
        return self._call("login", [username, password])

    def logout(self) -> dict[str, Any]:
        """Logout — detach the current identity from its account.

        After logout, the caller must re-login to access gated features.

        Returns:
            Reducer status dict.
        """
        return self._call("logout", [])

    def update_account(
        self,
        display_name: str = "",
        current_password: str = "",
        new_password: str = "",
    ) -> dict[str, Any]:
        """Update account display name and/or password.

        Args:
            display_name: New display name (empty = no change).
            current_password: Current password (required for verification).
            new_password: New password (empty = no change, min 6 chars).

        Returns:
            Reducer status dict.
        """
        return self._call("update_account", [display_name, current_password, new_password])

    def deactivate_account(self, password: str) -> dict[str, Any]:
        """Deactivate (soft-delete) this account.

        The account remains in the database with ``is_active = false``,
        preventing future logins. Cannot be reversed through the API.

        Args:
            password: Account password (required for verification).

        Returns:
            Reducer status dict.
        """
        return self._call("deactivate_account", [password])

    def promote_admin(self, target_identity: str) -> dict[str, Any]:
        """Promote a user to admin. Caller must be an existing admin.

        Args:
            target_identity: The identity hex string of the user to promote.

        Returns:
            Reducer status dict.
        """
        return self._call("promote_admin", [target_identity])

    def demote_admin(self, target_identity: str) -> dict[str, Any]:
        """Demote an admin to regular user. Caller must be an existing admin.

        Cannot demote yourself. At least one admin must always remain.

        Args:
            target_identity: The identity hex string of the admin to demote.

        Returns:
            Reducer status dict.
        """
        return self._call("demote_admin", [target_identity])

    def list_admins(self) -> list[dict[str, Any]]:
        """List all admin accounts.

        Results are read from the admin_result public table after calling
        the reducer.

        Returns:
            List of admin account records.
        """
        self._call("list_admins", [])
        return self._query("admin_result")

    # -----------------------------------------------------------------------
    # Memory
    # -----------------------------------------------------------------------

    @dataclass
    class MemoryRecord:
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
        def from_dict(cls, d: dict) -> "Client.MemoryRecord":
            """Create a MemoryRecord from a dictionary, filtering to field names only.

            Args:
                d: Dictionary of memory record fields.

            Returns:
                A MemoryRecord instance with only recognised fields populated.
            """
            return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def store(
        self,
        workspace_id: str,
        content: str = "",
        summary: str = "",
        memory_type: str = "experience",
        peer_id: str = "",
        observer_id: str = "",
        entities_json: str = "[]",
        confidence: float = 0.8,
        source_session_id: str = "",
        source_message_id: str = "",
        tier: str = "",
        veracity_tier: str = "",
        veracity_sources: int = 1,
    ) -> dict[str, Any]:
        """Store a memory. Auto-indexes via the embedder.

        Args:
            veracity_tier: Mnemosyne veracity tier — one of "stated",
                "unknown", "inferred", "imported", "tool". Overrides
                ``confidence`` using Bayesian compounding.
            veracity_sources: Number of independent confirmations of
                this fact (default 1 = no compounding). Used with
                ``veracity_tier`` to compute compounded confidence.
        """
        # Compute Bayesian confidence from veracity tier if provided
        if veracity_tier and veracity_tier != "unknown":
            from .veracity import compound, VeracityTier

            try:
                tier_enum = VeracityTier(veracity_tier)
                confidence = compound(tier=tier_enum, sources=max(1, veracity_sources))
            except ValueError:
                logger.warning("Unknown VeracityTier string '%s', keeping default confidence", veracity_tier)

        # ── Plugin dispatch: on_store ──
        metadata: dict[str, Any] = {
            "memory_type": memory_type,
            "confidence": confidence,
            "tier": tier,
            "veracity_tier": veracity_tier,
        }
        if self.plugin_manager is not None:
            content, metadata = self.plugin_manager.dispatch_store(content, metadata)

        # ── Reducer call: store_memory ──
        with _tracing_span("store.call", workspace_id=workspace_id, memory_type=memory_type):
            result = self._call(
                "store_memory",
                [
                    workspace_id,
                    peer_id,
                    observer_id,
                    memory_type,
                    content,
                    summary,
                    entities_json,
                    confidence,
                    source_session_id,
                    source_message_id,
                ],
            )
        # ── Invalidate query cache for this workspace ──
        if self._query_cache is not None:
            self._query_cache.invalidate(workspace_id=workspace_id)

        # ── Emit memory.created event ──
        self._emit_event(
            "memory.created",
            {
                "content": content[:200],
                "summary": summary,
                "memory_type": memory_type,
                "workspace_id": workspace_id,
            },
            workspace_id=workspace_id,
        )

        # If the embedder is reachable, index embeddings in the sidecar
        emb = self._embed(content)
        if emb:
            # Resolve the memory ID by content match — more reliable than
            # peer_id query which can return a different concurrent store.
            mems = self._query(
                "memory", workspace_id=workspace_id, filter_dict={}, columns=["id", "content"]
            )
            memory_id = ""
            for m in reversed(mems):
                if m.get("content", "") == content:
                    memory_id = m["id"]
                    break
            if memory_id:
                # Compute and cache MIB binary vector (32x compression)
                from .binary_vectors import binarize

                try:
                    self._binary_cache[memory_id] = binarize(emb)
                except (ValueError, Exception):
                    logger.warning("store_batch: binary compression failed for memory %s, skipping", memory_id)
                self._call(
                    "index_entity",
                    [
                        workspace_id,
                        "memory",
                        memory_id,
                        content,
                        json.dumps(emb),
                    ],
                )
                # Populate BM25 inverted index (legacy STDB term_index)
                self._call(
                    "index_terms",
                    [
                        workspace_id,
                        "memory",
                        memory_id,
                        content,
                    ],
                )

                # Index into Tantivy BM25 sidecar (real Okapi BM25)
                self._tantivy_index(workspace_id, memory_id, content, "memory")

                # Entity extraction: LLM first, fall back to regex
                self._extract_and_store_entities(workspace_id, memory_id, content)

        if tier and tier in ("L0", "L1", "L2"):
            mems = self._query(
                "memory",
                workspace_id=workspace_id,
                filter_dict={"peer_id": peer_id},
                columns=["id"],
            )
            if mems:
                self._call("update_memory_tier", [mems[-1]["id"], tier])

        return result

    def _extract_and_store_entities(
        self,
        workspace_id: str,
        memory_id: str,
        content: str,
    ) -> None:
        """Extract entities from content and store in entity_link/kg_node.

        Tries LLM extraction first (requires OPENAI_API_KEY), falls back
        to the regex-based ``extract_entities`` reducer.
        """
        from .llm import LLMClient

        llm = LLMClient()
        entities = llm.extract_entities_llm(content) if llm.available else None

        if entities:
            for ent in entities:
                name = ent.get("name", "")
                if not name or len(name) < 2:
                    continue
                etype = ent.get("entity_type", "unknown")
                aliases = ent.get("aliases", [])
                description = ent.get("description", name)

                try:
                    self._call(
                        "create_entity_link",
                        [
                            workspace_id,
                            name,
                            etype,
                            json.dumps(aliases[:10] if aliases else []),
                            description,
                        ],
                    )
                except RuntimeError:
                    logger.warning("store(): LLM entity extraction call failed for memory %s", memory_id)

                # Link entity to the source memory
                try:
                    self._call(
                        "link_entity_to_memory",
                        [
                            name,
                            memory_id,
                            etype,
                        ],
                    )
                except RuntimeError:
                    logger.warning("store(): link_entity_to_memory failed for entity '%s', memory %s", name, memory_id)
        else:
            # Fall back to regex-based extraction (no LLM key or LLM failed)
            try:
                self._call("extract_entities", [workspace_id, content])
            except RuntimeError:
                logger.warning("store(): regex entity extraction failed for memory %s", memory_id)

    def store_batch(
        self,
        workspace_id: str,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Store multiple memories in a single reducer call.

        Embeds all items in one batch call to the embedder, then sends a
        single ``store_memory_batch`` reducer with all items.  Much faster
        than N sequential ``store()`` calls when the embedder sidecar is
        the bottleneck.

        After the STDB reducer, indexes all items into the Tantivy BM25
        sidecar in a single batch HTTP call (``/index/batch``) instead of
        N sequential calls.

        Args:
            workspace_id: Target workspace UUID.
            items: List of dicts, each with:
                - ``content`` (str, required)
                - ``summary`` (str, optional)
                - ``memory_type`` (str, default ``"experience"``)
                - ``peer_id`` (str, optional)
                - ``observer_id`` (str, optional)
                - ``entities_json`` (str, optional)
                - ``confidence`` (float, default 0.8)
                - ``source_session_id`` (str, optional)
                - ``source_message_id`` (str, optional)

        Returns:
            List of reducer result dicts.
        """
        # Extract contents for batch embedding
        contents = []
        clean_items = []
        for item in items:
            content = item.get("content", "")
            if not content:
                continue
            contents.append(content)
            clean_items.append(
                {
                    "workspace_id": workspace_id,
                    "peer_id": item.get("peer_id", ""),
                    "observer_id": item.get("observer_id", ""),
                    "memory_type": item.get("memory_type", "experience"),
                    "content": content,
                    "summary": item.get("summary", content[:200]),
                    "entities_json": item.get("entities_json", "[]"),
                    "confidence": item.get("confidence", 0.8),
                    "source_session_id": item.get("source_session_id", ""),
                    "source_message_id": item.get("source_message_id", ""),
                }
            )

        if not clean_items:
            return []

        # Batch-embed
        try:

            resp = self._http.post(
                f"{self.embedder_url}/embed",
                content=json.dumps({"texts": contents}),
                headers={"Content-Type": "application/json"},
                timeout=max(10.0 * len(contents), 30.0),
            )
            if resp.status_code < 400:
                emb_list = resp.json().get("embeddings", [])
                if not emb_list and resp.json().get("embedding"):
                    emb_list = [resp.json().get("embedding", [])]
            else:
                emb_list = []
        except RuntimeError:
            logger.warning("store_batch: get_embeddings_batch failed, returning empty embeddings")
            emb_list = []

        # Call batch reducer — pass items as JSON string

        with _tracing_span(
            "store_batch.call", workspace_id=workspace_id, batch_size=len(clean_items)
        ):
            self._call("store_memory_batch", [json.dumps(clean_items)])

        # Batch-index all items with embeddings via single reducer calls.
        # Query back the inserted memories by content prefix, then call
        # index_entity_batch and index_terms_batch instead of N individual calls.
        entity_items = []
        terms_items = []

        for i, item in enumerate(clean_items):
            emb = emb_list[i] if i < len(emb_list) else None
            if emb:
                entity_items.append({
                    "workspace_id": workspace_id,
                    "entity_type": "memory",
                    "entity_id": "",  # filled below after query
                    "content": item["content"],
                    "embedding_json": json.dumps(emb),
                })
                terms_items.append({
                    "workspace_id": workspace_id,
                    "entity_type": "memory",
                    "entity_id": "",  # filled below after query
                    "content": item["content"],
                })

        if entity_items:
            # Query all matching memories in one batch — match by content prefix
            mems = self._query(
                "memory",
                workspace_id=workspace_id,
                columns=["id", "content"],
            )
            # Build a map from content[:100] -> most recent memory id
            content_to_id: dict[str, str] = {}
            for m in sorted(
                mems,
                key=lambda x: x.get("created_at", 0),
                reverse=True,
            ):
                key = m.get("content", "")[:100]
                if key not in content_to_id:
                    content_to_id[key] = m["id"]

            # Fill in entity_ids
            for ei, ti in zip(entity_items, terms_items):
                mid = content_to_id.get(ei["content"][:100], "")
                ei["entity_id"] = mid
                ti["entity_id"] = mid

            # Single batch call to index_entity_batch (all items with embeddings)
            self._call("index_entity_batch", [json.dumps(entity_items)])

            # Single batch call to index_terms_batch (only items with matched IDs)
            valid_terms = [t for t in terms_items if t["entity_id"]]
            if valid_terms:
                self._call("index_terms_batch", [json.dumps(valid_terms)])

            # Single batch Tantivy index call — all items with matched IDs in one HTTP request
            tantivy_items = []
            for ei in entity_items:
                if ei["entity_id"]:
                    tantivy_items.append({
                        "workspace_id": workspace_id,
                        "entity_id": ei["entity_id"],
                        "content": ei["content"],
                        "entity_type": ei["entity_type"],
                    })
            if tantivy_items:
                self._tantivy_index_batch(tantivy_items)

            # Entity extraction is LLM-based — still per-item (not a reducer)
            for ei in entity_items:
                if ei["entity_id"]:
                    self._extract_and_store_entities(
                        workspace_id,
                        ei["entity_id"],
                        ei["content"],
                    )

        return [{"status": "ok"} for _ in clean_items]

    def _fuse_and_deduplicate(
        self,
        rows: list[dict[str, Any]],
        tantivy_rows: list[dict[str, Any]],
        per_strat: dict[str, list[dict]],
        strat_min: dict[str, float],
        strat_max: dict[str, float],
        strategy_weights: dict[str, float],
    ) -> list[dict[str, Any]]:
        """Min-max normalize per strategy, weighted-sum fuse, dedup by entity_id."""
        best_per_strat: dict[str, dict[str, float]] = {
            "semantic": {},
            "keyword": {},
            "graph": {},
            "temporal": {},
            "binary": {},
        }
        best_row: dict[str, dict] = {}
        all_rows = list(rows)
        for tr in tantivy_rows:
            eid = tr.get("entity_id", "")
            if eid not in best_row:
                all_rows.append(tr)
        for r in all_rows:
            s = r.get("strategy", "")
            if s not in best_per_strat:
                continue
            sc = float(r.get("score", 0.0))
            eid = r.get("entity_id", "")
            rng = strat_max.get(s, 1.0) - strat_min.get(s, 0.0)
            normalized = ((sc - strat_min.get(s, 0.0)) / rng) if rng > 1e-10 else 1.0
            if eid not in best_per_strat[s] or normalized > best_per_strat[s][eid]:
                best_per_strat[s][eid] = normalized
            if eid not in best_row or sc > float(best_row[eid].get("score", 0)):
                best_row[eid] = dict(r)

        fused: dict[str, float] = {}
        for eid in set().union(*(d.keys() for d in best_per_strat.values())):
            total = 0.0
            for s, w in strategy_weights.items():
                total += best_per_strat[s].get(eid, 0.0) * w
            fused[eid] = total

        seen: dict[str, dict] = {}
        for r in all_rows:
            eid = r.get("entity_id", "")
            fs = fused.get(eid, 0.0)
            r["fused_score"] = fs
            if eid not in seen or fs > seen[eid].get("fused_score", float("-inf")):
                seen[eid] = r

        result = list(seen.values())
        result.sort(key=lambda r: r.get("fused_score", 0.0), reverse=True)
        return result

    def _enrich_content(
        self,
        rows: list[dict[str, Any]],
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """Look up memory/node/note content from STDB and apply veracity weighting.

        Uses the ``content`` field already present in hybrid_result rows.
        Batches confidence lookups via a single ``_query()`` to avoid N+1.
        """
        mem_ids = list({r.get("entity_id", "") for r in rows if r.get("entity_type") == "memory"})
        node_ids = list({r.get("entity_id", "") for r in rows if r.get("entity_type") == "node"})
        note_ids = list({r.get("entity_id", "") for r in rows if r.get("entity_type") == "note"})
        mem_confidences: dict[str, float] = {}
        node_map: dict[str, str] = {}
        note_map: dict[str, str] = {}

        # Batch fetch memory confidences — only for veracity weighting
        if mem_ids:
            try:
                mems = self._query(
                    "memory",
                    workspace_id=workspace_id,
                    columns=["id", "confidence"],
                    filter_dict={},
                )
                # Build confidence map from ALL memories (filter dict doesn't support IN)
                for m in mems:
                    if m.get("id") in mem_ids:
                        mem_confidences[m["id"]] = m.get("confidence", 0.8)
            except RuntimeError:
                logger.warning("_enrich_content: batch confidence lookup failed, skipping veracity")
        if node_ids:
            try:
                nodes = self._query("kg_node", columns=["id", "label"])
                for n in nodes:
                    if n.get("id") in node_ids:
                        node_map[n["id"]] = n.get("label", "")
            except RuntimeError:
                pass
        if note_ids:
            try:
                notes = self._query("note", workspace_id=workspace_id, columns=["id", "title", "content"])
                for n in notes:
                    if n.get("id") in note_ids:
                        note_map[n["id"]] = n.get("title", "") + "\n\n" + n.get("content", "")
            except RuntimeError:
                pass
        for r in rows:
            eid = r.get("entity_id", "")
            if r.get("entity_type") == "memory":
                r["memory_content"] = r.get("content", "")
            elif r.get("entity_type") == "node":
                r["memory_content"] = node_map.get(eid, "")
            elif r.get("entity_type") == "note":
                r["memory_content"] = note_map.get(eid, "")
            else:
                r["memory_content"] = ""
            # Add content snippet for callers that only need a preview
            content_text = r.get("memory_content", "") or r.get("content", "")
            r["snippet"] = _make_snippet(content_text)
            r["score"] = r.get("fused_score", r.get("score", 0.0))
            if eid in mem_confidences:
                from .veracity import confidence_multiplier

                mult = confidence_multiplier(mem_confidences[eid])
                r["score"] = r["score"] * mult
                r["veracity_multiplier"] = mult
        return rows

    def _keyword_fallback(
        self,
        workspace_id: str,
        query: str,
        memory_type: str,
        tier: str,
        limit: int,
        before: float | int | None = None,
        after: float | int | None = None,
    ) -> list[dict[str, Any]]:
        """Non-semantic keyword-only search fallback using client-side filtering.

        Searches both the ``memory`` table and the ``note`` table, merging
        results sorted by ``created_at`` descending.

        Args:
            before: Optional Unix timestamp — only return results with
                    ``created_at < before``.
            after: Optional Unix timestamp — only return results with
                    ``created_at > after``.
        """
        clauses = [f"workspace_id = '{_esc(workspace_id)}'"]
        if memory_type:
            clauses.append(f"memory_type = '{_esc(memory_type)}'")
        if tier:
            clauses.append(f"tier = '{_esc(tier)}'")
        filt = {}
        for clause in clauses:
            parts = clause.split(" = ", 1)
            if len(parts) == 2:
                key = parts[0].strip()
                val = parts[1].strip().strip("'")
                filt[key] = val
        rows = self._query("memory", workspace_id=workspace_id, filter_dict=filt)

        # Also fetch notes for keyword search
        note_rows = self._query("note", workspace_id=workspace_id, filter_dict={})
        for nr in note_rows:
            nr["entity_type"] = "note"
            nr["entity_id"] = nr["id"]

        if query:
            _STOPWORDS = {
                "a",
                "an",
                "the",
                "is",
                "are",
                "was",
                "were",
                "be",
                "been",
                "who",
                "what",
                "where",
                "when",
                "why",
                "how",
                "which",
                "do",
                "does",
                "did",
                "has",
                "have",
                "had",
                "can",
                "will",
                "would",
                "tell",
                "me",
                "about",
                "of",
                "in",
                "on",
                "at",
                "to",
                "for",
                "with",
                "and",
                "or",
                "not",
                "we",
                "our",
                "us",
                "i",
                "you",
                "they",
                "it",
                "its",
                "s",
                "that",
                "this",
                "there",
                "from",
            }
            keywords = [
                w.lower().rstrip("?,.:;!\"'")
                for w in query.split()
                if len(w.rstrip("?,.:;!\"'")) > 1
                and w.lower().rstrip("?,.:;!\"'") not in _STOPWORDS
            ]
            if keywords:
                rows = [
                    r
                    for r in rows
                    if any(
                        kw in r.get("content", "").lower() or kw in r.get("summary", "").lower()
                        for kw in keywords
                    )
                ]
                note_rows = [
                    nr
                    for nr in note_rows
                    if any(
                        kw in nr.get("content", "").lower() or kw in nr.get("title", "").lower()
                        for kw in keywords
                    )
                ]

        # Tag memory rows with entity_type for consistency
        for r in rows:
            r["entity_type"] = r.get("entity_type", "memory")
        # Merge, deduplicate by (entity_type, entity_id), sort by created_at desc
        seen: dict[tuple[str, str], dict] = {}
        for r in rows + note_rows:
            et = r.get("entity_type", "memory")
            eid = r.get("entity_id") or r.get("id", "")
            key = (et, eid)
            if key not in seen or r.get("created_at", 0) > seen[key].get("created_at", 0):
                seen[key] = r
        all_rows = list(seen.values())
        all_rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        results = all_rows[:limit]
        # Assign baseline fused_score for entity-aware boosting
        max_idx = max(len(results) - 1, 1)
        for idx, r in enumerate(results):
            r["fused_score"] = 1.0 - (idx / max_idx)
        # Add content snippets for callers that only need a preview
        for r in results:
            content_text = (
                r.get("content", "") or r.get("memory_content", "") or r.get("summary", "")
            )
            r["snippet"] = _make_snippet(content_text)
        # Apply entity-aware boosting with entity_link alias support
        if query:
            results = self._boost_with_entity_signal(query, results, workspace_id)
        self._emit_event(
            "search.performed",
            {
                "query": query,
                "result_count": len(results),
            },
            workspace_id=workspace_id,
        )
        # ── Date range filter (before/after) ──
        if before is not None or after is not None:
            filtered = []
            for r in results:
                ts = r.get("created_at")
                if ts is None:
                    continue
                if before is not None and not (ts < before):
                    continue
                if after is not None and not (ts > after):
                    continue
                filtered.append(r)
            results = filtered
        return results

    # ------------------------------------------------------------------
    # Entity-aware search result boosting (mem0 v3 multi-signal parity)
    def _boost_with_entity_signal(
        self,
        query: str,
        rows: list[dict[str, Any]],
        workspace_id: str,
        *,
        boost_factor: float = 0.15,
    ) -> list[dict[str, Any]]:
        """Boost search results that mention entities found in the query.

        Inspired by mem0 v3's multi-signal retrieval: if the query mentions
        a known knowledge-graph entity (label or summary match) OR an
        entity_link alias (e.g. "reinforcement learning from human feedback"
        matching the canonical "RLHF" entity), results whose content
        references that entity get a fused_score boost.

        Operates in-place on the ``fused_score`` of each row and re-sorts.

        Args:
            query: The search query.
            rows: Search results after ``_enrich_content`` (must have
                  ``memory_content`` or ``content`` key).
            workspace_id: Target workspace for entity lookup.
            boost_factor: Maximum fractional boost applied to entity-matching
                          results (default 0.15 = +15%).

        Returns:
            Rows with adjusted ``fused_score`` values, re-sorted
            highest-first.  If no entities are found in the query or
            the KG lookup fails, returns rows unchanged.
        """
        if not rows or not query:
            return rows

        # Fetch KG nodes from this workspace
        try:
            nodes = self._query(
                "kg_node",
                workspace_id=workspace_id,
                columns=["id", "label", "summary", "node_type"],
            )
        except RuntimeError:
            logger.warning("get_graph_context: query kg_node failed, returning partial results")
            return rows  # Graceful degradation

        # Fetch entity_link records for alias matching
        try:
            links = self._query(
                "entity_link",
                workspace_id=workspace_id,
                columns=["id", "entity_name", "aliases_json", "entity_type"],
            )
        except RuntimeError:
            logger.debug("get_graph_context: entity_link table may not exist, skipping alias matching")
            links = []  # entity_link table may not exist — graceful degradation

        if not nodes and not links:
            return rows

        query_lower = query.lower()
        query_words = set(query_lower.split())

        # Build a list of matched entities, each with canonical name + aliases
        # Structure: list[dict] — {"canonical": str, "aliases": list[str]}
        matching_entities: list[dict[str, Any]] = []

        # --- Match against KG node labels & summaries ---
        for node in nodes:
            label = (node.get("label") or "").lower().strip()
            summary = (node.get("summary") or "").lower().strip()

            if not label:
                continue

            # 1) Exact match: query contains the full entity label
            if label in query_lower:
                matching_entities.append({"canonical": label, "aliases": []})
                continue

            # 2) Word-level overlap: a word from the label appears in the query
            label_words = set(label.split())
            if label_words and query_words & label_words:
                matching_entities.append({"canonical": label, "aliases": []})
                continue

            # 3) Query substring appears in entity summary
            if summary and query_lower in summary:
                matching_entities.append({"canonical": label, "aliases": []})
                continue

        # --- Match against entity_link aliases ---

        for link in links:
            entity_name = (link.get("entity_name") or "").lower().strip()
            if not entity_name:
                continue

            # Parse aliases JSON
            raw_aliases = link.get("aliases_json") or "[]"
            try:
                alias_list: list[str] = json.loads(raw_aliases)
            except (ValueError, TypeError):
                logger.debug("get_graph_context: failed to parse aliases_json, treating as empty")
                alias_list = []

            # Build the set of names to check against the query:
            # canonical entity_name + all aliases
            all_names = [entity_name] + [a.lower().strip() for a in alias_list if a]

            matched = False
            for name in all_names:
                if name in query_lower:
                    matched = True
                    break
                name_words = set(name.split())
                if name_words and query_words & name_words:
                    matched = True
                    break

            if matched:
                matching_entities.append(
                    {
                        "canonical": entity_name,
                        "aliases": [a.lower().strip() for a in alias_list if a],
                    }
                )

        if not matching_entities:
            return rows

        canonical_labels = [e["canonical"] for e in matching_entities]
        logger.debug(
            "Entity-aware boost: detected %d entities in query: %s",
            len(canonical_labels),
            canonical_labels[:5],
        )

        # Boost each result that references any of the matched entities
        for row in rows:
            content = (row.get("memory_content") or row.get("content") or "").lower()
            if not content:
                continue

            # Count how many matched entities appear in the content.
            # For each entity: check canonical name first, then any alias.
            hit_count = 0
            for entity in matching_entities:
                canonical = entity["canonical"]
                if canonical and canonical in content:
                    hit_count += 1
                    continue
                for alias in entity["aliases"]:
                    if alias and alias in content:
                        hit_count += 1
                        break

            if hit_count == 0:
                continue

            # Proportional boost: more entity hits → higher boost,
            # capped by boost_factor
            proportion = min(hit_count / max(len(matching_entities), 1), 1.0)
            entity_boost = proportion * boost_factor
            current = row.get("fused_score", 0.0)
            row["fused_score"] = current * (1.0 + entity_boost)
            row["entity_boost"] = entity_boost

        # Re-sort by boosted fused_score
        rows.sort(key=lambda r: r.get("fused_score", 0.0), reverse=True)
        return rows

    def search(
        self,
        workspace_id: str,
        query: str = "",
        memory_type: str = "",
        tier: str = "",
        limit: int = 20,
        semantic: bool = True,
        rerank: bool = False,
        rerank_endpoint: str | None = None,
        rerank_model: str | None = None,
        rerank_api_key: str | None = None,
        cross_encoder: bool = True,
        query_expansion: bool = False,
        polyphonic: bool = False,
        mmr_lambda: float = 0.0,
        fusion_weights: dict[str, float] | None = None,
        entity_types: list[str] | None = None,
        before: float | int | None = None,
        after: float | int | None = None,
    ) -> list[dict[str, Any]]:
        """Search memories.  When *semantic* is True uses hybrid search.

        Args:
            rerank: If True, passes top results through an LLM reranker
                    (QMD-style) for relevance re-scoring.
            rerank_endpoint: OpenAI-compatible base URL for reranker
                    (default: ``LLM_RERANK_ENDPOINT`` env var).
            rerank_model: Model name for reranker
                    (default: ``LLM_RERANK_MODEL`` env var).
            rerank_api_key: API key for reranker
                    (default: ``LLM_RERANK_API_KEY`` or ``OPENAI_API_KEY`` env var).
            cross_encoder: If True (default), passes top results through a local ONNX
                    cross-encoder (ms-marco-MiniLM-L-6-v2) for discriminative
                    relevance scoring. Falls back gracefully if model files are
                    not available.
            query_expansion: If True, expands the query with synonyms and
                    related terms via LLM before searching.
            polyphonic: If True, uses Reciprocal Rank Fusion (RRF) with
                    diversity penalty instead of min-max normalization.
            mmr_lambda: If > 0, applies Maximal Marginal Relevance reranking.
                    0.7 is a good default (70% relevance, 30% diversity).
            fusion_weights: Optional dict of strategy weights for min-max fusion.
                    Keys: ``"semantic"``, ``"keyword"``, ``"binary"``, ``"graph"``, ``"temporal"``.
                    Values should sum to ~1.0. Omit or pass None to use defaults.
            entity_types: Optional list of entity_type values to filter results by.
                    e.g. ``["memory", "note"]`` to return only memories and notes,
                    or ``["node"]`` for KG nodes only. Applied after fusion and
                    enrichment, in both hybrid and keyword-fallback paths.
            before: Optional Unix timestamp — only return results with
                    ``created_at < before``.
            after: Optional Unix timestamp — only return results with
                    ``created_at > after``.
        """
        if semantic:
            # ── Query cache check ──
            cache_key: str | None = None
            if self._query_cache is not None:
                cache_key = self._query_cache.make_key(workspace_id, query, limit, "semantic")
                cached = self._query_cache.get(cache_key)
                if cached is not None:
                    return cached

            # ── Query expansion (pre-search) ──
            search_query = query
            if query_expansion and query:
                search_query = expand_query(query)
                # If expansion returned gibberish, fall back
                if not search_query or len(search_query.strip()) < 3:
                    search_query = query

            # BGE models need query instruction prefix for asymmetric search.
            query_text = f"Represent this sentence for searching relevant passages: {search_query}"
            emb = self._embed(query_text)
            emb_json = json.dumps(emb) if emb else "[]"

            # Check embedder health — if down, exclude semantic strategy and warn
            embedder_down = not emb
            if not embedder_down and emb:
                # Double-check: try a health ping. Use the OpenAI base URL
                # when embedding through the proxy, fall back to embedder_url.
                health_url = self.embedder_url
                import os as _os

                base = _os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
                if base and _os.environ.get("OPENAI_API_KEY"):
                    # Proxy health check: strip /v1 to get the root
                    health_url = base.replace("/v1", "") if "/v1" in base else base
                try:
                    health = self._http.get(
                        f"{health_url}/health",
                        timeout=2.0,
                    )
                    embedder_down = health.status_code >= 400
                except (httpx.ConnectError, httpx.TimeoutException):
                    embedder_down = True

            # ── Client-side semantic search ──
            # Moved from WASM reducer to Python for ~10x speedup:
            # WASM does O(n) JSON-parsed embedding comparison per row (~85ms each)
            # Python does it in pure-Python loops (~5ms per 60 rows with numpy-lite)
            # The reducer semantic strategy still works as fallback if embedder is down,
            # but by default we do it client-side for speed.
            do_client_side_semantic = not embedder_down and emb_json != "[]"
            strategies_list = ["keyword", "graph", "temporal"]
            if not do_client_side_semantic and not embedder_down:
                # Fallback: let the reducer handle semantic search
                strategies_list.insert(0, "semantic")
            elif embedder_down:
                logger.warning(
                    "Embedder sidecar unreachable — semantic search disabled. "
                    "Using keyword+graph+temporal only."
                )
            strategies = json.dumps(strategies_list)

            # ── Over-fetch (Mem0 pattern): fetch a large candidate pool ──
            # The cross-encoder needs plenty of candidates.  Min-max fusion
            # breaks on huge sets (all low scores collapse to same range),
            # so we fuse on a managed subset and let the cross-encoder handle
            # the rest.
            fetch_limit = max(limit * 4, 60)
            fusion_limit = max(limit * 3, 20)

            with _tracing_span(
                "search.hybrid",
                workspace_id=workspace_id,
                query_length=len(search_query),
                fetch_limit=fetch_limit,
            ):
                self._call(
                    "hybrid_search",
                    [
                        workspace_id,
                        search_query,
                        emb_json,
                        memory_type,
                        tier,
                        fetch_limit,
                        strategies,
                    ],
                )
            qhash = _query_hash(search_query)
            rows = self._sql(
                "SELECT * FROM hybrid_result "
                f"WHERE workspace_id = '{_esc(workspace_id)}' "
                f"  AND query_hash = '{_esc(qhash)}' "
            )

            # ── Weighted min-max fusion ──
            # Normalize each strategy to [0,1] via min-max, then weighted sum.
            # Semantic (0.65): strongest signal — bge-m3 (1024d)
            # Keyword (0.25): Tantivy's real Okapi BM25 with stemming + IDF.
            # Binary (0.05): MIB binary vector Hamming similarity — fast, orthogonal signal.
            # Graph (0.00), temporal (0.05): removed — graph is substring-matching
            #   and temporal is recency-only. Neither contributes meaningfully.
            #   All signal from semantic (0.65) + Tantivy keyword (0.25).
            STRATEGY_WEIGHTS = fusion_weights or {
                "semantic": 0.65,
                "keyword": 0.25,
                "binary": 0.05,
                "graph": 0.00,
                "temporal": 0.05,
            }

            # ── Fetch Tantivy keyword results ──
            tantivy_hits = self._tantivy_search(workspace_id, search_query, limit=fetch_limit)
            # Convert Tantivy hits to the same shape as STDB hybrid_result rows
            tantivy_rows: list[dict[str, Any]] = []
            for th in tantivy_hits:
                tantivy_rows.append(
                    {
                        "entity_id": th.get("entity_id", ""),
                        "entity_type": th.get("entity_type", "memory"),
                        "content": th.get("content", ""),
                        "score": float(th.get("score", 0.0)),
                        "strategy": "keyword",
                        "workspace_id": workspace_id,
                    }
                )

            # Compute min/max per strategy — but only on a capped subset.
            # Over-fetching dumps hundreds of low-score keyword matches
            # (0.125 per single-word hit) that collapse the min-max range.
            per_strat: dict[str, list[dict]] = {
                "keyword": [],  # Tantivy rows go here
                "semantic": [],
                "graph": [],
                "temporal": [],
                "binary": [],
            }

            # Sort Tantivy rows by score desc, take top fusion_limit
            tantivy_rows.sort(key=lambda r: r["score"], reverse=True)
            per_strat["keyword"] = tantivy_rows[:fusion_limit]

            # ── Binary vector similarity (MIB Hamming distance) ──
            # Compute once against the query embedding, reuse for all candidates
            query_emb = self._embed(search_query)
            if query_emb and self._binary_cache:
                from .binary_vectors import binarize, hamming_similarity

                try:
                    query_binary = binarize(query_emb)
                    binary_rows: list[dict[str, Any]] = []
                    for eid, cached_binary in self._binary_cache.items():
                        sim = hamming_similarity(query_binary, cached_binary)
                        if sim > 0.5:  # Only include meaningful matches
                            binary_rows.append(
                                {
                                    "entity_id": eid,
                                    "entity_type": "memory",
                                    "score": sim,
                                    "strategy": "binary",
                                    "workspace_id": workspace_id,
                                }
                            )
                    binary_rows.sort(key=lambda r: r["score"], reverse=True)
                    per_strat["binary"] = binary_rows[:fusion_limit]
                except (ValueError, Exception):
                    logger.warning("search: binary scoring failed, skipping binary results")

            # ── Client-side semantic search ──
            # Compute cosine similarity in Python instead of in the WASM reducer.
            # This avoids O(n) JSON-parsed embedding + memory lookup per row in STDB.
            if do_client_side_semantic:
                import math
                try:
                    query_vec = json.loads(emb_json)
                    qnorm = math.sqrt(sum(x * x for x in query_vec))
                    semantic_rows: list[dict[str, Any]] = []
                    # Fetch all search_index rows for this workspace
                    si_rows = self._sql(
                        "SELECT * FROM search_index "
                        f"WHERE workspace_id = '{_esc(workspace_id)}'"
                    )
                    # Pre-fetch memory trust_scores in one batch
                    mem_ids = set(
                        r["entity_id"] for r in si_rows
                        if r.get("entity_type") == "memory"
                    )
                    trust_scores: dict[str, float] = {}
                    if mem_ids:
                        for mid in mem_ids:
                            mem_rows = self._sql(
                                "SELECT trust_score FROM memory "
                                f"WHERE id = '{_esc(mid)}'"
                            )
                            if mem_rows:
                                trust_scores[mid] = float(mem_rows[0].get("trust_score", 0.5))
                    for si in si_rows:
                        si_emb_str = si.get("embedding_json", "")
                        if not si_emb_str or si_emb_str in ("[]", "null", ""):
                            continue
                        si_vec = json.loads(si_emb_str)
                        if len(si_vec) != len(query_vec):
                            continue
                        si_norm = math.sqrt(sum(x * x for x in si_vec))
                        if qnorm == 0.0 or si_norm == 0.0:
                            continue
                        dot = sum(a * b for a, b in zip(query_vec, si_vec))
                        score = max(0.0, min(1.0, dot / (qnorm * si_norm)))
                        if score < 0.1:
                            continue
                        # Weight by trust_score (0.5x–1.0x multiplier)
                        trust = trust_scores.get(si.get("entity_id", ""), 0.5)
                        weighted = score * (0.5 + trust * 0.5)
                        semantic_rows.append({
                            "entity_id": si.get("entity_id", ""),
                            "entity_type": si.get("entity_type", "memory"),
                            "content": si.get("content", ""),
                            "score": weighted,
                            "strategy": "semantic",
                            "workspace_id": workspace_id,
                        })
                    semantic_rows.sort(key=lambda r: r["score"], reverse=True)
                    per_strat["semantic"] = semantic_rows[:fusion_limit]
                except (ValueError, json.JSONDecodeError, Exception) as sem_err:
                    logger.warning(
                        "search: client-side semantic search failed (%s), "
                        "falling back to reducer semantic strategy",
                        sem_err,
                    )
                    # Fallback: re-run with semantic in strategies
                    strategies_list = ["semantic", "keyword", "graph", "temporal"]
                    strategies = json.dumps(strategies_list)
                    self._call(
                        "hybrid_search",
                        [
                            workspace_id,
                            search_query,
                            emb_json,
                            memory_type,
                            tier,
                            fetch_limit,
                            strategies,
                        ],
                    )
                    # Re-fetch rows after fallback re-run
                    rows = self._sql(
                        "SELECT * FROM hybrid_result "
                        f"WHERE workspace_id = '{_esc(workspace_id)}' "
                        f"  AND query_hash = '{_esc(qhash)}' "
                    )

            # Add STDB rows for semantic, graph, temporal (plus legacy keyword
            # as fallback — any row not in Tantivy still participates)
            for r in rows:
                s = r.get("strategy", "")
                if s in per_strat and len(per_strat[s]) < fusion_limit:
                    per_strat[s].append(r)

            strat_min: dict[str, float] = {}
            strat_max: dict[str, float] = {}
            for s, s_rows in per_strat.items():
                for r in s_rows:
                    sc = float(r.get("score", 0.0))
                    strat_min[s] = min(strat_min.get(s, float("inf")), sc)
                    strat_max[s] = max(strat_max.get(s, float("-inf")), sc)

            # ── Weighted min-max fusion + dedup ──
            rows = self._fuse_and_deduplicate(
                rows,
                tantivy_rows,
                per_strat,
                strat_min,
                strat_max,
                STRATEGY_WEIGHTS,
            )

            # ── Look up content and apply veracity weighting ──
            rows = self._enrich_content(rows, workspace_id)

            # ── Entity-aware search result boosting (mem0 v3 parity) ──
            rows = self._boost_with_entity_signal(query, rows, workspace_id)

            # ── Entity_types filter (after fusion, before reranking) ──
            if entity_types is not None and entity_types:
                rows = [r for r in rows if r.get("entity_type") in entity_types]

            # ── Date range filter (before/after) ──
            if before is not None or after is not None:
                filtered = []
                for r in rows:
                    ts = r.get("created_at")
                    if ts is None:
                        continue
                    if before is not None and not (ts < before):
                        continue
                    if after is not None and not (ts > after):
                        continue
                    filtered.append(r)
                rows = filtered

            if cross_encoder:
                try:
                    from .cross_encoder import cross_encoder_rerank

                    rows = cross_encoder_rerank(query, rows, top_k=len(rows))
                except (FileNotFoundError, ImportError, ValueError) as ce_err:
                    logger.warning(
                        "Cross-encoder unavailable (%s). "
                        "Install onnxruntime and download model files.",
                        ce_err,
                    )
            if rerank:
                rows = llm_rerank(
                    query,
                    rows,
                    endpoint=rerank_endpoint,
                    model=rerank_model,
                    api_key=rerank_api_key,
                    top_k=min(20, len(rows)),
                )
            # ── MMR diversity reranking ──
            if mmr_lambda > 0:
                from .mmr import mmr_rerank

                rows = mmr_rerank(rows, lambda_param=mmr_lambda)
            # ── Weibull temporal boost ──
            from .weibull import apply_temporal_boost

            rows = apply_temporal_boost(rows)
            results = rows[:limit]
            # ── Plugin dispatch: on_search ──
            if self.plugin_manager is not None:
                _, results = self.plugin_manager.dispatch_search(query, results)
            # ── Query cache store ──
            if self._query_cache is not None and cache_key is not None:
                self._query_cache.set(cache_key, results, workspace_id=workspace_id)
            # ── Emit search.performed event ──
            self._emit_event(
                "search.performed",
                {
                    "query": query,
                    "result_count": len(results),
                },
                workspace_id=workspace_id,
            )
            return results

        # Non-semantic (keyword) search via Tantivy BM25 sidecar (~1ms vs ~28ms WASM BM25)
        # Replaces the old _keyword_fallback which did client-side substring matching.
        tantivy_hits = self._tantivy_search(workspace_id, query, limit=limit)
        rows = []
        seen_ids: set[str] = set()
        for th in tantivy_hits:
            eid = th.get("entity_id", "")
            if eid and eid not in seen_ids:
                seen_ids.add(eid)
                rows.append(
                    {
                        "entity_id": eid,
                        "entity_type": th.get("entity_type", "memory"),
                        "content": th.get("content", ""),
                        "score": float(th.get("score", 0.0)),
                        "workspace_id": workspace_id,
                    }
                )
            if len(rows) >= limit:
                break
        if not rows and query:
            # Fallback: client-side substring matching if Tantivy is unreachable
            logger.warning(
                "Tantivy sidecar returned no results for query=%r — falling back to _keyword_fallback",
                query,
            )
            rows = self._keyword_fallback(
                workspace_id, query, memory_type, tier, limit, before=before, after=after
            )
        if entity_types is not None and entity_types:
            rows = [r for r in rows if r.get("entity_type") in entity_types]
        # ── Date range filter (before/after) — only needed in non-semantic path ──
        if before is not None or after is not None:
            filtered = []
            for r in rows:
                ts = r.get("created_at")
                if ts is None:
                    continue
                if before is not None and not (ts < before):
                    continue
                if after is not None and not (ts > after):
                    continue
                filtered.append(r)
            rows = filtered
        return rows

    def detect_patterns(
        self,
        workspace_id: str,
        *,
        limit: int = 200,
        include_clusters: bool = True,
        include_terms: bool = True,
        include_co_occur: bool = True,
    ) -> dict[str, Any]:
        """Run pattern detection on a workspace's memories.

        Args:
            workspace_id: The workspace to analyze.
            limit: Max memories to fetch for analysis.
            include_clusters: Run temporal clustering.
            include_terms: Run frequent term extraction.
            include_co_occur: Run co-occurrence detection.

        Returns:
            Dict with ``temporal_clusters``, ``frequent_terms``,
            ``co_occurrences``, ``total_memories``, ``summary``.
        """
        from .pattern_detection import detect_patterns as _detect

        mems = self._query(
            "memory",
            workspace_id=workspace_id,
            filter_dict={},
        )
        mems = mems[:limit]
        return _detect(
            mems,
            include_clusters=include_clusters,
            include_terms=include_terms,
            include_co_occur=include_co_occur,
        )

    def search_sessions_semantic(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Semantically search across all sessions/workspaces.

        Embes the query, calls the ``search_sessions_semantic`` reducer,
        and reads results from the ``session_search_result`` table.

        Falls back to an empty list when no embedder is available.
        """
        emb = self._embed(query)
        if not emb:
            return []

        emb_json = json.dumps(emb)
        self._call("search_sessions_semantic", [emb_json, limit])

        qhash = f"sessions:{limit}"
        rows = self._sql(f"SELECT * FROM session_search_result WHERE query_hash = '{_esc(qhash)}'")
        rows.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        return rows[:limit]

    def get_memory(self, memory_id: str) -> list[dict[str, Any]]:
        """Get a single memory by ID.  Auto-reinforces on read."""
        results = self._query("memory", filter_dict={"id": memory_id})
        if results:
            try:
                self._call("reinforce_memory", [memory_id])
            except RuntimeError:
                logger.warning("reinforce_memory: _call failed for memory %s", memory_id)
        return results

    def fuzzy_get(
        self,
        workspace_id: str,
        name: str,
        *,
        field: str = "content",
        threshold: float = 0.5,
        limit: int = 50,
    ) -> dict[str, Any] | None:
        """Find the closest-matching memory by string similarity (QMD parity).

        Fetches up to *limit* memories from the workspace and uses
        ``difflib.SequenceMatcher`` to find the one whose *field* value is
        most similar to *name*.

        Returns the best match if similarity >= *threshold*, otherwise
        ``None``.

        Args:
            workspace_id: The workspace to search.
            name: The target name to fuzzy-match against.
            field: Which memory field to compare (default ``\"content\"``).
            threshold: Minimum similarity ratio (0.0–1.0, default 0.5).
            limit: Max memories to scan (default 50).
        """
        from difflib import SequenceMatcher

        rows = self._query(
            "memory",
            workspace_id=workspace_id,
            filter_dict={},
        )
        if not rows:
            return None

        best = None
        best_ratio = 0.0
        for r in rows[:limit]:
            text = r.get(field, "")
            if not text:
                continue
            ratio = SequenceMatcher(
                None, name.lower(), text.lower()
            ).ratio()  # isjunk=None: treat all chars equally
            if ratio > best_ratio:
                best_ratio = ratio
                best = r

        if best and best_ratio >= threshold:
            return best
        return None

    def glob_get(
        self,
        workspace_id: str,
        pattern: str,
        *,
        field: str = "id",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return all memories matching a glob pattern (QMD parity).

        Uses ``fnmatch``-style wildcards (``*``, ``?``, ``[...]``) against
        the specified *field*.  Example::

            c.glob_get(\"ws-1\", \"auth-*\")      # IDs starting with \"auth-\"
            c.glob_get(\"ws-1\", \"auth-*\", field=\"content\")  # content match

        Args:
            workspace_id: The workspace to search.
            pattern: Glob pattern (e.g. ``\"journals/2025-05*\"``,
                     ``\"*auth*\"``).
            field: Which memory field to match against (default ``\"id\"``).
            limit: Max memories to scan (default 200).

        Returns:
            List of matching memory dicts (empty list if none match).
        """
        from fnmatch import fnmatch

        rows = self._query(
            "memory",
            workspace_id=workspace_id,
            filter_dict={},
        )
        matches = []
        for r in rows[:limit]:
            val = r.get(field, "")
            if isinstance(val, str) and fnmatch(val.lower(), pattern.lower()):
                matches.append(r)
        return matches

    def update_memory(
        self,
        memory_id: str,
        content: str,
        summary: str = "",
        confidence: float = 0.8,
        expires_at: int | None = None,
    ) -> dict[str, Any]:
        """Update a memory's content/summary/confidence.

        Parameters
        ----------
        memory_id:
            Target memory ID.
        content:
            New body text.
        summary:
            New short summary (default ``""`` = no summary).
        confidence:
            New confidence score 0.0–1.0 (default ``0.8``).
        expires_at:
            Expiration timestamp in microseconds (epoch).
            Special values:
            - ``None`` (default): preserve the current expiration.
            - ``0``: clear expiration (memory never expires).
            - ``>0``: set to the given absolute timestamp.

        Note
        ----
        This method sends 5 arguments when ``expires_at`` is explicitly set,
        or 4 arguments when ``expires_at`` is ``None`` (default).  The 4-arg
        form is backward-compatible with pre-``expires_at`` WASM binaries.
        The 5-arg form requires the ``expires_at`` reducer (rebuilt WASM).
        """  # noqa: E501
        if expires_at is None:
            # Backward-compatible: 4-arg call may fail on newer WASM that expects 5.
            # Try 5-arg with 0 (no expiration change = preserve current).
            return self._call(
                "update_memory",
                [memory_id, content, summary, confidence, 0],
            )
        # Forward-looking 5-arg call (requires rebuilt WASM with expires_at support)
        return self._call(
            "update_memory",
            [memory_id, content, summary, confidence, expires_at],
        )

    def delete_memory(self, memory_id: str) -> dict[str, Any]:
        """Deactivate a memory. Idempotent — succeeds if already deleted."""
        # ── Look up workspace_id for cache invalidation ──
        ws_id: str | None = None
        if self._query_cache is not None:
            rows = self._sql(f"SELECT workspace_id FROM memory WHERE id = '{_esc(memory_id)}'")
            if rows:
                ws_id = str(rows[0].get("workspace_id", ""))

        try:
            result = self._call("deactivate_memory", [memory_id])
            # ── Invalidate query cache ──
            if self._query_cache is not None and ws_id:
                self._query_cache.invalidate(workspace_id=ws_id)
            # ── Emit memory.deleted event ──
            self._emit_event(
                "memory.deleted",
                {
                    "memory_id": memory_id,
                },
                workspace_id=ws_id or "",
            )
            return result
        except RuntimeError as e:
            if "not found" in str(e).lower():
                return {"status": "ok", "note": "already deleted"}
            raise

    def batch_delete_memories(self, memory_ids: list[str]) -> dict[str, Any]:
        """Batch-deactivate multiple memories in a single reducer call.

        Much faster than N sequential ``delete_memory()`` calls because it
        sends all IDs in one network round-trip to the
        ``batch_delete_memories`` reducer.

        Parameters
        ----------
        memory_ids:
            List of memory ID strings to deactivate. Missing IDs are
            silently skipped (idempotent).

        Returns
        -------
        Dict with ``status``: ``"ok"`` on success.
        """
        if not memory_ids:
            return {"status": "ok", "note": "no IDs provided"}
        return self._call("batch_delete_memories", [json.dumps(memory_ids)])

    def update_memory_tier(self, memory_id: str, tier: str) -> dict[str, Any]:
        """Change a memory's compression tier.

        Parameters
        ----------
        memory_id:
            Target memory ID.
        tier:
            New tier. Must be one of ``"L0"``, ``"L1"``, or ``"L2"``.
            L0 = highest importance / shortest retention window,
            L2 = lowest importance / longest retention window.
        """
        if tier not in ("L0", "L1", "L2"):
            raise ValueError(f"Invalid tier '{tier}'. Must be L0, L1, or L2.")
        return self._call("update_memory_tier", [memory_id, tier])

    def set_memory_scope(self, memory_id: str, user_scope: str) -> dict[str, Any]:
        """Scope an existing memory to a specific user identity for isolation.

        Parameters
        ----------
        memory_id:
            The UUID of the memory to scope.
        user_scope:
            The user identity hash to scope the memory to. Pass empty string
            to make the memory shared/unscoped.
        """
        return self._call("set_memory_scope", [memory_id, user_scope])

    def set_workspace_context(self, workspace_id: str, context: str) -> dict[str, Any]:
        """Attach a context string to a workspace for QMD-style context trees."""
        return self._call("set_workspace_context", [workspace_id, context])

    def set_memory_context(self, memory_id: str, context: str) -> dict[str, Any]:
        """Attach a context string to a memory for QMD-style context trees."""
        return self._call("set_memory_context", [memory_id, context])

    def get_context_chain(self, memory_id: str) -> dict[str, Any]:
        """Return the context chain for a memory: workspace context + memory context."""
        mems = self._query(
            "memory", filter_dict={"id": memory_id}, columns=["id", "workspace_id", "context"]
        )
        if not mems:
            return {"workspace_context": "", "memory_context": ""}
        ws_id = mems[0].get("workspace_id", "")
        mem_ctx = mems[0].get("context", "")

        ws_ctx = ""
        if ws_id:
            wss = self._query("workspace", filter_dict={"id": ws_id}, columns=["context"])
            if wss:
                ws_ctx = wss[0].get("context", "")

        return {
            "workspace_context": ws_ctx,
            "memory_context": mem_ctx,
        }

    def reinforce(self, memory_id: str) -> dict[str, Any]:
        """Reinforce a memory (bump access_count + strength)."""
        return self._call("reinforce_memory", [memory_id])

    def rate_memory(self, memory_id: str, rating: str, peer_id: str) -> dict[str, Any]:
        """Rate a memory to adjust its trust score.

        Args:
            memory_id: The memory to rate.
            rating: "helpful" (score 5), "unhelpful" (score 1),
                    or an integer string "1"–"5" for graded feedback.
            peer_id: The peer submitting the rating.
        """
        return self._call("rate_memory", [memory_id, rating, peer_id])

    def escalate_memories(
        self, workspace_id: str, l2_to_l1: int = 5, l1_to_l0: int = 20
    ) -> dict[str, Any]:
        """Batch-escalate memory tiers based on access_count thresholds.

        Args:
            workspace_id: The workspace to escalate memories in.
            l2_to_l1: Access count threshold for L2→L1 escalation (default: 5).
            l1_to_l0: Access count threshold for L1→L0 escalation (default: 20).
        """
        return self._call("escalate_memories", [workspace_id, l2_to_l1, l1_to_l0])

    def list_memories(
        self, workspace_id: str, memory_type: str = "", limit: int = 50
    ) -> list[dict[str, Any]]:
        """List active memories in a workspace."""
        filt = {}
        if memory_type:
            filt["memory_type"] = memory_type
        rows = self._query("memory", workspace_id=workspace_id, filter_dict=filt)
        rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        return rows[:limit]

    def get_user_memories(self, user_scope: str, workspace_id: str) -> list[dict[str, Any]]:
        """Get all memories scoped to a specific user within a workspace.

        Calls the ``get_user_memories`` reducer which populates the
        ``user_memory_result`` table, then reads from it.

        Args:
            user_scope: The user identity hash to filter by.
            workspace_id: The workspace to search in.

        Returns:
            List of memory records scoped to the given user.
        """
        self._call("get_user_memories", [user_scope, workspace_id])
        rows = self._sql(
            "SELECT * FROM user_memory_result WHERE "
            f"user_scope = '{_esc(user_scope)}' AND "
            f"workspace_id = '{_esc(workspace_id)}'"
        )
        return rows

    # -----------------------------------------------------------------------
    # Directory (context directory tree)
    # -----------------------------------------------------------------------

    def list_directory(self, directory_id: str) -> list[dict[str, Any]]:
        """Get children of a directory."""
        self._call("get_children", [directory_id, True])
        return self._sql(
            f"SELECT * FROM directory_result WHERE query_hash = '{_esc(directory_id)}'"
        )

    def traverse_directory(self, workspace_id: str, root_directory_id: str) -> list[dict[str, Any]]:
        """Recursive BFS traversal of directory tree."""
        self._call("traverse_recursive", [workspace_id, root_directory_id])
        return self._sql(
            f"SELECT * FROM directory_result WHERE query_hash = '{_esc(root_directory_id)}'"
        )

    def get_directory(self, workspace_id: str, path_or_id: str) -> list[dict[str, Any]]:
        """Get a directory by ID or path."""
        self._call("get_directory", [workspace_id, path_or_id])
        return self._sql(
            f"SELECT * FROM directory_result WHERE workspace_id = '{_esc(workspace_id)}'"
        )

    def create_directory(
        self, workspace_id: str, name: str, path: str, parent_id: str = "", description: str = ""
    ) -> dict[str, Any]:
        """Create a directory in the context directory tree."""
        return self._call("create_directory", [workspace_id, name, path, parent_id, description])

    def link_memory_to_directory(
        self, directory_id: str, memory_id: str, workspace_id: str
    ) -> dict[str, Any]:
        """Link a memory to a directory."""
        return self._call("link_memory_to_directory", [directory_id, memory_id, workspace_id])

    def unlink_memory_from_directory(self, directory_id: str, memory_id: str) -> dict[str, Any]:
        """Unlink a memory from a directory."""
        return self._call("unlink_memory_from_directory", [directory_id, memory_id])

    def search_directory_contents(
        self, workspace_id: str, directory_path: str
    ) -> list[dict[str, Any]]:
        """Recursively search directory contents.

        Finds a directory by path, recursively collects all subdirectories
        and memory entries within the tree, and returns the result.

        Args:
            workspace_id: Target workspace.
            directory_path: Path of the root directory to search.

        Returns:
            List with a single DirectoryContentResult dict containing:
            id, workspace_id, directory_path, directory_id,
            subdirectory_ids_json (JSON array of sub-directory IDs),
            memory_ids_json (JSON array of contained memory IDs),
            created_at.
        """
        self._call("search_directory_contents", [workspace_id, directory_path])
        return self._sql(
            f"SELECT * FROM directory_content_result "
            f"WHERE workspace_id = '{_esc(workspace_id)}' "
            f"AND directory_path = '{_esc(directory_path)}' "
            f"ORDER BY created_at DESC LIMIT 1"
        )

    # -----------------------------------------------------------------------
    # Batch update & history (Mem0 parity)
    # -----------------------------------------------------------------------

    def batch_update_memories(
        self, workspace_id: str, memory_ids: list[str], updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Batch update multiple memories. Mem0 parity.
        updates can contain: content, summary, confidence, tier, is_active,
        expires_at

        Performs client-side batching: loops over each memory_id and
        calls the existing ``update_memory`` reducer individually.
        """
        updated = 0
        errors: list[str] = []
        for mem_id in memory_ids:
            try:
                # Fetch current memory to preserve unchanged fields
                current_rows = self._query(
                    "memory",
                    filter_dict={"id": mem_id},
                )
                if not current_rows:
                    errors.append(f"Memory '{mem_id}' not found")
                    continue
                current = current_rows[0]
                mem_ws = current.get("workspace_id", "")
                if workspace_id and mem_ws and mem_ws != workspace_id:
                    errors.append(f"Memory '{mem_id}' not in workspace '{workspace_id}'")
                    continue
                content = updates.get("content", current.get("content", ""))
                summary = updates.get("summary", current.get("summary", ""))
                confidence = updates.get("confidence", current.get("confidence", 0.8))
                expires_at = updates.get("expires_at", 0)
                self.update_memory(mem_id, content, summary, confidence, expires_at)
                updated += 1
            except Exception as e:
                errors.append(f"Memory '{mem_id}': {e}")

        if errors:
            return {"status": "partial", "updated": updated, "errors": errors}
        return {"status": "ok", "updated": updated}

    def get_memory_history(self, memory_id: str) -> list[dict[str, Any]]:
        """Get version history for a memory. Mem0 parity.

        Returns revision history from the ``memory_revision`` table,
        ordered by version ascending.  Each entry shows what changed
        in that revision (previous vs new content/summary/confidence).

        The current (latest) state is appended as the final entry
        with no ``previous_*`` fields.
        """
        # Fetch revision history from the memory_revision table
        revisions = self._query(
            "memory_revision",
            filter_dict={"memory_id": memory_id},
        )
        # Sort by version ascending
        revisions.sort(key=lambda r: r.get("version", 0))

        result: list[dict[str, Any]] = []
        for rev in revisions:
            result.append(
                {
                    "version": rev.get("version", 0),
                    "previous_content": rev.get("previous_content", ""),
                    "previous_summary": rev.get("previous_summary", ""),
                    "previous_confidence": rev.get("previous_confidence", 1.0),
                    "content": rev.get("new_content", ""),
                    "summary": rev.get("new_summary", ""),
                    "confidence": rev.get("new_confidence", 1.0),
                    "changed_at": rev.get("changed_at", 0),
                    "changed_by": rev.get("changed_by", ""),
                }
            )

        # Append the current state as the latest version
        rows = self._query(
            "memory",
            filter_dict={"id": memory_id},
            columns=["content", "summary", "version", "updated_at", "confidence"],
        )
        if rows:
            r = rows[0]
            current_version = r.get("version", 1)
            # Only append if we don't already have this version
            if not result or result[-1].get("version") != current_version:
                result.append(
                    {
                        "version": current_version,
                        "previous_content": "",
                        "previous_summary": "",
                        "previous_confidence": 0.0,
                        "content": r.get("content", ""),
                        "summary": r.get("summary", ""),
                        "confidence": r.get("confidence", 1.0),
                        "changed_at": r.get("updated_at", 0),
                        "changed_by": "",
                    }
                )

        return result

    def get_note_history(self, note_id: str) -> list[dict[str, Any]]:
        """Get version history for a note.

        Returns revision history from the ``note_revision`` table,
        ordered by version ascending.  Each entry shows what changed
        in that revision (previous vs new title/content).

        The current (latest) state is appended as the final entry
        with no ``previous_*`` fields.
        """
        # Fetch revision history from the note_revision table
        revisions = self._query(
            "note_revision",
            filter_dict={"note_id": note_id},
        )
        # Sort by version ascending
        revisions.sort(key=lambda r: r.get("version", 0))

        result: list[dict[str, Any]] = []
        for rev in revisions:
            result.append(
                {
                    "version": rev.get("version", 0),
                    "previous_title": rev.get("previous_title", ""),
                    "previous_content": rev.get("previous_content", ""),
                    "title": rev.get("new_title", ""),
                    "content": rev.get("new_content", ""),
                    "changed_at": rev.get("changed_at", 0),
                    "changed_by": rev.get("changed_by", ""),
                }
            )

        # Append the current state as the latest version
        rows = self._query(
            "note",
            filter_dict={"id": note_id},
            columns=["title", "content", "version", "updated_at"],
        )
        if rows:
            r = rows[0]
            current_version = r.get("version", 1)
            # Only append if we don't already have this version
            if not result or result[-1].get("version") != current_version:
                result.append(
                    {
                        "version": current_version,
                        "previous_title": "",
                        "previous_content": "",
                        "title": r.get("title", ""),
                        "content": r.get("content", ""),
                        "changed_at": r.get("updated_at", 0),
                        "changed_by": "",
                    }
                )

        return result

    # -----------------------------------------------------------------------
    # Reputation decay configuration (Weibull / Linear)
    # -----------------------------------------------------------------------

    def set_decay_model(
        self,
        workspace_id: str,
        model: str = "linear",
        decay_rate: float = 0.005,
        max_days: int = 90,
        weibull_shape: float = 0.6,
        weibull_scale: float = 30.0,
    ) -> dict[str, Any]:
        """Configure the decay model for a workspace.

        Args:
            workspace_id: Workspace to configure.
            model: ``"linear"`` (default) or ``"weibull"``.
            decay_rate: For linear — fraction of trust to decay per day (e.g. 0.005 = 0.5%/day).
            max_days: For linear — max age in days before trust hits floor.
            weibull_shape: For Weibull — k parameter (< 1 = rapid-then-slow forgetting, default 0.6).
            weibull_scale: For Weibull — λ parameter (characteristic time in days, default 30.0).

        Returns:
            The reducer response.
        """
        if model not in ("linear", "weibull"):
            raise ValueError(f"Unknown decay model '{model}'. Use 'linear' or 'weibull'.")

        if model == "linear":
            return self._call(
                "apply_reputation_decay",
                [
                    workspace_id,
                    decay_rate,
                    max_days,
                ],
            )
        else:
            return self._call(
                "apply_weibull_decay",
                [
                    workspace_id,
                    weibull_shape,
                    weibull_scale,
                ],
            )

    def get_decay_config(self, workspace_id: str) -> dict[str, Any] | None:
        """Get the current decay configuration for a workspace.

        Returns None if no config has been set yet.
        """
        rows = self._query("workspace_config", filter_dict={"id": workspace_id})
        if rows:
            return rows[0]
        return None

    def recommend_memories(
        self,
        workspace_id: str,
        limit: int = 20,
        min_urgency: float = 0.3,
    ) -> list[dict[str, Any]]:
        """Recommend memories that need attention (review, reinforce, discard).

        Returns memories sorted by urgency — low-trust, decaying, or
        consistently-poor memories that need human attention.

        Args:
            workspace_id: Target workspace.
            limit: Max recommendations (default 20).
            min_urgency: Minimum urgency threshold 0.0–1.0 (default 0.3).
        """
        self._call(
            "recommend_memories",
            [
                workspace_id,
                limit,
                min_urgency,
            ],
        )
        # Public result table — queryable via SQL directly
        return self._sql(
            f"SELECT * FROM memory_recommendation WHERE workspace_id = '{_esc(workspace_id)}'"
        )

    def get_peer_reputation(self, peer_id: str) -> dict[str, Any] | None:
        """Get reputation stats for a peer.

        Returns None if the peer has no feedback history.
        """
        rows = self._query("peer_reputation", filter_dict={"id": peer_id})
        if rows:
            return rows[0]
        return None

    # -----------------------------------------------------------------------
    # Document management (Supermemory parity)
    # -----------------------------------------------------------------------

    def create_document(
        self,
        workspace_id: str,
        title: str,
        content: str = "",
        content_type: str = "text",
        file_path: str = "",
        source_url: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a document with auto-chunking.

        Documents with content ≥ 100 chars are automatically split into
        overlapping ~500-char chunks (sentence-boundary-aware).

        Args:
            workspace_id: Target workspace.
            title: Document title.
            content: Document body text. Auto-chunked if ≥ 100 chars.
            content_type: ``"text"``, ``"pdf"``, ``"image"``, ``"video"``, ``"code"``, or ``"url"``.
            file_path: Optional file path reference.
            source_url: Optional source URL.
            metadata: Optional metadata dict (serialized to JSON).
        """
        meta_json = json.dumps(metadata or {})
        return self._call(
            "create_document",
            [
                workspace_id,
                title,
                content,
                content_type,
                file_path,
                source_url,
                meta_json,
            ],
        )

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """Get a document by ID."""
        rows = self._query("document", filter_dict={"id": doc_id})
        if rows:
            return rows[0]
        return None

    def list_documents(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all documents in a workspace."""
        return self._query("document", filter_dict={"workspace_id": workspace_id})

    def get_document_chunks(self, doc_id: str) -> list[dict[str, Any]]:
        """Get all chunks for a document, ordered by chunk_index."""
        rows = self._query("doc_chunk", filter_dict={"document_id": doc_id})
        rows.sort(key=lambda r: r.get("chunk_index", 0))
        return rows

    def delete_document(self, doc_id: str) -> dict[str, Any]:
        """Delete a document and all its chunks (cascading)."""
        return self._call("delete_document", [doc_id])

    # -----------------------------------------------------------------------
    # Knowledge graph pattern detection
    # -----------------------------------------------------------------------

    def detect_bridge_nodes(
        self,
        workspace_id: str,
        limit: int = 20,
        min_communities: int = 2,
    ) -> list[dict[str, Any]]:
        """Detect bridge nodes — concepts that connect multiple communities.

        Returns nodes sorted by bridge score (higher = more integrative).
        """
        self._call(
            "detect_bridge_nodes",
            [
                workspace_id,
                limit,
                min_communities,
            ],
        )
        # Public result table — queryable via SQL directly
        return self._sql(f"SELECT * FROM bridge_result WHERE workspace_id = '{_esc(workspace_id)}'")

    def compute_kg_stats(self, workspace_id: str) -> dict[str, Any] | None:
        """Compute knowledge graph statistics for a workspace.

        Returns a single stats row with node_count, edge_count,
        community_count, orphan_nodes, avg_degree, etc.
        """
        self._call("compute_kg_stats", [workspace_id])
        # Public result table — queryable via SQL directly
        rows = self._sql(
            f"SELECT * FROM kg_stats_result WHERE workspace_id = '{_esc(workspace_id)}'"
        )
        if rows:
            return rows[0]
        return None

    def get_memory_stats(self, workspace_id: str) -> dict[str, Any] | None:
        """Collect per-workspace memory metrics.

        Stats returned:
        - ``total_memories`` — count of all memories
        - ``active_memories`` — count of active memories
        - ``by_tier`` — JSON map of tier → count (L0, L1, L2)
        - ``by_type`` — JSON map of memory_type → count
        - ``avg_confidence`` — average confidence score
        - ``avg_age_seconds`` — average age in seconds
        - ``total_revisions`` — number of memory revisions
        - ``top_tags`` — JSON array of top-10 used tags
        - ``total_users`` — count of distinct user_scope values

        Returns a dict of stat_key → stat_value, or ``None`` if no stats
        were computed.
        """
        self._call("get_memory_stats", [workspace_id])
        # Public result table — queryable via SQL directly
        rows = self._sql(
            f"SELECT * FROM workspace_memory_stats_result WHERE workspace_id = '{_esc(workspace_id)}'"
        )
        if rows:
            return {r["stat_key"]: r["stat_value"] for r in rows}
        return None

    # -----------------------------------------------------------------------
    # Search with metadata/location filters (Honcho parity)
    # -----------------------------------------------------------------------

    def search_with_filters(
        self,
        workspace_id: str,
        query: str = "",
        memory_type: str = "",
        tier: str = "",
        metadata_filter: str = "",
        location_filter: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search with metadata and location filters. Honcho parity."""
        # For metadata/location filters, we do a keyword search first then filter in Python
        rows = self.search(workspace_id, query, memory_type, tier, limit, semantic=True)
        if metadata_filter:

            mf = (
                json.loads(metadata_filter) if isinstance(metadata_filter, str) else metadata_filter
            )
            filtered = []
            for r in rows:
                meta_str = r.get("metadata_json", "{}")
                try:
                    meta = json.loads(meta_str) if isinstance(meta_str, str) else meta_str
                except Exception:
                    logger.debug("filter: failed to parse metadata_json, treating as empty")
                    meta = {}
                matches = all(meta.get(k) == v for k, v in mf.items())
                if matches:
                    filtered.append(r)
            rows = filtered[:limit]
        if location_filter:
            loc = location_filter.lower()
            rows = [
                r
                for r in rows
                if loc in r.get("content", "").lower() or loc in r.get("summary", "").lower()
            ][:limit]
        return rows

    # -----------------------------------------------------------------------
    # Knowledge Graph
    # -----------------------------------------------------------------------

    def create_node(
        self,
        workspace_id: str,
        label: str,
        node_type: str = "concept",
        summary: str = "",
        metadata_json: str = "{}",
        source_memory_id: str = "",
    ) -> dict[str, Any]:
        """Create a knowledge-graph node and auto-index it.

        Args:
            workspace_id: Target workspace.
            label: Node label (used as display name).
            node_type: Type category (default: "concept").
            summary: Optional summary text.
            metadata_json: Optional JSON metadata string.
            source_memory_id: Optional memory record ID that supports this node.
        """
        result = self._call(
            "create_node",
            [
                workspace_id,
                label,
                node_type,
                summary,
                metadata_json,
                source_memory_id,
            ],
        )
        content = f"{label}: {summary}" if summary else label
        emb = self._embed(content)
        if emb:
            nodes = self._query(
                "kg_node", workspace_id=workspace_id, filter_dict={"label": label}, columns=["id"]
            )
            if nodes:
                self._call(
                    "index_entity",
                    [
                        workspace_id,
                        "node",
                        nodes[-1]["id"],
                        content,
                        json.dumps(emb),
                    ],
                )
        return result

    def update_node(
        self,
        node_id: str,
        label: str,
        node_type: str = "concept",
        summary: str = "",
        metadata_json: str = "{}",
        source_memory_id: str = "",
    ) -> dict[str, Any]:
        """Update an existing knowledge-graph node's mutable fields.

        Args:
            node_id: The ID of the node to update.
            label: New label (display name).
            node_type: Type category (default: ``"concept"``).
            summary: Updated summary text.
            metadata_json: Updated JSON metadata string.
            source_memory_id: Optional source memory ID.
        """
        return self._call(
            "update_node",
            [
                node_id,
                label,
                node_type,
                summary,
                metadata_json,
                source_memory_id,
            ],
        )

    def delete_node(
        self,
        node_id: str,
    ) -> dict[str, Any]:
        """Soft-delete a knowledge-graph node by ID.

        Removes the node from the KG (sets ``is_active = false``).
        The node's edges remain but become orphaned.

        Args:
            node_id: The ID of the node to delete.
        """
        return self._call("delete_node", [node_id])

    def create_edge(
        self,
        workspace_id: str,
        source_node_id: str,
        target_node_id: str,
        relation: str,
        weight: float = 1.0,
        confidence: str = "EXTRACTED",
        metadata_json: str = "{}",
        source_memory_id: str = "",
    ) -> dict[str, Any]:
        """Create a directed, typed edge between two KG nodes.

        Args:
            workspace_id: Target workspace.
            source_node_id: Source node ID.
            target_node_id: Target node ID.
            relation: Relationship type label.
            weight: Edge weight (default: 1.0).
            confidence: Confidence level (default: "EXTRACTED").
            metadata_json: Optional JSON metadata string.
            source_memory_id: Optional memory record ID that supports this edge.
        """
        return self._call(
            "create_edge",
            [
                workspace_id,
                source_node_id,
                target_node_id,
                relation,
                weight,
                confidence,
                metadata_json,
                source_memory_id,
            ],
        )

    def update_edge(
        self,
        edge_id: str,
        relation: str,
        weight: float = 1.0,
        metadata_json: str = "{}",
    ) -> dict[str, Any]:
        """Update an existing knowledge-graph edge's mutable fields.

        Args:
            edge_id: The ID of the edge to update.
            relation: New relationship type label.
            weight: New edge weight (default: 1.0).
            metadata_json: Updated JSON metadata string.
        """
        return self._call(
            "update_edge",
            [
                edge_id,
                relation,
                weight,
                metadata_json,
            ],
        )

    def delete_edge(
        self,
        edge_id: str,
    ) -> dict[str, Any]:
        """Soft-delete a knowledge-graph edge by ID.

        Removes the edge from the KG (sets ``is_active = false``).

        Args:
            edge_id: The ID of the edge to delete.
        """
        return self._call("delete_edge", [edge_id])

    def add_node_citation(
        self,
        workspace_id: str,
        node_id: str,
        memory_id: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Add a citation linking a KG node to a source memory.

        Args:
            workspace_id: Target workspace.
            node_id: The knowledge graph node ID.
            memory_id: The memory record that supports this node.
            description: Optional description of the citation relationship.
        """
        return self._call(
            "add_node_citation",
            [
                workspace_id,
                node_id,
                memory_id,
                description,
            ],
        )

    def add_edge_citation(
        self,
        workspace_id: str,
        edge_id: str,
        memory_id: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Add a citation linking a KG edge to a source memory.

        Args:
            workspace_id: Target workspace.
            edge_id: The knowledge graph edge ID.
            memory_id: The memory record that supports this edge.
            description: Optional description of the citation relationship.
        """
        return self._call(
            "add_edge_citation",
            [
                workspace_id,
                edge_id,
                memory_id,
                description,
            ],
        )

    def get_edge_history(
        self,
        edge_group_id: str,
    ) -> list[dict[str, Any]]:
        """Get all historical versions of a knowledge-graph edge.

        Edges in the KG are versioned — when an edge is updated, a new
        version is created with the same ``edge_group_id``. This method
        returns every version ordered by ``created_at``, letting you
        trace how a relationship evolved over time.

        Args:
            edge_group_id: The group ID of the edge(s) to query. All
                versions sharing this group ID are returned.

        Returns:
            List of edge version records with source_node_id,
            target_node_id, relation, weight, confidence, version, and
            timestamps (created_at, valid_at, invalid_at).
        """
        self._call("get_edge_history", [edge_group_id])
        rows = self._sql(
            "SELECT * FROM edge_history_result WHERE "
            f"edge_group_id = '{_esc(edge_group_id)}' "
            "ORDER BY created_at ASC"
        )
        return rows

    def get_citations(
        self,
        workspace_id: str,
        entity_id: str,
        entity_type: str = "node",
    ) -> list[dict[str, Any]]:
        """Get all citations for a KG entity (node or edge).

        Args:
            workspace_id: Target workspace.
            entity_id: The node or edge ID.
            entity_type: "node" (default) or "edge".

        Returns:
            List of citation records with source_memory_id, description, and timestamp.
        """
        self._call(
            "get_citations",
            [
                workspace_id,
                entity_id,
                entity_type,
            ],
        )
        rows = self._sql(
            "SELECT * FROM citation_result WHERE "
            f"entity_id = '{_esc(entity_id)}' "
            f"  AND entity_type = '{_esc(entity_type)}' "
        )
        return rows

    def query_graph(self, workspace_id: str, query: str = "") -> list[dict[str, Any]]:
        """Search KG nodes by label within a workspace."""
        rows = self._query("kg_node", workspace_id=workspace_id)
        if query:
            # Client-side filter (SpacetimeDB doesn't support LIKE)
            q = query.lower()
            rows = [
                r
                for r in rows
                if q in r.get("label", "").lower() or q in r.get("summary", "").lower()
            ]
        return rows

    def get_neighbors(self, node_id: str, workspace_id: str = "") -> list[dict[str, Any]]:
        """Get edges connected to a node within an optional workspace."""
        # Query both directions since _query doesn't support OR
        edges_src = self._query(
            "kg_edge", workspace_id=workspace_id, filter_dict={"source_node_id": node_id}
        )
        edges_tgt = self._query(
            "kg_edge", workspace_id=workspace_id, filter_dict={"target_node_id": node_id}
        )
        seen = set()
        edges = []
        for e in edges_src + edges_tgt:
            if e["id"] not in seen:
                seen.add(e["id"])
                edges.append(e)
        # Enrich with labels
        node_ids = set()
        for e in edges:
            node_ids.add(e.get("source_node_id", ""))
            node_ids.add(e.get("target_node_id", ""))
        node_ids.discard("")
        label_map = {}
        for nid in node_ids:
            rows = self._query(
                "kg_node",
                workspace_id=workspace_id,
                filter_dict={"id": nid},
                columns=["id", "label"],
            )
            if rows:
                label_map[nid] = rows[0].get("label", "")

        for e in edges:
            e["source_label"] = label_map.get(e.get("source_node_id", ""), "")
            e["target_label"] = label_map.get(e.get("target_node_id", ""), "")
        edges.sort(key=lambda r: r.get("weight", 0.0), reverse=True)
        return edges

    def detect_communities(self, workspace_id: str) -> dict[str, Any]:
        """Run label-propagation community detection."""
        return self._call("detect_communities", [workspace_id])

    def seed_communities(self, workspace_id: str) -> dict[str, Any]:
        """Seed unassigned nodes into new communities."""
        return self._call("seed_communities", [workspace_id])

    # -----------------------------------------------------------------------
    # Maintenance
    # -----------------------------------------------------------------------

    def run_maintenance(self) -> dict[str, Any]:
        """Trigger periodic maintenance (expire, decay, dedup)."""
        return self._call("manual_maintenance", [])

    def expire_memories(self) -> dict[str, Any]:
        """Manually expire all overdue memories.

        Iterates all memories and deactivates any whose ``expires_at``
        timestamp is in the past (greater than 0 and less than current
        time). Requires admin privileges on the database.

        Returns:
            Reducer status.
        """
        return self._call("expire_memories", [])

    def dedup(self, workspace_id: str) -> dict[str, Any]:
        """Run dedup within a workspace."""
        return self._call("dedup_memories", [workspace_id])

    def dedup_memories(self, workspace_id: str) -> dict[str, Any]:
        """Deduplicate near-duplicate memories in a workspace.

        Wraps the ``dedup_memories`` reducer (consolidation.rs:478).
        Near-duplicate detection uses cosine >= 0.85 + edit distance <= 30%.

        Args:
            workspace_id: The workspace to deduplicate.

        Returns:
            Reducer status dict.
        """
        return self.dedup(workspace_id)

    def consolidate_memories(
        self,
        workspace_id: str,
        source_ids: list[str],
        target_content: str,
        target_summary: str,
    ) -> dict[str, Any]:
        """Merge several source memories into a single new consolidated memory.

        Source memories are deactivated and a ``ConsolidationLog`` entry is
        created linking them to the new memory. The caller must be a workspace
        admin.

        Args:
            workspace_id: The workspace containing the source memories.
            source_ids: List of memory IDs to consolidate.
            target_content: Content for the new consolidated memory.
            target_summary: Summary for the new consolidated memory.

        Returns:
            Reducer status.
        """
        return self._call(
            "consolidate_memories",
            [workspace_id, json.dumps(source_ids), target_content, target_summary],
        )

    def temporal_search_with_weight(
        self,
        workspace_id: str,
        query: str = "",
        memory_type: str = "",
        tier: str = "",
        limit: int = 20,
        recency_weight: float = 0.7,
        time_context: str = "",
    ) -> list[dict[str, Any]]:
        """Time-weighted memory retrieval with configurable recency decay.

        Like the ``temporal`` strategy in :meth:`search`, but with:
        - Exponential recency boost controlled by ``recency_weight`` (0.0–1.0).
          Higher values penalize older memories more strongly.
          Default 0.7 provides a good balance (roughly corresponding to a
          7-day half-life with 70% recency influence).
        - ``time_context`` filters memories by age: "recent" (24h),
          "last_week", "last_month", "last_3_months", "last_year", or
          "" (no filter).

        Results are written to the ``HybridResult`` table with strategy
        ``temporal_weighted_<weight_int>``, keyed by a unique query hash
        that includes the recency_weight. Read back via SQL on
        ``hybrid_result`` filtered by workspace_id and query_hash.

        Args:
            workspace_id: The workspace to search.
            query: The search query (for query hash and optional semantic boosting).
            memory_type: Optional ``memory_type`` filter (e.g., "world_fact").
            tier: Optional tier filter ("L0", "L1", "L2").
            limit: Max results to return (default 20).
            recency_weight: How much to penalise old memories (0.0–1.0).
                0.0 = no recency bias, 1.0 = strong exponential decay.
            time_context: Temporal filter keyword as described above.

        Returns:
            List of hybrid_result rows matching the search.
        """
        emb_json = "[]"
        self._call(
            "temporal_search_with_weight",
            [
                workspace_id,
                query,
                emb_json,
                memory_type,
                tier,
                limit,
                recency_weight,
                time_context,
            ],
        )
        qhash = _query_hash(f"tw:{query}:{int(recency_weight * 100)}")
        return self._sql(
            "SELECT * FROM hybrid_result "
            f"WHERE workspace_id = '{_esc(workspace_id)}' "
            f"  AND query_hash = '{_esc(qhash)}' "
        )

    # -----------------------------------------------------------------------
    # Merge suggestions
    # -----------------------------------------------------------------------

    def suggest_merges(self, workspace_id: str, threshold: float = 0.8) -> dict[str, Any]:
        """Scan active memories and record merge suggestions.

        Args:
            workspace_id: The workspace to scan.
            threshold: Minimum cosine similarity threshold (default: 0.8).

        Returns:
            Reducer status.
        """
        return self._call("suggest_merges", [workspace_id, threshold])

    def approve_merge(self, suggestion_id: str) -> dict[str, Any]:
        """Approve a pending merge suggestion.

        Deactivates the source memory into the target (survivor) memory.

        Args:
            suggestion_id: The ID of the MergeSuggestion row.

        Returns:
            Reducer status.
        """
        return self._call("approve_merge", [suggestion_id])

    def reject_merge(self, suggestion_id: str) -> dict[str, Any]:
        """Reject a pending merge suggestion without merging.

        Args:
            suggestion_id: The ID of the MergeSuggestion row.

        Returns:
            Reducer status.
        """
        return self._call("reject_merge", [suggestion_id])

    # -----------------------------------------------------------------------
    # Session
    # -----------------------------------------------------------------------

    def get_peer_sessions(self, peer_id: str) -> list[dict[str, Any]]:
        """List sessions a peer has participated in."""
        # Query session_participant to find session IDs, then fetch each session
        parts = self._query("session_participant", filter_dict={"peer_id": peer_id})
        rows = []
        for sp in parts:
            sessions = self._query("session", filter_dict={"id": sp.get("session_id", "")})
            for s in sessions:
                s["role"] = sp.get("role", "")
                s["joined_at"] = sp.get("joined_at", 0)
                rows.append(s)
        rows.sort(key=lambda r: r.get("joined_at", 0), reverse=True)
        return rows

    def get_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieve messages for a session."""
        rows = self._query("message", filter_dict={"session_id": session_id})
        rows.sort(key=lambda r: r.get("created_at", 0))
        return rows

    def get_session_steps(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieve all reasoning steps for a session.

        Calls the ``get_session_steps`` reducer which writes to the
        ``session_step_result`` table, then queries that table.

        Args:
            session_id: The session to get steps for.

        Returns:
            A list of step dicts ordered by creation time, each with keys:
            query_hash, id, session_id, workspace_id, step_type, content,
            summary, parent_step_id, created_at.
        """
        self._call("get_session_steps", [session_id])
        query_hash = f"steps:{session_id}"
        rows = self._query("session_step_result", filter_dict={"query_hash": query_hash})
        rows.sort(key=lambda r: r.get("created_at", 0))
        return rows

    def add_agent_step(
        self,
        session_id: str,
        workspace_id: str,
        step_type: str,
        content: str,
        summary: str = "",
        parent_step_id: str = "",
    ) -> dict[str, Any]:
        """Record an agent reasoning step (thought, action, tool_call, etc.).

        Calls the ``add_agent_step`` reducer to append a reasoning step to a
        session's chain of thought.

        Args:
            session_id: The session to attach the step to.
            workspace_id: The workspace containing the session.
            step_type: One of ``"thought"``, ``"action"``, ``"observation"``,
                ``"tool_call"``, or ``"tool_result"``.
            content: The step content (text or JSON).
            summary: Optional short summary of the step.
            parent_step_id: Optional parent step ID for chain-of-thought
                linking.

        Returns:
            The reducer status dict. On success the calling tool can extract
            the created step id from the ``"id"`` key.
        """
        return self._call(
            "add_agent_step",
            [session_id, workspace_id, step_type, content, summary, parent_step_id],
        )

    # -----------------------------------------------------------------------
    # Profiles
    # -----------------------------------------------------------------------

    def upsert_profile(
        self,
        peer_id: str,
        static_facts: str = "",
        dynamic_context: str = "",
        preferences: str = "",
        tags: str = "",
    ) -> dict[str, Any]:
        """Create or update a peer profile.

        Args:
            peer_id: The peer ID.
            static_facts: JSON-encoded list of fact strings.
            dynamic_context: JSON-encoded list of context strings.
            preferences: JSON-encoded object of key-value preferences.
            tags: JSON-encoded list of tag strings.
        """
        return self._call(
            "upsert_profile",
            [
                peer_id,
                static_facts,
                dynamic_context,
                preferences,
                tags,
            ],
        )

    def add_profile_fact(self, peer_id: str, fact: str) -> dict[str, Any]:
        """Add a fact to a peer's profile (appended to static_facts_json array)."""
        return self._call("add_profile_fact", [peer_id, fact])

    def add_dynamic_context(self, peer_id: str, context: str) -> dict[str, Any]:
        """Add dynamic context to a peer's profile."""
        return self._call("add_dynamic_context", [peer_id, context])

    def get_profile(self, peer_id: str) -> dict[str, Any] | None:
        """Get a peer's profile by peer_id."""
        rows = self._query("profile", filter_dict={"peer_id": peer_id})
        return rows[0] if rows else None

    def list_profiles(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all profiles in a workspace (via peers → profiles)."""
        peers = self._query("peer", filter_dict={"workspace_id": workspace_id})
        peer_ids = [p["id"] for p in peers if p.get("id")]
        if not peer_ids:
            return []
        profiles = []
        for pid in peer_ids:
            p = self.get_profile(pid)
            if p:
                profiles.append(p)
        return profiles

    def search_profiles(
        self, workspace_id: str, query: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Search profiles by static_facts or dynamic_context (client-side filter)."""
        profiles = self.list_profiles(workspace_id)
        if query:
            q = query.lower()
            profiles = [
                r
                for r in profiles
                if q in r.get("static_facts_json", "").lower()
                or q in r.get("dynamic_context_json", "").lower()
            ]
        return profiles[:limit]

    def get_profile_context(self, peer_id: str) -> dict[str, Any] | None:
        """Get profile context result for a peer (calls get_profile_context reducer)."""
        self._call("get_profile_context", [peer_id])
        rows = self._sql(f"SELECT * FROM profile_context_result WHERE peer_id = '{_esc(peer_id)}'")
        return rows[0] if rows else None

    # -----------------------------------------------------------------------
    # Facts
    # -----------------------------------------------------------------------

    def add_fact(
        self,
        workspace_id: str,
        peer_id: str,
        content: str,
        fact_type: str = "dynamic",
        category: str = "custom",
        confidence: float = 0.8,
        source: str = "manual",
        tier: str = "L1",
    ) -> dict[str, Any]:
        """Add a fact about a peer.

        Parameters
        ----------
        workspace_id:
            The workspace ID.
        peer_id:
            The peer to associate the fact with.
        content:
            The fact content text.
        fact_type:
            Fact type (e.g. ``"dynamic"``, ``"static"``).
        category:
            Fact category (e.g. ``"custom"``).
        confidence:
            Confidence score (0.0–1.0). Default 0.8.
        source:
            Source of the fact (e.g. ``"manual"``).
        tier:
            Memory tier: ``"L0"``, ``"L1"``, or ``"L2"``.
        """
        return self._call(
            "add_fact",
            [workspace_id, peer_id, fact_type, category, content, confidence, source, tier],
        )

    def list_facts(
        self,
        workspace_id: str,
        peer_id: str = "",
        fact_type: str = "",
        tier: str = "",
        category: str = "",
    ) -> list[dict[str, Any]]:
        """List facts for a workspace with optional filters.

        Parameters
        ----------
        workspace_id:
            The workspace ID.
        peer_id:
            Optional: filter by peer ID.
        fact_type:
            Optional: filter by fact type.
        tier:
            Optional: filter by memory tier.
        category:
            Optional: filter by category.

        Returns:
            List of fact records from the ``fact_result`` table.
        """
        self._call("list_facts", [workspace_id, peer_id, fact_type, tier, category])
        query_hash = f"{workspace_id}:{peer_id}:{fact_type}:{tier}:{category}"
        rows = self._sql(
            f"SELECT * FROM fact_result WHERE query_hash = '{_esc(query_hash)}' ORDER BY created_at DESC"
        )
        if rows:
            try:
                return json.loads(rows[0].get("json_data", "[]"))
            except (json.JSONDecodeError, IndexError):
                logger.warning("get_cached_fact_result: failed to parse cached JSON data")
        return []

    def delete_fact(self, fact_id: str) -> dict[str, Any]:
        """Deactivate a fact (soft delete).

        Parameters
        ----------
        fact_id:
            The fact ID to delete.

        Returns:
            The reducer result dict.
        """
        return self._call("delete_fact", [fact_id])

    def update_fact(
        self,
        fact_id: str,
        content: str = "",
        confidence: float = 0.0,
        category: str = "",
        tier: str = "",
    ) -> dict[str, Any]:
        """Update a fact's content, confidence, category, and/or tier.

        Empty string parameters leave the corresponding field unchanged.
        A confidence of 0.0 leaves confidence unchanged.

        Parameters
        ----------
        fact_id:
            The fact ID to update.
        content:
            New content text (empty string = no change).
        confidence:
            New confidence score (0.0 = no change, 0.0–1.0).
        category:
            New category (empty string = no change).
        tier:
            New memory tier: ``\"L0\"``, ``\"L1\"``, or ``\"L2\"`` (empty string = no change).

        Returns:
            The reducer result dict.
        """
        return self._call("update_fact", [fact_id, content, confidence, category, tier])

    def search_facts(
        self,
        workspace_id: str,
        query: str,
        tier: str = "",
    ) -> list[dict[str, Any]]:
        """Search facts by content text (substring / case-insensitive match).

        Parameters
        ----------
        workspace_id:
            The workspace ID.
        query:
            The search query text.
        tier:
            Optional: filter by memory tier (``\"L0\"``, ``\"L1\"``, ``\"L2\"``).

        Returns:
            List of matching fact records from the ``fact_result`` table.
        """
        self._call("search_facts", [workspace_id, query, tier])
        query_hash = f"search:{query}:{tier}"
        rows = self._sql(
            f"SELECT * FROM fact_result WHERE query_hash = '{_esc(query_hash)}' ORDER BY created_at DESC"
        )
        if rows:
            try:
                return json.loads(rows[0].get("json_data", "[]"))
            except (json.JSONDecodeError, IndexError):
                logger.warning("get_fact_cache: failed to parse cached JSON data")
        return []

    # -----------------------------------------------------------------------
    # Knowledge Graph — additional queries
    # -----------------------------------------------------------------------

    def get_node(self, node_id: str) -> list[dict[str, Any]]:
        """Get a KG node by ID."""
        return self._query("kg_node", filter_dict={"id": node_id})

    def get_community(self, community_id: int) -> dict[str, Any]:
        """Get community details and its nodes."""
        community = self._query("kg_community", filter_dict={"id": str(community_id)})
        nodes = self._query("kg_node", filter_dict={"community_id": str(community_id)})
        return {
            "community": community[0] if community else None,
            "nodes": nodes,
        }

    def compute_pagerank(
        self, workspace_id: str, damping: float = 0.85, max_iterations: int = 100
    ) -> dict[str, Any]:
        """Compute PageRank centrality for all nodes in a workspace.

        Args:
            workspace_id: The workspace to compute PageRank for.
            damping: PageRank damping factor (default: 0.85).
            max_iterations: Maximum iterations (default: 100).

        Returns:
            Reducer status.
        """
        return self._call("compute_pagerank", [workspace_id, damping, max_iterations])

    def compute_community_hierarchy(self, workspace_id: str) -> dict[str, Any]:
        """Build hierarchical community dendrogram using agglomerative clustering.

        Args:
            workspace_id: The workspace to build hierarchy for.

        Returns:
            Reducer status.
        """
        return self._call("compute_community_hierarchy", [workspace_id])

    # -----------------------------------------------------------------------
    # API Keys
    # -----------------------------------------------------------------------

    def create_api_key(
        self,
        workspace_id: str,
        name: str,
        permissions: str = '["read"]',
    ) -> dict[str, Any]:
        """Create a new API key.

        Generates a secure random key secret, hashes it, and stores the
        hash in the SpacetimeDB ``ApiKey`` table.  The unhashed secret is
        returned **only once** — save it.

        Args:
            workspace_id: The workspace to associate the key with.
            name: A human-readable label for this key.
            permissions: JSON array of permission strings
                (default: ``["read"]``).

        Returns:
            Dict with ``status``, ``api_key`` (the secret), ``id`` (the
            key's database ID), and a warning note.
        """
        raw = secrets.token_bytes(32)
        api_key = "sk-" + raw.hex()
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        request_id = secrets.token_hex(16)

        self._call(
            "create_api_key",
            [
                workspace_id,
                name,
                permissions,
                key_hash,
                request_id,
            ],
        )

        # Fetch the just-created key from the public result table
        rows = self._sql(
            "SELECT api_key_id, name, permissions FROM api_key_result WHERE "
            f"request_id = '{_esc(request_id)}' "
            "AND operation = 'create'"
        )
        key_id = rows[0]["api_key_id"] if rows else ""

        return {
            "status": "ok",
            "api_key": api_key,
            "id": key_id,
            "note": "Save this key — it will not be shown again.",
        }

    def deactivate_api_key(self, key_id: str) -> dict[str, Any]:
        """Deactivate (revoke) an API key so it can no longer be used.

        Args:
            key_id: The primary-key ``id`` of the ``ApiKey`` row.

        Returns:
            Reducer status dict.
        """
        return self._call("deactivate_api_key", [key_id])

    def list_api_keys(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all API keys for a workspace.

        Calls the ``list_api_keys`` reducer which populates the public
        ``api_key_result`` table with metadata (key_hash excluded).

        Args:
            workspace_id: The workspace to query.

        Returns:
            List of API key metadata dicts.  The ``key_hash`` is never
            exposed — only safe metadata is returned.
        """
        self._call("list_api_keys", [workspace_id])
        return self._sql(
            "SELECT api_key_id, name, permissions, is_active, created_at, last_used_at "
            "FROM api_key_result WHERE "
            f"workspace_id = '{_esc(workspace_id)}' "
            "AND operation = 'list'"
        )

    # -----------------------------------------------------------------------
    # User management
    # -----------------------------------------------------------------------

    def add_user(
        self,
        user_id: str,
        email: str = "",
        first_name: str = "",
        last_name: str = "",
        metadata_json: str = "",
    ) -> dict[str, Any]:
        """Add a new user.

        The user table is public (readable via SQL) but mutations go through
        this reducer for auth enforcement.

        Args:
            user_id: Unique identifier for the user.
            email: Optional email address.
            first_name: Optional first name.
            last_name: Optional last name.
            metadata_json: Optional JSON blob for custom metadata.

        Returns:
            Reducer status dict.
        """
        return self._call("add_user", [user_id, email, first_name, last_name, metadata_json])

    def get_user(self, user_id: str) -> dict[str, Any]:
        """Verify a user exists (reducer checks auth, then client reads the
        public ``user`` table).

        Args:
            user_id: The user to look up.

        Returns:
            The user row, or raises :class:`NotFoundError` if absent.
        """
        self._call("get_user", [user_id])
        rows = self._sql(
            "SELECT user_id, email, first_name, last_name, metadata_json, "
            "created_at, updated_at "
            f"FROM \"user\" WHERE user_id = '{_esc(user_id)}'"
        )
        if not rows:
            raise NotFoundError(f"User '{user_id}' not found")
        return rows[0]

    def update_user(
        self,
        user_id: str,
        email: str = "",
        first_name: str = "",
        last_name: str = "",
        metadata_json: str = "",
    ) -> dict[str, Any]:
        """Update an existing user. Empty strings are treated as "don't update"
        (the Rust reducer preserves the existing value).

        Args:
            user_id: The user to update.
            email: New email (empty = unchanged).
            first_name: New first name (empty = unchanged).
            last_name: New last name (empty = unchanged).
            metadata_json: New metadata JSON (empty = unchanged).

        Returns:
            Reducer status dict.
        """
        return self._call("update_user", [user_id, email, first_name, last_name, metadata_json])

    def delete_user(self, user_id: str) -> dict[str, Any]:
        """Delete a user by user_id.

        Args:
            user_id: The user to delete.

        Returns:
            Reducer status dict.
        """
        return self._call("delete_user", [user_id])

    def list_users(self) -> list[dict[str, Any]]:
        """List all users. The reducer verifies authentication; then the
        client reads the public ``user`` table directly.

        Returns:
            List of user rows.
        """
        self._call("list_users", [])
        return self._sql(
            "SELECT user_id, email, first_name, last_name, metadata_json, "
            "created_at, updated_at FROM \"user\""
        )

    def get_user_sessions(self, user_id: str) -> list[dict[str, Any]]:
        """Get all sessions for a user.

        Calls the ``get_user_sessions`` reducer which populates the public
        ``user_session_result`` table with session metadata.

        Args:
            user_id: The user to look up sessions for.

        Returns:
            List of session records (query_id, user_id, session_id,
            session_name, workspace_id, created_at).
        """
        query_id = f"user_sessions:{user_id}"
        self._call("get_user_sessions", [user_id])
        return self._sql(
            "SELECT query_id, user_id, session_id, session_name, "
            "workspace_id, created_at FROM user_session_result WHERE "
            f"query_id = '{_esc(query_id)}'"
        )

    # -----------------------------------------------------------------------
    # Peer queries
    # -----------------------------------------------------------------------

    def list_peers(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        """List peers, optionally filtered by workspace."""
        return self._query("peer", workspace_id=workspace_id or "")

    # -----------------------------------------------------------------------
    # Context pack queries
    # -----------------------------------------------------------------------

    def list_context_packs(self, workspace_id: str) -> list[dict[str, Any]]:
        """List context packs for a workspace."""
        return self._query("context_pack", filter_dict={"workspace_id": workspace_id})

    def list_context_entries(self, pack_id: str) -> list[dict[str, Any]]:
        """List entries in a context pack."""
        return self._query("context_entry", filter_dict={"pack_id": pack_id})

    def list_context_deltas(self, previous_pack_id: str) -> list[dict[str, Any]]:
        """List delta entries for a pack."""
        return self._query("context_delta", filter_dict={"previous_pack_id": previous_pack_id})

    # -----------------------------------------------------------------------
    # Notes (markdown documents with wikilink backlinking)
    # -----------------------------------------------------------------------

    def create_note(
        self,
        workspace_id: str = "default",
        title: str = "",
        content: str = "",
        note_date: str = "",
        embed: bool = True,
    ) -> dict[str, Any]:
        """Create a note. If *embed* is True, auto-embeds via the sidecar."""
        embedding_json = "[]"
        if embed and content.strip():
            emb = self._embed(content[:1024])
            if emb:
                embedding_json = json.dumps(emb)
        result = self._call(
            "create_note",
            [
                workspace_id,
                title,
                content,
                note_date,
                embedding_json,
            ],
        )

        # Index the note into search_index so hybrid search finds it
        if result.get("status") == "ok" and content.strip():
            note_id = ""
            try:
                # Resolve the note ID by content match (same pattern as store_memory)
                notes = self._query(
                    "note",
                    workspace_id=workspace_id,
                    filter_dict={},
                    columns=["id", "content", "title"],
                )
                for n in reversed(notes):
                    if n.get("content", "") == content:
                        note_id = n["id"]
                        break
            except RuntimeError:
                logger.warning("add_note: note ID resolution failed, skipping Tantivy/BM25 indexing")
                return result
            if note_id:
                try:
                    index_emb = embedding_json if embedding_json != "[]" else "[]"
                    self._call(
                        "index_entity",
                        [
                            workspace_id,
                            "note",
                            note_id,
                            content,
                            index_emb,
                        ],
                    )
                    # Populate BM25 inverted index
                    self._call(
                        "index_terms",
                        [
                            workspace_id,
                            "note",
                            note_id,
                            content,
                        ],
                    )
                    # Index into Tantivy BM25 sidecar
                    self._tantivy_index(workspace_id, note_id, content, "note")
                except RuntimeError:
                    logger.warning("add_note: Tantivy/BM25 indexing failed for note %s, skipping", note_id)
        return result

    def update_note(
        self,
        note_id: str,
        title: str = "",
        content: str = "",
        embed: bool = True,
        expected_version: int = 0,
    ) -> dict[str, Any]:
        """Update a note. Re-embeds if content changes and *embed* is True.

        Pass *expected_version* to enable optimistic concurrency control.
        If the note has been modified since you last read it, the reducer
        returns an error and you should re-read, re-apply, and retry.
        """
        embedding_json = "[]"
        if embed and content.strip():
            emb = self._embed(content[:1024])
            if emb:
                embedding_json = json.dumps(emb)
        result = self._call("update_note", [note_id, title, content, embedding_json, expected_version])

        # Re-index the note in search_index (best-effort)
        if result.get("status") == "ok" and content.strip():
            try:
                # Resolve workspace_id from the note record
                note_records = self._query(
                    "note",
                    filter_dict={"id": note_id},
                    columns=["id", "workspace_id", "content"],
                )
                wid = note_records[0]["workspace_id"] if note_records else "default"
                # Remove old index entries first
                self._call("remove_from_index", ["note", note_id])
                # Re-index with new content
                index_emb = embedding_json if embedding_json != "[]" else "[]"
                self._call("index_entity", [wid, "note", note_id, content, index_emb])
                self._call("index_terms", [wid, "note", note_id, content])
                self._tantivy_index(wid, note_id, content, "note")
            except RuntimeError:
                logger.warning("update_note: Tantivy re-indexing failed for note %s, skipping", note_id)
        return result

    def delete_note(self, note_id: str) -> dict[str, Any]:
        """Delete a note and its backlinks, and remove from search index."""
        result = self._call("delete_note", [note_id])
        # Clean up search index entries
        if result.get("status") == "ok":
            try:
                self._call("remove_from_index", ["note", note_id])
            except RuntimeError:
                logger.warning("delete_note: remove_from_index failed for note %s, skipping", note_id)
        return result

    def list_notes(
        self, workspace_id: str = "default", include_inactive: bool = False
    ) -> list[dict[str, Any]]:
        """List notes in a workspace."""
        filt = {"workspace_id": workspace_id}
        if not include_inactive:
            filt["is_active"] = "true"
        rows = self._query("note", workspace_id=workspace_id, filter_dict=filt)
        rows.sort(key=lambda r: r.get("updated_at", 0), reverse=True)
        return rows

    def get_note(self, note_id: str) -> list[dict[str, Any]]:
        """Get a note by ID."""
        return self._query("note", filter_dict={"id": note_id})

    def get_note_by_date(self, note_date: str) -> list[dict[str, Any]]:
        """Get a note by its date string (YYYY-MM-DD)."""
        return self._query("note", filter_dict={"note_date": note_date, "is_active": "true"})

    def get_note_by_title(self, title: str) -> list[dict[str, Any]]:
        """Find a note by exact title."""
        return self._query("note", filter_dict={"title": title, "is_active": "true"})

    def get_backlinks(self, note_id: str) -> list[dict[str, Any]]:
        """Get all notes that link *to* the given note."""
        rows = self._query("note_backlink", filter_dict={"target_note_id": note_id})
        for r in rows:
            src = self._query("note", filter_dict={"id": r.get("source_note_id", "")})
            r["source_title"] = src[0].get("title", "") if src else ""
        return rows

    def get_outgoing_links(self, note_id: str) -> list[dict[str, Any]]:
        """Get all notes that the given note links *to*."""
        rows = self._query("note_backlink", filter_dict={"source_note_id": note_id})
        for r in rows:
            tgt = self._query("note", filter_dict={"id": r.get("target_note_id", "")})
            r["target_title"] = tgt[0].get("title", "") if tgt else ""
        return rows

    # -------------------------------------------------------------------
    # KG Graph Traversal
    # -------------------------------------------------------------------

    def graph_bfs(self, workspace_id: str, start_node_id: str, max_depth: int = 3) -> None:
        """BFS traversal from a start node up to max_depth.
        Results are in graph_traversal_result table, keyed by query_id."""
        self._call("graph_bfs", [workspace_id, start_node_id, max_depth])

    def shortest_path(
        self, workspace_id: str, source_id: str, target_id: str, max_hops: int = 6
    ) -> None:
        """Shortest path between two nodes.
        Results in shortest_path_result table, ordered by step_order."""
        self._call("shortest_path", [workspace_id, source_id, target_id, max_hops])

    def get_neighbors_via_reducer(self, workspace_id: str, node_id: str) -> None:
        """Get immediate neighbours of a node.
        Results in graph_traversal_result table with depth=1."""
        self._call("get_neighbors", [workspace_id, node_id])

    # -------------------------------------------------------------------
    # Mental Models
    # -------------------------------------------------------------------

    def synthesize_mental_models(self, workspace_id: str, memory_ids: list[str]) -> dict[str, Any]:
        """Request synthesis of a mental model from a set of source memories.

        Creates a pending ``MentalModel`` record. Run ``mental_model_synthesis.py``
        to generate actual LLM content.

        Parameters
        ----------
        workspace_id:
            The workspace containing the source memories.
        memory_ids:
            List of memory IDs to synthesize a mental model from.
        """
        return self._call(
            "synthesize_mental_models",
            [workspace_id, json.dumps(memory_ids)],
        )

    def get_mental_model(self, model_id: str) -> list[dict[str, Any]]:
        """Get a single mental model by its ID.

        Parameters
        ----------
        model_id:
            The UUID of the mental model.
        """
        return self._sql(f"SELECT * FROM mental_model WHERE id = '{_esc(model_id)}'")

    def list_mental_models(
        self, workspace_id: str, status: str = ""
    ) -> list[dict[str, Any]]:
        """List mental models for a workspace, optionally filtered by status.

        Parameters
        ----------
        workspace_id:
            The workspace ID.
        status:
            Optional filter: ``"pending"``, ``"completed"``, ``"failed"``,
            or ``""`` for all.
        """
        where = f"workspace_id = '{_esc(workspace_id)}'"
        if status:
            where += f" AND status = '{_esc(status)}'"
        return self._sql(
            f"SELECT * FROM mental_model WHERE {where} ORDER BY created_at DESC"
        )

    def delete_mental_model(self, model_id: str) -> dict[str, Any]:
        """Delete a mental model.

        Parameters
        ----------
        model_id:
            The UUID of the mental model to delete.
        """
        return self._call("delete_mental_model", [model_id])

    def update_mental_model(
        self,
        model_id: str,
        content: str,
        confidence: float = 0.5,
        status: str = "completed",
    ) -> dict[str, Any]:
        """Update the content, confidence, and status of an existing mental model.

        Parameters
        ----------
        model_id:
            The UUID of the mental model.
        content:
            The new synthesized content.
        confidence:
            Confidence score (0.0–1.0) for this mental model. Default 0.5.
        status:
            Status: ``"pending"``, ``"completed"``, or ``"failed"``.
        """
        return self._call(
            "update_mental_model",
            [model_id, content, confidence, status],
        )

    # -------------------------------------------------------------------
    # Tours
    # -------------------------------------------------------------------

    def create_tour(self, workspace_id: str, title: str, description: str = "") -> None:
        """Create a new guided tour."""
        self._call("create_tour", [workspace_id, title, description])

    def add_tour_stop(
        self, tour_id: str, node_id: str, heading: str, description: str = ""
    ) -> None:
        """Add a stop to a tour."""
        self._call("add_tour_stop", [tour_id, node_id, heading, description])

    def delete_tour(self, tour_id: str) -> None:
        """Delete a tour and all its stops."""
        self._call("delete_tour", [tour_id])

    def delete_tour_stop(self, stop_id: str) -> None:
        """Remove a single stop from a tour.

        Args:
            stop_id: The ID of the tour stop to remove.
        """
        self._call("remove_tour_stop", [stop_id])

    # -------------------------------------------------------------------
    # Tag Management
    # -------------------------------------------------------------------

    def create_tag(self, workspace_id: str, name: str, color: str = "#808080") -> None:
        """Create a new tag for organizing memories.

        Args:
            workspace_id: Target workspace.
            name: Tag display name.
            color: Hex color string (default: ``"#808080"``).
        """
        self._call("create_tag", [workspace_id, name, color])

    def tag_memory(self, memory_id: str, tag_id: str) -> None:
        """Attach a tag to a memory.

        Args:
            memory_id: The memory to tag.
            tag_id: The tag to attach.
        """
        self._call("tag_memory", [memory_id, tag_id])

    def untag_memory(self, memory_id: str, tag_id: str) -> None:
        """Remove a tag from a memory.

        Args:
            memory_id: The tagged memory.
            tag_id: The tag to detach.
        """
        self._call("untag_memory", [memory_id, tag_id])

    def batch_tag_memories(self, tag_id: str, memory_ids: list[str]) -> dict[str, Any]:
        """Batch-attach a tag to multiple memories in a single reducer call.

        Eliminates O(n) network round-trips for bulk tagging by sending all
        memory IDs in one call to the ``batch_tag_memories`` reducer.

        Args:
            tag_id: The tag to attach.
            memory_ids: List of memory ID strings to tag. Already-tagged
                memories are silently skipped (idempotent).

        Returns:
            Dict with ``status``: ``"ok"`` on success.
        """
        if not memory_ids:
            return {"status": "ok", "note": "no memory IDs provided"}
        return self._call("batch_tag_memories", [tag_id, json.dumps(memory_ids)])

    def batch_untag_memories(self, tag_id: str, memory_ids: list[str]) -> dict[str, Any]:
        """Batch-remove a tag from multiple memories in a single reducer call.

        Eliminates O(n) network round-trips for bulk untagging by sending all
        memory IDs in one call to the ``batch_untag_memories`` reducer.

        Args:
            tag_id: The tag to detach.
            memory_ids: List of memory ID strings to untag. Missing
                associations are silently skipped (idempotent).

        Returns:
            Dict with ``status``: ``"ok"`` on success.
        """
        if not memory_ids:
            return {"status": "ok", "note": "no memory IDs provided"}
        return self._call("batch_untag_memories", [tag_id, json.dumps(memory_ids)])

    def list_tags(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all tags in a workspace.

        Args:
            workspace_id: Target workspace.

        Returns:
            List of tag dicts with id, workspace_id, name, color, created_at.
        """
        # Note: the list_tags reducer was changed to return () for STDB v2.6 compat.
        # We now query the tag table directly via _query.
        self._call("list_tags", [workspace_id])  # auth gate
        return self._query("tag", workspace_id=workspace_id, columns=["id", "workspace_id", "name", "color", "created_at"])

    def delete_tag(self, tag_id: str) -> None:
        """Delete a tag and all its memory associations.

        Args:
            tag_id: The tag ID to delete.
        """
        self._call("delete_tag", [tag_id])

    def list_tags_by_memory(self, memory_id: str) -> list[dict[str, Any]]:
        """List all tags attached to a specific memory.

        Calls the ``list_tags_by_memory`` reducer which writes to the
        ``memory_tag_result`` table, then queries that table.

        Args:
            memory_id: The memory to look up tags for.

        Returns:
            A list of dicts with keys: id, memory_id, tag_id, tag_name, tag_color.
        """
        self._call("list_tags_by_memory", [memory_id])
        return self._sql(
            f"SELECT id, memory_id, tag_id, tag_name, tag_color "
            f"FROM memory_tag_result "
            f"WHERE memory_id = '{_esc(memory_id)}'"
        )

    def update_tag(self, tag_id: str, name: str = "", color: str = "#808080") -> None:
        """Update a tag's name and/or color.

        Args:
            tag_id: The tag ID to update.
            name: New display name (empty string leaves unchanged).
            color: New hex color string.
        """
        self._call("update_tag", [tag_id, name, color])

    def search_by_tags(
        self,
        workspace_id: str,
        tag_ids: list[str],
        query: str = "",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search memories by tag filter, optionally with semantic ranking.

        Only memories that have ALL specified tags are returned (intersection).

        Args:
            workspace_id: Target workspace.
            tag_ids: List of tag IDs to filter by (AND intersection).
            query: Optional query string for semantic ranking. Pass empty
                string to skip semantic similarity (results ordered by recency).
            limit: Maximum number of results.

        Returns:
            List of hybrid_result rows matching all tags, sorted by
            relevance (if query provided) or recency.
        """
        # Get embedding if query provided
        emb_json = "[]"
        if query:
            query_text = (
                f"Represent this sentence for searching relevant passages: {query}"
            )
            emb = self._embed(query_text)
            emb_json = json.dumps(emb) if emb else "[]"

        tag_ids_json = json.dumps(tag_ids)
        self._call(
            "search_by_tags",
            [
                workspace_id,
                tag_ids_json,
                emb_json,
                limit,
            ],
        )
        qhash = _query_hash(f"tagged:{tag_ids_json}")
        return self._sql(
            "SELECT * FROM hybrid_result "
            f"WHERE workspace_id = '{_esc(workspace_id)}' "
            f"  AND query_hash = '{_esc(qhash)}' "
            "ORDER BY score DESC"
        )

    # -------------------------------------------------------------------
    # Connector Configuration
    # -------------------------------------------------------------------

    def register_connector(
        self,
        name: str,
        connector_type: str,
        config_json: str,
        workspace_id: str,
        schedule_secs: int,
    ) -> None:
        """Register a new connector configuration."""
        self._call(
            "register_connector",
            [name, connector_type, config_json, workspace_id, schedule_secs],
        )

    def update_connector(
        self,
        id: str,
        name: str,
        connector_type: str,
        config_json: str,
        workspace_id: str,
        schedule_secs: int,
        is_active: bool,
    ) -> None:
        """Update an existing connector configuration."""
        self._call(
            "update_connector",
            [id, name, connector_type, config_json, workspace_id, schedule_secs, is_active],
        )

    def delete_connector(self, id: str) -> None:
        """Delete a connector configuration."""
        self._call("delete_connector", [id])

    # -------------------------------------------------------------------
    # Entity Extraction
    # -------------------------------------------------------------------

    def extract_entities(self, workspace_id: str, content: str) -> None:
        """Extract entities from text content and create KG nodes."""
        self._call("extract_entities", [workspace_id, content])

    # -------------------------------------------------------------------
    # Harmonic Beliefs
    # -------------------------------------------------------------------

    def store_harmonic_beliefs(
        self,
        workspace_id: str,
        peer_id: str,
        beliefs_json: str,
        cluster_id: str,
    ) -> None:
        """Store harmonized beliefs from one resonance round."""
        self._call(
            "store_harmonic_beliefs",
            [workspace_id, peer_id, beliefs_json, cluster_id],
        )

    def clear_harmonic_beliefs(self, workspace_id: str, min_confidence: float) -> None:
        """Clear stale beliefs for a workspace."""
        self._call("clear_harmonic_beliefs", [workspace_id, min_confidence])

    def log_resonance_session(
        self,
        workspace_id: str,
        peer_id: str,
        cluster_count: int,
        beliefs_generated: int,
        contradictions_resolved: int,
        harmony_score_avg: float,
        duration_ms: int,
    ) -> None:
        """Log a resonance session summary."""
        self._call(
            "log_resonance_session",
            [
                workspace_id,
                peer_id,
                cluster_count,
                beliefs_generated,
                contradictions_resolved,
                harmony_score_avg,
                duration_ms,
            ],
        )

    # -------------------------------------------------------------------
    # Entity Linking
    # -------------------------------------------------------------------

    def create_entity_link(
        self,
        workspace_id: str,
        canonical_name: str,
        entity_type: str,
        description: str = "",
    ) -> None:
        """Create a canonical entity link for Mem0-style entity resolution."""
        self._call(
            "create_entity_link",
            [
                workspace_id,
                canonical_name,
                "[]",
                entity_type,
                description,
            ],
        )

    def add_alias(self, entity_link_id: str, alias: str) -> None:
        """Add an alias to an existing entity link."""
        self._call("add_alias", [entity_link_id, alias])

    def resolve_entity(self, workspace_id: str, name: str) -> None:
        """Resolve an entity name within a workspace."""
        self._call("resolve_entity", [workspace_id, name])

    # -------------------------------------------------------------------
    # Backup & Restore
    # -------------------------------------------------------------------

    _BACKUP_TABLES = [
        "workspace",
        "space_permission",
        "memory",
        "memory_version",
        "kg_node",
        "kg_edge",
        "kg_community",
        "session",
        "session_participant",
        "message",
        "profile",
        "note",
        "fact",
        "peer",
        "context_pack",
        "context_entry",
        "directory",
        "directory_link",
        "backlink",
        "merge_suggestion",
        "connector_config",
        "entity_link",
    ]

    # -------------------------------------------------------------------
    # Memory Encryption at Rest
    # -------------------------------------------------------------------

    def init_workspace_encryption(self, workspace_id: str) -> dict[str, str]:
        """Initialise AES-256-GCM encryption for a workspace.

        Generates a new encryption key and enables encryption. Memories
        stored after this call will be encrypted before being written to
        SpacetimeDB. Existing plaintext memories are NOT automatically
        encrypted — call ``encrypt_existing_memories()`` after init.

        Idempotent: returns an error if encryption is already initialised.

        Args:
            workspace_id: The workspace to encrypt.

        Returns:
            Dict with status result from the reducer.
        """
        return self._call("init_workspace_encryption", [workspace_id])

    def set_workspace_encryption_enabled(
        self, workspace_id: str, enabled: bool
    ) -> dict[str, str]:
        """Enable or disable memory encryption for a workspace.

        When disabled, new memories are stored in plaintext. Existing
        encrypted memories are not automatically decrypted — they remain
        in their encrypted form in the database.

        Args:
            workspace_id: The workspace to modify.
            enabled: True to enable encryption, False to disable.

        Returns:
            Dict with status result from the reducer.
        """
        return self._call(
            "set_workspace_encryption_enabled", [workspace_id, enabled]
        )

    def rotate_workspace_encryption_key(self, workspace_id: str) -> dict[str, str]:
        """Rotate the encryption key for a workspace.

        New memories will use the new key. Call ``encrypt_existing_memories()``
        after rotation to re-encrypt existing memories with the new key.

        Args:
            workspace_id: The workspace whose key should be rotated.

        Returns:
            Dict with status result from the reducer.
        """
        return self._call("rotate_workspace_encryption_key", [workspace_id])

    def encrypt_existing_memories(self, workspace_id: str) -> dict[str, str]:
        """Re-encrypt all unencrypted memories in a workspace.

        Useful after initial encryption setup or key rotation. Encrypts
        any memories whose content is still in plaintext using the current
        workspace encryption key.

        Requires encryption to be enabled for the workspace.

        Args:
            workspace_id: The workspace whose memories should be encrypted.

        Returns:
            Dict with status result from the reducer.
        """
        return self._call("encrypt_existing_memories", [workspace_id])

    def get_decrypted_memory(self, memory_id: str) -> dict[str, str]:
        """Fetch a memory with its content and summary decrypted.

        Calls the ``get_decrypted_memory`` reducer which decrypts the
        stored ciphertext using the workspace key. Results are written
        to the ``decrypted_memory_result`` table for the calling identity.

        Args:
            memory_id: The ID of the memory to decrypt and return.

        Returns:
            Dict with status result from the reducer.
        """
        return self._call("get_decrypted_memory", [memory_id])

    def backup(self, output_path: str | None = None) -> dict[str, Any]:
        """Export all user data tables to a JSON file.

        Args:
            output_path: Path to write the backup file. If None, generates
                a filename like ``spacetime-memory-backup-YYYY-MM-DD.json``.

        Returns:
            Dict with backup metadata: tables backed up, row counts, file path.
        """
        import datetime

        manifest: dict[str, list[dict[str, Any]]] = {}
        total_rows = 0
        backed_up = []

        for table in self._BACKUP_TABLES:
            try:
                rows = self._query(table)
            except RuntimeError:
                logger.debug("backup: table '%s' does not exist or is not queryable, skipping", table)
                continue  # table doesn't exist or isn't queryable
            if rows:
                manifest[table] = rows
                total_rows += len(rows)
                backed_up.append(table)
            else:
                manifest[table] = []

        if output_path is None:
            date = datetime.date.today().isoformat()
            output_path = f"spacetime-memory-backup-{date}.json"

        payload = {
            "version": "0.3.0",
            "created_at": datetime.datetime.utcnow().isoformat(),
            "tables": manifest,
            "stats": {
                "table_count": len(backed_up),
                "total_rows": total_rows,
            },
        }

        # ── Plugin dispatch: on_export ──
        if self.plugin_manager is not None:
            # Convert manifest to flat list for plugin filtering
            all_rows: list[dict[str, Any]] = []
            for rows in manifest.values():
                all_rows.extend(rows)
            self.plugin_manager.dispatch_export(all_rows)

        with open(output_path, "w") as f:
            json.dump(payload, f, indent=2, default=str)

        return {
            "status": "ok",
            "path": output_path,
            "tables": backed_up,
            "total_rows": total_rows,
        }

    def restore(self, input_path: str) -> dict[str, Any]:
        """Import a backup file into the current database.

        Args:
            input_path: Path to the backup JSON file.

        Returns:
            Dict with restore metadata: tables restored, row counts.
        """
        with open(input_path, "r") as f:
            payload = json.load(f)

        manifest = payload.get("tables", {})
        total_restored = 0
        restored = []

        # ── Plugin dispatch: on_import ──
        if self.plugin_manager is not None:
            all_rows: list[dict[str, Any]] = []
            for rows in manifest.values():
                all_rows.extend(rows)
            self.plugin_manager.dispatch_import(all_rows)

        for table, rows in manifest.items():
            if not rows:
                continue
            if not rows[0]:
                continue
            try:
                col_names = list(rows[0].keys())
                placeholders = ", ".join(col_names)
                for row in rows:
                    values = []
                    for col in col_names:
                        val = row.get(col)
                        if val is None:
                            values.append("NULL")
                        elif isinstance(val, bool):
                            values.append("true" if val else "false")
                        elif isinstance(val, (int, float)):
                            values.append(str(val))
                        else:
                            values.append(f"'{_esc(str(val))}'")
                    sql = f"INSERT INTO {table} ({placeholders}) VALUES ({', '.join(values)})"
                    try:
                        self._sql(sql)
                    except RuntimeError:
                        logger.warning("restore: INSERT failed for table '%s' row, may be duplicate or schema mismatch", table)
                restored.append(table)
                total_restored += len(rows)
            except Exception:
                logger.error("restore: failed to restore table '%s', skipping", table)
                continue

        return {
            "status": "ok",
            "input_path": input_path,
            "tables": restored,
            "total_rows": total_restored,
        }

    @property
    def delta_sync(self):
        """Lazy-initialised ``DeltaSync`` instance for change-event polling.

        Usage::

            client.delta_sync.on("memory", "insert", lambda e: print(e))
            client.delta_sync.start()
        """
        if self._delta_sync is None:
            from .delta_sync import DeltaSync

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
            from .compounder import Compounder

            self._compounder = Compounder(self)
        return self._compounder


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _esc(val: str) -> str:
    """Basic SQL string escaping for single-quoted string literals."""
    return val.replace("'", "''")


def _query_hash(query: str) -> str:
    """Deterministic hash matching the Rust hybrid_query reducer."""
    h = 0
    for b in query.encode("utf-8"):
        h = ((h * 6364136223846793005) + b) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def _parse_sql_response(raw: str) -> list[dict[str, Any]]:
    """Parse SpacetimeDB's positional-array SQL response into dicts."""
    if not raw.strip():
        return []
    tables = json.loads(raw)
    results: list[dict[str, Any]] = []
    for table in tables:
        elements = table.get("schema", {}).get("elements", [])
        col_names: list[str] = []
        for el in elements:
            name_container = el.get("name", {})
            if isinstance(name_container, dict) and "some" in name_container:
                col_names.append(name_container["some"])
            else:
                col_names.append("?col?")
        for row in table.get("rows", []):
            row_dict: dict[str, Any] = {}
            for i, val in enumerate(row):
                key = col_names[i] if i < len(col_names) else f"col{i}"
                row_dict[key] = val
            results.append(row_dict)
    return results


def _make_snippet(text: str, max_chars: int = 200) -> str:
    """Truncate text at word boundary, appending '...' if truncated.

    Args:
        text: The full text to truncate.
        max_chars: Maximum character length before truncation (default 200).

    Returns:
        Truncated text ending at a word boundary, with ``...`` appended
        if the original exceeded *max_chars*.  Returns ``\"\"`` for
        falsy input.
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    # Break at last space within the truncated portion
    last_space = truncated.rfind(" ")
    if last_space > max_chars // 2:  # Only use word boundary if non-trivial
        truncated = truncated[:last_space]
    return truncated.rstrip() + "..."


# ---------------------------------------------------------------------------
# LLM Reranking (QMD parity)
# ---------------------------------------------------------------------------


def _parse_rerank_json(content: str) -> list[dict]:
    """Parse LLM reranker JSON output with 6 fallback strategies.

    LLMs frequently return malformed JSON — trailing commas, markdown fences,
    wrapped objects, line-by-line output.  This tries progressively more
    aggressive salvage strategies.

    Raises ValueError if all 6 strategies fail.
    """
    scores: list[dict] = []
    parse_ok = False
    errors: list[str] = []

    # Strategy 1: Direct parse
    try:
        scores = json.loads(content)
        if isinstance(scores, list):
            parse_ok = True
    except json.JSONDecodeError as e:
        errors.append(f"direct: {e}")

    # Strategy 2: Find JSON array boundaries
    if not parse_ok:
        m = re.search(r"\[.*\]", content, re.DOTALL)
        if m:
            try:
                scores = json.loads(m.group())
                if isinstance(scores, list):
                    parse_ok = True
            except json.JSONDecodeError as e:
                errors.append(f"array: {e}")

    # Strategy 3: Strict=False, try to salvage partial
    if not parse_ok:
        try:
            decoder = json.JSONDecoder()
            scores, _ = decoder.raw_decode(content)
            if isinstance(scores, dict):
                scores = [scores]
            if isinstance(scores, list):
                parse_ok = True
        except json.JSONDecodeError as e:
            errors.append(f"strict_false: {e}")

    # Strategy 4: Aggressive salvage — strip trailing commas, fix unquoted keys
    if not parse_ok:
        cleaned = content
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        m = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if m:
            try:
                scores = json.loads(m.group())
                if isinstance(scores, list):
                    parse_ok = True
            except json.JSONDecodeError as e:
                errors.append(f"salvage_array: {e}")

        if not parse_ok:
            # Look for a JSON object containing a "score" key
            m = re.search(r'\{[^}]*"score"[^}]*\}', cleaned, re.DOTALL)
            if m:
                try:
                    obj = json.loads(m.group())
                    if isinstance(obj, dict):
                        scores = [obj]
                        parse_ok = True
                except json.JSONDecodeError as e:
                    logger.debug("_parse_rerank_json: strategy 4 object salvage failed: %s", e)

    # Strategy 5: Dict wrapper — LLM returned {"scores": [...]} or similar
    if not parse_ok:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group())
                if isinstance(obj, dict):
                    for key in ("scores", "results", "rankings", "items", "data"):
                        if key in obj and isinstance(obj[key], list):
                            scores = obj[key]
                            parse_ok = True
                            break
                    if not parse_ok and "index" in obj:
                        scores = [obj]
                        parse_ok = True
            except json.JSONDecodeError as e:
                errors.append(f"dict_wrapper: {e}")

    # Strategy 6: Line-by-line extraction — one JSON object per line
    if not parse_ok and content.strip():
        lines = [line.strip() for line in content.split("\n") if line.strip().startswith("{")]
        if lines:
            extracted = []
            for line in lines:
                try:
                    obj = json.loads(line.rstrip(","))
                    if isinstance(obj, dict) and "index" in obj:
                        extracted.append(obj)
                except json.JSONDecodeError as e:
                    logger.debug("_parse_rerank_json: strategy 6 line-by-line parse failed: %s", e)
                    continue
            if extracted:
                scores = extracted
                parse_ok = True

    if not parse_ok:
        raise ValueError(f"JSON parse failed after 6 strategies: {'; '.join(errors[-2:])}")
    return scores


_RERANK_PROMPT = """Score each search result for relevance to the query (1-10).

10 — perfectly answers the query, exact match
7-9 — highly relevant, contains key information
4-6 — partially relevant, related concepts
1-3 — barely relevant, tangential mention

Query: {query}

Candidates:
{candidates}

Provide your scores as a JSON array in this exact format, no other text:
[{{"index": 0, "score": 8, "reason": "contains exact match for 'auth'"}}, ...]

JSON:"""


def llm_rerank(
    query: str,
    results: list[dict[str, Any]],
    endpoint: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    top_k: int = 10,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    """Rerank search results using an LLM (QMD-style).

    Sends top *top_k* results to an OpenAI-compatible chat completions
    endpoint and returns the original result dicts with scores replaced by
    the LLM's relevance scores and a ``rerank_reason`` field appended.

    Falls back to original results if the LLM call fails.

    Args:
        query: The original search query.
        results: Search result dicts (must have ``content`` key).
        endpoint: OpenAI-compatible base URL (default: env ``LLM_RERANK_ENDPOINT``
                  or ``http://127.0.0.1:4000/v1``).
        model: Model name (default: env ``LLM_RERANK_MODEL`` or ``gpt-4o-mini``).
        api_key: API key (default: env ``LLM_RERANK_API_KEY`` or ``OPENAI_API_KEY``).
        top_k: Number of results to send for reranking (default 10).
        timeout: HTTP timeout in seconds (default 30).
    """
    if not results:
        return results

    # Resolve config
    endpoint = endpoint or os.getenv("LLM_RERANK_ENDPOINT", "http://127.0.0.1:4000/v1")
    model = model or os.getenv("LLM_RERANK_MODEL", "ds-deepseek-v4-flash")
    api_key = api_key or os.getenv("LLM_RERANK_API_KEY") or os.getenv("OPENAI_API_KEY", "")

    # Build candidate list
    candidates_text = "\n".join(
        f"[{i}] {r.get('content', '')[:500]}" for i, r in enumerate(results[:top_k])
    )
    prompt = _RERANK_PROMPT.format(query=query, candidates=candidates_text)

    try:
        # Retry with backoff for rate limits
        resp = None
        for attempt in range(3):
            try:
                resp = httpx.post(
                    f"{endpoint.rstrip('/')}/chat/completions",
                    json={
                        "model": model,
                        "messages": [
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.0,
                        "max_tokens": 2048,
                    },
                    headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                    timeout=timeout,
                )
            except (httpx.ConnectError, httpx.TimeoutException):
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise
            if resp.status_code == 429:
                wait = 2**attempt
                logger.warning(
                    "LLM rerank rate-limited, retrying in %ds (attempt %d/3)", wait, attempt + 1
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        else:
            raise httpx.HTTPStatusError(
                "429 rate limit after 3 retries", request=resp.request, response=resp
            )
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = (msg.get("content") or "").strip()

        # Reasoning models (DeepSeek-R1, o1, etc.) put their output in
        # reasoning_content and leave content empty.  Fall back so the
        # JSON parser still has something to work with.
        if not content:
            reasoning = msg.get("reasoning_content") or ""
            if reasoning:
                content = reasoning.strip()

        # Strip markdown code fences if present
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        # Robust JSON parsing — LLMs sometimes return malformed JSON
        scores = _parse_rerank_json(content)

        # Merge LLM scores back into original results
        score_map: dict[int, tuple[float, str]] = {}
        for s in scores:
            idx = int(s["index"])
            score_map[idx] = (float(s["score"]) / 10.0, s.get("reason", ""))

        for i, r in enumerate(results[:top_k]):
            if i in score_map:
                r["score"] = score_map[i][0]
                r["rerank_reason"] = score_map[i][1]
            else:
                r["score"] = r.get("score", 0.0) * 0.5  # penalize unranked
                r["rerank_reason"] = "not reranked by LLM"

        # Re-sort by new scores
        results[:top_k] = sorted(
            results[:top_k],
            key=lambda r: r.get("score", 0.0),
            reverse=True,
        )

    except (
        json.JSONDecodeError,
        httpx.HTTPStatusError,
        httpx.ConnectError,
        httpx.TimeoutException,
    ) as exc:
        logger.warning("LLM rerank failed, returning original results: %s", exc)

    return results
