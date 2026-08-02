"""Ontology management module — Graphiti parity.

Provides a type hierarchy and relationship type system for knowledge graph
entities. Extends the existing KG infrastructure with:

- Entity type hierarchy (e.g. Person > Employee > Manager)
- Relationship type definitions with constraints (source_type, target_type,
  allowed predicates)
- Schema validation for nodes and edges against the ontology
- Namespace management for organising ontologies
- Search recipe definitions (named search configurations)
- Saga tracking — long-running KG operations with rollback

All data is stored via structured entries in the workspace's memory/directive
infrastructure, with client-side logic providing validation and processing.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from ._base import NotFoundError, logger

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class EntityTypeDefinition:
    """Definition of an entity type in the ontology hierarchy.

    Attributes:
        id: Unique identifier.
        workspace_id: The workspace this type belongs to.
        name: Human-readable type name (e.g. "Person", "Employee").
        parent_type: Optional parent type name for hierarchy (e.g. "Person").
        properties: List of allowed property key names for this type.
        description: Free-text description.
        namespace: Optional namespace for organising ontologies.
        created_at: Unix micros timestamp.
        updated_at: Unix micros timestamp.
    """
    id: str = ""
    workspace_id: str = ""
    name: str = ""
    parent_type: str = ""
    properties: list[str] = field(default_factory=list)
    description: str = ""
    namespace: str = ""
    created_at: int = 0
    updated_at: int = 0

    def to_storage_dict(self) -> dict[str, Any]:
        """Serialise to a dict for storage in the ontology entry table."""
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "parent_type": self.parent_type,
            "properties": json.dumps(self.properties),
            "description": self.description,
            "namespace": self.namespace,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "entry_type": "entity_type",
        }

    @classmethod
    def from_storage_dict(cls, row: dict[str, Any]) -> EntityTypeDefinition:
        """Parse an EntityTypeDefinition from a storage row."""
        props_raw = row.get("properties", "[]")
        if isinstance(props_raw, str):
            try:
                properties = json.loads(props_raw)
            except (json.JSONDecodeError, TypeError):
                properties = []
        elif isinstance(props_raw, list):
            properties = props_raw
        else:
            properties = []

        return cls(
            id=row.get("id", ""),
            workspace_id=row.get("workspace_id", ""),
            name=row.get("name", ""),
            parent_type=row.get("parent_type", ""),
            properties=properties,
            description=row.get("description", ""),
            namespace=row.get("namespace", ""),
            created_at=int(row.get("created_at", 0)),
            updated_at=int(row.get("updated_at", 0)),
        )


@dataclass
class RelationTypeDefinition:
    """Definition of a relationship type in the ontology.

    Attributes:
        id: Unique identifier.
        workspace_id: The workspace this relation type belongs to.
        name: Human-readable name (e.g. "reports_to", "works_at").
        source_types: List of allowed source entity type names.
        target_types: List of allowed target entity type names.
        properties: List of allowed property key names for edges of this type.
        description: Free-text description.
        namespace: Optional namespace for organising ontologies.
        created_at: Unix micros timestamp.
        updated_at: Unix micros timestamp.
    """
    id: str = ""
    workspace_id: str = ""
    name: str = ""
    source_types: list[str] = field(default_factory=list)
    target_types: list[str] = field(default_factory=list)
    properties: list[str] = field(default_factory=list)
    description: str = ""
    namespace: str = ""
    created_at: int = 0
    updated_at: int = 0

    def to_storage_dict(self) -> dict[str, Any]:
        """Serialise to a dict for storage in the ontology entry table."""
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "source_types": json.dumps(self.source_types),
            "target_types": json.dumps(self.target_types),
            "properties": json.dumps(self.properties),
            "description": self.description,
            "namespace": self.namespace,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "entry_type": "relation_type",
        }

    @classmethod
    def from_storage_dict(cls, row: dict[str, Any]) -> RelationTypeDefinition:
        """Parse a RelationTypeDefinition from a storage row."""
        def _load_json_list(val: Any) -> list[str]:
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    return []
            return val if isinstance(val, list) else []

        return cls(
            id=row.get("id", ""),
            workspace_id=row.get("workspace_id", ""),
            name=row.get("name", ""),
            source_types=_load_json_list(row.get("source_types", "[]")),
            target_types=_load_json_list(row.get("target_types", "[]")),
            properties=_load_json_list(row.get("properties", "[]")),
            description=row.get("description", ""),
            namespace=row.get("namespace", ""),
            created_at=int(row.get("created_at", 0)),
            updated_at=int(row.get("updated_at", 0)),
        )


@dataclass
class SearchRecipe:
    """A named search configuration.

    Attributes:
        id: Unique identifier.
        workspace_id: The workspace this recipe belongs to.
        name: Human-readable name (e.g. "recent_concepts", "kg_semantic_search").
        search_params: Dict of search parameters (query, limit, filters, etc.).
        description: Free-text description.
        created_at: Unix micros timestamp.
        updated_at: Unix micros timestamp.
    """
    id: str = ""
    workspace_id: str = ""
    name: str = ""
    search_params: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    created_at: int = 0
    updated_at: int = 0

    def to_storage_dict(self) -> dict[str, Any]:
        """Serialise to a dict for storage."""
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "search_params": json.dumps(self.search_params),
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "entry_type": "search_recipe",
        }

    @classmethod
    def from_storage_dict(cls, row: dict[str, Any]) -> SearchRecipe:
        """Parse a SearchRecipe from a storage row."""
        params_raw = row.get("search_params", "{}")
        if isinstance(params_raw, str):
            try:
                search_params = json.loads(params_raw)
            except (json.JSONDecodeError, TypeError):
                search_params = {}
        elif isinstance(params_raw, dict):
            search_params = params_raw
        else:
            search_params = {}

        return cls(
            id=row.get("id", ""),
            workspace_id=row.get("workspace_id", ""),
            name=row.get("name", ""),
            search_params=search_params,
            description=row.get("description", ""),
            created_at=int(row.get("created_at", 0)),
            updated_at=int(row.get("updated_at", 0)),
        )


@dataclass
class SagaStep:
    """A single step within a saga.

    Attributes:
        name: Step name (unique within the saga).
        action: Description of the action performed.
        result: JSON-serialisable result or status of the step.
        status: One of "pending", "completed", "failed", "rolled_back".
        created_at: Unix micros timestamp.
    """
    name: str = ""
    action: str = ""
    result: Any = None
    status: str = "pending"
    created_at: int = 0


@dataclass
class Saga:
    """Tracks a multi-step KG operation with rollback support.

    Attributes:
        id: Unique identifier.
        workspace_id: The workspace this saga belongs to.
        name: Human-readable name (e.g. "import_contacts_batch").
        steps: List of SagaStep instances.
        status: One of "active", "completed", "rolled_back", "failed".
        created_at: Unix micros timestamp.
        updated_at: Unix micros timestamp.
    """
    id: str = ""
    workspace_id: str = ""
    name: str = ""
    steps: list[SagaStep] = field(default_factory=list)
    status: str = "active"
    created_at: int = 0
    updated_at: int = 0

    def to_storage_dict(self) -> dict[str, Any]:
        """Serialise to a dict for storage."""
        steps_data = []
        for step in self.steps:
            step_dict = asdict(step)
            step_dict["result"] = json.dumps(step_dict.get("result"))
            steps_data.append(step_dict)
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "steps": json.dumps(steps_data),
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "entry_type": "saga",
        }

    @classmethod
    def from_storage_dict(cls, row: dict[str, Any]) -> Saga:
        """Parse a Saga from a storage row."""
        steps_raw = row.get("steps", "[]")
        if isinstance(steps_raw, str):
            try:
                steps_data = json.loads(steps_raw)
            except (json.JSONDecodeError, TypeError):
                steps_data = []
        elif isinstance(steps_raw, list):
            steps_data = steps_raw
        else:
            steps_data = []

        steps = []
        for sd in steps_data:
            result_raw = sd.get("result", "null")
            if isinstance(result_raw, str):
                try:
                    result = json.loads(result_raw)
                except (json.JSONDecodeError, TypeError):
                    result = result_raw
            else:
                result = result_raw
            steps.append(SagaStep(
                name=sd.get("name", ""),
                action=sd.get("action", ""),
                result=result,
                status=sd.get("status", "pending"),
                created_at=int(sd.get("created_at", 0)),
            ))

        return cls(
            id=row.get("id", ""),
            workspace_id=row.get("workspace_id", ""),
            name=row.get("name", ""),
            steps=steps,
            status=row.get("status", "active"),
            created_at=int(row.get("created_at", 0)),
            updated_at=int(row.get("updated_at", 0)),
        )


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------


# In-memory storage for when no backend reducer / table is available.
# The mixin first tries _call + _query (reducer path), then falls back
# to this in-memory dict when reducers are not registered.  Tests and
# standalone SDK usage should work with the in-memory fallback.
_ONTO_STORE: dict[str, dict[str, Any]] = {}  # id -> entry dict


def _now_micros() -> int:
    """Return current time in Unix microseconds."""
    return int(time.time() * 1_000_000)


def _gen_id() -> str:
    """Generate a short unique ID."""
    return secrets.token_hex(12)


class OntologyMixin:
    """Spacetime-Memory ontology mixin.

    Provides Client methods for ontology management — entity type hierarchy,
    relation types with constraints, schema validation, namespaces, search
    recipes, and saga tracking.

    Inherits from ClientBase for connection infrastructure.  Data is stored
    either via backend reducers (when available) or in an internal dict.
    """

    # ------------------------------------------------------------------
    # Entity type CRUD
    # ------------------------------------------------------------------

    def create_entity_type(
        self,
        workspace_id: str,
        name: str,
        parent_type: str = "",
        properties: list[str] | None = None,
        description: str = "",
        namespace: str = "",
    ) -> dict[str, Any]:
        """Create a new entity type in the ontology hierarchy.

        Args:
            workspace_id: Target workspace.
            name: Type name (e.g. "Employee").
            parent_type: Optional parent type name (e.g. "Person").
            properties: List of allowed property key names.
            description: Free-text description.
            namespace: Optional namespace for organising ontologies.

        Returns:
            Dict with ``status`` and ``id`` keys.
        """
        now = _now_micros()
        entry_id = _gen_id()
        et = EntityTypeDefinition(
            id=entry_id,
            workspace_id=workspace_id,
            name=name,
            parent_type=parent_type,
            properties=properties or [],
            description=description,
            namespace=namespace,
            created_at=now,
            updated_at=now,
        )
        storage = et.to_storage_dict()

        try:
            result = self._call(
                "create_ontology_entry",
                [
                    workspace_id,
                    entry_id,
                    name,
                    json.dumps(storage),
                    "entity_type",
                    namespace,
                ],
            )
            if result.get("status") == "ok":
                _ONTO_STORE[entry_id] = storage
            return result
        except Exception:
            # Fallback: in-memory storage
            _ONTO_STORE[entry_id] = storage
            return {"status": "ok", "id": entry_id}

    def get_entity_type(self, type_id: str) -> dict[str, Any] | None:
        """Get an entity type definition by its ID.

        Args:
            type_id: The entity type ID.

        Returns:
            Entity type dict, or ``None`` if not found.
        """
        # Try reducer path
        try:
            self._call("get_ontology_entry", [type_id])
            rows = self._query("ontology_entry", filter_dict={"id": type_id})
            if rows:
                return rows[0]
        except Exception:
            pass

        # Fallback: in-memory lookup
        entry = _ONTO_STORE.get(type_id)
        if entry and entry.get("entry_type") == "entity_type":
            return entry
        return None

    def list_entity_types(
        self,
        workspace_id: str,
        parent_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """List entity types in a workspace, optionally filtered by parent.

        Args:
            workspace_id: Target workspace.
            parent_type: If set, only return types with this parent.

        Returns:
            List of entity type dicts.
        """
        results: list[dict[str, Any]] = []

        # Try reducer path
        try:
            self._call("list_ontology_entries", [workspace_id, "entity_type"])
            rows = self._sql_param(
                "SELECT * FROM ontology_list_result WHERE "
                "workspace_id = ? AND entry_type = 'entity_type' "
                "ORDER BY created_at ASC",
                workspace_id,
            )
            results = rows
        except Exception:
            pass

        if not results:
            # Fallback: in-memory filter
            for entry in _ONTO_STORE.values():
                if (entry.get("workspace_id") == workspace_id
                        and entry.get("entry_type") == "entity_type"):
                    results.append(entry)

        if parent_type is not None:
            results = [r for r in results if r.get("parent_type") == parent_type]

        return results

    def delete_entity_type(self, type_id: str) -> dict[str, Any]:
        """Delete an entity type by its ID.

        Args:
            type_id: The entity type ID.

        Returns:
            Dict with reducer response status.
        """
        try:
            result = self._call("delete_ontology_entry", [type_id])
            _ONTO_STORE.pop(type_id, None)
            return result
        except Exception:
            removed = _ONTO_STORE.pop(type_id, None)
            if removed:
                return {"status": "ok"}
            return {"status": "error", "message": f"Entity type '{type_id}' not found"}

    # ------------------------------------------------------------------
    # Relation type CRUD
    # ------------------------------------------------------------------

    def create_relation_type(
        self,
        workspace_id: str,
        name: str,
        source_types: list[str] | None = None,
        target_types: list[str] | None = None,
        properties: list[str] | None = None,
        description: str = "",
        namespace: str = "",
    ) -> dict[str, Any]:
        """Create a new relationship type with source/target constraints.

        Args:
            workspace_id: Target workspace.
            name: Relationship type name (e.g. "reports_to", "works_at").
            source_types: List of allowed source entity type names.
            target_types: List of allowed target entity type names.
            properties: List of allowed property key names for edges.
            description: Free-text description.
            namespace: Optional namespace for organising ontologies.

        Returns:
            Dict with ``status`` and ``id`` keys.
        """
        now = _now_micros()
        entry_id = _gen_id()
        rt = RelationTypeDefinition(
            id=entry_id,
            workspace_id=workspace_id,
            name=name,
            source_types=source_types or [],
            target_types=target_types or [],
            properties=properties or [],
            description=description,
            namespace=namespace,
            created_at=now,
            updated_at=now,
        )
        storage = rt.to_storage_dict()

        try:
            result = self._call(
                "create_ontology_entry",
                [
                    workspace_id,
                    entry_id,
                    name,
                    json.dumps(storage),
                    "relation_type",
                    namespace,
                ],
            )
            if result.get("status") == "ok":
                _ONTO_STORE[entry_id] = storage
            return result
        except Exception:
            _ONTO_STORE[entry_id] = storage
            return {"status": "ok", "id": entry_id}

    def get_relation_type(self, type_id: str) -> dict[str, Any] | None:
        """Get a relation type definition by its ID.

        Args:
            type_id: The relation type ID.

        Returns:
            Relation type dict, or ``None`` if not found.
        """
        try:
            self._call("get_ontology_entry", [type_id])
            rows = self._query("ontology_entry", filter_dict={"id": type_id})
            if rows:
                return rows[0]
        except Exception:
            pass

        entry = _ONTO_STORE.get(type_id)
        if entry and entry.get("entry_type") == "relation_type":
            return entry
        return None

    def list_relation_types(
        self,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """List all relation types in a workspace.

        Args:
            workspace_id: Target workspace.

        Returns:
            List of relation type dicts.
        """
        results: list[dict[str, Any]] = []

        try:
            self._call("list_ontology_entries", [workspace_id, "relation_type"])
            rows = self._sql_param(
                "SELECT * FROM ontology_list_result WHERE "
                "workspace_id = ? AND entry_type = 'relation_type' "
                "ORDER BY created_at ASC",
                workspace_id,
            )
            results = rows
        except Exception:
            pass

        if not results:
            for entry in _ONTO_STORE.values():
                if (entry.get("workspace_id") == workspace_id
                        and entry.get("entry_type") == "relation_type"):
                    results.append(entry)

        return results

    def delete_relation_type(self, type_id: str) -> dict[str, Any]:
        """Delete a relation type by its ID.

        Args:
            type_id: The relation type ID.

        Returns:
            Dict with reducer response status.
        """
        try:
            result = self._call("delete_ontology_entry", [type_id])
            _ONTO_STORE.pop(type_id, None)
            return result
        except Exception:
            removed = _ONTO_STORE.pop(type_id, None)
            if removed:
                return {"status": "ok"}
            return {"status": "error", "message": f"Relation type '{type_id}' not found"}

    # ------------------------------------------------------------------
    # Schema validation
    # ------------------------------------------------------------------

    def _resolve_entity_type_definition(
        self,
        entity_type_name: str,
        workspace_id: str,
        _depth: int = 0,
    ) -> EntityTypeDefinition | None:
        """Resolve an entity type definition by name, walking the hierarchy.

        Searches within the workspace for an entity type with the given
        name. Returns the :class:`EntityTypeDefinition` or ``None``.
        """
        if _depth > 20:
            return None

        types = self.list_entity_types(workspace_id)
        for t in types:
            if t.get("name") == entity_type_name:
                return EntityTypeDefinition.from_storage_dict(t)
        return None

    def _resolve_relation_type_definition(
        self,
        relation_type_name: str,
        workspace_id: str,
    ) -> RelationTypeDefinition | None:
        """Resolve a relation type definition by name."""
        rtypes = self.list_relation_types(workspace_id)
        for rt in rtypes:
            if rt.get("name") == relation_type_name:
                return RelationTypeDefinition.from_storage_dict(rt)
        return None

    def _check_type_inheritance(
        self,
        node_type_name: str,
        expected_type_name: str,
        workspace_id: str,
        _depth: int = 0,
    ) -> bool:
        """Check if ``node_type_name`` is or inherits from ``expected_type_name``."""
        if _depth > 20:
            return False

        if node_type_name == expected_type_name:
            return True

        et = self._resolve_entity_type_definition(node_type_name, workspace_id)
        if et is None:
            return False

        if et.parent_type:
            return self._check_type_inheritance(
                et.parent_type, expected_type_name, workspace_id, _depth + 1,
            )
        return False

    def validate_node(
        self,
        node_data: dict[str, Any],
        entity_type: str,
        workspace_id: str = "",
    ) -> dict[str, Any]:
        """Validate a KG node against an entity type definition.

        Checks:
        - The entity type exists in the workspace ontology.
        - All keys in *node_data* are allowed properties for that type
          (plus standard KG fields like ``label``, ``summary``, ``id``).
        - Unknown properties generate warnings.

        Args:
            node_data: The node data dict (keys like ``label``, ``summary``,
                plus custom properties).
            entity_type: The entity type name to validate against.
            workspace_id: Target workspace (required for ontology lookup).

        Returns:
            Dict with ``valid`` (bool), ``errors`` (list), ``warnings`` (list).
        """
        errors: list[str] = []
        warnings: list[str] = []

        if not workspace_id:
            # Try to extract from node_data
            workspace_id = node_data.get("workspace_id", "")

        # Resolve the entity type definition (including inheritance)
        et = self._resolve_entity_type_definition(entity_type, workspace_id)
        if et is None:
            errors.append(f"Entity type '{entity_type}' not found in workspace ontology")
            return {"valid": False, "errors": errors, "warnings": warnings}

        # Standard KG fields that are always allowed
        standard_fields = {
            "id", "label", "summary", "node_type", "metadata_json",
            "source_memory_id", "source_document_id", "workspace_id",
            "is_active", "created_at", "updated_at",
        }

        allowed_properties = set(et.properties) | standard_fields

        for key in node_data:
            if key not in allowed_properties:
                warnings.append(
                    f"Unknown property '{key}' — not declared in entity type "
                    f"'{entity_type}' (allowed: {sorted(et.properties)})"
                )

        # Check that type hierarchy is followed — node_type must match
        node_type_val = node_data.get("node_type", "")
        if node_type_val and node_type_val != entity_type:
            if not self._check_type_inheritance(node_type_val, entity_type, workspace_id):
                warnings.append(
                    f"node_type '{node_type_val}' does not match or inherit "
                    f"from expected entity type '{entity_type}'"
                )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    def validate_edge(
        self,
        edge_data: dict[str, Any],
        relation_type: str,
        workspace_id: str = "",
    ) -> dict[str, Any]:
        """Validate a KG edge against a relation type definition.

        Checks:
        - The relation type exists in the workspace ontology.
        - Source and target node types match the constraints (if available).
        - Unknown properties generate warnings.

        Args:
            edge_data: The edge data dict (keys like ``relation``,
                ``source_node_id``, ``target_node_id``, plus custom properties).
            relation_type: The relation type name to validate against.
            workspace_id: Target workspace (required for ontology lookup).

        Returns:
            Dict with ``valid`` (bool), ``errors`` (list), ``warnings`` (list).
        """
        errors: list[str] = []
        warnings: list[str] = []

        if not workspace_id:
            workspace_id = edge_data.get("workspace_id", "")

        rt = self._resolve_relation_type_definition(relation_type, workspace_id)
        if rt is None:
            errors.append(
                f"Relation type '{relation_type}' not found in workspace ontology"
            )
            return {"valid": False, "errors": errors, "warnings": warnings}

        # Standard edge fields
        standard_fields = {
            "id", "relation", "source_node_id", "target_node_id",
            "weight", "confidence", "metadata_json", "source_memory_id",
            "source_document_id", "workspace_id", "is_active",
            "created_at", "updated_at",
        }

        allowed_properties = set(rt.properties) | standard_fields

        for key in edge_data:
            if key not in allowed_properties:
                warnings.append(
                    f"Unknown property '{key}' — not declared in relation type "
                    f"'{relation_type}' (allowed: {sorted(rt.properties)})"
                )

        # Source/target type constraints
        edge_source_types = edge_data.get("source_types", [])
        if not edge_source_types:
            # Try to infer from source_node_id — not possible without graph traversal
            pass
        elif rt.source_types:
            for st in edge_source_types:
                if st not in rt.source_types:
                    any_match = any(
                        self._check_type_inheritance(st, allowed, workspace_id)
                        for allowed in rt.source_types
                    )
                    if not any_match:
                        errors.append(
                            f"Source type '{st}' is not allowed for relation "
                            f"'{relation_type}' (allowed: {rt.source_types})"
                        )

        edge_target_types = edge_data.get("target_types", [])
        if edge_target_types and rt.target_types:
            for tt in edge_target_types:
                if tt not in rt.target_types:
                    any_match = any(
                        self._check_type_inheritance(tt, allowed, workspace_id)
                        for allowed in rt.target_types
                    )
                    if not any_match:
                        errors.append(
                            f"Target type '{tt}' is not allowed for relation "
                            f"'{relation_type}' (allowed: {rt.target_types})"
                        )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # Search recipe management
    # ------------------------------------------------------------------

    def create_search_recipe(
        self,
        workspace_id: str,
        name: str,
        search_params: dict[str, Any] | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a named search configuration (recipe).

        Args:
            workspace_id: Target workspace.
            name: Human-readable name (e.g. "recent_concepts").
            search_params: Dict of search parameters such as ``query``,
                ``limit``, ``filters``, ``search_type``, etc.
            description: Free-text description.

        Returns:
            Dict with ``status`` and ``id`` keys.
        """
        now = _now_micros()
        entry_id = _gen_id()
        recipe = SearchRecipe(
            id=entry_id,
            workspace_id=workspace_id,
            name=name,
            search_params=search_params or {},
            description=description,
            created_at=now,
            updated_at=now,
        )
        storage = recipe.to_storage_dict()

        try:
            result = self._call(
                "create_ontology_entry",
                [
                    workspace_id,
                    entry_id,
                    name,
                    json.dumps(storage),
                    "search_recipe",
                    "",
                ],
            )
            if result.get("status") == "ok":
                _ONTO_STORE[entry_id] = storage
            return result
        except Exception:
            _ONTO_STORE[entry_id] = storage
            return {"status": "ok", "id": entry_id}

    def get_search_recipe(self, recipe_id: str) -> dict[str, Any] | None:
        """Get a search recipe by its ID.

        Args:
            recipe_id: The search recipe ID.

        Returns:
            Search recipe dict, or ``None`` if not found.
        """
        try:
            self._call("get_ontology_entry", [recipe_id])
            rows = self._query("ontology_entry", filter_dict={"id": recipe_id})
            if rows:
                return rows[0]
        except Exception:
            pass

        entry = _ONTO_STORE.get(recipe_id)
        if entry and entry.get("entry_type") == "search_recipe":
            return entry
        return None

    def search_with_recipe(
        self,
        workspace_id: str,
        query: str,
        recipe_name: str,
    ) -> list[dict[str, Any]]:
        """Execute a search using a named recipe.

        Looks up the recipe by name in the workspace, then calls
        ``client.search()`` with the recipe's parameters merged with
        the provided query.

        Args:
            workspace_id: Target workspace.
            query: The search query string.
            recipe_name: Name of the search recipe to use.

        Returns:
            List of search result dicts.
        """
        # Find recipe by name in the workspace
        try:
            self._call("list_ontology_entries", [workspace_id, "search_recipe"])
            rows = self._sql_param(
                "SELECT * FROM ontology_list_result WHERE "
                "workspace_id = ? AND entry_type = 'search_recipe' "
                "ORDER BY created_at ASC",
                workspace_id,
            )
            recipes = rows
        except Exception:
            recipes = [
                e for e in _ONTO_STORE.values()
                if e.get("workspace_id") == workspace_id
                and e.get("entry_type") == "search_recipe"
            ]

        recipe = None
        for r in recipes:
            if r.get("name") == recipe_name:
                recipe = SearchRecipe.from_storage_dict(r)
                break

        if recipe is None:
            raise NotFoundError(
                f"Search recipe '{recipe_name}' not found in workspace '{workspace_id}'"
            )

        # Build search kwargs from recipe params + overrides
        params = dict(recipe.search_params)
        params["query"] = query
        limit = params.pop("limit", 20)
        filters = params.pop("filters", None)

        search_kwargs: dict[str, Any] = {
            "workspace_id": workspace_id,
            "query": query,
            "limit": limit,
        }
        if filters:
            search_kwargs["filters"] = filters

        # Call the search method (may be "search" or "search_memories")
        try:
            return self.search(**search_kwargs)  # type: ignore[arg-type]
        except AttributeError:
            # Fallback: basic _query search
            rows = self._query("kg_node", workspace_id=workspace_id)
            q = query.lower()
            matched = [
                r for r in rows
                if q in r.get("label", "").lower()
                or q in r.get("summary", "").lower()
            ]
            return matched[:limit]

    # ------------------------------------------------------------------
    # Gap #5: Custom Ontology — attribute extraction, validation modes,
    # entity/relationship type search
    # ------------------------------------------------------------------

    def extract_attributes(
        self,
        text: str,
        ontology_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Extract structured attributes from text using the LLM.

        Uses the existing LLM infrastructure to extract attribute key-value
        pairs from unstructured text.  If *ontology_schema* is provided,
        extraction is constrained to the declared properties in that schema.

        Args:
            text: The unstructured text to extract attributes from.
            ontology_schema: Optional dict with ``entity_type`` (str) and
                ``properties`` (list of str) to constrain extraction.

        Returns:
            Dict of extracted attribute key-value pairs.
        """
        if not text:
            return {}

        schema_hint = ""
        if ontology_schema:
            entity_type = ontology_schema.get("entity_type", "")
            props = ontology_schema.get("properties", [])
            if props:
                schema_hint = (
                    f"\nExtract ONLY from these allowed properties for "
                    f"entity type '{entity_type}': {json.dumps(props)}\n"
                    f"Return ONLY those keys that can be confidently determined "
                    f"from the text.\n"
                )

        prompt = (
            "Extract structured attributes from the following text. "
            "Return a JSON object with key-value pairs for all attributes "
            "you can determine. Be concise — only include attributes that "
            "are explicitly stated or clearly implied.\n"
            f"{schema_hint}"
            f"\nText:\n{text[:3000]}\n\n"
            "JSON:"
        )

        try:
            endpoint = os.getenv("LLM_RERANK_ENDPOINT", "http://127.0.0.1:4000/v1")
            model = os.getenv("LLM_RERANK_MODEL", "ds-deepseek-v4-flash")
            api_key = os.getenv("LLM_RERANK_API_KEY") or os.getenv("OPENAI_API_KEY", "")

            resp = httpx.post(
                f"{endpoint.rstrip('/')}/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "max_tokens": 1024,
                },
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                timeout=30,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()

            # Strip markdown fences if present
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            result = json.loads(content)
            if isinstance(result, dict):
                return result
            return {}
        except Exception as exc:
            logger.warning("Attribute extraction failed: %s", exc)
            return {}

    def strict_validate(
        self,
        entity_data: dict[str, Any],
        entity_type: str | None = None,
        workspace_id: str = "",
    ) -> dict[str, Any]:
        """Strict-mode schema validation — rejects undeclared properties.

        Unlike ``validate_node()`` (which only warns on undeclared properties),
        strict mode **rejects** entities that have properties not declared
        in the entity type definition.

        Args:
            entity_data: The entity data dict.
            entity_type: Optional entity type name.  If not provided, tries
                to infer from ``entity_data.get("node_type")``.
            workspace_id: Target workspace.

        Returns:
            Dict with ``valid`` (bool), ``errors`` (list), and
            ``warnings`` (list).
        """
        if not entity_type:
            entity_type = entity_data.get("node_type", "")

        if not workspace_id:
            workspace_id = entity_data.get("workspace_id", "")

        # Start with normal validation
        result = self.validate_node(entity_data, entity_type or "", workspace_id)

        # In strict mode, warnings about unknown properties become errors
        if result.get("warnings"):
            for w in result["warnings"]:
                if "Unknown property" in w:
                    result["errors"].append(w)
            result["warnings"] = []
            result["valid"] = len(result["errors"]) == 0

        return result

    def extensible_validate(
        self,
        entity_data: dict[str, Any],
        entity_type: str | None = None,
        workspace_id: str = "",
    ) -> dict[str, Any]:
        """Extensible-mode schema validation — allows undeclared properties.

        Same as ``validate_node()`` but explicitly runs in extensible mode:
        undeclared properties generate warnings but never errors.

        Args:
            entity_data: The entity data dict.
            entity_type: Optional entity type name.
            workspace_id: Target workspace.

        Returns:
            Dict with ``valid`` (bool, always True if type exists),
            ``errors`` (list), ``warnings`` (list).
        """
        if not entity_type:
            entity_type = entity_data.get("node_type", "")

        if not workspace_id:
            workspace_id = entity_data.get("workspace_id", "")

        result = self.validate_node(entity_data, entity_type, workspace_id)
        # In extensible mode, errors about unknown properties become warnings
        deferred: list[str] = []
        for err in result.get("errors", []):
            if "not found" in err:
                deferred.append(err)
            else:
                result.setdefault("warnings", []).append(
                    f"[extensible] {err}"
                )
        result["errors"] = deferred
        result["valid"] = len(result["errors"]) == 0
        return result

    def set_ontology_mode(
        self,
        workspace_id: str,
        mode: str,
    ) -> dict[str, Any]:
        """Set the ontology validation mode for a workspace.

        Args:
            workspace_id: Target workspace.
            mode: One of ``"strict"`` or ``"extensible"``.

        Returns:
            Dict with ``status`` and ``mode`` keys.
        """
        if mode not in ("strict", "extensible"):
            return {"status": "error", "message": f"Invalid mode '{mode}'. Must be 'strict' or 'extensible'."}

        key = f"_ontology_mode_{workspace_id}"
        _ONTO_STORE[key] = {
            "id": key,
            "workspace_id": workspace_id,
            "mode": mode,
            "updated_at": _now_micros(),
            "entry_type": "ontology_mode",
        }

        try:
            self._call(
                "create_ontology_entry",
                [workspace_id, key, "_ontology_mode",
                 json.dumps(_ONTO_STORE[key]), "ontology_mode", ""],
            )
        except Exception:
            pass

        return {"status": "ok", "mode": mode}

    def get_ontology_mode(self, workspace_id: str) -> dict[str, Any]:
        """Get the current ontology validation mode for a workspace.

        Args:
            workspace_id: Target workspace.

        Returns:
            Dict with ``mode`` (str) and ``workspace_id``.
            Defaults to ``"extensible"`` if not explicitly set.
        """
        key = f"_ontology_mode_{workspace_id}"

        # Try reducer path
        try:
            self._call("get_ontology_entry", [key])
            rows = self._query("ontology_entry", filter_dict={"id": key})
            if rows:
                mode = rows[0].get("mode", "extensible")
                return {"workspace_id": workspace_id, "mode": mode}
        except Exception:
            pass

        # Fallback: in-memory lookup
        entry = _ONTO_STORE.get(key)
        if entry:
            return {"workspace_id": workspace_id, "mode": entry.get("mode", "extensible")}

        return {"workspace_id": workspace_id, "mode": "extensible"}

    def search_entity_types(
        self,
        workspace_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        """Search/query entity types in a workspace.

        Performs a case-insensitive substring match against type names,
        descriptions, and properties.

        Args:
            workspace_id: Target workspace.
            query: Search query string.

        Returns:
            List of matching entity type dicts.
        """
        if not query:
            return self.list_entity_types(workspace_id)

        types = self.list_entity_types(workspace_id)
        q = query.lower().strip()
        matched = []
        for t in types:
            name = (t.get("name") or "").lower()
            desc = (t.get("description") or "").lower()
            props_raw = t.get("properties", "[]")
            props_str = ""
            if isinstance(props_raw, str):
                try:
                    props_list = json.loads(props_raw)
                    props_str = " ".join(props_list).lower()
                except (json.JSONDecodeError, TypeError):
                    pass
            elif isinstance(props_raw, list):
                props_str = " ".join(props_raw).lower()

            if q in name or q in desc or q in props_str:
                matched.append(t)

        return matched

    def search_relationship_types(
        self,
        workspace_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        """Search/query relationship types in a workspace.

        Performs a case-insensitive substring match against type names,
        descriptions, source/target types, and properties.

        Args:
            workspace_id: Target workspace.
            query: Search query string.

        Returns:
            List of matching relationship type dicts.
        """
        if not query:
            return self.list_relation_types(workspace_id)

        types = self.list_relation_types(workspace_id)
        q = query.lower().strip()
        matched = []
        for t in types:
            name = (t.get("name") or "").lower()
            desc = (t.get("description") or "").lower()
            src = (t.get("source_types") or "")
            tgt = (t.get("target_types") or "")
            src_str = ""
            tgt_str = ""
            if isinstance(src, str):
                try:
                    src_str = " ".join(json.loads(src)).lower()
                except (json.JSONDecodeError, TypeError):
                    src_str = src.lower()
            elif isinstance(src, list):
                src_str = " ".join(src).lower()
            if isinstance(tgt, str):
                try:
                    tgt_str = " ".join(json.loads(tgt)).lower()
                except (json.JSONDecodeError, TypeError):
                    tgt_str = tgt.lower()
            elif isinstance(tgt, list):
                tgt_str = " ".join(tgt).lower()

            if q in name or q in desc or q in src_str or q in tgt_str:
                matched.append(t)

        return matched

    # ------------------------------------------------------------------
    # Saga tracking
    # ------------------------------------------------------------------

    def create_saga(
        self,
        workspace_id: str,
        name: str,
        steps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a new saga for tracking a multi-step KG operation.

        Args:
            workspace_id: Target workspace.
            name: Human-readable name (e.g. "import_contacts_batch").
            steps: Optional list of step dicts, each with ``name`` and
                ``action`` keys.

        Returns:
            Dict with ``status`` and ``id`` keys.
        """
        now = _now_micros()
        entry_id = _gen_id()

        step_objs: list[SagaStep] = []
        if steps:
            for s in steps:
                step_objs.append(SagaStep(
                    name=s.get("name", ""),
                    action=s.get("action", ""),
                    status="pending",
                    created_at=now,
                ))

        saga = Saga(
            id=entry_id,
            workspace_id=workspace_id,
            name=name,
            steps=step_objs,
            status="active",
            created_at=now,
            updated_at=now,
        )
        storage = saga.to_storage_dict()

        try:
            result = self._call(
                "create_ontology_entry",
                [
                    workspace_id,
                    entry_id,
                    name,
                    json.dumps(storage),
                    "saga",
                    "",
                ],
            )
            if result.get("status") == "ok":
                _ONTO_STORE[entry_id] = storage
            return result
        except Exception:
            _ONTO_STORE[entry_id] = storage
            return {"status": "ok", "id": entry_id}

    def get_saga(self, saga_id: str) -> dict[str, Any] | None:
        """Get a saga by its ID.

        Args:
            saga_id: The saga ID.

        Returns:
            Saga dict, or ``None`` if not found.
        """
        try:
            self._call("get_ontology_entry", [saga_id])
            rows = self._query("ontology_entry", filter_dict={"id": saga_id})
            if rows:
                return rows[0]
        except Exception:
            pass

        entry = _ONTO_STORE.get(saga_id)
        if entry and entry.get("entry_type") == "saga":
            return entry
        return None

    def complete_saga_step(
        self,
        saga_id: str,
        step_name: str,
        result: Any = None,
    ) -> dict[str, Any]:
        """Mark a step within a saga as completed.

        Args:
            saga_id: The saga ID.
            step_name: The name of the step to complete.
            result: Optional result data to store with the step.

        Returns:
            Dict with reducer response status.
        """
        # Update in-memory store
        entry = _ONTO_STORE.get(saga_id)
        if entry is None:
            return {"status": "error", "message": f"Saga '{saga_id}' not found"}

        try:
            saga = Saga.from_storage_dict(entry)
        except Exception:
            return {"status": "error", "message": f"Failed to parse saga '{saga_id}'"}

        now = _now_micros()
        found = False
        for step in saga.steps:
            if step.name == step_name:
                step.status = "completed"
                step.result = result
                step.created_at = now
                found = True
                break

        if not found:
            return {"status": "error", "message": f"Step '{step_name}' not found in saga '{saga_id}'"}

        saga.updated_at = now
        _ONTO_STORE[saga_id] = saga.to_storage_dict()

        try:
            return self._call(
                "update_ontology_entry",
                [saga_id, json.dumps(_ONTO_STORE[saga_id])],
            )
        except Exception:
            return {"status": "ok"}

    def rollback_saga(self, saga_id: str) -> dict[str, Any]:
        """Mark a saga as rolled back.

        Sets the saga status to ``"rolled_back"`` and all pending steps to
        ``"rolled_back"``.

        Args:
            saga_id: The saga ID.

        Returns:
            Dict with reducer response status.
        """
        entry = _ONTO_STORE.get(saga_id)
        if entry is None:
            return {"status": "error", "message": f"Saga '{saga_id}' not found"}

        try:
            saga = Saga.from_storage_dict(entry)
        except Exception:
            return {"status": "error", "message": f"Failed to parse saga '{saga_id}'"}

        now = _now_micros()
        saga.status = "rolled_back"
        for step in saga.steps:
            if step.status == "pending" or step.status == "active":
                step.status = "rolled_back"
        saga.updated_at = now
        _ONTO_STORE[saga_id] = saga.to_storage_dict()

        try:
            return self._call(
                "update_ontology_entry",
                [saga_id, json.dumps(_ONTO_STORE[saga_id])],
            )
        except Exception:
            return {"status": "ok"}

    def list_sagas(
        self,
        workspace_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List sagas in a workspace, optionally filtered by status.

        Args:
            workspace_id: Target workspace.
            status: If set, only return sagas with this status
                (e.g. ``"active"``, ``"completed"``, ``"rolled_back"``).

        Returns:
            List of saga dicts.
        """
        results: list[dict[str, Any]] = []

        try:
            self._call("list_ontology_entries", [workspace_id, "saga"])
            rows = self._sql_param(
                "SELECT * FROM ontology_list_result WHERE "
                "workspace_id = ? AND entry_type = 'saga' "
                "ORDER BY created_at ASC",
                workspace_id,
            )
            results = rows
        except Exception:
            pass

        if not results:
            for entry in _ONTO_STORE.values():
                if (entry.get("workspace_id") == workspace_id
                        and entry.get("entry_type") == "saga"):
                    results.append(entry)

        if status is not None:
            results = [r for r in results if r.get("status") == status]

        return results
