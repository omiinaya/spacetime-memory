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


# ── Graph query tools (get_node, get_neighbors, get_community, query_graph) ──


class TestGetNode:
    """Tests for the get_node MCP tool."""

    def test_get_node_found(self, mock_mcp_client):
        from server.mcp.main import get_node
        mock_mcp_client.get_node.return_value = [
            {"id": "n1", "label": "RLHF", "node_type": "concept"},
        ]
        result = get_node(id="n1")
        assert isinstance(result, list)
        assert result[0]["label"] == "RLHF"
        mock_mcp_client.get_node.assert_called_once_with("n1")

    def test_get_node_not_found(self, mock_mcp_client):
        from server.mcp.main import get_node
        mock_mcp_client.get_node.return_value = []
        result = get_node(id="nonexistent")
        assert result == []


class TestUpdateNode:
    """Tests for the update_node MCP tool."""

    def test_updates_node(self, mock_mcp_client):
        from server.mcp.main import update_node
        mock_mcp_client.update_node.return_value = {
            "status": "ok", "node_id": "n1",
        }
        result = update_node(
            node_id="n1",
            label="RLHF Updated",
            node_type="concept",
            summary="Updated summary",
        )
        assert result["status"] == "ok"
        mock_mcp_client.update_node.assert_called_once_with(
            "n1", "RLHF Updated", "concept", "Updated summary", "{}", "",
        )

    def test_updates_node_with_all_args(self, mock_mcp_client):
        from server.mcp.main import update_node
        mock_mcp_client.update_node.return_value = {"status": "ok"}
        result = update_node(
            node_id="n1",
            label="RLHF",
            node_type="concept",
            summary="Summary",
            metadata_json='{"source": "paper"}',
            source_memory_id="mem1",
        )
        assert result["status"] == "ok"
        mock_mcp_client.update_node.assert_called_once_with(
            "n1", "RLHF", "concept", "Summary",
            '{"source": "paper"}', "mem1",
        )

    def test_default_node_type(self, mock_mcp_client):
        from server.mcp.main import update_node
        mock_mcp_client.update_node.return_value = {"status": "ok"}
        update_node(node_id="n1", label="Test")
        mock_mcp_client.update_node.assert_called_once_with(
            "n1", "Test", "concept", "", "{}", "",
        )


class TestCreateEdge:
    """Tests for the create_edge MCP tool."""

    def test_creates_edge_with_minimal_args(self, mock_mcp_client):
        from server.mcp.main import create_edge
        mock_mcp_client.create_edge.return_value = {"status": "ok", "edge_id": "e1"}
        result = create_edge(
            workspace_id="ws1",
            source_node_id="n1",
            target_node_id="n2",
            relation="informed_by",
        )
        assert result["edge_id"] == "e1"
        mock_mcp_client.create_edge.assert_called_once_with(
            "ws1", "n1", "n2", "informed_by", 1.0, "EXTRACTED", "{}", "",
        )

    def test_creates_edge_with_all_args(self, mock_mcp_client):
        from server.mcp.main import create_edge
        mock_mcp_client.create_edge.return_value = {"status": "ok", "edge_id": "e2"}
        result = create_edge(
            workspace_id="ws1",
            source_node_id="n1",
            target_node_id="n3",
            relation="contradicts",
            weight=0.8,
            confidence="INFERRED",
            metadata_json='{"source": "paper"}',
            source_memory_id="mem1",
        )
        assert result["edge_id"] == "e2"
        mock_mcp_client.create_edge.assert_called_once_with(
            "ws1", "n1", "n3", "contradicts", 0.8, "INFERRED",
            '{"source": "paper"}', "mem1",
        )


class TestGetNeighbors:
    """Tests for the get_neighbors MCP tool."""

    def test_get_neighbors_with_edges(self, mock_mcp_client):
        from server.mcp.main import get_neighbors
        mock_mcp_client.get_neighbors.return_value = [
            {"edge_id": "e1", "source_node_id": "n1", "target_node_id": "n2", "relationship": "related_to"},
            {"edge_id": "e2", "source_node_id": "n1", "target_node_id": "n3", "relationship": "informed_by"},
        ]
        result = get_neighbors(node_id="n1")
        assert len(result) == 2
        assert result[0]["relationship"] == "related_to"
        mock_mcp_client.get_neighbors.assert_called_once_with("n1")

    def test_get_neighbors_empty(self, mock_mcp_client):
        from server.mcp.main import get_neighbors
        mock_mcp_client.get_neighbors.return_value = []
        result = get_neighbors(node_id="lonely")
        assert result == []


class TestGetCommunity:
    """Tests for the get_community MCP tool."""

    def test_get_community_with_nodes(self, mock_mcp_client):
        from server.mcp.main import get_community
        mock_mcp_client.get_community.return_value = {
            "community_id": 1,
            "nodes": [{"id": "n1", "label": "A"}, {"id": "n2", "label": "B"}],
        }
        result = get_community(community_id=1)
        assert result["community_id"] == 1
        assert len(result["nodes"]) == 2
        mock_mcp_client.get_community.assert_called_once_with(1)

    def test_get_community_empty(self, mock_mcp_client):
        from server.mcp.main import get_community
        mock_mcp_client.get_community.return_value = {"community_id": 99, "nodes": []}
        result = get_community(community_id=99)
        assert result["nodes"] == []


class TestQueryGraph:
    """Tests for the query_graph MCP tool."""

    def test_query_graph_with_results(self, mock_mcp_client):
        from server.mcp.main import query_graph
        mock_mcp_client.query_graph.return_value = [
            {"id": "n1", "label": "Python", "node_type": "concept"},
            {"id": "n2", "label": "Rust", "node_type": "concept"},
        ]
        result = query_graph(workspace_id="ws1", query="language")
        assert len(result) == 2
        assert result[0]["label"] == "Python"
        mock_mcp_client.query_graph.assert_called_once_with("ws1", "language")

    def test_query_graph_empty(self, mock_mcp_client):
        from server.mcp.main import query_graph
        mock_mcp_client.query_graph.return_value = []
        result = query_graph(workspace_id="ws1", query="nonexistent")
        assert result == []

    def test_query_graph_default_query(self, mock_mcp_client):
        from server.mcp.main import query_graph
        mock_mcp_client.query_graph.return_value = []
        result = query_graph(workspace_id="ws1")
        assert result == []
        mock_mcp_client.query_graph.assert_called_once_with("ws1", "")


# ── Graph computation tools (shortest_path, graph_bfs, pagerank, community_hierarchy) ──


class TestShortestPath:
    """Tests for the shortest_path MCP tool."""

    def test_shortest_path_calls_client(self, mock_mcp_client):
        from server.mcp.main import shortest_path
        result = shortest_path(
            workspace_id="ws1",
            source_id="n1",
            target_id="n5",
            max_hops=6,
        )
        assert "Shortest path computed" in result
        mock_mcp_client.shortest_path.assert_called_once_with("ws1", "n1", "n5", 6)

    def test_shortest_path_custom_hops(self, mock_mcp_client):
        from server.mcp.main import shortest_path
        result = shortest_path(
            workspace_id="ws1",
            source_id="a",
            target_id="b",
            max_hops=3,
        )
        assert "Shortest path computed" in result
        mock_mcp_client.shortest_path.assert_called_once_with("ws1", "a", "b", 3)


class TestGraphBFS:
    """Tests for the graph_bfs MCP tool."""

    def test_bfs_calls_client(self, mock_mcp_client):
        from server.mcp.main import graph_bfs
        result = graph_bfs(workspace_id="ws1", start_node_id="n1", max_depth=3)
        assert "BFS from n1" in result
        assert "depth 3" in result
        mock_mcp_client.graph_bfs.assert_called_once_with("ws1", "n1", 3)

    def test_bfs_custom_depth(self, mock_mcp_client):
        from server.mcp.main import graph_bfs
        result = graph_bfs(workspace_id="ws1", start_node_id="root", max_depth=5)
        assert "BFS from root" in result
        mock_mcp_client.graph_bfs.assert_called_once_with("ws1", "root", 5)


class TestComputePagerank:
    """Tests for the compute_pagerank MCP tool."""

    def test_pagerank_with_results(self, mock_mcp_client):
        from server.mcp.main import compute_pagerank
        mock_mcp_client._sql.return_value = [
            {"node_id": "n1", "rank": 0.95},
            {"node_id": "n2", "rank": 0.80},
        ]
        result = compute_pagerank(workspace_id="ws1", damping=0.85, max_iterations=100)
        import json as _json
        parsed = _json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["rank"] == 0.95
        mock_mcp_client.compute_pagerank.assert_called_once_with("ws1", 0.85, 100)

    def test_pagerank_empty(self, mock_mcp_client):
        from server.mcp.main import compute_pagerank
        mock_mcp_client._sql.return_value = []
        result = compute_pagerank(workspace_id="ws1")
        import json as _json
        parsed = _json.loads(result)
        assert parsed == []

    def test_pagerank_default_params(self, mock_mcp_client):
        from server.mcp.main import compute_pagerank
        mock_mcp_client._sql.return_value = []
        compute_pagerank(workspace_id="ws1")
        mock_mcp_client.compute_pagerank.assert_called_once_with("ws1", 0.85, 100)


class TestComputeCommunityHierarchy:
    """Tests for the compute_community_hierarchy MCP tool."""

    def test_hierarchy_with_results(self, mock_mcp_client):
        from server.mcp.main import compute_community_hierarchy
        mock_mcp_client._sql.side_effect = [
            [  # edges
                {"edge_id": "e1", "depth": 0},
                {"edge_id": "e2", "depth": 1},
            ],
            [  # clusters
                {"cluster_id": "c1", "depth": 0},
            ],
        ]
        result = compute_community_hierarchy(workspace_id="ws1")
        import json as _json
        parsed = _json.loads(result)
        assert "edges" in parsed
        assert "clusters" in parsed
        assert len(parsed["edges"]) == 2
        assert len(parsed["clusters"]) == 1
        mock_mcp_client.compute_community_hierarchy.assert_called_once_with("ws1")

    def test_hierarchy_empty(self, mock_mcp_client):
        from server.mcp.main import compute_community_hierarchy
        mock_mcp_client._sql.return_value = []
        result = compute_community_hierarchy(workspace_id="ws1")
        import json as _json
        parsed = _json.loads(result)
        assert parsed["edges"] == []
        assert parsed["clusters"] == []

    def test_hierarchy_calls_sql_twice(self, mock_mcp_client):
        from server.mcp.main import compute_community_hierarchy
        mock_mcp_client._sql.side_effect = [[], []]
        compute_community_hierarchy(workspace_id="ws1")
        assert mock_mcp_client._sql.call_count == 2


class TestComputeKgStats:
    """Tests for the compute_kg_stats MCP tool."""

    def test_returns_stats(self, mock_mcp_client):
        from server.mcp.main import compute_kg_stats
        mock_mcp_client.compute_kg_stats.return_value = {
            "workspace_id": "ws1",
            "node_count": 42,
            "edge_count": 156,
            "community_count": 5,
            "orphan_nodes": 3,
            "avg_degree": 3.7,
        }
        result = compute_kg_stats(workspace_id="ws1")
        import json as _json
        parsed = _json.loads(result)
        assert parsed["node_count"] == 42
        assert parsed["edge_count"] == 156
        assert parsed["community_count"] == 5
        assert parsed["orphan_nodes"] == 3
        assert parsed["avg_degree"] == 3.7
        mock_mcp_client.compute_kg_stats.assert_called_once_with("ws1")

    def test_no_stats_returns_error(self, mock_mcp_client):
        from server.mcp.main import compute_kg_stats
        mock_mcp_client.compute_kg_stats.return_value = None
        result = compute_kg_stats(workspace_id="empty_ws")
        import json as _json
        parsed = _json.loads(result)
        assert "error" in parsed
        assert parsed["workspace_id"] == "empty_ws"


# ── Recommendation tools (recommend_memories, search_sessions_semantic,
#    get_user_memories, search_profiles) ──────────────────────────────────


class TestRecommendMemories:
    """Tests for the recommend_memories MCP tool."""

    def test_returns_recommendations(self, mock_mcp_client):
        from server.mcp.main import recommend_memories
        mock_mcp_client.recommend_memories.return_value = [
            {"id": "r1", "content": "Urgent memory", "urgency": 0.9,
             "reason": "low-trust"},
            {"id": "r2", "content": "Decaying memory", "urgency": 0.7,
             "reason": "decay"},
        ]
        result = recommend_memories(workspace_id="ws1")
        import json as _json
        parsed = _json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["urgency"] == 0.9
        assert parsed[1]["reason"] == "decay"
        mock_mcp_client.recommend_memories.assert_called_once_with(
            workspace_id="ws1", limit=20, min_urgency=0.3,
        )

    def test_custom_params(self, mock_mcp_client):
        from server.mcp.main import recommend_memories
        mock_mcp_client.recommend_memories.return_value = [
            {"id": "r3", "urgency": 0.6},
        ]
        result = recommend_memories(workspace_id="ws2", limit=5, min_urgency=0.5)
        import json as _json
        parsed = _json.loads(result)
        assert len(parsed) == 1
        mock_mcp_client.recommend_memories.assert_called_once_with(
            workspace_id="ws2", limit=5, min_urgency=0.5,
        )

    def test_no_recommendations(self, mock_mcp_client):
        from server.mcp.main import recommend_memories
        mock_mcp_client.recommend_memories.return_value = []
        result = recommend_memories(workspace_id="empty_ws")
        import json as _json
        parsed = _json.loads(result)
        assert "message" in parsed
        assert parsed["message"] == "No recommendations found"


class TestSearchSessionsSemantic:
    """Tests for the search_sessions_semantic MCP tool."""

    def test_returns_sessions(self, mock_mcp_client):
        from server.mcp.main import search_sessions_semantic
        mock_mcp_client.search_sessions_semantic.return_value = [
            {"session_id": "s1", "content": "AI discussion", "score": 0.95},
            {"session_id": "s2", "content": "ML talk", "score": 0.85},
        ]
        result = search_sessions_semantic(query="machine learning", limit=10)
        import json as _json
        parsed = _json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["score"] == 0.95
        mock_mcp_client.search_sessions_semantic.assert_called_once_with(
            query="machine learning", limit=10,
        )

    def test_custom_limit(self, mock_mcp_client):
        from server.mcp.main import search_sessions_semantic
        mock_mcp_client.search_sessions_semantic.return_value = []
        result = search_sessions_semantic(query="test", limit=5)
        import json as _json
        parsed = _json.loads(result)
        assert parsed["message"] == "No sessions found"
        mock_mcp_client.search_sessions_semantic.assert_called_once_with(
            query="test", limit=5,
        )

    def test_empty_result(self, mock_mcp_client):
        from server.mcp.main import search_sessions_semantic
        mock_mcp_client.search_sessions_semantic.return_value = []
        result = search_sessions_semantic(query="nonexistent")
        import json as _json
        parsed = _json.loads(result)
        assert "No sessions found" in parsed["message"]


class TestGetUserMemories:
    """Tests for the get_user_memories MCP tool."""

    def test_returns_user_memories(self, mock_mcp_client):
        from server.mcp.main import get_user_memories
        mock_mcp_client.get_user_memories.return_value = [
            {"id": "m1", "content": "User memory 1", "user_scope": "alice"},
            {"id": "m2", "content": "User memory 2", "user_scope": "alice"},
        ]
        result = get_user_memories(user_scope="alice", workspace_id="ws1")
        import json as _json
        parsed = _json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["user_scope"] == "alice"
        mock_mcp_client.get_user_memories.assert_called_once_with(
            user_scope="alice", workspace_id="ws1",
        )

    def test_empty_result(self, mock_mcp_client):
        from server.mcp.main import get_user_memories
        mock_mcp_client.get_user_memories.return_value = []
        result = get_user_memories(user_scope="bob", workspace_id="ws1")
        import json as _json
        parsed = _json.loads(result)
        assert "No user memories found" in parsed["message"]


class TestSearchProfiles:
    """Tests for the search_profiles MCP tool."""

    def test_returns_profiles(self, mock_mcp_client):
        from server.mcp.main import search_profiles
        mock_mcp_client.search_profiles.return_value = [
            {"id": "p1", "name": "Alice", "static_facts_json": "researcher"},
            {"id": "p2", "name": "Bob", "static_facts_json": "developer"},
        ]
        result = search_profiles(workspace_id="ws1", query="researcher")
        import json as _json
        parsed = _json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "Alice"
        mock_mcp_client.search_profiles.assert_called_once_with(
            workspace_id="ws1", query="researcher", limit=20,
        )

    def test_custom_limit(self, mock_mcp_client):
        from server.mcp.main import search_profiles
        mock_mcp_client.search_profiles.return_value = []
        result = search_profiles(workspace_id="ws1", query="dev", limit=5)
        import json as _json
        parsed = _json.loads(result)
        assert parsed["message"] == "No profiles found"
        mock_mcp_client.search_profiles.assert_called_once_with(
            workspace_id="ws1", query="dev", limit=5,
        )

    def test_empty_result(self, mock_mcp_client):
        from server.mcp.main import search_profiles
        mock_mcp_client.search_profiles.return_value = []
        result = search_profiles(workspace_id="ws2", query="nobody")
        import json as _json
        parsed = _json.loads(result)
        assert "No profiles found" in parsed["message"]


# ── Profile context tools ───────────────────────────────────────────────


class TestAddDynamicContext:
    """Tests for the add_dynamic_context MCP tool."""

    def test_adds_dynamic_context(self, mock_mcp_client):
        from server.mcp.main import add_dynamic_context
        mock_mcp_client.add_dynamic_context.return_value = {"status": "ok"}
        result = add_dynamic_context(peer_id="peer123", context="Working on task X")
        assert "Dynamic context added" in result
        assert "peer123" in result
        mock_mcp_client.add_dynamic_context.assert_called_once_with(
            "peer123", "Working on task X",
        )

    def test_truncates_long_peer_id(self, mock_mcp_client):
        from server.mcp.main import add_dynamic_context
        mock_mcp_client.add_dynamic_context.return_value = {"status": "ok"}
        long_id = "a" * 64
        result = add_dynamic_context(peer_id=long_id, context="test")
        assert "Dynamic context added" in result
        assert len(result) < 100  # Should truncate the long ID


class TestAddProfileFact:
    """Tests for the add_profile_fact MCP tool."""

    def test_adds_profile_fact(self, mock_mcp_client):
        from server.mcp.main import add_profile_fact
        mock_mcp_client.add_profile_fact.return_value = {"status": "ok"}
        result = add_profile_fact(peer_id="peer456", fact="Expert in ML")
        assert "Profile fact added" in result
        assert "peer456" in result
        mock_mcp_client.add_profile_fact.assert_called_once_with(
            "peer456", "Expert in ML",
        )

    def test_empty_peer_id(self, mock_mcp_client):
        from server.mcp.main import add_profile_fact
        mock_mcp_client.add_profile_fact.return_value = {"status": "ok"}
        result = add_profile_fact(peer_id="", fact="Empty peer test")
        assert "Profile fact added" in result


class TestGetProfileContext:
    """Tests for the get_profile_context MCP tool."""

    def test_returns_context(self, mock_mcp_client):
        from server.mcp.main import get_profile_context
        mock_mcp_client.get_profile_context.return_value = {
            "peer_id": "peer789",
            "context": "Active in workspace ws1",
        }
        result = get_profile_context(peer_id="peer789")
        assert len(result) == 1
        assert result[0]["peer_id"] == "peer789"
        assert "context" in result[0]
        mock_mcp_client.get_profile_context.assert_called_once_with("peer789")

    def test_no_context_returns_empty_list(self, mock_mcp_client):
        from server.mcp.main import get_profile_context
        mock_mcp_client.get_profile_context.return_value = None
        result = get_profile_context(peer_id="nonexistent")
        assert result == []

    def test_empty_peer_id(self, mock_mcp_client):
        from server.mcp.main import get_profile_context
        mock_mcp_client.get_profile_context.return_value = None
        result = get_profile_context(peer_id="")
        assert result == []


# ── Workspace tools ─────────────────────────────────────────────────────


class TestDeleteWorkspace:
    """Tests for the delete_workspace MCP tool."""

    def test_delete_workspace_calls_client(self, mock_mcp_client):
        from server.mcp.main import delete_workspace
        mock_mcp_client.delete_workspace.return_value = {
            "status": "ok", "id": "ws1",
        }
        result = delete_workspace(workspace_id="ws1")
        assert result["status"] == "ok"
        mock_mcp_client.delete_workspace.assert_called_once_with("ws1")


class TestFuzzyGet:
    """Tests for the fuzzy_get MCP tool."""

    def test_finds_best_match(self, mock_mcp_client):
        from server.mcp.main import fuzzy_get
        mock_mcp_client.fuzzy_get.return_value = {
            "id": "abc123", "content": "Hello world", "score": 0.85,
        }
        result = fuzzy_get(workspace_id="ws1", name="hello", field="content",
                           threshold=0.5, limit=50)
        assert "abc123" in result
        assert "Hello world" in result
        mock_mcp_client.fuzzy_get.assert_called_once_with(
            workspace_id="ws1", name="hello", field="content",
            threshold=0.5, limit=50,
        )

    def test_no_match(self, mock_mcp_client):
        from server.mcp.main import fuzzy_get
        mock_mcp_client.fuzzy_get.return_value = None
        result = fuzzy_get(workspace_id="ws1", name="xyz")
        assert "No memory found" in result
        assert "0.5" in result

    def test_passes_defaults(self, mock_mcp_client):
        from server.mcp.main import fuzzy_get
        mock_mcp_client.fuzzy_get.return_value = None
        fuzzy_get(workspace_id="ws1", name="test")
        mock_mcp_client.fuzzy_get.assert_called_once_with(
            workspace_id="ws1", name="test", field="content",
            threshold=0.5, limit=50,
        )


class TestDetectPatterns:
    """Tests for the detect_patterns MCP tool."""

    def test_returns_json(self, mock_mcp_client):
        from server.mcp.main import detect_patterns
        mock_mcp_client.detect_patterns.return_value = {
            "temporal_clusters": [{"date": "2026-07-06", "count": 5}],
            "frequent_terms": [{"term": "AI", "count": 10}],
            "co_occurrences": [{"pair": ("AI", "ML"), "count": 3}],
            "total_memories": 100,
            "summary": "Found patterns.",
        }
        result = detect_patterns(workspace_id="ws1")
        assert "temporal_clusters" in result
        assert "AI" in result
        mock_mcp_client.detect_patterns.assert_called_once_with(
            workspace_id="ws1", limit=200,
            include_clusters=True, include_terms=True, include_co_occur=True,
        )

    def test_disables_flags(self, mock_mcp_client):
        from server.mcp.main import detect_patterns
        mock_mcp_client.detect_patterns.return_value = {}
        detect_patterns(workspace_id="ws1", limit=50,
                        include_clusters=False, include_terms=True,
                        include_co_occur=False)
        mock_mcp_client.detect_patterns.assert_called_once_with(
            workspace_id="ws1", limit=50,
            include_clusters=False, include_terms=True, include_co_occur=False,
        )


class TestGetNoteByDate:
    """Tests for the get_note_by_date MCP tool."""

    def test_returns_notes_for_date(self, mock_mcp_client):
        from server.mcp.main import get_note_by_date
        mock_mcp_client.get_note_by_date.return_value = [
            {"id": "n1", "title": "Test", "note_date": "2026-07-06",
             "content": "Content"},
        ]
        result = get_note_by_date(note_date="2026-07-06")
        assert len(result) == 1
        assert result[0]["title"] == "Test"
        mock_mcp_client.get_note_by_date.assert_called_once_with("2026-07-06")

    def test_empty_date(self, mock_mcp_client):
        from server.mcp.main import get_note_by_date
        mock_mcp_client.get_note_by_date.return_value = []
        result = get_note_by_date(note_date="2099-01-01")
        assert result == []
        mock_mcp_client.get_note_by_date.assert_called_once_with("2099-01-01")


class TestListMemories:
    """Tests for the list_memories MCP tool."""

    def test_lists_memories(self, mock_mcp_client):
        from server.mcp.main import list_memories
        mock_mcp_client.list_memories.return_value = [
            {"id": "m1", "content": "First", "memory_type": "experience"},
            {"id": "m2", "content": "Second", "memory_type": "experience"},
        ]
        result = list_memories(workspace_id="ws1")
        assert len(result) == 2
        assert result[0]["id"] == "m1"
        mock_mcp_client.list_memories.assert_called_once_with(
            "ws1", "", 50,
        )

    def test_filters_by_memory_type(self, mock_mcp_client):
        from server.mcp.main import list_memories
        mock_mcp_client.list_memories.return_value = [
            {"id": "m3", "content": "Observation", "memory_type": "observation"},
        ]
        result = list_memories(workspace_id="ws1", memory_type="observation", limit=10)
        assert len(result) == 1
        assert result[0]["memory_type"] == "observation"
        mock_mcp_client.list_memories.assert_called_once_with(
            "ws1", "observation", 10,
        )

    def test_empty_workspace(self, mock_mcp_client):
        from server.mcp.main import list_memories
        mock_mcp_client.list_memories.return_value = []
        result = list_memories(workspace_id="empty_ws")
        assert result == []
        mock_mcp_client.list_memories.assert_called_once_with(
            "empty_ws", "", 50,
        )


# ── glob_get ────────────────────────────────────────────────────────────


class TestGlobGet:
    """Tests for the glob_get MCP tool."""

    def test_finds_matching_memories(self, mock_mcp_client):
        from server.mcp.main import glob_get
        mock_mcp_client.glob_get.return_value = [
            {"id": "auth-token-1", "content": "Auth token config"},
            {"id": "auth-token-2", "content": "Another auth token"},
        ]
        result = glob_get(workspace_id="ws1", pattern="auth-*")
        assert "auth-token-1" in result
        assert "auth-token-2" in result
        mock_mcp_client.glob_get.assert_called_once_with(
            workspace_id="ws1", pattern="auth-*", field="id", limit=200,
        )

    def test_no_matches_returns_message(self, mock_mcp_client):
        from server.mcp.main import glob_get
        mock_mcp_client.glob_get.return_value = []
        result = glob_get(workspace_id="ws1", pattern="nope-*")
        assert "No memories matching pattern" in result
        assert "nope-*" in result

    def test_custom_field_and_limit(self, mock_mcp_client):
        from server.mcp.main import glob_get
        mock_mcp_client.glob_get.return_value = [
            {"id": "m1", "content": "agent memory"},
        ]
        result = glob_get(workspace_id="ws1", pattern="*agent*", field="content", limit=50)
        assert "agent memory" in result
        mock_mcp_client.glob_get.assert_called_once_with(
            workspace_id="ws1", pattern="*agent*", field="content", limit=50,
        )

    def test_empty_pattern(self, mock_mcp_client):
        from server.mcp.main import glob_get
        mock_mcp_client.glob_get.return_value = []
        result = glob_get(workspace_id="ws1", pattern="")
        assert "No memories matching pattern" in result
        mock_mcp_client.glob_get.assert_called_once_with(
            workspace_id="ws1", pattern="", field="id", limit=200,
        )


# ── search_with_filters ─────────────────────────────────────────────────


class TestSearchWithFilters:
    """Tests for the search_with_filters MCP tool."""

    def test_filters_by_metadata(self, mock_mcp_client):
        from server.mcp.main import search_with_filters
        mock_mcp_client.search_with_filters.return_value = [
            {"id": "m1", "content": "Confidential doc", "metadata": {"source": "wiki"}},
            {"id": "m2", "content": "Another doc", "metadata": {"source": "wiki"}},
        ]
        result = search_with_filters(
            workspace_id="ws1",
            metadata_filter='{"source": "wiki"}',
        )
        assert len(result) == 2
        assert result[0]["metadata"]["source"] == "wiki"
        mock_mcp_client.search_with_filters.assert_called_once_with(
            workspace_id="ws1", query="", memory_type="", tier="",
            metadata_filter='{"source": "wiki"}', location_filter="", limit=20,
        )

    def test_filters_by_location(self, mock_mcp_client):
        from server.mcp.main import search_with_filters
        mock_mcp_client.search_with_filters.return_value = [
            {"id": "m1", "content": "Nearby place", "location": {"lat": 37.77}},
        ]
        result = search_with_filters(
            workspace_id="ws1",
            location_filter='{"lat": 37.77, "lng": -122.42}',
        )
        assert len(result) == 1
        assert result[0]["id"] == "m1"
        mock_mcp_client.search_with_filters.assert_called_once_with(
            workspace_id="ws1", query="", memory_type="", tier="",
            metadata_filter="", location_filter='{"lat": 37.77, "lng": -122.42}',
            limit=20,
        )

    def test_all_params_passed(self, mock_mcp_client):
        from server.mcp.main import search_with_filters
        mock_mcp_client.search_with_filters.return_value = []
        search_with_filters(
            workspace_id="ws2",
            query="test query",
            memory_type="note",
            tier="L0",
            metadata_filter='{"priority": "high"}',
            location_filter='{"city": "NYC"}',
            limit=5,
        )
        mock_mcp_client.search_with_filters.assert_called_once_with(
            workspace_id="ws2", query="test query", memory_type="note",
            tier="L0", metadata_filter='{"priority": "high"}',
            location_filter='{"city": "NYC"}', limit=5,
        )

    def test_empty_result_returns_empty_list(self, mock_mcp_client):
        from server.mcp.main import search_with_filters
        mock_mcp_client.search_with_filters.return_value = []
        result = search_with_filters(workspace_id="ws1")
        assert result == []


# ── Citation tools (add_node_citation, add_edge_citation, get_citations) ──


class TestAddNodeCitation:
    """Tests for the add_node_citation MCP tool."""

    def test_adds_citation(self, mock_mcp_client):
        from server.mcp.main import add_node_citation
        mock_mcp_client.add_node_citation.return_value = {
            "status": "ok", "citation_id": "cit1",
        }
        result = add_node_citation(
            workspace_id="ws1",
            node_id="n1",
            memory_id="mem1",
            description="Supports the entity summary",
        )
        assert result["status"] == "ok"
        assert result["citation_id"] == "cit1"
        mock_mcp_client.add_node_citation.assert_called_once_with(
            "ws1", "n1", "mem1", "Supports the entity summary",
        )

    def test_minimal_args(self, mock_mcp_client):
        from server.mcp.main import add_node_citation
        mock_mcp_client.add_node_citation.return_value = {"status": "ok"}
        result = add_node_citation(
            workspace_id="ws1",
            node_id="n1",
            memory_id="mem1",
        )
        assert result["status"] == "ok"
        mock_mcp_client.add_node_citation.assert_called_once_with(
            "ws1", "n1", "mem1", "",
        )


class TestAddEdgeCitation:
    """Tests for the add_edge_citation MCP tool."""

    def test_adds_edge_citation(self, mock_mcp_client):
        from server.mcp.main import add_edge_citation
        mock_mcp_client.add_edge_citation.return_value = {
            "status": "ok", "citation_id": "cit2",
        }
        result = add_edge_citation(
            workspace_id="ws1",
            edge_id="e1",
            memory_id="mem2",
            description="Supports this edge relationship",
        )
        assert result["status"] == "ok"
        mock_mcp_client.add_edge_citation.assert_called_once_with(
            "ws1", "e1", "mem2", "Supports this edge relationship",
        )

    def test_edge_citation_minimal(self, mock_mcp_client):
        from server.mcp.main import add_edge_citation
        mock_mcp_client.add_edge_citation.return_value = {"status": "ok"}
        result = add_edge_citation(
            workspace_id="ws1",
            edge_id="e1",
            memory_id="mem2",
        )
        assert result["status"] == "ok"
        mock_mcp_client.add_edge_citation.assert_called_once_with(
            "ws1", "e1", "mem2", "",
        )


class TestGetCitations:
    """Tests for the get_citations MCP tool."""

    def test_gets_citations_for_node(self, mock_mcp_client):
        from server.mcp.main import get_citations
        mock_mcp_client.get_citations.return_value = [
            {
                "entity_id": "n1",
                "entity_type": "node",
                "source_memory_id": "mem1",
                "description": "Supports entity",
                "created_at": 1700000000,
            },
        ]
        result = get_citations(
            workspace_id="ws1",
            entity_id="n1",
            entity_type="node",
        )
        assert len(result) == 1
        assert result[0]["source_memory_id"] == "mem1"
        mock_mcp_client.get_citations.assert_called_once_with(
            "ws1", "n1", "node",
        )

    def test_gets_citations_for_edge(self, mock_mcp_client):
        from server.mcp.main import get_citations
        mock_mcp_client.get_citations.return_value = [
            {
                "entity_id": "e1",
                "entity_type": "edge",
                "source_memory_id": "mem2",
                "description": "Supports edge",
            },
        ]
        result = get_citations(
            workspace_id="ws1",
            entity_id="e1",
            entity_type="edge",
        )
        assert len(result) == 1
        assert result[0]["entity_type"] == "edge"
        mock_mcp_client.get_citations.assert_called_once_with(
            "ws1", "e1", "edge",
        )

    def test_empty_citations(self, mock_mcp_client):
        from server.mcp.main import get_citations
        mock_mcp_client.get_citations.return_value = []
        result = get_citations(
            workspace_id="ws1",
            entity_id="nonexistent",
        )
        assert result == []
        mock_mcp_client.get_citations.assert_called_once_with(
            "ws1", "nonexistent", "node",
        )

    def test_default_entity_type_is_node(self, mock_mcp_client):
        from server.mcp.main import get_citations
        mock_mcp_client.get_citations.return_value = []
        get_citations(workspace_id="ws1", entity_id="n1")
        mock_mcp_client.get_citations.assert_called_once_with(
            "ws1", "n1", "node",
        )


# ── delete_tour ─────────────────────────────────────────────────────


class TestDeleteTour:
    """Tests for the delete_tour MCP tool."""

    def test_deletes_tour(self, mock_mcp_client):
        from server.mcp.main import delete_tour
        result = delete_tour(tour_id="tour123")
        assert "deleted" in result
        assert "tour123" in result
        mock_mcp_client.delete_tour.assert_called_once_with("tour123")

    def test_calls_client_method(self, mock_mcp_client):
        from server.mcp.main import delete_tour
        delete_tour(tour_id="my-tour-id")
        mock_mcp_client.delete_tour.assert_called_once_with("my-tour-id")


# ── resolve_entity ──────────────────────────────────────────────────


class TestResolveEntity:
    """Tests for the resolve_entity MCP tool."""

    def test_resolves_entity(self, mock_mcp_client):
        from server.mcp.main import resolve_entity
        result = resolve_entity(workspace_id="ws1", name="Alice")
        assert "resolved" in result
        assert "Alice" in result
        assert "ws1" in result
        mock_mcp_client.resolve_entity.assert_called_once_with("ws1", "Alice")

    def test_calls_client_method(self, mock_mcp_client):
        from server.mcp.main import resolve_entity
        resolve_entity(workspace_id="ws-abc", name="Bob")
        mock_mcp_client.resolve_entity.assert_called_once_with("ws-abc", "Bob")


# ── get_directory ────────────────────────────────────────────────────────


class TestGetDirectory:
    """Tests for the get_directory MCP tool."""

    def test_gets_by_id(self, mock_mcp_client):
        from server.mcp.main import get_directory
        mock_mcp_client.get_directory.return_value = [
            {"id": "dir1", "name": "Projects", "path": "/projects"},
        ]
        result = get_directory(workspace_id="ws1", path_or_id="dir1")
        assert "dir1" in result
        assert "Projects" in result
        mock_mcp_client.get_directory.assert_called_once_with("ws1", "dir1")

    def test_gets_by_path(self, mock_mcp_client):
        from server.mcp.main import get_directory
        result = get_directory(workspace_id="ws1", path_or_id="/projects/ai")
        mock_mcp_client.get_directory.assert_called_once_with("ws1", "/projects/ai")

    def test_empty_result(self, mock_mcp_client):
        from server.mcp.main import get_directory
        mock_mcp_client.get_directory.return_value = []
        result = get_directory(workspace_id="ws1", path_or_id="nonexistent")
        assert "[]" in result


# ── link_memory_to_directory / unlink_memory_from_directory ────────────


class TestLinkMemoryToDirectory:
    """Tests for the link_memory_to_directory MCP tool."""

    def test_links_memory(self, mock_mcp_client):
        from server.mcp.main import link_memory_to_directory
        result = link_memory_to_directory(
            directory_id="dir-abc", memory_id="mem-xyz", workspace_id="ws1"
        )
        assert "link" in result.lower()
        mock_mcp_client.link_memory_to_directory.assert_called_once_with(
            "dir-abc", "mem-xyz", "ws1"
        )

    def test_calls_client_method(self, mock_mcp_client):
        from server.mcp.main import link_memory_to_directory
        link_memory_to_directory("d1", "m1", "w1")
        mock_mcp_client.link_memory_to_directory.assert_called_once_with(
            "d1", "m1", "w1"
        )


class TestUnlinkMemoryFromDirectory:
    """Tests for the unlink_memory_from_directory MCP tool."""

    def test_unlinks_memory(self, mock_mcp_client):
        from server.mcp.main import unlink_memory_from_directory
        result = unlink_memory_from_directory(
            directory_id="dir-abc", memory_id="mem-xyz"
        )
        assert "unlink" in result.lower()
        mock_mcp_client.unlink_memory_from_directory.assert_called_once_with(
            "dir-abc", "mem-xyz"
        )

    def test_calls_client_method(self, mock_mcp_client):
        from server.mcp.main import unlink_memory_from_directory
        unlink_memory_from_directory("d1", "m1")
        mock_mcp_client.unlink_memory_from_directory.assert_called_once_with(
            "d1", "m1"
        )


# ── backup / restore ──────────────────────────────────────────────────


class TestBackup:
    """Tests for the backup MCP tool."""

    def test_backup_with_default_path(self, mock_mcp_client):
        from server.mcp.main import backup
        mock_mcp_client.backup.return_value = {
            "status": "ok",
            "path": "spacetime-memory-backup-2026-07-27.json",
            "tables": ["memory", "note", "kg_node"],
            "total_rows": 150,
            "table_count": 3,
        }
        result = backup(workspace_id="default")
        assert "Backup written" in result
        assert "150" in result
        mock_mcp_client.backup.assert_called_once_with(output_path=None)

    def test_backup_with_custom_path(self, mock_mcp_client):
        from server.mcp.main import backup
        mock_mcp_client.backup.return_value = {
            "status": "ok",
            "path": "/tmp/my-backup.json",
            "tables": ["memory"],
            "total_rows": 42,
            "table_count": 1,
        }
        result = backup(workspace_id="ws1", output_path="/tmp/my-backup.json")
        assert "/tmp/my-backup.json" in result
        assert "42" in result
        mock_mcp_client.backup.assert_called_once_with(
            output_path="/tmp/my-backup.json"
        )

    def test_backup_empty_result(self, mock_mcp_client):
        from server.mcp.main import backup
        mock_mcp_client.backup.return_value = {
            "status": "ok",
            "path": "backup.json",
            "tables": [],
            "total_rows": 0,
            "table_count": 0,
        }
        result = backup(workspace_id="empty")
        assert "0" in result


class TestRestore:
    """Tests for the restore MCP tool."""

    def test_restore_success(self, mock_mcp_client):
        from server.mcp.main import restore
        mock_mcp_client.restore.return_value = {
            "restored": ["memory", "note"],
            "total_rows": 200,
        }
        result = restore(input_path="/tmp/backup.json")
        assert "200" in result
        assert "2 table(s)" in result
        mock_mcp_client.restore.assert_called_once_with("/tmp/backup.json")

    def test_restore_no_data(self, mock_mcp_client):
        from server.mcp.main import restore
        mock_mcp_client.restore.return_value = {
            "restored": [],
            "total_rows": 0,
        }
        result = restore(input_path="/tmp/empty-backup.json")
        assert "0" in result


# ── create_api_key / deactivate_api_key / list_api_keys ────────────────


class TestCreateApiKey:
    """Tests for the create_api_key MCP tool."""

    def test_creates_key(self, mock_mcp_client):
        from server.mcp.main import create_api_key
        mock_mcp_client.create_api_key.return_value = {
            "status": "ok",
            "api_key": "sk-abc123...",
            "id": "key-001",
        }
        result = create_api_key(
            workspace_id="ws1",
            name="test-key",
            permissions='["read"]',
        )
        assert "test-key" in result
        assert "sk-abc123" in result
        assert "key-001" in result
        assert "Save this secret" in result
        mock_mcp_client.create_api_key.assert_called_once_with(
            workspace_id="ws1",
            name="test-key",
            permissions='["read"]',
        )

    def test_creates_key_with_write_perms(self, mock_mcp_client):
        from server.mcp.main import create_api_key
        mock_mcp_client.create_api_key.return_value = {
            "status": "ok",
            "api_key": "sk-xyz...",
            "id": "key-002",
        }
        result = create_api_key(
            workspace_id="ws1",
            name="admin-key",
            permissions='["read", "write"]',
        )
        assert "admin-key" in result
        mock_mcp_client.create_api_key.assert_called_once_with(
            workspace_id="ws1",
            name="admin-key",
            permissions='["read", "write"]',
        )


class TestDeactivateApiKey:
    """Tests for the deactivate_api_key MCP tool."""

    def test_deactivates_key(self, mock_mcp_client):
        from server.mcp.main import deactivate_api_key
        mock_mcp_client.deactivate_api_key.return_value = {
            "status": "ok",
        }
        result = deactivate_api_key(key_id="key-001")
        assert "key-001" in result
        assert "deactivated" in result
        mock_mcp_client.deactivate_api_key.assert_called_once_with("key-001")

    def test_deactivate_calls_client_method(self, mock_mcp_client):
        from server.mcp.main import deactivate_api_key
        deactivate_api_key(key_id="key-abc")
        mock_mcp_client.deactivate_api_key.assert_called_once_with("key-abc")


class TestListApiKeys:
    """Tests for the list_api_keys MCP tool."""

    def test_lists_keys(self, mock_mcp_client):
        from server.mcp.main import list_api_keys
        mock_mcp_client.list_api_keys.return_value = [
            {
                "api_key_id": "key-001",
                "name": "read-key",
                "permissions": '["read"]',
                "is_active": True,
                "created_at": 1000,
            },
            {
                "api_key_id": "key-002",
                "name": "admin-key",
                "permissions": '["read", "write"]',
                "is_active": False,
                "created_at": 2000,
            },
        ]
        result = list_api_keys(workspace_id="ws1")
        assert "Total: 2" in result
        assert "read-key" in result
        assert "admin-key" in result
        assert "✅" in result
        assert "❌" in result
        mock_mcp_client.list_api_keys.assert_called_once_with("ws1")

    def test_empty_result(self, mock_mcp_client):
        from server.mcp.main import list_api_keys
        mock_mcp_client.list_api_keys.return_value = []
        result = list_api_keys(workspace_id="ws1")
        assert "No API keys found" in result
        mock_mcp_client.list_api_keys.assert_called_once_with("ws1")

    def test_calls_client_method(self, mock_mcp_client):
        from server.mcp.main import list_api_keys
        mock_mcp_client.list_api_keys.return_value = []
        list_api_keys(workspace_id="ws-abc")
        mock_mcp_client.list_api_keys.assert_called_once_with("ws-abc")


# ── set_workspace_context / set_memory_context / get_context_chain ──────


class TestSetWorkspaceContext:
    """Tests for the set_workspace_context MCP tool."""

    def test_sets_context(self, mock_mcp_client):
        from server.mcp.main import set_workspace_context
        mock_mcp_client.set_workspace_context.return_value = {
            "status": "ok",
        }
        result = set_workspace_context(
            workspace_id="ws1", context="Agent session context data"
        )
        assert "ok" in result.get("status", "")
        mock_mcp_client.set_workspace_context.assert_called_once_with(
            "ws1", "Agent session context data"
        )

    def test_calls_client_method(self, mock_mcp_client):
        from server.mcp.main import set_workspace_context
        set_workspace_context(workspace_id="ws-abc", context="test context")
        mock_mcp_client.set_workspace_context.assert_called_once_with(
            "ws-abc", "test context"
        )


class TestSetMemoryContext:
    """Tests for the set_memory_context MCP tool."""

    def test_sets_context(self, mock_mcp_client):
        from server.mcp.main import set_memory_context
        mock_mcp_client.set_memory_context.return_value = {
            "status": "ok",
        }
        result = set_memory_context(
            memory_id="mem-123", context="Memory-specific context"
        )
        assert "ok" in result.get("status", "")
        mock_mcp_client.set_memory_context.assert_called_once_with(
            "mem-123", "Memory-specific context"
        )

    def test_calls_client_method(self, mock_mcp_client):
        from server.mcp.main import set_memory_context
        set_memory_context(memory_id="mem-xyz", context="ctx")
        mock_mcp_client.set_memory_context.assert_called_once_with(
            "mem-xyz", "ctx"
        )


class TestGetContextChain:
    """Tests for the get_context_chain MCP tool."""

    def test_gets_context_chain(self, mock_mcp_client):
        from server.mcp.main import get_context_chain
        mock_mcp_client.get_context_chain.return_value = {
            "workspace_context": "WS context",
            "memory_context": "Memory context",
        }
        result = get_context_chain(memory_id="mem-123")
        assert result["workspace_context"] == "WS context"
        assert result["memory_context"] == "Memory context"
        mock_mcp_client.get_context_chain.assert_called_once_with("mem-123")

    def test_empty_chain(self, mock_mcp_client):
        from server.mcp.main import get_context_chain
        mock_mcp_client.get_context_chain.return_value = {
            "workspace_context": "",
            "memory_context": "",
        }
        result = get_context_chain(memory_id="mem-nonexistent")
        assert result["workspace_context"] == ""
        assert result["memory_context"] == ""

    def test_calls_client_method(self, mock_mcp_client):
        from server.mcp.main import get_context_chain
        get_context_chain(memory_id="mem-xyz")
        mock_mcp_client.get_context_chain.assert_called_once_with("mem-xyz")


# ── set_decay_model / get_decay_config (decay model tools) ──────────────


class TestSetDecayModel:
    """Tests for the set_decay_model MCP tool."""

    def test_sets_linear_default(self, mock_mcp_client):
        from server.mcp.main import set_decay_model
        mock_mcp_client.set_decay_model.return_value = {"status": "ok"}
        result = set_decay_model(
            workspace_id="ws1",
        )
        assert "Decay model configured" in result
        assert "linear" in result
        mock_mcp_client.set_decay_model.assert_called_once_with(
            workspace_id="ws1",
            model="linear",
            decay_rate=0.005,
            max_days=90,
            weibull_shape=0.6,
            weibull_scale=30.0,
        )

    def test_sets_weibull(self, mock_mcp_client):
        from server.mcp.main import set_decay_model
        mock_mcp_client.set_decay_model.return_value = {"status": "ok"}
        result = set_decay_model(
            workspace_id="ws2",
            model="weibull",
            weibull_shape=0.8,
            weibull_scale=45.0,
        )
        assert "weibull" in result
        mock_mcp_client.set_decay_model.assert_called_once_with(
            workspace_id="ws2",
            model="weibull",
            decay_rate=0.005,
            max_days=90,
            weibull_shape=0.8,
            weibull_scale=45.0,
        )

    def test_calls_client_method(self, mock_mcp_client):
        from server.mcp.main import set_decay_model
        mock_mcp_client.set_decay_model.return_value = {"status": "ok"}
        set_decay_model(workspace_id="ws-abc", model="linear", decay_rate=0.01)
        mock_mcp_client.set_decay_model.assert_called_once_with(
            workspace_id="ws-abc",
            model="linear",
            decay_rate=0.01,
            max_days=90,
            weibull_shape=0.6,
            weibull_scale=30.0,
        )


class TestGetDecayConfig:
    """Tests for the get_decay_config MCP tool."""

    def test_returns_config(self, mock_mcp_client):
        from server.mcp.main import get_decay_config
        mock_mcp_client.get_decay_config.return_value = {
            "id": "ws1",
            "model": "linear",
            "decay_rate": 0.005,
            "max_days": 90,
        }
        result = get_decay_config(workspace_id="ws1")
        assert "Decay config" in result
        assert "model" in result
        assert "linear" in result
        assert "decay_rate" in result
        mock_mcp_client.get_decay_config.assert_called_once_with("ws1")

    def test_no_config(self, mock_mcp_client):
        from server.mcp.main import get_decay_config
        mock_mcp_client.get_decay_config.return_value = None
        result = get_decay_config(workspace_id="ws-none")
        assert "No decay configuration" in result
        mock_mcp_client.get_decay_config.assert_called_once_with("ws-none")

    def test_calls_client_method(self, mock_mcp_client):
        from server.mcp.main import get_decay_config
        mock_mcp_client.get_decay_config.return_value = None
        get_decay_config(workspace_id="ws-abc")
        mock_mcp_client.get_decay_config.assert_called_once_with("ws-abc")


# ── batch_update_memories ────────────────────────────────────────────────


class TestBatchUpdateMemories:
    """Tests for the batch_update_memories MCP tool."""

    def test_batch_updates_success(self, mock_mcp_client):
        from server.mcp.main import batch_update_memories
        mock_mcp_client.batch_update_memories.return_value = {
            "status": "ok",
            "updated": 2,
        }
        result = batch_update_memories(
            workspace_id="ws1",
            memory_ids_json='["mem-001", "mem-002"]',
            updates_json='{"summary": "Updated summary", "confidence": 0.95}',
        )
        assert "Batch update complete" in result
        assert "ok" in result
        assert "2/2" in result
        mock_mcp_client.batch_update_memories.assert_called_once_with(
            workspace_id="ws1",
            memory_ids=["mem-001", "mem-002"],
            updates={"summary": "Updated summary", "confidence": 0.95},
        )

    def test_batch_partial_errors(self, mock_mcp_client):
        from server.mcp.main import batch_update_memories
        mock_mcp_client.batch_update_memories.return_value = {
            "status": "partial",
            "updated": 1,
            "errors": ["Memory 'mem-002' not found"],
        }
        result = batch_update_memories(
            workspace_id="ws1",
            memory_ids_json='["mem-001", "mem-002"]',
            updates_json='{"confidence": 0.9}',
        )
        assert "partial" in result
        assert "1/2" in result
        assert "Memory 'mem-002' not found" in result
        mock_mcp_client.batch_update_memories.assert_called_once_with(
            workspace_id="ws1",
            memory_ids=["mem-001", "mem-002"],
            updates={"confidence": 0.9},
        )

    def test_invalid_memory_ids_json(self, mock_mcp_client):
        from server.mcp.main import batch_update_memories
        result = batch_update_memories(
            workspace_id="ws1",
            memory_ids_json="not-json",
            updates_json='{"summary": "test"}',
        )
        assert "Error" in result
        assert "valid JSON array" in result

    def test_invalid_updates_json(self, mock_mcp_client):
        from server.mcp.main import batch_update_memories
        result = batch_update_memories(
            workspace_id="ws1",
            memory_ids_json='["mem-001"]',
            updates_json="not-json",
        )
        assert "Error" in result
        assert "valid JSON object" in result

    def test_non_array_memory_ids(self, mock_mcp_client):
        from server.mcp.main import batch_update_memories
        result = batch_update_memories(
            workspace_id="ws1",
            memory_ids_json='"not-an-array"',
            updates_json='{"summary": "test"}',
        )
        assert "Error" in result
        assert "JSON array" in result

    def test_non_dict_updates(self, mock_mcp_client):
        from server.mcp.main import batch_update_memories
        result = batch_update_memories(
            workspace_id="ws1",
            memory_ids_json='["mem-001"]',
            updates_json='"not-a-dict"',
        )
        assert "Error" in result
        assert "JSON object" in result

    def test_calls_client_method(self, mock_mcp_client):
        from server.mcp.main import batch_update_memories
        mock_mcp_client.batch_update_memories.return_value = {
            "status": "ok",
            "updated": 1,
        }
        batch_update_memories(
            workspace_id="ws-abc",
            memory_ids_json='["mem-xyz"]',
            updates_json='{"tier": "important"}',
        )
        mock_mcp_client.batch_update_memories.assert_called_once_with(
            workspace_id="ws-abc",
            memory_ids=["mem-xyz"],
            updates={"tier": "important"},
        )


# ── ping ──────────────────────────────────────────────────────────────────


class TestPing:
    """Tests for the ping MCP diagnostic tool."""

    def test_ping_ok(self, mock_mcp_client):
        from server.mcp.main import ping
        mock_mcp_client.ping.return_value = {
            "status": "ok",
            "latency_ms": 3.2,
        }
        result = ping()
        assert "reachable" in result
        assert "3.2" in result
        mock_mcp_client.ping.assert_called_once_with()

    def test_ping_error(self, mock_mcp_client):
        from server.mcp.main import ping
        mock_mcp_client.ping.return_value = {
            "status": "error",
            "message": "Connection refused",
            "latency_ms": 5001.0,
        }
        result = ping()
        assert "unreachable" in result
        assert "Connection refused" in result
        assert "5001" in result
        mock_mcp_client.ping.assert_called_once_with()

    def test_ping_unknown_status(self, mock_mcp_client):
        from server.mcp.main import ping
        mock_mcp_client.ping.return_value = {
            "latency_ms": 0.0,
        }
        result = ping()
        assert "unreachable" in result or "unknown" in result.lower()
        mock_mcp_client.ping.assert_called_once_with()

    def test_ping_calls_client(self, mock_mcp_client):
        from server.mcp.main import ping
        mock_mcp_client.ping.return_value = {
            "status": "ok",
            "latency_ms": 1.0,
        }
        ping()
        mock_mcp_client.ping.assert_called_once_with()


# ── add_alias ─────────────────────────────────────────────────────────────


class TestAddAlias:
    """Tests for the add_alias MCP tool."""

    def test_adds_alias(self, mock_mcp_client):
        from server.mcp.main import add_alias
        mock_mcp_client.add_alias.return_value = None
        result = add_alias(entity_link_id="el-123", alias="Bob")
        assert "Alias" in result
        assert "Bob" in result
        assert "el-123" in result
        mock_mcp_client.add_alias.assert_called_once_with(
            "el-123", "Bob"
        )

    def test_calls_client_method(self, mock_mcp_client):
        from server.mcp.main import add_alias
        mock_mcp_client.add_alias.return_value = None
        add_alias(entity_link_id="el-xyz-987", alias="Alice")
        mock_mcp_client.add_alias.assert_called_once_with(
            "el-xyz-987", "Alice"
        )


# ── list_peers ─────────────────────────────────────────────────────────────


class TestListPeers:
    """Tests for the list_peers MCP tool."""

    def test_lists_all_peers(self, mock_mcp_client):
        from server.mcp.main import list_peers
        mock_mcp_client.list_peers.return_value = [
            {"peer_id": "peer-001", "workspace_id": "ws1"},
            {"peer_id": "peer-002", "workspace_id": "ws1"},
        ]
        result = list_peers()
        assert len(result) == 2
        assert result[0]["peer_id"] == "peer-001"
        assert result[1]["peer_id"] == "peer-002"
        mock_mcp_client.list_peers.assert_called_once_with(None)

    def test_filters_by_workspace(self, mock_mcp_client):
        from server.mcp.main import list_peers
        mock_mcp_client.list_peers.return_value = [
            {"peer_id": "peer-001", "workspace_id": "ws1"},
        ]
        result = list_peers(workspace_id="ws1")
        assert len(result) == 1
        mock_mcp_client.list_peers.assert_called_once_with("ws1")

    def test_empty_result(self, mock_mcp_client):
        from server.mcp.main import list_peers
        mock_mcp_client.list_peers.return_value = []
        result = list_peers(workspace_id="empty-ws")
        assert result == []
        mock_mcp_client.list_peers.assert_called_once_with("empty-ws")

    def test_returns_profile_metadata(self, mock_mcp_client):
        from server.mcp.main import list_peers
        mock_mcp_client.list_peers.return_value = [
            {
                "peer_id": "peer-003",
                "workspace_id": "ws2",
                "profile": {"name": "Alice", "tags": ["researcher"]},
            },
        ]
        result = list_peers()
        assert result[0]["profile"]["name"] == "Alice"
        assert "researcher" in result[0]["profile"]["tags"]


# ── list_profiles ────────────────────────────────────────────────────────────


class TestListProfiles:
    """Tests for the list_profiles MCP tool."""

    def test_lists_profiles_for_workspace(self, mock_mcp_client):
        from server.mcp.main import list_profiles
        mock_mcp_client.list_profiles.return_value = [
            {"peer_id": "p1", "static_facts_json": "[]", "tags_json": "[]"},
            {"peer_id": "p2", "static_facts_json": "[]", "tags_json": "[]"},
        ]
        result = list_profiles(workspace_id="ws-1")
        assert len(result) == 2
        assert result[0]["peer_id"] == "p1"
        assert result[1]["peer_id"] == "p2"
        mock_mcp_client.list_profiles.assert_called_once_with("ws-1")

    def test_empty_result(self, mock_mcp_client):
        from server.mcp.main import list_profiles
        mock_mcp_client.list_profiles.return_value = []
        result = list_profiles(workspace_id="empty-ws")
        assert result == []
        mock_mcp_client.list_profiles.assert_called_once_with("empty-ws")

    def test_returns_profile_details(self, mock_mcp_client):
        from server.mcp.main import list_profiles
        mock_mcp_client.list_profiles.return_value = [
            {
                "peer_id": "p-003",
                "static_facts_json": '[{"key": "expertise", "value": "AI"}]',
                "dynamic_context_json": '{"status": "active"}',
                "tags_json": '["researcher"]',
            },
        ]
        result = list_profiles(workspace_id="ws-2")
        assert "AI" in result[0]["static_facts_json"]
        assert "active" in result[0]["dynamic_context_json"]
        assert mock_mcp_client.list_profiles.call_count == 1


# ── get_peer_reputation ──────────────────────────────────────────────────────


class TestGetPeerReputation:
    """Tests for the get_peer_reputation MCP tool."""

    def test_returns_reputation_for_peer(self, mock_mcp_client):
        from server.mcp.main import get_peer_reputation
        mock_mcp_client.get_peer_reputation.return_value = {
            "id": "peer-001",
            "trust_score": 0.92,
            "feedback_count": 15,
            "positive_feedback": 14,
            "negative_feedback": 1,
        }
        result = get_peer_reputation(peer_id="peer-001")
        assert result["id"] == "peer-001"
        assert result["trust_score"] == 0.92
        assert result["feedback_count"] == 15
        mock_mcp_client.get_peer_reputation.assert_called_once_with("peer-001")

    def test_returns_none_for_unknown_peer(self, mock_mcp_client):
        from server.mcp.main import get_peer_reputation
        mock_mcp_client.get_peer_reputation.return_value = None
        result = get_peer_reputation(peer_id="unknown-peer")
        assert result is None
        mock_mcp_client.get_peer_reputation.assert_called_once_with("unknown-peer")

    def test_includes_all_reputation_fields(self, mock_mcp_client):
        from server.mcp.main import get_peer_reputation
        mock_mcp_client.get_peer_reputation.return_value = {
            "id": "peer-002",
            "trust_score": 0.75,
            "feedback_count": 8,
            "positive_feedback": 6,
            "negative_feedback": 2,
            "last_updated": "2026-06-27T12:00:00Z",
        }
        result = get_peer_reputation(peer_id="peer-002")
        assert result["trust_score"] == 0.75
        assert result["feedback_count"] == 8
        assert result["positive_feedback"] == 6
        assert result["negative_feedback"] == 2
        assert result["last_updated"] == "2026-06-27T12:00:00Z"


# ── run_maintenance ──────────────────────────────────────────────────────────


class TestRunMaintenance:
    """Tests for the run_maintenance MCP tool."""

    def test_triggers_maintenance(self, mock_mcp_client):
        from server.mcp.main import run_maintenance
        mock_mcp_client.run_maintenance.return_value = {
            "status": "ok",
            "expired": 5,
            "decayed": 12,
            "deduped": 3,
        }
        result = run_maintenance()
        assert result["status"] == "ok"
        assert result["expired"] == 5
        assert result["decayed"] == 12
        assert result["deduped"] == 3
        mock_mcp_client.run_maintenance.assert_called_once_with()

    def test_returns_clean_state(self, mock_mcp_client):
        from server.mcp.main import run_maintenance
        mock_mcp_client.run_maintenance.return_value = {
            "status": "ok",
            "expired": 0,
            "decayed": 0,
            "deduped": 0,
        }
        result = run_maintenance()
        assert result["expired"] == 0
        assert result["decayed"] == 0
        assert result["deduped"] == 0


# ── check_embedder_health ────────────────────────────────────────────────────


class TestCheckEmbedderHealth:
    """Tests for the check_embedder_health MCP tool."""

    def test_returns_healthy(self, mock_mcp_client):
        from server.mcp.main import check_embedder_health
        mock_mcp_client.check_embedder_health.return_value = {
            "status": "ok",
            "reachable": True,
            "model": "nomic-embed-text-v1.5",
        }
        result = check_embedder_health()
        assert result["status"] == "ok"
        assert result["reachable"] is True
        mock_mcp_client.check_embedder_health.assert_called_once_with()

    def test_returns_unreachable(self, mock_mcp_client):
        from server.mcp.main import check_embedder_health
        mock_mcp_client.check_embedder_health.return_value = {
            "status": "error",
            "reachable": False,
            "message": "Connection refused",
        }
        result = check_embedder_health()
        assert result["status"] == "error"
        assert result["reachable"] is False
        assert "Connection refused" in result["message"]

    def test_returns_embedder_details(self, mock_mcp_client):
        from server.mcp.main import check_embedder_health
        mock_mcp_client.check_embedder_health.return_value = {
            "status": "ok",
            "reachable": True,
            "model": "nomic-embed-text-v1.5",
            "dimension": 768,
            "uptime_seconds": 3600,
        }
        result = check_embedder_health()
        assert result["model"] == "nomic-embed-text-v1.5"
        assert result["dimension"] == 768
        assert result["uptime_seconds"] == 3600

