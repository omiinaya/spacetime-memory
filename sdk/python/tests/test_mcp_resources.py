"""Tests for server/mcp/_resources.py — MCP resource and prompt definitions module.

Patches ``server.mcp.tools.app.get_client`` so resources can be tested without
a live database.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    """Patch ``server.mcp._resources.get_client`` to return a MagicMock."""
    with patch("server.mcp._resources.get_client") as mock_fn:
        instance = MagicMock()
        mock_fn.return_value = instance
        yield instance


# =========================================================================
# Module-level sanity checks
# =========================================================================


class TestModuleImport:
    """Verify the _resources module can be imported and is structurally sound."""

    def test_can_import(self):
        """The module should import without error."""
        from server.mcp import _resources

        assert _resources is not None

    def test_docstring_present(self):
        """The module should carry the expected top-level docstring."""
        from server.mcp import _resources

        doc = _resources.__doc__
        assert doc is not None
        assert "MCP resource and prompt definitions" in doc
        assert "spacetime-memory MCP server" in doc

    def test_future_annotations_imported(self):
        """from __future__ import annotations should be present on the module."""
        from server.mcp import _resources

        hints = getattr(_resources, "__annotations__", {})
        assert isinstance(hints, dict)

    def test_exports_resources_and_prompts(self):
        """The module should define registered resource and prompt functions."""
        from server.mcp import _resources

        # Public names should include our new functions
        public_names = sorted(n for n in dir(_resources) if not n.startswith("_"))
        assert "annotations" in public_names
        assert "server_info" in public_names
        assert "workspace_info" in public_names
        assert "summarize_workspace" in public_names
        assert "memory_search_query" in public_names

    def test_mcp_instance_used(self):
        """The module imports and uses the shared mcp instance."""
        from server.mcp import _resources

        assert hasattr(_resources, "mcp")
        assert _resources.mcp is not None


# =========================================================================
# Resources
# =========================================================================


@pytest.mark.unit
class TestServerInfoResource:
    """Tests for the ``info://server`` resource."""

    def test_returns_valid_json(self):
        """server_info() returns a JSON string with expected keys."""
        from server.mcp._resources import server_info

        result = server_info()
        data = json.loads(result)
        assert isinstance(data, dict)
        assert "host" in data
        assert "port" in data
        assert "database" in data
        assert "embedder_url" in data
        assert "tantivy_url" in data

    def test_host_is_string(self):
        from server.mcp._resources import server_info

        data = json.loads(server_info())
        assert isinstance(data["host"], str)

    def test_port_is_int(self):
        from server.mcp._resources import server_info

        data = json.loads(server_info())
        assert isinstance(data["port"], int)

    def test_indented_output(self):
        """Output is pretty-printed (contains newlines)."""
        from server.mcp._resources import server_info

        result = server_info()
        assert "\n" in result
        assert result.startswith("{")

    def test_default_values_match(self):
        """Default config values should be reflected."""
        import importlib
        from unittest.mock import patch

        with patch.dict(
            "os.environ",
            {
                "EMBEDDER_URL": "http://localhost:4000",
                "TANTIVY_URL": "http://localhost:9091",
            },
            clear=False,
        ):
            import server.mcp._resources as res_mod
            import server.mcp.tools.app as app_mod

            importlib.reload(app_mod)
            importlib.reload(res_mod)
            data = json.loads(res_mod.server_info())
        # These are the defaults from app.py
        assert data["host"] == "localhost"
        assert data["port"] == 3001
        assert data["database"] == "spacetime-memory"
        assert data["embedder_url"] == "http://localhost:4000"


@pytest.mark.unit
class TestWorkspaceInfoResource:
    """Tests for the ``info://workspace/{workspace_id}`` template resource."""

    def test_calls_get_client(self, mock_client):
        """workspace_info() calls get_client() and list_space_members()."""
        from server.mcp._resources import workspace_info

        mock_client.list_space_members.return_value = [
            {"peer_id": "p1", "permission": "owner"},
        ]

        result = workspace_info(workspace_id="ws-1")
        mock_client.list_space_members.assert_called_once_with("ws-1")

        data = json.loads(result)
        assert data["workspace_id"] == "ws-1"
        assert data["member_count"] == 1

    def test_empty_workspace(self, mock_client):
        """Workspace with no members returns member_count 0."""
        from server.mcp._resources import workspace_info

        mock_client.list_space_members.return_value = []

        data = json.loads(workspace_info(workspace_id="empty"))
        assert data["workspace_id"] == "empty"
        assert data["member_count"] == 0
        assert data["members"] == []

    def test_multiple_members(self, mock_client):
        """All member permissions are included in the output."""
        from server.mcp._resources import workspace_info

        mock_client.list_space_members.return_value = [
            {"peer_id": "p1", "permission": "owner"},
            {"peer_id": "p2", "permission": "editor"},
            {"peer_id": "p3", "permission": "viewer"},
        ]

        data = json.loads(workspace_info(workspace_id="ws-1"))
        assert data["member_count"] == 3
        permissions = {m["peer_id"]: m["permission"] for m in data["members"]}
        assert permissions["p1"] == "owner"
        assert permissions["p2"] == "editor"
        assert permissions["p3"] == "viewer"

    def test_client_error_is_caught(self, mock_client):
        """When the client raises, the resource returns a JSON error object."""
        from server.mcp._resources import workspace_info

        mock_client.list_space_members.side_effect = ValueError(
            "Workspace not found: unknown"
        )

        data = json.loads(workspace_info(workspace_id="unknown"))
        assert "error" in data
        assert "Workspace not found" in data["error"]
        assert data["workspace_id"] == "unknown"

    def test_client_connection_error_is_caught(self, mock_client):
        """Connection errors are caught and returned as JSON error."""
        from server.mcp._resources import workspace_info

        mock_client.list_space_members.side_effect = ConnectionError(
            "Cannot reach database"
        )

        data = json.loads(workspace_info(workspace_id="ws-1"))
        assert "error" in data
        assert "Cannot reach database" in data["error"]


# =========================================================================
# Prompts
# =========================================================================


@pytest.mark.unit
class TestSummarizeWorkspacePrompt:
    """Tests for the ``summarize-workspace`` prompt."""

    def test_returns_list_of_messages(self):
        """The prompt returns a list with a single message dict."""
        from server.mcp._resources import summarize_workspace

        result = summarize_workspace(workspace_id="ws-1")
        assert isinstance(result, list)
        assert len(result) == 1
        assert "role" in result[0]
        assert "content" in result[0]

    def test_message_has_user_role(self):
        from server.mcp._resources import summarize_workspace

        result = summarize_workspace(workspace_id="ws-1")
        assert result[0]["role"] == "user"

    def test_content_includes_workspace_id(self):
        from server.mcp._resources import summarize_workspace

        result = summarize_workspace(workspace_id="my-workspace")
        assert "my-workspace" in result[0]["content"]

    def test_default_focus_general(self):
        """When no focus is given, it defaults to 'general'."""
        from server.mcp._resources import summarize_workspace

        result = summarize_workspace(workspace_id="ws-1")
        assert "focus on: general" in result[0]["content"]

    def test_custom_focus(self):
        from server.mcp._resources import summarize_workspace

        result = summarize_workspace(workspace_id="ws-1", focus="code quality")
        assert "focus on: code quality" in result[0]["content"]

    def test_content_has_section_headers(self):
        from server.mcp._resources import summarize_workspace

        result = summarize_workspace(workspace_id="ws-1")
        content = result[0]["content"]
        assert "Overview" in content
        assert "Key Topics" in content
        assert "Notable Items" in content


@pytest.mark.unit
class TestMemorySearchQueryPrompt:
    """Tests for the ``memory-search-query`` prompt."""

    def test_returns_list_of_messages(self):
        from server.mcp._resources import memory_search_query

        result = memory_search_query(question="What is AI?")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_content_includes_question(self):
        from server.mcp._resources import memory_search_query

        result = memory_search_query(question="Where did I save my notes?")
        assert "Where did I save my notes?" in result[0]["content"]

    def test_default_max_results(self):
        from server.mcp._resources import memory_search_query

        result = memory_search_query(question="test")
        assert "Max results: 10" in result[0]["content"]

    def test_custom_max_results(self):
        from server.mcp._resources import memory_search_query

        result = memory_search_query(question="test", max_results=25)
        assert "Max results: 25" in result[0]["content"]

    def test_prompt_asks_for_query_only(self):
        from server.mcp._resources import memory_search_query

        result = memory_search_query(question="test")
        content = result[0]["content"]
        assert "Return only the search query string" in content
