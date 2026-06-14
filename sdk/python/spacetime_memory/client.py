"""Python client for spacetime-memory.

Provides a high-level Client class that wraps the SpacetimeDB HTTP SQL API,
the reducer-call endpoint, and embedder support (Rust ONNX sidecar + OpenAI
API fallback).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

import httpx

import logging
import re

if TYPE_CHECKING:
    from .local_embedder import LocalEmbedder

logger = logging.getLogger(__name__)

from .query_expansion import expand_query  # noqa: E402 — intentional late import

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

    - ``"local"`` — use the Rust ONNX sidecar (HTTP, default behaviour)
    - ``"python"`` — use the in-process Python ONNX embedder
      (requires ``onnxruntime`` and ``tokenizers`` — install via
      ``pip install 'spacetime-memory[local-embed]'``)
    - ``"openai"`` — use OpenAI's embeddings API
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
        embedder_type: str | None = None,
        timeout: float = 30.0,
        verbose: bool = False,
        token: str | None = None,
    ):
        self.host = host or os.environ.get("SPACETIMEDB_HOST", "localhost")
        self.port = str(port or os.environ.get("SPACETIMEDB_PORT", "3001"))
        self.database = database or os.environ.get(
            "SPACETIMEDB_DB", "c200e409f602c06527d0aa66dc2d05718a6b62c4c3317b5498951cea41782713"
        )
        self.embedder_url = (
            embedder_url
            or os.environ.get("EMBEDDER_URL", "http://localhost:9090")
        )
        self.tantivy_url = os.environ.get(
            "TANTIVY_URL", "http://localhost:9091"
        )
        self.embedder_type = (
            embedder_type
            or os.environ.get("EMBEDDER_TYPE") or self._default_embedder_type()
        )
        self.verbose = verbose
        self.token = token or os.environ.get("SPACETIMEDB_TOKEN")
        self.max_retries = int(os.environ.get("STMEM_MAX_RETRIES", "3"))
        self._circuit_breaker_threshold = int(os.environ.get("STMEM_CIRCUIT_THRESHOLD", "5"))
        self._circuit_breaker_reset_secs = float(os.environ.get("STMEM_CIRCUIT_RESET_SECS", "30.0"))
        self._consecutive_failures: int = 0
        self._circuit_open_until: float = 0.0
        self._metrics: Any = None  # Set via set_metrics_collector()
        self.request_id: str = os.urandom(4).hex()  # Unique per-client instance
        self._identity_token: str | None = None
        self._identity_established: bool = False

        base = f"http://{self.host}:{self.port}"
        self.sql_url = f"{base}/v1/database/{self.database}/sql"
        self.reducer_url = f"{base}/v1/database/{self.database}/call"
        self._http = httpx.Client(timeout=timeout)
        self._local_python_embedder: LocalEmbedder | None = None

    def _headers(self) -> dict[str, str]:
        """Return common HTTP headers, including auth if a token is set."""
        headers: dict[str, str] = {}
        # Use explicit JWT token if provided, otherwise use captured identity token
        auth_token = self.token or self._identity_token
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        return headers

    def _ensure_identity(self) -> None:
        """Establish a consistent identity with SpacetimeDB.

        Makes an anonymous request to capture the identity token
        from the response, then uses it for all subsequent calls.
        Only needed when no explicit JWT token is configured.
        """
        if self._identity_established or self.token:
            return
        try:
            resp = self._http.get(
                f"http://{self.host}:{self.port}/v1/database/{self.database}",
                timeout=5.0,
            )
            token = resp.headers.get("spacetime-identity-token", "")
            if token:
                self._identity_token = token
            self._identity_established = True
        except Exception:
            # If the handshake fails, proceed without identity
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
        except Exception:
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

        # All retries exhausted — trip circuit breaker
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
        return {"status": "ok"}

    @staticmethod
    def _default_embedder_type() -> str:
        """Choose a sensible default based on environment.
        If OPENAI_API_KEY is set, default to openai so the sidecar
        is not tried first on every store call.
        """
        if os.environ.get('OPENAI_API_KEY'):
            return 'openai'
        return 'auto'

    _DEFAULT_EMBEDDER_URL = 'http://localhost:9090'

    def _embed(self, text: str) -> list[float]:
        """Get an embedding vector.

        Behaviour depends on ``embedder_type``:
        - ``"local"``: use the Rust ONNX sidecar (raises on failure)
        - ``"python"``: use the in-process Python ONNX embedder
        - ``"openai"``: call OpenAI embeddings API
        - ``"auto"``: try sidecar first, fall back to OpenAI. If both fail,
          raises ``EmbedderUnavailableError`` with a combined message.
        """
        if self.embedder_type == "openai":
            return self._embed_openai(text)
        if self.embedder_type == "local":
            return self._embed_local(text)
        if self.embedder_type == "python":
            return self._embed_python(text)

        # "auto" — try local, fall back to OpenAI
        # Skip local trial when EMBEDDER_URL is the default and a cloud
        # API key is available — no point waiting for a connection timeout.
        if self.embedder_url == self._DEFAULT_EMBEDDER_URL and os.environ.get('OPENAI_API_KEY'):
            result = self._embed_openai(text)
            if result:
                return result
        try:
            return self._embed_local(text)
        except EmbedderUnavailableError:
            logger.info("Local embedder unavailable, falling back to OpenAI")
            result = self._embed_openai(text)
            if result:
                return result
            raise EmbedderUnavailableError(
                "Embedder unavailable (local sidecar down, OpenAI fallback also failed). "
                "Check EMBEDDER_URL and OPENAI_API_KEY."
            )

    # ── model detection ────────────────────────────────────────────────
    _bge_model_cache: bool | None = None
    _e5_model_cache: bool | None = None

    def _is_bge_model(self) -> bool:
        """Check if the embedder is running a BGE-family model (needs query instruction prefix)."""
        if self._bge_model_cache is not None:
            return self._bge_model_cache
        try:
            resp = self._http.get(f"{self.embedder_url}/health", timeout=2.0)
            if resp.status_code < 400:
                model = resp.json().get("model", "").lower()
                self._bge_model_cache = "bge" in model and "reranker" not in model
                return self._bge_model_cache
        except Exception:
            pass
        return False

    def _is_e5_model(self) -> bool:
        """Check if the embedder is running an E5-family model (needs 'query: ' prefix)."""
        if self._e5_model_cache is not None:
            return self._e5_model_cache
        try:
            resp = self._http.get(f"{self.embedder_url}/health", timeout=2.0)
            if resp.status_code < 400:
                model = resp.json().get("model", "").lower()
                self._e5_model_cache = "e5" in model
                return self._e5_model_cache
        except Exception:
            pass
        return False

    def _embed_local(self, text: str) -> list[float]:
        """Get an embedding vector via the Rust ONNX sidecar."""
        try:
            resp = self._http.post(
                f"{self.embedder_url}/embed",
                content=json.dumps({"text": text}),
                headers={"Content-Type": "application/json"},
                timeout=10.0,
            )
            if resp.status_code >= 400:
                raise EmbedderUnavailableError(
                    f"Embedder returned HTTP {resp.status_code} for text (len={len(text)})"
                )
            return resp.json().get("embedding", [])
        except httpx.TimeoutException:
            raise EmbedderUnavailableError(f"Embedder timed out for text (len={len(text)})")
        except httpx.ConnectError:
            raise EmbedderUnavailableError(
                f"Embedder connection refused at {self.embedder_url}. Is the sidecar running?"
            )
        except Exception:
            logger.exception("Unexpected error in _embed for text (len=%d)", len(text))
            raise

    def _embed_python(self, text: str) -> list[float]:
        """Get an embedding vector via the in-process Python ONNX embedder.

        Lazily initializes the :class:`LocalEmbedder` on first call.
        """
        return self._embed_batch_python([text])[0]

    def _embed_openai(self, text: str) -> list[float]:
        """Embed via OpenAI API."""
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
                    "dimensions": int(os.environ.get("EMBEDDING_DIMENSIONS", "3072")),
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["data"][0]["embedding"]
        except httpx.TimeoutException:
            logger.warning("OpenAI embedder timed out for text (len=%d)", len(text))
            return []
        except Exception:
            logger.exception("OpenAI embedder failed for text (len=%d)", len(text))
            return []

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for multiple texts.

        Behaviour follows ``embedder_type`` — see :meth:`_embed`.
        """
        if not texts:
            return []
        if self.embedder_type == "openai":
            return self._embed_batch_openai(texts)
        if self.embedder_type == "local":
            return self._embed_batch_local(texts)
        if self.embedder_type == "python":
            return self._embed_batch_python(texts)

        # "auto" — try local, fall back to OpenAI
        result = self._embed_batch_local(texts)
        if result:
            return result
        logger.info("Local embedder unavailable for batch, falling back to OpenAI")
        return self._embed_batch_openai(texts)

    def _embed_batch_local(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for multiple texts via the Rust ONNX sidecar."""
        if not texts:
            return []
        try:
            resp = self._http.post(
                f"{self.embedder_url}/embed",
                content=json.dumps({"text": "", "texts": texts}),
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )
            if resp.status_code >= 400:
                logger.warning(
                    "Embedder returned HTTP %d for batch (count=%d): %s",
                    resp.status_code, len(texts), resp.text[:200],
                )
                return []
            return resp.json().get("embeddings", [])
        except httpx.TimeoutException:
            logger.warning("Embedder timed out for batch (count=%d)", len(texts))
            return []
        except httpx.ConnectError:
            logger.warning("Embedder connection refused for batch (count=%d) — is the sidecar running?", len(texts))
            return []
        except Exception:
            logger.exception("Unexpected error in _embed_batch (count=%d)", len(texts))
            return []

    def _embed_batch_python(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for multiple texts via the in-process Python ONNX embedder.

        Lazily initializes the :class:`LocalEmbedder` on first call.
        """
        if not texts:
            return []
        from .local_embedder import LocalEmbedder

        if self._local_python_embedder is None:
            self._local_python_embedder = LocalEmbedder()
        return self._local_python_embedder.embed_batch(texts)

    def _embed_batch_openai(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for multiple texts via OpenAI API."""
        if not texts:
            return []
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
                    "dimensions": int(os.environ.get("EMBEDDING_DIMENSIONS", "3072")),
                },
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
        except Exception:
            logger.exception("OpenAI embedder failed for batch (count=%d)", len(texts))
            return []

    def check_embedder_health(self) -> dict[str, Any]:
        """Check if the embedder sidecar is running. Returns status info."""
        try:
            resp = self._http.get(f"{self.embedder_url}/health", timeout=5.0)
            if resp.status_code == 200:
                embedder_status = resp.json()
                embedder_status["reachable"] = True
                return embedder_status
            return {"status": "error", "code": resp.status_code, "reachable": True}
        except Exception as e:
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
        except Exception:
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
        except Exception:
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
        except Exception as e:
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
    ) -> dict[str, Any]:
        """Store a memory. Auto-indexes via the embedder."""
        result = self._call("store_memory", [
            workspace_id, peer_id, observer_id,
            memory_type, content, summary, entities_json,
            confidence, source_session_id, source_message_id,
        ])

        # Auto-index
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
        entities = llm.extract_entities_llm(content)

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
        cross_encoder: bool = False,
        query_expansion: bool = False,
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
            cross_encoder: If True, passes top results through a local ONNX
                    cross-encoder (ms-marco-MiniLM-L-6-v2) before LLM rerank.
            query_expansion: If True, expands the query with synonyms and
                    related terms via LLM before searching.
        """
        if semantic:
            # ── Query expansion (pre-search) ──
            search_query = query
            if query_expansion and query:
                search_query = expand_query(query)
                # If expansion returned gibberish, fall back
                if not search_query or len(search_query.strip()) < 3:
                    search_query = query

            # BGE models need query instruction prefix for asymmetric search.
            # E5 models need "query: " prefix.
            query_text = search_query
            if self._is_bge_model():
                query_text = f"Represent this sentence for searching relevant passages: {search_query}"
            elif self._is_e5_model():
                query_text = f"query: {search_query}"
            emb = self._embed(query_text)
            emb_json = json.dumps(emb) if emb else "[]"

            # Check embedder health — if down, exclude semantic strategy and warn
            embedder_down = not emb
            if not embedder_down and emb:
                # Double-check: try a health ping
                try:
                    health = self._http.get(
                        f"{self.embedder_url}/health", timeout=2.0,
                    )
                    embedder_down = health.status_code >= 400
                except Exception:
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

            self._call("hybrid_search", [
                workspace_id, search_query, emb_json,
                memory_type, tier, fetch_limit, strategies,
            ])
            qhash = _query_hash(search_query)
            rows = self._sql(
                "SELECT * FROM hybrid_result "
                f"WHERE workspace_id = '{_esc(workspace_id)}' "
                f"  AND query_hash = '{_esc(qhash)}' "
            )

            # ── Weighted min-max fusion ──
            # Normalize each strategy to [0,1] via min-max, then weighted sum.
            # Semantic (0.65): strongest signal — now backed by bge-large-en-v1.5
            #   (1024-dim, +4 MTEB over MiniLM).
            # Keyword (0.25): Tantivy's real Okapi BM25 with stemming + IDF.
            # Graph (0.05), temporal (0.05): supporting signals — low weight
            #   because graph is substring-matching and temporal is recency-only.
            STRATEGY_WEIGHTS = {
                "semantic": 0.65,
                "keyword": 0.25,
                "graph": 0.05,
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
                "semantic": [], "graph": [], "temporal": [],
            }

            # Sort Tantivy rows by score desc, take top fusion_limit
            tantivy_rows.sort(key=lambda r: r["score"], reverse=True)
            per_strat["keyword"] = tantivy_rows[:fusion_limit]

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

            # Fuse: take the BEST normalized score per strategy per entity,
            # then weighted sum.  (Don't sum all rows — an entity can appear
            # in many keyword rows for different term matches.)
            best_per_strat: dict[str, dict[str, float]] = {
                "semantic": {}, "keyword": {}, "graph": {}, "temporal": {},
            }
            best_row: dict[str, dict] = {}
            # Include both STDB rows and Tantivy keyword rows in normalization
            all_rows = list(rows)
            for tr in tantivy_rows:
                # Only add Tantivy row if entity not already covered by STDB
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

            # Weighted sum of best per-strategy normalized scores
            fused: dict[str, float] = {}
            for eid in set().union(*(d.keys() for d in best_per_strat.values())):
                total = 0.0
                for s, w in STRATEGY_WEIGHTS.items():
                    total += best_per_strat[s].get(eid, 0.0) * w
                fused[eid] = total

            # Deduplicate: keep best row per entity, tag with fused score
            seen: dict[str, dict] = {}
            for r in all_rows:
                eid = r.get("entity_id", "")
                fs = fused.get(eid, 0.0)
                r["fused_score"] = fs
                if eid not in seen or fs > seen[eid].get("fused_score", float("-inf")):
                    seen[eid] = r

            rows = list(seen.values())
            rows.sort(key=lambda r: r.get("fused_score", 0.0), reverse=True)

            # Look up content from source tables in Python
            mem_ids = [r.get("entity_id", "") for r in rows if r.get("entity_type") == "memory"]
            node_ids = [r.get("entity_id", "") for r in rows if r.get("entity_type") == "node"]
            mem_map = {}
            node_map = {}
            for mid in mem_ids:
                mems = self._query("memory", filter_dict={"id": mid},
                                   workspace_id=workspace_id,
                                   columns=["id", "content"])
                if mems:
                    mem_map[mid] = mems[0].get("content", "")
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
                # Surface fused_score as the canonical score for consumers
                r["score"] = r.get("fused_score", r.get("score", 0.0))
            if cross_encoder:
                from .cross_encoder import cross_encoder_rerank
                rows = cross_encoder_rerank(query, rows, top_k=len(rows))
            if rerank:
                rows = llm_rerank(
                    query, rows,
                    endpoint=rerank_endpoint,
                    model=rerank_model,
                    api_key=rerank_api_key,
                    top_k=min(20, len(rows)),
                )
            return rows[:limit]

        # Non-semantic (keyword) fallback
        # SpacetimeDB SQL doesn't support LIKE, so we fetch all and filter client-side
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

        # Client-side keyword filter (SpacetimeDB doesn't support LIKE)
        if query:
            q = query.lower()
            rows = [
                r for r in rows
                if q in r.get("content", "").lower()
                or q in r.get("summary", "").lower()
            ]

        rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        return rows[:limit]

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
        try:
            return self._call("deactivate_memory", [memory_id])
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
            f"workspace_id = '{_esc(workspace_id)}' "
            "ORDER BY created_at DESC"
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
            f"query_hash = '{_esc(directory_id)}' "
            "ORDER BY depth ASC, name ASC"
        )

    def traverse_directory(self, workspace_id: str, root_directory_id: str) -> list[dict[str, Any]]:
        """Recursive BFS traversal of directory tree."""
        self._call("traverse_recursive", [workspace_id, root_directory_id])
        return self._sql(
            "SELECT * FROM directory_result WHERE "
            f"query_hash = '{_esc(root_directory_id)}' "
            "ORDER BY depth ASC, name ASC"
        )

    def get_directory(self, workspace_id: str, path_or_id: str) -> list[dict[str, Any]]:
        """Get a directory by ID or path."""
        self._call("get_directory", [workspace_id, path_or_id])
        return self._sql(
            "SELECT * FROM directory_result WHERE "
            f"workspace_id = '{_esc(workspace_id)}' "
            "ORDER BY depth ASC"
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
        """
        return self._call("batch_update_memories", [
            workspace_id, json.dumps(memory_ids), json.dumps(updates)
        ])

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
                except RuntimeError:
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
    ) -> dict[str, Any]:
        """Create a knowledge-graph node and auto-index it."""
        result = self._call("create_node", [
            workspace_id, label, node_type, summary, metadata_json,
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
    ) -> dict[str, Any]:
        """Create a directed, typed edge between two KG nodes."""
        return self._call("create_edge", [
            workspace_id, source_node_id, target_node_id,
            relation, weight, confidence, metadata_json,
        ])

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
            "AND operation = 'create' "
            "ORDER BY created_at DESC LIMIT 1"
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
            "AND operation = 'list' "
            "ORDER BY created_at DESC"
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
            except RuntimeError:
                continue

        return {
            "status": "ok",
            "input_path": input_path,
            "tables": restored,
            "total_rows": total_restored,
        }


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

_RERANK_PROMPT = """You are a search result relevance judge. Given a query and \
a list of candidate search results, assign each a relevance score from 1-10.

Scoring:
  10 — perfectly answers the query, exact match
  7-9 — highly relevant, contains key information
  4-6 — partially relevant, related concepts
  1-3 — barely relevant, tangential mention

Query: {query}

Candidates:
{candidates}

Return ONLY a JSON array in this exact format, no other text:
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
    model = model or os.getenv("LLM_RERANK_MODEL", "gpt-4o-mini")
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
        for attempt in range(3):
            resp = httpx.post(
                f"{endpoint.rstrip('/')}/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a search reranker. Return only JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 2048,
                },
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                timeout=timeout,
            )
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
        scores: list[dict] = []
        parse_ok = False
        errors = []

        # Strategy 1: Direct parse
        try:
            scores = json.loads(content)
            if isinstance(scores, list):
                parse_ok = True
        except json.JSONDecodeError as e:
            errors.append(f"direct: {e}")

        # Strategy 2: Find JSON array boundaries
        if not parse_ok:
            import re
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
                # Might be a single dict, wrap in list
                if isinstance(scores, dict):
                    scores = [scores]
                if isinstance(scores, list):
                    parse_ok = True
            except json.JSONDecodeError as e:
                errors.append(f"strict_false: {e}")

        # Strategy 4: Aggressive salvage — strip trailing commas, fix unquoted keys
        if not parse_ok:
            import re as _re
            cleaned = content
            # Remove trailing commas before closing brackets/braces
            cleaned = _re.sub(r',\s*([}\]])', r'\1', cleaned)
            # Try to extract any JSON array
            m = _re.search(r'\[.*\]', cleaned, _re.DOTALL)
            if m:
                try:
                    scores = json.loads(m.group())
                    if isinstance(scores, dict):
                        scores = [scores]
                    if isinstance(scores, list):
                        parse_ok = True
                except json.JSONDecodeError as e:
                    errors.append(f"salvage_array: {e}")
            
            if not parse_ok:
                # Last resort: try to find any JSON object and wrap it
                m = _re.search(r'\{.*?\}.*?\"score\"', cleaned, _re.DOTALL)
                if m:
                    try:
                        # Try parsing as a dict directly
                        obj = json.loads(m.group().rstrip('"score"').rstrip(','))
                        if isinstance(obj, dict):
                            scores = [obj]
                            parse_ok = True
                    except json.JSONDecodeError:
                        pass

        if not parse_ok:
            raise ValueError(f"JSON parse failed after 3 strategies: {'; '.join(errors[-2:])}")

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

    except Exception as exc:
        logger.warning("LLM rerank failed, returning original results: %s", exc)

    return results
