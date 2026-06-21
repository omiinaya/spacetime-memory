"""Tests for Connector base class internals (base.py).

Covers Connector.__init__, _load_cursor, _save_cursor,
_retry_client_call, last_status, on_event, run, Event dataclass,
ConnectorRegistry, and ConnectorDaemon.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from spacetime_memory.connectors.base import (
    Connector,
    Event,
    ConnectorRegistry,
    ConnectorDaemon,
)


# ── Concrete subclass for testing abstract base ──────────────────────


class TestConnector(Connector):
    """Concrete Connector that returns canned events for testing."""

    def __init__(self, *, events=None, cursor_dir=None, poll_side_effect=None):
        super().__init__(cursor_dir=cursor_dir)
        self._events = events or []
        self._poll_side_effect = poll_side_effect
        self._poll_count = 0
        self._on_event_calls = []

    def poll(self):
        if self._poll_side_effect is not None:
            self._poll_count += 1
            if callable(self._poll_side_effect):
                return self._poll_side_effect(self._poll_count)
            raise self._poll_side_effect
        self._poll_count += 1
        return list(self._events)

    def on_event(self, event, client):
        self._on_event_calls.append((event, client))
        super().on_event(event, client)


# ── Event dataclass ──────────────────────────────────────────────────


class TestEvent:
    """Tests for the Event dataclass."""

    def test_default_values(self):
        ev = Event(content="hello")
        assert ev.content == "hello"
        assert ev.workspace_id == ""
        assert ev.summary == ""
        assert ev.memory_type == "experience"
        assert ev.peer_id == "connector"
        assert ev.session_id == ""
        assert ev.metadata == {}

    def test_all_fields_custom(self):
        ev = Event(
            content="test",
            workspace_id="ws-1",
            summary="a summary",
            memory_type="world_fact",
            peer_id="user-1",
            session_id="sess-1",
            metadata={"key": "val"},
        )
        assert ev.workspace_id == "ws-1"
        assert ev.summary == "a summary"
        assert ev.memory_type == "world_fact"
        assert ev.peer_id == "user-1"
        assert ev.session_id == "sess-1"
        assert ev.metadata == {"key": "val"}

    def test_dataclass_repr(self):
        ev = Event(content="x")
        r = repr(ev)
        assert "Event" in r
        assert "x" in r


# ── Connector __init__ ───────────────────────────────────────────────


class TestConnectorInit:
    """Tests for Connector.__init__ behavior."""

    def test_default_cursor_dir(self, tmp_path):
        """Uses ~/.spacetime-memory/connectors by default."""
        with mock.patch("os.path.expanduser", return_value=str(tmp_path)):
            conn = TestConnector()
        assert conn._cursor_dir == str(tmp_path)
        assert conn._cursor == {}
        assert conn._last_poll_time == 0.0
        assert conn._error_count == 0
        assert conn._last_status == "ok"

    def test_custom_cursor_dir(self, tmp_path):
        """Custom cursor_dir is respected."""
        d = tmp_path / "custom"
        conn = TestConnector(cursor_dir=str(d))
        assert conn._cursor_dir == str(d)
        assert d.exists()  # os.makedirs was called
        assert conn._cursor_file == str(d / "TestConnector_cursor.json")

    def test_logger_naming(self):
        """Logger is named connector.<ClassName>."""
        conn = TestConnector()
        assert conn._log.name == "connector.TestConnector"


# ── Cursor persistence ───────────────────────────────────────────────


class TestCursorLoad:
    """Tests for _load_cursor."""

    def test_no_cursor_file(self, tmp_path):
        """When cursor file doesn't exist, _cursor stays empty."""
        conn = TestConnector(cursor_dir=str(tmp_path))
        conn._cursor = {"old": "data"}
        conn._load_cursor()
        assert conn._cursor == {}  # reset to empty

    def test_loads_valid_json(self, tmp_path):
        """Loads JSON cursor data from disk."""
        cursor_file = tmp_path / "TestConnector_cursor.json"
        cursor_file.write_text(json.dumps({"since": "2024-01-01", "count": 5}))

        conn = TestConnector(cursor_dir=str(tmp_path))
        conn._load_cursor()
        assert conn._cursor == {"since": "2024-01-01", "count": 5}

    def test_loads_corrupt_json(self, tmp_path):
        """Corrupt JSON resets to empty dict."""
        cursor_file = tmp_path / "TestConnector_cursor.json"
        cursor_file.write_text("not valid json!!!")

        conn = TestConnector(cursor_dir=str(tmp_path))
        conn._load_cursor()
        assert conn._cursor == {}

    def test_loads_non_dict_json(self, tmp_path):
        """If the JSON is not a dict, reset to empty."""
        cursor_file = tmp_path / "TestConnector_cursor.json"
        cursor_file.write_text("[1, 2, 3]")

        conn = TestConnector(cursor_dir=str(tmp_path))
        conn._load_cursor()
        assert conn._cursor == {}

    def test_loads_permission_error(self, tmp_path):
        """OSError (permission) during load resets to empty."""
        cursor_file = tmp_path / "TestConnector_cursor.json"
        cursor_file.write_text('{"k": "v"}')

        conn = TestConnector(cursor_dir=str(tmp_path))
        with mock.patch("builtins.open", side_effect=OSError("Permission denied")):
            conn._load_cursor()
        assert conn._cursor == {}


class TestCursorSave:
    """Tests for _save_cursor."""

    def test_saves_cursor_to_file(self, tmp_path):
        """_save_cursor writes JSON to the cursor file."""
        conn = TestConnector(cursor_dir=str(tmp_path))
        conn._cursor = {"last_id": "abc123", "count": 42}
        conn._save_cursor()

        cursor_file = tmp_path / "TestConnector_cursor.json"
        assert cursor_file.exists()
        data = json.loads(cursor_file.read_text())
        assert data == {"last_id": "abc123", "count": 42}

    def test_save_permission_error_handled(self, tmp_path):
        """OSError during save is caught and logged."""
        conn = TestConnector(cursor_dir=str(tmp_path))
        conn._cursor = {"k": "v"}

        with mock.patch("builtins.open", side_effect=OSError("Permission denied")):
            conn._save_cursor()  # should not raise

        # File should not exist
        cursor_file = tmp_path / "TestConnector_cursor.json"
        assert not cursor_file.exists()

    def test_save_overwrites_previous(self, tmp_path):
        """Saving twice overwrites the file."""
        conn = TestConnector(cursor_dir=str(tmp_path))
        conn._cursor = {"v": 1}
        conn._save_cursor()
        conn._cursor = {"v": 2}
        conn._save_cursor()

        data = json.loads((tmp_path / "TestConnector_cursor.json").read_text())
        assert data == {"v": 2}


# ── Retry with backoff ───────────────────────────────────────────────


class TestRetryClientCall:
    """Tests for _retry_client_call."""

    def test_first_attempt_succeeds(self):
        """When the first attempt succeeds, return the response immediately."""
        conn = TestConnector()
        mock_resp = mock.Mock(spec=httpx.Response, status_code=200)
        mock_client = mock.Mock(spec=httpx.Client)
        mock_client.get.return_value = mock_resp

        result = conn._retry_client_call(mock_client, "get", "http://example.com")
        assert result is mock_resp
        mock_client.get.assert_called_once_with("http://example.com")

    def test_retries_on_request_error_then_succeeds(self):
        """Retries when httpx.RequestError is raised, succeeds on retry."""
        conn = TestConnector()
        mock_resp = mock.Mock(spec=httpx.Response, status_code=200)
        mock_client = mock.Mock(spec=httpx.Client)

        # Fail once, succeed on second call
        mock_client.get.side_effect = [
            httpx.RequestError("timeout"),
            mock_resp,
        ]

        with mock.patch("time.sleep") as mock_sleep:
            result = conn._retry_client_call(mock_client, "get", "http://example.com")

        assert result is mock_resp
        assert mock_client.get.call_count == 2
        mock_sleep.assert_called_once()

    def test_exhausts_retries_and_raises(self):
        """After max_retries failures, re-raises the last RequestError."""
        conn = TestConnector()
        mock_client = mock.Mock(spec=httpx.Client)
        mock_client.get.side_effect = httpx.RequestError("always failing")

        with mock.patch("time.sleep"):
            with pytest.raises(httpx.RequestError, match="always failing"):
                conn._retry_client_call(mock_client, "get", "http://example.com", max_retries=2)

        assert mock_client.get.call_count == 2

    def test_uses_method_parameter(self):
        """The method parameter determines which HTTP method is called."""
        conn = TestConnector()
        mock_resp = mock.Mock(spec=httpx.Response, status_code=201)
        mock_client = mock.Mock(spec=httpx.Client)
        mock_client.post.return_value = mock_resp

        result = conn._retry_client_call(
            mock_client, "post", "http://example.com", json={"key": "val"}
        )
        assert result is mock_resp
        mock_client.post.assert_called_once_with("http://example.com", json={"key": "val"})

    def test_custom_max_retries(self):
        """max_retries parameter is respected."""
        conn = TestConnector()
        mock_client = mock.Mock(spec=httpx.Client)
        mock_client.get.side_effect = httpx.RequestError("fail")

        with mock.patch("time.sleep"):
            with pytest.raises(httpx.RequestError):
                conn._retry_client_call(mock_client, "get", "http://example.com", max_retries=5)

        assert mock_client.get.call_count == 5

    def test_custom_base_delay(self):
        """base_delay parameter affects sleep duration."""
        conn = TestConnector()
        mock_client = mock.Mock(spec=httpx.Client)
        mock_resp = mock.Mock(spec=httpx.Response, status_code=200)

        # Fail on first, succeed on second
        mock_client.get.side_effect = [
            httpx.RequestError("timeout"),
            mock_resp,
        ]

        with mock.patch("time.sleep") as mock_sleep:
            result = conn._retry_client_call(
                mock_client, "get", "http://example.com", base_delay=5.0
            )

        assert result is mock_resp
        # Sleep called with base_delay * 2^0 = 5.0 + jitter (0-0.1)
        call_arg = mock_sleep.call_args[0][0]
        assert 5.0 <= call_arg <= 5.1

    def test_does_not_retry_on_4xx(self):
        """4xx responses are NOT retried — the RequestError is only for transport errors."""
        conn = TestConnector()
        mock_client = mock.Mock(spec=httpx.Client)
        # 4xx triggers httpx.HTTPStatusError, which is NOT a RequestError subclass
        # in newer httpx. But our code only catches RequestError, so 4xx passes through
        mock_resp = mock.Mock(spec=httpx.Response, status_code=404)
        mock_client.get.return_value = mock_resp

        result = conn._retry_client_call(mock_client, "get", "http://example.com")
        assert result is mock_resp
        assert mock_client.get.call_count == 1  # no retry


# ── last_status ──────────────────────────────────────────────────────


class TestLastStatus:
    """Tests for the last_status method."""

    def test_initial_status_is_ok(self):
        conn = TestConnector()
        status = conn.last_status()
        assert status["status"] == "ok"
        assert status["last_poll"] == 0.0
        assert status["errors_since_last_ok"] == 0

    def test_status_after_poll(self):
        conn = TestConnector()
        conn._last_poll_time = 1234567890.0
        conn._error_count = 3
        conn._last_status = "error"
        status = conn.last_status()
        assert status == {
            "status": "error",
            "last_poll": 1234567890.0,
            "errors_since_last_ok": 3,
        }


# ── on_event ─────────────────────────────────────────────────────────


class TestOnEvent:
    """Tests for the on_event default implementation."""

    def test_on_event_calls_client_store(self):
        conn = TestConnector()
        mock_client = mock.Mock()
        ev = Event(
            content="test memory",
            workspace_id="ws-1",
            summary="A summary",
            memory_type="world_fact",
            peer_id="user-1",
            session_id="sess-1",
        )

        conn.on_event(ev, mock_client)
        mock_client.store.assert_called_once_with(
            workspace_id="ws-1",
            content="test memory",
            summary="A summary",
            memory_type="world_fact",
            peer_id="user-1",
            source_session_id="sess-1",
        )

    def test_on_event_falls_back_to_content_preview(self):
        """When summary is empty, uses first 200 chars of content."""
        conn = TestConnector()
        mock_client = mock.Mock()
        ev = Event(
            content="x" * 300,
            workspace_id="ws-1",
            summary="",  # empty
            memory_type="experience",
            peer_id="",
            session_id="",
        )

        conn.on_event(ev, mock_client)
        mock_client.store.assert_called_once_with(
            workspace_id="ws-1",
            content="x" * 300,
            summary="x" * 200,  # first 200 chars
            memory_type="experience",
            peer_id="connector",  # default when empty
            source_session_id="",  # default
        )

    def test_on_event_default_values(self):
        """Default Event values produce sensible store() call."""
        conn = TestConnector()
        mock_client = mock.Mock()
        ev = Event(content="just content")

        conn.on_event(ev, mock_client)
        mock_client.store.assert_called_once_with(
            workspace_id="",
            content="just content",
            summary="just content",  # content[:200] when summary empty
            memory_type="experience",
            peer_id="connector",
            source_session_id="",
        )


# ── run loop ─────────────────────────────────────────────────────────


class TestRun:
    """Tests for the run() poll loop."""

    def test_run_processes_events(self):
        """run() calls poll(), feeds events to on_event(), and tracks status."""
        conn = TestConnector(events=[
            Event(content="ev1"),
            Event(content="ev2"),
        ])
        mock_client = mock.Mock()

        with mock.patch("time.sleep"):
            conn.run(mock_client, interval_secs=0.01, stop_after=1)

        assert conn._last_status == "ok"
        assert conn._last_poll_time > 0
        assert conn._error_count == 0
        assert len(conn._on_event_calls) == 2

    def test_run_respects_max_per_tick(self):
        """max_per_tick caps the number of events processed."""
        conn = TestConnector(events=[
            Event(content=f"ev{i}") for i in range(10)
        ])
        mock_client = mock.Mock()

        with mock.patch("time.sleep"):
            conn.run(mock_client, interval_secs=0.01, max_per_tick=3, stop_after=1)

        assert len(conn._on_event_calls) == 3

    def test_run_stop_after_multiple_ticks(self):
        """stop_after=N runs N ticks."""
        conn = TestConnector(events=[Event(content="tick")])
        mock_client = mock.Mock()

        with mock.patch("time.sleep"):
            conn.run(mock_client, interval_secs=0.01, stop_after=3)

        assert conn._poll_count == 3
        assert len(conn._on_event_calls) == 3

    def test_run_handles_poll_error(self):
        """When poll() raises, status is set to error and counter increments."""
        conn = TestConnector(poll_side_effect=RuntimeError("poll failed"))
        mock_client = mock.Mock()

        with mock.patch("time.sleep"):
            conn.run(mock_client, interval_secs=0.01, stop_after=2)

        assert conn._last_status == "error"
        assert conn._error_count == 2

    def test_run_handles_on_event_error(self):
        """When on_event() raises, error is logged and count increments."""
        conn = TestConnector(events=[
            Event(content="ev1"),
            Event(content="ev2"),
        ])
        mock_client = mock.Mock()
        # Make the second event crash
        def crashing_on_event(event, client):
            if event.content == "ev2":
                raise RuntimeError("handler crash")
            conn._on_event_calls.append((event, client))
            super(TestConnector, conn).on_event(event, client)
        conn.on_event = crashing_on_event

        with mock.patch("time.sleep"):
            conn.run(mock_client, interval_secs=0.01, stop_after=1)

        # First event succeeded, second event error counted
        assert conn._error_count == 1
        assert conn._last_status == "ok"  # still ok because poll() succeeded

    def test_run_saves_cursor_on_exit(self):
        """run() calls _save_cursor() when the loop ends."""
        conn = TestConnector(events=[])
        mock_client = mock.Mock()

        with mock.patch.object(conn, "_save_cursor") as mock_save, \
             mock.patch("time.sleep"):
            conn.run(mock_client, interval_secs=0.01, stop_after=1)

        mock_save.assert_called_once()

    def test_run_infinite_loop_needs_interrupt(self):
        """Without stop_after, run() blocks forever (verified via patched sleep)."""
        conn = TestConnector(events=[])
        mock_client = mock.Mock()

        # Mock time.sleep to raise KeyboardInterrupt after 1 call
        with mock.patch("time.sleep") as mock_sleep:
            mock_sleep.side_effect = [None, KeyboardInterrupt()]
            with pytest.raises(KeyboardInterrupt):
                conn.run(mock_client, interval_secs=0.01)

        assert conn._poll_count >= 1


# ── ConnectorRegistry ────────────────────────────────────────────────


class TestConnectorRegistry:
    """Tests for the ConnectorRegistry class."""

    def test_register_and_get(self):
        reg = ConnectorRegistry()
        conn = TestConnector()
        reg.register("test", conn)
        assert reg.get("test") is conn

    def test_get_nonexistent(self):
        reg = ConnectorRegistry()
        assert reg.get("nope") is None

    def test_unregister(self):
        reg = ConnectorRegistry()
        conn = TestConnector()
        reg.register("test", conn)
        reg.unregister("test")
        assert reg.get("test") is None

    def test_unregister_nonexistent_no_error(self):
        reg = ConnectorRegistry()
        reg.unregister("nope")  # should not raise

    def test_list_returns_copy(self):
        reg = ConnectorRegistry()
        conn = TestConnector()
        reg.register("test", conn)

        listing = reg.list()
        assert listing == {"test": conn}
        # Mutating the returned dict doesn't affect registry
        listing["new"] = mock.Mock()
        assert reg.get("new") is None

    def test_poll_all_aggregates(self):
        reg = ConnectorRegistry()
        reg.register("a", TestConnector(events=[Event(content="a1")]))
        reg.register("b", TestConnector(events=[Event(content="b1"), Event(content="b2")]))

        results = reg.poll_all()
        assert set(results.keys()) == {"a", "b"}
        assert len(results["a"]) == 1
        assert len(results["b"]) == 2
        assert results["a"][0].content == "a1"

    def test_poll_all_handles_errors(self):
        reg = ConnectorRegistry()
        reg.register("ok", TestConnector(events=[Event(content="ok")]))
        reg.register("bad", TestConnector(poll_side_effect=RuntimeError("boom")))

        results = reg.poll_all()
        assert len(results["ok"]) == 1
        assert results["bad"] == []  # error caught, empty list returned


# ── ConnectorDaemon ──────────────────────────────────────────────────


class TestConnectorDaemon:
    """Tests for the ConnectorDaemon class."""

    def test_init(self):
        client = mock.Mock()
        daemon = ConnectorDaemon(client, db_poll_secs=30)
        assert daemon.client is client
        assert daemon.db_poll_secs == 30
        assert daemon._runners == {}
        assert daemon._running is False

    def test_stop(self):
        daemon = ConnectorDaemon(mock.Mock())
        daemon._running = True
        daemon.stop()
        assert daemon._running is False

    def test_load_configs(self):
        client = mock.Mock()
        client._query.return_value = [
            {"id": "c1", "name": "My RSS", "connector_type": "rss",
             "config_json": '{"feed_url":"https://example.com/feed"}',
             "workspace_id": "ws-1", "schedule_secs": 300, "is_active": "true"}
        ]
        daemon = ConnectorDaemon(client)
        rows = daemon._load_configs()
        assert len(rows) == 1
        assert rows[0]["id"] == "c1"
        client._query.assert_called_once()

    def test_build_connector_rss(self):
        daemon = ConnectorDaemon(mock.Mock())
        cfg = {
            "id": "c1", "name": "RSS Feed",
            "connector_type": "rss",
            "config_json": '{"feed_url": "https://example.com/rss"}',
            "workspace_id": "ws-1",
        }
        with mock.patch("spacetime_memory.connectors.RssFeedConnector") as MockRSS:
            result = daemon._build_connector(cfg)
            MockRSS.assert_called_once_with(
                feed_url="https://example.com/rss", workspace_id="ws-1"
            )

    def test_build_connector_unknown_type(self):
        daemon = ConnectorDaemon(mock.Mock())
        cfg = {
            "id": "c1", "name": "Bad",
            "connector_type": "nonexistent",
            "config_json": "{}",
            "workspace_id": "ws-1",
        }
        with pytest.raises(ValueError, match="Unknown connector type"):
            daemon._build_connector(cfg)

    def test_build_connector_github(self):
        daemon = ConnectorDaemon(mock.Mock())
        cfg = {
            "id": "c2", "name": "GH",
            "connector_type": "github",
            "config_json": '{"token": "tok", "username": "user"}',
            "workspace_id": "ws-2",
        }
        with mock.patch("spacetime_memory.connectors.GitHubConnector") as MockGH:
            daemon._build_connector(cfg)
            MockGH.assert_called_once_with(token="tok", username="user", workspace_id="ws-2")

    def test_build_connector_twitter(self):
        daemon = ConnectorDaemon(mock.Mock())
        cfg = {
            "id": "c3", "name": "Twitter",
            "connector_type": "twitter",
            "config_json": '{"bearer_token": "bear", "user_id": "uid"}',
            "workspace_id": "ws-3",
        }
        with mock.patch("spacetime_memory.connectors.TwitterConnector") as MockTw:
            daemon._build_connector(cfg)
            MockTw.assert_called_once_with(bearer_token="bear", user_id="uid", workspace_id="ws-3")

    def test_build_connector_slack(self):
        daemon = ConnectorDaemon(mock.Mock())
        cfg = {
            "id": "c4", "name": "Slack",
            "connector_type": "slack",
            "config_json": '{"token": "tok", "channel_ids": ["c1"]}',
            "workspace_id": "ws-4",
        }
        with mock.patch("spacetime_memory.connectors.SlackConnector") as MockSlack:
            daemon._build_connector(cfg)
            MockSlack.assert_called_once_with(token="tok", channel_ids=["c1"], workspace_id="ws-4")

    def test_build_connector_discord(self):
        daemon = ConnectorDaemon(mock.Mock())
        cfg = {
            "id": "c5", "name": "Discord",
            "connector_type": "discord",
            "config_json": '{"token": "tok", "channel_ids": ["c2"]}',
            "workspace_id": "ws-5",
        }
        with mock.patch("spacetime_memory.connectors.DiscordConnector") as MockDisc:
            daemon._build_connector(cfg)
            MockDisc.assert_called_once_with(token="tok", channel_ids=["c2"], workspace_id="ws-5")

    def test_start_single_tick(self):
        """start() runs a single tick and stops."""
        daemon = ConnectorDaemon(mock.Mock(), db_poll_secs=1)

        configs = [{"id": "c1", "name": "RSS", "connector_type": "rss",
                     "config_json": '{"feed_url":"http://ex.com/rss"}',
                     "workspace_id": "ws-1", "schedule_secs": 300}]

        with mock.patch.object(daemon, "_load_configs", return_value=configs), \
             mock.patch.object(daemon, "_build_connector") as mock_build, \
             mock.patch("time.sleep") as mock_sleep:
            # Make start() return after 1 tick
            mock_sleep.side_effect = [None, None, KeyboardInterrupt()]

            mock_conn = TestConnector(events=[Event(content="ev1")])
            mock_build.return_value = mock_conn

            with pytest.raises(KeyboardInterrupt):
                daemon.start()

        assert "c1" in daemon._runners

    def test_start_removes_stale_connectors(self):
        """start() removes runners for configs that are no longer active."""
        daemon = ConnectorDaemon(mock.Mock(), db_poll_secs=1)

        # Return empty configs — any existing runners should be removed
        with mock.patch.object(daemon, "_load_configs", return_value=[]), \
             mock.patch("time.sleep") as mock_sleep:
            mock_sleep.side_effect = [None, KeyboardInterrupt()]

            # Manually inject a runner that should be removed
            stale_conn = TestConnector()
            daemon._runners["stale-id"] = stale_conn

            with pytest.raises(KeyboardInterrupt):
                daemon.start()

        assert "stale-id" not in daemon._runners
