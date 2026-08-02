"""Tests for client sub-modules: AdminMixin, WorkspaceMixin, KGMixin,
EmbedderMixin, and _parse_rerank_json.

All tests use the ``mock_http_client`` fixture — no live SpacetimeDB required.
"""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import httpx
import pytest
from conftest import make_sql_response

# ============================================================================
# AdminMixin
# ============================================================================


class TestAdminMixin:
    """AdminMixin methods (maintenance, notes, encryption, etc.)."""

    def test_run_maintenance(self, mock_http_client):
        result = mock_http_client.run_maintenance()
        assert result == {"status": "ok"}

    def test_expire_memories(self, mock_http_client):
        result = mock_http_client.expire_memories()
        assert result == {"status": "ok"}

    def test_dedup(self, mock_http_client):
        result = mock_http_client.dedup("ws-1")
        assert result == {"status": "ok"}

    def test_dedup_memories_delegates(self, mock_http_client):
        """dedup_memories delegates to dedup (same reducer)."""
        result = mock_http_client.dedup_memories("ws-1")
        assert result == {"status": "ok"}

    def test_consolidate_memories(self, mock_http_client):
        result = mock_http_client.consolidate_memories(
            "ws-1", ["m1", "m2"], "merged content", "merged summary"
        )
        assert result == {"status": "ok"}

    def test_suggest_merges_default_threshold(self, mock_http_client):
        result = mock_http_client.suggest_merges("ws-1")
        assert result == {"status": "ok"}

    def test_suggest_merges_custom_threshold(self, mock_http_client):
        result = mock_http_client.suggest_merges("ws-1", threshold=0.9)
        assert result == {"status": "ok"}

    def test_approve_merge(self, mock_http_client):
        result = mock_http_client.approve_merge("sug-1")
        assert result == {"status": "ok"}

    def test_reject_merge(self, mock_http_client):
        result = mock_http_client.reject_merge("sug-1")
        assert result == {"status": "ok"}

    # --- Notes ---

    def test_create_note_basic(self, mock_http_client):
        """create_note with no content returns ok (no embed needed)."""
        result = mock_http_client.create_note(
            workspace_id="ws-1", title="Test", content=""
        )
        assert result == {"status": "ok"}

    def test_create_note_with_embed(self, mock_http_client):
        """create_note with content triggers embedding. Mock returns empty,
        so no re-indexing happens."""
        result = mock_http_client.create_note(
            workspace_id="ws-1", title="Hello", content="World", embed=True
        )
        assert result == {"status": "ok"}

    def test_update_note(self, mock_http_client):
        result = mock_http_client.update_note(
            note_id="note-1", title="Updated", content="New content", expected_version=1
        )
        assert result == {"status": "ok"}

    def test_delete_note(self, mock_http_client):
        result = mock_http_client.delete_note("note-1")
        assert result == {"status": "ok"}

    def test_list_notes(self, mock_http_client):
        """list_notes returns empty list when no notes exist."""
        result = mock_http_client.list_notes("ws-1")
        assert result == []

    def test_get_note(self, mock_http_client):
        result = mock_http_client.get_note("note-1")
        assert result == []

    def test_get_note_by_date(self, mock_http_client):
        result = mock_http_client.get_note_by_date("2026-07-07")
        assert result == []

    def test_get_note_by_title(self, mock_http_client):
        result = mock_http_client.get_note_by_title("Hello")
        assert result == []

    def test_get_backlinks(self, mock_http_client):
        result = mock_http_client.get_backlinks("note-1")
        assert result == []

    def test_get_outgoing_links(self, mock_http_client):
        result = mock_http_client.get_outgoing_links("note-1")
        assert result == []

    # --- Tours ---

    def test_create_tour(self, mock_http_client):
        result = mock_http_client.create_tour("ws-1", "My Tour", "A guided tour")
        assert result is None
        mock_http_client._http.post.assert_called_once()

    def test_add_tour_stop(self, mock_http_client):
        result = mock_http_client.add_tour_stop("tour-1", "node-1", "Welcome")
        assert result is None
        mock_http_client._http.post.assert_called_once()

    def test_delete_tour(self, mock_http_client):
        result = mock_http_client.delete_tour("tour-1")
        assert result is None
        mock_http_client._http.post.assert_called_once()

    def test_delete_tour_stop(self, mock_http_client):
        result = mock_http_client.delete_tour_stop("stop-1")
        assert result is None
        mock_http_client._http.post.assert_called_once()

    # --- Connector registration ---

    def test_register_connector(self, mock_http_client):
        result = mock_http_client.register_connector(
            "My Connector", "webhook", '{"port": 8080}', "ws-1", 60
        )
        assert result is None
        mock_http_client._http.post.assert_called_once()

    def test_update_connector(self, mock_http_client):
        result = mock_http_client.update_connector(
            "conn-1", "My Connector", "webhook", '{"port": 8081}', "ws-1", 120, True
        )
        assert result is None
        mock_http_client._http.post.assert_called_once()

    def test_delete_connector(self, mock_http_client):
        result = mock_http_client.delete_connector("conn-1")
        assert result is None
        mock_http_client._http.post.assert_called_once()

    # --- Entity extraction ---

    def test_extract_entities(self, mock_http_client):
        result = mock_http_client.extract_entities("ws-1", "Alice works at Acme Corp")
        assert result is None
        mock_http_client._http.post.assert_called_once()

    # --- Entity links ---

    def test_create_entity_link(self, mock_http_client):
        result = mock_http_client.create_entity_link("ws-1", "Acme Corp", "organization", "A company")
        assert result is None
        mock_http_client._http.post.assert_called_once()

    def test_add_alias(self, mock_http_client):
        result = mock_http_client.add_alias("el-1", "Acme")
        assert result is None
        mock_http_client._http.post.assert_called_once()

    def test_resolve_entity(self, mock_http_client):
        result = mock_http_client.resolve_entity("ws-1", "Acme Corp")
        assert result is None
        mock_http_client._http.post.assert_called_once()

    # --- Encryption ---

    def test_init_workspace_encryption(self, mock_http_client):
        result = mock_http_client.init_workspace_encryption("ws-1")
        assert result == {"status": "ok"}

    def test_set_workspace_encryption_enabled(self, mock_http_client):
        result = mock_http_client.set_workspace_encryption_enabled("ws-1", True)
        assert result == {"status": "ok"}

    def test_rotate_workspace_encryption_key(self, mock_http_client):
        result = mock_http_client.rotate_workspace_encryption_key("ws-1")
        assert result == {"status": "ok"}

    def test_encrypt_existing_memories(self, mock_http_client):
        result = mock_http_client.encrypt_existing_memories("ws-1")
        assert result == {"status": "ok"}

    def test_get_decrypted_memory(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[{"status": "ok"}]):
            result = mock_http_client.get_decrypted_memory("mem-1")
        assert result == {"status": "ok"}

    # --- Backup & Restore ---

    def test_backup(self, mock_http_client, tmp_path):
        """backup() writes JSON file and returns correct metadata."""
        output = tmp_path / "backup.json"
        result = mock_http_client.backup(output_path=str(output))
        assert result["status"] == "ok"
        assert result["path"] == str(output)
        assert output.exists()
        with open(output) as f:
            payload = json.load(f)
        assert "tables" in payload
        assert payload["version"] == "0.3.0"

    def test_restore(self, mock_http_client, tmp_path):
        """restore() reads a backup JSON and returns metadata."""
        backup = tmp_path / "restore_test.json"
        backup.write_text(
            json.dumps(
                {
                    "version": "0.3.0",
                    "created_at": "2026-01-01T00:00:00",
                    "tables": {
                        "workspace": [{"id": "ws-1", "name": "Test"}],
                        "memory": [],
                    },
                    "stats": {"table_count": 2, "total_rows": 1},
                }
            )
        )
        result = mock_http_client.restore(str(backup))
        assert result["status"] == "ok"
        assert "total_rows" in result
        assert "tables" in result

    # --- Resonance ---

    def test_store_harmonic_beliefs(self, mock_http_client):
        result = mock_http_client.store_harmonic_beliefs(
            "ws-1", "peer-1", '[{"belief": "test"}]', "cluster-1"
        )
        assert result is None
        mock_http_client._http.post.assert_called_once()

    def test_clear_harmonic_beliefs(self, mock_http_client):
        result = mock_http_client.clear_harmonic_beliefs("ws-1", 0.5)
        assert result is None
        mock_http_client._http.post.assert_called_once()

    def test_log_resonance_session(self, mock_http_client):
        result = mock_http_client.log_resonance_session(
            "ws-1", "peer-1", 5, 10, 2, 0.85, 1200
        )
        assert result is None
        mock_http_client._http.post.assert_called_once()


# ============================================================================
# WorkspaceMixin
# ============================================================================


class TestWorkspaceMixin:
    """WorkspaceMixin methods (workspace CRUD, members, auth, API keys, users)."""

    def test_create_workspace(self, mock_http_client):
        result = mock_http_client.create_workspace("My Workspace", "A description")
        assert result["status"] == "ok"
        assert "id" in result

    def test_create_workspace_with_id(self, mock_http_client):
        result = mock_http_client.create_workspace(
            "My Workspace", "A description", id="custom-id"
        )
        assert result["status"] == "ok"
        assert result["id"] == "custom-id"

    def test_list_workspaces(self, mock_http_client):
        result = mock_http_client.list_workspaces()
        assert result == []

    def test_delete_workspace(self, mock_http_client):
        result = mock_http_client.delete_workspace("ws-1")
        assert result == {"status": "ok"}

    def test_update_workspace(self, mock_http_client):
        result = mock_http_client.update_workspace("ws-1", "New Name", "New desc")
        assert result == {"status": "ok"}

    def test_set_workspace_visibility(self, mock_http_client):
        result = mock_http_client.set_workspace_visibility("ws-1", True)
        assert result == {"status": "ok"}

    def test_get_workspace_context(self, mock_http_client):
        result = mock_http_client.get_workspace_context("ws-1")
        assert result == {"workspace_id": "ws-1", "context": "", "queried_at": 0}

    def test_list_space_members(self, mock_http_client):
        result = mock_http_client.list_space_members("ws-1")
        assert result == []

    def test_grant_space_access(self, mock_http_client):
        result = mock_http_client.grant_space_access("ws-1", "peer-1", "editor")
        assert result == {"status": "ok"}

    def test_revoke_space_access(self, mock_http_client):
        result = mock_http_client.revoke_space_access("ws-1", "peer-1")
        assert result == {"status": "ok"}

    # --- Auth / Account ---

    def test_register(self, mock_http_client):
        result = mock_http_client.register("alice", "Alice", "securepass")
        assert result == {"status": "ok"}

    def test_login(self, mock_http_client):
        result = mock_http_client.login("alice", "securepass")
        assert result == {"status": "ok"}

    def test_logout(self, mock_http_client):
        result = mock_http_client.logout()
        assert result == {"status": "ok"}

    def test_update_account(self, mock_http_client):
        result = mock_http_client.update_account(
            display_name="Alice Updated",
            current_password="oldpass",
            new_password="newpass",
        )
        assert result == {"status": "ok"}

    def test_deactivate_account(self, mock_http_client):
        result = mock_http_client.deactivate_account("securepass")
        assert result == {"status": "ok"}

    def test_promote_admin(self, mock_http_client):
        result = mock_http_client.promote_admin("identity-hex")
        assert result == {"status": "ok"}

    def test_demote_admin(self, mock_http_client):
        result = mock_http_client.demote_admin("identity-hex")
        assert result == {"status": "ok"}

    def test_list_admins(self, mock_http_client):
        result = mock_http_client.list_admins()
        assert result == []

    # --- API Keys ---

    def test_create_api_key(self, mock_http_client):
        result = mock_http_client.create_api_key(
            "ws-1", "My Key", '["read", "write"]', '["ws-1"]'
        )
        assert result["status"] == "ok"
        assert "api_key" in result
        assert result["api_key"].startswith("sk-")

    def test_create_api_key_with_star_scope(self, mock_http_client):
        result = mock_http_client.create_api_key("ws-1", "Admin Key")
        assert result["status"] == "ok"
        assert result["scope"] == "*"

    def test_verify_api_key(self, mock_http_client):
        result = mock_http_client.verify_api_key("sk-test")
        assert result["valid"] is False

    def test_update_api_key(self, mock_http_client):
        result = mock_http_client.update_api_key(
            "key-1", name="Renamed", permissions='["read"]', scope="*", is_active=True
        )
        assert result == {"status": "ok"}

    def test_deactivate_api_key(self, mock_http_client):
        result = mock_http_client.deactivate_api_key("key-1")
        assert result == {"status": "ok"}

    def test_list_api_keys(self, mock_http_client):
        result = mock_http_client.list_api_keys("ws-1")
        assert result == []

    # --- Users ---

    def test_add_user(self, mock_http_client):
        result = mock_http_client.add_user(
            "user-1", "user@example.com", "Alice", "Smith", '{"role": "admin"}'
        )
        assert result == {"status": "ok"}

    def test_get_user_not_found(self, mock_http_client):
        """get_user raises NotFoundError when user doesn't exist."""
        with pytest.raises(RuntimeError, match="not found"):
            mock_http_client.get_user("nonexistent")

    def test_update_user(self, mock_http_client):
        result = mock_http_client.update_user(
            "user-1", email="new@example.com", first_name="Bob"
        )
        assert result == {"status": "ok"}

    def test_delete_user(self, mock_http_client):
        result = mock_http_client.delete_user("user-1")
        assert result == {"status": "ok"}

    def test_list_users(self, mock_http_client):
        result = mock_http_client.list_users()
        assert result == []


# ============================================================================
# KGMixin
# ============================================================================


class TestKGMixin:
    """KGMixin methods (nodes, edges, citations, communities, profiles, facts)."""

    # --- Nodes ---

    def test_create_node(self, mock_http_client):
        result = mock_http_client.create_node(
            "ws-1", "Python", node_type="language", summary="A programming language"
        )
        assert result == {"status": "ok"}

    def test_update_node(self, mock_http_client):
        result = mock_http_client.update_node(
            "node-1", "Python 3", node_type="language", summary="Updated"
        )
        assert result == {"status": "ok"}

    def test_delete_node(self, mock_http_client):
        result = mock_http_client.delete_node("node-1")
        assert result == {"status": "ok"}

    # --- Edges ---

    def test_create_edge(self, mock_http_client):
        result = mock_http_client.create_edge(
            "ws-1", "node-1", "node-2", relation="depends_on", weight=0.8
        )
        assert result == {"status": "ok"}

    def test_update_edge(self, mock_http_client):
        result = mock_http_client.update_edge(
            "edge-1", relation="related_to", weight=0.5
        )
        assert result == {"status": "ok"}

    def test_delete_edge(self, mock_http_client):
        result = mock_http_client.delete_edge("edge-1")
        assert result == {"status": "ok"}

    # --- Citations ---

    def test_add_node_citation(self, mock_http_client):
        result = mock_http_client.add_node_citation(
            "ws-1", "node-1", "mem-1", "Supports this node"
        )
        assert result == {"status": "ok"}

    def test_add_edge_citation(self, mock_http_client):
        result = mock_http_client.add_edge_citation(
            "ws-1", "edge-1", "mem-1", "Evidence for this edge"
        )
        assert result == {"status": "ok"}

    def test_get_edge_history(self, mock_http_client):
        result = mock_http_client.get_edge_history("eg-1")
        assert result == []

    def test_get_citations(self, mock_http_client):
        result = mock_http_client.get_citations("ws-1", "node-1", entity_type="node")
        assert result == []

    # --- Graph queries ---

    def test_query_graph(self, mock_http_client):
        result = mock_http_client.query_graph("ws-1")
        assert result == []

    def test_query_graph_with_filter(self, mock_http_client):
        result = mock_http_client.query_graph("ws-1", query="Python")
        assert result == []

    def test_get_neighbors(self, mock_http_client):
        result = mock_http_client.get_neighbors("node-1", workspace_id="ws-1")
        assert result == []

    # --- Communities ---

    def test_detect_communities(self, mock_http_client):
        result = mock_http_client.detect_communities("ws-1")
        assert result == {"status": "ok"}

    def test_seed_communities(self, mock_http_client):
        result = mock_http_client.seed_communities("ws-1")
        assert result == {"status": "ok"}

    # --- Profiles ---

    def test_upsert_profile(self, mock_http_client):
        result = mock_http_client.upsert_profile(
            "peer-1", static_facts='["likes python"]', preferences='{"theme": "dark"}'
        )
        assert result == {"status": "ok"}

    def test_add_profile_fact(self, mock_http_client):
        result = mock_http_client.add_profile_fact("peer-1", "Loves hiking")
        assert result == {"status": "ok"}

    def test_add_dynamic_context(self, mock_http_client):
        result = mock_http_client.add_dynamic_context("peer-1", "Currently working")
        assert result == {"status": "ok"}

    def test_get_profile_no_profile(self, mock_http_client):
        result = mock_http_client.get_profile("peer-1")
        assert result is None

    def test_get_profile_with_mock(self, mock_http_client):
        """Configure SQL response to return a profile."""
        profile_row = {
            "peer_id": "peer-1",
            "static_facts_json": '["likes python"]',
            "dynamic_context_json": "",
            "preferences_json": "{}",
        }
        mock_http_client._http.post.side_effect = None
        # First POST call = _call('query_table', ...) returns {"status": "ok"}
        # Second POST call = _sql(query) returns the profile data
        side_effects = [
            Mock(status_code=200, text=json.dumps([]), json=lambda: {"data": [{"embedding": [0.0]}]}),
            Mock(
                status_code=200,
                text=make_sql_response(
                    [
                        {
                            "table_name": "profile",
                            "row_json": json.dumps(profile_row),
                        }
                    ]
                ),
                json=lambda: {"data": [{"embedding": [0.0]}]},
            ),
        ]
        mock_http_client._http.post.side_effect = side_effects

        result = mock_http_client.get_profile("peer-1")
        assert result is not None
        assert result["peer_id"] == "peer-1"
        assert "likes python" in result["static_facts_json"]

    def test_list_profiles_empty(self, mock_http_client):
        result = mock_http_client.list_profiles("ws-1")
        assert result == []

    def test_search_profiles_empty(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value=[]):
            result = mock_http_client.search_profiles("ws-1", "python")
        assert result == []

    def test_get_profile_context(self, mock_http_client):
        result = mock_http_client.get_profile_context("peer-1")
        assert result is None

    # --- Facts ---

    def test_add_fact(self, mock_http_client):
        result = mock_http_client.add_fact(
            "ws-1", "peer-1", "Alice knows Python", fact_type="dynamic",
            category="skill", confidence=0.9, source="manual", tier="L1"
        )
        assert result == {"status": "ok"}

    def test_list_facts_empty(self, mock_http_client):
        result = mock_http_client.list_facts("ws-1")
        assert result == []


# ============================================================================
# EmbedderMixin
# ============================================================================


class TestEmbedderMixin:
    """EmbedderMixin methods (embedding, health checks, Tantivy BM25)."""

    def test_embed_batch_empty(self, mock_http_client):
        """_embed_batch returns [] for empty input."""
        result = mock_http_client._embed_batch([])
        assert result == []

    def test_embed_batch_no_api_key(self, mock_http_client, monkeypatch):
        """_embed_batch returns [] when OPENAI_API_KEY is missing."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = mock_http_client._embed_batch(["hello", "world"])
        assert result == []

    def test_embed_batch_openai_empty(self, mock_http_client):
        result = mock_http_client._embed_batch_openai([])
        assert result == []

    def test_check_embedder_health_ok(self, mock_http_client):
        """check_embedder_health returns status from mock."""
        result = mock_http_client.check_embedder_health()
        assert result is not None
        assert result.get("model") == "bge-m3"

    def test_check_embedder_health_connect_error(self, mock_http_client):
        """check_embedder_health handles connection errors gracefully."""
        mock_http_client._http.get.side_effect = httpx.ConnectError("Connection refused")
        result = mock_http_client.check_embedder_health()
        assert result["status"] == "error"
        assert result["reachable"] is False

    def test_check_tantivy_health_ok(self, mock_http_client):
        """check_tantivy_health returns status from mock."""
        mock_http_client._http.get.return_value = Mock(
            status_code=200, json=lambda: {"status": "ok", "reachable": True}
        )
        result = mock_http_client.check_tantivy_health()
        assert result is not None

    def test_request_with_retry_simple_get(self, mock_http_client):
        """_request_with_retry_simple handles GET requests."""
        mock_http_client._http.get.return_value = Mock(
            status_code=200,
            json=lambda: {"result": "ok"},
            text='{"result": "ok"}',
        )
        resp = mock_http_client._request_with_retry_simple("GET", "http://test.local/api")
        assert resp is not None
        assert resp.status_code == 200

    def test_request_with_retry_simple_post(self, mock_http_client):
        """_request_with_retry_simple handles POST requests."""
        resp = mock_http_client._request_with_retry_simple(
            "POST", "http://test.local/api", json={"key": "value"}
        )
        assert resp is not None

    def test_tantivy_index(self, mock_http_client):
        """_tantivy_index returns True on success."""
        result = mock_http_client._tantivy_index("ws-1", "mem-1", "content", "memory")
        assert result is True

    def test_tantivy_index_batch_empty(self, mock_http_client):
        """_tantivy_index_batch returns True for empty input."""
        result = mock_http_client._tantivy_index_batch([])
        assert result is True

    def test_tantivy_index_batch(self, mock_http_client):
        """_tantivy_index_batch returns True on success."""
        result = mock_http_client._tantivy_index_batch(
            [{"workspace_id": "ws-1", "entity_id": "mem-1", "content": "hello", "entity_type": "memory"}]
        )
        assert result is True

    def test_tantivy_search(self, mock_http_client):
        """_tantivy_search returns empty list on default mock."""
        # Mock the Tantivy search response to return a JSON array
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text=json.dumps([]),
            json=list,
        )
        result = mock_http_client._tantivy_search("ws-1", "test query")
        assert result == []


# ============================================================================
# _parse_rerank_json (standalone function from _rerank.py)
# ============================================================================


class TestParseRerankJson:
    """_parse_rerank_json with all 6 fallback strategies."""

    def test_direct_array(self):
        """Strategy 1: direct JSON array parse."""
        from spacetime_memory.client._rerank import _parse_rerank_json

        result = _parse_rerank_json('[{"index": 0, "score": 8, "reason": "good"}]')
        assert len(result) == 1
        assert result[0]["index"] == 0
        assert result[0]["score"] == 8

    def test_markdown_code_fences(self):
        """Strategy 2: JSON array inside markdown fences."""
        from spacetime_memory.client._rerank import _parse_rerank_json

        content = """```json
[{"index": 0, "score": 9, "reason": "exact match"}]
```"""
        result = _parse_rerank_json(content)
        assert len(result) == 1
        assert result[0]["score"] == 9

    def test_trailing_comma_salvage(self):
        """Strategy 4: trailing commas stripped."""
        from spacetime_memory.client._rerank import _parse_rerank_json

        content = '[{"index": 0, "score": 7, "reason": "relevant",}]'
        result = _parse_rerank_json(content)
        assert len(result) == 1
        assert result[0]["score"] == 7

    def test_dict_wrapper(self):
        """Strategy 5: LLM returned {'scores': [...]}."""
        from spacetime_memory.client._rerank import _parse_rerank_json

        content = '{"scores": [{"index": 0, "score": 8}], "model": "gpt-4"}'
        result = _parse_rerank_json(content)
        assert len(result) == 1
        assert result[0]["index"] == 0

    def test_dict_wrapper_results_key(self):
        """Strategy 5 with 'results' key."""
        from spacetime_memory.client._rerank import _parse_rerank_json

        content = '{"results": [{"index": 1, "score": 6}]}'
        result = _parse_rerank_json(content)
        assert len(result) == 1
        assert result[0]["index"] == 1

    def test_dict_wrapper_rankings_key(self):
        """Strategy 5 with 'rankings' key."""
        from spacetime_memory.client._rerank import _parse_rerank_json

        content = '{"rankings": [{"index": 2, "score": 5}]}'
        result = _parse_rerank_json(content)
        assert len(result) == 1
        assert result[0]["index"] == 2

    def test_line_by_line(self):
        """Strategy 6: one JSON object per line. Uses a text prefix that
        blocks strategies 1-5 so strategy 6 can be exercised."""
        from spacetime_memory.client._rerank import _parse_rerank_json

        # Raw text before JSON blocks raw_decode (strategy 3).
        # No "score" key blocks strategy 4's object-with-score search.
        # No common dict keys ("scores", "results", etc.) blocks strategy 5.
        content = (
            "Results:\n"
            '{"index": 0, "value": 10}\n'
            '{"index": 1, "value": 7}\n'
        )
        result = _parse_rerank_json(content)
        assert len(result) == 2
        assert result[0]["index"] == 0
        assert result[0]["value"] == 10
        assert result[1]["index"] == 1

    def test_empty_string_raises(self):
        """Empty string raises ValueError."""
        from spacetime_memory.client._rerank import _parse_rerank_json

        with pytest.raises(ValueError, match="JSON parse failed"):
            _parse_rerank_json("")

    def test_gibberish_raises(self):
        """Completely invalid content raises ValueError."""
        from spacetime_memory.client._rerank import _parse_rerank_json

        with pytest.raises(ValueError):
            _parse_rerank_json("Not even close to JSON")

    def test_single_object_wrapped(self):
        """Single object wrapped in an array via strategy 3."""
        from spacetime_memory.client._rerank import _parse_rerank_json

        content = '{"index": 0, "score": 10, "reason": "perfect"}'
        result = _parse_rerank_json(content)
        assert len(result) == 1
        assert result[0]["index"] == 0
        assert result[0]["score"] == 10

    def test_embedded_json_in_text(self):
        """JSON array embedded in conversational text (strategy 2)."""
        from spacetime_memory.client._rerank import _parse_rerank_json

        content = (
            "Here are my rankings:\n"
            '[{"index": 0, "score": 8, "reason": "good match"}]\n'
            "Hope this helps!"
        )
        result = _parse_rerank_json(content)
        assert len(result) == 1
        assert result[0]["index"] == 0
