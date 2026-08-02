"""Cognitive operations mixin — Cognee parity.

A formal "cognitive operations" abstraction — named ops that wrap
pipeline stages. Each operation has a type: observe, filter, extract,
transform, classify, rank, or store.

Operations are registered via the ``cognitive_op`` table and can be
executed individually or as part of a pipeline.
"""

from __future__ import annotations

import json
from typing import Any

from ._base import _tracing_span


class CognitiveOpMixin:
    """Mixin for cognitive operation management — Cognee parity.

    Provides a named cognitive operations abstraction that wraps
    processing pipeline stages.
    """

    # -----------------------------------------------------------------------
    # CRUD operations
    # -----------------------------------------------------------------------

    def register_cognitive_op(
        self,
        workspace_id: str,
        name: str,
        op_type: str,
        description: str = "",
        config_json: str = "{}",
        pipeline_stage_type: str = "",
    ) -> dict[str, Any]:
        """Register a new cognitive operation.

        Args:
            workspace_id: Workspace to register the op in.
            name: Unique operation name (e.g. "entity_extract", "semantic_search").
            op_type: Operation type: "observe", "filter", "extract",
                "transform", "classify", "rank", or "store".
            description: Human-readable description.
            config_json: Operation-specific JSON configuration.
            pipeline_stage_type: Maps to an existing pipeline stage type.

        Returns:
            The reducer result.
        """
        with _tracing_span("register_cognitive_op"):
            return self._call("register_cognitive_op", [
                workspace_id, "", name, op_type, description,
                config_json, pipeline_stage_type,
            ])

    def unregister_cognitive_op(
        self,
        workspace_id: str,
        op_id: str,
    ) -> dict[str, Any]:
        """Unregister (delete) a cognitive operation.

        Args:
            workspace_id: Workspace containing the op.
            op_id: ID of the operation to delete.

        Returns:
            The reducer result.
        """
        with _tracing_span("unregister_cognitive_op"):
            return self._call("unregister_cognitive_op", [workspace_id, op_id])

    def get_cognitive_ops(
        self,
        workspace_id: str,
        op_type_filter: str = "",
    ) -> list[dict[str, Any]]:
        """Get cognitive operations, optionally filtered by type.

        Args:
            workspace_id: Workspace to get ops from.
            op_type_filter: Filter by op_type. Empty or "all" returns all.

        Returns:
            List of cognitive operation dicts.
        """
        with _tracing_span("get_cognitive_ops"):
            self._call("get_cognitive_ops", [workspace_id, op_type_filter])
            rows = self._query(
                "cognitive_op_result",
                workspace_id=workspace_id,
            )
            if rows and len(rows) > 0:
                latest = max(rows, key=lambda r: r.get("created_at", 0))
                data = latest.get("data", "[]")
                if isinstance(data, str):
                    try:
                        return json.loads(data)
                    except (json.JSONDecodeError, TypeError):
                        pass
            return []

    def execute_cognitive_op(
        self,
        workspace_id: str,
        op_id: str,
        input_data: Any = None,
    ) -> dict[str, Any]:
        """Execute a cognitive operation.

        Args:
            workspace_id: Workspace containing the op.
            op_id: ID of the operation to execute.
            input_data: Input data for the operation (will be JSON-serialized).

        Returns:
            The operation result dict.
        """
        with _tracing_span("execute_cognitive_op"):
            input_json = json.dumps(input_data) if input_data is not None else "{}"
            self._call("execute_cognitive_op", [workspace_id, op_id, input_json])
            rows = self._query(
                "cognitive_op_result",
                workspace_id=workspace_id,
            )
            if rows and len(rows) > 0:
                latest = max(rows, key=lambda r: r.get("created_at", 0))
                data = latest.get("data", "{}")
                if isinstance(data, str):
                    try:
                        return json.loads(data)
                    except (json.JSONDecodeError, TypeError):
                        pass
            return {"status": "error", "message": "No result found"}

    def get_cognitive_pipeline(
        self,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """Get the ordered pipeline of registered cognitive ops.

        The pipeline follows the standard order:
        observe → extract → classify → filter → transform → rank → store

        Args:
            workspace_id: Workspace to get pipeline from.

        Returns:
            Ordered list of cognitive operation dicts.
        """
        with _tracing_span("get_cognitive_pipeline"):
            self._call("get_cognitive_pipeline", [workspace_id])
            rows = self._query(
                "cognitive_op_result",
                workspace_id=workspace_id,
            )
            if rows and len(rows) > 0:
                latest = max(rows, key=lambda r: r.get("created_at", 0))
                data = latest.get("data", "[]")
                if isinstance(data, str):
                    try:
                        return json.loads(data)
                    except (json.JSONDecodeError, TypeError):
                        pass
            return []

    # -----------------------------------------------------------------------
    # Typed operation abstractions
    # -----------------------------------------------------------------------

    def observe(
        self,
        workspace_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        """Observe — semantic search observation operation.

        Finds and returns cognitive ops of type "observe", or runs
        a semantic search query.

        Args:
            workspace_id: Workspace to observe in.
            query: Search query.

        Returns:
            List of observation results.
        """
        with _tracing_span("cognitive_op.observe"):
            ops = self.get_cognitive_ops(workspace_id, op_type_filter="observe")
            if ops:
                # Execute the first observe op with the query as input
                result = self.execute_cognitive_op(workspace_id, ops[0]["id"], {"query": query})
                return [result]
            return []

    def extract(
        self,
        workspace_id: str,
        content: str,
    ) -> list[dict[str, Any]]:
        """Extract — entity extraction operation.

        Args:
            workspace_id: Workspace to extract in.
            content: Text content to extract entities from.

        Returns:
            List of extraction results.
        """
        with _tracing_span("cognitive_op.extract"):
            ops = self.get_cognitive_ops(workspace_id, op_type_filter="extract")
            if ops:
                result = self.execute_cognitive_op(workspace_id, ops[0]["id"], {"content": content})
                return [result]
            return []

    def classify(
        self,
        workspace_id: str,
        content: str,
    ) -> list[dict[str, Any]]:
        """Classify — categorization operation.

        Args:
            workspace_id: Workspace to classify in.
            content: Content to categorize.

        Returns:
            List of classification results.
        """
        with _tracing_span("cognitive_op.classify"):
            ops = self.get_cognitive_ops(workspace_id, op_type_filter="classify")
            if ops:
                result = self.execute_cognitive_op(workspace_id, ops[0]["id"], {"content": content})
                return [result]
            return []

    def rank(
        self,
        workspace_id: str,
        results: list[Any],
    ) -> list[dict[str, Any]]:
        """Rank — re-ranking operation.

        Args:
            workspace_id: Workspace to rank in.
            results: List of results to re-rank.

        Returns:
            List of ranked results.
        """
        with _tracing_span("cognitive_op.rank"):
            ops = self.get_cognitive_ops(workspace_id, op_type_filter="rank")
            if ops:
                result = self.execute_cognitive_op(workspace_id, ops[0]["id"], {"results": results})
                return [result]
            return results  # passthrough if no rank op

    def transform(
        self,
        workspace_id: str,
        content: str,
        operation: str = "",
    ) -> list[dict[str, Any]]:
        """Transform — content transformation operation.

        Args:
            workspace_id: Workspace to transform in.
            content: Content to transform.
            operation: Transformation operation name.

        Returns:
            List of transformation results.
        """
        with _tracing_span("cognitive_op.transform"):
            ops = self.get_cognitive_ops(workspace_id, op_type_filter="transform")
            if ops:
                result = self.execute_cognitive_op(workspace_id, ops[0]["id"], {
                    "content": content,
                    "operation": operation,
                })
                return [result]
            return []

    def filter(
        self,
        workspace_id: str,
        results: list[Any],
        criteria: str = "",
    ) -> list[dict[str, Any]]:
        """Filter — result filtering operation.

        Args:
            workspace_id: Workspace to filter in.
            results: Results to filter.
            criteria: Filter criteria as string.

        Returns:
            Filtered results.
        """
        with _tracing_span("cognitive_op.filter"):
            ops = self.get_cognitive_ops(workspace_id, op_type_filter="filter")
            if ops:
                result = self.execute_cognitive_op(workspace_id, ops[0]["id"], {
                    "results": results,
                    "criteria": criteria,
                })
                return [result]
            return results  # passthrough if no filter op

    def store(
        self,
        workspace_id: str,
        results: list[Any],
    ) -> list[dict[str, Any]]:
        """Store — persist results operation.

        Args:
            workspace_id: Workspace to store in.
            results: Results to store.

        Returns:
            List of storage results.
        """
        with _tracing_span("cognitive_op.store"):
            ops = self.get_cognitive_ops(workspace_id, op_type_filter="store")
            if ops:
                result = self.execute_cognitive_op(workspace_id, ops[0]["id"], {"results": results})
                return [result]
            return []

    # -----------------------------------------------------------------------
    # Pipeline execution
    # -----------------------------------------------------------------------

    def run_cognitive_pipeline(
        self,
        workspace_id: str,
        op_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Run multiple cognitive operations in sequence (a pipeline).

        Args:
            workspace_id: Workspace to run the pipeline in.
            op_types: List of op_types to run in order. If None, runs all
                ops in the default pipeline order.

        Returns:
            List of results from each pipeline stage.
        """
        with _tracing_span("run_cognitive_pipeline"):
            if op_types is None:
                pipeline = self.get_cognitive_pipeline(workspace_id)
                op_types = [op["op_type"] for op in pipeline if "op_type" in op]

            results = []
            for op_type in op_types:
                ops = self.get_cognitive_ops(workspace_id, op_type_filter=op_type)
                for op in ops:
                    result = self.execute_cognitive_op(workspace_id, op["id"], {
                        "pipeline_input": results[-1] if results else None,
                    })
                    results.append(result)
            return results
