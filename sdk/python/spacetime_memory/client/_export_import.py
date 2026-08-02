"""Export/Import mixin — client-side orchestration for data portability.

Provides:
  - ``export_memories`` — export workspace memories to JSON, markdown, or CSV
  - ``import_memories`` — import memories with merge/replace/skip strategy
  - ``export_workspace`` — full workspace export (memories + KG + notes + profiles)
  - ``import_workspace`` — full workspace import (all domains)

All data is read via existing ``_query()`` calls and imported via existing
reducer calls (``store_memory``, ``create_node``, ``create_edge``,
``create_note``, etc.).  No new STDB reducers are introduced — this is a
pure client-side orchestration layer.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any

from ._base import _tracing_span, logger

# Export format field ordering — consistent column order for CSV
_MEMORY_CSV_FIELDS = [
    "id", "workspace_id", "peer_id", "memory_type", "content",
    "summary", "entities_json", "confidence", "tier",
    "created_at", "updated_at",
]
_KG_NODE_CSV_FIELDS = [
    "id", "workspace_id", "label", "node_type", "summary",
    "metadata_json", "created_at",
]
_KG_EDGE_CSV_FIELDS = [
    "id", "workspace_id", "source_node_id", "target_node_id",
    "relation", "weight", "confidence", "created_at",
]
_NOTE_CSV_FIELDS = [
    "id", "workspace_id", "title", "content", "embed",
    "tags_json", "created_at", "updated_at",
]
_PROFILE_CSV_FIELDS = [
    "peer_id", "static_facts_json", "dynamic_context_json",
    "preferences_json", "tags_json",
]


class ExportImportMixin:
    """Spacetime-Memory export/import mixin.

    Provides client-side orchestration for exporting and importing
    workspace data across all supported domains (memories, knowledge
    graph, notes, profiles).

    Inherits from ClientBase for connection infrastructure.
    """

    # -------------------------------------------------------------------
    # Export — memories
    # -------------------------------------------------------------------

    def export_memories(
        self,
        workspace_id: str,
        fmt: str = "json",
        filters: dict[str, Any] | None = None,
    ) -> str:
        """Export all memories for a workspace.

        Args:
            workspace_id: Target workspace.
            fmt: Output format — ``"json"`` (default), ``"markdown"``,
                or ``"csv"``.
            filters: Optional dict of field → value to filter by
                (applied client-side after query).

        Returns:
            Serialised export data as a string (JSON array, CSV text,
            or concatenated markdown).

        Raises:
            ValueError: On unknown format.
        """
        with _tracing_span(
            "export_memories", workspace_id=workspace_id, fmt=fmt
        ):
            memories = self._query("memory", workspace_id=workspace_id)
            if filters:
                memories = self._apply_filters(memories, filters)

            if fmt == "json":
                return json.dumps(memories, indent=2, default=str)
            elif fmt == "csv":
                return self._dicts_to_csv(memories, _MEMORY_CSV_FIELDS)
            elif fmt == "markdown":
                return self._memories_to_markdown(memories)
            else:
                raise ValueError(
                    f"Unknown export format '{fmt}'. "
                    "Supported: json, csv, markdown."
                )

    # -------------------------------------------------------------------
    # Import — memories
    # -------------------------------------------------------------------

    def import_memories(
        self,
        workspace_id: str,
        data: str,
        fmt: str = "json",
        strategy: str = "merge",
    ) -> dict[str, Any]:
        """Import memories into a workspace.

        Args:
            workspace_id: Target workspace.
            data: Serialised memory data (JSON array string, CSV text,
                or markdown text — depends on ``fmt``).
            fmt: Input format — ``"json"`` (default), ``"csv"``,
                or ``"markdown"``.
            strategy: Conflict strategy — one of:
                - ``"merge"`` (default): keep existing, add new
                - ``"replace"``: overwrite existing with imported
                - ``"skip"``: skip entries that already exist

        Returns:
            Dict with keys: ``imported`` (count), ``skipped`` (count),
            ``errors`` (list of error messages).

        Raises:
            ValueError: On unknown format or strategy.
            json.JSONDecodeError: On invalid JSON input.
        """
        if strategy not in ("merge", "replace", "skip"):
            raise ValueError(
                f"Unknown strategy '{strategy}'. "
                "Supported: merge, replace, skip."
            )

        with _tracing_span(
            "import_memories",
            workspace_id=workspace_id,
            fmt=fmt,
            strategy=strategy,
        ):
            # Parse input
            records = self._parse_memory_input(data, fmt)

            # Validate data
            for i, rec in enumerate(records):
                if not isinstance(rec, dict):
                    raise ValueError(f"Item {i}: expected dict, got {type(rec).__name__}")
                if "content" not in rec or not rec["content"]:
                    raise ValueError(f"Item {i}: missing required field 'content'")

            # Fetch existing memories for conflict detection
            existing = self._query("memory", workspace_id=workspace_id)
            existing_content_map: dict[str, list[dict[str, Any]]] = {}
            for m in existing:
                key = m.get("content", "")
                existing_content_map.setdefault(key, []).append(m)

            imported = 0
            skipped = 0
            errors: list[str] = []

            for i, rec in enumerate(records):
                try:
                    content = rec.get("content", "")
                    # Check conflict
                    dup = existing_content_map.get(content, [])
                    # Also check if we already imported this content in this batch
                    already_imported = any(
                        r.get("_imported")
                        for r in dup
                    )
                    if dup or already_imported:
                        if strategy == "skip":
                            skipped += 1
                            continue
                        elif strategy == "replace":
                            # Delete existing, then re-import
                            for m in dup:
                                try:
                                    self._call("delete_memory", [m["id"]])
                                except Exception as e:
                                    logger.warning(
                                        "import_memories: failed to delete memory %s: %s",
                                        m.get("id"), e,
                                    )
                        # strategy == "merge": keep existing, skip
                        else:  # merge
                            skipped += 1
                            continue

                    # Call store_memory reducer
                    self._call("store_memory", [
                        workspace_id,
                        rec.get("peer_id", ""),
                        rec.get("observer_id", ""),
                        rec.get("memory_type", "experience"),
                        content,
                        rec.get("summary", content[:200]),
                        rec.get("entities_json", "[]"),
                        rec.get("confidence", 0.8),
                        rec.get("source_session_id", ""),
                        rec.get("source_message_id", ""),
                        rec.get("images_json", ""),
                    ])
                    imported += 1
                    # Track this content as imported
                    rec["_imported"] = True

                except Exception as e:
                    errors.append(f"Item {i}: {e}")
                    logger.warning("import_memories: item %d failed: %s", i, e)

            return {
                "imported": imported,
                "skipped": skipped,
                "errors": errors,
            }

    # -------------------------------------------------------------------
    # Export — full workspace
    # -------------------------------------------------------------------

    def export_workspace_bundle(
        self,
        workspace_id: str,
        include: list[str] | None = None,
    ) -> str:
        """Export a full workspace as a JSON bundle.

        Note: named ``export_workspace_bundle`` to avoid colliding with
        the existing ``WorkspaceMixin.export_workspace()`` which exports
        notes as markdown only.

        Args:
            workspace_id: Target workspace.
            include: List of domains to include. Defaults to all:
                ``["memories", "kg", "notes", "profiles"]``.
                Sub-options:
                - ``"memories"`` — memory records
                - ``"kg"`` — KG nodes + KG edges
                - ``"notes"`` — wiki notes
                - ``"profiles"`` — peer profiles

        Returns:
            JSON string with a top-level object containing each domain
            as a key mapping to its data array.  Metadata keys:
            ``_exported_at``, ``_workspace_id``, ``_version``.
        """
        if include is None:
            include = ["memories", "kg", "notes", "profiles"]

        valid_domains = {"memories", "kg", "notes", "profiles"}
        unknown = set(include) - valid_domains
        if unknown:
            raise ValueError(
                f"Unknown domain(s): {', '.join(unknown)}. "
                f"Valid: {', '.join(sorted(valid_domains))}."
            )

        with _tracing_span(
            "export_workspace_bundle", workspace_id=workspace_id, domains=",".join(include)
        ):
            bundle: dict[str, Any] = {
                "_exported_at": datetime.now(UTC).isoformat(),
                "_workspace_id": workspace_id,
                "_version": "1.0",
            }

            if "memories" in include:
                bundle["memories"] = self._query("memory", workspace_id=workspace_id)

            if "kg" in include:
                bundle["kg_nodes"] = self._query("kg_node", workspace_id=workspace_id)
                bundle["kg_edges"] = self._query("kg_edge", workspace_id=workspace_id)

            if "notes" in include:
                bundle["notes"] = self._query("note", workspace_id=workspace_id)

            if "profiles" in include:
                bundle["profiles"] = self._query("profile", workspace_id=workspace_id)

            return json.dumps(bundle, indent=2, default=str)

    # -------------------------------------------------------------------
    # Import — full workspace
    # -------------------------------------------------------------------

    def import_workspace(
        self,
        workspace_id: str,
        data: str,
        strategy: str = "merge",
    ) -> dict[str, Any]:
        """Import a full workspace from a JSON bundle created by
        ``export_workspace_bundle()``.

        Args:
            workspace_id: Target workspace (may differ from the original).
            data: The JSON bundle string produced by ``export_workspace()``.
            strategy: Conflict strategy — ``"merge"`` (default),
                ``"replace"``, or ``"skip"``.  Applied per record
                across all domains.

        Returns:
            Dict with per-domain counts: ``memories``, ``kg``, ``notes``,
            ``profiles``, and ``errors`` (list of error messages).
        """
        if strategy not in ("merge", "replace", "skip"):
            raise ValueError(
                f"Unknown strategy '{strategy}'. "
                "Supported: merge, replace, skip."
            )

        with _tracing_span(
            "import_workspace", workspace_id=workspace_id, strategy=strategy
        ):
            bundle = json.loads(data)

            results: dict[str, Any] = {
                "memories": {"imported": 0, "skipped": 0},
                "kg_nodes": {"imported": 0, "skipped": 0},
                "kg_edges": {"imported": 0, "skipped": 0},
                "notes": {"imported": 0, "skipped": 0},
                "profiles": {"imported": 0, "skipped": 0},
                "errors": [],
            }

            # Import memories
            if "memories" in bundle:
                mem_data = json.dumps(bundle["memories"])
                mem_result = self.import_memories(
                    workspace_id, mem_data, fmt="json", strategy=strategy,
                )
                results["memories"]["imported"] = mem_result.get("imported", 0)
                results["memories"]["skipped"] = mem_result.get("skipped", 0)
                results["errors"].extend(
                    f"memories: {e}" for e in mem_result.get("errors", [])
                )

            # Import KG nodes
            if "kg_nodes" in bundle:
                for i, node in enumerate(bundle["kg_nodes"]):
                    try:
                        label = node.get("label", "")
                        if not label:
                            results["errors"].append(f"kg_nodes[{i}]: missing label")
                            continue
                        self._call("create_node", [
                            workspace_id,
                            label,
                            node.get("node_type", "concept"),
                            node.get("summary", ""),
                            node.get("metadata_json", "{}"),
                            node.get("source_memory_id", ""),
                            node.get("source_document_id", ""),
                        ])
                        results["kg_nodes"]["imported"] += 1
                    except Exception as e:
                        if "already exists" in str(e).lower():
                            if strategy == "skip" or strategy == "merge":
                                results["kg_nodes"]["skipped"] += 1
                                continue
                            elif strategy == "replace":
                                # Try to find and delete existing node
                                try:
                                    existing_nodes = self._query(
                                        "kg_node",
                                        workspace_id=workspace_id,
                                        filter_dict={"label": label},
                                        columns=["id"],
                                    )
                                    for en in existing_nodes:
                                        self._call("delete_node", [en["id"]])
                                except Exception:
                                    pass
                                try:
                                    self._call("create_node", [
                                        workspace_id,
                                        label,
                                        node.get("node_type", "concept"),
                                        node.get("summary", ""),
                                        node.get("metadata_json", "{}"),
                                        node.get("source_memory_id", ""),
                                        node.get("source_document_id", ""),
                                    ])
                                    results["kg_nodes"]["imported"] += 1
                                except Exception as e2:
                                    results["errors"].append(f"kg_nodes[{i}]: {e2}")
                        else:
                            results["errors"].append(f"kg_nodes[{i}]: {e}")

            # Import KG edges
            if "kg_edges" in bundle:
                for i, edge in enumerate(bundle["kg_edges"]):
                    try:
                        self._call("create_edge", [
                            workspace_id,
                            edge.get("source_node_id", ""),
                            edge.get("target_node_id", ""),
                            edge.get("relation", "related_to"),
                            edge.get("weight", 1.0),
                            edge.get("confidence", "EXTRACTED"),
                            edge.get("metadata_json", "{}"),
                            edge.get("source_memory_id", ""),
                        ])
                        results["kg_edges"]["imported"] += 1
                    except Exception as e:
                        if "already exists" in str(e).lower():
                            if strategy == "skip" or strategy == "merge":
                                results["kg_edges"]["skipped"] += 1
                                continue
                        results["errors"].append(f"kg_edges[{i}]: {e}")

            # Import notes
            if "notes" in bundle:
                for i, note in enumerate(bundle["notes"]):
                    try:
                        content = note.get("content", "")
                        title = note.get("title", "Untitled")
                        if not content:
                            results["errors"].append(f"notes[{i}]: empty content")
                            continue
                        self._call("create_note", [
                            workspace_id,
                            title,
                            content,
                            note.get("embed", True),
                            note.get("tags_json", "[]"),
                        ])
                        results["notes"]["imported"] += 1
                    except Exception as e:
                        if "already exists" in str(e).lower():
                            if strategy == "skip" or strategy == "merge":
                                results["notes"]["skipped"] += 1
                                continue
                        results["errors"].append(f"notes[{i}]: {e}")

            # Import profiles
            if "profiles" in bundle:
                for i, profile in enumerate(bundle["profiles"]):
                    try:
                        peer_id = profile.get("peer_id", "")
                        if not peer_id:
                            results["errors"].append(f"profiles[{i}]: missing peer_id")
                            continue
                        self._call("upsert_profile", [
                            peer_id,
                            profile.get("static_facts_json", "[]"),
                            profile.get("dynamic_context_json", "[]"),
                            profile.get("preferences_json", "{}"),
                            profile.get("tags_json", "[]"),
                        ])
                        results["profiles"]["imported"] += 1
                    except Exception as e:
                        results["errors"].append(f"profiles[{i}]: {e}")

            return results

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    def _apply_filters(
        self,
        records: list[dict[str, Any]],
        filters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Apply client-side filters to a list of dict records."""
        result = records
        for key, value in filters.items():
            result = [r for r in result if r.get(key) == value]
        return result

    def _dicts_to_csv(
        self,
        records: list[dict[str, Any]],
        fields: list[str],
    ) -> str:
        """Convert a list of dicts to CSV string with the given field order."""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            row = {k: rec.get(k, "") for k in fields}
            # Format complex values as JSON strings
            for k in fields:
                v = row[k]
                if isinstance(v, (dict, list)):
                    row[k] = json.dumps(v)
                elif v is None:
                    row[k] = ""
            writer.writerow(row)
        return output.getvalue()

    def _memories_to_markdown(self, memories: list[dict[str, Any]]) -> str:
        """Convert a list of memory records to concatenated markdown."""
        parts: list[str] = []
        for m in memories:
            content = m.get("content", "")
            summary = m.get("summary", "")
            mem_type = m.get("memory_type", "experience")
            confidence = m.get("confidence", 0.8)
            ts = m.get("created_at", "")
            parts.append(
                f"---\n"
                f"**Type:** {mem_type}  \n"
                f"**Confidence:** {confidence}  \n"
                f"**Created:** {ts}  \n"
                f"**ID:** {m.get('id', '')}  \n"
                f"\n"
                f"{content}\n"
                f"\n"
                f"{'*' + summary + '*' if summary else ''}\n"
            )
        return "\n".join(parts)

    def _parse_memory_input(
        self,
        data: str,
        fmt: str,
    ) -> list[dict[str, Any]]:
        """Parse memory data from the given format into a list of dicts."""
        if fmt == "json":
            parsed = json.loads(data)
            if isinstance(parsed, dict):
                return [parsed]
            if isinstance(parsed, list):
                return parsed
            raise ValueError(f"JSON input must be an object or array, got {type(parsed).__name__}")
        elif fmt == "csv":
            return self._csv_to_dicts(data, _MEMORY_CSV_FIELDS)
        elif fmt == "markdown":
            return self._markdown_to_memories(data)
        else:
            raise ValueError(
                f"Unknown import format '{fmt}'. Supported: json, csv, markdown."
            )

    def _csv_to_dicts(
        self,
        data: str,
        fields: list[str],
    ) -> list[dict[str, Any]]:
        """Parse CSV text into a list of dicts."""
        reader = csv.DictReader(io.StringIO(data))
        records: list[dict[str, Any]] = []
        for row in reader:
            rec: dict[str, Any] = {}
            for f in fields:
                val = row.get(f, "")
                # Try to parse JSON-like strings
                if isinstance(val, str) and val.startswith(("{", "[")):
                    try:
                        rec[f] = json.loads(val)
                    except (json.JSONDecodeError, ValueError):
                        rec[f] = val
                else:
                    rec[f] = val
            records.append(rec)
        return records

    def _markdown_to_memories(self, data: str) -> list[dict[str, Any]]:
        """Parse concatenated markdown memory entries into a list of dicts.

        Each entry is separated by ``---`` and prefixed with YAML-like
        metadata lines (Type, Confidence, Created, ID).
        """
        memories: list[dict[str, Any]] = []
        blocks = data.split("\n---\n")
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            lines = block.split("\n")
            metadata: dict[str, Any] = {}
            content_lines: list[str] = []
            in_meta = True
            for line in lines:
                if in_meta and line.startswith("**") and "** " in line:
                    # Parse metadata line: **Key:** Value
                    colon_idx = line.find(":** ")
                    if colon_idx > 0:
                        key = line[2:colon_idx].strip().lower()
                        val = line[colon_idx + 4:].strip()
                        metadata[key] = val
                elif in_meta and line.strip() == "":
                    continue
                else:
                    in_meta = False
                    content_lines.append(line)

            content = "\n".join(content_lines).strip()
            if content:
                memories.append({
                    "content": content,
                    "summary": metadata.get("summary", ""),
                    "memory_type": metadata.get("type", "experience"),
                    "confidence": float(metadata.get("confidence", 0.8)),
                    "created_at": metadata.get("created", ""),
                })
        return memories
