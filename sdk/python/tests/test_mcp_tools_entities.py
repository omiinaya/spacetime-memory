"""Tests for server/mcp/tools/entities.py — Entity Resolution MCP tools."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ====================================================================
# resolve_entity
# ====================================================================


@pytest.mark.unit
class TestResolveEntity:
    """Tests for the ``resolve_entity`` tool."""

    @patch("server.mcp.tools.entities.get_client")
    def test_resolve_entity_calls_client_method(self, mock_get_client):
        """resolve_entity delegates to get_client().resolve_entity."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.entities import resolve_entity

        result = resolve_entity(workspace_id="ws-1", name="Alice")

        mock_client.resolve_entity.assert_called_once_with("ws-1", "Alice")
        assert "Entity 'Alice' resolved" in result
        assert "ws-1" in result

    @patch("server.mcp.tools.entities.get_client")
    def test_resolve_entity_raises_on_not_found(self, mock_get_client):
        """resolve_entity propagates client exception on resolution failure."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.resolve_entity.side_effect = ValueError(
            "Entity 'Unknown' not found"
        )

        from server.mcp.tools.entities import resolve_entity

        with pytest.raises(ValueError, match="not found"):
            resolve_entity(workspace_id="ws-1", name="Unknown")

    @patch("server.mcp.tools.entities.get_client")
    def test_resolve_entity_raises_on_permission_error(self, mock_get_client):
        """resolve_entity propagates PermissionError from client."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.resolve_entity.side_effect = PermissionError(
            "Unauthorized"
        )

        from server.mcp.tools.entities import resolve_entity

        with pytest.raises(PermissionError):
            resolve_entity(workspace_id="ws-1", name="Alice")

    @patch("server.mcp.tools.entities.get_client")
    def test_resolve_entity_with_empty_name(self, mock_get_client):
        """resolve_entity handles empty name string."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.entities import resolve_entity

        result = resolve_entity(workspace_id="ws-1", name="")

        mock_client.resolve_entity.assert_called_once_with("ws-1", "")
        assert "Entity '' resolved" in result

    @patch("server.mcp.tools.entities.get_client")
    def test_resolve_entity_with_special_chars(self, mock_get_client):
        """resolve_entity handles special characters in name."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.entities import resolve_entity

        name = "Alice 😊 Müller-Schmidt (a.k.a. \"The Boss\")"
        result = resolve_entity(workspace_id="ws-1", name=name)

        mock_client.resolve_entity.assert_called_once_with("ws-1", name)
        assert "Entity 'Alice" in result
        assert "resolved" in result

    @patch("server.mcp.tools.entities.get_client")
    def test_resolve_entity_with_long_name(self, mock_get_client):
        """resolve_entity handles very long entity names."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.entities import resolve_entity

        long_name = "A" * 5000
        result = resolve_entity(workspace_id="ws-1", name=long_name)

        mock_client.resolve_entity.assert_called_once_with("ws-1", long_name)
        assert "Entity '" in result
        assert "resolved" in result

    @patch("server.mcp.tools.entities.get_client")
    def test_resolve_entity_with_empty_workspace(self, mock_get_client):
        """resolve_entity handles empty workspace_id."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.entities import resolve_entity

        result = resolve_entity(workspace_id="", name="Alice")

        mock_client.resolve_entity.assert_called_once_with("", "Alice")
        assert "" in result


# ====================================================================
# add_alias
# ====================================================================


@pytest.mark.unit
class TestAddAlias:
    """Tests for the ``add_alias`` tool."""

    @patch("server.mcp.tools.entities.get_client")
    def test_add_alias_calls_client_method(self, mock_get_client):
        """add_alias delegates to get_client().add_alias."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.entities import add_alias

        entity_link_id = "link-abc-123"
        result = add_alias(entity_link_id=entity_link_id, alias="Bobby")

        mock_client.add_alias.assert_called_once_with(entity_link_id, "Bobby")
        assert "Alias 'Bobby' added" in result
        assert "link-abc-123" in result

    @patch("server.mcp.tools.entities.get_client")
    def test_add_alias_raises_on_conflict(self, mock_get_client):
        """add_alias propagates exception on alias conflict."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.add_alias.side_effect = ValueError(
            "Alias 'Bobby' already exists for this entity link"
        )

        from server.mcp.tools.entities import add_alias

        with pytest.raises(ValueError, match="already exists"):
            add_alias(entity_link_id="link-abc-123", alias="Bobby")

    @patch("server.mcp.tools.entities.get_client")
    def test_add_alias_raises_on_invalid_link_id(self, mock_get_client):
        """add_alias propagates exception on invalid entity link ID."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.add_alias.side_effect = ValueError(
            "Entity link 'bad-link' not found"
        )

        from server.mcp.tools.entities import add_alias

        with pytest.raises(ValueError, match="not found"):
            add_alias(entity_link_id="bad-link", alias="Bobby")

    @patch("server.mcp.tools.entities.get_client")
    def test_add_alias_with_special_chars(self, mock_get_client):
        """add_alias handles aliases with special characters."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.entities import add_alias

        alias = "🌟 Star-Player 🏆 (MVP!)"
        entity_link_id = "link-xyz"
        result = add_alias(entity_link_id=entity_link_id, alias=alias)

        mock_client.add_alias.assert_called_once_with(entity_link_id, alias)
        assert "Alias '🌟 Star-Player" in result
        assert "added" in result

    @patch("server.mcp.tools.entities.get_client")
    def test_add_alias_with_long_alias(self, mock_get_client):
        """add_alias handles very long alias strings."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.entities import add_alias

        long_alias = "x" * 5000
        result = add_alias(entity_link_id="link-1", alias=long_alias)

        mock_client.add_alias.assert_called_once_with("link-1", long_alias)
        assert "Alias '" in result

    @patch("server.mcp.tools.entities.get_client")
    def test_add_alias_with_empty_alias(self, mock_get_client):
        """add_alias handles empty alias string."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.entities import add_alias

        result = add_alias(entity_link_id="link-1", alias="")

        mock_client.add_alias.assert_called_once_with("link-1", "")
        assert "Alias '' added" in result

    @patch("server.mcp.tools.entities.get_client")
    def test_add_alias_truncated_link_id_in_message(self, mock_get_client):
        """add_alias message shows first 16 chars of entity_link_id."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.entities import add_alias

        link_id = "a-very-long-link-id-that-should-be-truncated"
        result = add_alias(entity_link_id=link_id, alias="test alias")

        # The entity_link_id[:16] appears in the message
        assert link_id[:16] in result
        # Full ID should NOT appear
        assert link_id[16:] not in result


# ====================================================================
# create_entity_link
# ====================================================================


@pytest.mark.unit
class TestCreateEntityLink:
    """Tests for the ``create_entity_link`` tool."""

    @patch("server.mcp.tools.entities.get_client")
    def test_create_entity_link_calls_client_method(self, mock_get_client):
        """create_entity_link delegates to get_client().create_entity_link."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.entities import create_entity_link

        result = create_entity_link(
            workspace_id="ws-42",
            canonical_name="Alice Smith",
            entity_type="person",
            description="A test user",
        )

        mock_client.create_entity_link.assert_called_once_with(
            "ws-42", "Alice Smith", "person", "A test user"
        )
        assert "Entity link 'Alice Smith' created" in result
        assert "ws-42" in result

    @patch("server.mcp.tools.entities.get_client")
    def test_create_entity_link_with_default_description(self, mock_get_client):
        """create_entity_link uses empty string as default description."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.entities import create_entity_link

        create_entity_link(
            workspace_id="ws-1",
            canonical_name="Bob",
            entity_type="person",
        )

        mock_client.create_entity_link.assert_called_once_with(
            "ws-1", "Bob", "person", ""
        )

    @patch("server.mcp.tools.entities.get_client")
    def test_create_entity_link_raises_on_invalid_workspace(self, mock_get_client):
        """create_entity_link propagates exception on invalid workspace."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.create_entity_link.side_effect = ValueError(
            "Workspace 'bad-ws' not found"
        )

        from server.mcp.tools.entities import create_entity_link

        with pytest.raises(ValueError, match="not found"):
            create_entity_link(
                workspace_id="bad-ws",
                canonical_name="Test",
                entity_type="person",
            )

    @patch("server.mcp.tools.entities.get_client")
    def test_create_entity_link_raises_on_duplicate(self, mock_get_client):
        """create_entity_link propagates exception on duplicate entity link."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.create_entity_link.side_effect = ValueError(
            "Entity link 'Test' already exists"
        )

        from server.mcp.tools.entities import create_entity_link

        with pytest.raises(ValueError, match="already exists"):
            create_entity_link(
                workspace_id="ws-1",
                canonical_name="Test",
                entity_type="person",
            )

    @patch("server.mcp.tools.entities.get_client")
    def test_create_entity_link_with_special_chars(self, mock_get_client):
        """create_entity_link handles special characters in names."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.entities import create_entity_link

        name = "José \"Pepe\" García ⚡"
        result = create_entity_link(
            workspace_id="ws-1",
            canonical_name=name,
            entity_type="person",
            description="Usuario con caracteres especiales 🎉",
        )

        mock_client.create_entity_link.assert_called_once_with(
            "ws-1", name, "person", "Usuario con caracteres especiales 🎉"
        )
        assert "Entity link 'José" in result

    @patch("server.mcp.tools.entities.get_client")
    def test_create_entity_link_truncated_workspace_in_message(self, mock_get_client):
        """create_entity_link message shows first 16 chars of workspace_id."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from server.mcp.tools.entities import create_entity_link

        ws_id = "a-very-long-workspace-id-that-is-over-16-chars"
        result = create_entity_link(
            workspace_id=ws_id,
            canonical_name="Test",
            entity_type="concept",
        )

        assert ws_id[:16] in result
        assert ws_id[16:] not in result


# ====================================================================
# search_entities  (from compounder.py — entity search with list results)
# ====================================================================


@pytest.mark.unit
class TestSearchEntities:
    """Tests for the ``search_entities`` tool in compounder.py."""

    @patch("server.mcp.tools.compounder.get_client")
    @patch("spacetime_memory.compounder.Compounder")
    def test_search_entities_empty_results(
        self, mock_compounder_cls, mock_get_client
    ):
        """search_entities returns 'No entities found.' for empty results."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        cp_mock = MagicMock()
        cp_mock.search_entities.return_value = []
        mock_compounder_cls.return_value = cp_mock

        from server.mcp.tools.compounder import search_entities

        result = search_entities(
            workspace_id="default",
            label="NonExistent",
            node_type="",
            semantic_query="",
            limit=20,
        )

        mock_compounder_cls.assert_called_once_with(mock_client)
        cp_mock.search_entities.assert_called_once_with(
            workspace_id="default",
            label="NonExistent",
            node_type=None,
            semantic_query=None,
            limit=20,
        )
        assert result == "No entities found."

    @patch("server.mcp.tools.compounder.get_client")
    @patch("spacetime_memory.compounder.Compounder")
    def test_search_entities_with_results(
        self, mock_compounder_cls, mock_get_client
    ):
        """search_entities formats results correctly."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        results = [
            {
                "id": "abc123def456",
                "label": "Alice Smith",
                "node_type": "person",
                "summary": "A test user entity",
            },
            {
                "id": "xyz789",
                "label": "Bob Corp",
                "node_type": "org",
                "summary": "A business entity",
            },
        ]
        cp_mock = MagicMock()
        cp_mock.search_entities.return_value = results
        mock_compounder_cls.return_value = cp_mock

        from server.mcp.tools.compounder import search_entities

        result = search_entities(
            workspace_id="default",
            label="",
            node_type="",
            semantic_query="",
            limit=5,
        )

        mock_compounder_cls.assert_called_once_with(mock_client)
        cp_mock.search_entities.assert_called_once_with(
            workspace_id="default",
            label=None,
            node_type=None,
            semantic_query=None,
            limit=5,
        )
        assert "Found 2 entities:" in result
        assert "Alice Smith" in result
        assert "Bob Corp" in result
        assert "[person]" in result
        assert "[org]" in result

    @patch("server.mcp.tools.compounder.get_client")
    @patch("spacetime_memory.compounder.Compounder")
    def test_search_entities_no_match_in_workspace(
        self, mock_compounder_cls, mock_get_client
    ):
        """search_entities returns empty message when no entities match."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        cp_mock = MagicMock()
        cp_mock.search_entities.return_value = []
        mock_compounder_cls.return_value = cp_mock

        from server.mcp.tools.compounder import search_entities

        result = search_entities(
            workspace_id="empty-ws",
            label="Anything",
            node_type="person",
            semantic_query="",
            limit=10,
        )

        mock_compounder_cls.assert_called_once_with(mock_client)
        cp_mock.search_entities.assert_called_once_with(
            workspace_id="empty-ws",
            label="Anything",
            node_type="person",
            semantic_query=None,
            limit=10,
        )
        assert result == "No entities found."

    @patch("server.mcp.tools.compounder.get_client")
    @patch("spacetime_memory.compounder.Compounder")
    def test_search_entities_with_missing_fields(
        self, mock_compounder_cls, mock_get_client
    ):
        """search_entities handles results with missing optional fields."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        results = [
            {
                "id": "minimal-id-12345",
                "label": "Minimal",
                # no node_type, no summary
            },
        ]
        cp_mock = MagicMock()
        cp_mock.search_entities.return_value = results
        mock_compounder_cls.return_value = cp_mock

        from server.mcp.tools.compounder import search_entities

        result = search_entities(
            workspace_id="default",
            label="Minimal",
        )

        mock_compounder_cls.assert_called_once_with(mock_client)
        cp_mock.search_entities.assert_called_once()
        assert "Found 1 entities:" in result
        assert "Minimal" in result
        assert "[?]" in result  # missing node_type defaults to '?'

    @patch("server.mcp.tools.compounder.get_client")
    @patch("spacetime_memory.compounder.Compounder")
    def test_search_entities_raises_on_client_error(
        self, mock_compounder_cls, mock_get_client
    ):
        """search_entities propagates client exceptions."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        cp_mock = MagicMock()
        cp_mock.search_entities.side_effect = ValueError(
            "Workspace not found"
        )
        mock_compounder_cls.return_value = cp_mock

        from server.mcp.tools.compounder import search_entities

        with pytest.raises(ValueError, match="Workspace not found"):
            search_entities(workspace_id="bad-ws")
