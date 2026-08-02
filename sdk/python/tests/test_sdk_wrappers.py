"""Unit tests for all 25 new typed wrapper methods.

Tests all wrappers by mocking ``_call`` on a real Client instance,
following the pattern established in ``test_sdk_unit.py``.
"""
from __future__ import annotations

from unittest.mock import patch

from spacetime_memory import Client

# ═══════════════════════════════════════════════════════════════════════════
# KGMixinWrappers  (14 methods from _kg.py)
# ═══════════════════════════════════════════════════════════════════════════


class TestKGMixinWrappers:
    """Tests for the 14 new KG mixin wrapper methods."""

    def test_create_community(self):
        """create_community delegates to _call('create_community', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.create_community("ws-1", "My Community", "A test community")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "create_community",
                ["ws-1", "My Community", "A test community"],
            )

    def test_create_community_default_summary(self):
        """create_community defaults summary to empty string."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.create_community("ws-1", "My Community")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "create_community",
                ["ws-1", "My Community", ""],
            )

    def test_assign_to_community(self):
        """assign_to_community delegates to _call('assign_to_community', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.assign_to_community("node-1", 42)
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "assign_to_community",
                ["node-1", 42],
            )

    def test_compute_god_nodes(self):
        """compute_god_nodes delegates to _call('compute_god_nodes', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.compute_god_nodes("ws-1", top_n=5)
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "compute_god_nodes",
                ["ws-1", 5],
            )

    def test_compute_god_nodes_default_top_n(self):
        """compute_god_nodes defaults top_n to 10."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.compute_god_nodes("ws-1")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "compute_god_nodes",
                ["ws-1", 10],
            )

    def test_detect_ripple_impact(self):
        """detect_ripple_impact delegates to _call('detect_ripple_impact', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.detect_ripple_impact("ws-1", "node", "node-123")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "detect_ripple_impact",
                ["ws-1", "node", "node-123"],
            )

    def test_get_ripple_impacts(self):
        """get_ripple_impacts delegates to _call('get_ripple_impacts', ...) and returns None."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.get_ripple_impacts("ws-1", source_id="src-1")
            assert result is None
            mock_call.assert_called_once_with(
                "get_ripple_impacts",
                ["ws-1", "src-1"],
            )

    def test_get_ripple_impacts_default_source_id(self):
        """get_ripple_impacts defaults source_id to empty string."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.get_ripple_impacts("ws-1")
            assert result is None
            mock_call.assert_called_once_with(
                "get_ripple_impacts",
                ["ws-1", ""],
            )

    def test_resolve_ripple_impact(self):
        """resolve_ripple_impact delegates to _call('resolve_ripple_impact', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.resolve_ripple_impact("impact-1")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "resolve_ripple_impact",
                ["impact-1"],
            )

    def test_dismiss_ripple_impact(self):
        """dismiss_ripple_impact delegates to _call('dismiss_ripple_impact', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.dismiss_ripple_impact("impact-1")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "dismiss_ripple_impact",
                ["impact-1"],
            )

    def test_get_stale_nodes(self):
        """get_stale_nodes delegates to _call('get_stale_nodes', ...) and returns None."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.get_stale_nodes("ws-1")
            assert result is None
            mock_call.assert_called_once_with(
                "get_stale_nodes",
                ["ws-1"],
            )

    def test_update_peer(self):
        """update_peer delegates to _call('update_peer', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.update_peer("peer-1", "New Name", '{"key": "val"}')
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "update_peer",
                ["peer-1", "New Name", '{"key": "val"}'],
            )

    def test_update_peer_default_metadata(self):
        """update_peer defaults metadata_json to '{}'."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.update_peer("peer-1", "New Name")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "update_peer",
                ["peer-1", "New Name", "{}"],
            )

    def test_delete_peer(self):
        """delete_peer delegates to _call('delete_peer', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.delete_peer("peer-1")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "delete_peer",
                ["peer-1"],
            )

    def test_get_peer_memory_summary(self):
        """get_peer_memory_summary delegates to _call('get_peer_memory_summary', ...) and returns None."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.get_peer_memory_summary("peer-1")
            assert result is None
            mock_call.assert_called_once_with(
                "get_peer_memory_summary",
                ["peer-1"],
            )

    def test_search_profiles(self):
        """search_profiles returns filtered profiles via list_profiles."""
        client = Client()
        with patch.object(client, "list_profiles") as mock_list:
            mock_list.return_value = [{"peer_id": "p1", "static_facts_json": "python expert"}]
            result = client.search_profiles("ws-1", "python")
            assert len(result) == 1
            assert result[0]["peer_id"] == "p1"

    def test_search_profiles_default_workspace(self):
        """search_profiles returns empty list when no profiles match."""
        client = Client()
        with patch.object(client, "list_profiles", return_value=[]):
            result = client.search_profiles("ws-1", "my query")
            assert result == []

    def test_list_subscriptions(self):
        """list_subscriptions delegates to _call('list_subscriptions', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.list_subscriptions(workspace_id="ws-1")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "list_subscriptions",
                ["ws-1"],
            )

    def test_list_subscriptions_default_workspace(self):
        """list_subscriptions defaults workspace_id to empty string."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.list_subscriptions()
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "list_subscriptions",
                [""],
            )

    def test_get_search_results(self):
        """get_search_results delegates to _call('get_search_results', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.get_search_results(workspace_id="ws-1", query_hash="abc123")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "get_search_results",
                ["ws-1", "abc123"],
            )

    def test_get_search_results_defaults(self):
        """get_search_results defaults both parameters to empty strings."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.get_search_results()
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "get_search_results",
                ["", ""],
            )


# ═══════════════════════════════════════════════════════════════════════════
# TestSessionMixinWrappers  (3 methods from _session.py)
# ═══════════════════════════════════════════════════════════════════════════


class TestSessionMixinWrappers:
    """Tests for the 3 new session mixin wrapper methods."""

    def test_send_message(self):
        """send_message delegates to _call('send_message', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.send_message(
                session_id="sess-1",
                sender_id="user-1",
                content="Hello!",
                content_type="text",
                metadata_json='{"key": "val"}',
            )
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "send_message",
                ["sess-1", "user-1", "Hello!", "text", '{"key": "val"}'],
            )

    def test_send_message_defaults(self):
        """send_message uses default content_type and metadata_json."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.send_message(
                session_id="sess-1",
                sender_id="user-1",
                content="Hello!",
            )
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "send_message",
                ["sess-1", "user-1", "Hello!", "text", "{}"],
            )

    def test_delete_message(self):
        """delete_message delegates to _call('delete_message', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.delete_message("msg-1")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "delete_message",
                ["msg-1"],
            )

    def test_delete_session_steps(self):
        """delete_session_steps delegates to _call('delete_session_steps', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.delete_session_steps("sess-1")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "delete_session_steps",
                ["sess-1"],
            )


# ═══════════════════════════════════════════════════════════════════════════
# TestAdminMixinWrappers  (4 methods from _admin.py)
# ═══════════════════════════════════════════════════════════════════════════


class TestAdminMixinWrappers:
    """Tests for the 4 new admin mixin wrapper methods."""

    def test_decay_weak_memories(self):
        """decay_weak_memories delegates to _call('decay_weak_memories', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.decay_weak_memories("ws-1", decay_rate=0.3, threshold=0.05)
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "decay_weak_memories",
                ["ws-1", 0.3, 0.05],
            )

    def test_decay_weak_memories_defaults(self):
        """decay_weak_memories uses default decay_rate (0.5) and threshold (0.1)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.decay_weak_memories("ws-1")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "decay_weak_memories",
                ["ws-1", 0.5, 0.1],
            )

    def test_admin_deactivate_account(self):
        """admin_deactivate_account delegates to _call('admin_deactivate_account', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.admin_deactivate_account("identity-xyz")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "admin_deactivate_account",
                ["identity-xyz"],
            )

    def test_delete_api_key(self):
        """delete_api_key delegates to _call('delete_api_key', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.delete_api_key("api-key-1")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "delete_api_key",
                ["api-key-1"],
            )

    def test_manual_decay(self):
        """manual_decay delegates to _call('manual_decay', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.manual_decay("ws-1", '["mem-1", "mem-2"]')
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "manual_decay",
                ["ws-1", '["mem-1", "mem-2"]'],
            )


# ═══════════════════════════════════════════════════════════════════════════
# TestNotesMixinWrappers  (2 methods from _notes.py)
# ═══════════════════════════════════════════════════════════════════════════


class TestNotesMixinWrappers:
    """Tests for the 2 new notes mixin wrapper methods."""

    def test_update_note_block(self):
        """update_note_block delegates to _call('update_note_block', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.update_note_block(
                block_id="block-1",
                content="New content",
                block_type="text",
            )
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "update_note_block",
                ["block-1", "New content", "text"],
            )

    def test_update_note_block_defaults(self):
        """update_note_block uses default empty content and block_type."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.update_note_block(block_id="block-1")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "update_note_block",
                ["block-1", "", ""],
            )

    def test_parse_note_blocks(self):
        """parse_note_blocks delegates to _call('parse_note_blocks', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.parse_note_blocks("note-1")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "parse_note_blocks",
                ["note-1"],
            )


# ═══════════════════════════════════════════════════════════════════════════
# TestDocumentMixinWrappers  (1 method from _memories_docs.py)
# ═══════════════════════════════════════════════════════════════════════════


class TestDocumentMixinWrappers:
    """Tests for the 1 new document mixin wrapper method."""

    def test_add_chunk(self):
        """add_chunk delegates to _call('add_chunk', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.add_chunk(
                document_id="doc-1",
                content="Chunk content",
                chunk_index=2,
                metadata_json='{"page": 5}',
            )
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "add_chunk",
                ["doc-1", "Chunk content", 2, '{"page": 5}'],
            )

    def test_add_chunk_defaults(self):
        """add_chunk uses default chunk_index (0) and metadata_json ('{}')."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.add_chunk(document_id="doc-1", content="Chunk content")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "add_chunk",
                ["doc-1", "Chunk content", 0, "{}"],
            )


# ═══════════════════════════════════════════════════════════════════════════
# TestDirectoryMixinWrappers  (1 method from _memories_directory.py)
# ═══════════════════════════════════════════════════════════════════════════


class TestDirectoryMixinWrappers:
    """Tests for the 1 new directory mixin wrapper method."""

    def test_delete_directory(self):
        """delete_directory delegates to _call('delete_directory', ...)."""
        client = Client()
        with patch.object(client, "_call") as mock_call:
            mock_call.return_value = {"status": "ok"}
            result = client.delete_directory("/my/path")
            assert result == {"status": "ok"}
            mock_call.assert_called_once_with(
                "delete_directory",
                ["/my/path"],
            )
