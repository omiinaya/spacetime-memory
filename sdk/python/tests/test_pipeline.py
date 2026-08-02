"""Unit tests for PipelineMixin — Cognee-parity pipeline system.

All tests use the ``mock_http_client`` fixture — no live SpacetimeDB required.
"""

from __future__ import annotations

import time

import pytest

from spacetime_memory.client._pipeline import (
    PipelineDefinition,
    PipelineResult,
    PipelineStage,
    StageType,
)


class TestPipelineStageConstructors:
    """PipelineStage class-method constructors."""

    def test_search_stage(self):
        stage = PipelineStage.search(query="test query", top_k=20)
        assert stage.type == StageType.SEARCH
        assert stage.params["query"] == "test query"
        assert stage.params["top_k"] == 20

    def test_search_stage_defaults(self):
        stage = PipelineStage.search(query="hello")
        assert stage.params["top_k"] == 10  # default

    def test_filter_stage(self):
        stage = PipelineStage.filter(min_confidence=0.5, max_age_hours=24)
        assert stage.type == StageType.FILTER
        assert stage.params["min_confidence"] == 0.5
        assert stage.params["max_age_hours"] == 24

    def test_filter_stage_with_types(self):
        stage = PipelineStage.filter(
            include_types=["memory", "note"],
            exclude_types=["session"],
        )
        assert stage.params["include_types"] == ["memory", "note"]
        assert stage.params["exclude_types"] == ["session"]

    def test_extract_stage(self):
        stage = PipelineStage.extract(type="entities")
        assert stage.type == StageType.EXTRACT
        assert stage.params["type"] == "entities"

    def test_transform_stage(self):
        stage = PipelineStage.transform(llm_prompt="Summarize: {input}")
        assert stage.type == StageType.TRANSFORM
        assert stage.params["llm_prompt"] == "Summarize: {input}"
        assert stage.params["temperature"] == 0.0

    def test_store_stage(self):
        stage = PipelineStage.store(target="note", title="My Summary", tags=["daily"])
        assert stage.type == StageType.STORE
        assert stage.params["target"] == "note"
        assert stage.params["title"] == "My Summary"
        assert stage.params["tags"] == ["daily"]

    def test_classify_stage(self):
        stage = PipelineStage.classify(categories=["positive", "negative"])
        assert stage.type == StageType.CLASSIFY
        assert stage.params["categories"] == ["positive", "negative"]

    def test_rank_stage(self):
        stage = PipelineStage.rank(field="confidence", reverse=True, top_k=5)
        assert stage.type == StageType.RANK
        assert stage.params["field"] == "confidence"
        assert stage.params["top_k"] == 5

    def test_rank_stage_defaults(self):
        stage = PipelineStage.rank()
        assert stage.params["field"] == "score"
        assert stage.params["reverse"] is True
        assert stage.params["top_k"] is None

    def test_serialize_roundtrip(self):
        original = PipelineStage.search(query="hello", top_k=5)
        d = original.to_dict()
        restored = PipelineStage.from_dict(d)
        assert restored.type == original.type
        assert restored.params == original.params

    def test_filter_defaults(self):
        stage = PipelineStage.filter()
        assert stage.params["min_confidence"] == 0.0
        assert stage.params["max_age_hours"] is None
        assert stage.params["include_types"] is None
        assert stage.params["exclude_types"] is None


class TestPipelineCrud:
    """create_pipeline, list_pipelines, get_pipeline_status, delete_pipeline."""

    def test_create_pipeline(self, mock_http_client):
        pipeline = mock_http_client.create_pipeline(
            workspace_id="ws-1",
            name="test_pipeline",
            stages=[
                PipelineStage.search(query="hello"),
                PipelineStage.store(target="memory"),
            ],
        )
        assert pipeline.id is not None
        assert pipeline.name == "test_pipeline"
        assert pipeline.workspace_id == "ws-1"
        assert len(pipeline.stages) == 2
        assert pipeline.enabled is True

    def test_create_pipeline_with_schedule_and_tags(self, mock_http_client):
        pipeline = mock_http_client.create_pipeline(
            workspace_id="ws-1",
            name="scheduled_pipeline",
            stages=[
                PipelineStage.search(query="daily updates", top_k=20),
                PipelineStage.filter(min_confidence=0.5),
            ],
            schedule="0 9 * * *",
            tags={"env": "prod", "owner": "agent"},
        )
        assert pipeline.schedule == "0 9 * * *"
        assert pipeline.tags == {"env": "prod", "owner": "agent"}

    def test_list_pipelines(self, mock_http_client):
        mock_http_client.create_pipeline("ws-1", "pipe1", [PipelineStage.search(query="a")])
        mock_http_client.create_pipeline("ws-1", "pipe2", [PipelineStage.search(query="b")])
        mock_http_client.create_pipeline("ws-2", "pipe3", [PipelineStage.search(query="c")])

        all_pipes = mock_http_client.list_pipelines()
        assert len(all_pipes) == 3

        ws1_pipes = mock_http_client.list_pipelines(workspace_id="ws-1")
        assert len(ws1_pipes) == 2

        ws2_pipes = mock_http_client.list_pipelines(workspace_id="ws-2")
        assert len(ws2_pipes) == 1

    def test_get_pipeline_status(self, mock_http_client):
        pipeline = mock_http_client.create_pipeline(
            "ws-1", "status_test", [PipelineStage.search(query="test")]
        )
        status = mock_http_client.get_pipeline_status(pipeline.id)
        assert status["id"] == pipeline.id
        assert status["name"] == "status_test"
        assert status["workspace_id"] == "ws-1"
        assert status["enabled"] is True
        assert status["last_status"] == "never_run"
        assert status["recent_executions"] == []

    def test_get_pipeline_status_not_found(self, mock_http_client):
        with pytest.raises(KeyError, match="not found"):
            mock_http_client.get_pipeline_status("nonexistent-id")

    def test_delete_pipeline(self, mock_http_client):
        pipeline = mock_http_client.create_pipeline(
            "ws-1", "delete_me", [PipelineStage.search(query="x")]
        )
        assert len(mock_http_client.list_pipelines()) == 1

        result = mock_http_client.delete_pipeline(pipeline.id)
        assert result["status"] == "ok"

        assert len(mock_http_client.list_pipelines()) == 0

    def test_delete_pipeline_not_found(self, mock_http_client):
        with pytest.raises(KeyError, match="not found"):
            mock_http_client.delete_pipeline("nonexistent")


class TestPipelineExecution:
    """execute_pipeline — runs stages and returns results."""

    def test_execute_empty_pipeline(self, mock_http_client):
        pipeline = mock_http_client.create_pipeline(
            "ws-1", "empty", stages=[]
        )
        result = mock_http_client.execute_pipeline(pipeline.id)
        assert result.success is True
        assert result.stages_output == []

    def test_execute_search_only_pipeline(self, mock_http_client):
        pipeline = mock_http_client.create_pipeline(
            "ws-1",
            "search_only",
            stages=[PipelineStage.search(query="hello", top_k=5)],
        )
        result = mock_http_client.execute_pipeline(pipeline.id)
        assert result.success is True
        assert len(result.stages_output) == 1
        assert result.stages_output[0]["type"] == "search"
        assert result.duration_ms >= 0  # fast execution may round to 0

    def test_execute_full_pipeline(self, mock_http_client):
        """Search → Filter → Extract → Store (classic Cognee-like pipeline)."""
        pipeline = mock_http_client.create_pipeline(
            "ws-2",
            "cognee_parity",
            stages=[
                PipelineStage.search(query="important memories", top_k=100),
                PipelineStage.filter(min_confidence=0.3, max_age_hours=48),
                PipelineStage.extract(type="entities"),
                PipelineStage.store(target="memory", title="Pipeline Output"),
            ],
        )
        result = mock_http_client.execute_pipeline(pipeline.id)
        assert result.success is True, f"Pipeline failed: {result.error}"
        assert len(result.stages_output) == 4
        for i, stage_out in enumerate(result.stages_output):
            assert "duration_ms" in stage_out
            assert stage_out["duration_ms"] >= 0

    def test_execute_with_rank_stage(self, mock_http_client):
        pipeline = mock_http_client.create_pipeline(
            "ws-1",
            "rank_pipe",
            stages=[
                PipelineStage.filter(),  # start with filter (no-op on empty input)
                PipelineStage.rank(field="score", top_k=5),
            ],
        )
        result = mock_http_client.execute_pipeline(pipeline.id)
        assert result.success is True

    def test_execute_with_classify_stage(self, mock_http_client):
        pipeline = mock_http_client.create_pipeline(
            "ws-1",
            "classify_pipe",
            stages=[
                PipelineStage.filter(),
                PipelineStage.classify(categories=["tech", "science"]),
            ],
        )
        result = mock_http_client.execute_pipeline(pipeline.id)
        assert result.success is True

    def test_execute_pipeline_not_found(self, mock_http_client):
        with pytest.raises(KeyError, match="not found"):
            mock_http_client.execute_pipeline("nonexistent")

    def test_execute_updates_last_status(self, mock_http_client):
        pipeline = mock_http_client.create_pipeline(
            "ws-1",
            "status_check",
            stages=[PipelineStage.search(query="test")],
        )
        assert pipeline.last_status == "never_run"

        result = mock_http_client.execute_pipeline(pipeline.id)
        assert result.success is True
        # Re-fetch to see updated status
        status = mock_http_client.get_pipeline_status(pipeline.id)
        assert status["last_status"] == "success"
        assert status["last_run_at"] > 0

    def test_execute_with_overrides(self, mock_http_client):
        """Overrides should be merged into stage params."""
        pipeline = mock_http_client.create_pipeline(
            "ws-1",
            "overrides",
            stages=[PipelineStage.search(query="original", top_k=10)],
        )
        result = mock_http_client.execute_pipeline(pipeline.id, query="overridden")
        assert result.success is True
        # The param in the output should reflect the override
        assert result.stages_output[0]["params"]["query"] == "overridden"

    def test_recent_executions_in_status(self, mock_http_client):
        pipeline = mock_http_client.create_pipeline(
            "ws-1",
            "log_test",
            stages=[PipelineStage.search(query="test")],
        )
        mock_http_client.execute_pipeline(pipeline.id)
        mock_http_client.execute_pipeline(pipeline.id)

        status = mock_http_client.get_pipeline_status(pipeline.id)
        assert len(status["recent_executions"]) == 2
        assert status["recent_executions"][0]["success"] is True

    def test_definition_to_dict_roundtrip(self, mock_http_client):
        pipeline = mock_http_client.create_pipeline(
            "ws-1",
            "roundtrip",
            stages=[
                PipelineStage.search(query="test", top_k=5),
                PipelineStage.filter(min_confidence=0.8),
            ],
            tags={"key": "val"},
        )
        d = pipeline.to_dict()
        assert d["name"] == "roundtrip"
        assert d["workspace_id"] == "ws-1"
        assert len(d["stages"]) == 2

        restored = PipelineDefinition.from_dict(d)
        assert restored.name == "roundtrip"
        assert restored.workspace_id == "ws-1"
        assert len(restored.stages) == 2
        assert restored.stages[0].type == StageType.SEARCH

    def test_result_to_dict(self):
        result = PipelineResult(
            pipeline_id="pipe-1",
            execution_id="exec-1",
            success=True,
            started_at=100.0,
            finished_at=101.5,
            stages_output=[{"stage": 0, "type": "search", "output": []}],
            duration_ms=1500.0,
        )
        d = result.to_dict()
        assert d["pipeline_id"] == "pipe-1"
        assert d["success"] is True
        assert d["duration_ms"] == 1500.0


class TestStageExecution:
    """Test individual stage execution logic."""

    def test_filter_confidence_threshold(self, mock_http_client):
        items = [
            {"content": "low confidence", "confidence": 0.2},
            {"content": "high confidence", "confidence": 0.9},
            {"content": "medium confidence", "confidence": 0.5},
        ]
        # Access the stage executor directly
        result = mock_http_client._execute_filter(
            {"min_confidence": 0.6}, items
        )
        assert len(result) == 1
        assert result[0]["content"] == "high confidence"

    def test_filter_age_hours(self, mock_http_client):
        now = time.time()
        items = [
            {"content": "old", "created_at": now - 86400 * 2},  # 2 days ago
            {"content": "new", "created_at": now - 3600},  # 1 hour ago
        ]
        result = mock_http_client._execute_filter(
            {"max_age_hours": 24}, items
        )
        assert len(result) == 1
        assert result[0]["content"] == "new"

    def test_filter_include_exclude_types(self, mock_http_client):
        items = [
            {"content": "note content", "type": "note"},
            {"content": "memory content", "type": "memory"},
            {"content": "session content", "type": "session"},
        ]
        result = mock_http_client._execute_filter(
            {"include_types": ["note", "memory"]}, items
        )
        assert len(result) == 2

        result = mock_http_client._execute_filter(
            {"exclude_types": ["session"]}, items
        )
        assert len(result) == 2

    def test_extract_entities(self, mock_http_client):
        items = [
            {"content": "Alice met Bob in Paris yesterday"},
        ]
        result = mock_http_client._execute_extract(
            {"type": "entities"}, items
        )
        assert len(result) == 1
        entities = result[0].get("extracted_entities", [])
        assert "Alice" in entities or "Bob" in entities or "Paris" in entities

    def test_extract_keywords(self, mock_http_client):
        items = [
            {"content": "The important architecture decision was made yesterday"},
        ]
        result = mock_http_client._execute_extract(
            {"type": "keywords"}, items
        )
        assert len(result) == 1
        keywords = result[0].get("extracted_keywords", [])
        assert "important" in keywords or "architecture" in keywords

    def test_rank_by_score(self, mock_http_client):
        items = [
            {"id": "a", "score": 0.3},
            {"id": "b", "score": 0.9},
            {"id": "c", "score": 0.1},
        ]
        result = mock_http_client._execute_rank(
            {"field": "score", "reverse": True}, items
        )
        assert [r["id"] for r in result] == ["b", "a", "c"]

    def test_rank_with_top_k(self, mock_http_client):
        items = [
            {"id": "a", "score": 0.3},
            {"id": "b", "score": 0.9},
            {"id": "c", "score": 0.1},
        ]
        result = mock_http_client._execute_rank(
            {"field": "score", "top_k": 2}, items
        )
        assert len(result) == 2
        assert result[0]["id"] == "b"

    def test_classify_with_categories(self, mock_http_client):
        items = [
            {"content": "A breakthrough in artificial intelligence and machine learning"},
            {"content": "Science and experimental results in physics"},
            {"content": "Random note about weather conditions"},
        ]
        result = mock_http_client._execute_classify(
            {"categories": ["tech", "science", "general"]}, items
        )
        assert len(result) == 3
        assert result[0]["classification"] == "tech"
        assert result[1]["classification"] == "science"
        # No match for weather content → falls back to first category
        assert result[2]["classification"] == "tech"

    def test_transform_passthrough_no_llm(self, mock_http_client):
        items = [{"content": "test data"}]
        result = mock_http_client._execute_transform(
            {"llm_prompt": "Summarize", "output_key": "transformed"}, items
        )
        # No local_llm configured, so it should pass through
        assert isinstance(result, list)

    def test_store_fallback_no_workspace(self, mock_http_client):
        result = mock_http_client._execute_store(
            {"target": "memory"}, "some data"
        )
        assert result["stored"] is False
        assert result["target"] == "memory"
        assert result["data"] == "some data"


class TestPipelineDefinitionDataclass:
    """PipelineDefinition dataclass methods."""

    def test_from_dict_full(self):
        d = {
            "id": "test-id",
            "name": "test",
            "workspace_id": "ws-1",
            "stages": [
                {"type": "search", "params": {"query": "hello", "top_k": 5}},
                {"type": "filter", "params": {"min_confidence": 0.5}},
            ],
            "schedule": "0 9 * * *",
            "enabled": True,
            "created_at": 100.0,
            "updated_at": 200.0,
            "last_run_at": 150.0,
            "last_status": "success",
            "tags": {"env": "test"},
        }
        p = PipelineDefinition.from_dict(d)
        assert p.id == "test-id"
        assert p.name == "test"
        assert p.workspace_id == "ws-1"
        assert len(p.stages) == 2
        assert p.stages[0].type == StageType.SEARCH
        assert p.stages[0].params["query"] == "hello"
        assert p.tags == {"env": "test"}

    def test_from_dict_defaults(self):
        d = {"id": "min", "name": "min", "stages": []}
        p = PipelineDefinition.from_dict(d)
        assert p.enabled is True
        assert p.schedule == ""
        assert p.last_status == "never_run"
        assert p.tags == {}
