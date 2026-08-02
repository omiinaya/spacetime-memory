"""Unit tests for KGMixin — knowledge graph operations.

All tests use the ``mock_http_client`` fixture — no live SpacetimeDB required.
"""

from __future__ import annotations

import json
from unittest.mock import patch


class TestKGMixin:
    """KGMixin methods (nodes, edges, communities, traversal, facts, etc.)."""

    # --- Nodes ---

    def test_create_node(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok", "id": "node-1"}), \
             patch.object(mock_http_client, "_embed", return_value=[0.1, 0.2, 0.3]), \
             patch.object(mock_http_client, "_query", return_value=[{"id": "node-1"}]):
            result = mock_http_client.create_node(
                "ws-1", "Python", node_type="language", summary="A programming language"
            )
        assert result == {"status": "ok", "id": "node-1"}

    def test_create_node_no_embed(self, mock_http_client):
        """create_node still works even when embedding returns empty."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_embed", return_value=[]):
            result = mock_http_client.create_node("ws-1", "Just a label")
        assert result == {"status": "ok"}

    def test_create_node_empty_summary(self, mock_http_client):
        """create_node with empty summary embeds just the label; returns the
        created node (with id) merged with status:ok — compounder workflows
        consume node['id']."""
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_embed", return_value=[0.5]), \
             patch.object(mock_http_client, "_query", return_value=[{"id": "node-1"}]):
            result = mock_http_client.create_node("ws-1", "Python")
        assert result["status"] == "ok"
        assert result["id"] == "node-1"

    def test_update_node(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.update_node(
                "node-1", "Python 3", node_type="language", summary="Updated"
            )
        assert result == {"status": "ok"}

    def test_delete_node(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.delete_node("node-1")
        assert result == {"status": "ok"}

    # --- Edges ---

    def test_create_edge(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.create_edge(
                "ws-1", "node-1", "node-2", relation="depends_on", weight=0.8
            )
        assert result == {"status": "ok"}

    def test_update_edge(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.update_edge("edge-1", relation="related_to", weight=0.5)
        assert result == {"status": "ok"}

    def test_delete_edge(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.delete_edge("edge-1")
        assert result == {"status": "ok"}

    # --- Citations ---

    def test_add_node_citation(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.add_node_citation(
                "ws-1", "node-1", "mem-1", "Supports this node"
            )
        assert result == {"status": "ok"}

    def test_add_edge_citation(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.add_edge_citation(
                "ws-1", "edge-1", "mem-1", "Evidence for this edge"
            )
        assert result == {"status": "ok"}

    def test_get_edge_history(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_sql_param", return_value=[
                 {"edge_group_id": "eg-1", "version": 1},
                 {"edge_group_id": "eg-1", "version": 2},
             ]):
            result = mock_http_client.get_edge_history("eg-1")
        assert len(result) == 2

    def test_get_edge_as_of(self, mock_http_client):
        """get_edge_as_of returns the edge version valid at a given timestamp."""
        with patch.object(mock_http_client, "_sql_param", return_value=[
            # Only version 1 is valid at t=150 (valid_at=100 <= 150, invalid_at=200 > 150)
            {"edge_group_id": "eg-1", "version": 1, "valid_at": 100, "invalid_at": 200},
        ]):
            result = mock_http_client.get_edge_as_of("eg-1", 150)
        assert result is not None
        assert result["version"] == 1  # version 1 was valid at t=150

    def test_get_edge_as_of_no_match(self, mock_http_client):
        """get_edge_as_of returns None when no edge was valid at the given time."""
        with patch.object(mock_http_client, "_sql_param", return_value=[]):
            result = mock_http_client.get_edge_as_of("eg-1", 999999)
        assert result is None

    def test_get_edge_as_of_best_version(self, mock_http_client):
        """get_edge_as_of picks the highest version when multiple overlap."""
        with patch.object(mock_http_client, "_sql_param", return_value=[
            {"edge_group_id": "eg-1", "version": 1, "valid_at": 100, "invalid_at": 300},
            {"edge_group_id": "eg-1", "version": 2, "valid_at": 150, "invalid_at": 0},
        ]):
            result = mock_http_client.get_edge_as_of("eg-1", 200)
        assert result is not None
        assert result["version"] == 2  # highest version valid at t=200

    def test_get_citations(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"entity_id": "node-1", "source_memory_id": "mem-1"}
             ]):
            result = mock_http_client.get_citations("ws-1", "node-1", entity_type="node")
        assert len(result) == 1
        assert result[0]["entity_id"] == "node-1"

    # --- Graph queries ---

    def test_query_graph(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[
            {"id": "n1", "label": "Python", "summary": "Language"},
            {"id": "n2", "label": "Rust", "summary": "Systems language"},
        ]):
            result = mock_http_client.query_graph("ws-1")
        assert len(result) == 2

    def test_query_graph_with_filter(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[
            {"id": "n1", "label": "Python", "summary": "Language"},
            {"id": "n2", "label": "Rust", "summary": "Systems language"},
        ]):
            result = mock_http_client.query_graph("ws-1", query="Python")
        assert len(result) == 1
        assert result[0]["label"] == "Python"

    def test_query_graph_filter_case_insensitive(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[
            {"id": "n1", "label": "Python", "summary": "Language"},
        ]):
            result = mock_http_client.query_graph("ws-1", query="python")
        assert len(result) == 1

    def test_get_neighbors(self, mock_http_client):
        """get_neighbors enriches edges with source/target labels."""
        node_labels = {
            "node-1": {"id": "node-1", "label": "Python"},
            "node-2": {"id": "node-2", "label": "Rust"},
        }

        def _query_side(table, **kw):
            if table == "kg_edge":
                filt = kw.get("filter_dict", {})
                if filt.get("source_node_id") == "node-1":
                    return [{"id": "e1", "source_node_id": "node-1", "target_node_id": "node-2", "weight": 0.8}]
                return []
            if table == "kg_node":
                nid = kw.get("filter_dict", {}).get("id", "")
                return [node_labels.get(nid, {})] if nid else []
            return []

        with patch.object(mock_http_client, "_query", side_effect=_query_side):
            result = mock_http_client.get_neighbors("node-1", workspace_id="ws-1")
        assert len(result) == 1
        assert result[0]["source_label"] == "Python"
        assert result[0]["target_label"] == "Rust"

    # --- Communities ---

    def test_detect_communities(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.detect_communities("ws-1")
        assert result == {"status": "ok"}

    def test_seed_communities(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.seed_communities("ws-1")
        assert result == {"status": "ok"}

    def test_create_community(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.create_community("ws-1", "My Community", "A summary")
        assert result == {"status": "ok"}

    def test_assign_to_community(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.assign_to_community("node-1", 42)
        assert result == {"status": "ok"}

    # --- Profiles ---

    def test_upsert_profile(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.upsert_profile(
                "peer-1", static_facts='["likes python"]', preferences='{"theme": "dark"}'
            )
        assert result == {"status": "ok"}

    def test_add_profile_fact(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.add_profile_fact("peer-1", "Loves hiking")
        assert result == {"status": "ok"}

    def test_add_dynamic_context(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.add_dynamic_context("peer-1", "Currently working")
        assert result == {"status": "ok"}

    def test_get_profile_no_profile(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.get_profile("peer-1")
        assert result is None

    def test_get_profile(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[
            {"peer_id": "peer-1", "static_facts_json": '["likes python"]', "dynamic_context_json": "", "preferences_json": "{}"}
        ]):
            result = mock_http_client.get_profile("peer-1")
        assert result is not None
        assert result["peer_id"] == "peer-1"

    def test_list_profiles_empty(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.list_profiles("ws-1")
        assert result == []

    def test_list_profiles(self, mock_http_client):
        with patch.object(mock_http_client, "_query", side_effect=[
            [{"id": "peer-1"}],
            [{"peer_id": "peer-1", "static_facts_json": "[]", "dynamic_context_json": "", "preferences_json": "{}"}],
        ]):
            result = mock_http_client.list_profiles("ws-1")
        assert len(result) == 1

    def test_search_profiles_empty(self, mock_http_client):
        """search_profiles returns empty list when no profiles match."""
        with patch.object(mock_http_client, "list_profiles", return_value=[]):
            result = mock_http_client.search_profiles("ws-1", "python")
        assert result == []

    def test_get_profile_context(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.get_profile_context("peer-1")
        assert result is None

    # --- Facts ---

    def test_add_fact(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.add_fact(
                "ws-1", "peer-1", "Alice knows Python", fact_type="dynamic",
                category="skill", confidence=0.9, source="manual", tier="L1"
            )
        assert result == {"status": "ok"}

    def test_list_facts_empty(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.list_facts("ws-1")
        assert result == []

    def test_list_facts_with_data(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"json_data": json.dumps([{"content": "fact1"}, {"content": "fact2"}])}
             ]):
            result = mock_http_client.list_facts("ws-1")
        assert len(result) == 2
        assert result[0]["content"] == "fact1"

    def test_delete_fact(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.delete_fact("fact-1")
        assert result == {"status": "ok"}

    def test_update_fact(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.update_fact("fact-1", content="Updated", confidence=0.95, category="skill", tier="L1")
        assert result == {"status": "ok"}

    def test_search_facts(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[
                 {"json_data": json.dumps([{"content": "result1"}])}
             ]):
            result = mock_http_client.search_facts("ws-1", "python")
        assert len(result) == 1

    # --- Node retrieval ---

    def test_get_node(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[{"id": "node-1", "label": "Python"}]):
            result = mock_http_client.get_node("node-1")
        assert len(result) == 1
        assert result[0]["id"] == "node-1"

    # --- Community details ---

    def test_get_community(self, mock_http_client):
        with patch.object(mock_http_client, "_query", side_effect=[
            [{"id": "42", "name": "Community 1"}],
            [{"id": "n1", "community_id": "42"}],
        ]):
            result = mock_http_client.get_community(42)
        assert result["community"] is not None
        assert result["community"]["id"] == "42"
        assert len(result["nodes"]) == 1

    def test_get_community_no_community(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.get_community(999)
        assert result["community"] is None

    # --- PageRank ---

    def test_compute_pagerank(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.compute_pagerank("ws-1", damping=0.85, max_iterations=100)
        assert result == {"status": "ok"}

    # --- Community hierarchy ---

    def test_compute_community_hierarchy(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.compute_community_hierarchy("ws-1")
        assert result == {"status": "ok"}

    # --- God nodes ---

    def test_compute_god_nodes(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.compute_god_nodes("ws-1", top_n=10)
        assert result == {"status": "ok"}

    # --- BFS / Shortest Path ---

    def test_graph_bfs(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.graph_bfs("ws-1", "node-1", max_depth=3)
        assert result is None

    def test_bfs_alias(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.bfs("ws-1", "node-1", max_depth=3)
        assert result is None

    def test_shortest_path(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.shortest_path("ws-1", "node-1", "node-5", max_hops=6)
        assert result is None

    def test_get_neighbors_via_reducer(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.get_neighbors_via_reducer("ws-1", "node-1")
        assert result is None

    # --- Ripple impact ---

    def test_detect_ripple_impact(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.detect_ripple_impact("ws-1", "node", "node-1")
        assert result == {"status": "ok"}

    def test_get_ripple_impacts(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.get_ripple_impacts("ws-1", "source-1")
        assert result is None

    def test_resolve_ripple_impact(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.resolve_ripple_impact("impact-1")
        assert result == {"status": "ok"}

    def test_dismiss_ripple_impact(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.dismiss_ripple_impact("impact-1")
        assert result == {"status": "ok"}

    def test_get_stale_nodes(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.get_stale_nodes("ws-1")
        assert result is None

    # --- Mental models ---

    def test_synthesize_mental_models(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.synthesize_mental_models("ws-1", ["mem-1", "mem-2"])
        assert result == {"status": "ok"}

    def test_get_mental_model(self, mock_http_client):
        with patch.object(mock_http_client, "_sql_param", return_value=[{"id": "mm-1", "content": "test"}]):
            result = mock_http_client.get_mental_model("mm-1")
        assert len(result) == 1

    def test_list_mental_models(self, mock_http_client):
        with patch.object(mock_http_client, "_sql_param", return_value=[{"id": "mm-1"}]):
            result = mock_http_client.list_mental_models("ws-1", status="completed")
        assert len(result) == 1

    def test_list_mental_models_no_status(self, mock_http_client):
        with patch.object(mock_http_client, "_sql_param", return_value=[]):
            result = mock_http_client.list_mental_models("ws-1")
        assert result == []

    def test_delete_mental_model(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.delete_mental_model("mm-1")
        assert result == {"status": "ok"}

    def test_update_mental_model(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.update_mental_model("mm-1", "New content", confidence=0.9, status="completed")
        assert result == {"status": "ok"}

    # --- Peers ---

    def test_update_peer(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.update_peer("peer-1", "Alice", '{"role": "admin"}')
        assert result == {"status": "ok"}

    def test_delete_peer(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.delete_peer("peer-1")
        assert result == {"status": "ok"}

    def test_get_peer_memory_summary(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.get_peer_memory_summary("peer-1")
        assert result is None

    # --- Cross-link ---

    def test_cross_link_no_memories(self, mock_http_client):
        with patch.object(mock_http_client, "_query", return_value=[]):
            result = mock_http_client.cross_link("ws-1")
        assert result == {"links_created": 0, "pairs_checked": 0}

    def test_cross_link_with_memories(self, mock_http_client):
        with patch.object(mock_http_client, "_query", side_effect=[
            [{"id": "mem-1", "content": "This is a test memory with enough length", "created_at": 100}],
            [{"id": "mem-2", "content": "Another test memory with enough length too", "created_at": 200}],
        ]), \
             patch.object(mock_http_client, "_sql", return_value=[]), \
             patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.cross_link("ws-1", limit=50)
        assert result["pairs_checked"] == 1
        assert result["links_created"] == 1

    # --- Lint workspace ---

    def test_lint_workspace(self, mock_http_client):
        with patch.object(mock_http_client, "_sql", side_effect=[
            [{"id": "n1"}, {"id": "n2"}],
            [],
            [],
        ]):
            result = mock_http_client.lint_workspace("ws-1")
        assert result["total"] == 2
        assert result["orphans"] == 2

    def test_lint_workspace_no_orphans(self, mock_http_client):
        with patch.object(mock_http_client, "_sql", side_effect=[
            [{"id": "n1"}],
            [{"id": "e1"}],
        ]):
            result = mock_http_client.lint_workspace("ws-1")
        assert result["total"] == 1
        assert result["orphans"] == 0

    # --- Suggest connections ---

    def test_suggest_connections(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_query", return_value=[{"id": "n1", "label": "Node 1"}]):
            result = mock_http_client.suggest_connections("ws-1")
        assert len(result) == 1

    # --- Store answer ---

    def test_store_answer_empty(self, mock_http_client):
        result = mock_http_client.store_answer("What?", "", "ws-1")
        assert result == {"note": {"id": "", "title": ""}, "entities": [], "links": 0}

    def test_store_answer_with_content(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}), \
             patch.object(mock_http_client, "_sql", return_value=[{"id": "note-1"}]):
            result = mock_http_client.store_answer("What is Python?", "Python is a language.", "ws-1")
        assert result["note"]["id"] == "note-1"

    # --- Search / list subscriptions ---

    def test_search_profiles_reducer(self, mock_http_client):
        with patch.object(mock_http_client, "list_profiles", return_value=[]):
            result = mock_http_client.search_profiles("ws-1", "python")
        assert result == []

    def test_list_subscriptions(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.list_subscriptions("ws-1")
        assert result == {"status": "ok"}

    def test_get_search_results(self, mock_http_client):
        with patch.object(mock_http_client, "_call", return_value={"status": "ok"}):
            result = mock_http_client.get_search_results("ws-1", "hash123")
        assert result == {"status": "ok"}
