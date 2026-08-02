"""Embedder and Tantivy BM25 sidecar mixin — extracted from _base.py.

Provides ClientBase with embedding infrastructure and Tantivy BM25
keyword-search sidecar connectivity.
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from collections import OrderedDict
from typing import Any

import httpx

from ._base import SpacetimeDBError

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

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class EmbedderMixin:
    """Embedding and Tantivy BM25 sidecar mixin.

    Provides Client methods for embedding via local embedder proxy (bge-m3)
    with OpenAI fallback, and Tantivy BM25 full-text indexing/search.
    Inherits from ClientBase for connection infrastructure.
    """

    _DEFAULT_EMBEDDER_URL = "http://127.0.0.1:9090/v1"

    # ── Query embedding cache (avoids redundant ~350ms embedder calls) ──
    # NOTE: this is deliberately an instance attribute (lazily initialized in
    # _get_embed_cache()). A class-level cache would be SHARED across every
    # Client instance — embedding lookups for one workspace/account would leak
    # into another, and tests that embed the same text would observe cache hits
    # from unrelated earlier tests (order-dependent failures). See
    # sdk/python/tests/test_identity_resilience.py for the regression guard.
    _EMBED_CACHE_MAX_SIZE = 256
    _EMBED_CACHE_TTL_SECS = 300  # 5 minutes

    def _get_embed_cache(self) -> "OrderedDict[str, tuple[float, list[float]]]":
        """Return this instance's embedding cache, creating it on first use."""
        if not hasattr(self, "_embed_cache"):
            self._embed_cache: OrderedDict[str, tuple[float, list[float]]] = OrderedDict()
        return self._embed_cache

    # ── Embedding ──────────────────────────────────────────────────

    def _embed(self, text: str) -> list[float]:
        """Get an embedding vector, trying the local embedder first.

        Uses an LRU query-embedding cache (TTL 5 min, max 256 entries)
        to avoid redundant ~350ms embedder calls for repeated queries.
        Cache is keyed by the normalized query text so semantically
        identical queries reuse embeddings.

        Tries the local bge-m3 embedder service at ``self.embedder_url``
        (default port 4000).  Falls back to OpenAI if the local embedder
        is unreachable or returns errors.
        """
        with _tracing_span("embed", text_length=len(text)):
            # ── Query embedding cache check ──
            cache_key = text.strip().lower()
            now = time.time()
            cache = self._get_embed_cache()
            cached = cache.get(cache_key)
            if cached is not None:
                ts, vec = cached
                if now - ts < self._EMBED_CACHE_TTL_SECS:
                    logger.debug("Embedding cache hit for '%s'", cache_key[:40])
                    self._init_embedder_counters()
                    self._embedder_total_calls += 1
                    return vec
                # Expired — remove
                del cache[cache_key]

            self._init_embedder_counters()
            self._embedder_total_calls += 1
            # Try local embedder first
            result = self._embed_local(text)
            if result:
                self._clear_embedder_errors()
                # Cache result
                cache[cache_key] = (now, result)
                while len(cache) > self._EMBED_CACHE_MAX_SIZE:
                    cache.popitem(last=False)
                return result
            # Local embedder failed — record error and fall back to OpenAI
            self._embedder_total_errors += 1
            self._record_embedder_error()
            self._check_error_rate_alert()
            result = self._embed_openai(text)
            if result:
                # Cache the fallback result too
                cache[cache_key] = (now, result)
                while len(cache) > self._EMBED_CACHE_MAX_SIZE:
                    cache.popitem(last=False)
                return result
            # Both failed
            self._embedder_total_errors += 1
            self._record_embedder_error()
            self._check_error_rate_alert()
            return []

    def _embed_local(self, text: str) -> list[float] | None:
        """Embed via the local bge-m3 proxy at ``self.embedder_url``.

        Returns the embedding vector on success, or ``None`` if the
        local embedder is unreachable / returns an error (so callers
        can fall back to OpenAI).  Returns ``None`` (not []) so code
        paths can distinguish "local embedder unreachable" from
        "empty embedding returned by the API".

        The endpoint is expected to be OpenAI-compatible (POST /embeddings).
        """
        with _tracing_span("embed.local", text_length=len(text)):
            url = getattr(self, "embedder_url", self._DEFAULT_EMBEDDER_URL)
            try:
                resp = self._request_with_retry_simple(
                    "POST",
                    f"{url}/embeddings",
                    headers={"Content-Type": "application/json"},
                    json={
                        "input": text,
                        "model": os.environ.get("EMBEDDER_LOCAL_MODEL", "BAAI/bge-m3"),
                    },
                    timeout=30,
                )
                if resp is None:
                    logger.warning("Local embedder unreachable at %s — will fall back", url)
                    return None
                resp.raise_for_status()
                data = resp.json()
                return data["data"][0]["embedding"]
            except httpx.TimeoutException:
                logger.warning("Local embedder timed out at %s", url)
                return None
            except (httpx.ConnectError, httpx.RemoteProtocolError):
                logger.warning("Local embedder connection failed at %s — will fall back", url)
                return None
            except (json.JSONDecodeError, httpx.HTTPError, KeyError, IndexError, ValueError):
                logger.exception("Local embedder returned invalid response at %s", url)
                return None

    def _embed_openai(self, text: str) -> list[float]:
        """Embed via OpenAI API."""
        with _tracing_span("embed.openai", text_length=len(text)):
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                logger.warning("OPENAI_API_KEY not set, cannot use OpenAI embedder fallback")
                return []
            try:
                base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
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
        """Get embeddings for multiple texts, trying the local embedder first.

        Tries the local bge-m3 embedder service at ``self.embedder_url``
        first.  Falls back to OpenAI if the local embedder is unreachable
        or returns errors.

        Records embedder errors through the metrics collector and
        emits a CRITICAL-level alert when consecutive failures
        exceed the threshold (STMEM_EMBEDDER_ALERT_THRESHOLD, default 3).

        Also tracks total calls and errors for time-window error-rate
        alerting pushed to SpacetimeDB.
        """
        if not texts:
            return []
        with _tracing_span("embed.batch", batch_size=len(texts)):
            self._init_embedder_counters()
            self._embedder_total_calls += 1
            # Try local embedder first
            result = self._embed_batch_local(texts)
            if result:
                self._clear_embedder_errors()
                return result
            # Local embedder failed — record error and fall back to OpenAI
            self._embedder_total_errors += 1
            self._record_embedder_error()
            self._check_error_rate_alert()
            result = self._embed_batch_openai(texts)
            if result:
                return result
            # Both failed — record a second error for the OpenAI failure too
            self._embedder_total_errors += 1
            self._record_embedder_error()
            self._check_error_rate_alert()
            return []

    def _embed_batch_local(self, texts: list[str]) -> list[list[float]] | None:
        """Embed multiple texts via the local bge-m3 proxy.

        For large batches (>100 items), returns None immediately to avoid
        multi-minute CPU embedding time. Small batches (<100) are processed
        in chunks of 25 with per-chunk timeout.

        Returns a list of embedding vectors on success, or ``None``
        if the local embedder is unavailable or the batch is too large.
        """
        if not texts:
            return []
        # Skip embedding for large batches — takes too long on CPU embedder.
        # Memory storage and BM25 keyword indexing work without embeddings.
        if len(texts) > 100:
            logger.info("store_batch: skipping embed for %d items (batch too large, keyword-only)", len(texts))
            return None
        with _tracing_span("embed.batch.local", batch_size=len(texts)):
            url = getattr(self, "embedder_url", self._DEFAULT_EMBEDDER_URL)
            # Chunk to avoid timeouts on slow CPU embedder
            chunk_size = 25
            all_embeddings: list[list[float]] = []
            for start in range(0, len(texts), chunk_size):
                chunk = texts[start:start + chunk_size]
                try:
                    resp = self._request_with_retry_simple(
                        "POST",
                        f"{url}/embeddings",
                        headers={"Content-Type": "application/json"},
                        json={
                            "input": chunk,
                            "model": os.environ.get("EMBEDDER_LOCAL_MODEL", "BAAI/bge-m3"),
                        },
                        timeout=120,  # generous per-chunk timeout
                    )
                    if resp is None:
                        logger.warning("Local embedder unreachable for chunk at %s", url)
                        return None
                    resp.raise_for_status()
                    data = resp.json()
                    all_embeddings.extend(item["embedding"] for item in data["data"])
                except httpx.TimeoutException:
                    logger.warning("Local embedder timed out for chunk at %s", url)
                    return None
                except (httpx.ConnectError, httpx.RemoteProtocolError):
                    logger.warning("Local embedder connection failed for chunk at %s", url)
                    return None
                except (json.JSONDecodeError, httpx.HTTPError, KeyError, IndexError, ValueError):
                    logger.exception("Local embedder returned invalid chunk response at %s", url)
                    return None
            return all_embeddings

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
                base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
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
                results = [item["embedding"] for item in data["data"]]
                return results
            except httpx.TimeoutException:
                logger.warning("OpenAI embedder timed out for batch (count=%d)", len(texts))
                return []
            except (json.JSONDecodeError, httpx.HTTPError, KeyError, IndexError, ValueError):
                logger.exception("OpenAI embedder failed for batch (count=%d)", len(texts))
                return []

    # ── Health checks ──────────────────────────────────────────────

    def _init_embedder_counters(self) -> None:
        """Lazy-initialize embedder total-call and error counters.

        Called by _embed and _embed_batch on first invocation so the
        counters work even when EmbedderMixin is used standalone (no
        ClientBase.__init__).  Also sets up the rate-window timestamp
        list for time-window-based error rate alerting.
        """
        if not hasattr(self, "_embedder_total_calls"):
            self._embedder_total_calls: int = 0
            self._embedder_total_errors: int = 0
            self._embedder_error_timestamps: list[float] = []
            self._embedder_rate_window_secs: int = int(
                os.environ.get("STMEM_EMBEDDER_RATE_WINDOW_SECS", "300")
            )
            self._embedder_rate_alert_threshold_pct: float = float(
                os.environ.get("STMEM_EMBEDDER_RATE_ALERT_THRESHOLD_PCT", "50.0")
            )
            self._embedder_rate_alerted: bool = False

    def _record_embedder_error(self) -> None:
        """Record an embedder failure, incrementing the consecutive-failure
        counter and logging a CRITICAL alert when the threshold is exceeded.

        Also records the error through the metrics collector if available,
        and prunes stale error timestamps from the rate-window list.
        """
        now = time.time()
        # Lazy-init tracking state (supports direct EmbedderMixin testing)
        if not hasattr(self, '_embedder_consecutive_failures'):
            self._embedder_consecutive_failures = 0
            self._embedder_last_failure_ts = 0.0
            self._embedder_alert_threshold = int(
                os.environ.get('STMEM_EMBEDDER_ALERT_THRESHOLD', '3')
            )
            self._embedder_was_degraded = False
            self._embedder_alerted = False
        self._embedder_consecutive_failures += 1
        self._embedder_last_failure_ts = now

        # Prune stale timestamps and append the error timestamp for rate window
        if hasattr(self, '_embedder_error_timestamps'):
            cutoff = now - getattr(self, '_embedder_rate_window_secs', 300)
            self._embedder_error_timestamps = [
                ts for ts in self._embedder_error_timestamps if ts >= cutoff
            ]
            self._embedder_error_timestamps.append(now)

        # Record through metrics collector
        try:
            m = getattr(self, "_metrics", None)
            if m is not None:
                m.record_embedder_error()
        except (SpacetimeDBError, httpx.HTTPError):
            pass

        # Alert when consecutive failures exceed threshold
        if self._embedder_consecutive_failures >= self._embedder_alert_threshold:
            if not self._embedder_alerted:
                self._embedder_alerted = True
                self._embedder_was_degraded = True
                self._push_embedder_alert(
                    severity=2,  # critical
                    message=(
                        f"Local embedder has failed {self._embedder_consecutive_failures} consecutive times "
                        f"(threshold={self._embedder_alert_threshold}) — "
                        f"SDK has fallen back to OpenAI. "
                        f"Check the embedder service at {self.embedder_url}"
                    ),
                    degraded=True,
                    recovery=False,
                )
            logger.critical(
                "Local embedder has failed %d consecutive times (threshold=%d) — "
                "SDK has fallen back to OpenAI. "
                "Check the embedder service at %s",
                self._embedder_consecutive_failures,
                self._embedder_alert_threshold,
                self.embedder_url,
            )
        else:
            logger.warning(
                "Local embedder failure #%d — SDK will use OpenAI fallback. "
                "Alert threshold: %d consecutive failures.",
                self._embedder_consecutive_failures,
                self._embedder_alert_threshold,
            )

    def _clear_embedder_errors(self) -> None:
        """Reset the consecutive-failure counter on a successful embedder call.

        Pushes a recovery alert to SpacetimeDB if the embedder was previously
        in degraded state, so dashboards and alerting systems can track
        uptime.
        """
        consecutive = getattr(self, '_embedder_consecutive_failures', 0)
        was_degraded = getattr(self, '_embedder_was_degraded', False)
        # Always reset the rate-alerted flag on any clear, even if
        # consecutive_failures is 0 (rate alerts can fire independently
        # via _check_error_rate_alert).
        self._embedder_rate_alerted = False
        if consecutive > 0:
            logger.info(
                'Embedder recovered after %d consecutive failures — resetting error counter.',
                consecutive,
            )
            self._embedder_consecutive_failures = 0
            self._embedder_last_failure_ts = 0.0
            # Record recovery through metrics collector
            try:
                m = getattr(self, "_metrics", None)
                if m is not None:
                    m.record_embedder_recovery()
            except (SpacetimeDBError, httpx.HTTPError):
                pass
            if was_degraded:
                self._embedder_was_degraded = False
                self._embedder_alerted = False
                self._push_embedder_alert(
                    severity=0,  # recovery
                    message=(
                        f"Local embedder has recovered after {consecutive} consecutive failures — "
                        f"resuming normal operation."
                    ),
                    degraded=False,
                    recovery=True,
                )

    def _push_embedder_alert(
        self,
        severity: int,
        message: str,
        degraded: bool,
        recovery: bool,
    ) -> None:
        """Push an embedder alert event to SpacetimeDB.

        Calls the ``push_embedder_alert`` reducer to record the alert
        so dashboards and alerting systems can track embedder health
        over time.

        Computes the actual error rate percentage from the tracked
        total calls and errors, instead of passing a placeholder 0.0.

        Args:
            severity: 0=recovery, 1=warning, 2=critical.
            message: Human-readable alert message.
            degraded: Whether the embedder is currently degraded.
            recovery: Whether this is a recovery event.
        """
        total_calls = getattr(self, '_embedder_total_calls', 0)
        total_errors = getattr(self, '_embedder_total_errors', 0)
        error_rate_pct = 0.0
        if total_calls > 0:
            error_rate_pct = round(total_errors / total_calls * 100, 2)
        try:
            self._call("push_embedder_alert", [
                severity,
                message,
                getattr(self, '_embedder_consecutive_failures', 0),
                total_calls,
                total_errors,
                error_rate_pct,
                degraded,
                recovery,
                not degraded,  # reachable = not degraded (approximation)
                getattr(self, 'embedder_url', 'unknown'),
            ])
        except (SpacetimeDBError, httpx.HTTPError):
            logger.warning("Failed to push embedder alert to SpacetimeDB", exc_info=True)

    def _check_error_rate_alert(self) -> None:
        """Check embedder error rate within the configured time window.

        If the error rate (errors / total calls) exceeds the configured
        threshold percentage, pushes a WARNING-level alert to SpacetimeDB
        (deduplicated — only fires once per degradation episode).

        Environment variables:
            STMEM_EMBEDDER_RATE_WINDOW_SECS (default: 300)
            STMEM_EMBEDDER_RATE_ALERT_THRESHOLD_PCT (default: 50.0)
        """
        threshold_pct = getattr(self, '_embedder_rate_alert_threshold_pct', 50.0)
        total_calls = getattr(self, '_embedder_total_calls', 0)
        total_errors = getattr(self, '_embedder_total_errors', 0)
        if total_calls == 0:
            return
        rate_pct = round(total_errors / total_calls * 100, 2)
        if rate_pct >= threshold_pct and total_errors >= 3:
            if not getattr(self, '_embedder_rate_alerted', False):
                self._embedder_rate_alerted = True
                self._push_embedder_alert(
                    severity=1,  # warning
                    message=(
                        f"Embedder error rate {rate_pct}% ({total_errors} errors "
                        f"in {total_calls} calls) exceeds threshold "
                        f"{threshold_pct}% — SDK embeddings are degraded. "
                        f"Check the embedder service at {self.embedder_url}"
                    ),
                    degraded=True,
                    recovery=False,
                )
                logger.warning(
                    "Embedder error rate %.1f%% (%d/%d) exceeds threshold %.1f%% — "
                    "pushed rate alert to SpacetimeDB.",
                    rate_pct, total_errors, total_calls, threshold_pct,
                )

    def check_embedder_health(self) -> dict[str, Any]:
        """Check if the embedder sidecar is running. Returns status info."""
        with _tracing_span("embedder.health"):
            # Include embedder degradation tracking in health output
            consecutive = getattr(self, '_embedder_consecutive_failures', 0)
            threshold = getattr(self, '_embedder_alert_threshold', 3)
            info: dict[str, Any] = {
                'consecutive_failures': consecutive,
                'alert_threshold': threshold,
                'openai_fallback_active': consecutive >= threshold,
            }
            last_ts = getattr(self, '_embedder_last_failure_ts', 0.0)
            if consecutive > 0 and last_ts > 0:
                info['last_failure_seconds_ago'] = round(time.time() - last_ts, 1)
            if consecutive >= threshold:
                info['degraded'] = True
                info['degradation_warning'] = (
                    f'Local embedder has failed {consecutive} consecutive times — '
                    'SDK has fallen back to OpenAI. Semantic search results may differ '
                    '(different embedding model) until the local embedder recovers.'
                )
            try:
                resp = self._request_with_retry_simple(
                    "GET", f"{self.embedder_url}/health", timeout=5.0
                )
                if resp is None:
                    info["status"] = "error"
                    info["message"] = "Embedder unreachable after retries"
                    info["reachable"] = False
                    return info
                if resp.status_code == 200:
                    embedder_status = resp.json()
                    embedder_status["reachable"] = True
                    embedder_status.update(info)
                    return embedder_status
                info["status"] = "error"
                info["code"] = resp.status_code
                info["reachable"] = True
                return info
            except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as e:
                info["status"] = "error"
                info["message"] = str(e)
                info["reachable"] = False
                return info

    def check_tantivy_health(self) -> dict[str, Any]:
        """Check if the Tantivy BM25 sidecar is running (port 9091). Returns status info."""
        with _tracing_span("tantivy.health"):
            try:
                resp = self._request_with_retry_tantivy(
                    "GET", f"{self.tantivy_url}/health", timeout=5.0
                )
                if resp.status_code == 200:
                    status = resp.json()
                    status["reachable"] = True
                    return status
                return {"status": "error", "code": resp.status_code, "reachable": True}
            except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError, RuntimeError) as e:
                return {"status": "error", "message": str(e), "reachable": False}

    # ── External request helpers (no STDB circuit breaker) ────────

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

    def _request_with_retry_tantivy(
        self, method: str, url: str, **kwargs: Any
    ) -> httpx.Response:
        """Same as ``_request_with_retry`` but with an isolated circuit breaker.

        Tantivy BM25 sidecar failures must NOT trip the STDB circuit breaker.
        Same retry logic (exponential backoff + jitter), but uses dedicated
        ``_tantivy_circuit_open_until`` / ``_tantivy_consecutive_failures``
        state so Tantivy blips don't block STDB requests.
        """
        now = time.time()
        if self._tantivy_circuit_open_until > now:
            raise RuntimeError(
                f"Tantivy circuit breaker is open "
                f"(retry in {self._tantivy_circuit_open_until - now:.0f}s). "
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
                code = int(getattr(resp, "status_code", 500))
                if code < 500 or code >= 600 or code == 530:
                    self._tantivy_consecutive_failures = 0
                    self._tantivy_circuit_open_until = 0.0
                    return resp
                last_exc = RuntimeError(f"Tantivy server error (HTTP {code}) on {url}")
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_exc = e
            except httpx.RemoteProtocolError as e:
                last_exc = e
            if attempt < self.max_retries:
                delay = 0.5 * (2**attempt) * (1 + random.random())
                logger.warning(
                    "Tantivy request failed (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1,
                    self.max_retries + 1,
                    last_exc,
                    delay,
                )
                time.sleep(delay)

        # All retries exhausted — trip Tantivy circuit breaker (no host failover)
        self._tantivy_consecutive_failures += 1
        if self._tantivy_consecutive_failures >= self._circuit_breaker_threshold:
            self._tantivy_circuit_open_until = (
                time.time() + self._circuit_breaker_reset_secs
            )
            logger.warning(
                "Tantivy circuit breaker opened for %.0fs after %d consecutive failures",
                self._circuit_breaker_reset_secs,
                self._tantivy_consecutive_failures,
            )
        raise RuntimeError(
            f"Tantivy request failed after {self.max_retries + 1} attempts: "
            f"{last_exc}"
        ) from last_exc

    def _tantivy_index(
        self, workspace_id: str, entity_id: str, content: str, entity_type: str = ""
    ) -> bool:
        """Index a single document in the Tantivy BM25 sidecar.

        ``entity_type`` is accepted but currently unused by the sidecar;
        included for forward compatibility.
        """
        with _tracing_span("tantivy.index", entity_id=entity_id):
            try:
                payload: dict[str, Any] = {
                    "workspace_id": workspace_id,
                    "entity_id": entity_id,
                    "content": content,
                }
                if entity_type:
                    payload["entity_type"] = entity_type
                resp = self._request_with_retry_tantivy(
                    "POST",
                    f"{self.tantivy_url}/index",
                    json=payload,
                    timeout=10,
                )
                return resp.status_code < 400
            except RuntimeError:
                return False

    def _tantivy_index_batch(self, items: list[dict[str, str]]) -> bool:
        """Index multiple documents in the Tantivy BM25 sidecar."""
        if not items:
            return True
        with _tracing_span("tantivy.index_batch", batch_size=len(items)):
            try:
                resp = self._request_with_retry_tantivy(
                    "POST",
                    f"{self.tantivy_url}/index/batch",
                    json={"items": items},
                    timeout=30,
                )
                return resp.status_code < 400
            except RuntimeError:
                return False

    def _tantivy_search(
        self, workspace_id: str, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Search Tantivy BM25 index with a text query."""
        with _tracing_span("tantivy.search", query=query[:100]):
            try:
                resp = self._request_with_retry_tantivy(
                    "POST",
                    f"{self.tantivy_url}/search",
                    json={
                        "workspace_id": workspace_id,
                        "query": query,
                        "limit": limit,
                    },
                    timeout=10,
                )
                if resp.status_code < 400:
                    return resp.json()
                return []
            except RuntimeError:
                return []
