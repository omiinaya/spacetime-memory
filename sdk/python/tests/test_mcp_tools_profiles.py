"""Tests for server/mcp/tools/profiles.py MCP tools.

Patches ``server.mcp.tools.app.get_client`` to verify delegation.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    """Patch ``server.mcp.tools.profiles.get_client`` to return a MagicMock."""
    with patch("server.mcp.tools.profiles.get_client") as mock_fn:
        instance = MagicMock()
        mock_fn.return_value = instance
        yield instance


# ---------------------------------------------------------------------------
# get_profile
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetProfile:
    """Tests for ``get_profile``."""

    def test_returns_list(self, mock_client):
        from server.mcp.tools.profiles import get_profile

        mock_client.get_profile.return_value = [
            {"peer_id": "p1", "name": "Alice"},
        ]
        result = get_profile(peer_id="p1")
        mock_client.get_profile.assert_called_once_with("p1")
        assert result[0]["peer_id"] == "p1"


# ---------------------------------------------------------------------------
# upsert_profile
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpsertProfile:
    """Tests for ``upsert_profile``."""

    def test_with_defaults(self, mock_client):
        from server.mcp.tools.profiles import upsert_profile

        mock_client.upsert_profile.return_value = {"status": "ok"}
        result = upsert_profile(peer_id="p1")
        mock_client.upsert_profile.assert_called_once_with(
            "p1", "[]", "[]", "{}", "[]"
        )
        assert result == {"status": "ok"}

    def test_custom_values(self, mock_client):
        from server.mcp.tools.profiles import upsert_profile

        mock_client.upsert_profile.return_value = {"status": "created"}
        result = upsert_profile(
            peer_id="p1",
            static_facts_json='["fact1"]',
            dynamic_context_json='["ctx1"]',
            preferences_json='{"theme":"dark"}',
            tags_json='["admin"]',
        )
        mock_client.upsert_profile.assert_called_once_with(
            "p1", '["fact1"]', '["ctx1"]', '{"theme":"dark"}', '["admin"]'
        )
        assert result == {"status": "created"}


# ---------------------------------------------------------------------------
# list_profiles
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListProfiles:
    """Tests for ``list_profiles``."""

    def test_returns_list(self, mock_client):
        from server.mcp.tools.profiles import list_profiles

        mock_client.list_profiles.return_value = [
            {"peer_id": "p1", "static_facts": ["fact_a"]},
        ]
        result = list_profiles(workspace_id="ws-1")
        mock_client.list_profiles.assert_called_once_with("ws-1")
        assert result[0]["peer_id"] == "p1"


# ---------------------------------------------------------------------------
# add_dynamic_context
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddDynamicContext:
    """Tests for ``add_dynamic_context``."""

    def test_message(self, mock_client):
        from server.mcp.tools.profiles import add_dynamic_context

        result = add_dynamic_context(peer_id="p1", context="working on task X")
        mock_client.add_dynamic_context.assert_called_once_with(
            "p1", "working on task X"
        )
        assert "Dynamic context added" in result
        assert "p1" in result


# ---------------------------------------------------------------------------
# add_profile_fact
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddProfileFact:
    """Tests for ``add_profile_fact``."""

    def test_message(self, mock_client):
        from server.mcp.tools.profiles import add_profile_fact

        result = add_profile_fact(peer_id="p1", fact="likes Python")
        mock_client.add_profile_fact.assert_called_once_with(
            "p1", "likes Python"
        )
        assert "Profile fact added" in result
        assert "p1" in result


# ---------------------------------------------------------------------------
# get_profile_context
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetProfileContext:
    """Tests for ``get_profile_context``."""

    def test_with_rows(self, mock_client):
        from server.mcp.tools.profiles import get_profile_context

        mock_client.get_profile_context.return_value = {"key": "value"}
        result = get_profile_context(peer_id="p1")
        mock_client.get_profile_context.assert_called_once_with("p1")
        assert result == [{"key": "value"}]

    def test_empty(self, mock_client):
        from server.mcp.tools.profiles import get_profile_context

        mock_client.get_profile_context.return_value = None
        result = get_profile_context(peer_id="p1")
        assert result == []


# ---------------------------------------------------------------------------
# get_peer_reputation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPeerReputation:
    """Tests for ``get_peer_reputation``."""

    def test_with_data(self, mock_client):
        from server.mcp.tools.profiles import get_peer_reputation

        mock_client.get_peer_reputation.return_value = {
            "peer_id": "p1",
            "reputation_score": 4.5,
        }
        result = get_peer_reputation(peer_id="p1")
        mock_client.get_peer_reputation.assert_called_once_with("p1")
        assert result["reputation_score"] == 4.5

    def test_none(self, mock_client):
        from server.mcp.tools.profiles import get_peer_reputation

        mock_client.get_peer_reputation.return_value = None
        result = get_peer_reputation(peer_id="unknown")
        assert result is None


# ---------------------------------------------------------------------------
# run_maintenance
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunMaintenance:
    """Tests for ``run_maintenance``."""

    def test_delegation(self, mock_client):
        from server.mcp.tools.profiles import run_maintenance

        mock_client.run_maintenance.return_value = {
            "expired": 5,
            "decayed": 3,
            "deduped": 1,
        }
        result = run_maintenance()
        mock_client.run_maintenance.assert_called_once_with()
        assert result["expired"] == 5


# ---------------------------------------------------------------------------
# expire_memories
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExpireMemories:
    """Tests for ``expire_memories``."""

    def test_delegation(self, mock_client):
        from server.mcp.tools.profiles import expire_memories

        mock_client.expire_memories.return_value = {"status": "ok"}
        result = expire_memories()
        mock_client.expire_memories.assert_called_once_with()
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# check_embedder_health
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckEmbedderHealth:
    """Tests for ``check_embedder_health``."""

    def test_delegation(self, mock_client):
        from server.mcp.tools.profiles import check_embedder_health

        mock_client.check_embedder_health.return_value = {
            "reachable": True,
            "model": "text-embedding-3-small",
        }
        result = check_embedder_health()
        mock_client.check_embedder_health.assert_called_once_with()
        assert result["reachable"] is True


# ---------------------------------------------------------------------------
# add_fact
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddFact:
    """Tests for ``add_fact``."""

    def test_with_defaults(self, mock_client):
        from server.mcp.tools.profiles import add_fact

        result = add_fact(workspace_id="ws-1", peer_id="p1", content="fact text")
        mock_client.add_fact.assert_called_once_with(
            "ws-1", "p1", "fact text", "dynamic", "custom", 0.8, "manual", "L1"
        )
        assert "Fact added" in result

    def test_custom_params(self, mock_client):
        from server.mcp.tools.profiles import add_fact

        result = add_fact(
            workspace_id="ws-1",
            peer_id="p1",
            content="important fact",
            fact_type="static",
            category="biography",
            confidence=0.95,
            source="interview",
            tier="L2",
        )
        mock_client.add_fact.assert_called_once_with(
            "ws-1", "p1", "important fact",
            "static", "biography", 0.95, "interview", "L2",
        )
        assert "Fact added" in result


# ---------------------------------------------------------------------------
# list_facts
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListFacts:
    """Tests for ``list_facts``."""

    def test_with_filters(self, mock_client):
        from server.mcp.tools.profiles import list_facts

        mock_client.list_facts.return_value = [
            {"json_data": '[{"id":"f1","content":"test"}]'}
        ]
        result = list_facts(
            workspace_id="ws-1",
            peer_id="p1",
            fact_type="dynamic",
            tier="L1",
            category="custom",
        )
        mock_client.list_facts.assert_called_once_with(
            "ws-1", "p1", "dynamic", "L1", "custom"
        )
        assert result == [{"id": "f1", "content": "test"}]

    def test_empty(self, mock_client):
        from server.mcp.tools.profiles import list_facts

        mock_client.list_facts.return_value = []
        result = list_facts(workspace_id="ws-1")
        assert result == []

    def test_no_json_data(self, mock_client):
        from server.mcp.tools.profiles import list_facts

        mock_client.list_facts.return_value = [{}]
        result = list_facts(workspace_id="ws-1")
        assert result == []


# ---------------------------------------------------------------------------
# delete_fact
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteFact:
    """Tests for ``delete_fact``."""

    def test_message(self, mock_client):
        from server.mcp.tools.profiles import delete_fact

        result = delete_fact(fact_id="f-123")
        mock_client.delete_fact.assert_called_once_with("f-123")
        assert "deactivated" in result


# ---------------------------------------------------------------------------
# update_fact
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateFact:
    """Tests for ``update_fact``."""

    def test_all_params(self, mock_client):
        from server.mcp.tools.profiles import update_fact

        result = update_fact(
            fact_id="f-1",
            content="new content",
            confidence=0.9,
            category="updated",
            tier="L3",
        )
        mock_client.update_fact.assert_called_once_with(
            "f-1", "new content", 0.9, "updated", "L3"
        )
        assert "updated" in result

    def test_defaults(self, mock_client):
        from server.mcp.tools.profiles import update_fact

        result = update_fact(fact_id="f-1")
        mock_client.update_fact.assert_called_once_with(
            "f-1", "", 0.0, "", ""
        )
        assert "updated" in result


# ---------------------------------------------------------------------------
# search_facts
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchFacts:
    """Tests for ``search_facts``."""

    def test_with_results(self, mock_client):
        from server.mcp.tools.profiles import search_facts

        mock_client.search_facts.return_value = [
            {"json_data": '[{"id":"f1","content":"match"}]'}
        ]
        result = search_facts(workspace_id="ws-1", query="match")
        mock_client.search_facts.assert_called_once_with(
            "ws-1", "match", ""
        )
        assert result == [{"id": "f1", "content": "match"}]

    def test_empty(self, mock_client):
        from server.mcp.tools.profiles import search_facts

        mock_client.search_facts.return_value = []
        result = search_facts(workspace_id="ws-1", query="nonexistent")
        assert result == []

    def test_no_json_data(self, mock_client):
        from server.mcp.tools.profiles import search_facts

        mock_client.search_facts.return_value = [{}]
        result = search_facts(workspace_id="ws-1", query="x")
        assert result == []
