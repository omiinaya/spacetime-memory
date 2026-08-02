"""zep_cloud.external_clients.ontology — EntityModel for the harness ontology."""

from pydantic import BaseModel


class EntityModel(BaseModel):
    """Base class for ontology entity definitions (harness compatibility)."""

    pass


__all__ = ["EntityModel"]
