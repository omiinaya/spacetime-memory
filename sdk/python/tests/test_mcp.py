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
