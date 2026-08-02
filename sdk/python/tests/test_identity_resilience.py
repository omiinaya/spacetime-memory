"""Tests for SDK identity resilience fixes (2026-08-01).

Two benchmark-contamination bugs were fixed in ``client/_base.py``:

1. ``_ensure_identity()`` permanently gave up on a failed handshake (it set
   ``_identity_established = True`` even when no token was captured), so every
   later call went out unauthenticated → "Not authenticated" reducer errors
   contaminated benchmark results with zero-retrieval questions.
   Fix: on failure it leaves ``_identity_established = False`` so the next
   call retries the handshake.

2. ``_call()`` / ``_call_with_result()`` adopted whatever
   ``spacetime-identity-token`` header came back on ANY response. Under load
   STDB can echo a fresh *anonymous* token, silently swapping the registered
   account identity for an anonymous one mid-run → "Access denied" on every
   later workspace-scoped call.
   Fix: only adopt a new token from auth-relevant reducers (``register``,
   ``login``, ``create_auth_session``, ``verify_login``) or when no token
   exists yet.
"""

from unittest.mock import MagicMock, patch

import httpx

# ── Helpers ────────────────────────────────────────────────────────────────


def make_client():
    """ClientBase with mocked HTTP transport (mirrors test_base fixture)."""
    from spacetime_memory import Client

    cb = Client.__new__(Client)
    cb._http = MagicMock(spec=httpx.Client)
    cb._http.get.return_value = MagicMock(
        status_code=200, headers={}, text="", content=b""
    )
    cb._http.post.return_value = MagicMock(
        status_code=200, headers={}, text="{}", content=b"{}"
    )
    cb._identity_token = ""
    cb._identity_established = False
    cb.token = None
    cb._identity_peer_id = ""
    cb._last_identity_refresh = 0.0
    cb._identity_refresh_interval = 300.0
    cb.host = "127.0.0.1"
    cb.port = "3001"
    cb.database = "test_db"
    cb.sql_url = f"http://{cb.host}:{cb.port}/v1/database/{cb.database}/sql"
    cb.reducer_url = f"http://{cb.host}:{cb.port}/v1/database/{cb.database}/call"
    cb.embedder_url = "http://127.0.0.1:4000"
    cb.tantivy_url = "http://127.0.0.1:9091"
    cb.verbose = False
    cb.max_retries = 3
    cb._consecutive_failures = 0
    cb._circuit_open_until = 0.0
    cb._circuit_breaker_threshold = 5
    cb._circuit_breaker_reset_secs = 30.0
    cb._hosts = ["127.0.0.1:3001"]
    cb._current_host_index = 0
    cb._embedder_consecutive_failures = 0
    cb._embedder_last_failure_ts = 0.0
    cb._embedder_alert_threshold = 3
    cb._init_embedder_counters = lambda: None
    cb._query_cache = None
    cb._binary_cache = {}
    cb._metrics = None
    cb._delta_sync = None
    cb._compounder = None
    cb.plugin_manager = None
    cb.event_bus = None
    cb.local_llm = None
    cb._plugin = None
    cb._observability = None
    cb.request_id = "abcdef01"
    cb._call_counter = 0
    cb._pending_reconnect = False
    return cb


def resp(status=200, headers=None, text="{}"):
    return MagicMock(
        status_code=status, headers=headers or {}, text=text, content=text.encode()
    )


# ── _ensure_identity resilience ────────────────────────────────────────────


class TestEnsureIdentityResilience:
    def test_handshake_failure_does_not_mark_established(self):
        """HTTP 500 on handshake must NOT set _identity_established=True."""
        cb = make_client()
        cb._http.get.return_value = resp(status=500)
        cb._ensure_identity()
        assert cb._identity_established is False
        assert cb._identity_token == ""

    def test_handshake_connection_error_does_not_mark_established(self):
        """Connect error on handshake must NOT permanently give up."""
        cb = make_client()
        cb._http.get.side_effect = httpx.ConnectError("refused")
        cb._ensure_identity()
        assert cb._identity_established is False

    def test_handshake_success_captures_token_and_pins_host(self):
        """Successful handshake captures the identity token."""
        cb = make_client()
        cb._http.get.return_value = resp(
            headers={"spacetime-identity-token": "anon-identity-tok"}
        )
        cb._ensure_identity()
        assert cb._identity_established is True
        assert cb._identity_token == "anon-identity-tok"
        assert cb.host == "127.0.0.1"

    def test_retry_after_transient_failure_succeeds(self):
        """A later call retries the handshake once STDB recovers."""
        cb = make_client()
        cb._http.get.side_effect = [
            httpx.ConnectError("refused"),  # first handshake fails
            resp(headers={"spacetime-identity-token": "recovered-tok"}),  # recovers
        ]
        cb._ensure_identity()
        assert cb._identity_established is False  # still not established
        cb._ensure_identity()  # second call retries
        assert cb._identity_established is True
        assert cb._identity_token == "recovered-tok"


# ── _call token-guard ──────────────────────────────────────────────────────


class TestCallTokenGuard:
    def test_non_auth_reducer_does_not_clobber_existing_token(self):
        """A plain search response must not overwrite a registered token."""
        cb = make_client()
        cb.token = "registered-account-token"
        cb._identity_token = "registered-account-token"
        cb._identity_established = True
        # STDB echoes an anonymous token on an arbitrary response
        cb._http.post.return_value = resp(
            headers={"spacetime-identity-token": "anonymous-echo"}
        )
        cb._call("search", ["ws", "query"])
        assert cb.token == "registered-account-token"  # unchanged
        assert cb._identity_token == "registered-account-token"

    def test_auth_reducer_adopts_new_token(self):
        """login/register responses may update the token."""
        cb = make_client()
        cb.token = None
        cb._http.post.return_value = resp(
            headers={"spacetime-identity-token": "account-token"}
        )
        cb._call("login", ["user", "pass"])
        assert cb.token == "account-token"

    def test_first_token_adopted_when_none(self):
        """When no token exists, any response may establish one."""
        cb = make_client()
        cb.token = None
        cb._http.post.return_value = resp(
            headers={"spacetime-identity-token": "first-token"}
        )
        cb._call("create_note", ["ws", "title", "content"])
        assert cb.token == "first-token"

    def test_call_with_result_guard(self):
        """_call_with_result must not clobber a registered token either."""
        cb = make_client()
        cb.token = "registered-account-token"
        cb._identity_token = "registered-account-token"
        cb._identity_established = True
        cb._http.post.return_value = resp(
            headers={"spacetime-identity-token": "anonymous-echo"},
            text='{"result": {"ok": true}}',
        )
        cb._call_with_result("get_results", [])
        assert cb.token == "registered-account-token"


class TestEmbedCacheIsolation:
    """The query-embedding cache must be instance-scoped, not class-scoped.

    Regression for the 2026-08-02 test-pollution bug: ``_embed_cache`` was a
    class-level ``OrderedDict`` shared by every ``Client`` instance. In a full
    serial test run, the first test that embedded text ``"hello"`` populated the
    shared cache; later tests asserting error/fallback behaviour for the same
    text observed a cache hit and received the cached vector instead of the
    expected ``[]`` (order-dependent failures that vanished under xdist, where
    polluter and victim ran on different workers).
    """

    def test_cache_is_per_instance(self):
        from spacetime_memory import Client

        c1 = Client.__new__(Client)
        c2 = Client.__new__(Client)
        # No pre-existing instance attribute (class attribute removed)
        assert not hasattr(c1, "_embed_cache")
        assert not hasattr(c2, "_embed_cache")

        cache1 = c1._get_embed_cache()
        cache2 = c2._get_embed_cache()

        assert cache1 is not cache2  # different instances, different caches
        assert hasattr(c1, "_embed_cache")
        assert hasattr(c2, "_embed_cache")

        cache1["hello"] = (0.0, [1.0, 2.0])
        assert "hello" not in cache2  # no leakage between instances

    def test_error_path_not_poisoned_by_prior_success(self):
        """A prior successful embed of 'hello' must not satisfy a later error test."""
        from unittest.mock import Mock

        import httpx

        from spacetime_memory import Client

        # Instance A: successful embed of "hello" caches a vector.
        a = Client.__new__(Client)
        a.embedder_url = "http://127.0.0.1:59999"  # unreachable -> local fails
        a._http = MagicMock(spec=httpx.Client)
        a.max_retries = 1
        a._request_with_retry_simple = MagicMock(return_value=Mock(
            status_code=200,
            json=lambda: {"data": [{"embedding": [0.0]}]},
        ))
        a._init_embedder_counters()
        a._embedder_total_errors = 0
        a._embedder_error_timestamps = []
        a._record_embedder_error = MagicMock()
        a._check_error_rate_alert = MagicMock()
        a._clear_embedder_errors = MagicMock()
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            vec = a._embed("hello")
        assert vec == [0.0]

        # Instance B: same text, but the local embedder now fails AND OpenAI
        # fails — must return [], NOT the cached vector from A.
        b = Client.__new__(Client)
        b.embedder_url = "http://127.0.0.1:59999"
        b._http = MagicMock(spec=httpx.Client)
        b.max_retries = 1
        b._request_with_retry_simple = MagicMock(side_effect=httpx.ConnectError("down"))
        b._init_embedder_counters()
        b._embedder_total_errors = 0
        b._embedder_error_timestamps = []
        b._record_embedder_error = MagicMock()
        b._check_error_rate_alert = MagicMock()
        b._clear_embedder_errors = MagicMock()
        with patch.dict("os.environ", {}, clear=True):  # no API key -> OpenAI [] too
            result = b._embed("hello")
        assert result == []
