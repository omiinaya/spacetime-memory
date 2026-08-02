"""Data types matching Graphiti's core models.

All data classes from the graphiti adapter, split out for the package
structure.  Re-exported from ``__init__.py``.
"""

from __future__ import annotations

import dataclasses
import json
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Self


@dataclass
class EntityNode:
    """Knowledge graph entity node.

    Maps to SpacetimeDB ``kg_node`` table.  ``name`` is indexed
    for semantic search via the embedder.
    """

    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])
    name: str = ""
    name_embedding: list[float] | None = None
    summary: str = ""
    group_id: str = "default"
    labels: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def from_stmem(cls: type[EntityNode], row: dict[str, Any]) -> EntityNode:
        """Build from a SpacetimeDB ``kg_node`` row."""
        attrs = {}
        raw = row.get("metadata_json", "{}")
        if raw and raw != "{}":
            try:
                attrs = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                pass  # corrupt attribute data — skip this entry gracefully
        labels_raw = row.get("labels", "")
        labels = json.loads(labels_raw) if isinstance(labels_raw, str) and labels_raw else []
        created = row.get("created_at", 0)
        return cls(
            uuid=row.get("id", ""),
            name=row.get("label", ""),
            summary=row.get("summary", ""),
            group_id=row.get("workspace_id", "default"),
            labels=labels,
            attributes=attrs,
            created_at=datetime.fromtimestamp(created / 1_000_000, tz=UTC)
            if created and created > 1e12
            else datetime.fromtimestamp(created, tz=UTC)
            if created
            else datetime.now(UTC),
        )

    def model_dump(self, **kwargs) -> dict:
        """Serialize to a plain dict (Pydantic compatibility)."""
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}

    @classmethod
    def model_validate(cls: type[Self], data: dict) -> Self:
        """Create instance from a dict (Pydantic compatibility)."""
        return cls(
            **{k: v for k, v in data.items() if k in [f.name for f in dataclasses.fields(cls)]}
        )


@dataclass
class EntityEdge:
    """Knowledge graph directed edge between two entity nodes.

    Maps to SpacetimeDB ``kg_edge`` table.  ``fact`` contains the
    natural-language description of the relationship.

    Supports temporal versioning (Graphiti parity): when an edge is
    updated, the old version is invalidated (``invalid_at`` set) and
    a new version is created with incremented ``version`` and the
    same ``edge_group_id``.
    """

    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])
    name: str = ""
    fact: str = ""
    fact_embedding: list[float] | None = None
    source_node_uuid: str = ""
    target_node_uuid: str = ""
    group_id: str = "default"
    episodes: list[str] = field(default_factory=list)
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    expired_at: datetime | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Temporal versioning (Graphiti parity)
    version: int = 1
    edge_group_id: str = ""
    reference_time: datetime | None = None

    @classmethod
    def from_stmem(cls: type[EntityEdge], row: dict[str, Any]) -> EntityEdge:
        """Build from a SpacetimeDB ``kg_edge`` row."""
        attrs = {}
        raw = row.get("metadata_json", "{}")
        if raw and raw != "{}":
            try:
                attrs = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                pass  # corrupt attribute data — skip this entry gracefully
        created = row.get("created_at", 0)
        valid = row.get("valid_at", 0)
        invalid = row.get("invalid_at", 0)
        return cls(
            uuid=row.get("id", ""),
            name=row.get("relation", ""),
            fact=row.get("fact", row.get("relation", "")),
            source_node_uuid=row.get("source_node_id", ""),
            target_node_uuid=row.get("target_node_id", ""),
            group_id=row.get("workspace_id", "default"),
            attributes=attrs,
            created_at=datetime.fromtimestamp(created / 1_000_000, tz=UTC)
            if created and created > 1e12
            else datetime.fromtimestamp(created, tz=UTC)
            if created
            else datetime.now(UTC),
            valid_at=datetime.fromtimestamp(valid / 1_000_000, tz=UTC)
            if valid and valid > 1e12
            else datetime.fromtimestamp(valid, tz=UTC)
            if valid
            else None,
            invalid_at=datetime.fromtimestamp(invalid / 1_000_000, tz=UTC)
            if invalid and invalid > 1e12
            else datetime.fromtimestamp(invalid, tz=UTC)
            if invalid
            else None,
            version=row.get("version", 1),
            edge_group_id=row.get("edge_group_id", ""),
        )

    def model_dump(self, **kwargs) -> dict:
        """Serialize to a plain dict (Pydantic compatibility)."""
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}

    @classmethod
    def model_validate(cls: type[Self], data: dict) -> Self:
        """Create instance from a dict (Pydantic compatibility)."""
        return cls(
            **{k: v for k, v in data.items() if k in [f.name for f in dataclasses.fields(cls)]}
        )


@dataclass
class EpisodicNode:
    """An episode (text input that generated graph entities).

    Maps to SpacetimeDB ``memory`` table.
    """

    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])
    name: str = ""
    content: str = ""
    source: str = "message"
    source_description: str = ""
    group_id: str = "default"
    labels: list[str] = field(default_factory=list)
    episode_metadata: dict[str, Any] = field(default_factory=dict)
    entity_edges: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    valid_at: datetime | None = None

    def model_dump(self, **kwargs) -> dict:
        """Serialize to a plain dict (Pydantic compatibility)."""
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}

    @classmethod
    def model_validate(cls: type[Self], data: dict) -> Self:
        """Create instance from a dict (Pydantic compatibility)."""
        return cls(
            **{k: v for k, v in data.items() if k in [f.name for f in dataclasses.fields(cls)]}
        )


@dataclass
class CommunityNode:
    """Community node (result from community detection)."""

    uuid: str = ""
    name: str = ""
    group_id: str = "default"
    summary: str = ""
    labels: list[str] = field(default_factory=list)
    name_embedding: list[float] | None = None
    member_uuids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def model_dump(self, **kwargs) -> dict:
        """Serialize to a plain dict (Pydantic compatibility)."""
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}

    @classmethod
    def model_validate(cls: type[Self], data: dict) -> Self:
        """Create instance from a dict (Pydantic compatibility)."""
        return cls(
            **{k: v for k, v in data.items() if k in [f.name for f in dataclasses.fields(cls)]}
        )


@dataclass
class CommunityEdge:
    """Edge connecting communities to entities."""

    uuid: str = ""
    source_node_uuid: str = ""
    target_node_uuid: str = ""
    group_id: str = "default"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class EpisodicEdge:
    """Edge from an episode to an entity it mentions (MENTIONS relationship)."""

    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])
    source_node_uuid: str = ""
    target_node_uuid: str = ""
    group_id: str = "default"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class HasEpisodeEdge:
    """Edge from a saga to an episode (HAS_EPISODE relationship)."""

    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])
    source_node_uuid: str = ""
    target_node_uuid: str = ""
    group_id: str = "default"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class NextEpisodeEdge:
    """Edge linking consecutive episodes (NEXT_EPISODE relationship)."""

    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])
    source_node_uuid: str = ""
    target_node_uuid: str = ""
    group_id: str = "default"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class SagaNode:
    """An episode saga — a named, summarised group of episodes.

    Maps to SpacetimeDB ``kg_node`` with ``node_type="saga"``.
    """

    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])
    name: str = ""
    group_id: str = "default"
    labels: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    summary: str = ""
    first_episode_uuid: str | None = None
    last_episode_uuid: str | None = None
    last_summarized_at: datetime | None = None
    last_summarized_episode_valid_at: datetime | None = None

    def model_dump(self, **kwargs) -> dict:
        """Serialize to a plain dict (Pydantic compatibility)."""
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}

    @classmethod
    def model_validate(cls: type[Self], data: dict) -> Self:
        """Create instance from a dict (Pydantic compatibility)."""
        return cls(
            **{k: v for k, v in data.items() if k in [f.name for f in dataclasses.fields(cls)]}
        )


@dataclass
class SearchResults:
    """Results from an advanced search (``search_``)."""

    edges: list[EntityEdge] = field(default_factory=list)
    nodes: list[EntityNode] = field(default_factory=list)


@dataclass
class AddBulkEpisodeResults:
    """Results from a bulk ``add_episode`` operation."""

    episodes: list[EpisodicNode] = field(default_factory=list)
    episodic_edges: list[Any] = field(default_factory=list)
    nodes: list[EntityNode] = field(default_factory=list)
    edges: list[EntityEdge] = field(default_factory=list)
    communities: list[CommunityNode] = field(default_factory=list)
    community_edges: list[CommunityEdge] = field(default_factory=list)


@dataclass
class AddEpisodeResults:
    """Results from ``add_episode``."""

    episode: EpisodicNode | None = None
    episodic_edges: list[Any] = field(default_factory=list)
    nodes: list[EntityNode] = field(default_factory=list)
    edges: list[EntityEdge] = field(default_factory=list)
    communities: list[CommunityNode] = field(default_factory=list)
    community_edges: list[CommunityEdge] = field(default_factory=list)


@dataclass
class RawEpisode:
    """Raw episode data before processing (forward compat)."""

    name: str = ""
    content: str = ""
    source: str = "message"
    source_description: str = ""
    reference_time: datetime | None = None
    uuid: str = field(default_factory=lambda: _uuid.uuid4().hex[:32])


@dataclass
class AddTripletResults:
    """Results from ``add_triplet``."""

    nodes: list[EntityNode] = field(default_factory=list)
    edges: list[EntityEdge] = field(default_factory=list)
