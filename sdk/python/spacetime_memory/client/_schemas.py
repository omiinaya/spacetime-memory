"""Schema definitions for structured search output.

Provides TypedDict schemas and a transformer function (``_apply_return_schema``)
for mapping raw search result dicts into LLM-friendly, predictable shapes.

Usage::

    from spacetime_memory.client._schemas import LLMSearchResult, _apply_return_schema

    # Transform raw results to the compact LLM shape
    llm_ready = _apply_return_schema(raw_results, "llm")

    # Or use a custom TypedDict
    class MyResult(TypedDict):
        id: str
        content: str

    filtered = _apply_return_schema(raw_results, MyResult)
"""

from __future__ import annotations

from typing import Any, TypedDict, get_type_hints

# ---------------------------------------------------------------------------
# Built-in schemas
# ---------------------------------------------------------------------------


class LLMSearchResult(TypedDict):
    """Compact, LLM-friendly search result.

    All fields renamed with clear, consistent names so an LLM can
    immediately understand the shape.  ``relevance`` is a 0.0–1.0 fused
    score; ``type`` discriminates entity kinds (memory, note, node, etc.).

    Example dict returned when ``search(return_schema="llm")`` is
    used::

        {
            "id": "00000123-4567-89ab-cdef-123456789abc",
            "content": "Reinforcement learning from human feedback (RLHF)...",
            "relevance": 0.87,
            "type": "memory",
            "snippet": "Reinforcement learning from human feedback (RLHF)...",
            "created_at": 1712345678.0,
        }
    """

    id: str
    """Unique entity identifier (entity_id / memory_id / note_id)."""

    content: str
    """Full text content (memory_content, content, description, or summary)."""

    relevance: float
    """Fused relevance score in 0.0–1.0 range."""

    type: str
    """Entity type discriminator (memory, note, node, session, etc.)."""

    snippet: str
    """Short content preview (~200 chars), useful for previews."""

    created_at: float
    """Unix timestamp of creation date."""


# ---------------------------------------------------------------------------
# Field resolution
# ---------------------------------------------------------------------------

# Map: schema field name -> list of possible source keys (in priority order)
_FIELD_ALIASES: dict[str, list[str]] = {
    "id": ["entity_id", "memory_id", "note_id", "node_id", "id", "session_id"],
    "content": [
        "memory_content",
        "content",
        "text",
        "description",
        "summary",
        "body",
    ],
    "relevance": ["fused_score", "score", "relevance", "relevance_score"],
    "score": ["fused_score", "score", "relevance", "relevance_score"],
    "type": ["entity_type", "memory_type", "type", "doc_type", "node_type"],
    "entity_type": ["entity_type", "memory_type", "type", "doc_type", "node_type"],
    "created_at": ["created_at", "timestamp_", "updated_at", "modified_at"],
    "updated_at": ["updated_at", "modified_at", "created_at"],
    "timestamp": ["created_at", "timestamp_", "updated_at", "modified_at"],
    "snippet": ["snippet", "summary", "preview", "abstract", "content"],
    "title": ["title", "name", "label", "heading", "memory_type"],
    "name": ["name", "label", "title"],
    "workspace": ["workspace_id", "workspace"],
    "workspace_id": ["workspace_id", "workspace"],
    "memory_type": ["memory_type", "entity_type", "type", "doc_type"],
    "entity_id": ["entity_id", "memory_id", "note_id", "node_id", "id"],
}


def _resolve_field(row: dict[str, Any], field: str) -> Any:
    """Resolve a single schema *field* from a raw result *row*.

    Tries in order:
    1. Exact key match in *row*.
    2. Known aliases from ``_FIELD_ALIASES``.
    3. Case-insensitive fallback across all keys.

    Returns ``None`` when no match is found.
    """
    # 1. Direct match
    if field in row and row[field] is not None:
        return row[field]

    # 2. Alias lookup
    aliases = _FIELD_ALIASES.get(field, [])
    for alias in aliases:
        if alias in row and row[alias] is not None and row[alias] != "":
            return row[alias]

    # 3. Case-insensitive fallback
    field_lower = field.lower()
    for key, val in row.items():
        if key.lower() == field_lower and val is not None:
            return val

    return None


# ---------------------------------------------------------------------------
# Public transformer
# ---------------------------------------------------------------------------


def _apply_return_schema(
    results: list[dict[str, Any]],
    schema: Any,
) -> list[dict[str, Any]]:
    """Transform *results* to match the requested *schema*.

    Args:
        results:
            Raw result dicts from ``search()`` or any other method that
            returns ``list[dict[str, Any]]``.
        schema:
            One of:

            * ``None`` — returns *results* unchanged (no-op).
            * ``"llm"`` — returns a ``list[LLMSearchResult]`` with only
              the six compact fields (id, content, relevance, type,
              snippet, created_at).
            * A ``TypedDict`` class — returns ``list[dict]`` with only
              the annotated fields from that TypedDict.  Field values
              are resolved via ``_resolve_field`` (exact match → alias
              → case-insensitive).

    Returns:
        Transformed results matching the requested schema.
        If *schema* is unrecognised, returns *results* unchanged.
    """
    if schema is None or not results:
        return results

    # ── Resolve schema class ──
    if schema == "llm":
        schema_cls: type = LLMSearchResult
    elif isinstance(schema, type) and hasattr(schema, "__annotations__"):
        schema_cls = schema  # e.g. a TypedDict subclass
    else:
        # Unknown schema type — return as-is
        return results

    # Introspect annotated fields
    hints = get_type_hints(schema_cls, globalns=globals())
    fields: list[str] = list(hints.keys())

    transformed: list[dict[str, Any]] = []
    for row in results:
        new_row: dict[str, Any] = {}
        for field in fields:
            new_row[field] = _resolve_field(row, field)
        # Special handling: ensure relevance is a float for LLM schema
        if schema == "llm":
            r = new_row.get("relevance")
            if r is not None:
                new_row["relevance"] = float(r) if not isinstance(r, float) else r
            else:
                new_row["relevance"] = 0.0
        transformed.append(new_row)

    return transformed
