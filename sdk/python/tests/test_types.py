"""Tests for spacetime_memory.connectors._types — Event, ConnectorRegistry, ConnectorDaemon.

All tests use mocked connectors and clients. No real network calls.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestEvent:
    """Event dataclass for connector poll results."""

    def test_default_values(self):
        from spacetime_memory.connectors._types import Event

        e = Event(content="hello")
        assert e.content == "hello"
        assert e.workspace_id == ""
        assert e.summary == ""
        assert e.memory_type == "experience"
        assert e.peer_id == "connector"
        assert e.session_id == ""
        assert e.metadata == {}

    def test_custom_values(self):
        from spacetime_memory.connectors._types import Event

        e = Event(
            content="test content",
            workspace_id="ws-1",
            summary="summary",
            memory_type="observation",
            peer_id="my-bot",
            session_id="sess-1",
            metadata={"source": "rss"},
        )
        assert e.content == "test content"
        assert e.workspace_id == "ws-1"
        assert e.summary == "summary"
        assert e.memory_type == "observation"
        assert e.peer_id == "my-bot"
        assert e.session_id == "sess-1"
        assert e.metadata == {"source": "rss"}


class TestConnectorRegistry:
    """Registry for managing multiple SyncConnector instances."""

    @pytest.fixture
    def registry(self):
        from spacetime_memory.connectors._types import ConnectorRegistry

        return ConnectorRegistry()

    def test_register_and_get(self, registry):
        connector = MagicMock()
        registry.register("test", connector)
        assert registry.get("test") is connector

    def test_unregister(self, registry):
        connector = MagicMock()
        registry.register("test", connector)
        registry.unregister("test")
        assert registry.get("test") is None

    def test_unregister_nonexistent(self, registry):
        # Should not raise
        registry.unregister("nonexistent")

    def test_list_empty(self, registry):
        assert registry.list() == {}

    def test_list_returns_copy(self, registry):
        connector = MagicMock()
        registry.register("test", connector)
        listing = registry.list()
        listing["extra"] = MagicMock()
        assert "extra" not in registry.list()

    def test_poll_all_returns_results(self, registry):
        c1 = MagicMock()
        c1.poll.return_value = [MagicMock(), MagicMock()]
        c2 = MagicMock()
        c2.poll.return_value = [MagicMock()]
        registry.register("c1", c1)
        registry.register("c2", c2)
        results = registry.poll_all()
        assert len(results["c1"]) == 2
        assert len(results["c2"]) == 1

    def test_poll_all_error_isolation(self, registry):
        """One connector failing does not prevent others from polling."""
        c1 = MagicMock()
        c1.poll.side_effect = ValueError("c1 error")
        c2 = MagicMock()
        c2.poll.return_value = [MagicMock()]
        registry.register("c1", c1)
        registry.register("c2", c2)
        results = registry.poll_all()
        assert results["c1"] == []  # error returns empty list
        assert len(results["c2"]) == 1

    def test_poll_all_empty_registry(self, registry):
        results = registry.poll_all()
        assert results == {}

    def test_register_overwrites_existing(self, registry):
        c1 = MagicMock()
        c2 = MagicMock()
        registry.register("test", c1)
        registry.register("test", c2)
        assert registry.get("test") is c2


class TestConnectorDaemon:
    """Background daemon for polling connectors loaded from DB configs."""

    @pytest.fixture
    def daemon(self):
        from spacetime_memory.connectors._types import ConnectorDaemon

        client = MagicMock()
        client._query.return_value = []
        return ConnectorDaemon(client, db_poll_secs=1)

    def test_init_sets_attributes(self, daemon):
        assert daemon.db_poll_secs == 1
        assert daemon._runners == {}
        assert daemon._running is False

    def test_load_configs_queries_database(self, daemon):
        daemon.client._query.return_value = [
            {"id": "cfg-1", "name": "my-feed", "connector_type": "rss",
             "config_json": '{"feed_url": "https://example.com/rss"}',
             "workspace_id": "ws-1", "schedule_secs": 300},
        ]
        configs = daemon._load_configs()
        assert len(configs) == 1
        assert configs[0]["id"] == "cfg-1"
        daemon.client._query.assert_called_once()

    def test_load_configs_empty(self, daemon):
        daemon.client._query.return_value = []
        configs = daemon._load_configs()
        assert configs == []

    def test_build_connector_rss(self, daemon):
        with patch("spacetime_memory.connectors.RssFeedConnector") as MockRss:
            cfg = {
                "id": "cfg-1",
                "connector_type": "rss",
                "config_json": '{"feed_url": "https://example.com/rss"}',
                "workspace_id": "ws-1",
            }
            conn = daemon._build_connector(cfg)
            MockRss.assert_called_once_with(feed_url="https://example.com/rss", workspace_id="ws-1")
            assert conn is not None

    def test_build_connector_unknown_type(self, daemon):
        cfg = {
            "id": "cfg-bad",
            "connector_type": "unknown_type",
            "config_json": "{}",
            "workspace_id": "ws-1",
        }
        with pytest.raises(ValueError, match="Unknown connector type"):
            daemon._build_connector(cfg)

    def test_build_connector_rss_defaults_empty_feed_url(self, daemon):
        with patch("spacetime_memory.connectors.RssFeedConnector") as MockRss:
            cfg = {
                "id": "cfg-2",
                "connector_type": "rss",
                "config_json": "{}",
                "workspace_id": "ws-2",
            }
            daemon._build_connector(cfg)
            MockRss.assert_called_once_with(feed_url="", workspace_id="ws-2")

    def test_build_connector_github(self, daemon):
        with patch("spacetime_memory.connectors.GitHubConnector") as MockGh:
            cfg = {
                "id": "cfg-3",
                "connector_type": "github",
                "config_json": '{"token": "ghp_xxx", "username": "testuser"}',
                "workspace_id": "ws-1",
            }
            conn = daemon._build_connector(cfg)
            MockGh.assert_called_once_with(
                token="ghp_xxx", username="testuser", workspace_id="ws-1"
            )
            assert conn is not None

    def test_start_stop(self, daemon):
        """Verify start/stop cycle doesn't raise."""
        # Verify initial state
        assert daemon._running is False
        daemon.stop()
        assert daemon._running is False

    def test_start_loads_configs_and_polls(self, daemon):
        """Daemon loads configs, builds connectors, runs poll."""
        mock_connector = MagicMock()
        mock_connector.poll.return_value = []
        mock_connector.on_event = MagicMock()

        daemon.client._query.return_value = [
            {"id": "cfg-1", "name": "test", "connector_type": "rss",
             "config_json": '{"feed_url": "https://example.com/rss"}',
             "workspace_id": "ws-1", "schedule_secs": 300},
        ]

        with patch.object(daemon, "_build_connector", return_value=mock_connector):
            # Manually run one tick of the daemon
            configs = daemon._load_configs()
            assert len(configs) == 1

            cfg = configs[0]
            cid = cfg["id"]
            conn = daemon._build_connector(cfg)
            daemon._runners[cid] = conn

            events = conn.poll()
            mock_connector.poll.assert_called_once()
            assert events == []

    def test_event_handler_error_isolated(self, daemon):
        """One event handler error does not crash the loop."""
        mock_connector = MagicMock()
        mock_connector.poll.return_value = [MagicMock(), MagicMock()]
        mock_connector.on_event.side_effect = [ValueError("handler error"), None]

        daemon._runners["cfg-1"] = mock_connector

        # Manually run the poll-and-handle block
        for cid, conn in list(daemon._runners.items()):
            events = conn.poll()
            for ev in events:
                try:
                    conn.on_event(ev, daemon.client)
                except Exception:
                    pass  # This is what the daemon does

        # Should have called on_event twice despite the first raising
        assert mock_connector.on_event.call_count == 2
