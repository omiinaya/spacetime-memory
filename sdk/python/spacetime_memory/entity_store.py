"""Mem0 .entity_store parity for spacetime-memory.

Extracts, stores, and manages entities from unstructured text as
knowledge-graph nodes.  Provides both standalone functions and an
``EntityStore`` class that wraps them into a cohesive API.

Design follows Mem0's entity_store pattern:
  - ``extract_entities``  – named-entity extraction (LLM or heuristic)
  - ``store_entities``    – persist extracted entities as KG nodes
  - ``search_entities``   – find stored entities by label/summary
  - ``get_entity_graph``  – neighbourhood graph around an entity
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Entity type mapping  (same mapping used in entity_linking.py)
# ---------------------------------------------------------------------------
_TYPE_MAP: dict[str, str] = {
    "person": "entity",
    "pet": "entity",
    "book": "entity",
    "place": "entity",
    "event": "entity",
    "activity": "entity",
    "organization": "entity",
    "concept": "concept",
    "other": "entity",
    "technology": "concept",
    "acronym": "concept",
    "code": "code",
    "document": "document",
    "topic": "topic",
    "entity": "entity",
}

# ---------------------------------------------------------------------------
# 1.  extract_entities
# ---------------------------------------------------------------------------

_DEFAULT_EXTRACT_PROMPT = (
    "Extract ALL named entities from the following text as a JSON array.\n\n"
    'Return ONLY valid JSON array. Each item: {{"name": "...", "entity_type": "...", "description": "..."}}\n\n'
    "Entity types: person, pet, book, place, event, activity, organization, concept, technology, other\n\n"
    "Rules:\n"
    "- Extract EVERY named entity you find\n"
    "- Use short, descriptive summaries\n\n"
    "Text: {text}\n\n"
    "JSON array:"
)


def _extract_entities_heuristic(text: str) -> list[dict[str, Any]]:
    """Simple regex-based entity extraction as fallback.

    Extracts:
    - Capitalised multi-word phrases (potential people / organisations)
    - Quoted strings (potential book titles, song names)
    - URLs, email addresses
    - Hashtags
    """
    seen: set[str] = set()
    entities: list[dict[str, Any]] = []

    # Quoted strings  (book titles, song names, etc.)
    for match in re.finditer(r'"([^"]{2,80})"', text):
        name = match.group(1).strip()
        if name.lower() not in seen:
            seen.add(name.lower())
            entities.append(
                {"name": name, "entity_type": "other", "description": ""}
            )

    # Hashtags
    for match in re.finditer(r'#(\w{2,})', text):
        name = match.group(1)
        if name.lower() not in seen:
            seen.add(name.lower())
            entities.append(
                {"name": name, "entity_type": "concept", "description": ""}
            )

    # Capitalised multi-word phrases (3+ words, each capitalised)
    for match in re.finditer(
        r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){2,})\b', text
    ):
        name = match.group(1).strip()
        if name.lower() not in seen:
            seen.add(name.lower())
            entities.append(
                {
                    "name": name,
                    "entity_type": "organization",
                    "description": "",
                }
            )

    # URLs
    for match in re.finditer(r'https?://[^\s,;)]+', text):
        name = match.group(0).strip()
        if name.lower() not in seen:
            seen.add(name.lower())
            entities.append(
                {"name": name, "entity_type": "other", "description": ""}
            )

    return entities


def _extract_entities_llm(
    text: str,
    llm_func: Callable[[str], str] | None = None,
) -> list[dict[str, Any]] | None:
    """Extract entities via an LLM callable.

    The callable receives a prompt and must return a response string
    (presumably containing a JSON array of entities).  Returns ``None``
    when no LLM is available or parsing fails.
    """
    if llm_func is None:
        return None

    prompt = _DEFAULT_EXTRACT_PROMPT.format(text=text[:4000])
    try:
        raw = llm_func(prompt)
    except Exception as exc:
        logger.warning("entity_store: LLM extraction failed: %s", exc)
        return None

    if not raw or not raw.strip():
        return None

    # Strip markdown code fences
    import json

    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("entity_store: LLM returned invalid JSON: %r", raw[:200])
        return None

    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        entities = (
            result.get("entities")
            or result.get("items")
            or result.get("entity_list")
            or []
        )
        if isinstance(entities, list):
            return entities
    return []


def extract_entities(
    text: str,
    llm_func: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """Extract named entities from unstructured *text*.

    Parameters
    ----------
    text:
        The source text to analyse.
    llm_func:
        Optional callable that takes a prompt string and returns a
        response.  When provided it is used as the primary extractor;
        when ``None`` (or if the LLM call fails) a heuristic regex
        fallback is used.

    Returns
    -------
    List of entity dicts with keys ``name``, ``entity_type``,
    ``description``.
    """
    entities = _extract_entities_llm(text, llm_func)
    if entities is not None:
        return entities
    return _extract_entities_heuristic(text)


# ---------------------------------------------------------------------------
# 2.  store_entities
# ---------------------------------------------------------------------------


def store_entities(
    client: Any,
    workspace_id: str,
    entities: list[dict[str, Any]],
    *,
    source_memory_id: str = "",
    skip_existing: bool = True,
) -> list[dict[str, Any]]:
    """Store extracted *entities* as knowledge-graph nodes.

    Each entity dict must have at least a ``"name"`` key.  Entities
    whose label already exists in the workspace KG are skipped when
    *skip_existing* is ``True`` (the default).

    Parameters
    ----------
    client:
        Spacetime Memory client instance.
    workspace_id:
        Target workspace identifier.
    entities:
        List of entity dicts (as returned by :func:`extract_entities`).
    source_memory_id:
        Optional memory ID to associate with the created nodes.
    skip_existing:
        When ``True`` (default), nodes whose label already exists are
        skipped instead of raising an error.

    Returns
    -------
    List of created node dicts (empty if all were skipped).
    """
    created: list[dict[str, Any]] = []
    for ent in entities:
        name = (ent.get("name") or "").strip()
        if not name:
            continue

        entity_type = (ent.get("entity_type") or "entity").lower()
        node_type = _TYPE_MAP.get(entity_type, "entity")

        # Skip if existing node with same label
        if skip_existing:
            existing = client._query(
                "kg_node",
                workspace_id=workspace_id,
                filter_dict={"label": name},
                columns=["id", "label"],
            )
            if existing:
                logger.debug(
                    "entity_store: skipping existing node '%s'", name
                )
                continue

        description = ent.get("description") or ""
        summary = (
            description[:200]
            if description
            else f"{entity_type}: {name}"
        )

        try:
            node = client.create_node(
                workspace_id=workspace_id,
                label=name,
                node_type=node_type,
                summary=summary,
                source_memory_id=source_memory_id,
            )
            created.append(node)
        except RuntimeError as exc:
            logger.debug(
                "entity_store: create_node failed for '%s': %s", name, exc
            )
            continue

    return created


# ---------------------------------------------------------------------------
# 3.  search_entities
# ---------------------------------------------------------------------------


def search_entities(
    client: Any,
    workspace_id: str,
    query: str,
    type: str | None = None,
) -> list[dict[str, Any]]:
    """Search stored entities by label / summary within a workspace.

    Parameters
    ----------
    client:
        Spacetime Memory client instance.
    workspace_id:
        Target workspace identifier.
    query:
        Search string (case-insensitive substring match against label
        and summary).
    type:
        Optional node type filter (e.g. ``"entity"``, ``"concept"``).

    Returns
    -------
    List of matching node dicts (each with ``id``, ``label``,
    ``node_type``, ``summary``, etc.).
    """
    # Fetch all KG nodes  (client-side filter since STDB lacks LIKE)
    try:
        nodes = client._query(
            "kg_node",
            workspace_id=workspace_id,
            columns=["id", "label", "node_type", "summary"],
        )
    except RuntimeError:
        logger.warning("entity_store: failed to query kg_node")
        return []

    if not nodes:
        return []

    q = query.lower().strip()
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for node in nodes:
        nid = node.get("id", "")
        if not nid or nid in seen_ids:
            continue

        # Optional type filter
        if type is not None:
            node_t = (node.get("node_type") or "").lower()
            if node_t != type.lower():
                continue

        label = (node.get("label") or "").lower()
        summary = (node.get("summary") or "").lower()

        if q in label or q in summary:
            seen_ids.add(nid)
            results.append(node)

    return results


# ---------------------------------------------------------------------------
# 4.  get_entity_graph
# ---------------------------------------------------------------------------


def get_entity_graph(
    client: Any,
    workspace_id: str,
    entity_id: str,
) -> dict[str, Any]:
    """Get the sub-graph centred on *entity_id*.

    Returns the entity node itself plus every edge incident to it, along
    with the nodes at the other end of those edges (the "neighbourhood").

    Parameters
    ----------
    client:
        Spacetime Memory client instance.
    workspace_id:
        Target workspace identifier.
    entity_id:
        Knowledge-graph node ID of the entity.

    Returns
    -------
    A dict with keys:
      - ``"node"``        – the entity's own node dict (or ``None``)
      - ``"edges"``       – list of edge dicts
      - ``"neighbors"``   – list of neighbour node dicts
    """
    result: dict[str, Any] = {
        "node": None,
        "edges": [],
        "neighbors": [],
    }

    # 1. Fetch the entity node
    try:
        node_rows = client._query(
            "kg_node",
            workspace_id=workspace_id,
            filter_dict={"id": entity_id},
        )
        if node_rows:
            result["node"] = node_rows[0]
        else:
            logger.warning(
                "entity_store: entity %s not found in workspace %s",
                entity_id,
                workspace_id,
            )
            return result
    except RuntimeError as exc:
        logger.warning(
            "entity_store: failed to fetch node %s: %s", entity_id, exc
        )
        return result

    # 2. Fetch edges  (using the client's built-in get_neighbors)
    try:
        edges = client.get_neighbors(
            node_id=entity_id, workspace_id=workspace_id
        )
    except RuntimeError as exc:
        logger.warning(
            "entity_store: get_neighbors failed for %s: %s",
            entity_id,
            exc,
        )
        return result

    result["edges"] = edges

    # 3. Collect neighbour node IDs and deduplicate
    neighbor_ids: set[str] = set()
    for edge in edges:
        src = edge.get("source_node_id") or ""
        tgt = edge.get("target_node_id") or ""
        if src == entity_id and tgt:
            neighbor_ids.add(tgt)
        elif tgt == entity_id and src:
            neighbor_ids.add(src)

    # 4. Fetch neighbour node details
    for nid in neighbor_ids:
        try:
            rows = client._query(
                "kg_node",
                workspace_id=workspace_id,
                filter_dict={"id": nid},
                columns=["id", "label", "node_type", "summary"],
            )
            if rows:
                result["neighbors"].append(rows[0])
        except RuntimeError:
            continue

    return result


# ---------------------------------------------------------------------------
# 5.  EntityStore  (cohesive class API)
# ---------------------------------------------------------------------------


class EntityStore:
    """Cohesive entity store API (Mem0 .entity_store parity).

    Wraps the standalone functions into a stateful class that holds a
    client reference and a workspace ID so you don't have to pass them
    on every call.

    Parameters
    ----------
    client:
        Spacetime Memory client instance.
    workspace_id:
        Default workspace identifier.
    llm_func:
        Optional LLM callable used by :meth:`extract_entities`.
    """

    def __init__(
        self,
        client: Any,
        workspace_id: str,
        llm_func: Callable[[str], str] | None = None,
    ) -> None:
        self.client = client
        self.workspace_id = workspace_id
        self.llm_func = llm_func

    # -- Convenience shortcuts that auto-inject client + workspace_id -------

    def extract_entities(
        self,
        text: str,
        llm_func: Callable[[str], str] | None = None,
    ) -> list[dict[str, Any]]:
        """Extract named entities from *text*.

        Uses the instance's ``llm_func`` when *llm_func* is not
        explicitly passed.
        """
        return extract_entities(
            text, llm_func=llm_func if llm_func is not None else self.llm_func
        )

    def store_entities(
        self,
        entities: list[dict[str, Any]],
        *,
        source_memory_id: str = "",
        skip_existing: bool = True,
    ) -> list[dict[str, Any]]:
        """Store extracted entities as KG nodes."""
        return store_entities(
            self.client,
            self.workspace_id,
            entities,
            source_memory_id=source_memory_id,
            skip_existing=skip_existing,
        )

    def search_entities(
        self,
        query: str,
        type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search stored entities by label / summary."""
        return search_entities(self.client, self.workspace_id, query, type=type)

    def get_entity_graph(
        self,
        entity_id: str,
    ) -> dict[str, Any]:
        """Get the sub-graph centred on *entity_id*."""
        return get_entity_graph(self.client, self.workspace_id, entity_id)

    # -- Convenience: extract + store in one call --------------------------

    def extract_and_store(
        self,
        text: str,
        *,
        source_memory_id: str = "",
        skip_existing: bool = True,
        llm_func: Callable[[str], str] | None = None,
    ) -> dict[str, Any]:
        """Extract entities from *text* and immediately store them.

        Returns a dict with ``"entities"`` (the extracted list) and
        ``"stored"`` (the created KG node list).
        """
        entities = self.extract_entities(text, llm_func=llm_func)
        stored = self.store_entities(
            entities,
            source_memory_id=source_memory_id,
            skip_existing=skip_existing,
        )
        return {"entities": entities, "stored": stored}
