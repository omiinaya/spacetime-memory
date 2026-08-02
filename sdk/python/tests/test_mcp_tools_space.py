"""Tests for server/mcp/tools/space.py MCP tools.

Patches ``server.mcp.tools.app.get_client`` to verify delegation.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    """Patch ``server.mcp.tools.space.get_client`` to return a MagicMock."""
    with patch("server.mcp.tools.space.get_client") as mock_fn:
        instance = MagicMock()
        mock_fn.return_value = instance
        yield instance


# =========================================================================
# grant_space_access
# =========================================================================


@pytest.mark.unit
class TestGrantSpaceAccess:
    """Tests for ``grant_space_access``."""

    def test_delegation(self, mock_client):
        from server.mcp.tools.space import grant_space_access

        result = grant_space_access(
            workspace_id="ws-1",
            peer_id="p1",
            permission="editor",
        )
        mock_client.grant_space_access.assert_called_once_with(
            "ws-1", "p1", "editor"
        )
        assert "Granted" in result
        assert "editor" in result
        assert "ws-1" in result

    def test_long_ids_truncated_in_message(self, mock_client):
        """IDs longer than 16 chars are truncated with '...' in the return message."""
        from server.mcp.tools.space import grant_space_access

        long_ws = "a" * 40
        long_peer = "b" * 40
        result = grant_space_access(
            workspace_id=long_ws,
            peer_id=long_peer,
            permission="viewer",
        )
        mock_client.grant_space_access.assert_called_once_with(
            long_ws, long_peer, "viewer"
        )
        # Message should contain truncated versions
        assert "aaaaaaaaaaaaaaaa..." in result  # 16 chars + ...
        assert "bbbbbbbbbbbbbbbb..." in result
        assert "Granted" in result

    def test_empty_workspace_id(self, mock_client):
        """Empty workspace ID is passed through to the client."""
        from server.mcp.tools.space import grant_space_access

        result = grant_space_access(
            workspace_id="",
            peer_id="p1",
            permission="editor",
        )
        mock_client.grant_space_access.assert_called_once_with(
            "", "p1", "editor"
        )
        # Empty ID truncates to empty string + "..." in message
        assert "...' for workspace '...'" in result

    def test_empty_peer_id(self, mock_client):
        """Empty peer ID is passed through to the client."""
        from server.mcp.tools.space import grant_space_access

        result = grant_space_access(
            workspace_id="ws-1",
            peer_id="",
            permission="viewer",
        )
        mock_client.grant_space_access.assert_called_once_with(
            "ws-1", "", "viewer"
        )
        assert "access to peer '...'" in result

    @pytest.mark.parametrize(
        "invalid_permission",
        ["", "admin", "write", "read", None],
    )
    def test_invalid_permission(self, mock_client, invalid_permission):
        """Invalid permission values are passed through; the client raises."""
        from server.mcp.tools.space import grant_space_access

        mock_client.grant_space_access.side_effect = ValueError(
            f"Invalid permission: {invalid_permission!r}"
        )

        with pytest.raises(ValueError, match="Invalid permission"):
            grant_space_access(
                workspace_id="ws-1",
                peer_id="p1",
                permission=invalid_permission,
            )
        mock_client.grant_space_access.assert_called_once_with(
            "ws-1", "p1", invalid_permission
        )

    def test_client_connection_error(self, mock_client):
        """Network/DB error from client is propagated."""
        from server.mcp.tools.space import grant_space_access

        mock_client.grant_space_access.side_effect = ConnectionError(
            "Cannot reach database"
        )

        with pytest.raises(ConnectionError, match="Cannot reach database"):
            grant_space_access(
                workspace_id="ws-1",
                peer_id="p1",
                permission="editor",
            )


# =========================================================================
# revoke_space_access
# =========================================================================


@pytest.mark.unit
class TestRevokeSpaceAccess:
    """Tests for ``revoke_space_access``."""

    def test_delegation(self, mock_client):
        from server.mcp.tools.space import revoke_space_access

        result = revoke_space_access(
            workspace_id="ws-1",
            peer_id="p1",
        )
        mock_client.revoke_space_access.assert_called_once_with(
            "ws-1", "p1"
        )
        assert "Revoked" in result
        assert "ws-1" in result

    def test_empty_workspace_id(self, mock_client):
        """Empty workspace ID is passed through."""
        from server.mcp.tools.space import revoke_space_access

        result = revoke_space_access(workspace_id="", peer_id="p1")
        mock_client.revoke_space_access.assert_called_once_with("", "p1")
        assert "Revoked" in result

    def test_empty_peer_id(self, mock_client):
        """Empty peer ID is passed through."""
        from server.mcp.tools.space import revoke_space_access

        result = revoke_space_access(workspace_id="ws-1", peer_id="")
        mock_client.revoke_space_access.assert_called_once_with("ws-1", "")
        assert "Revoked" in result

    def test_long_ids_truncated(self, mock_client):
        """Long IDs are truncated in the return message."""
        from server.mcp.tools.space import revoke_space_access

        long_ws = "x" * 30
        long_peer = "y" * 30
        result = revoke_space_access(
            workspace_id=long_ws,
            peer_id=long_peer,
        )
        mock_client.revoke_space_access.assert_called_once_with(
            long_ws, long_peer
        )
        assert "xxxxxxxxxxxxxxxx..." in result
        assert "yyyyyyyyyyyyyyyy..." in result

    def test_client_error_propagated(self, mock_client):
        """Client exception propagates through the tool."""
        from server.mcp.tools.space import revoke_space_access

        mock_client.revoke_space_access.side_effect = PermissionError(
            "Not an owner"
        )
        with pytest.raises(PermissionError, match="Not an owner"):
            revoke_space_access(workspace_id="ws-1", peer_id="p1")


# =========================================================================
# list_space_members
# =========================================================================


@pytest.mark.unit
class TestListSpaceMembers:
    """Tests for ``list_space_members``."""

    def test_returns_list(self, mock_client):
        from server.mcp.tools.space import list_space_members

        mock_client.list_space_members.return_value = [
            {"peer_id": "p1", "permission": "owner"},
        ]
        result = list_space_members(workspace_id="ws-1")
        mock_client.list_space_members.assert_called_once_with("ws-1")
        assert result[0]["peer_id"] == "p1"

    def test_empty(self, mock_client):
        from server.mcp.tools.space import list_space_members

        mock_client.list_space_members.return_value = []
        result = list_space_members(workspace_id="empty")
        assert result == []

    def test_multiple_members(self, mock_client):
        """Returns all members including owners, editors, viewers."""
        from server.mcp.tools.space import list_space_members

        mock_client.list_space_members.return_value = [
            {"peer_id": "p1", "permission": "owner"},
            {"peer_id": "p2", "permission": "editor"},
            {"peer_id": "p3", "permission": "viewer"},
        ]
        result = list_space_members(workspace_id="ws-1")
        assert len(result) == 3
        assert result[0]["permission"] == "owner"
        assert result[1]["permission"] == "editor"
        assert result[2]["permission"] == "viewer"

    def test_members_with_extra_fields(self, mock_client):
        """Members may include optional fields (granted_by, created_at)."""
        from server.mcp.tools.space import list_space_members

        mock_client.list_space_members.return_value = [
            {
                "peer_id": "p1",
                "permission": "owner",
                "granted_by": "admin",
                "created_at": "2025-01-01T00:00:00Z",
            },
        ]
        result = list_space_members(workspace_id="ws-1")
        assert result[0]["granted_by"] == "admin"
        assert result[0]["created_at"] == "2025-01-01T00:00:00Z"

    def test_empty_workspace_id(self, mock_client):
        """Empty workspace ID is passed through."""
        from server.mcp.tools.space import list_space_members

        mock_client.list_space_members.return_value = []
        result = list_space_members(workspace_id="")
        mock_client.list_space_members.assert_called_once_with("")
        assert result == []

    def test_nonexistent_workspace(self, mock_client):
        """Non-existent workspace raises an error from the client."""
        from server.mcp.tools.space import list_space_members

        mock_client.list_space_members.side_effect = ValueError(
            "Workspace not found: unknown"
        )

        with pytest.raises(ValueError, match="Workspace not found"):
            list_space_members(workspace_id="unknown")
