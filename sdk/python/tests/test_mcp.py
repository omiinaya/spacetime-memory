# ── search_entities ────────────────────────────────────────────────────


class TestSearchEntities:
    """Tests for the search_entities MCP tool."""

    def test_finds_entities(self, mock_compounder):
        from server.mcp.main import search_entities
        mock_compounder.search_entities.return_value = [
            {"id": "abc123", "label": "Alice", "node_type": "person",
             "summary": "A researcher."},
            {"id": "def456", "label": "Bob", "node_type": "person",
             "summary": "A developer."},
        ]
        result = search_entities(label="Alice")
        assert "Found 2 entities" in result
        assert "Alice" in result
        assert "Bob" in result
        mock_compounder.search_entities.assert_called_once()

    def test_empty_results(self, mock_compounder):
        from server.mcp.main import search_entities
        mock_compounder.search_entities.return_value = []
        result = search_entities(workspace_id="ws1", node_type="person")
        assert result == "No entities found."
        mock_compounder.search_entities.assert_called_once_with(
            workspace_id="ws1", label=None, node_type="person",
            semantic_query=None, limit=20,
        )

    def test_passes_limit(self, mock_compounder):
        from server.mcp.main import search_entities
        mock_compounder.search_entities.return_value = []
        search_entities(limit=5)
        call_kw = mock_compounder.search_entities.call_args[1]
        assert call_kw["limit"] == 5

    def test_missing_summary_handled(self, mock_compounder):
        """Entities with no summary should not crash."""
        from server.mcp.main import search_entities
        mock_compounder.search_entities.return_value = [
            {"id": "xyz", "label": "X", "node_type": "concept",
             "summary": None},
        ]
        result = search_entities(semantic_query="AI")
        assert "Found 1 entities" in result
        assert "X" in result

    def test_semantic_search_passed_correctly(self, mock_compounder):
        from server.mcp.main import search_entities
        mock_compounder.search_entities.return_value = []
        search_entities(workspace_id="ws1", semantic_query="machine learning")
        mock_compounder.search_entities.assert_called_once_with(
            workspace_id="ws1", label=None, node_type=None,
            semantic_query="machine learning", limit=20,
        )


# ── ingest_source ──────────────────────────────────────────────────────


class TestIngestSource:
    """Tests for the ingest_source MCP tool."""

    def test_ingest_with_entities(self, mock_compounder):
        from server.mcp.main import ingest_source
        mock_compounder.ingest_source.return_value = {
            "note_id": "n1",
            "entities": [{"id": "e1"}, {"id": "e2"}],
            "links": [{"id": "l1"}],
            "contradictions": [],
        }
        result = ingest_source(
            source_text="Some text.",
            source_title="Test Article",
            workspace_id="default",
            source_type="article",
        )
        assert "Ingested 'Test Article'" in result
        assert "Entities: 2" in result
        assert "Links: 1" in result
        assert "Contradictions: 0" in result
        mock_compounder.ingest_source.assert_called_once()

    def test_ingest_no_entities(self, mock_compounder):
        from server.mcp.main import ingest_source
        mock_compounder.ingest_source.return_value = {
            "note_id": "n1",
            "entities": [],
            "links": [],
            "contradictions": [],
        }
        result = ingest_source(
            source_text="Short text.",
            source_title="Minimal",
        )
        assert "Entities: 0" in result
        assert "Links: 0" in result

    def test_ingest_with_contradictions(self, mock_compounder):
        from server.mcp.main import ingest_source
        mock_compounder.ingest_source.return_value = {
            "note_id": "n1",
            "entities": [{"id": "e1"}],
            "links": [{"id": "l1"}, {"id": "l2"}],
            "contradictions": [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}],
        }
        result = ingest_source(
            source_text="Contradictory text.",
            source_title="Contra",
        )
        assert "Contradictions: 3" in result

    def test_ingest_empty_text(self, mock_compounder):
        from server.mcp.main import ingest_source
        mock_compounder.ingest_source.return_value = {
            "note_id": "n1",
            "entities": [],
            "links": [],
            "contradictions": [],
        }
        result = ingest_source(
            source_text="",
            source_title="Empty",
        )
        assert "Ingested 'Empty'" in result

    def test_ingest_passes_correct_params(self, mock_compounder):
        from server.mcp.main import ingest_source
        mock_compounder.ingest_source.return_value = {
            "note_id": "n1", "entities": [], "links": [], "contradictions": [],
        }
        ingest_source(
            source_text="Hello world.",
            source_title="Hello",
            workspace_id="custom_ws",
            source_type="paper",
        )
        mock_compounder.ingest_source.assert_called_once_with(
            source_text="Hello world.",
            source_title="Hello",
            workspace_id="custom_ws",
            source_type="paper",
        )


# ── lint_workspace ─────────────────────────────────────────────────────


class TestLintWorkspace:
    """Tests for the lint_workspace MCP tool."""

    def test_lint_no_issues(self, mock_compounder):
        from server.mcp.main import lint_workspace
        mock_compounder.lint_workspace.return_value = {
            "summary": {
                "orphan_count": 0,
                "missing_crossref_count": 0,
                "contradiction_count": 0,
                "total_issues": 0,
            },
        }
        result = lint_workspace(workspace_id="ws1")
        assert "Lint complete" in result
        assert "0" in result
        mock_compounder.lint_workspace.assert_called_once_with(
            workspace_id="ws1", check_contradictions=False,
        )

    def test_lint_with_issues(self, mock_compounder):
        from server.mcp.main import lint_workspace
        mock_compounder.lint_workspace.return_value = {
            "summary": {
                "orphan_count": 5,
                "missing_crossref_count": 3,
                "contradiction_count": 1,
                "total_issues": 9,
            },
        }
        result = lint_workspace(workspace_id="ws1", check_contradictions=True)
        assert "Orphans: 5" in result
        assert "Missing crossrefs: 3" in result
        assert "Contradictions: 1" in result
        assert "Total issues: 9" in result

    def test_default_workspace(self, mock_compounder):
        from server.mcp.main import lint_workspace
        mock_compounder.lint_workspace.return_value = {
            "summary": {
                "orphan_count": 0, "missing_crossref_count": 0,
                "contradiction_count": 0, "total_issues": 0,
            },
        }
        lint_workspace()
        mock_compounder.lint_workspace.assert_called_once_with(
            workspace_id="default", check_contradictions=False,
        )


# ── store_answer (non-batch) ───────────────────────────────────────────


class TestStoreAnswer:
    """Tests for the store_answer MCP tool."""

    def test_stores_answer(self, mock_compounder):
        from server.mcp.main import store_answer
        mock_compounder.store_answer.return_value = {
            "note": {"id": "note_abc123"},
            "entities": [{"id": "e1"}, {"id": "e2"}],
            "links": [],
        }
        result = store_answer(query="What is X?", answer="X is Y.")
        assert "Answer stored" in result
        assert "note_abc123" in result
        assert "Entities extracted: 2" in result

    def test_no_entities(self, mock_compounder):
        from server.mcp.main import store_answer
        mock_compounder.store_answer.return_value = {
            "note": {"id": "n1"},
            "entities": [],
            "links": [],
        }
        result = store_answer(query="Q", answer="A")
        assert "Entities extracted: 0" in result

    def test_parses_source_memory_ids(self, mock_compounder):
        from server.mcp.main import store_answer
        mock_compounder.store_answer.return_value = {
            "note": {"id": "n1"}, "entities": [], "links": [],
        }
        store_answer(query="Q", answer="A", source_memory_ids="mem1,mem2,mem3")
        call_kw = mock_compounder.store_answer.call_args[1]
        assert call_kw["source_memory_ids"] == ["mem1", "mem2", "mem3"]

    def test_empty_source_memory_ids(self, mock_compounder):
        from server.mcp.main import store_answer
        mock_compounder.store_answer.return_value = {
            "note": {"id": "n1"}, "entities": [], "links": [],
        }
        store_answer(query="Q", answer="A", source_memory_ids="")
        call_kw = mock_compounder.store_answer.call_args[1]
        assert call_kw["source_memory_ids"] is None


# ── store_answers_batch ────────────────────────────────────────────────


class TestStoreAnswersBatch:
    """Tests for the store_answers_batch MCP tool."""

    def test_batch_stores_two_pairs(self, mock_compounder):
        from server.mcp.main import store_answers_batch
        mock_compounder.store_answers.return_value = [
            {"note": {"id": "n1"}, "entities": [{"id": "e1"}, {"id": "e2"}]},
            {"note": {"id": "n2"}, "entities": []},
        ]
        result = store_answers_batch(
            qa_pairs_json='[["What is X?", "X is Y."], ["What is Z?", "Z is W."]]',
        )
        assert "Batch stored 2 answers" in result
        assert "Total entities extracted: 2" in result
        mock_compounder.store_answers.assert_called_once()

    def test_batch_empty_list(self, mock_compounder):
        from server.mcp.main import store_answers_batch
        mock_compounder.store_answers.return_value = []
        result = store_answers_batch(qa_pairs_json="[]")
        assert "Batch stored 0 answers" in result
        assert "Total entities extracted: 0" in result

    def test_batch_single_pair(self, mock_compounder):
        from server.mcp.main import store_answers_batch
        mock_compounder.store_answers.return_value = [
            {"note": {"id": "n1"}, "entities": [{"id": "e1"}]},
        ]
        result = store_answers_batch(
            qa_pairs_json='[["Q1", "A1"]]',
        )
        assert "Batch stored 1 answer" in result
        assert "Total entities extracted: 1" in result

    def test_batch_invalid_json(self, mock_compounder):
        from server.mcp.main import store_answers_batch
        result = store_answers_batch(qa_pairs_json="not valid json")
        assert "Error: invalid JSON" in result
        mock_compounder.store_answers.assert_not_called()

    def test_batch_not_a_list(self, mock_compounder):
        from server.mcp.main import store_answers_batch
        result = store_answers_batch(qa_pairs_json='"just a string"')
        assert "Error: qa_pairs_json must be" in result
        mock_compounder.store_answers.assert_not_called()

    def test_batch_wrong_structure(self, mock_compounder):
        from server.mcp.main import store_answers_batch
        result = store_answers_batch(qa_pairs_json='[1, 2, 3]')
        assert "Error: qa_pairs_json must be" in result
        mock_compounder.store_answers.assert_not_called()

    def test_batch_passes_workspace_id(self, mock_compounder):
        from server.mcp.main import store_answers_batch
        mock_compounder.store_answers.return_value = []
        store_answers_batch(
            qa_pairs_json='[["Q", "A"]]',
            workspace_id="custom_ws",
        )
        call_kw = mock_compounder.store_answers.call_args[1]
        assert call_kw["workspace_id"] == "custom_ws"

    def test_batch_passes_source_memory_ids(self, mock_compounder):
        from server.mcp.main import store_answers_batch
        mock_compounder.store_answers.return_value = []
        store_answers_batch(
            qa_pairs_json='[["Q", "A"]]',
            source_memory_ids="mem1,mem2,mem3",
        )
        call_kw = mock_compounder.store_answers.call_args[1]
        assert call_kw["source_memory_ids"] == ["mem1", "mem2", "mem3"]

    def test_batch_empty_source_memory_ids(self, mock_compounder):
        from server.mcp.main import store_answers_batch
        mock_compounder.store_answers.return_value = []
        store_answers_batch(
            qa_pairs_json='[["Q", "A"]]',
            source_memory_ids="",
        )
        call_kw = mock_compounder.store_answers.call_args[1]
        assert call_kw["source_memory_ids"] is None

    def test_batch_no_entities(self, mock_compounder):
        from server.mcp.main import store_answers_batch
        mock_compounder.store_answers.return_value = [
            {"note": {"id": "n1"}, "entities": []},
        ]
        result = store_answers_batch(qa_pairs_json='[["Q", "A"]]')
        assert "Total entities extracted: 0" in result


# ── create_entity_page ─────────────────────────────────────────────────


class TestCreateEntityPage:
    """Tests for the create_entity_page MCP tool."""

    def test_creates_entity(self, mock_compounder):
        from server.mcp.main import create_entity_page
        mock_compounder.create_entity_page.return_value = {
            "note": {"id": "note_xyz"},
        }
        result = create_entity_page(
            name="RLHF",
            description="Reinforcement Learning from Human Feedback",
            entity_type="concept",
            workspace_id="default",
        )
        assert "Entity page 'RLHF' created" in result
        mock_compounder.create_entity_page.assert_called_once_with(
            name="RLHF",
            description="Reinforcement Learning from Human Feedback",
            entity_type="concept",
            workspace_id="default",
        )

    def test_default_type_is_concept(self, mock_compounder):
        from server.mcp.main import create_entity_page
        mock_compounder.create_entity_page.return_value = {
            "note": {"id": "n1"},
        }
        create_entity_page(name="AI", description="Artificial Intelligence")
        call_kw = mock_compounder.create_entity_page.call_args[1]
        assert call_kw["entity_type"] == "concept"


# ── update_entity_page ─────────────────────────────────────────────────


class TestUpdateEntityPage:
    """Tests for the update_entity_page MCP tool."""

    def test_updates_entity(self, mock_compounder):
        from server.mcp.main import update_entity_page
        mock_compounder.update_entity_page.return_value = {
            "note": {"id": "n1"},
        }
        result = update_entity_page(
            name="RLHF",
            description="Updated description",
            entity_type="concept",
        )
        assert "Entity page 'RLHF' updated" in result

    def test_entity_not_found(self, mock_compounder):
        from server.mcp.main import update_entity_page
        mock_compounder.update_entity_page.return_value = {}
        result = update_entity_page(name="Unknown")
        assert "not found" in result

    def test_partial_update(self, mock_compounder):
        """Only provided fields should be passed."""
        from server.mcp.main import update_entity_page
        mock_compounder.update_entity_page.return_value = {"note": {"id": "n1"}}
        update_entity_page(name="RLHF", description="New desc")
        call_kw = mock_compounder.update_entity_page.call_args[1]
        assert call_kw["name"] == "RLHF"
        assert call_kw["description"] == "New desc"
        assert call_kw.get("entity_type") is None


# ── create_concept_page ────────────────────────────────────────────────


class TestCreateConceptPage:
    """Tests for the create_concept_page MCP tool."""

    def test_creates_concept(self, mock_compounder):
        from server.mcp.main import create_concept_page
        mock_compounder.create_concept_page.return_value = {
            "note": {"id": "note_c1"},
        }
        result = create_concept_page(
            concept="RLHF",
            definition="A fine-tuning method using human preferences.",
        )
        assert "Concept page 'RLHF' created" in result
        mock_compounder.create_concept_page.assert_called_once()

    def test_parses_related_concepts(self, mock_compounder):
        from server.mcp.main import create_concept_page
        mock_compounder.create_concept_page.return_value = {
            "note": {"id": "n1"},
        }
        create_concept_page(
            concept="PPO",
            definition="Proximal Policy Optimization",
            related_concepts="RLHF, GRPO, DPO",
        )
        call_kw = mock_compounder.create_concept_page.call_args[1]
        assert call_kw["related_concepts"] == ["RLHF", "GRPO", "DPO"]

    def test_empty_related_concepts(self, mock_compounder):
        from server.mcp.main import create_concept_page
        mock_compounder.create_concept_page.return_value = {
            "note": {"id": "n1"},
        }
        create_concept_page(concept="X", definition="X is.")
        call_kw = mock_compounder.create_concept_page.call_args[1]
        assert call_kw["related_concepts"] is None


# ── create_comparison_page ─────────────────────────────────────────────


class TestCreateComparisonPage:
    """Tests for the create_comparison_page MCP tool."""

    def test_creates_comparison(self, mock_compounder):
        from server.mcp.main import create_comparison_page
        mock_compounder.create_comparison_page.return_value = {
            "note": {"id": "note_comp1"},
        }
        result = create_comparison_page(
            title="A vs B",
            items="A, B",
        )
        assert "Comparison page 'A vs B' created" in result
        assert "2 items" in result

    def test_parses_items_and_criteria(self, mock_compounder):
        from server.mcp.main import create_comparison_page
        mock_compounder.create_comparison_page.return_value = {
            "note": {"id": "n1"},
        }
        create_comparison_page(
            title="X vs Y vs Z",
            items="X, Y, Z",
            criteria="speed, cost, quality",
        )
        call_kw = mock_compounder.create_comparison_page.call_args[1]
        assert call_kw["items"] == ["X", "Y", "Z"]
        assert call_kw["criteria"] == ["speed", "cost", "quality"]


# ── generate_overview ──────────────────────────────────────────────────


class TestGenerateOverview:
    """Tests for the generate_overview MCP tool."""

    def test_overview_generated(self, mock_compounder):
        from server.mcp.main import generate_overview
        mock_compounder.generate_overview_page.return_value = {
            "note": {"id": "overview_abc123def456"},
        }
        result = generate_overview(workspace_id="ws1")
        assert "Overview generated:" in result
        assert "overview_abc123" in result

    def test_overview_empty_workspace(self, mock_compounder):
        from server.mcp.main import generate_overview
        mock_compounder.generate_overview_page.return_value = {"note": {}}
        result = generate_overview(workspace_id="ws1")
        assert "Workspace is empty" in result
