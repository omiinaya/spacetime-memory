"""Tests for server/mcp/tools/mental.py - Mental model MCP tools."""
import pytest
from server.mcp.tools.mental import (
    get_mental_model, list_mental_models, delete_mental_model,
    synthesize_mental_models,
)


class TestMentalModule:
    """Test suite for mental.py - verify all expected exports exist."""

    def test_get_mental_model_exists(self):
        assert callable(get_mental_model)

    def test_list_mental_models_exists(self):
        assert callable(list_mental_models)

    def test_delete_mental_model_exists(self):
        assert callable(delete_mental_model)

    def test_synthesize_mental_models_exists(self):
        assert callable(synthesize_mental_models)
