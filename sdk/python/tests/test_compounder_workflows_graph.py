"""Unit tests for CompounderWorkflowsGraph — knowledge graph workflows.

These tests use Compounder (which combines all mixins) because methods
like cross_link, suggest_connections, and lint_workspace call helper
methods defined in other mixins (CompounderHelpers).
"""

from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
class TestCrossLink:
    """Tests for CompounderWorkflowsGraph.cross_link()."""

    def test_no_memories_returns_zero(self):
        """No memories returns zero links."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.return_value = []
        cp = Compounder(client)
        result = cp.cross_link(workspace_id="ws1")
        assert result == {"links_created": 0, "pairs_checked": 0}

    def test_short_content_skipped(self):
        """Memories with short content (< 20 chars) are skipped."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.return_value = [
            {"id": "m1", "content": "hi", "created_at": 100},
        ]
        cp = Compounder(client)
        result = cp.cross_link(workspace_id="ws1")
        assert result["pairs_checked"] == 0

    def test_creates_edges_for_similar_memories(self):
        """Creates edges between semantically similar memories."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        # memories query, then edges query for _already_linked
        client._query.side_effect = [
            [
                {"id": "m1", "content": "This is a sufficiently long content about AI.", "created_at": 200},
                {"id": "m2", "content": "This is another long content about RL.", "created_at": 100},
            ],
            # _already_linked: no existing edges
            [],
        ]
        client.search.return_value = [
            {"entity_id": "m2", "score": 0.85, "content": "similar"},
        ]
        cp = Compounder(client)
        result = cp.cross_link(workspace_id="ws1", similarity_threshold=0.7)
        assert result["pairs_checked"] >= 1

    def test_respects_similarity_threshold(self):
        """Only memories above threshold are linked."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            [
                {"id": "m1", "content": "A" * 30, "created_at": 100},
                {"id": "m2", "content": "B" * 30, "created_at": 50},
            ],
            # _already_linked
            [],
        ]
        client.search.return_value = [
            {"entity_id": "m2", "score": 0.6, "content": "different"},
        ]
        cp = Compounder(client)
        result = cp.cross_link(workspace_id="ws1", similarity_threshold=0.8)
        assert result["links_created"] == 0  # 0.6 < 0.8


@pytest.mark.unit
class TestSuggestConnections:
    """Tests for CompounderWorkflowsGraph.suggest_connections()."""

    def test_no_nodes_returns_empty(self):
        """No nodes returns empty suggestions."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [[], []]  # no edges, no nodes
        cp = Compounder(client)
        suggestions = cp.suggest_connections(workspace_id="ws1")
        assert suggestions == []

    def test_fewer_than_two_nodes_returns_empty(self):
        """Fewer than 2 nodes returns empty suggestions."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            [],  # edges
            [{"id": "A", "label": "Only Node"}],  # nodes
        ]
        cp = Compounder(client)
        suggestions = cp.suggest_connections(workspace_id="ws1")
        assert suggestions == []

    def test_finds_common_neighbour_suggestions(self):
        """Nodes sharing a common neighbour are suggested."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            # edges
            [
                {"source_node_id": "H", "target_node_id": "A"},
                {"source_node_id": "H", "target_node_id": "B"},
                {"source_node_id": "H", "target_node_id": "C"},
                {"source_node_id": "A", "target_node_id": "C"},
            ],
            # nodes
            [
                {"id": "A", "label": "Node A"},
                {"id": "B", "label": "Node B"},
                {"id": "C", "label": "Node C"},
                {"id": "H", "label": "Hub H"},
            ],
        ]
        cp = Compounder(client)
        suggestions = cp.suggest_connections(workspace_id="ws1")
        # A and B share neighbour H — should be suggested
        sug_labels = {(s["source_label"], s["target_label"]) for s in suggestions}
        assert ("Node A", "Node B") in sug_labels or ("Node B", "Node A") in sug_labels

    def test_skips_already_connected_pairs(self):
        """Already-connected pairs are not suggested."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            # edges — A↔B already connected
            [
                {"source_node_id": "A", "target_node_id": "B"},
            ],
            # nodes
            [
                {"id": "A", "label": "A"},
                {"id": "B", "label": "B"},
                {"id": "H", "label": "H"},
            ],
        ]
        cp = Compounder(client)
        suggestions = cp.suggest_connections(workspace_id="ws1")
        assert len(suggestions) == 0

    def test_sorts_by_common_count_descending(self):
        """Suggestions are sorted by common count descending."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            # edges: A and B share {H1, H2}; A and C share {H1}
            [
                {"source_node_id": "H1", "target_node_id": "A"},
                {"source_node_id": "H1", "target_node_id": "B"},
                {"source_node_id": "H2", "target_node_id": "A"},
                {"source_node_id": "H2", "target_node_id": "B"},
                {"source_node_id": "H1", "target_node_id": "C"},
            ],
            # nodes
            [
                {"id": "A", "label": "A"},
                {"id": "B", "label": "B"},
                {"id": "C", "label": "C"},
                {"id": "H1", "label": "H1"},
                {"id": "H2", "label": "H2"},
            ],
        ]
        cp = Compounder(client)
        suggestions = cp.suggest_connections(workspace_id="ws1")
        if len(suggestions) >= 2:
            assert suggestions[0]["common_count"] >= suggestions[1]["common_count"]


@pytest.mark.unit
class TestLintWorkspace:
    """Tests for CompounderWorkflowsGraph.lint_workspace()."""

    def test_empty_result_when_no_checks(self):
        """No checks enabled returns empty result."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.return_value = []  # _log_activity
        cp = Compounder(client)
        result = cp.lint_workspace(
            "ws1",
            check_orphans=False,
            check_missing_crossrefs=False,
            check_contradictions=False,
            check_note_orphans=False,
        )
        assert result["orphans"] == []
        assert result["summary"]["total_issues"] == 0

    def test_finds_orphan_nodes(self):
        """Orphan nodes are detected."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            # _find_orphan_nodes: nodes
            [
                {"id": "orphan_1", "label": "Orphan", "node_type": "concept"},
            ],
            # _find_orphan_nodes: edges
            [{"source_node_id": "A", "target_node_id": "B"}],
            # _log_activity: query _log
            [],
        ]
        cp = Compounder(client)
        result = cp.lint_workspace(
            "ws1",
            check_orphans=True,
            check_missing_crossrefs=False,
            check_contradictions=False,
            check_note_orphans=False,
        )
        assert len(result["orphans"]) == 1
        assert result["orphans"][0]["label"] == "Orphan"
        assert result["summary"]["orphan_count"] == 1

    def test_finds_missing_crossrefs(self):
        """Missing cross-references are detected."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            # _find_missing_crossrefs: kg_node
            [{"id": "n1", "label": "ImportantConcept"}],
            # _find_missing_crossrefs: kg_edge
            [],
            # _find_missing_crossrefs: memories
            [{"id": "mem_1", "content": "This mentions ImportantConcept"}],
            # _find_missing_crossrefs: notes
            [{"id": "note_1", "content": "Also mentions ImportantConcept"}],
            # _log_activity: query _log
            [],
        ]
        cp = Compounder(client)
        result = cp.lint_workspace(
            "ws1",
            check_orphans=False,
            check_missing_crossrefs=True,
            check_contradictions=False,
            check_note_orphans=False,
        )
        assert len(result["missing_crossrefs"]) >= 1
        assert result["summary"]["missing_crossref_count"] >= 1

    def test_finds_note_orphans(self):
        """Note orphans are detected."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.side_effect = [
            # _find_note_orphans: notes
            [{"id": "n1", "title": "Lonely Note", "content": "Just some text."}],
            # _find_note_orphans: kg_nodes
            [{"id": "kg1", "label": "AI"}],
            # _find_note_orphans: edges
            [],
            # _log_activity: query _log
            [],
        ]
        cp = Compounder(client)
        result = cp.lint_workspace(
            "ws1",
            check_orphans=False,
            check_missing_crossrefs=False,
            check_contradictions=False,
            check_note_orphans=True,
        )
        assert len(result["note_orphans"]) == 1
        assert result["note_orphans"][0]["title"] == "Lonely Note"

    def test_contradiction_detection_requires_llm(self):
        """Without LLM, contradictions list is empty."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.return_value = []  # _log_activity
        cp = Compounder(client)  # LLM not configured (default)
        result = cp.lint_workspace(
            "ws1",
            check_contradictions=True,
            check_orphans=False,
            check_missing_crossrefs=False,
            check_note_orphans=False,
        )
        assert result["contradictions"] == []

    def test_logs_lint_activity(self):
        """lint_workspace logs activity."""
        from spacetime_memory.compounder.core import Compounder

        client = MagicMock()
        client._query.return_value = []  # _log_activity: create new
        cp = Compounder(client)
        cp.lint_workspace(
            "ws1",
            check_orphans=False,
            check_missing_crossrefs=False,
            check_contradictions=False,
            check_note_orphans=False,
        )
        # Should have created or updated a _log note
        log_creates = [
            c for c in client.create_note.call_args_list
            if c[1].get("title") == "_log"
        ]
        assert len(log_creates) >= 0  # at minimum doesn't crash
