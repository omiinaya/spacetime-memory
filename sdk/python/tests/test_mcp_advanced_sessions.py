"""Tests for MCP tools — split from test_mcp_advanced.py."""

import pytest

pytest.skip("requires MCP server runtime (server/mcp/)", allow_module_level=True)

class TestGetPeerSessions:
    """Tests for the get_peer_sessions MCP tool."""

    def test_gets_sessions(self, mock_mcp_client):
        from server.mcp.main import get_peer_sessions

        mock_mcp_client.get_peer_sessions.return_value = [
            {"session_id": "s1", "peer_id": "p1"},
        ]
        result = get_peer_sessions(peer_id="p1")
        assert len(result) == 1
        mock_mcp_client.get_peer_sessions.assert_called_once_with("p1")



# ── TestGetSessionMessages ────────────────────────────────────────────────────────

class TestGetSessionMessages:
    """Tests for the get_session_messages MCP tool."""

    def test_gets_messages(self, mock_mcp_client):
        from server.mcp.main import get_session_messages

        mock_mcp_client.get_session_messages.return_value = [
            {"message_id": "msg1", "content": "Hello"},
        ]
        result = get_session_messages(session_id="s1")
        assert len(result) == 1
        mock_mcp_client.get_session_messages.assert_called_once_with("s1")



# ── TestCreateTour ────────────────────────────────────────────────────────

class TestCreateTour:
    """Tests for the create_tour MCP tool."""

    def test_creates_tour(self, mock_mcp_client):
        from server.mcp.main import create_tour

        result = create_tour(workspace_id="ws1", title="My Tour", description="A guided tour")
        assert "Tour" in result
        assert "My Tour" in result
        mock_mcp_client.create_tour.assert_called_once_with("ws1", "My Tour", "A guided tour")



# ── TestAddTourStop ────────────────────────────────────────────────────────

class TestAddTourStop:
    """Tests for the add_tour_stop MCP tool."""

    def test_adds_stop(self, mock_mcp_client):
        from server.mcp.main import add_tour_stop

        result = add_tour_stop(tour_id="tour1", node_id="n1", heading="Intro", description="Start here")
        assert "Intro" in result
        mock_mcp_client.add_tour_stop.assert_called_once_with("tour1", "n1", "Intro", "Start here")


# ── Fact tools ────────────────────────────────────────────────────────────



# ── TestAddFact ────────────────────────────────────────────────────────

class TestAddFact:
    """Tests for the add_fact MCP tool."""

    def test_adds_fact(self, mock_mcp_client):
        from server.mcp.main import add_fact

        result = add_fact(
            workspace_id="ws1",
            peer_id="p1",
            content="Alice is an AI researcher",
        )
        assert "Fact added" in result
        mock_mcp_client.add_fact.assert_called_once_with(
            "ws1", "p1", "Alice is an AI researcher", "dynamic", "custom", 0.8, "manual", "L1"
        )



# ── TestListFacts ────────────────────────────────────────────────────────

class TestListFacts:
    """Tests for the list_facts MCP tool."""

    def test_lists_facts(self, mock_mcp_client):
        from server.mcp.main import list_facts

        mock_mcp_client.list_facts.return_value = [
            {"json_data": '[{"id": "f1", "content": "Fact 1"}]'}
        ]
        result = list_facts(workspace_id="ws1")
        assert len(result) == 1
        assert result[0]["id"] == "f1"
        mock_mcp_client.list_facts.assert_called_once_with("ws1", "", "", "", "")

    def test_empty(self, mock_mcp_client):
        from server.mcp.main import list_facts

        mock_mcp_client.list_facts.return_value = []
        result = list_facts(workspace_id="ws1")
        assert result == []

    def test_with_filters(self, mock_mcp_client):
        from server.mcp.main import list_facts

        mock_mcp_client.list_facts.return_value = [
            {"json_data": "[]"}
        ]
        list_facts(workspace_id="ws1", peer_id="p1", fact_type="static", tier="L1", category="bio")
        mock_mcp_client.list_facts.assert_called_once_with("ws1", "p1", "static", "L1", "bio")


# ── Directory tools ───────────────────────────────────────────────────────



# ── TestListFactsEdgeCases ────────────────────────────────────────────────────────

class TestListFactsEdgeCases:
    """Tests for edge cases in list_facts MCP tool."""

    def test_json_decode_error_returns_empty(self, mock_mcp_client):
        from server.mcp.main import list_facts

        mock_mcp_client.list_facts.return_value = [
            {"json_data": "not valid json"}
        ]
        result = list_facts(workspace_id="ws1")
        assert result == []

    def test_empty_rows_returns_empty(self, mock_mcp_client):
        from server.mcp.main import list_facts

        mock_mcp_client.list_facts.return_value = []
        result = list_facts(workspace_id="ws1")
        assert result == []



# ── TestSearchFactsEdgeCases ────────────────────────────────────────────────────────

class TestSearchFactsEdgeCases:
    """Tests for edge cases in search_facts MCP tool."""

    def test_json_decode_error_returns_empty(self, mock_mcp_client):
        from server.mcp.main import search_facts

        mock_mcp_client.search_facts.return_value = [
            {"json_data": "not valid json"}
        ]
        result = search_facts(workspace_id="ws1", query="hello")
        assert result == []

    def test_empty_rows_returns_empty(self, mock_mcp_client):
        from server.mcp.main import search_facts

        mock_mcp_client.search_facts.return_value = []
        result = search_facts(workspace_id="ws1", query="hello")
        assert result == []


# ── health_check ──────────────────────────────────────────────────────────
