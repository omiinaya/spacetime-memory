"""Unit tests for MentalModelMixin (_mental_models.py).

Tests the mental model / disposition / directive template operations
using a mocked Client so no real SpacetimeDB is needed.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from spacetime_memory.client._mental_models import (
    DIRECTIVE_TEMPLATES,
    Disposition,
    MentalModel,
    MentalModelMixin,
    _build_mental_model_prompt,
)

# =====================================================================
# Data class tests
# =====================================================================


class TestMentalModelDataclass:
    def test_default_construction(self):
        m = MentalModel()
        assert m.id == ""
        assert m.name == ""
        assert m.rules == []
        assert m.constraints == []
        assert m.heuristics == []
        assert m.status == "active"
        assert m.priority == 3

    def test_from_directive_full(self):
        row = {
            "id": "mm_001",
            "workspace_id": "ws_001",
            "title": "Test Model",
            "description": json.dumps({
                "rules": ["rule 1", "rule 2"],
                "constraints": ["constraint 1"],
                "heuristics": ["heuristic 1"],
                "description": "A test model",
            }),
            "status": "active",
            "priority": 4,
            "tags_json": json.dumps(["tag1", "tag2"]),
            "created_at": 1_000_000,
            "updated_at": 1_000_001,
        }
        m = MentalModel.from_directive(row)
        assert m.id == "mm_001"
        assert m.name == "Test Model"
        assert m.rules == ["rule 1", "rule 2"]
        assert m.constraints == ["constraint 1"]
        assert m.heuristics == ["heuristic 1"]
        assert m.description == "A test model"
        assert m.tags == ["tag1", "tag2"]
        assert m.status == "active"
        assert m.priority == 4
        assert m.created_at == 1_000_000

    def test_from_directive_empty_description(self):
        row = {
            "id": "mm_002",
            "workspace_id": "ws_001",
            "title": "Empty Model",
            "description": "",
            "status": "active",
            "priority": 3,
            "tags_json": "[]",
            "created_at": 0,
            "updated_at": 0,
        }
        m = MentalModel.from_directive(row)
        assert m.name == "Empty Model"
        assert m.rules == []
        assert m.constraints == []
        assert m.heuristics == []
        assert m.tags == []

    def test_from_directive_invalid_json_description(self):
        row = {
            "id": "mm_003",
            "workspace_id": "ws_001",
            "title": "Bad JSON",
            "description": "not valid json",
            "status": "active",
            "priority": 3,
            "tags_json": "[]",
            "created_at": 0,
            "updated_at": 0,
        }
        m = MentalModel.from_directive(row)
        assert m.name == "Bad JSON"
        assert m.rules == []
        assert m.constraints == []
        assert m.heuristics == []

    def test_from_directive_tags_list_directly(self):
        """Handle case where tags_json is already a list (not a JSON string)."""
        row = {
            "id": "mm_004",
            "workspace_id": "ws_001",
            "title": "Tags List",
            "description": "{}",
            "status": "active",
            "priority": 3,
            "tags_json": ["tag_a", "tag_b"],
            "created_at": 0,
            "updated_at": 0,
        }
        m = MentalModel.from_directive(row)
        assert m.tags == ["tag_a", "tag_b"]

    def test_to_directive_args(self):
        m = MentalModel(
            id="mm_005",
            workspace_id="ws_001",
            name="My Model",
            rules=["rule 1"],
            constraints=["constraint 1"],
            heuristics=["heuristic 1"],
            description="My description",
            tags=["urgent"],
            priority=5,
        )
        args = m.to_directive_args()
        assert args["title"] == "My Model"
        assert args["category"] == "mental_model"
        assert args["priority"] == 5
        desc = json.loads(args["description"])
        assert desc["rules"] == ["rule 1"]
        assert desc["constraints"] == ["constraint 1"]
        assert desc["heuristics"] == ["heuristic 1"]
        assert desc["description"] == "My description"

    def test_priority_clamping_to_directive(self):
        m = MentalModel(priority=10)
        args = m.to_directive_args()
        assert args["priority"] == 5  # clamped

        m2 = MentalModel(priority=0)
        args2 = m2.to_directive_args()
        assert args2["priority"] == 1  # clamped


class TestDispositionDataclass:
    def test_default_construction(self):
        d = Disposition()
        assert d.id == ""
        assert d.disposition_type == "neutral"
        assert d.intensity == 3
        assert d.active is True

    def test_from_directive(self):
        row = {
            "id": "disp_001",
            "workspace_id": "ws_001",
            "title": "disposition:skeptical",
            "description": json.dumps({
                "type": "skeptical",
                "intensity": 4,
                "description": "Be skeptical",
            }),
            "status": "active",
            "category": "disposition",
            "created_at": 1_000_000,
        }
        d = Disposition.from_directive(row)
        assert d.disposition_type == "skeptical"
        assert d.intensity == 4
        assert d.description == "Be skeptical"
        assert d.active is True

    def test_from_directive_inactive(self):
        row = {
            "id": "disp_002",
            "workspace_id": "ws_001",
            "title": "disposition:optimistic",
            "description": json.dumps({"type": "optimistic", "intensity": 5}),
            "status": "inactive",
            "created_at": 0,
        }
        d = Disposition.from_directive(row)
        assert d.active is False

    def test_to_directive_args(self):
        d = Disposition(
            workspace_id="ws_001",
            disposition_type="creative",
            intensity=5,
            description="Be creative",
        )
        args = d.to_directive_args(title="my-title")
        assert args["title"] == "my-title"
        assert args["category"] == "disposition"
        desc = json.loads(args["description"])
        assert desc["type"] == "creative"
        assert desc["intensity"] == 5

    def test_intensity_clamping(self):
        d = Disposition(intensity=7)
        args = d.to_directive_args()
        desc = json.loads(args["description"])
        assert desc["intensity"] == 5

        d2 = Disposition(intensity=0)
        args2 = d2.to_directive_args()
        desc2 = json.loads(args2["description"])
        assert desc2["intensity"] == 1


# =====================================================================
# Helper function tests
# =====================================================================


class TestBuildMentalModelPrompt:
    def test_basic_prompt(self):
        m = MentalModel(
            name="Analytical Lens",
            description="Apply analytical thinking.",
            rules=["Break problems down", "Use evidence"],
            constraints=["Stay in scope"],
            heuristics=["First principles"],
        )
        prompt = _build_mental_model_prompt(m)
        assert "## Mental Model: Analytical Lens" in prompt
        assert "Apply analytical thinking." in prompt
        assert "Break problems down" in prompt
        assert "Stay in scope" in prompt
        assert "First principles" in prompt

    def test_minimal_prompt(self):
        m = MentalModel(name="Simple")
        prompt = _build_mental_model_prompt(m)
        assert "## Mental Model: Simple" in prompt
        assert "### Rules" not in prompt


# =====================================================================
# Mixin tests (using mock Client)
# =====================================================================


@pytest.fixture
def mock_client():
    """A mocked object with the ClientBase interface (used by mixin methods)."""
    client = MagicMock()
    client._call.return_value = {"status": "ok"}
    client._query.return_value = []
    client._sql.return_value = []
    client._sql_param.return_value = []
    return client


class TestMentalModelMixinCreate:
    def test_create_mental_model_calls_reducer(self, mock_client):
        """create_mental_model should call create_directive reducer."""
        mixin = MentalModelMixin()
        # Wire the mixin to use the mock client's methods
        mixin._call = mock_client._call
        mixin._query = mock_client._query

        result = mixin.create_mental_model(
            workspace_id="ws_001",
            name="Test Model",
            rules=["rule 1"],
            constraints=["constraint 1"],
            heuristics=["heuristic 1"],
            tags=["tag1"],
            description="A test",
            priority=3,
        )

        # Should call create_directive with the right args
        mock_client._call.assert_called_once()
        args, kwargs = mock_client._call.call_args
        assert args[0] == "create_directive"
        assert args[1][0] == "ws_001"        # workspace_id
        assert args[1][1] == "Test Model"     # title
        args_desc = json.loads(args[1][2])
        assert args_desc["rules"] == ["rule 1"]
        assert args_desc["constraints"] == ["constraint 1"]
        assert args_desc["heuristics"] == ["heuristic 1"]
        assert args[1][3] == 3                # priority
        assert args[1][5] == "mental_model"   # category
        assert result["status"] == "ok"

    def test_create_mental_model_from_template(self, mock_client):
        mixin = MentalModelMixin()
        mixin._call = mock_client._call
        mixin._query = mock_client._query

        mixin.create_mental_model_from_template(
            workspace_id="ws_001",
            template_name="analysis",
        )

        mock_client._call.assert_called_once()
        args, _ = mock_client._call.call_args
        assert args[0] == "create_directive"
        # The title should come from the template
        assert args[1][1] == "Analysis Lens"

    def test_create_from_template_unknown(self, mock_client):
        mixin = MentalModelMixin()
        with pytest.raises(ValueError, match="Unknown template"):
            mixin.create_mental_model_from_template(
                workspace_id="ws_001",
                template_name="nonexistent",
            )

    def test_create_mental_model_resolves_id(self, mock_client):
        """After creation, the mixin tries to resolve the directive ID."""
        mixin = MentalModelMixin()
        mixin._call = mock_client._call
        mixin._query = mock_client._query

        # Simulate finding the created directive
        mock_client._query.return_value = [
            {"id": "new_directive_123", "title": "Test Model", "created_at": 2000},
        ]

        result = mixin.create_mental_model(
            workspace_id="ws_001",
            name="Test Model",
        )
        assert result["id"] == "new_directive_123"


class TestMentalModelMixinGet:
    def test_get_mental_model_found(self, mock_client):
        mixin = MentalModelMixin()
        mixin._query = mock_client._query

        mock_client._query.return_value = [{
            "id": "mm_001",
            "workspace_id": "ws_001",
            "title": "My Model",
            "description": json.dumps({"rules": ["r1"], "constraints": [], "heuristics": []}),
            "status": "active",
            "priority": 3,
            "category": "mental_model",
            "tags_json": "[]",
            "created_at": 100,
            "updated_at": 200,
        }]

        model = mixin.get_mental_model("mm_001")
        assert model is not None
        assert model.id == "mm_001"
        assert model.name == "My Model"
        assert model.rules == ["r1"]

    def test_get_mental_model_not_found(self, mock_client):
        mixin = MentalModelMixin()
        mixin._query = mock_client._query
        mock_client._query.return_value = []
        assert mixin.get_mental_model("nonexistent") is None

    def test_get_mental_model_wrong_category(self, mock_client):
        """Directives that are not mental models should return None."""
        mixin = MentalModelMixin()
        mixin._query = mock_client._query
        mock_client._query.return_value = [{
            "id": "dir_001",
            "category": "other",
            "title": "Not a model",
            "description": "{}",
            "created_at": 0,
            "updated_at": 0,
        }]
        assert mixin.get_mental_model("dir_001") is None


class TestMentalModelMixinList:
    def test_list_mental_models(self, mock_client):
        mixin = MentalModelMixin()
        mixin._call = mock_client._call
        mixin._query = mock_client._query
        mixin._sql_param = mock_client._sql_param

        mock_client._query.return_value = [
            {
                "id": "mm_001",
                "workspace_id": "ws_001",
                "title": "Model A",
                "description": json.dumps({"rules": [], "constraints": [], "heuristics": []}),
                "status": "active",
                "priority": 3,
                "category": "mental_model",
                "tags_json": "[]",
                "created_at": 200,
                "updated_at": 200,
            },
            {
                "id": "mm_002",
                "workspace_id": "ws_001",
                "title": "Model B",
                "description": json.dumps({"rules": [], "constraints": [], "heuristics": []}),
                "status": "inactive",
                "priority": 2,
                "category": "mental_model",
                "tags_json": "[]",
                "created_at": 100,
                "updated_at": 100,
            },
        ]

        models = mixin.list_mental_models("ws_001")
        assert len(models) == 2

    def test_list_mental_models_filtered(self, mock_client):
        mixin = MentalModelMixin()
        mixin._call = mock_client._call
        mixin._query = mock_client._query
        mixin._sql_param = mock_client._sql_param

        mock_client._query.return_value = [
            {
                "id": "mm_001",
                "workspace_id": "ws_001",
                "title": "Active Model",
                "description": json.dumps({"rules": [], "constraints": [], "heuristics": []}),
                "status": "active",
                "priority": 3,
                "category": "mental_model",
                "tags_json": "[]",
                "created_at": 100,
                "updated_at": 100,
            },
        ]

        models = mixin.list_mental_models("ws_001", status="active")
        assert len(models) == 1
        assert models[0].status == "active"


class TestMentalModelMixinApply:
    def test_apply_mental_model(self, mock_client):
        mixin = MentalModelMixin()
        mixin._query = mock_client._query
        # Need get_mental_model to work
        mixin.get_mental_model = MentalModelMixin.get_mental_model.__get__(mixin, MentalModelMixin)

        mock_client._query.return_value = [{
            "id": "mm_001",
            "workspace_id": "ws_001",
            "title": "Focus Model",
            "description": json.dumps({
                "rules": ["Focus on one task"],
                "constraints": ["No multitasking"],
                "heuristics": ["Single-task"],
                "description": "Stay focused",
            }),
            "status": "active",
            "priority": 3,
            "category": "mental_model",
            "tags_json": '["focus"]',
            "created_at": 100,
            "updated_at": 100,
        }]

        result = mixin.apply_mental_model(
            workspace_id="ws_001",
            model_id="mm_001",
            context={"user_query": "Help me work"},
        )

        assert "mental_model" in result
        assert result["mental_model"]["name"] == "Focus Model"
        assert result["mental_model"]["rules"] == ["Focus on one task"]
        assert "mental_model_prompt" in result
        assert "Focus on one task" in result["mental_model_prompt"]
        # Original context preserved
        assert result["user_query"] == "Help me work"

    def test_apply_mental_model_not_found(self, mock_client):
        mixin = MentalModelMixin()
        mixin._query = mock_client._query
        mock_client._query.return_value = []

        with pytest.raises(ValueError, match="not found"):
            mixin.apply_mental_model("ws_001", "nonexistent")

    def test_apply_mental_model_empty_context(self, mock_client):
        mixin = MentalModelMixin()
        mixin._query = mock_client._query
        mock_client._query.return_value = [{
            "id": "mm_001",
            "workspace_id": "ws_001",
            "title": "Empty Model",
            "description": json.dumps({"rules": [], "constraints": [], "heuristics": []}),
            "status": "active",
            "priority": 3,
            "category": "mental_model",
            "tags_json": "[]",
            "created_at": 0,
            "updated_at": 0,
        }]

        # Call without context
        result = mixin.apply_mental_model("ws_001", "mm_001")
        assert "mental_model" in result
        assert result["mental_model"]["name"] == "Empty Model"


class TestMentalModelMixinUpdate:
    def test_update_mental_model(self, mock_client):
        mixin = MentalModelMixin()
        mixin._call = mock_client._call
        mixin._query = mock_client._query

        mock_client._query.return_value = [{
            "id": "mm_001",
            "workspace_id": "ws_001",
            "title": "Original",
            "description": json.dumps({"rules": [], "constraints": [], "heuristics": []}),
            "status": "active",
            "priority": 3,
            "category": "mental_model",
            "tags_json": "[]",
            "created_at": 100,
            "updated_at": 100,
        }]

        result = mixin.update_mental_model(
            "mm_001",
            name="Updated Model",
            rules=["new rule"],
        )

        assert result["status"] == "ok"
        mock_client._call.assert_called_once()
        args, _ = mock_client._call.call_args
        assert args[0] == "update_directive_status"
        # Description should contain the new rules
        new_desc = json.loads(args[1][2])
        assert new_desc["rules"] == ["new rule"]

    def test_update_mental_model_not_found(self, mock_client):
        mixin = MentalModelMixin()
        mixin._query = mock_client._query
        mock_client._query.return_value = []
        result = mixin.update_mental_model("nonexistent", name="New")
        assert result["status"] == "error"


class TestDispositionMixin:
    def test_set_disposition(self, mock_client):
        mixin = MentalModelMixin()
        mixin._call = mock_client._call
        mixin._query = mock_client._query
        mixin._sql_param = mock_client._sql_param

        result = mixin.set_disposition(
            workspace_id="ws_001",
            disposition_type="skeptical",
            intensity=4,
            description="Question everything",
        )

        assert result["status"] == "ok"
        # Should call list_directives (via get_disposition check) + create_directive
        assert mock_client._call.call_count == 2
        # The second call should be create_directive
        args, _ = mock_client._call.call_args_list[1]
        assert args[0] == "create_directive"
        assert args[1][0] == "ws_001"
        assert args[1][5] == "disposition"
        desc = json.loads(args[1][2])
        assert desc["type"] == "skeptical"
        assert desc["intensity"] == 4

    def test_set_disposition_invalid_type(self, mock_client):
        mixin = MentalModelMixin()
        with pytest.raises(ValueError, match="Invalid disposition_type"):
            mixin.set_disposition("ws_001", "nonexistent_type")

    def test_get_disposition_found(self, mock_client):
        mixin = MentalModelMixin()
        mixin._call = mock_client._call
        mixin._query = mock_client._query
        mixin._sql_param = mock_client._sql_param

        mock_client._query.return_value = [{
            "id": "disp_001",
            "workspace_id": "ws_001",
            "title": "disposition:optimistic",
            "description": json.dumps({"type": "optimistic", "intensity": 5, "description": ""}),
            "status": "active",
            "category": "disposition",
            "created_at": 100,
        }]

        d = mixin.get_disposition("ws_001")
        assert d is not None
        assert d.disposition_type == "optimistic"
        assert d.intensity == 5
        assert d.active is True

    def test_get_disposition_none(self, mock_client):
        mixin = MentalModelMixin()
        mixin._call = mock_client._call
        mixin._query = mock_client._query
        mixin._sql_param = mock_client._sql_param

        mock_client._query.return_value = []
        mock_client._sql_param.return_value = []

        d = mixin.get_disposition("ws_001")
        assert d is None

    def test_clear_disposition(self, mock_client):
        """clear_disposition should deactivate the active disposition."""
        mixin = MentalModelMixin()
        mixin._call = mock_client._call
        mixin._query = mock_client._query
        mixin._sql_param = mock_client._sql_param

        mock_client._query.return_value = [{
            "id": "disp_001",
            "workspace_id": "ws_001",
            "title": "disposition:neutral",
            "description": json.dumps({"type": "neutral", "intensity": 3}),
            "status": "active",
            "category": "disposition",
            "created_at": 100,
        }]

        result = mixin.clear_disposition("ws_001")
        assert result["status"] == "ok"
        # Should call list_directives (via get_disposition) + update_directive_status
        assert mock_client._call.call_count == 2
        # The second call should be update_directive_status
        args, _ = mock_client._call.call_args_list[1]
        assert args[0] == "update_directive_status"
        assert args[1][1] == "inactive"

    def test_clear_disposition_none(self, mock_client):
        mixin = MentalModelMixin()
        mixin._call = mock_client._call
        mixin._query = mock_client._query
        mixin._sql_param = mock_client._sql_param

        mock_client._query.return_value = []
        mock_client._sql_param.return_value = []

        result = mixin.clear_disposition("ws_001")
        assert result["status"] == "ok"
        assert "note" in result


class TestDirectiveTemplates:
    def test_list_directive_templates(self):
        mixin = MentalModelMixin()
        templates = mixin.list_directive_templates()
        assert "analysis" in templates
        assert "creative" in templates
        assert "critical" in templates
        assert "empathetic" in templates
        assert len(templates) == 4

    def test_analysis_template_structure(self):
        mixin = MentalModelMixin()
        templates = mixin.list_directive_templates()
        analysis = templates["analysis"]
        assert analysis["title"] == "Analysis Lens"
        assert len(analysis["rules"]) >= 2
        assert len(analysis["constraints"]) >= 1
        assert len(analysis["heuristics"]) >= 1

    def test_template_directive_constant_matches(self):
        """Ensure DIRECTIVE_TEMPLATES data is internally consistent."""
        assert "analysis" in DIRECTIVE_TEMPLATES
        tmpl = DIRECTIVE_TEMPLATES["analysis"]
        assert tmpl["title"] == "Analysis Lens"
        desc = json.loads(tmpl["description"])
        assert isinstance(desc["rules"], list)
        assert isinstance(desc["constraints"], list)
        assert isinstance(desc["heuristics"], list)
