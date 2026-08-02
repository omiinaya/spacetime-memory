"""Tests for server/mcp/tools/org.py MCP tools.

Patches ``server.mcp.tools.org.get_client`` and ``org_sync_daemon.OrgSyncDaemon``
to verify delegation.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# org_sync_daemon is imported inside the function body via dynamic sys.path.
# Make it importable here so we can patch it.
_scripts_dir = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),  # tests/
    "..", "..", "..", "scripts",                  # repo root /scripts/
)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)


@pytest.fixture
def mock_client():
    """Patch ``server.mcp.tools.org.get_client`` to return a MagicMock."""
    with patch("server.mcp.tools.org.get_client") as mock_fn:
        instance = MagicMock()
        mock_fn.return_value = instance
        yield instance


@pytest.mark.unit
class TestOrgSync:
    """Tests for ``org_sync``."""

    def test_sync_without_dry_run(self, mock_client):
        from server.mcp.tools.org import org_sync

        mock_daemon = MagicMock()
        mock_daemon.scan.return_value = 42
        mock_daemon.get_status.return_value = {"files_tracked": 3}

        with patch(
            "org_sync_daemon.OrgSyncDaemon",
            return_value=mock_daemon,
        ) as mock_daemon_cls:
            result = org_sync(
                workspace_id="ws-1",
                directory="/tmp/org-test",
                dry_run=False,
            )

        mock_daemon_cls.assert_called_once_with(
            org_dir="/tmp/org-test",
            workspace_id="ws-1",
            client=mock_client,
            dry_run=False,
        )
        mock_daemon.scan.assert_called_once()
        assert "Org sync complete" in result
        assert "42" in result
        assert "3" in result

    def test_dry_run(self, mock_client):
        from server.mcp.tools.org import org_sync

        mock_daemon = MagicMock()
        mock_daemon.scan.return_value = 10
        mock_daemon.get_status.return_value = {"files_tracked": 2}

        with patch(
            "org_sync_daemon.OrgSyncDaemon",
            return_value=mock_daemon,
        ) as mock_daemon_cls:
            result = org_sync(
                workspace_id="ws-1",
                directory="~/org",
                dry_run=True,
            )

        mock_daemon_cls.assert_called_once_with(
            org_dir="~/org",
            workspace_id="ws-1",
            client=mock_client,
            dry_run=True,
        )
        assert "[dry-run]" in result
        assert "10" in result
        assert "2" in result

    # ------------------------------------------------------------------
    # Error cases
    # ------------------------------------------------------------------

    def test_directory_not_found(self, mock_client):
        """Directory does not exist — scan returns 0, no files tracked."""
        from server.mcp.tools.org import org_sync

        mock_daemon = MagicMock()
        mock_daemon.scan.return_value = 0
        mock_daemon.get_status.return_value = {"files_tracked": 0}

        with patch(
            "org_sync_daemon.OrgSyncDaemon",
            return_value=mock_daemon,
        ) as mock_daemon_cls:
            result = org_sync(
                workspace_id="ws-1",
                directory="/nonexistent/path",
                dry_run=False,
            )

        mock_daemon_cls.assert_called_once_with(
            org_dir="/nonexistent/path",
            workspace_id="ws-1",
            client=mock_client,
            dry_run=False,
        )
        mock_daemon.scan.assert_called_once()
        # Even though the directory is invalid, the daemon handles it
        # gracefully and returns 0. The function should still produce a
        # well-formed result message.
        assert "Org sync complete" in result
        assert "0 events" in result
        assert "0 file(s)" in result

    def test_missing_workspace(self, mock_client):
        """Empty workspace_id — daemon still runs but syncs nothing."""
        from server.mcp.tools.org import org_sync

        mock_daemon = MagicMock()
        mock_daemon.scan.return_value = 0
        mock_daemon.get_status.return_value = {"files_tracked": 0}

        with patch(
            "org_sync_daemon.OrgSyncDaemon",
            return_value=mock_daemon,
        ) as mock_daemon_cls:
            result = org_sync(
                workspace_id="",
                directory="/tmp/org-test",
                dry_run=False,
            )

        mock_daemon_cls.assert_called_once_with(
            org_dir="/tmp/org-test",
            workspace_id="",
            client=mock_client,
            dry_run=False,
        )
        mock_daemon.scan.assert_called_once()
        assert "Org sync complete" in result
        assert "0 events" in result
        assert "0 file(s)" in result

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_empty_directory(self, mock_client):
        """Directory exists but contains no .org files — 0 events, 0 files."""
        from server.mcp.tools.org import org_sync

        mock_daemon = MagicMock()
        mock_daemon.scan.return_value = 0
        mock_daemon.get_status.return_value = {"files_tracked": 0}

        with patch(
            "org_sync_daemon.OrgSyncDaemon",
            return_value=mock_daemon,
        ) as mock_daemon_cls:
            result = org_sync(
                workspace_id="ws-1",
                directory="/tmp/empty-org-dir",
                dry_run=False,
            )

        mock_daemon_cls.assert_called_once_with(
            org_dir="/tmp/empty-org-dir",
            workspace_id="ws-1",
            client=mock_client,
            dry_run=False,
        )
        mock_daemon.scan.assert_called_once()
        assert "Org sync complete" in result
        assert "0 events" in result
        assert "0 file(s)" in result

    def test_daemon_returns_zero_files(self, mock_client):
        """Daemon reports 0 files tracked after scan — edge case from empty state."""
        from server.mcp.tools.org import org_sync

        mock_daemon = MagicMock()
        mock_daemon.scan.return_value = 0
        mock_daemon.get_status.return_value = {"files_tracked": 0}

        with patch(
            "org_sync_daemon.OrgSyncDaemon",
            return_value=mock_daemon,
        ) as mock_daemon_cls:
            result = org_sync(
                workspace_id="ws-1",
                directory="/tmp/org-test",
                dry_run=True,
            )

        mock_daemon_cls.assert_called_once_with(
            org_dir="/tmp/org-test",
            workspace_id="ws-1",
            client=mock_client,
            dry_run=True,
        )
        mock_daemon.scan.assert_called_once()
        # Dry-run result format with 0 events
        assert "[dry-run]" in result
        assert "0 events" in result
        assert "0 file(s)" in result

    def test_default_directory(self, mock_client):
        """No directory argument — function uses default '~/org'."""
        from server.mcp.tools.org import org_sync

        mock_daemon = MagicMock()
        mock_daemon.scan.return_value = 5
        mock_daemon.get_status.return_value = {"files_tracked": 1}

        with patch(
            "org_sync_daemon.OrgSyncDaemon",
            return_value=mock_daemon,
        ) as mock_daemon_cls:
            result = org_sync(
                workspace_id="ws-1",
                dry_run=False,
            )

        # Default directory is ~/org
        mock_daemon_cls.assert_called_once_with(
            org_dir="~/org",
            workspace_id="ws-1",
            client=mock_client,
            dry_run=False,
        )
        mock_daemon.scan.assert_called_once()
        assert "Org sync complete" in result
        assert "5" in result

    def test_large_sync(self, mock_client):
        """Large number of events and files should format correctly."""
        from server.mcp.tools.org import org_sync

        mock_daemon = MagicMock()
        mock_daemon.scan.return_value = 999
        mock_daemon.get_status.return_value = {"files_tracked": 50}

        with patch(
            "org_sync_daemon.OrgSyncDaemon",
            return_value=mock_daemon,
        ) as mock_daemon_cls:
            result = org_sync(
                workspace_id="ws-large",
                directory="/tmp/large-org",
                dry_run=False,
            )

        mock_daemon_cls.assert_called_once_with(
            org_dir="/tmp/large-org",
            workspace_id="ws-large",
            client=mock_client,
            dry_run=False,
        )
        assert "999" in result
        assert "50" in result

    def test_single_file_sync(self, mock_client):
        """Single file tracked — 1 file, N events."""
        from server.mcp.tools.org import org_sync

        mock_daemon = MagicMock()
        mock_daemon.scan.return_value = 3
        mock_daemon.get_status.return_value = {"files_tracked": 1}

        with patch(
            "org_sync_daemon.OrgSyncDaemon",
            return_value=mock_daemon,
        ) as mock_daemon_cls:
            result = org_sync(
                workspace_id="ws-1",
                directory="/tmp/single-org",
                dry_run=True,
            )

        mock_daemon_cls.assert_called_once_with(
            org_dir="/tmp/single-org",
            workspace_id="ws-1",
            client=mock_client,
            dry_run=True,
        )
        assert "[dry-run]" in result
        assert "3" in result
        assert "1 file(s)" in result

    def test_exception_propagation(self, mock_client):
        """Unhandled exception from daemon.scan() propagates to caller."""
        from server.mcp.tools.org import org_sync

        mock_daemon = MagicMock()
        mock_daemon.scan.side_effect = PermissionError("Permission denied: /tmp/org-test")

        with patch(
            "org_sync_daemon.OrgSyncDaemon",
            return_value=mock_daemon,
        ), pytest.raises(PermissionError, match="Permission denied"):
            org_sync(
                workspace_id="ws-1",
                directory="/tmp/org-test",
                dry_run=False,
            )
