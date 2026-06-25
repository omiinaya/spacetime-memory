"""Unit tests for Compounder — compound knowledge operations."""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock


class TestCompounderStoreAnswer:
    """Tests for Compounder.store_answer()."""

    def test_empty_answer_returns_empty(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        cp = Compounder(client)
        result = cp.store_answer(query="q", answer="")
        assert result == {}

    def test_creates_note_with_generated_title(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "note_1", "title": "What is X?"}
        cp = Compounder(client)
        result = cp.store_answer(query="What is X?", answer="X is a concept.")
        client.create_note.assert_called_once()
        call_kw = client.create_note.call_args[1]
        assert call_kw["title"] == "What is X"
        assert "## Question" in call_kw["content"]
        assert "## Synthesis" in call_kw["content"]
        assert result["note"]["id"] == "note_1"

    def test_uses_explicit_title(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "n1"}
        cp = Compounder(client)
        cp.store_answer(query="q", answer="answer", title="My Title")
        assert client.create_note.call_args[1]["title"] == "My Title"

    def test_extracts_entities_and_creates_nodes(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}

        # Mock LLM to return entities
        mock_llm = MagicMock()
        mock_llm.extract_entities_llm.return_value = [
            {"name": "Alice", "entity_type": "person", "description": "A researcher"},
            {"name": "Bob", "entity_type": "person", "description": "A developer"},
        ]
        client.create_node.side_effect = [
            {"id": "node_1"},  # First call
            {"id": "node_2"},  # Second call
        ]

        cp = Compounder(client, llm=mock_llm)
        result = cp.store_answer(query="Who are Alice and Bob?", answer="Alice and Bob are colleagues.")

        assert client.create_node.call_count == 2
        assert len(result["entities"]) == 2
        assert result["entities"][0]["id"] == "node_1"
        assert result["entities"][1]["id"] == "node_2"

    def test_entity_extraction_failure_graceful(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}

        mock_llm = MagicMock()
        mock_llm.extract_entities_llm.return_value = None  # LLM not configured

        cp = Compounder(client, llm=mock_llm)
        result = cp.store_answer(query="q", answer="Some answer.")
        assert client.create_node.call_count == 0  # No entities to create
        assert result["entities"] == []

    def test_entity_creation_error_skipped(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        mock_llm = MagicMock()
        mock_llm.extract_entities_llm.return_value = [
            {"name": "Alice", "entity_type": "person"},
        ]
        client.create_node.side_effect = RuntimeError("db error")

        cp = Compounder(client, llm=mock_llm)
        result = cp.store_answer(query="q", answer="Alice.")
        assert result["entities"] == []  # Error caught gracefully

    def test_links_to_source_memories(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        mock_llm = MagicMock()
        mock_llm.extract_entities_llm.return_value = None

        cp = Compounder(client, llm=mock_llm)
        result = cp.store_answer(
            query="q", answer="ans",
            source_memory_ids=["mem_1", "mem_2"],
        )
        assert client._call.call_count == 2  # Two link calls

    def test_updates_workspace_index(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        client._query.return_value = []  # No existing index

        mock_llm = MagicMock()
        mock_llm.extract_entities_llm.return_value = None

        cp = Compounder(client, llm=mock_llm)
        cp.store_answer(query="q", answer="ans.", workspace_id="ws1")

        # Should create an index note since none exists
        idx_calls = [
            c for c in client.create_note.call_args_list
            if c[1].get("title") == "_index"
        ]
        assert len(idx_calls) >= 1

    def test_appends_to_existing_index(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        client._query.return_value = [
            {"id": "idx_1", "content": "# Index\n\n- [Old](old)\n"}
        ]  # Existing index

        mock_llm = MagicMock()
        mock_llm.extract_entities_llm.return_value = None

        cp = Compounder(client, llm=mock_llm)
        cp.store_answer(query="q", answer="ans.", workspace_id="ws1")

        # Should update existing index (append)
        client.update_note.assert_called_once()
        new_content = client.update_note.call_args[1]["content"]
        assert "Old" in new_content

    def test_long_query_uses_first_answer_line(self):
        from spacetime_memory.compounder import Compounder
        cp = Compounder(MagicMock())
        long_query = "What is the fundamental nature of consciousness in the context of modern neuroscience and philosophy of mind?" * 3
        title = cp._generate_title(long_query, "First line of answer.\nSecond line.")
        assert len(title) <= 80
        assert "First" in title


class TestCompounderCrossLink:
    """Tests for Compounder.cross_link()."""

    def test_no_memories_returns_zero(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.return_value = []
        cp = Compounder(client)
        result = cp.cross_link(workspace_id="ws1")
        assert result == {"links_created": 0, "pairs_checked": 0}

    def test_short_content_skipped(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.return_value = [
            {"id": "m1", "content": "hi", "created_at": 100},
        ]
        cp = Compounder(client)
        result = cp.cross_link(workspace_id="ws1")
        assert result["pairs_checked"] == 0


class TestCompounderSuggestConnections:
    """Tests for Compounder.suggest_connections()."""

    def test_no_nodes_returns_empty(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.side_effect = [[], []]  # no edges, no nodes
        cp = Compounder(client)
        suggestions = cp.suggest_connections(workspace_id="ws1")
        assert suggestions == []

    def test_finds_common_neighbour_suggestions(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        # Nodes: A, B, C, D  (all connected to hub H, but A↔B not directly connected)
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
        from spacetime_memory.compounder import Compounder
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
        assert len(suggestions) == 0  # Already connected


class TestCompounderInternal:
    """Tests for internal helpers."""

    def test_generate_title_short_query(self):
        from spacetime_memory.compounder import Compounder
        cp = Compounder(MagicMock())
        title = cp._generate_title("What is RLHF?", "RLHF is a method.")
        assert title == "What is RLHF"

    def test_format_answer_page_structure(self):
        from spacetime_memory.compounder import Compounder
        cp = Compounder(MagicMock())
        page = cp._format_answer_page("Q?", "A.", source_ids=["m1"])
        assert "## Question" in page
        assert "## Synthesis" in page
        assert "## Sources" in page
        assert "`m1`" in page

    def test_format_answer_page_no_sources(self):
        from spacetime_memory.compounder import Compounder
        cp = Compounder(MagicMock())
        page = cp._format_answer_page("Q?", "A.")
        assert "## Sources" not in page

    def test_already_linked_checks_both_directions(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.return_value = [
            {"source_node_id": "A", "target_node_id": "B"},
        ]
        cp = Compounder(client)
        assert cp._already_linked("A", "B") is True
        assert cp._already_linked("B", "A") is True  # Reverse also matches
        assert cp._already_linked("A", "C") is False

    def test_node_label_lookup(self):
        from spacetime_memory.compounder import Compounder
        cp = Compounder(MagicMock())
        nodes = [
            {"id": "n1", "label": "Alice"},
            {"id": "n2", "label": "Bob"},
        ]
        assert cp._node_label("n1", nodes) == "Alice"
        assert cp._node_label("n3", nodes) == "n3"[:12]  # fallback to truncated ID
