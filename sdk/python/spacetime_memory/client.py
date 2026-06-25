"""Python client for spacetime-memory.

Provides a high-level Client class that wraps the SpacetimeDB HTTP SQL API,
the reducer-call endpoint, and embedder support (OpenAI-compatible proxy → NVIDIA NIM).
API fallback.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

import logging
import re

logger = logging.getLogger(__name__)

from .query_expansion import expand_query  # noqa: E402 — intentional late import

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
    "not found": "Record not found. Check the ID.",
    "unauthorized": "Authentication required. Please login first.",
    "already exists": "Record already exists with this identifier.",
    "validation error": "Invalid input. Check the format of your data.",
    "rate limit": "Too many requests. Please wait before trying again.",
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
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )

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
        plugin_manager: Any | None = None,
        event_bus: Any | None = None,
        query_cache: Any | None = None,
        local_llm: Any | None = None,
    ):
        self.host = host or os.environ.get("SPACETIMEDB_HOST", "localhost")
        self.port = str(port or os.environ.get("SPACETIMEDB_PORT", "3001"))
        self.database = database or os.environ.get(
            "SPACETIMEDB_DB", "c20082e7643347e8d36302b550bb98c7343f9ea2a268f3bee58ee58d3c3dcbf1"
        )
        # Bypass HTTP proxy for localhost — the system http_proxy
        # routes through isp.decodo.com which blocks STDB reducer calls.
        os.environ.setdefault("no_proxy", "localhost,127.0.0.1,127.0.0.1,.local")
        self.embedder_url = (
            embedder_url
            or os.environ.get("EMBEDDER_URL", "http://localhost:9090")
        )
        self.tantivy_url = os.environ.get(
            "TANTIVY_URL", "http://localhost:9091"
        )
        self.verbose = verbose
        self.token = token or os.environ.get("SPACETIMEDB_TOKEN")
        self.max_retries = int(os.environ.get("STMEM_MAX_RETRIES", "3"))
        self._circuit_breaker_threshold = int(os.environ.get("STMEM_CIRCUIT_THRESHOLD", "5"))
        self._circuit_breaker_reset_secs = float(os.environ.get("STMEM_CIRCUIT_RESET_SECS", "30.0"))
        self._consecutive_failures: int = 0
        # MIB binary vector cache — entity_id → packed bytes
        self._binary_cache: dict[str, bytes] = {}
        self._circuit_open_until: float = 0.0
        self._metrics: Any = None  # Set via set_metrics_collector()
        self._delta_sync: Any = None  # Lazy DeltaSync instance
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
            self.host, self.port,
            self._current_host_index + 1, len(self._hosts),
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

    def _emit_event(
        self, event_type: str, data: dict[str, Any], workspace_id: str = ""
    ) -> None:
        """Emit a memory lifecycle event to the configured event bus."""
        if self.event_bus is not None:
            from .streaming import MemoryEvent
            self.event_bus.emit(MemoryEvent(
                event_type=event_type,
                data=data,
                workspace_id=workspace_id,
            ))

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
                    hostport, host_idx + 1, len(self._hosts),
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

    def _request_with_retry(
        self, method: str, url: str, **kwargs: Any
    ) -> httpx.Response:
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
        import random as _random
        import time as _time

        # Circuit breaker check
        now = _time.time()
        if self._circuit_open_until > now:
            raise RuntimeError(
                f"SpacetimeDB circuit breaker is open "
                f"(retry in {self._circuit_open_until - now:.0f}s). "
                f"Circuit resets at STMEM_CIRCUIT_RESET_SECS="
                f"{self._circuit_breaker_reset_secs}."
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
                delay = 0.5 * (2 ** attempt) * (1 + _random.random())
                logger.warning(
                    "Request failed (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1, self.max_retries + 1, last_exc, delay,
                )
                _time.sleep(delay)

        # All retries exhausted — try failover to next host before giving up
        if self._try_failover():
            logger.info(
                "Failover to %s:%s — re-trying %s %s",
                self.host, self.port, method, url,
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
            self._circuit_open_until = _time.time() + self._circuit_breaker_reset_secs
            logger.warning(
                "Circuit breaker opened for %.0fs after %d consecutive failures",
                self._circuit_breaker_reset_secs, self._consecutive_failures,
            )
        raise RuntimeError(
            f"Request failed after {self.max_retries + 1} attempts: {last_exc}"
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
                return self._request_with_retry(
                    "POST", self.sql_url, content=query, headers=headers,
                )

            if self._metrics is not None:
                resp = self._metrics.record("sql", _do_sql)
            else:
                resp = _do_sql()

            if resp.status_code >= 400:
                error_text = resp.text[:500]
                if self.verbose:
                    raise RuntimeError(
                        f"SQL error (HTTP {resp.status_code}): {error_text}"
                    )
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
        import secrets
        import json

        query_id = secrets.token_hex(16)
        filter_json = json.dumps(filter_dict or {})
        columns_json = json.dumps(columns or [])

        self._call("query_table", [
            query_id, table, workspace_id, filter_json, columns_json,
        ])

        # Read results from the public query_result table
        rows = self._sql(
            "SELECT table_name, row_json FROM query_result WHERE "
            f"query_id = '{_esc(query_id)}'"
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
                return self._request_with_retry(
                    "POST", f"{self.reducer_url}/{reducer}",
                    content=json.dumps(args), headers=headers,
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

        # Capture updated identity token from response (e.g. after register/login)
        new_token = resp.headers.get("spacetime-identity-token", "")
        if new_token and new_token != self._identity_token:
            self._identity_token = new_token
            self._identity_established = True

        return {"status": "ok"}

    _DEFAULT_EMBEDDER_URL = 'http://localhost:9090'

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
                base_url = os.environ.get(
                    "OPENAI_BASE_URL",
                    "https://api.openai.com/v1"
                ).rstrip("/")
                resp = self._http.post(
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
                base_url = os.environ.get(
                    "OPENAI_BASE_URL",
                    "https://api.openai.com/v1"
                ).rstrip("/")
                resp = self._http.post(
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
                resp = self._http.get(f"{self.embedder_url}/health", timeout=5.0)
                if resp.status_code == 200:
                    embedder_status = resp.json()
                    embedder_status["reachable"] = True
                    return embedder_status
                return {"status": "error", "code": resp.status_code, "reachable": True}
            except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as e:
                return {"status": "error", "message": str(e), "reachable": False}

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
            resp = self._http.post(
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
        except (httpx.ConnectError, httpx.TimeoutException):
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
            resp = self._http.post(
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
        except (httpx.ConnectError, httpx.TimeoutException):
            return []

    def ping(self) -> dict[str, Any]:
        """Quick connectivity check against SpacetimeDB.

        Hits the database info endpoint and reports latency.
        """
        import time
        start = time.monotonic()
        try:
            resp = self._http.get(
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
        except (httpx.ConnectError, httpx.TimeoutException) as e:
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

    def create_workspace(self, name: str, description: str = "", id: str | None = None) -> dict[str, Any]:
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
                pass  # Unknown tier string, keep default confidence

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
            result = self._call("store_memory", [
                workspace_id, peer_id, observer_id,
                memory_type, content, summary, entities_json,
                confidence, source_session_id, source_message_id,
            ])
        # ── Invalidate query cache for this workspace ──
        if self._query_cache is not None:
            self._query_cache.invalidate(workspace_id=workspace_id)

        # ── Emit memory.created event ──
        self._emit_event("memory.created", {
            "content": content[:200],
            "summary": summary,
            "memory_type": memory_type,
            "workspace_id": workspace_id,
        }, workspace_id=workspace_id)

        # If the embedder is reachable, index embeddings in the sidecar
        emb = self._embed(content)
        if emb:
            # Resolve the memory ID by content match — more reliable than
            # peer_id query which can return a different concurrent store.
            mems = self._query("memory", workspace_id=workspace_id,
                              filter_dict={},
                              columns=["id", "content"])
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
                    pass  # Binary compression best-effort, non-critical
                self._call("index_entity", [
                    workspace_id, "memory", memory_id,
                    content, json.dumps(emb),
                ])
                # Populate BM25 inverted index (legacy STDB term_index)
                self._call("index_terms", [
                    workspace_id, "memory", memory_id, content,
                ])

                # Index into Tantivy BM25 sidecar (real Okapi BM25)
                self._tantivy_index(workspace_id, memory_id, content, "memory")

                # Entity extraction: LLM first, fall back to regex
                self._extract_and_store_entities(workspace_id, memory_id, content)

        if tier and tier in ("L0", "L1", "L2"):
            mems = self._query("memory", workspace_id=workspace_id,
                              filter_dict={"peer_id": peer_id},
                              columns=["id"])
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
                    self._call("create_entity_link", [
                        workspace_id, name, etype,
                        json.dumps(aliases[:10] if aliases else []),
                        description,
                    ])
                except RuntimeError:
                    pass

                # Link entity to the source memory
                try:
                    self._call("link_entity_to_memory", [
                        name, memory_id, etype,
                    ])
                except RuntimeError:
                    pass
        else:
            # Fall back to regex-based extraction (no LLM key or LLM failed)
            try:
                self._call("extract_entities", [workspace_id, content])
            except RuntimeError:
                pass

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
            clean_items.append({
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
            })

        if not clean_items:
            return []

        # Batch-embed
        try:
            import json
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
            emb_list = []

        # Call batch reducer — pass items as JSON string
        import json as _j
        with _tracing_span("store_batch.call", workspace_id=workspace_id, batch_size=len(clean_items)):
            self._call("store_memory_batch", [_j.dumps(clean_items)])

        # Index each item with its embedding
        for i, item in enumerate(clean_items):
            emb = emb_list[i] if i < len(emb_list) else None
            if emb:
                mems = self._query("memory", workspace_id=workspace_id,
                                  filter_dict={"content": item['content'][:100]},
                                  columns=["id"])
                if mems:
                    # Take most recent (server returns unsorted; sort client-side)
                    mems.sort(key=lambda m: m.get("created_at", 0), reverse=True)
                    import json as _json
                    self._call("index_entity", [
                        workspace_id, "memory", mems[0]["id"],
                        item["content"], _json.dumps(emb),
                    ])
                    # Populate BM25 inverted index
                    self._call("index_terms", [
                        workspace_id, "memory", mems[0]["id"], item["content"],
                    ])
                    # Entity extraction
                    self._extract_and_store_entities(
                        workspace_id, mems[0]["id"], item["content"],
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
            "semantic": {}, "keyword": {}, "graph": {}, "temporal": {},
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
        """Look up memory/node content from STDB and apply veracity weighting."""
        mem_ids = [r.get("entity_id", "") for r in rows if r.get("entity_type") == "memory"]
        node_ids = [r.get("entity_id", "") for r in rows if r.get("entity_type") == "node"]
        mem_map = {}
        mem_confidences: dict[str, float] = {}
        node_map = {}
        for mid in mem_ids:
            mems = self._query("memory", filter_dict={"id": mid},
                               workspace_id=workspace_id,
                               columns=["id", "content", "confidence"])
            if mems:
                mem_map[mid] = mems[0].get("content", "")
                mem_confidences[mid] = mems[0].get("confidence", 0.8)
        for nid in node_ids:
            nodes = self._query("kg_node", filter_dict={"id": nid}, columns=["id", "label"])
            if nodes:
                node_map[nid] = nodes[0].get("label", "")
        for r in rows:
            eid = r.get("entity_id", "")
            if r.get("entity_type") == "memory":
                r["memory_content"] = mem_map.get(eid, "")
            elif r.get("entity_type") == "node":
                r["memory_content"] = node_map.get(eid, "")
            else:
                r["memory_content"] = ""
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
    ) -> list[dict[str, Any]]:
        """Non-semantic keyword-only search fallback using client-side filtering."""
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

        if query:
            _STOPWORDS = {
                "a", "an", "the", "is", "are", "was", "were", "be", "been",
                "who", "what", "where", "when", "why", "how", "which", "do",
                "does", "did", "has", "have", "had", "can", "will", "would",
                "tell", "me", "about", "of", "in", "on", "at", "to", "for",
                "with", "and", "or", "not", "we", "our", "us", "i", "you",
                "they", "it", "its", "s", "that", "this", "there", "from",
            }
            keywords = [
                w.lower().rstrip("?,.:;!\"'")
                for w in query.split()
                if len(w.rstrip("?,.:;!\"'")) > 1
                and w.lower().rstrip("?,.:;!\"'") not in _STOPWORDS
            ]
            if keywords:
                rows = [
                    r for r in rows
                    if any(
                        kw in r.get("content", "").lower()
                        or kw in r.get("summary", "").lower()
                        for kw in keywords
                    )
                ]

        rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        results = rows[:limit]
        self._emit_event("search.performed", {
            "query": query,
            "result_count": len(results),
        }, workspace_id=workspace_id)
        return results


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
        """
        if semantic:
            # ── Query cache check ──
            cache_key: str | None = None
            if self._query_cache is not None:
                cache_key = self._query_cache.make_key(
                    workspace_id, query, limit, "semantic"
                )
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
                        f"{health_url}/health", timeout=2.0,
                    )
                    embedder_down = health.status_code >= 400
                except (httpx.ConnectError, httpx.TimeoutException):
                    embedder_down = True

            strategies_list = ["keyword", "graph", "temporal"]
            if not embedder_down:
                strategies_list.insert(0, "semantic")
            else:
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
                self._call("hybrid_search", [
                    workspace_id, search_query, emb_json,
                    memory_type, tier, fetch_limit, strategies,
                    polyphonic,
                    mmr_lambda,
                ])
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
                tantivy_rows.append({
                    "entity_id": th.get("entity_id", ""),
                    "entity_type": th.get("entity_type", "memory"),
                    "content": th.get("content", ""),
                    "score": float(th.get("score", 0.0)),
                    "strategy": "keyword",
                    "workspace_id": workspace_id,
                })

            # Compute min/max per strategy — but only on a capped subset.
            # Over-fetching dumps hundreds of low-score keyword matches
            # (0.125 per single-word hit) that collapse the min-max range.
            per_strat: dict[str, list[dict]] = {
                "keyword": [],  # Tantivy rows go here
                "semantic": [], "graph": [], "temporal": [], "binary": [],
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
                            binary_rows.append({
                                "entity_id": eid,
                                "entity_type": "memory",
                                "score": sim,
                                "strategy": "binary",
                                "workspace_id": workspace_id,
                            })
                    binary_rows.sort(key=lambda r: r["score"], reverse=True)
                    per_strat["binary"] = binary_rows[:fusion_limit]
                except (ValueError, Exception):
                    pass  # Binary scoring is best-effort

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
                rows, tantivy_rows, per_strat,
                strat_min, strat_max, STRATEGY_WEIGHTS,
            )

            # ── Look up content and apply veracity weighting ──
            rows = self._enrich_content(rows, workspace_id)

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
                    query, rows,
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
            self._emit_event("search.performed", {
                "query": query,
                "result_count": len(results),
            }, workspace_id=workspace_id)
            return results

        # Non-semantic (keyword) fallback
        return self._keyword_fallback(workspace_id, query, memory_type, tier, limit)

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

        import json as _json
        emb_json = _json.dumps(emb)
        self._call("search_sessions_semantic", [emb_json, limit])

        qhash = f"sessions:{limit}"
        rows = self._sql(
            "SELECT * FROM session_search_result "
            f"WHERE query_hash = '{_esc(qhash)}'"
        )
        rows.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        return rows[:limit]

    def get_memory(self, memory_id: str) -> list[dict[str, Any]]:
        """Get a single memory by ID.  Auto-reinforces on read."""
        results = self._query("memory", filter_dict={"id": memory_id})
        if results:
            try:
                self._call("reinforce_memory", [memory_id])
            except RuntimeError:
                pass
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
            ratio = SequenceMatcher(None, name.lower(), text.lower()).ratio()  # isjunk=None: treat all chars equally
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
        self, memory_id: str, content: str, summary: str = "", confidence: float = 0.8
    ) -> dict[str, Any]:
        """Update a memory's content/summary/confidence."""
        return self._call("update_memory", [memory_id, content, summary, confidence])

    def delete_memory(self, memory_id: str) -> dict[str, Any]:
        """Deactivate a memory. Idempotent — succeeds if already deleted."""
        # ── Look up workspace_id for cache invalidation ──
        ws_id: str | None = None
        if self._query_cache is not None:
            rows = self._sql(
                f"SELECT workspace_id FROM memory WHERE id = '{_esc(memory_id)}'"
            )
            if rows:
                ws_id = str(rows[0].get("workspace_id", ""))

        try:
            result = self._call("deactivate_memory", [memory_id])
            # ── Invalidate query cache ──
            if self._query_cache is not None and ws_id:
                self._query_cache.invalidate(workspace_id=ws_id)
            # ── Emit memory.deleted event ──
            self._emit_event("memory.deleted", {
                "memory_id": memory_id,
            }, workspace_id=ws_id or "")
            return result
        except RuntimeError as e:
            if "not found" in str(e).lower():
                return {"status": "ok", "note": "already deleted"}
            raise

    def set_workspace_context(self, workspace_id: str, context: str) -> dict[str, Any]:
        """Attach a context string to a workspace for QMD-style context trees."""
        return self._call("set_workspace_context", [workspace_id, context])

    def set_memory_context(self, memory_id: str, context: str) -> dict[str, Any]:
        """Attach a context string to a memory for QMD-style context trees."""
        return self._call("set_memory_context", [memory_id, context])

    def get_context_chain(self, memory_id: str) -> dict[str, Any]:
        """Return the context chain for a memory: workspace context + memory context."""
        mems = self._query("memory", filter_dict={"id": memory_id}, columns=["id", "workspace_id", "context"])
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

    def rate_memory(
        self, memory_id: str, rating: str, peer_id: str
    ) -> dict[str, Any]:
        """Rate a memory to adjust its trust score.

        Args:
            memory_id: The memory to rate.
            rating: "helpful" (score 5), "unhelpful" (score 1),
                    or an integer string "1"–"5" for graded feedback.
            peer_id: The peer submitting the rating.
        """
        return self._call("rate_memory", [memory_id, rating, peer_id])

    def escalate_memories(self, workspace_id: str, l2_to_l1: int = 5, l1_to_l0: int = 20) -> dict[str, Any]:
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

    def get_user_memories(
        self, user_scope: str, workspace_id: str
    ) -> list[dict[str, Any]]:
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
            "SELECT * FROM directory_result WHERE "
            f"query_hash = '{_esc(directory_id)}'"
        )

    def traverse_directory(self, workspace_id: str, root_directory_id: str) -> list[dict[str, Any]]:
        """Recursive BFS traversal of directory tree."""
        self._call("traverse_recursive", [workspace_id, root_directory_id])
        return self._sql(
            "SELECT * FROM directory_result WHERE "
            f"query_hash = '{_esc(root_directory_id)}'"
        )

    def get_directory(self, workspace_id: str, path_or_id: str) -> list[dict[str, Any]]:
        """Get a directory by ID or path."""
        self._call("get_directory", [workspace_id, path_or_id])
        return self._sql(
            "SELECT * FROM directory_result WHERE "
            f"workspace_id = '{_esc(workspace_id)}'"
        )

    def create_directory(self, workspace_id: str, name: str, path: str, parent_id: str = "", description: str = "") -> dict[str, Any]:
        """Create a directory in the context directory tree."""
        return self._call("create_directory", [workspace_id, name, path, parent_id, description])

    def link_memory_to_directory(self, directory_id: str, memory_id: str, workspace_id: str) -> dict[str, Any]:
        """Link a memory to a directory."""
        return self._call("link_memory_to_directory", [directory_id, memory_id, workspace_id])

    def unlink_memory_from_directory(self, directory_id: str, memory_id: str) -> dict[str, Any]:
        """Unlink a memory from a directory."""
        return self._call("unlink_memory_from_directory", [directory_id, memory_id])

    # -----------------------------------------------------------------------
    # Batch update & history (Mem0 parity)
    # -----------------------------------------------------------------------

    def batch_update_memories(self, workspace_id: str, memory_ids: list[str], updates: dict[str, Any]) -> dict[str, Any]:
        """Batch update multiple memories. Mem0 parity.
        updates can contain: content, summary, confidence, tier, is_active

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
                    filter_dict={"id": mem_id, "workspace_id": workspace_id},
                )
                if not current_rows:
                    errors.append(f"Memory '{mem_id}' not found")
                    continue
                current = current_rows[0]
                content = updates.get("content", current.get("content", ""))
                summary = updates.get("summary", current.get("summary", ""))
                confidence = updates.get("confidence", current.get("confidence", 0.8))
                self.update_memory(mem_id, content, summary, confidence)
                updated += 1
            except Exception as e:
                errors.append(f"Memory '{mem_id}': {e}")

        if errors:
            return {"status": "partial", "updated": updated, "errors": errors}
        return {"status": "ok", "updated": updated}

    def get_memory_history(self, memory_id: str) -> list[dict[str, Any]]:
        """Get version history for a memory. Mem0 parity.

        Returns the current state as a single-version history entry
        (SpacetimeDB doesn't store version snapshots).
        """
        rows = self._query("memory", filter_dict={"id": memory_id},
                          columns=["id", "content", "summary", "version", "updated_at", "confidence"])
        if rows:
            r = rows[0]
            return [{
                "version": r.get("version", 1),
                "content": r.get("content", ""),
                "summary": r.get("summary", ""),
                "confidence": r.get("confidence", 1.0),
                "updated_at": r.get("updated_at", 0),
            }]
        return []

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
            return self._call("apply_reputation_decay", [
                workspace_id, decay_rate, max_days,
            ])
        else:
            return self._call("apply_weibull_decay", [
                workspace_id, weibull_shape, weibull_scale,
            ])

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
        self._call("recommend_memories", [
            workspace_id, limit, min_urgency,
        ])
        # Public result table — queryable via SQL directly
        return self._sql(
            "SELECT * FROM memory_recommendation WHERE "
            f"workspace_id = '{_esc(workspace_id)}'"
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
        import json
        meta_json = json.dumps(metadata or {})
        return self._call("create_document", [
            workspace_id, title, content, content_type,
            file_path, source_url, meta_json,
        ])

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """Get a document by ID."""
        rows = self._query("document", filter_dict={"id": doc_id})
        if rows:
            return rows[0]
        return None

    def list_documents(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all documents in a workspace."""
        return self._query("document",
                          filter_dict={"workspace_id": workspace_id})

    def get_document_chunks(self, doc_id: str) -> list[dict[str, Any]]:
        """Get all chunks for a document, ordered by chunk_index."""
        rows = self._query("doc_chunk",
                          filter_dict={"document_id": doc_id})
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
        self._call("detect_bridge_nodes", [
            workspace_id, limit, min_communities,
        ])
        # Public result table — queryable via SQL directly
        return self._sql(
            "SELECT * FROM bridge_result WHERE "
            f"workspace_id = '{_esc(workspace_id)}'"
        )

    def compute_kg_stats(self, workspace_id: str) -> dict[str, Any] | None:
        """Compute knowledge graph statistics for a workspace.

        Returns a single stats row with node_count, edge_count,
        community_count, orphan_nodes, avg_degree, etc.
        """
        self._call("compute_kg_stats", [workspace_id])
        # Public result table — queryable via SQL directly
        rows = self._sql(
            "SELECT * FROM kg_stats_result WHERE "
            f"workspace_id = '{_esc(workspace_id)}'"
        )
        if rows:
            return rows[0]
        return None

    # -----------------------------------------------------------------------
    # Search with metadata/location filters (Honcho parity)
    # -----------------------------------------------------------------------

    def search_with_filters(self, workspace_id: str, query: str = "",
                             memory_type: str = "",
                             tier: str = "",
                             metadata_filter: str = "",
                             location_filter: str = "",
                             limit: int = 20) -> list[dict[str, Any]]:
        """Search with metadata and location filters. Honcho parity."""
        # For metadata/location filters, we do a keyword search first then filter in Python
        rows = self.search(workspace_id, query, memory_type, tier, limit, semantic=True)
        if metadata_filter:
            import json
            mf = json.loads(metadata_filter) if isinstance(metadata_filter, str) else metadata_filter
            filtered = []
            for r in rows:
                meta_str = r.get("metadata_json", "{}")
                try:
                    meta = json.loads(meta_str) if isinstance(meta_str, str) else meta_str
                except Exception:
                    meta = {}
                matches = all(meta.get(k) == v for k, v in mf.items())
                if matches:
                    filtered.append(r)
            rows = filtered[:limit]
        if location_filter:
            loc = location_filter.lower()
            rows = [r for r in rows if loc in r.get("content", "").lower() or loc in r.get("summary", "").lower()][:limit]
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
        result = self._call("create_node", [
            workspace_id, label, node_type, summary, metadata_json,
            source_memory_id,
        ])
        content = f"{label}: {summary}" if summary else label
        emb = self._embed(content)
        if emb:
            nodes = self._query("kg_node", workspace_id=workspace_id,
                               filter_dict={"label": label},
                               columns=["id"])
            if nodes:
                self._call("index_entity", [
                    workspace_id, "node", nodes[-1]["id"],
                    content, json.dumps(emb),
                ])
        return result

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
        return self._call("create_edge", [
            workspace_id, source_node_id, target_node_id,
            relation, weight, confidence, metadata_json,
            source_memory_id,
        ])

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
        return self._call("add_node_citation", [
            workspace_id, node_id, memory_id, description,
        ])

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
        return self._call("add_edge_citation", [
            workspace_id, edge_id, memory_id, description,
        ])

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
        self._call("get_citations", [
            workspace_id, entity_id, entity_type,
        ])
        result_key = "citation_result"
        rows = self._sql(
            "SELECT * FROM citation_result WHERE "
            f"entity_id = '{_esc(entity_id)}' "
            f"  AND entity_type = '{_esc(entity_type)}' "
        )
        return rows

    def query_graph(
        self, workspace_id: str, query: str = ""
    ) -> list[dict[str, Any]]:
        """Search KG nodes by label within a workspace."""
        rows = self._query("kg_node", workspace_id=workspace_id)
        if query:
            # Client-side filter (SpacetimeDB doesn't support LIKE)
            q = query.lower()
            rows = [
                r for r in rows
                if q in r.get("label", "").lower()
                or q in r.get("summary", "").lower()
            ]
        return rows

    def get_neighbors(self, node_id: str, workspace_id: str = "") -> list[dict[str, Any]]:
        """Get edges connected to a node within an optional workspace."""
        # Query both directions since _query doesn't support OR
        edges_src = self._query("kg_edge", workspace_id=workspace_id,
                                filter_dict={"source_node_id": node_id})
        edges_tgt = self._query("kg_edge", workspace_id=workspace_id,
                                filter_dict={"target_node_id": node_id})
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
            rows = self._query("kg_node", workspace_id=workspace_id,
                               filter_dict={"id": nid}, columns=["id", "label"])
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

    def dedup(self, workspace_id: str) -> dict[str, Any]:
        """Run dedup within a workspace."""
        return self._call("dedup_memories", [workspace_id])

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
        return self._call("upsert_profile", [
            peer_id, static_facts, dynamic_context, preferences, tags,
        ])

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

    def search_profiles(self, workspace_id: str, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search profiles by static_facts or dynamic_context (client-side filter)."""
        profiles = self.list_profiles(workspace_id)
        if query:
            q = query.lower()
            profiles = [
                r for r in profiles
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

    def compute_pagerank(self, workspace_id: str, damping: float = 0.85, max_iterations: int = 100) -> dict[str, Any]:
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
        import secrets
        import hashlib

        raw = secrets.token_bytes(32)
        api_key = "sk-" + raw.hex()
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        request_id = secrets.token_hex(16)

        self._call("create_api_key", [
            workspace_id, name, permissions, key_hash, request_id,
        ])

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
        return self._call("create_note", [
            workspace_id, title, content, note_date, embedding_json,
        ])

    def update_note(
        self,
        note_id: str,
        title: str = "",
        content: str = "",
        embed: bool = True,
    ) -> dict[str, Any]:
        """Update a note. Re-embeds if content changes and *embed* is True."""
        embedding_json = "[]"
        if embed and content.strip():
            emb = self._embed(content[:1024])
            if emb:
                embedding_json = json.dumps(emb)
        return self._call("update_note", [note_id, title, content, embedding_json])

    def delete_note(self, note_id: str) -> dict[str, Any]:
        """Delete a note and its backlinks."""
        return self._call("delete_note", [note_id])

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

    def shortest_path(self, workspace_id: str, source_id: str, target_id: str, max_hops: int = 6) -> None:
        """Shortest path between two nodes.
        Results in shortest_path_result table, ordered by step_order."""
        self._call("shortest_path", [workspace_id, source_id, target_id, max_hops])

    def get_neighbors_via_reducer(self, workspace_id: str, node_id: str) -> None:
        """Get immediate neighbours of a node.
        Results in graph_traversal_result table with depth=1."""
        self._call("get_neighbors", [workspace_id, node_id])

    # -------------------------------------------------------------------
    # Tours
    # -------------------------------------------------------------------

    def create_tour(self, workspace_id: str, title: str, description: str = "") -> None:
        """Create a new guided tour."""
        self._call("create_tour", [workspace_id, title, description])

    def add_tour_stop(self, tour_id: str, node_id: str, heading: str, description: str = "") -> None:
        """Add a stop to a tour."""
        self._call("add_tour_stop", [tour_id, node_id, heading, description])

    def delete_tour(self, tour_id: str) -> None:
        """Delete a tour and all its stops."""
        self._call("delete_tour", [tour_id])

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
        self._call("create_entity_link", [
            workspace_id, canonical_name, "[]", entity_type, description,
        ])

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
    ]

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
                        pass  # may be a duplicate or schema mismatch
                restored.append(table)
                total_restored += len(rows)
            except Exception:
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
        m = re.search(r'\[.*\]', content, re.DOTALL)
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
        cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
        m = re.search(r'\[.*\]', cleaned, re.DOTALL)
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
                except json.JSONDecodeError:
                    pass

    # Strategy 5: Dict wrapper — LLM returned {"scores": [...]} or similar
    if not parse_ok:
        m = re.search(r'\{.*\}', content, re.DOTALL)
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
        lines = [l.strip() for l in content.split("\n") if l.strip().startswith("{")]
        if lines:
            extracted = []
            for line in lines:
                try:
                    obj = json.loads(line.rstrip(","))
                    if isinstance(obj, dict) and "index" in obj:
                        extracted.append(obj)
                except json.JSONDecodeError:
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
                  or ``http://localhost:4000/v1``).
        model: Model name (default: env ``LLM_RERANK_MODEL`` or ``gpt-4o-mini``).
        api_key: API key (default: env ``LLM_RERANK_API_KEY`` or ``OPENAI_API_KEY``).
        top_k: Number of results to send for reranking (default 10).
        timeout: HTTP timeout in seconds (default 30).
    """
    if not results:
        return results

    # Resolve config
    endpoint = endpoint or os.getenv(
        "LLM_RERANK_ENDPOINT", "http://localhost:4000/v1"
    )
    model = model or os.getenv("LLM_RERANK_MODEL", "ds-deepseek-v4-flash")
    api_key = api_key or os.getenv("LLM_RERANK_API_KEY") or os.getenv("OPENAI_API_KEY", "")

    # Build candidate list
    candidates_text = "\n".join(
        f"[{i}] {r.get('content', '')[:500]}"
        for i, r in enumerate(results[:top_k])
    )
    prompt = _RERANK_PROMPT.format(query=query, candidates=candidates_text)

    try:
        # Retry with backoff for rate limits
        import time as _time
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
                    _time.sleep(2 ** attempt)
                    continue
                raise
            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.warning("LLM rerank rate-limited, retrying in %ds (attempt %d/3)", wait, attempt + 1)
                _time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        else:
            raise httpx.HTTPStatusError("429 rate limit after 3 retries", request=resp.request, response=resp)
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

    except (json.JSONDecodeError, httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning("LLM rerank failed, returning original results: %s", exc)

    return results
