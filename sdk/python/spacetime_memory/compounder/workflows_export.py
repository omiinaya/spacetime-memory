"""Compounder workflows — export and overview workflows."""
from __future__ import annotations

import datetime
import logging
from typing import Any

logger = logging.getLogger(__name__)




class CompounderWorkflowsExport:
    """Mixin — export and overview workflows."""


    def export_workspace(
        self,
        output_dir: str,
        workspace_id: str = "default",
        *,
        include_kg: bool = False,
        include_system_notes: bool = False,
        kg_json: bool = False,
    ) -> dict[str, Any]:
        """Export all notes in a workspace as markdown files with
        YAML frontmatter, ready for Obsidian or git-based wiki browsing.

        Generates one ``.md`` file per note, using the note title as
        the filename.  YAML frontmatter includes ``id``, ``type``,
        ``created``, ``updated``, ``tags``, and ``backlinks``.

        When ``kg_json=True``, also writes a ``kg.json`` file to the
        target directory containing the full knowledge graph — all
        nodes and edges — as a structured JSON document.  This enables
        external tooling (LLM pipelines, graph analysis) to consume the
        workspace's entity graph in a single file.

        Args:
            output_dir: Directory to write markdown files into.
            workspace_id: Target workspace.
            include_kg: Also export KG node summaries as markdown.
            include_system_notes: Include ``_index`` and ``_log`` notes.
            kg_json: Also export full KG (nodes + edges) as ``kg.json``.

        Returns:
            Dict with ``files_written``, ``output_dir``, ``errors``,
            and optionally ``kg_json_path``.
        """
        import pathlib

        out = pathlib.Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        result: dict[str, Any] = {
            "files_written": 0,
            "output_dir": str(out),
            "errors": [],
        }

        # Fetch all notes
        notes = self._client._query(
            "note",
            workspace_id=workspace_id,
            filter_dict={},
        )
        if not notes and not include_kg and not kg_json:
            return result

        # Build backlink map (memory → list of notes that reference it)
        backlink_map: dict[str, list[str]] = {}
        edges = self._client._query(
            "kg_edge",
            workspace_id=workspace_id,
            filter_dict={},
        )
        for e in edges:
            src = e.get("source_node_id", "")
            tgt = e.get("target_node_id", "")
            if src:
                backlink_map.setdefault(tgt, []).append(src)
            if tgt:
                backlink_map.setdefault(src, []).append(tgt)

        for note in notes:
            note_id = note.get("id", "")
            title = note.get("title", "untitled")
            content = note.get("content", "")
            created = note.get("created_at", "")
            updated = note.get("updated_at", "")

            # Skip system notes unless asked
            if not include_system_notes and title.startswith("_"):
                continue

            # Build frontmatter
            backlinks = backlink_map.get(note_id, [])
            bl_lines = "\n".join(f'    - "{b}"' for b in backlinks[:20])

            frontmatter = (
                "---\n"
                f'id: "{note_id}"\n'
                f'title: "{title}"\n'
                f"created: {created}\n"
                f"updated: {updated}\n"
                f"backlinks:\n{bl_lines}\n"
                "---\n\n"
            )

            # Sanitize filename
            safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title).strip()
            if not safe_title:
                safe_title = note_id[:12]
            filename = out / f"{safe_title[:100]}.md"

            try:
                filename.write_text(frontmatter + content, encoding="utf-8")
                result["files_written"] += 1
            except OSError as e:
                result["errors"].append(f"{safe_title}: {e}")

        # Optionally export KG nodes as markdown entity pages
        if include_kg:
            kg_dir = out / "_kg_nodes"
            kg_dir.mkdir(exist_ok=True)
            nodes = self._client._query(
                "kg_node",
                workspace_id=workspace_id,
                filter_dict={},
            )
            for node in nodes:
                label = node.get("label", "unknown")
                summary = node.get("summary", "")
                ntype = node.get("node_type", "concept")
                node_id = node.get("id", "")
                kg_content = (
                    "---\n"
                    f'id: "{node_id}"\n'
                    f"type: kg_node\n"
                    f"node_type: {ntype}\n"
                    f'label: "{label}"\n'
                    "---\n\n"
                    f"## {label}\n\n"
                    f"**Type:** {ntype}\n\n"
                    f"{summary}\n"
                )
                safe_label = "".join(c if c.isalnum() or c in " -_" else "_" for c in label).strip()
                try:
                    (kg_dir / f"{safe_label[:100]}.md").write_text(kg_content, encoding="utf-8")
                    result["files_written"] += 1
                except OSError as e:
                    result["errors"].append(f"kg_{label}: {e}")

        # Export full KG as a single JSON file (nodes + edges)
        if kg_json:
            import json

            nodes = self._client._query(
                "kg_node",
                workspace_id=workspace_id,
                filter_dict={},
            )
            all_edges = self._client._query(
                "kg_edge",
                workspace_id=workspace_id,
                filter_dict={},
            )
            kg_data = {
                "workspace_id": workspace_id,
                "nodes": nodes,
                "edges": all_edges,
            }
            kg_path = out / "kg.json"
            try:
                kg_path.write_text(
                    json.dumps(kg_data, indent=2, default=str),
                    encoding="utf-8",
                )
                result["kg_json_path"] = str(kg_path)
                result["files_written"] += 1
            except OSError as e:
                result["errors"].append(f"kg.json: {e}")

        return result



    def generate_overview_page(
        self,
        workspace_id: str = "default",
        embed: bool = True,
    ) -> dict[str, Any]:
        """Generate a high-level overview/synthesis page for the
        workspace, summarizing its contents.

        Scans all notes, KG nodes, and edges to produce a markdown
        overview with entity tables, connections map, and stats.
        Uses LLM to write the synthesis if available; falls back
        to a structured data-driven summary.

        Returns:
            Dict with ``note`` key if created, or empty dict if
            the workspace is empty.
        """
        notes = (
            self._client._query(
                "note",
                workspace_id=workspace_id,
                filter_dict={},
            )
            or []
        )
        nodes = (
            self._client._query(
                "kg_node",
                workspace_id=workspace_id,
                filter_dict={},
            )
            or []
        )
        edges = (
            self._client._query(
                "kg_edge",
                workspace_id=workspace_id,
                filter_dict={},
            )
            or []
        )

        if not notes and not nodes:
            return {"note": {}}

        # Count by note type from frontmatter (best-effort)
        entity_notes = [
            n
            for n in notes
            if "type: person" in n.get("content", "")
            or "type: organization" in n.get("content", "")
        ]
        concept_notes = [n for n in notes if "type: concept" in n.get("content", "")]
        source_notes = [n for n in notes if n.get("title", "").startswith("Source:")]
        comparison_notes = [n for n in notes if n.get("title", "").startswith("Comparison:")]
        regular_notes = [
            n
            for n in notes
            if not n.get("title", "").startswith("_")
            and n not in entity_notes
            and n not in concept_notes
            and n not in source_notes
            and n not in comparison_notes
        ]

        # Count node types
        node_types: dict[str, int] = {}
        for nd in nodes:
            nt = nd.get("node_type", "unknown")
            node_types[nt] = node_types.get(nt, 0) + 1

        # Count edge types
        edge_types: dict[str, int] = {}
        for e in edges:
            rt = e.get("relation_type", "unknown")
            edge_types[rt] = edge_types.get(rt, 0) + 1

        # Count orphan nodes (no edges)
        connected_ids: set[str] = set()
        for e in edges:
            src = e.get("source_node_id", "")
            tgt = e.get("target_node_id", "")
            if src:
                connected_ids.add(src)
            if tgt:
                connected_ids.add(tgt)
        orphan_count = sum(1 for nd in nodes if nd.get("id", "") not in connected_ids)

        # Top entities table
        entity_rows = ""
        top_nodes = sorted(
            nodes,
            key=lambda n: len(n.get("summary", "")),
            reverse=True,
        )[:10]
        if top_nodes:
            entity_rows = "| Entity | Type | Summary |\n|--------|------|---------|\n"
            for nd in top_nodes:
                label = nd.get("label", "?")[:30]
                ntype = nd.get("node_type", "?")[:15]
                summary = nd.get("summary", "")[:80]
                entity_rows += f"| {label} | {ntype} | {summary} |\n"

        # Recent activity from _log
        recent_items = ""
        log_notes = [n for n in notes if n.get("title") == "_log"]
        if log_notes:
            log_content = log_notes[-1].get("content", "")
            log_lines = [line for line in log_content.split("\n") if line.startswith("## [")][-5:]
            if log_lines:
                recent_items = "\n".join(f"- {line.strip('# ')}" for line in log_lines)

        type_table = ""
        if node_types:
            type_table = "| Type | Count |\n|------|:-----:|\n"
            for nt, count in sorted(node_types.items(), key=lambda x: -x[1]):
                type_table += f"| {nt} | {count} |\n"

        # Build the overview page
        lines = [
            "---",
            "type: overview",
            "tags: [overview, synthesis]",
            f"created: {datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d')}",
            "---",
            "",
            "## Workspace Overview",
            "",
            f"**{len(notes)}** notes · **{len(nodes)}** KG nodes · "
            f"**{len(edges)}** edges · **{orphan_count}** orphans",
            "",
        ]

        # LLM synthesis if available
        if self._llm.available:
            summary_prompt = (
                f"Workspace '{workspace_id}' has {len(notes)} notes, "
                f"{len(nodes)} KG nodes ({node_types}), and {len(edges)} edges. "
                f"Top entities: {[n.get('label', '') for n in top_nodes[:5]]}. "
                "Write a 3-5 sentence synthesis of what this workspace "
                "contains. Focus on the main themes and knowledge domains."
            )
            llm_synthesis = self._llm.summarize(
                summary_prompt,
                instruction="Write a concise workspace synthesis.",
            )
            if llm_synthesis:
                lines.append("### AI Synthesis\n")
                lines.append(llm_synthesis)
                lines.append("")

        # Stats sections
        lines.append("### Notes by Category\n")
        lines.append("| Category | Count |")
        lines.append("|----------|:-----:|")
        lines.append(f"| Sources | {len(source_notes)} |")
        lines.append(f"| Entity pages | {len(entity_notes)} |")
        lines.append(f"| Concept pages | {len(concept_notes)} |")
        lines.append(f"| Comparisons | {len(comparison_notes)} |")
        lines.append(f"| Other | {len(regular_notes)} |")
        lines.append(
            f"| System (_index, _log) | "
            f"{sum(1 for n in notes if n.get('title', '').startswith('_'))} |"
        )
        lines.append("")

        if type_table:
            lines.append("### Knowledge Graph Entity Types\n")
            lines.append(type_table)
            lines.append("")

        if entity_rows:
            lines.append("### Top Entities\n")
            lines.append(entity_rows)
            lines.append("")

        if orphan_count > 0:
            lines.append(
                f"> ⚠ **{orphan_count} orphan nodes** — KG nodes with "
                f"no edges. Consider linking them or running `lint()`."
            )
            lines.append("")

        if recent_items:
            lines.append("### Recent Activity\n")
            lines.append(recent_items)
            lines.append("")

        if edge_types:
            edge_lines = "| Relation Type | Count |\n|------|:-----:|\n"
            for rt, count in sorted(edge_types.items(), key=lambda x: -x[1]):
                edge_lines += f"| {rt} | {count} |\n"
            lines.append("### Edge Types\n")
            lines.append(edge_lines)

        lines.append("---")
        lines.append(f"*Auto-generated overview for workspace '{workspace_id}'*")

        content = "\n".join(lines)

        note = self._client.create_note(
            workspace_id=workspace_id,
            title="_overview",
            content=content,
            embed=embed,
        )

        self._log_activity(
            workspace_id,
            "generate_overview",
            f"Workspace overview — {len(notes)} notes, {len(nodes)} nodes, {len(edges)} edges",
        )

        return {"note": note}

