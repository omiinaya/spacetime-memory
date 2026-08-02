"""Unit tests for the Ontology management module — Graphiti parity.

All tests use a mock Client to avoid requiring a live SpacetimeDB instance.
The in-memory fallback store (_ONTO_STORE) is exercised.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from spacetime_memory.client._ontology import (
    _ONTO_STORE,
    EntityTypeDefinition,
    OntologyMixin,
    RelationTypeDefinition,
    Saga,
    SagaStep,
    SearchRecipe,
)

# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture(autouse=True)
def clear_store():
    """Clear the in-memory ontology store before and after each test."""
    _ONTO_STORE.clear()
    yield
    _ONTO_STORE.clear()


@pytest.fixture
def mock_client():
    """Create a mock Client instance with OntologyMixin mixed in.

    The mock simulates the ClientBase pattern where _call, _query,
    _sql_param, and search methods are available.  By default, all
    reducer calls raise an exception, forcing the in-memory fallback.
    """
    client = MagicMock(spec=OntologyMixin)
    # Attach the mixin methods directly
    for name in dir(OntologyMixin):
        attr = getattr(OntologyMixin, name)
        if callable(attr) and not name.startswith("_"):
            setattr(client, name, attr.__get__(client, OntologyMixin))
    # Internal methods too
    client._resolve_entity_type_definition = OntologyMixin._resolve_entity_type_definition.__get__(client, OntologyMixin)
    client._resolve_relation_type_definition = OntologyMixin._resolve_relation_type_definition.__get__(client, OntologyMixin)
    client._check_type_inheritance = OntologyMixin._check_type_inheritance.__get__(client, OntologyMixin)
    # Make _call raise by default (forces in-memory fallback)
    client._call = MagicMock(side_effect=RuntimeError("No reducer registered"))
    client._query = MagicMock(return_value=[])
    client._sql_param = MagicMock(return_value=[])
    # Add search method
    client.search = MagicMock(return_value=[])
    return client


# =====================================================================
# EntityTypeDefinition dataclass tests
# =====================================================================


class TestEntityTypeDefinition:
    def test_default_fields(self):
        et = EntityTypeDefinition()
        assert et.id == ""
        assert et.name == ""
        assert et.parent_type == ""
        assert et.properties == []
        assert et.namespace == ""

    def test_to_storage_dict(self):
        et = EntityTypeDefinition(
            id="et-1",
            workspace_id="ws-1",
            name="Employee",
            parent_type="Person",
            properties=["department", "title"],
            description="An employee at a company",
            namespace="org",
            created_at=1000,
            updated_at=2000,
        )
        d = et.to_storage_dict()
        assert d["id"] == "et-1"
        assert d["name"] == "Employee"
        assert d["parent_type"] == "Person"
        assert d["entry_type"] == "entity_type"
        assert json.loads(d["properties"]) == ["department", "title"]

    def test_from_storage_dict_with_json_strings(self):
        d = {
            "id": "et-2",
            "workspace_id": "ws-1",
            "name": "Manager",
            "parent_type": "Employee",
            "properties": '["budget", "team_size"]',
            "description": "A manager supervises a team",
            "namespace": "org",
            "created_at": 1000,
            "updated_at": 2000,
        }
        et = EntityTypeDefinition.from_storage_dict(d)
        assert et.name == "Manager"
        assert et.parent_type == "Employee"
        assert et.properties == ["budget", "team_size"]

    def test_from_storage_dict_with_list_properties(self):
        d = {
            "id": "et-3",
            "workspace_id": "ws-1",
            "name": "Person",
            "parent_type": "",
            "properties": ["name", "age"],
            "description": "",
            "namespace": "",
            "created_at": 0,
            "updated_at": 0,
        }
        et = EntityTypeDefinition.from_storage_dict(d)
        assert et.properties == ["name", "age"]

    def test_from_storage_dict_with_malformed_properties(self):
        d = {
            "id": "et-4",
            "workspace_id": "ws-1",
            "name": "BadType",
            "parent_type": "",
            "properties": 42,
            "description": "",
            "namespace": "",
            "created_at": 0,
            "updated_at": 0,
        }
        et = EntityTypeDefinition.from_storage_dict(d)
        assert et.properties == []


# =====================================================================
# RelationTypeDefinition dataclass tests
# =====================================================================


class TestRelationTypeDefinition:
    def test_default_fields(self):
        rt = RelationTypeDefinition()
        assert rt.name == ""
        assert rt.source_types == []
        assert rt.target_types == []

    def test_to_storage_dict(self):
        rt = RelationTypeDefinition(
            id="rt-1",
            workspace_id="ws-1",
            name="reports_to",
            source_types=["Employee"],
            target_types=["Manager"],
            properties=["start_date"],
            description="Employment reporting line",
            namespace="org",
        )
        d = rt.to_storage_dict()
        assert d["entry_type"] == "relation_type"
        assert json.loads(d["source_types"]) == ["Employee"]
        assert json.loads(d["target_types"]) == ["Manager"]

    def test_from_storage_dict(self):
        d = {
            "id": "rt-2",
            "workspace_id": "ws-1",
            "name": "works_at",
            "source_types": '["Person"]',
            "target_types": '["Organization"]',
            "properties": '["since"]',
            "description": "Employment relationship",
            "namespace": "",
            "created_at": 0,
            "updated_at": 0,
        }
        rt = RelationTypeDefinition.from_storage_dict(d)
        assert rt.name == "works_at"
        assert rt.source_types == ["Person"]
        assert rt.target_types == ["Organization"]
        assert rt.properties == ["since"]


# =====================================================================
# SearchRecipe dataclass tests
# =====================================================================


class TestSearchRecipe:
    def test_default_fields(self):
        r = SearchRecipe()
        assert r.name == ""
        assert r.search_params == {}

    def test_to_storage_dict(self):
        r = SearchRecipe(
            id="sr-1",
            workspace_id="ws-1",
            name="recent_concepts",
            search_params={"limit": 10, "filters": {"node_type": "concept"}},
            description="Get recent concept nodes",
        )
        d = r.to_storage_dict()
        assert d["entry_type"] == "search_recipe"
        params = json.loads(d["search_params"])
        assert params["limit"] == 10

    def test_from_storage_dict(self):
        d = {
            "id": "sr-2",
            "workspace_id": "ws-1",
            "name": "kg_search",
            "search_params": '{"query": "", "limit": 20}',
            "description": "",
            "created_at": 0,
            "updated_at": 0,
        }
        r = SearchRecipe.from_storage_dict(d)
        assert r.name == "kg_search"
        assert r.search_params["limit"] == 20


# =====================================================================
# Saga / SagaStep dataclass tests
# =====================================================================


class TestSagaStep:
    def test_default_fields(self):
        s = SagaStep()
        assert s.name == ""
        assert s.status == "pending"
        assert s.result is None


class TestSaga:
    def test_default_fields(self):
        s = Saga()
        assert s.status == "active"
        assert s.steps == []

    def test_with_steps(self):
        step1 = SagaStep(name="create_nodes", action="Create 10 KG nodes", status="completed")
        step2 = SagaStep(name="create_edges", action="Link nodes", status="pending")
        saga = Saga(
            id="sg-1",
            workspace_id="ws-1",
            name="import_batch",
            steps=[step1, step2],
        )
        assert len(saga.steps) == 2
        assert saga.steps[0].name == "create_nodes"

    def test_to_and_from_storage(self):
        step1 = SagaStep(name="step1", action="Do something", result={"ok": True}, status="completed")
        saga = Saga(
            id="sg-1",
            workspace_id="ws-1",
            name="test_saga",
            steps=[step1],
            status="active",
        )
        d = saga.to_storage_dict()
        assert d["entry_type"] == "saga"

        restored = Saga.from_storage_dict(d)
        assert restored.name == "test_saga"
        assert restored.status == "active"
        assert len(restored.steps) == 1
        assert restored.steps[0].result == {"ok": True}

    def test_from_storage_with_list_steps(self):
        d = {
            "id": "sg-2",
            "workspace_id": "ws-1",
            "name": "batch",
            "steps": [
                {"name": "a", "action": "Action A", "result": "null", "status": "completed", "created_at": 100},
            ],
            "status": "completed",
            "created_at": 0,
            "updated_at": 0,
        }
        saga = Saga.from_storage_dict(d)
        assert saga.status == "completed"
        assert saga.steps[0].name == "a"


# =====================================================================
# OntologyMixin — Entity Type CRUD
# =====================================================================


class TestCreateEntityType:
    def test_create_and_get(self, mock_client):
        result = mock_client.create_entity_type("ws-1", "Person",
                                                 description="A person entity")
        assert result["status"] == "ok"
        assert result["id"] != ""

        # Get by ID
        et = mock_client.get_entity_type(result["id"])
        assert et is not None
        assert et["name"] == "Person"

    def test_create_with_parent(self, mock_client):
        mock_client.create_entity_type("ws-1", "Person")
        result = mock_client.create_entity_type("ws-1", "Employee",
                                                 parent_type="Person",
                                                 properties=["department", "title"])
        assert result["status"] == "ok"

    def test_create_with_namespace(self, mock_client):
        result = mock_client.create_entity_type("ws-1", "Product",
                                                 namespace="ecommerce")
        assert result["status"] == "ok"
        et = mock_client.get_entity_type(result["id"])
        assert et["namespace"] == "ecommerce"

    def test_get_nonexistent(self, mock_client):
        assert mock_client.get_entity_type("nonexistent") is None

    def test_delete_entity_type(self, mock_client):
        result = mock_client.create_entity_type("ws-1", "Temporary")
        type_id = result["id"]
        del_result = mock_client.delete_entity_type(type_id)
        assert del_result["status"] == "ok"
        assert mock_client.get_entity_type(type_id) is None

    def test_delete_nonexistent(self, mock_client):
        result = mock_client.delete_entity_type("no-such-type")
        assert result["status"] == "error"


class TestListEntityTypes:
    def test_list_empty(self, mock_client):
        types = mock_client.list_entity_types("ws-1")
        assert types == []

    def test_list_multiple(self, mock_client):
        mock_client.create_entity_type("ws-1", "Person")
        mock_client.create_entity_type("ws-1", "Organization")
        mock_client.create_entity_type("ws-2", "Product")  # other workspace
        types = mock_client.list_entity_types("ws-1")
        assert len(types) == 2
        names = {t["name"] for t in types}
        assert names == {"Person", "Organization"}

    def test_list_by_parent(self, mock_client):
        mock_client.create_entity_type("ws-1", "Person")
        mock_client.create_entity_type("ws-1", "Employee", parent_type="Person")
        mock_client.create_entity_type("ws-1", "Manager", parent_type="Employee")

        children = mock_client.list_entity_types("ws-1", parent_type="Person")
        assert len(children) == 1
        assert children[0]["name"] == "Employee"

        grandchildren = mock_client.list_entity_types("ws-1", parent_type="Employee")
        assert len(grandchildren) == 1
        assert grandchildren[0]["name"] == "Manager"


# =====================================================================
# OntologyMixin — Relation Type CRUD
# =====================================================================


class TestCreateRelationType:
    def test_create_and_get(self, mock_client):
        result = mock_client.create_relation_type(
            "ws-1", "reports_to",
            source_types=["Employee"],
            target_types=["Manager"],
            description="Reporting line",
        )
        assert result["status"] == "ok"
        rt = mock_client.get_relation_type(result["id"])
        assert rt is not None
        assert rt["name"] == "reports_to"
        assert json.loads(rt["source_types"]) == ["Employee"]

    def test_create_with_properties(self, mock_client):
        result = mock_client.create_relation_type(
            "ws-1", "works_at",
            source_types=["Person"],
            target_types=["Organization"],
            properties=["start_date", "role"],
        )
        assert result["status"] == "ok"
        rt = mock_client.get_relation_type(result["id"])
        props = json.loads(rt["properties"])
        assert "start_date" in props

    def test_list_relation_types(self, mock_client):
        mock_client.create_relation_type("ws-1", "reports_to")
        mock_client.create_relation_type("ws-1", "works_at")
        rtypes = mock_client.list_relation_types("ws-1")
        assert len(rtypes) == 2
        names = {r["name"] for r in rtypes}
        assert names == {"reports_to", "works_at"}

    def test_delete_relation_type(self, mock_client):
        result = mock_client.create_relation_type("ws-1", "temp_rel")
        rt_id = result["id"]
        del_result = mock_client.delete_relation_type(rt_id)
        assert del_result["status"] == "ok"
        assert mock_client.get_relation_type(rt_id) is None


# =====================================================================
# Schema validation
# =====================================================================


class TestValidateNode:
    def test_validate_valid_node(self, mock_client):
        mock_client.create_entity_type("ws-1", "Person",
                                        properties=["name", "age"])
        result = mock_client.validate_node(
            {"label": "Alice", "summary": "A person", "name": "Alice", "age": 30},
            "Person",
            workspace_id="ws-1",
        )
        assert result["valid"] is True
        assert result["errors"] == []

    def test_validate_unknown_property(self, mock_client):
        mock_client.create_entity_type("ws-1", "Person",
                                        properties=["name", "age"])
        result = mock_client.validate_node(
            {"label": "Bob", "name": "Bob", "height": 180},
            "Person",
            workspace_id="ws-1",
        )
        assert result["valid"] is True  # unknown props = warnings, not errors
        assert len(result["warnings"]) == 1
        assert "height" in result["warnings"][0]

    def test_validate_nonexistent_type(self, mock_client):
        result = mock_client.validate_node(
            {"label": "X"},
            "NonExistentType",
            workspace_id="ws-1",
        )
        assert result["valid"] is False
        assert len(result["errors"]) == 1

    def test_validate_with_inheritance(self, mock_client):
        mock_client.create_entity_type("ws-1", "Person",
                                        properties=["name"])
        mock_client.create_entity_type("ws-1", "Employee",
                                        parent_type="Person",
                                        properties=["department"])
        # A node with node_type "Employee" should be valid for entity_type "Person"
        result = mock_client.validate_node(
            {"label": "Carol", "name": "Carol", "department": "Eng",
             "node_type": "Employee"},
            "Person",
            workspace_id="ws-1",
        )
        assert result["valid"] is True


class TestValidateEdge:
    def test_validate_valid_edge(self, mock_client):
        mock_client.create_relation_type("ws-1", "reports_to",
                                          source_types=["Employee"],
                                          target_types=["Manager"])
        result = mock_client.validate_edge(
            {"relation": "reports_to", "weight": 1.0},
            "reports_to",
            workspace_id="ws-1",
        )
        assert result["valid"] is True

    def test_validate_nonexistent_relation(self, mock_client):
        result = mock_client.validate_edge(
            {"relation": "unknown_rel"},
            "unknown_rel",
            workspace_id="ws-1",
        )
        assert result["valid"] is False
        assert len(result["errors"]) == 1

    def test_validate_unknown_property(self, mock_client):
        mock_client.create_relation_type("ws-1", "reports_to")
        result = mock_client.validate_edge(
            {"relation": "reports_to", "custom_field": "value"},
            "reports_to",
            workspace_id="ws-1",
        )
        assert result["valid"] is True
        assert len(result["warnings"]) == 1
        assert "custom_field" in result["warnings"][0]

    def test_validate_source_type_constraint(self, mock_client):
        mock_client.create_relation_type("ws-1", "reports_to",
                                          source_types=["Employee"],
                                          target_types=["Manager"])
        result = mock_client.validate_edge(
            {"relation": "reports_to",
             "source_types": ["Contractor"],  # not in allowed source types
             "target_types": ["Manager"]},
            "reports_to",
            workspace_id="ws-1",
        )
        # Contractor is not Employee, so it should error
        assert result["valid"] is False
        assert len(result["errors"]) >= 1


# =====================================================================
# Search recipes
# =====================================================================


class TestSearchRecipeMixin:
    def test_create_and_get(self, mock_client):
        result = mock_client.create_search_recipe(
            "ws-1",
            "recent_concepts",
            {"limit": 10, "filters": {"node_type": "concept"}},
            "Get recent concept nodes",
        )
        assert result["status"] == "ok"
        recipe = mock_client.get_search_recipe(result["id"])
        assert recipe is not None
        assert recipe["name"] == "recent_concepts"

    def test_search_with_recipe_not_found(self, mock_client):
        with pytest.raises(Exception):
            mock_client.search_with_recipe("ws-1", "test query", "no_such_recipe")

    def test_search_with_recipe_calls_search(self, mock_client):
        mock_client.create_search_recipe(
            "ws-1", "my_search", {"limit": 5},
        )
        mock_client.search = MagicMock(return_value=[{"id": "1", "content": "result"}])
        results = mock_client.search_with_recipe("ws-1", "hello", "my_search")
        assert len(results) == 1
        mock_client.search.assert_called_once()


# =====================================================================
# Saga tracking
# =====================================================================


class TestSagaTracking:
    def test_create_saga(self, mock_client):
        result = mock_client.create_saga("ws-1", "import_batch")
        assert result["status"] == "ok"
        assert result["id"] != ""

    def test_create_saga_with_steps(self, mock_client):
        steps = [
            {"name": "create_nodes", "action": "Create KG nodes"},
            {"name": "create_edges", "action": "Link nodes"},
        ]
        result = mock_client.create_saga("ws-1", "import_batch", steps=steps)
        saga = mock_client.get_saga(result["id"])
        assert saga is not None
        assert saga["name"] == "import_batch"

    def test_get_nonexistent_saga(self, mock_client):
        assert mock_client.get_saga("no_saga") is None

    def test_complete_saga_step(self, mock_client):
        steps = [{"name": "step1", "action": "First step"}]
        result = mock_client.create_saga("ws-1", "test", steps=steps)
        saga_id = result["id"]

        step_result = mock_client.complete_saga_step(saga_id, "step1", {"count": 42})
        assert step_result["status"] == "ok"

        saga = Saga.from_storage_dict(_ONTO_STORE[saga_id])
        assert saga.steps[0].status == "completed"
        assert saga.steps[0].result == {"count": 42}

    def test_complete_nonexistent_step(self, mock_client):
        steps = [{"name": "step1", "action": "First step"}]
        result = mock_client.create_saga("ws-1", "test", steps=steps)
        saga_id = result["id"]

        step_result = mock_client.complete_saga_step(saga_id, "no_such_step", {})
        assert step_result["status"] == "error"

    def test_rollback_saga(self, mock_client):
        steps = [
            {"name": "step1", "action": "First"},
            {"name": "step2", "action": "Second"},
        ]
        result = mock_client.create_saga("ws-1", "test", steps=steps)
        saga_id = result["id"]

        # Complete first step, then rollback
        mock_client.complete_saga_step(saga_id, "step1", {"ok": True})
        rollback_result = mock_client.rollback_saga(saga_id)
        assert rollback_result["status"] == "ok"

        saga = Saga.from_storage_dict(_ONTO_STORE[saga_id])
        assert saga.status == "rolled_back"
        assert saga.steps[0].status == "completed"  # completed steps stay completed
        assert saga.steps[1].status == "rolled_back"  # pending steps are rolled back

    def test_rollback_nonexistent_saga(self, mock_client):
        result = mock_client.rollback_saga("no_saga")
        assert result["status"] == "error"

    def test_list_sagas(self, mock_client):
        mock_client.create_saga("ws-1", "import1")
        mock_client.create_saga("ws-1", "import2")
        mock_client.create_saga("ws-2", "other")  # different workspace

        sagas = mock_client.list_sagas("ws-1")
        assert len(sagas) == 2
        names = {s["name"] for s in sagas}
        assert names == {"import1", "import2"}

    def test_list_sagas_by_status(self, mock_client):
        mock_client.create_saga("ws-1", "active_saga")
        r2 = mock_client.create_saga("ws-1", "to_rollback")
        mock_client.rollback_saga(r2["id"])

        active = mock_client.list_sagas("ws-1", status="active")
        assert len(active) == 1
        assert active[0]["name"] == "active_saga"

        rolled = mock_client.list_sagas("ws-1", status="rolled_back")
        assert len(rolled) == 1
        assert rolled[0]["name"] == "to_rollback"


# =====================================================================
# Edge cases and integration scenarios
# =====================================================================


class TestEdgeCases:
    def test_entity_type_hierarchy_resolution(self, mock_client):
        """Verify deep inheritance chains work."""
        mock_client.create_entity_type("ws-1", "Person", properties=["name"])
        mock_client.create_entity_type("ws-1", "Employee", parent_type="Person",
                                        properties=["employee_id"])
        mock_client.create_entity_type("ws-1", "Manager", parent_type="Employee",
                                        properties=["budget"])
        mock_client.create_entity_type("ws-1", "SeniorManager", parent_type="Manager",
                                        properties=["region"])

        # Check inheritance chain
        result = mock_client.validate_node(
            {"label": "Dave", "node_type": "SeniorManager"},
            "Person",
            workspace_id="ws-1",
        )
        assert result["valid"] is True

    def test_unknown_properties_are_warnings_not_errors(self, mock_client):
        mock_client.create_entity_type("ws-1", "SimpleType",
                                        properties=["only_this"])
        result = mock_client.validate_node(
            {"label": "Test", "only_this": "ok", "unknown_field": "bad"},
            "SimpleType",
            workspace_id="ws-1",
        )
        assert result["valid"] is True
        assert len(result["warnings"]) == 1

    def test_standard_fields_never_warn(self, mock_client):
        mock_client.create_entity_type("ws-1", "Minimal")
        result = mock_client.validate_node(
            {
                "id": "abc",
                "label": "Test",
                "summary": "A test node",
                "node_type": "Minimal",
                "metadata_json": "{}",
                "is_active": True,
            },
            "Minimal",
            workspace_id="ws-1",
        )
        assert result["valid"] is True
        assert result["warnings"] == []

    def test_validate_edge_with_empty_constraints(self, mock_client):
        """Relation type with no source/target constraints should allow anything."""
        mock_client.create_relation_type("ws-1", "related_to")
        result = mock_client.validate_edge(
            {"relation": "related_to"},
            "related_to",
            workspace_id="ws-1",
        )
        assert result["valid"] is True

    def test_list_entity_types_scoped_by_workspace(self, mock_client):
        mock_client.create_entity_type("ws-1", "A")
        mock_client.create_entity_type("ws-2", "B")
        mock_client.create_entity_type("ws-1", "C")
        assert len(mock_client.list_entity_types("ws-1")) == 2
        assert len(mock_client.list_entity_types("ws-2")) == 1

    def test_saga_round_trip_complex(self, mock_client):
        """Full lifecycle: create → step complete → rollback."""
        steps = [
            {"name": "validate", "action": "Validate input data"},
            {"name": "create_nodes", "action": "Create 50 KG nodes"},
            {"name": "create_edges", "action": "Create edges between nodes"},
        ]
        r = mock_client.create_saga("ws-1", "bulk_import", steps=steps)
        sid = r["id"]

        mock_client.complete_saga_step(sid, "validate", {"valid": True, "count": 50})
        mock_client.complete_saga_step(sid, "create_nodes", {"nodes_created": 50})
        # Oops — something went wrong, rollback
        mock_client.rollback_saga(sid)

        saga = Saga.from_storage_dict(_ONTO_STORE[sid])
        assert saga.status == "rolled_back"
        assert saga.steps[0].status == "completed"  # completed steps stay completed
        assert saga.steps[1].status == "completed"
        assert saga.steps[2].status == "rolled_back"  # pending → rolled_back
