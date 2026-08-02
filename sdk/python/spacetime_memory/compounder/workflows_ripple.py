"""Compounder workflows — ripple update detection."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)




class CompounderWorkflowsRipple:
    """Mixin — ripple update detection."""


    def detect_ripple_effects(
        self,
        source_id: str,
        workspace_id: str = "default",
        max_hops: int = 2,
        include_notes: bool = False,
        stale_only: bool = False,
    ) -> dict[str, Any]:
        """Detect which KG nodes need re-summarization when *source_id* is updated.

        Walks the knowledge graph outward from *source_id*, following edges to
        find all entities that may have stale summaries.  *source_id* can be a
        kg_node, note, or memory ID.

        Args:
            source_id: The ID of the updated source (kg_node, note, or memory).
            workspace_id: Target workspace.
            max_hops: Max transitive hops (1 = direct only, default 2,
                      clamped to [1, 6]).
            include_notes: If True, also find notes whose title or content
                textually references an affected node label.
            stale_only: If True, ``needs_review`` only includes nodes already
                marked stale (``stale_since > 0``). Stats always include
                ``stale_count`` regardless.

        Returns:
            Dict with keys:

            * **source** — {type, label, id, workspace_id}
            * **directly_affected** — list of {id, label, type, reason,
              stale_since, ripple_path}
            * **transitively_affected** — list of {id, label, type, reason,
              hop, stale_since, ripple_path}
            * **needs_review** — list of {id, label, type, reason,
              stale_since, hop, ripple_path} — every KG node that should
              be re-summarized when the source is updated (excludes source
              itself)
            * **affected_notes** — list of {id, title} (only when
              include_notes=True; source note excluded)
            * **stats** — {total_entities, direct_count, transitive_count,
              kg_nodes_needing_review, max_hops_reached}
        """
        max_hops = max(1, min(max_hops, 6))

        # ── Default result ──
        result: dict[str, Any] = {
            "source": {"type": "memory", "label": source_id, "id": source_id, "workspace_id": workspace_id},
            "directly_affected": [],
            "transitively_affected": [],
            "affected_notes": [],
            "stats": {
                "total_entities": 0,
                "direct_count": 0,
                "transitive_count": 0,
                "kg_nodes_needing_review": 0,
                "max_hops_reached": 0,
            },
        }

        if not source_id.strip():
            result["error"] = "source_id is required"
            return result

        # ── Determine source type ──
        # The server-side filter_dict filters server-side; double-filter client-side
        # for robustness with mock clients in tests.
        source_info: dict[str, Any] | None = None

        # 1. Check kg_node
        nodes = self._client._query("kg_node", workspace_id=workspace_id, filter_dict={"id": source_id})
        nodes = [n for n in nodes if n.get("id") == source_id]
        if nodes:
            source_info = {
                "type": "kg_node",
                "label": nodes[0].get("label", source_id),
                "id": source_id,
                "workspace_id": workspace_id,
            }

        # 2. Check note
        if not source_info:
            notes = self._client._query("note", workspace_id=workspace_id, filter_dict={"id": source_id})
            notes = [n for n in notes if n.get("id") == source_id]
            if notes:
                source_info = {
                    "type": "note",
                    "label": notes[0].get("title", source_id),
                    "id": source_id,
                    "workspace_id": workspace_id,
                }

        # 3. Check memory
        if not source_info:
            memories = self._client._query("memory", workspace_id=workspace_id, filter_dict={"id": source_id})
            memories = [m for m in memories if m.get("id") == source_id]
            if memories:
                source_info = {
                    "type": "memory",
                    "label": source_id,
                    "id": source_id,
                    "workspace_id": workspace_id,
                }

        if source_info:
            result["source"] = source_info

        # ── Fetch workspace data ──
        all_nodes = self._client._query("kg_node", workspace_id=workspace_id, filter_dict={})
        all_edges = self._client._query("kg_edge", workspace_id=workspace_id, filter_dict={})
        node_map = {n.get("id", ""): n for n in all_nodes}

        # ── BFS to find affected nodes ──
        if source_info and source_info["type"] == "kg_node":
            # Source is itself a KG node — BFS outward via edges
            source_node_id = source_id
            visited: dict[str, int] = {source_node_id: 0}  # node_id -> hop
            queue: list[str] = [source_node_id]
            path_map: dict[str, list[dict]] = {source_node_id: []}  # node_id -> [steps]

            while queue:
                current = queue.pop(0)
                cur_hop = visited[current]
                if cur_hop >= max_hops:
                    continue

                for e in all_edges:
                    src = e.get("source_node_id", "")
                    tgt = e.get("target_node_id", "")
                    # Ripple effects follow edge DIRECTION (source -> target):
                    # if A "informs" B, updating A affects B, not vice-versa.
                    if src == current:
                        neighbour = tgt
                    else:
                        neighbour = None
                    if neighbour and neighbour not in visited:
                        visited[neighbour] = cur_hop + 1
                        queue.append(neighbour)
                        # Record traversal path
                        step = {
                            "edge_id": e.get("id", ""),
                            "relation": e.get("relation", "related_to"),
                            "from": current,
                            "to": neighbour,
                        }
                        path_map[neighbour] = list(path_map.get(current, [])) + [step]

        elif source_info:
            # Source is note or memory — find KG nodes with matching source_memory_id
            visited = {}
            path_map: dict[str, list[dict]] = {}
            for n in all_nodes:
                if n.get("source_memory_id", "") == source_id:
                    nid = n.get("id", "")
                    if nid:
                        visited[nid] = 1  # direct reference = hop 1
                        path_map[nid] = [{
                            "edge_id": "",
                            "relation": "source_of",
                            "from": source_id,
                            "to": nid,
                        }]
                        # Enqueue for transitive expansion
                        queue = [nid]
                        while queue:
                            current = queue.pop(0)
                            cur_hop = visited[current]
                            if cur_hop >= max_hops:
                                continue
                            for e in all_edges:
                                src = e.get("source_node_id", "")
                                tgt = e.get("target_node_id", "")
                                # Directed traversal (source -> target).
                                if src == current:
                                    neighbour = tgt
                                else:
                                    neighbour = None
                                if neighbour and neighbour not in visited:
                                    visited[neighbour] = cur_hop + 1
                                    queue.append(neighbour)
                                    step = {
                                        "edge_id": e.get("id", ""),
                                        "relation": e.get("relation", "related_to"),
                                        "from": current,
                                        "to": neighbour,
                                    }
                                    path_map[neighbour] = list(path_map.get(current, [])) + [step]
        else:
            # Source not found in any table
            visited = {}
            path_map: dict[str, list[dict]] = {}
            path_map: dict[str, list[dict]] = {}

        # ── Categorise visited nodes ──
        direct_ids: set[str] = set()
        needs_review: list[dict[str, Any]] = []
        for nid, hop in visited.items():
            if nid == source_id:
                continue
            node = node_map.get(nid, {})
            entry = {
                "id": nid,
                "label": node.get("label", nid),
                "type": node.get("node_type", "unknown"),
                "stale_since": node.get("stale_since", 0),
            }
            # Attach ripple path if available
            rp = path_map.get(nid, [])
            if rp:
                entry["ripple_path"] = rp
            if hop == 1:
                entry["reason"] = "direct_neighbour"
                result["directly_affected"].append(entry)
                direct_ids.add(nid)
            else:
                entry["reason"] = f"transitive_{hop}_hops"
                entry["hop"] = hop
                result["transitively_affected"].append(entry)
                result["stats"]["max_hops_reached"] = max(result["stats"]["max_hops_reached"], hop)
            # Every visited KG node (except source) goes into needs_review
            needs_review.append(entry)

        result["needs_review"] = needs_review

        # ── Stats ──
        result["stats"]["direct_count"] = len(result["directly_affected"])
        result["stats"]["transitive_count"] = len(result["transitively_affected"])
        result["stats"]["total_entities"] = result["stats"]["direct_count"] + result["stats"]["transitive_count"]
        result["stats"]["kg_nodes_needing_review"] = result["stats"]["total_entities"]
        result["stats"]["stale_count"] = sum(
            1 for e in needs_review if (e.get("stale_since") or 0) > 0
        )
        if stale_only:
            result["needs_review"] = [
                e for e in needs_review if (e.get("stale_since") or 0) > 0
            ]

        # ── Include notes (textual match on affected node labels) ──
        if include_notes and (
            result["directly_affected"]
            or result["transitively_affected"]
            or (source_info and source_info["type"] == "kg_node")
        ):
            all_notes = self._client._query("note", workspace_id=workspace_id, filter_dict={})
            all_affected = result["directly_affected"] + result["transitively_affected"]
            affected_labels: set[str] = set()
            for e in all_affected:
                lbl = e.get("label", "")
                if lbl and len(lbl) > 2:
                    affected_labels.add(lbl.lower())
            # Also match the source entity's own label: when the updated source
            # is a KG node, notes that reference it are impacted even if it has
            # no graph neighbours.
            if source_info and source_info["type"] == "kg_node":
                src_lbl = source_info.get("label", "")
                if src_lbl and len(src_lbl) > 2:
                    affected_labels.add(src_lbl.lower())

            for n in all_notes:
                nid = n.get("id", "")
                # Skip the source note itself
                if nid == source_id:
                    continue
                title = n.get("title", "")
                ncontent = n.get("content", "")
                combined = (title + " " + ncontent).lower()
                for label in affected_labels:
                    if label in combined:
                        result["affected_notes"].append({"id": nid, "title": title})
                        break

        return result



    def apply_ripple_updates(
        self,
        detection_result: dict[str, Any],
        new_information: str = "",
        source_note_id: str = "",
        workspace_id: str = "default",
        dry_run: bool = False,
        clear_stale: bool = False,
    ) -> dict[str, Any]:
        """Re-summarize all nodes flagged by ``detect_ripple_effects``.

        Iterates over the ``needs_review`` list in *detection_result*,
        calling ``_ripple_update_entity`` for each node to merge
        *new_information* into each affected node's existing summary.

        Args:
            detection_result: The dict returned by
                ``detect_ripple_effects()``. Must contain a
                ``needs_review`` key.
            new_information: Text describing what changed in the
                source — this is merged into each affected node's
                summary.  If empty, uses a generic "updated" message.
            source_note_id: The source note ID passed to
                ``_ripple_update_entity`` (for provenance tracking).
            workspace_id: Target workspace.
            dry_run: If True, only report what would be updated
                without actually calling the LLM.

        Returns:
            Dict with:

            * **updated** — list of {node_id, label} for successful updates
            * **skipped** — list of {node_id, label, reason} for skipped nodes
            * **errors** — list of {node_id, label, error} for failed updates
            * **stats** — {total, updated_count, skipped_count, error_count}
        """
        result: dict[str, Any] = {
            "updated": [],
            "skipped": [],
            "errors": [],
            "stats": {"total": 0, "updated_count": 0, "skipped_count": 0, "error_count": 0},
        }

        needs_review = detection_result.get("needs_review", [])
        if not needs_review:
            return result

        info = new_information.strip() or                "The source associated with this node was updated with new information."

        for entry in needs_review:
            node_id = entry.get("id", "")
            label = entry.get("label", node_id)
            reason = entry.get("reason", "unknown")

            if dry_run:
                result["updated"].append({"node_id": node_id, "label": label, "reason": reason})
                continue

            if not label.strip():
                result["skipped"].append({
                    "node_id": node_id, "label": label,
                    "reason": "empty label, cannot update",
                })
                continue

            try:
                self._ripple_update_entity(
                    workspace_id=workspace_id,
                    entity_name=label,
                    new_information=info,
                    source_note_id=source_note_id,
                )
                if clear_stale and node_id:
                    try:
                        self._client._call("set_node_stale", [node_id, False])
                    except Exception:
                        logger.warning("apply_ripple_updates: failed to clear stale flag for %s", node_id)
                result["updated"].append({"node_id": node_id, "label": label, "reason": reason})
            except RuntimeError as exc:
                result["errors"].append({
                    "node_id": node_id, "label": label,
                    "error": str(exc)[:200],
                })

        stats = result["stats"]
        stats["total"] = len(needs_review)
        stats["updated_count"] = len(result["updated"])
        stats["skipped_count"] = len(result["skipped"])
        stats["error_count"] = len(result["errors"])

        return result



    def mark_stale_for_source(
        self,
        workspace_id: str,
        source_id: str,
        max_hops: int = 2,
    ) -> dict[str, Any]:
        """Mark every KG node affected by *source_id* as stale.

        Uses ``detect_ripple_effects`` to compute the affected set, then calls
        the ``set_node_stale`` reducer on each node. Returns a dict with
        ``status`` and ``marked_count``.
        """
        if not source_id:
            return {"status": "error", "marked_count": 0, "error": "source_id is required"}
        detection = self.detect_ripple_effects(
            source_id=source_id, workspace_id=workspace_id, max_hops=max_hops
        )
        marked = 0
        errors = 0
        for entry in detection.get("needs_review", []):
            node_id = entry.get("id", "")
            if not node_id:
                continue
            try:
                self._client._call("set_node_stale", [node_id, True])
                marked += 1
            except Exception:
                errors += 1
                logger.warning("mark_stale_for_source: failed to mark %s", node_id)
        return {
            "status": "ok",
            "marked_count": marked,
            "error_count": errors,
            "source_id": source_id,
            "workspace_id": workspace_id,
        }



    def clear_stale_flag(self, node_id: str) -> bool:
        """Clear the stale flag (``stale_since``) on a KG node.

        Returns True on success, False if *node_id* is empty or the reducer
        call fails.
        """
        if not node_id:
            return False
        try:
            self._client._call("set_node_stale", [node_id, False])
            return True
        except Exception:
            logger.warning("clear_stale_flag: failed for node %s", node_id)
            return False

