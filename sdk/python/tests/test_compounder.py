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
        ]  # Existing index (will also be found for _log query)

        mock_llm = MagicMock()
        mock_llm.available = False
        mock_llm.extract_entities_llm.return_value = None

        cp = Compounder(client, llm=mock_llm)
        cp.store_answer(query="q", answer="ans.", workspace_id="ws1")

        # Should update existing index (append)
        idx_calls = [
            c for c in client.update_note.call_args_list
            if c[1].get("title") == "_index"
        ]
        assert len(idx_calls) >= 1
        new_content = idx_calls[0][1]["content"]
        assert "Old" in new_content

    def test_long_query_uses_first_answer_line(self):
        from spacetime_memory.compounder import Compounder
        cp = Compounder(MagicMock())
        long_query = "What is the fundamental nature of consciousness in the context of modern neuroscience and philosophy of mind?" * 3
        title = cp._generate_title(long_query, "First line of answer.\nSecond line.")
        assert len(title) <= 80
        assert "First" in title


class TestCompounderStoreAnswers:
    """Tests for Compounder.store_answers()."""

    def test_empty_pairs_returns_empty(self):
        from spacetime_memory.compounder import Compounder
        cp = Compounder(MagicMock())
        results = cp.store_answers([])
        assert results == []

    def test_stores_multiple_answers(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        client._query.return_value = []  # no existing index
        mock_llm = MagicMock()
        mock_llm.available = False
        mock_llm.extract_entities_llm.return_value = None

        cp = Compounder(client, llm=mock_llm)
        results = cp.store_answers([
            ("What is RLHF?", "RLHF stands for Reinforcement Learning from Human Feedback."),
            ("What is GPT?", "GPT is a generative pre-trained transformer."),
        ], workspace_id="ws1")

        assert len(results) == 2
        assert results[0]["note"] == {"id": "note_1"}
        assert results[1]["note"] == {"id": "note_1"}

    def test_handles_single_error_gracefully(self):
        from spacetime_memory.compounder import Compounder
        cp = Compounder(MagicMock())
        # Mock store_answer on the instance to raise on second call
        original = cp.store_answer
        call_count = 0

        def mock_store(query, answer, workspace_id="default",
                       source_memory_ids=None, title=None, embed=True):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Simulated failure")
            return {"note": {"id": f"note_{call_count}"},
                    "entities": [], "links": []}

        cp.store_answer = mock_store

        results = cp.store_answers([
            ("Q1", "A1"),
            ("Q2", "A2"),
            ("Q3", "A3"),
        ], workspace_id="ws1")

        assert len(results) == 3
        # First should have succeeded
        assert results[0]["note"]["id"] == "note_1"
        # Second should be empty dict (error caught)
        assert results[1] == {"note": {}, "entities": [], "links": []}
        # Third should have succeeded
        assert results[2]["note"]["id"] == "note_3"


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


class TestLogActivity:
    """Tests for _log_activity()."""

    def test_creates_log_note_when_none_exists(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.return_value = []  # No existing log
        cp = Compounder(client)
        cp._log_activity("ws1", "test", "detail")
        # Should create a _log note
        create_calls = [c for c in client.create_note.call_args_list
                        if c[1].get("title") == "_log"]
        assert len(create_calls) == 1

    def test_appends_to_existing_log(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.return_value = [
            {"id": "log_1", "content": "# Log\n\n## [old] prior | entry\n"}
        ]
        cp = Compounder(client)
        cp._log_activity("ws1", "store_answer", "test detail")
        assert client.update_note.call_count >= 1


class TestLintWorkspace:
    """Tests for lint_workspace()."""

    def test_orphan_detection(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        # _log_activity also calls _query — provide extra entries
        client._query.side_effect = [
            [{"id": "C", "label": "Orphan", "node_type": "concept"}],  # nodes (from _find_orphan_nodes)
            [{"source_node_id": "A", "target_node_id": "B"}],  # edges (from _find_orphan_nodes)
            [],  # _log_activity: query for existing _log note
        ]
        cp = Compounder(client)
        result = cp.lint_workspace("ws1", check_orphans=True,
                                    check_missing_crossrefs=False,
                                    check_contradictions=False)
        assert len(result["orphans"]) == 1
        assert result["orphans"][0]["label"] == "Orphan"
        assert result["summary"]["orphan_count"] == 1

    def test_no_orphans_when_all_connected(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.side_effect = [
            [{"id": "A", "label": "A"}],  # nodes
            [{"source_node_id": "A", "target_node_id": "B"}],  # edges
            [],  # _log_activity
        ]
        cp = Compounder(client)
        result = cp.lint_workspace("ws1", check_orphans=True,
                                    check_missing_crossrefs=False,
                                    check_contradictions=False)
        assert result["summary"]["orphan_count"] == 0

    def test_missing_crossrefs(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.side_effect = [
            [{"id": "n1", "label": "ImportantConcept"}],  # kg_node
            [],  # kg_edge — no existing links
            [{"id": "mem_1", "content": "This mentions ImportantConcept in passing"}],  # memory
            [{"id": "note_1", "content": "Also mentions ImportantConcept"}],  # note
            [],  # _log_activity
        ]
        cp = Compounder(client)
        result = cp.lint_workspace("ws1", check_orphans=False,
                                    check_missing_crossrefs=True,
                                    check_contradictions=False)
        assert len(result["missing_crossrefs"]) >= 1
        assert result["summary"]["missing_crossref_count"] >= 1

    def test_contradiction_detection_requires_llm(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        cp = Compounder(client)  # LLM not configured (default)
        result = cp.lint_workspace("ws1", check_contradictions=True)
        assert result["contradictions"] == []

    def test_contradiction_with_llm(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        mock_llm = MagicMock()
        mock_llm.available = True
        mock_llm.chat.return_value = '{"is_contradiction": true, "explanation": "They say opposite things"}'
        client._query.return_value = [
            {"id": "m1", "content": "The sky is blue.", "created_at": 100},
            {"id": "m2", "content": "The sky is green.", "created_at": 200},
        ]
        cp = Compounder(client, llm=mock_llm)
        result = cp.lint_workspace("ws1", check_contradictions=True,
                                    check_orphans=False, check_missing_crossrefs=False)
        assert len(result["contradictions"]) == 1
        assert result["contradictions"][0]["explanation"] == "They say opposite things"


class TestRippleUpdate:
    """Tests for _ripple_update_entity()."""

    def test_skips_when_llm_unavailable(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        mock_llm = MagicMock()
        mock_llm.available = False
        cp = Compounder(client, llm=mock_llm)
        cp._ripple_update_entity("ws1", "Alice", "new info", "note_1")
        client._query.assert_not_called()

    def test_skips_when_no_node_found(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        mock_llm = MagicMock()
        mock_llm.available = True
        client._query.return_value = []  # No matching node
        cp = Compounder(client, llm=mock_llm)
        cp._ripple_update_entity("ws1", "UnknownEntity", "info", "n1")
        # Should not crash
        assert True

    def test_uses_llm_to_merge_existing_summary(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        mock_llm = MagicMock()
        mock_llm.available = True
        mock_llm.summarize.return_value = "Updated summary with new info integrated."
        client._query.return_value = [
            {"id": "node_1", "label": "Alice", "summary": "Original summary",
             "node_type": "person"},
        ]
        cp = Compounder(client, llm=mock_llm)
        cp._ripple_update_entity("ws1", "Alice",
                                  "Alice published a new paper on RL.",
                                  "note_1")
        # Should call update_node reducer
        client._call.assert_called_once()
        args = client._call.call_args
        assert args[0][0] == "update_node"
        assert "Updated summary" in str(args[0][1])


class TestIngestSource:
    """Tests for Compounder.ingest_source()."""

    def test_empty_text_returns_empty(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        cp = Compounder(client)
        result = cp.ingest_source(source_text="", source_title="Test")
        assert result["note"] == {}
        assert result["entities"] == []

    def test_creates_summary_note(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        cp = Compounder(client)
        result = cp.ingest_source(
            source_text="This is a test article about AI.",
            source_title="Test Article",
        )
        client.create_note.assert_called_once()
        call_kw = client.create_note.call_args[1]
        assert "Source: Test Article" in call_kw["title"]
        assert "## Summary" in call_kw["content"]
        assert result["note"]["id"] == "note_1"

    def test_uses_llm_summary_when_available(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        mock_llm = MagicMock()
        mock_llm.available = True
        mock_llm.summarize.return_value = "LLM generated summary."
        mock_llm.extract_entities_llm.return_value = None

        cp = Compounder(client, llm=mock_llm)
        cp.ingest_source(
            source_text="Long article text about machine learning.",
            source_title="ML Article",
        )
        # Summary should be LLM-generated
        call_kw = client.create_note.call_args[1]
        assert "LLM generated summary" in call_kw["content"]

    def test_extracts_entities_when_llm_available(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        client.create_node.side_effect = [
            {"id": "node_1"},
            {"id": "node_2"},
        ]

        mock_llm = MagicMock()
        mock_llm.available = True
        mock_llm.summarize.return_value = None  # Falls back to raw text
        mock_llm.extract_entities_llm.return_value = [
            {"name": "GPT-4", "entity_type": "product", "description": "A language model"},
            {"name": "OpenAI", "entity_type": "org", "description": "AI company"},
        ]

        cp = Compounder(client, llm=mock_llm)
        result = cp.ingest_source(
            source_text="GPT-4 by OpenAI is a language model.",
            source_title="GPT-4 Overview",
        )
        assert len(result["entities"]) == 2
        assert result["entities"][0]["id"] == "node_1"

    def test_links_entities_to_source_note(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        client.create_node.return_value = {"id": "node_1"}

        mock_llm = MagicMock()
        mock_llm.available = True
        mock_llm.summarize.return_value = None
        mock_llm.extract_entities_llm.return_value = [
            {"name": "GPT-4", "entity_type": "product"},
        ]

        cp = Compounder(client, llm=mock_llm)
        result = cp.ingest_source(
            source_text="GPT-4 by OpenAI.",
            source_title="Test",
        )
        assert len(result["links"]) == 1

    def test_checks_contradictions_on_ingest(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        client.search.return_value = [
            {"entity_id": "mem_1", "content": "The sky is blue."},
        ]

        mock_llm = MagicMock()
        mock_llm.available = True
        mock_llm.summarize.return_value = "Summary text."
        mock_llm.extract_entities_llm.return_value = None
        mock_llm.chat.return_value = (
            '{"is_contradiction": true, '
            '"explanation": "Colors differ."}'
        )

        cp = Compounder(client, llm=mock_llm)
        result = cp.ingest_source(
            source_text="The sky is green.",
            source_title="Test",
        )
        assert len(result["contradictions"]) == 1
        assert result["contradictions"][0]["explanation"] == "Colors differ."

    def test_no_contradictions_when_llm_unavailable(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        cp = Compounder(client)  # Default LLM — not available
        result = cp.ingest_source(
            source_text="Some content.",
            source_title="Test",
        )
        assert result["contradictions"] == []

    def test_updates_index_and_log(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        client._query.return_value = []  # No existing index/log
        cp = Compounder(client)
        result = cp.ingest_source(
            source_text="Content here.",
            source_title="Log Test",
        )
        # Should create index note
        idx_calls = [c for c in client.create_note.call_args_list
                     if c[1].get("title") == "_index"]
        assert len(idx_calls) >= 1


class TestProactiveContradiction:
    """Tests for _check_contradictions_on_ingest()."""

    def test_returns_empty_when_llm_unavailable(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        cp = Compounder(client)
        result = cp._check_contradictions_on_ingest("ws1", "new content", "n1")
        assert result == []

    def test_returns_empty_when_no_similar_memories(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.search.return_value = []
        mock_llm = MagicMock()
        mock_llm.available = True

        cp = Compounder(client, llm=mock_llm)
        result = cp._check_contradictions_on_ingest("ws1", "new", "n1")
        assert result == []

    def test_detects_contradiction(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.search.return_value = [
            {"entity_id": "mem_1", "content": "The sky is blue."},
        ]
        mock_llm = MagicMock()
        mock_llm.available = True
        mock_llm.chat.return_value = (
            '{"is_contradiction": true, "explanation": "Opposite claims"}'
        )

        cp = Compounder(client, llm=mock_llm)
        result = cp._check_contradictions_on_ingest("ws1", "The sky is red.", "src_1")
        assert len(result) == 1
        assert result[0]["memory_id"] == "mem_1"
        # Should create contradiction note
        client.create_note.assert_called_once()

    def test_skips_non_contradictory(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.search.return_value = [
            {"entity_id": "mem_1", "content": "Water is wet."},
        ]
        mock_llm = MagicMock()
        mock_llm.available = True
        mock_llm.chat.return_value = (
            '{"is_contradiction": false, "explanation": "Consistent"}'
        )

        cp = Compounder(client, llm=mock_llm)
        result = cp._check_contradictions_on_ingest("ws1", "Water is liquid.", "src_1")
        assert result == []


class TestEntityPage:
    """Tests for create_entity_page()."""

    def test_creates_note_and_node(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.return_value = []  # No existing node
        client.create_node.return_value = {"id": "node_1", "label": "Alice"}
        client.create_note.return_value = {"id": "note_1"}

        cp = Compounder(client)
        result = cp.create_entity_page(
            name="Alice",
            description="A researcher.",
            entity_type="person",
        )
        assert result["node"]["id"] == "node_1"
        assert result["note"]["id"] == "note_1"
        client.create_node.assert_called_once()
        # create_note called for entity page + _log
        assert client.create_note.call_count >= 1
        first_call = client.create_note.call_args_list[0]
        assert "Alice" in first_call[1]["title"]

    def test_reuses_existing_node(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.return_value = [
            {"id": "node_1", "label": "Alice"},
        ]  # Node already exists
        client.create_note.return_value = {"id": "note_1"}

        cp = Compounder(client)
        result = cp.create_entity_page(name="Alice", description="A researcher.")
        assert result["node"]["id"] == "node_1"
        client.create_node.assert_not_called()  # Should not re-create

    def test_includes_yaml_frontmatter(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.return_value = []
        client.create_node.return_value = {"id": "n1"}
        client.create_note.return_value = {"id": "note_1"}

        cp = Compounder(client)
        cp.create_entity_page(
            name="Test Entity",
            description="A test.",
            tags=["ai", "research"],
        )
        call_kw = client.create_note.call_args_list[0][1]
        assert "type: concept" in call_kw["content"]
        assert "tags: [ai, research]" in call_kw["content"]
        assert "## Overview" in call_kw["content"]

    def test_creates_edge_between_note_and_node(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.return_value = []
        client.create_node.return_value = {"id": "node_1"}
        client.create_note.return_value = {"id": "note_1"}

        cp = Compounder(client)
        cp.create_entity_page(name="Alice", description="A person.")
        client._call.assert_called_once()
        args = client._call.call_args
        assert args[0][0] == "create_edge"
        assert "note_1" in str(args[0][1])
        assert "node_1" in str(args[0][1])


class TestConceptPage:
    """Tests for create_concept_page()."""

    def test_creates_concept_note_with_definition(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}
        client.create_node.return_value = {"id": "node_1"}

        cp = Compounder(client)
        result = cp.create_concept_page(
            concept="RLHF",
            definition="Reinforcement Learning from Human Feedback.",
        )
        assert result["note"]["id"] == "note_1"
        call_kw = client.create_note.call_args_list[0][1]
        assert "Concept: RLHF" in call_kw["title"]
        assert "Reinforcement Learning" in call_kw["content"]
        assert "type: concept" in call_kw["content"]

    def test_includes_related_concepts(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "n1"}
        client.create_node.return_value = {"id": "node_1"}

        cp = Compounder(client)
        cp.create_concept_page(
            concept="DPO",
            definition="Direct Preference Optimization.",
            related_concepts=["RLHF", "PPO"],
        )
        call_kw = client.create_note.call_args_list[0][1]
        assert "[[RLHF]]" in call_kw["content"]
        assert "[[PPO]]" in call_kw["content"]


class TestComparisonPage:
    """Tests for create_comparison_page()."""

    def test_creates_comparison_table(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "note_1"}

        cp = Compounder(client)
        result = cp.create_comparison_page(
            title="RLHF vs DPO",
            items=[
                {"name": "RLHF", "type": "reward-based", "complexity": "High"},
                {"name": "DPO", "type": "direct", "complexity": "Low"},
            ],
        )
        assert result["note"]["id"] == "note_1"
        call_kw = client.create_note.call_args_list[0][1]
        assert "Comparison: RLHF vs DPO" in call_kw["title"]
        assert "| Name | Type | Complexity |" in call_kw["content"]
        assert "| RLHF | reward-based | High |" in call_kw["content"]
        assert "| DPO | direct | Low |" in call_kw["content"]

    def test_empty_items_returns_empty(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        cp = Compounder(client)
        result = cp.create_comparison_page(title="Empty", items=[])
        assert result["note"] == {}

    def test_single_item_still_creates_table(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client.create_note.return_value = {"id": "n1"}

        cp = Compounder(client)
        result = cp.create_comparison_page(
            title="Single",
            items=[{"name": "Only Item", "value": "42"}],
        )
        assert result["note"]["id"] == "n1"


class TestExportWorkspace:
    """Tests for Compounder.export_workspace()."""

    def test_empty_workspace_returns_zero(self, tmp_path):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.return_value = []
        cp = Compounder(client)
        result = cp.export_workspace(
            output_dir=str(tmp_path),
            workspace_id="ws1",
        )
        assert result["files_written"] == 0

    def test_exports_notes_as_markdown(self, tmp_path):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        # _query for notes, then edges, then _log_activity
        client._query.side_effect = [
            [
                {"id": "n1", "title": "Test Note", "content": "Hello world.",
                 "created_at": "2026-06-25", "updated_at": "2026-06-25"},
                {"id": "n2", "title": "Another Note", "content": "More text.",
                 "created_at": "2026-06-24", "updated_at": "2026-06-24"},
            ],
            [],  # edges (no backlinks)
        ]
        cp = Compounder(client)
        result = cp.export_workspace(
            output_dir=str(tmp_path),
            workspace_id="ws1",
        )
        assert result["files_written"] == 2
        # Check files exist
        files = list(tmp_path.iterdir())
        assert len(files) == 2

    def test_exports_yaml_frontmatter(self, tmp_path):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.side_effect = [
            [
                {"id": "n1", "title": "My Page", "content": "Content here.",
                 "created_at": "2026-06-25", "updated_at": ""},
            ],
            [],  # edges
        ]
        cp = Compounder(client)
        result = cp.export_workspace(
            output_dir=str(tmp_path),
            workspace_id="ws1",
        )
        assert result["files_written"] == 1
        content = (tmp_path / "My Page.md").read_text()
        assert "---" in content
        assert 'id: "n1"' in content
        assert 'title: "My Page"' in content
        assert "Content here." in content

    def test_skips_system_notes_by_default(self, tmp_path):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.side_effect = [
            [
                {"id": "n1", "title": "_index", "content": "Index",
                 "created_at": "", "updated_at": ""},
                {"id": "n2", "title": "Real Note", "content": "Real",
                 "created_at": "", "updated_at": ""},
            ],
            [],  # edges
        ]
        cp = Compounder(client)
        result = cp.export_workspace(
            output_dir=str(tmp_path),
            workspace_id="ws1",
        )
        assert result["files_written"] == 1
        assert not (tmp_path / "_index.md").exists()

    def test_includes_system_notes_when_requested(self, tmp_path):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.side_effect = [
            [
                {"id": "n1", "title": "_log", "content": "Log entry",
                 "created_at": "", "updated_at": ""},
                {"id": "n2", "title": "Real Note", "content": "Real",
                 "created_at": "", "updated_at": ""},
            ],
            [],  # edges
        ]
        cp = Compounder(client)
        result = cp.export_workspace(
            output_dir=str(tmp_path),
            workspace_id="ws1",
            include_system_notes=True,
        )
        assert result["files_written"] == 2
        assert (tmp_path / "_log.md").exists()

    def test_export_kg_nodes(self, tmp_path):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        # First call: notes, Second call: edges, Third call: nodes
        client._query.side_effect = [
            [],  # notes
            [],  # edges
            [
                {"id": "kg1", "label": "Alice", "node_type": "person",
                 "summary": "A researcher."},
                {"id": "kg2", "label": "RLHF", "node_type": "concept",
                 "summary": "A training method."},
            ],
        ]
        cp = Compounder(client)
        result = cp.export_workspace(
            output_dir=str(tmp_path),
            workspace_id="ws1",
            include_kg=True,
        )
        kg_dir = tmp_path / "_kg_nodes"
        assert kg_dir.exists()
        assert result["files_written"] == 2

    def test_sanitizes_filenames(self, tmp_path):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.side_effect = [
            [
                {"id": "n1", "title": "Special: chars/here?",
                 "content": "test", "created_at": "", "updated_at": ""},
            ],
            [],
        ]
        cp = Compounder(client)
        result = cp.export_workspace(
            output_dir=str(tmp_path),
            workspace_id="ws1",
        )
        assert result["files_written"] == 1
        # Should have sanitized the filename
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert "?" not in files[0].name
        assert "/" not in files[0].name


class TestGenerateOverview:
    """Tests for Compounder.generate_overview_page()."""

    def test_empty_workspace_returns_empty(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.return_value = []
        cp = Compounder(client)
        result = cp.generate_overview_page(workspace_id="ws1")
        assert result["note"] == {}

    def test_creates_overview_note(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.side_effect = [
            [
                {"id": "n1", "title": "Test Note", "content": "Some content",
                 "created_at": "", "updated_at": ""},
            ],
            [
                {"id": "kg1", "label": "Alice", "node_type": "person",
                 "summary": "A researcher."},
            ],
            [],  # edges
            [],  # _log_activity: query for existing _log
        ]
        client.create_note.return_value = {"id": "overview_1"}
        mock_llm = MagicMock()
        mock_llm.available = False

        cp = Compounder(client, llm=mock_llm)
        result = cp.generate_overview_page(workspace_id="ws1")
        assert result["note"]["id"] == "overview_1"
        # Check the note content — use first create_note call
        first_note_call = client.create_note.call_args_list[0]
        assert first_note_call[1]["title"] == "_overview"
        assert "Workspace Overview" in first_note_call[1]["content"]
        assert "**1** notes" in first_note_call[1]["content"]
        assert "A researcher" in first_note_call[1]["content"]  # from node summary

    def test_includes_entity_tables(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.side_effect = [
            [
                {"id": "n1", "title": "Source: Article", "content": "type: article",
                 "created_at": "", "updated_at": ""},
            ],
            [
                {"id": "kg1", "label": "Alice", "node_type": "person",
                 "summary": "A researcher in AI."},
                {"id": "kg2", "label": "Bob", "node_type": "person",
                 "summary": "A developer."},
            ],
            [
                {"source_node_id": "kg1", "target_node_id": "kg2",
                 "relation_type": "collaborates"},
            ],
            [],  # _log_activity: query for existing _log
        ]
        client.create_note.return_value = {"id": "ov_1"}
        mock_llm = MagicMock()
        mock_llm.available = False

        cp = Compounder(client, llm=mock_llm)
        result = cp.generate_overview_page(workspace_id="ws1")
        assert result["note"]["id"] == "ov_1"
        content = client.create_note.call_args_list[0][1]["content"]
        assert "Alice" in content
        assert "Bob" in content
        assert "collaborates" in content
        assert "Orphan" not in content  # No orphans (both connected)

    def test_detects_orphan_nodes(self):
        from spacetime_memory.compounder import Compounder
        client = MagicMock()
        client._query.side_effect = [
            [],  # notes
            [
                {"id": "kg1", "label": "OrphanNode", "node_type": "concept",
                 "summary": "Alone."},
            ],
            [],  # no edges → orphan
            [],  # _log_activity: query for existing _log
        ]
        client.create_note.return_value = {"id": "ov_1"}
        mock_llm = MagicMock()
        mock_llm.available = False

        cp = Compounder(client, llm=mock_llm)
        result = cp.generate_overview_page(workspace_id="ws1")
        content = client.create_note.call_args_list[0][1]["content"]
        assert "orphan" in content.lower()

