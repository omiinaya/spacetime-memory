"""Memory search and hybrid retrieval mixin."""
from __future__ import annotations

import json
import math
import os as _os
import time
from typing import Any

import httpx

from ..query_expansion import expand_query
from ._base import _tracing_span, logger
from ._rerank import llm_rerank
from ._schemas import _apply_return_schema
from ._search_helpers import cosine_similarity, tokenize_query
from ._session_search import SessionSearchMixin
from ._utils import _esc, _make_snippet, _query_hash


class SearchMixin(SessionSearchMixin):
    """Spacetime-Memory search and hybrid retrieval mixin.

    Provides Client methods related to semantic search, keyword search,
    hybrid fusion, entity-aware boosting, and cross-encoder reranking.
    Inherits from ClientBase for connection infrastructure.
    """
    # ------------------------------------------------------------------
    # Entity-aware search result boosting (mem0 v3 multi-signal parity)
    # ------------------------------------------------------------------

    def _boost_with_entity_signal(
        self,
        query: str,
        rows: list[dict[str, Any]],
        workspace_id: str,
        *,
        boost_factor: float = 0.15,
    ) -> list[dict[str, Any]]:
        """Boost search results that mention entities found in the query.

        Inspired by mem0 v3's multi-signal retrieval: if the query mentions
        a known knowledge-graph entity (label or summary match) OR an
        entity_link alias (e.g. "reinforcement learning from human feedback"
        matching the canonical "RLHF" entity), results whose content
        references that entity get a fused_score boost.

        Operates in-place on the ``fused_score`` of each row and re-sorts.

        Args:
            query: The search query.
            rows: Search results after ``_enrich_content`` (must have
                  ``memory_content`` or ``content`` key).
            workspace_id: Target workspace for entity lookup.
            boost_factor: Maximum fractional boost applied to entity-matching
                          results (default 0.15 = +15%).

        Returns:
            Rows with adjusted ``fused_score`` values, re-sorted
            highest-first.  If no entities are found in the query or
            the KG lookup fails, returns rows unchanged.
        """
        if not rows or not query:
            return rows

        # Fetch KG nodes from this workspace
        try:
            nodes = self._query(
                "kg_node",
                workspace_id=workspace_id,
                columns=["id", "label", "summary", "node_type"],
            )
        except RuntimeError:
            logger.warning("get_graph_context: query kg_node failed, returning partial results")
            return rows  # Graceful degradation

        # Fetch entity_link records for alias matching
        try:
            links = self._query(
                "entity_link",
                workspace_id=workspace_id,
                columns=["id", "entity_name", "aliases_json", "entity_type"],
            )
        except RuntimeError:
            logger.debug("get_graph_context: entity_link table may not exist, skipping alias matching")
            links = []  # entity_link table may not exist — graceful degradation

        if not nodes and not links:
            return rows

        query_lower = query.lower()
        query_words = set(query_lower.split())

        # Build a list of matched entities, each with canonical name + aliases
        # Structure: list[dict] — {"canonical": str, "aliases": list[str]}
        matching_entities: list[dict[str, Any]] = []

        # --- Match against KG node labels & summaries ---
        for node in nodes:
            label = (node.get("label") or "").lower().strip()
            summary = (node.get("summary") or "").lower().strip()

            if not label:
                continue

            # 1) Exact match: query contains the full entity label
            if label in query_lower:
                matching_entities.append({"canonical": label, "aliases": []})
                continue

            # 2) Word-level overlap: a word from the label appears in the query
            label_words = set(label.split())
            if label_words and query_words & label_words:
                matching_entities.append({"canonical": label, "aliases": []})
                continue

            # 3) Query substring appears in entity summary
            if summary and query_lower in summary:
                matching_entities.append({"canonical": label, "aliases": []})
                continue

        # --- Match against entity_link aliases ---

        for link in links:
            entity_name = (link.get("entity_name") or "").lower().strip()
            if not entity_name:
                continue

            # Parse aliases JSON
            raw_aliases = link.get("aliases_json") or "[]"
            try:
                alias_list: list[str] = json.loads(raw_aliases)
            except (ValueError, TypeError):
                logger.debug("get_graph_context: failed to parse aliases_json, treating as empty")
                alias_list = []

            # Build the set of names to check against the query:
            # canonical entity_name + all aliases
            all_names = [entity_name] + [a.lower().strip() for a in alias_list if a]

            matched = False
            for name in all_names:
                if name in query_lower:
                    matched = True
                    break
                name_words = set(name.split())
                if name_words and query_words & name_words:
                    matched = True
                    break

            if matched:
                matching_entities.append(
                    {
                        "canonical": entity_name,
                        "aliases": [a.lower().strip() for a in alias_list if a],
                    }
                )

        if not matching_entities:
            return rows

        canonical_labels = [e["canonical"] for e in matching_entities]
        logger.debug(
            "Entity-aware boost: detected %d entities in query: %s",
            len(canonical_labels),
            canonical_labels[:5],
        )

        # Boost each result that references any of the matched entities
        for row in rows:
            content = (row.get("memory_content") or row.get("content") or "").lower()
            if not content:
                continue

            # Count how many matched entities appear in the content.
            # For each entity: check canonical name first, then any alias.
            hit_count = 0
            for entity in matching_entities:
                canonical = entity["canonical"]
                if canonical and canonical in content:
                    hit_count += 1
                    continue
                for alias in entity["aliases"]:
                    if alias and alias in content:
                        hit_count += 1
                        break

            if hit_count == 0:
                continue

            # Proportional boost: more entity hits → higher boost,
            # capped by boost_factor
            proportion = min(hit_count / max(len(matching_entities), 1), 1.0)
            entity_boost = proportion * boost_factor
            current = row.get("fused_score", 0.0)
            row["fused_score"] = current * (1.0 + entity_boost)
            row["entity_boost"] = entity_boost

        # Re-sort by boosted fused_score
        rows.sort(key=lambda r: r.get("fused_score", 0.0), reverse=True)
        return rows

    def _fuse_and_deduplicate(
        self,
        rows: list[dict[str, Any]],
        tantivy_rows: list[dict[str, Any]],
        per_strat: dict[str, list[dict]],
        strat_min: dict[str, float],
        strat_max: dict[str, float],
        strategy_weights: dict[str, float],
        polyphonic: bool = False,
    ) -> list[dict[str, Any]]:
        """Min-max normalize per strategy, weighted-sum fuse, dedup by entity_id.

        When *polyphonic* is True, uses Reciprocal Rank Fusion (RRF) instead of
        min-max, which handles disparate score distributions more robustly.
        """
        # ├── RRF path (polyphonic) ──────────────────────────────────────
        if polyphonic:
            from ._search_helpers import reciprocal_rank_fusion
            return reciprocal_rank_fusion(per_strat, k=60, top_k=len(rows) + 100)

        # └── Min-max path (default) ─────────────────────────────────────
        best_per_strat: dict[str, dict[str, float]] = {
            "semantic": {},
            "keyword": {},
            "graph": {},
            "temporal": {},
            "binary": {},
        }
        best_row: dict[str, dict] = {}
        all_rows = list(rows)
        for tr in tantivy_rows:
            eid = tr.get("entity_id", "")
            if eid not in best_row:
                all_rows.append(tr)
        # Also include client-side computed rows (semantic, binary) that
        # aren't in STDB reducer results or Tantivy.
        for strat_name in ("semantic", "binary"):
            for sr in per_strat.get(strat_name, []):
                eid = sr.get("entity_id", "")
                if eid not in best_row:
                    all_rows.append(sr)
        for r in all_rows:
            s = r.get("strategy", "")
            if s not in best_per_strat:
                continue
            sc = float(r.get("score", 0.0))
            eid = r.get("entity_id", "")
            rng = strat_max.get(s, 1.0) - strat_min.get(s, 0.0)
            normalized = ((sc - strat_min.get(s, 0.0)) / rng) if rng > 1e-10 else 1.0
            if eid not in best_per_strat[s] or normalized > best_per_strat[s][eid]:
                best_per_strat[s][eid] = normalized
            if eid not in best_row or sc > float(best_row[eid].get("score", 0)):
                best_row[eid] = dict(r)

        fused: dict[str, float] = {}
        for eid in set().union(*(d.keys() for d in best_per_strat.values())):
            total = 0.0
            for s, w in strategy_weights.items():
                total += best_per_strat[s].get(eid, 0.0) * w
            fused[eid] = total

        seen: dict[str, dict] = {}
        for r in all_rows:
            eid = r.get("entity_id", "")
            fs = fused.get(eid, 0.0)
            r["fused_score"] = fs
            if eid not in seen or fs > seen[eid].get("fused_score", float("-inf")):
                seen[eid] = r

        result = list(seen.values())
        result.sort(key=lambda r: r.get("fused_score", 0.0), reverse=True)
        return result

    def _enrich_content(
        self,
        rows: list[dict[str, Any]],
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """Look up memory/node/note content from STDB and apply veracity weighting.

        Uses the ``content`` field already present in hybrid_result rows.
        Batches confidence lookups via a single ``_query()`` to avoid N+1.
        """
        mem_ids = list({r.get("entity_id", "") for r in rows if r.get("entity_type") == "memory"})
        node_ids = list({r.get("entity_id", "") for r in rows if r.get("entity_type") == "node"})
        note_ids = list({r.get("entity_id", "") for r in rows if r.get("entity_type") == "note"})
        mem_confidences: dict[str, float] = {}
        node_map: dict[str, str] = {}
        note_map: dict[str, str] = {}

        # Batch fetch memory confidences — only for veracity weighting
        if mem_ids:
            try:
                mems = self._query(
                    "memory",
                    workspace_id=workspace_id,
                    columns=["id", "confidence"],
                    filter_dict={},
                )
                # Build confidence map from ALL memories (filter dict doesn't support IN)
                for m in mems:
                    if m.get("id") in mem_ids:
                        mem_confidences[m["id"]] = m.get("confidence", 0.8)
            except RuntimeError:
                logger.warning("_enrich_content: batch confidence lookup failed, skipping veracity")
        if node_ids:
            try:
                nodes = self._query("kg_node", columns=["id", "label"])
                for n in nodes:
                    if n.get("id") in node_ids:
                        node_map[n["id"]] = n.get("label", "")
            except RuntimeError:
                pass
        if note_ids:
            try:
                notes = self._query("note", workspace_id=workspace_id, columns=["id", "title", "content"])
                for n in notes:
                    if n.get("id") in note_ids:
                        note_map[n["id"]] = n.get("title", "") + "\n\n" + n.get("content", "")
            except RuntimeError:
                pass
        for r in rows:
            eid = r.get("entity_id", "")
            if r.get("entity_type") == "memory":
                r["memory_content"] = r.get("content", "")
            elif r.get("entity_type") == "node":
                r["memory_content"] = node_map.get(eid, "")
            elif r.get("entity_type") == "note":
                r["memory_content"] = note_map.get(eid, "")
            else:
                r["memory_content"] = ""
            # Add content snippet for callers that only need a preview
            content_text = r.get("memory_content", "") or r.get("content", "")
            r["snippet"] = _make_snippet(content_text)
            r["score"] = r.get("fused_score", r.get("score", 0.0))
            if eid in mem_confidences:
                from ..veracity import confidence_multiplier

                mult = confidence_multiplier(mem_confidences[eid])
                r["score"] = r["score"] * mult
                r["veracity_multiplier"] = mult
        return rows

    def _graph_search_client_side(
        self,
        workspace_id: str,
        query: str,
        memory_type: str,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Client-side graph search: find KG nodes matching the query,
        then fetch memories linked to those nodes via entity_id.

        Uses SQL reads (free on public tables) instead of the STDB reducer.
        """
        if not query or not query.strip():
            return []

        query_lower = query.lower().strip()
        results: list[dict[str, Any]] = []

        # Step 1: Find KG nodes whose label or summary matches the query
        try:
            # Use ILIKE for case-insensitive substring matching on labels
            node_rows = self._sql(
                "SELECT node_id, label, summary, entity_id, node_type "
                "FROM kg_node "
                f"WHERE workspace_id = '{_esc(workspace_id)}' "
                f"AND (LOWER(label) LIKE '%' || LOWER('{_esc(query_lower)}') || '%' "
                f"OR LOWER(summary) LIKE '%' || LOWER('{_esc(query_lower)}') || '%') "
                "LIMIT 50"
            )
        except RuntimeError:
            logger.debug("graph_search: kg_node query failed")
            return []

        if not node_rows:
            return []

        node_ids = [n["node_id"] for n in node_rows]
        node_entity_ids = {n["node_id"]: n.get("entity_id", "") for n in node_rows}

        # Step 2: Find edges connecting these nodes to other entities
        # Build a quoted list of node_ids for SQL
        node_ids_quoted = ",".join(f"'{_esc(nid)}'" for nid in node_ids)

        try:
            edge_rows = self._sql(
                "SELECT source_node_id, target_node_id, fact, metadata_json "
                "FROM kg_edge "
                f"WHERE workspace_id = '{_esc(workspace_id)}' "
                f"AND (source_node_id IN ({node_ids_quoted}) "
                f"OR target_node_id IN ({node_ids_quoted})) "
                "ORDER BY created_at DESC "
                "LIMIT 100"
            )
        except RuntimeError:
            logger.debug("graph_search: kg_edge query failed")
            return []

        # Step 3: Collect entity_ids from connected nodes
        connected_node_ids: set[str] = set()
        for e in edge_rows:
            src = e.get("source_node_id", "")
            tgt = e.get("target_node_id", "")
            if src in node_ids:
                connected_node_ids.add(tgt)
            if tgt in node_ids:
                connected_node_ids.add(src)

        # Step 4: For each connected node, find its entity_id
        # and fetch the associated memory content
        seen_entities: set[str] = set()
        connected_entity_ids: list[str] = []
        for nid in connected_node_ids:
            eid = node_entity_ids.get(nid, "")
            if eid and eid not in seen_entities:
                seen_entities.add(eid)
                connected_entity_ids.append(eid)
            else:
                # Try to look up entity_id from node_rows for this nid
                pass

        # Also query entity_id for any connected node_ids not in our initial result
        extra_nids = connected_node_ids - set(node_ids)
        if extra_nids:
            extra_quoted = ",".join(f"'{_esc(nid)}'" for nid in extra_nids)
            try:
                extra_nodes = self._sql(
                    "SELECT node_id, entity_id, label "
                    "FROM kg_node "
                    f"WHERE workspace_id = '{_esc(workspace_id)}' "
                    f"AND node_id IN ({extra_quoted})"
                )
                for en in extra_nodes:
                    eid = en.get("entity_id", "")
                    if eid and eid not in seen_entities:
                        seen_entities.add(eid)
                        connected_entity_ids.append(eid)
            except RuntimeError:
                pass

        # Step 5: Fetch memory content for connected entity_ids
        if connected_entity_ids:
            eid_quoted = ",".join(f"'{_esc(eid)}'" for eid in connected_entity_ids)
            try:
                memories = self._sql(
                    "SELECT entity_id, content, memory_type, created_at, "
                    "trust_score, strength "
                    "FROM memory "
                    f"WHERE workspace_id = '{_esc(workspace_id)}' "
                    f"AND entity_id IN ({eid_quoted}) "
                    "AND deactivated_at IS NULL "
                    "ORDER BY trust_score DESC "
                    "LIMIT 50"
                )
                for m in memories:
                    if memory_type and m.get("memory_type") != memory_type:
                        continue
                    results.append({
                        "entity_id": m.get("entity_id", ""),
                        "entity_type": "memory",
                        "content": m.get("content", ""),
                        "score": float(m.get("trust_score", 0.5)) * 0.5,
                        "strategy": "graph",
                        "workspace_id": workspace_id,
                    })
            except RuntimeError:
                logger.debug("graph_search: memory query failed")

        # Step 6: Add the matched node content directly as hits
        for n in node_rows:
            label = n.get("label", "")
            summary = n.get("summary", "")
            content = f"{label}: {summary}" if summary else label
            if not content:
                continue
            results.append({
                "entity_id": n.get("entity_id", n.get("node_id", "")),
                "entity_type": "kg_node",
                "content": content,
                "score": 0.6,  # Direct KG match — high base score
                "strategy": "graph",
                "workspace_id": workspace_id,
            })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    def _temporal_search_client_side(
        self,
        workspace_id: str,
        memory_type: str,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Client-side temporal search: fetch most recent memories.

        Uses SQL reads (free on public tables) instead of the STDB reducer.
        """
        try:
            type_clause = f"AND memory_type = '{_esc(memory_type)}'" if memory_type else ""
            mems = self._sql(
                "SELECT id, content, memory_type, created_at, "
                "trust_score, strength, deactivated_at "
                "FROM memory "
                f"WHERE workspace_id = '{_esc(workspace_id)}' "
                f"{type_clause} "
                "AND deactivated_at IS NULL "
                "ORDER BY created_at DESC "
                f"LIMIT {limit}"
            )
        except RuntimeError:
            logger.debug("temporal search: memory query failed")
            return []

        results = []
        for m in mems:
            results.append({
                # Memory PK is `id` — map it to the result's entity_id.
                "entity_id": m.get("id", m.get("entity_id", "")),
                "entity_type": "memory",
                "content": m.get("content", ""),
                # Decay score: recency-only signal, deliberately small and
                # below semantic relevance. Starting at 1.0 let an arbitrarily
                # fresh memory outrank a genuine semantic match after fusion.
                # It now decays downward from 0.35 (min-max normalized by the
                # fusion layer, which also down-weights it to 0.05).
                "score": 0.35 * (1.0 - len(results) / max(limit + 1, 2)),
                "strategy": "temporal",
                "workspace_id": workspace_id,
            })

        return results

    def _keyword_fallback(
        self,
        workspace_id: str,
        query: str,
        memory_type: str,
        tier: str,
        limit: int,
        before: float | None = None,
        after: float | None = None,
    ) -> list[dict[str, Any]]:
        """Non-semantic keyword-only search fallback using client-side filtering.

        Searches both the ``memory`` table and the ``note`` table, merging
        results sorted by ``created_at`` descending.

        Args:
            before: Optional Unix timestamp — only return results with
                    ``created_at < before``.
            after: Optional Unix timestamp — only return results with
                    ``created_at > after``.
        """
        clauses = [f"workspace_id = '{_esc(workspace_id)}'"]
        if memory_type:
            clauses.append(f"memory_type = '{_esc(memory_type)}'")
        if tier:
            clauses.append(f"tier = '{_esc(tier)}'")
        filt = {}
        for clause in clauses:
            parts = clause.split(" = ", 1)
            if len(parts) == 2:
                key = parts[0].strip()
                val = parts[1].strip().strip("'")
                filt[key] = val
        rows = self._query("memory", workspace_id=workspace_id, filter_dict=filt)

        # Also fetch notes for keyword search
        note_rows = self._query("note", workspace_id=workspace_id, filter_dict={})
        for nr in note_rows:
            nr["entity_type"] = "note"
            nr["entity_id"] = nr["id"]

        if query:
            keywords = tokenize_query(query)
            if keywords:
                rows = [
                    r
                    for r in rows
                    if any(
                        kw in r.get("content", "").lower() or kw in r.get("summary", "").lower()
                        for kw in keywords
                    )
                ]
                note_rows = [
                    nr
                    for nr in note_rows
                    if any(
                        kw in nr.get("content", "").lower() or kw in nr.get("title", "").lower()
                        for kw in keywords
                    )
                ]

        # Tag memory rows with entity_type for consistency
        for r in rows:
            r["entity_type"] = r.get("entity_type", "memory")
        # Merge, deduplicate by (entity_type, entity_id), sort by created_at desc
        seen: dict[tuple[str, str], dict] = {}
        for r in rows + note_rows:
            et = r.get("entity_type", "memory")
            eid = r.get("entity_id") or r.get("id", "")
            key = (et, eid)
            if key not in seen or r.get("created_at", 0) > seen[key].get("created_at", 0):
                seen[key] = r
        all_rows = list(seen.values())
        all_rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        results = all_rows[:limit]
        # Assign baseline fused_score for entity-aware boosting
        max_idx = max(len(results) - 1, 1)
        for idx, r in enumerate(results):
            r["fused_score"] = 1.0 - (idx / max_idx)
        # Add content snippets for callers that only need a preview
        for r in results:
            content_text = (
                r.get("content", "") or r.get("memory_content", "") or r.get("summary", "")
            )
            r["snippet"] = _make_snippet(content_text)
        # Apply entity-aware boosting with entity_link alias support
        if query:
            results = self._boost_with_entity_signal(query, results, workspace_id)
        self._emit_event(
            "search.performed",
            {
                "query": query,
                "result_count": len(results),
            },
            workspace_id=workspace_id,
        )
        # ── Date range filter (before/after) ──
        if before is not None or after is not None:
            filtered = []
            for r in results:
                ts = r.get("created_at")
                if ts is None:
                    continue
                if before is not None and not (ts < before):
                    continue
                if after is not None and not (ts > after):
                    continue
                filtered.append(r)
            results = filtered
        return results

    def search(
        self,
        workspace_id: str,
        query: str = "",
        memory_type: str = "",
        tier: str = "",
        limit: int = 20,
        semantic: bool = True,
        rerank: bool = False,
        rerank_endpoint: str | None = None,
        rerank_model: str | None = None,
        rerank_api_key: str | None = None,
        cross_encoder: bool = True,
        query_expansion: bool = False,
        polyphonic: bool = False,
        mmr_lambda: float = 0.0,
        fusion_weights: dict[str, float] | None = None,
        entity_types: list[str] | None = None,
        temporal_filter: dict[str, Any] | None = None,
        before: float | None = None,
        after: float | None = None,
        relative_time: str | None = None,
        return_schema: str | type | None = None,
    ) -> list[dict[str, Any]]:
        """Search memories.  When *semantic* is True uses hybrid search.

        Args:
            temporal_filter: Optional dict with ``"from"`` and/or ``"to"`` keys
                    (Unix timestamps) to filter results by creation time.
                    Shorthand for ``before``/``after`` — entries are used
                    only when the corresponding explicit param is not set.
                    Example: ``{"from": 1700000000, "to": 1700086400}``.
            rerank: If True, passes top results through an LLM reranker
                    (QMD-style) for relevance re-scoring.
            rerank_endpoint: OpenAI-compatible base URL for reranker
                    (default: ``LLM_RERANK_ENDPOINT`` env var).
            rerank_model: Model name for reranker
                    (default: ``LLM_RERANK_MODEL`` env var).
            rerank_api_key: API key for reranker
                    (default: ``LLM_RERANK_API_KEY`` or ``OPENAI_API_KEY`` env var).
            cross_encoder: If True (default), passes top results through a local ONNX
                    cross-encoder (ms-marco-MiniLM-L-6-v2) for discriminative
                    relevance scoring. Falls back gracefully if model files are
                    not available.
            query_expansion: If True, expands the query with synonyms and
                    related terms via LLM before searching.
            polyphonic: If True, uses Reciprocal Rank Fusion (RRF) with
                    diversity penalty instead of min-max normalization.
            mmr_lambda: If > 0, applies Maximal Marginal Relevance reranking.
                    0.7 is a good default (70% relevance, 30% diversity).
            fusion_weights: Optional dict of strategy weights for min-max fusion.
                    Keys: ``"semantic"``, ``"keyword"``, ``"binary"``, ``"graph"``, ``"temporal"``.
                    Values should sum to ~1.0. Omit or pass None to use defaults.
            entity_types: Optional list of entity_type values to filter results by.
                    e.g. ``["memory", "note"]`` to return only memories and notes,
                    or ``["node"]`` for KG nodes only. Applied after fusion and
                    enrichment, in both hybrid and keyword-fallback paths.
            before: Optional Unix timestamp — only return results with
                    ``created_at < before``.
            after: Optional Unix timestamp — only return results with
                    ``created_at > after``.
            return_schema: If ``"llm"``, returns ``list[LLMSearchResult]`` with compact
                    fields (id, content, relevance, type, snippet, created_at).
                    If a ``TypedDict`` subclass, keeps only the annotated fields.
                    ``None`` (default) returns raw dicts unchanged.
        """
        # -- Resolve temporal_filter into before/after --
        if temporal_filter is not None:
            if after is None and "from" in temporal_filter:
                after = temporal_filter["from"]
            if before is None and "to" in temporal_filter:
                before = temporal_filter["to"]

        # -- Enforce workspace access (ACL gate) --
        # Search reads public content tables via SQL for performance, so the
        # reducer hot loop is avoided; but that means workspace privacy must
        # be enforced explicitly. check_workspace_access is a single cheap
        # reducer call (auth + membership check) — it raises for non-members
        # of private workspaces and passes for members or public workspaces.
        if workspace_id:
            try:
                self._call("check_workspace_access", [workspace_id])
            except RuntimeError:
                raise
            except Exception:
                # Unknown error from the gate (e.g. reducer absent on an old
                # module) — fail closed: do not silently search a workspace
                # whose access we could not verify.
                raise RuntimeError(
                    f"Access denied: could not verify access to workspace '{workspace_id}'"
                )

        # -- Resolve relative_time expressions (date-math querying) --
        # Supports: "7d" (last 7 days), "30d", "1w", "2m", "1y",
        #           "yesterday", "today", "last week", "last month", "last year"
        if relative_time and before is None:
            import re as _re
            now_ts = time.time()
            rt = str(relative_time).lower().strip()

            # Numeric expressions: 7d, 30d, 1w, 2m, 1y
            m = _re.match(r'^(\d+)\s*([dwmoy])$', rt)
            if m:
                val = int(m.group(1))
                unit = m.group(2)
                unit_map = {'d': 86400, 'w': 604800, 'm': 2592000, 'o': 2592000, 'y': 31536000}
                after = now_ts - val * unit_map.get(unit, 86400)
            elif rt in ('yesterday',):
                after = now_ts - 86400
            elif rt in ('today',):
                import datetime as _dt
                today_start = _dt.datetime.now(_dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                after = today_start
            elif rt in ('last week', 'last_week', '1w'):
                after = now_ts - 604800
            elif rt in ('last month', 'last_month', '1m'):
                after = now_ts - 2592000
            elif rt in ('last year', 'last_year', '1y'):
                after = now_ts - 31536000
            elif rt in ('this week', 'this_week'):
                import datetime as _dt
                today = _dt.datetime.now(_dt.UTC)
                monday = today - _dt.timedelta(days=today.weekday())
                after = monday.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            elif rt in ('this month', 'this_month'):
                import datetime as _dt
                month_start = _dt.datetime.now(_dt.UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
                after = month_start

        if semantic:
            # ── Query cache check ──
            cache_key: str | None = None
            if self._query_cache is not None:
                cache_key = self._query_cache.make_key(workspace_id, query, limit, "semantic")
                cached = self._query_cache.get(cache_key)
                if cached is not None:
                    return cached

            # ── Query expansion (pre-search) ──
            search_query = query
            if query_expansion and query:
                search_query = expand_query(query)
                # If expansion returned gibberish, fall back
                if not search_query or len(search_query.strip()) < 3:
                    search_query = query

            # BGE models need query instruction prefix for asymmetric search.
            query_text = f"Represent this sentence for searching relevant passages: {search_query}"
            emb = self._embed(query_text)
            emb_json = json.dumps(emb) if emb else "[]"

            # Check embedder health — if down, exclude semantic strategy and warn
            embedder_down = not emb
            if not embedder_down and emb:
                # Double-check: try a health ping. Strip /v1 if present since
                # health endpoints typically live at the root, not under /v1.
                health_url = self.embedder_url.rstrip("/")
                if "/v1" in health_url:
                    health_url = health_url.replace("/v1", "")

                base = _os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
                if base and _os.environ.get("OPENAI_API_KEY"):
                    # Proxy health check: strip /v1 to get the root
                    health_url = base.replace("/v1", "") if "/v1" in base else base
                try:
                    health = self._http.get(
                        f"{health_url}/health",
                        timeout=2.0,
                    )
                    embedder_down = health.status_code >= 400
                except httpx.ConnectError:
                    embedder_down = True
                except httpx.TimeoutException:
                    embedder_down = True

            # ── Client-side semantic search ──
            # Moved from WASM reducer to Python for ~10x speedup:
            # WASM does O(n) JSON-parsed embedding comparison per row (~85ms each)
            # Python does it in pure-Python loops (~5ms per 60 rows with numpy-lite)
            # The reducer semantic strategy still works as fallback if embedder is down,
            # but by default we do it client-side for speed.
            do_client_side_semantic = not embedder_down and emb_json != "[]"
            strategies_list = ["keyword", "graph", "temporal"]
            if not do_client_side_semantic and not embedder_down:
                # Fallback: let the reducer handle semantic search
                strategies_list.insert(0, "semantic")
            elif embedder_down:
                logger.warning(
                    "Embedder sidecar unreachable — semantic search disabled. "
                    "Using keyword+graph+temporal only."
                )

            # ── Over-fetch (Mem0 pattern): fetch a large candidate pool ──
            # The cross-encoder needs plenty of candidates.  Min-max fusion
            # breaks on huge sets (all low scores collapse to same range),
            # so we fuse on a managed subset and let the cross-encoder handle
            # the rest.
            fetch_limit = max(limit * 6, 120)
            fusion_limit = max(limit * 4, 30)

            with _tracing_span(
                "search.hybrid",
                workspace_id=workspace_id,
                query_length=len(search_query),
                fetch_limit=fetch_limit,
            ):
                # ── Parallel: client-side graph/temporal search + Tantivy ──
                # NOTE: We do NOT call the hybrid_search STDB reducer to avoid
                # "Module energy budget exhausted" errors. All search strategies
                # are now computed client-side via SQL reads (which are free):
                #   - keyword → Tantivy sidecar (:9091)
                #   - semantic → SQL read on search_index + Python cosine similarity
                #   - graph → SQL query on kg_edge + kg_node
                #   - temporal → SQL query on memory (created_at ordering)

                # Client-side graph search: find KG nodes matching query,
                # then fetch memories linked to those nodes
                graph_rows: list[dict[str, Any]] = []
                try:
                    graph_rows = self._graph_search_client_side(
                        workspace_id, search_query, memory_type, limit=fusion_limit
                    )
                except Exception as graph_err:
                    logger.debug("search: client-side graph search failed (%s), skipping", graph_err)

                # Client-side temporal search: fetch recent memories
                temporal_rows: list[dict[str, Any]] = []
                try:
                    temporal_rows = self._temporal_search_client_side(
                        workspace_id, memory_type, limit=fusion_limit
                    )
                except Exception as temp_err:
                    logger.debug("search: client-side temporal search failed (%s), skipping", temp_err)

            # No reducer call — hybrid_result table is empty.
            # All results come from client-side strategies below.
            rows: list[dict[str, Any]] = []
            # Normalize each strategy to [0,1] via min-max, then weighted sum.
            # Semantic (0.65): strongest signal — bge-m3 (1024d)
            # Keyword (0.25): Tantivy's real Okapi BM25 with stemming + IDF.
            # Binary (0.05): MIB binary vector Hamming similarity — fast, orthogonal signal.
            # Graph (0.00), temporal (0.05): removed — graph is substring-matching
            #   and temporal is recency-only. Neither contributes meaningfully.
            #   All signal from semantic (0.65) + Tantivy keyword (0.25).
            STRATEGY_WEIGHTS = fusion_weights or {
                "semantic": 0.55,
                "keyword": 0.30,
                "binary": 0.05,
                "graph": 0.05,
                "temporal": 0.05,
            }

            # ── Fetch Tantivy keyword results ──
            tantivy_hits = self._tantivy_search(workspace_id, search_query, limit=fetch_limit)
            # Convert Tantivy hits to the same shape as STDB hybrid_result rows
            tantivy_rows: list[dict[str, Any]] = []
            for th in tantivy_hits:
                tantivy_rows.append(
                    {
                        "entity_id": th.get("entity_id", ""),
                        "entity_type": th.get("entity_type", "memory"),
                        "content": th.get("content", ""),
                        "score": float(th.get("score", 0.0)),
                        "strategy": "keyword",
                        "workspace_id": workspace_id,
                    }
                )

            # Compute min/max per strategy — but only on a capped subset.
            # Over-fetching dumps hundreds of low-score keyword matches
            # (0.125 per single-word hit) that collapse the min-max range.
            per_strat: dict[str, list[dict]] = {
                "keyword": [],  # Tantivy rows go here
                "semantic": [],
                "graph": [],
                "temporal": [],
                "binary": [],
            }

            # Sort Tantivy rows by score desc, take top fusion_limit
            tantivy_rows.sort(key=lambda r: r["score"], reverse=True)
            per_strat["keyword"] = tantivy_rows[:fusion_limit]

            # ── Binary vector similarity (MIB Hamming distance) ──
            # Compute once against the query embedding, reuse for all candidates
            # Reuse the embedding computed above instead of calling _embed again
            query_emb = emb
            if query_emb and self._binary_cache:
                from ..binary_vectors import binarize, hamming_similarity

                try:
                    query_binary = binarize(query_emb)
                    binary_rows: list[dict[str, Any]] = []
                    for eid, cached_binary in self._binary_cache.items():
                        sim = hamming_similarity(query_binary, cached_binary)
                        if sim > 0.5:  # Only include meaningful matches
                            binary_rows.append(
                                {
                                    "entity_id": eid,
                                    "entity_type": "memory",
                                    "score": sim,
                                    "strategy": "binary",
                                    "workspace_id": workspace_id,
                                }
                            )
                    binary_rows.sort(key=lambda r: r["score"], reverse=True)
                    per_strat["binary"] = binary_rows[:fusion_limit]
                except (ValueError, Exception):
                    logger.warning("search: binary scoring failed, skipping binary results")

            # ── Client-side semantic search ──
            # Compute cosine similarity in Python instead of in the WASM reducer.
            # This avoids O(n) JSON-parsed embedding + memory lookup per row in STDB.
            if do_client_side_semantic:
                try:
                    query_vec = json.loads(emb_json)
                    semantic_rows: list[dict[str, Any]] = []
                    # Fetch all search_index rows for this workspace
                    si_rows = self._sql(
                        "SELECT * FROM search_index "
                        f"WHERE workspace_id = '{_esc(workspace_id)}'"
                    )
                    # Pre-fetch memory trust_scores in one batch
                    # Note: STDB SQL doesn't support IN () for string columns,
                    # so we fetch all workspace memories and filter in Python.
                    mem_ids = set(
                        r["entity_id"] for r in si_rows
                        if r.get("entity_type") == "memory"
                    )
                    trust_scores: dict[str, float] = {}
                    if mem_ids:
                        mem_rows_all = self._sql(
                            "SELECT id, trust_score FROM memory "
                            f"WHERE workspace_id = '{_esc(workspace_id)}'"
                        )
                        for mr in mem_rows_all:
                            trust_scores[mr["id"]] = float(mr.get("trust_score", 0.5))
                    for si in si_rows:
                        si_emb_str = si.get("embedding_json", "")
                        if not si_emb_str or si_emb_str in ("[]", "null", ""):
                            continue
                        si_vec = json.loads(si_emb_str)
                        if len(si_vec) != len(query_vec):
                            continue
                        si_norm = math.sqrt(sum(x * x for x in si_vec))
                        if len(query_vec) == 0 or si_norm == 0.0:
                            continue
                        score = cosine_similarity(query_vec, si_vec)
                        if score < 0.1:
                            continue
                        # Weight by trust_score (0.5x–1.0x multiplier)
                        trust = trust_scores.get(si.get("entity_id", ""), 0.5)
                        weighted = score * (0.5 + trust * 0.5)
                        semantic_rows.append({
                            "entity_id": si.get("entity_id", ""),
                            "entity_type": si.get("entity_type", "memory"),
                            "content": si.get("content", ""),
                            "score": weighted,
                            "strategy": "semantic",
                            "workspace_id": workspace_id,
                        })
                    semantic_rows.sort(key=lambda r: r["score"], reverse=True)
                    per_strat["semantic"] = semantic_rows[:fusion_limit]
                except (ValueError, json.JSONDecodeError, Exception) as sem_err:
                    logger.warning(
                        "search: client-side semantic search failed (%s), "
                        "falling back to reducer semantic strategy",
                        sem_err,
                    )
                    # No fallback to reducer — skip semantic on failure
                    # (client-side SQL reads are free; reducer calls exhaust energy budget)

            # Add client-side graph and temporal search rows to the fusion pool
            # (semantic and keyword are already in per_strat from above)
            if 'graph_rows' in dir() and graph_rows:
                for r in graph_rows:
                    strat = r.get("strategy", "graph")
                    if strat in per_strat and len(per_strat[strat]) < fusion_limit:
                        per_strat[strat].append(r)
            if 'temporal_rows' in dir() and temporal_rows:
                for r in temporal_rows:
                    strat = r.get("strategy", "temporal")
                    if strat in per_strat and len(per_strat[strat]) < fusion_limit:
                        per_strat[strat].append(r)

            # Add STDB rows for semantic, graph, temporal (from old reducer path)
            for r in rows:
                s = r.get("strategy", "")
                if s in per_strat and len(per_strat[s]) < fusion_limit:
                    per_strat[s].append(r)

            strat_min: dict[str, float] = {}
            strat_max: dict[str, float] = {}
            for s, s_rows in per_strat.items():
                for r in s_rows:
                    sc = float(r.get("score", 0.0))
                    strat_min[s] = min(strat_min.get(s, float("inf")), sc)
                    strat_max[s] = max(strat_max.get(s, float("-inf")), sc)

            # ── Weighted min-max fusion + dedup ──
            rows = self._fuse_and_deduplicate(
                rows,
                tantivy_rows,
                per_strat,
                strat_min,
                strat_max,
                STRATEGY_WEIGHTS,
                polyphonic=polyphonic,
            )

            # ── Look up content and apply veracity weighting ──
            rows = self._enrich_content(rows, workspace_id)

            # ── Entity-aware search result boosting (mem0 v3 parity) ──
            rows = self._boost_with_entity_signal(query, rows, workspace_id, boost_factor=0.40)

            # ── KG context injection: find entities in query, inject connected memories ──
            try:
                from ..entity_linking import inject_entity_context
                rows = inject_entity_context(
                    self, workspace_id, query, rows, boost_factor=0.30, max_entity_memories=10
                )
            except ImportError:
                pass  # entity_linking not available — skip

            # ── Entity_types filter (after fusion, before reranking) ──
            if entity_types is not None and entity_types:
                rows = [r for r in rows if r.get("entity_type") in entity_types]

            # ── Date range filter (before/after) ──
            if before is not None or after is not None:
                filtered = []
                for r in rows:
                    ts = r.get("created_at")
                    if ts is None:
                        continue
                    if before is not None and not (ts < before):
                        continue
                    if after is not None and not (ts > after):
                        continue
                    filtered.append(r)
                rows = filtered

            if cross_encoder:
                try:
                    from ..cross_encoder import cross_encoder_rerank

                    rows = cross_encoder_rerank(query, rows, top_k=len(rows))
                except (FileNotFoundError, ImportError, ValueError) as ce_err:
                    logger.warning(
                        "Cross-encoder unavailable (%s). "
                        "Install onnxruntime and download model files.",
                        ce_err,
                    )
            if rerank:
                rows = llm_rerank(
                    query,
                    rows,
                    endpoint=rerank_endpoint,
                    model=rerank_model,
                    api_key=rerank_api_key,
                    top_k=min(20, len(rows)),
                    plugin_manager=self.plugin_manager,
                )
            # ── MMR diversity reranking ──
            if mmr_lambda > 0:
                from spacetime_memory.mmr import mmr_rerank

                rows = mmr_rerank(rows, lambda_param=mmr_lambda)
            # ── Weibull temporal boost ──
            from spacetime_memory.weibull import apply_temporal_boost

            rows = apply_temporal_boost(rows)
            # ── Enrich rows with entities_json ──
            self._enrich_entities_json(rows, workspace_id)
            results = rows[:limit]
            # ── Plugin dispatch: on_search ──
            if self.plugin_manager is not None:
                _, results = self.plugin_manager.dispatch_search(query, results)
            # ── Query cache store ──
            if self._query_cache is not None and cache_key is not None:
                self._query_cache.set(cache_key, results, workspace_id=workspace_id)
            # ── Emit search.performed event ──
            self._emit_event(
                "search.performed",
                {
                    "query": query,
                    "result_count": len(results),
                },
                workspace_id=workspace_id,
            )
            if return_schema is not None:
                results = _apply_return_schema(results, return_schema)
            return results

        # Non-semantic (keyword) search via Tantivy BM25 sidecar (~1ms vs ~28ms WASM BM25)
        # Replaces the old _keyword_fallback which did client-side substring matching.
        tantivy_hits = self._tantivy_search(workspace_id, query, limit=limit)
        rows = []
        seen_ids: set[str] = set()
        for th in tantivy_hits:
            eid = th.get("entity_id", "")
            if eid and eid not in seen_ids:
                seen_ids.add(eid)
                rows.append(
                    {
                        "entity_id": eid,
                        "entity_type": th.get("entity_type", "memory"),
                        "content": th.get("content", ""),
                        "score": float(th.get("score", 0.0)),
                        "workspace_id": workspace_id,
                        "created_at": th.get("created_at"),
                    }
                )
            if len(rows) >= limit:
                break
        if not rows and query:
            # Fallback: client-side substring matching if Tantivy is unreachable
            logger.warning(
                "Tantivy sidecar returned no results for query=%r — falling back to _keyword_fallback",
                query,
            )
            rows = self._keyword_fallback(
                workspace_id, query, memory_type, tier, limit, before=before, after=after
            )
        if entity_types is not None and entity_types:
            rows = [r for r in rows if r.get("entity_type") in entity_types]
        # ── Date range filter (before/after) — Graphiti-parity temporal filtering ──
        # Uses valid_from/valid_to (valid-time range) instead of created_at (transaction time).
        if before is not None or after is not None:
            filtered = []
            for r in rows:
                vf = r.get("valid_from", r.get("created_at"))
                vt = r.get("valid_to", r.get("created_at"))
                if vf is None:
                    continue
                if before is not None and not (vf < before):
                    continue
                if after is not None and vt is not None and not (vt > after):
                    continue
                filtered.append(r)
            rows = filtered

        # ── Enrich rows with entities_json from memory table ──
        # Tantivy/Tantivy-fallback doesn't store entities_json, but the
        # memory table does. Batch-fetch for any rows that are missing it.
        self._enrich_entities_json(rows, workspace_id)

        if return_schema is not None:
            rows = _apply_return_schema(rows, return_schema)
        return rows

    def _enrich_entities_json(
        self,
        rows: list[dict],
        workspace_id: str,
    ) -> None:
        """Enrich search results with entities_json from the memory table.

        Tantivy/Tantivy-fallback results don't include entities_json,
        but the memory table does. This method batch-fetches and enriches.
        """
        entity_ids = set()
        for r in rows:
            if r.get("entity_id") or r.get("id"):
                entity_ids.add(r.get("entity_id", r.get("id", "")))
        if not entity_ids:
            return
        try:
            mem_rows = self._query("memory", workspace_id=workspace_id, filter_dict={})
            id_to_entities = {
                m.get("id", ""): m.get("entities_json", "")
                for m in mem_rows
                if m.get("id") in entity_ids
            }
            for r in rows:
                eid = r.get("entity_id", r.get("id", ""))
                if eid and eid in id_to_entities and not r.get("entities_json"):
                    r["entities_json"] = id_to_entities[eid]
        except Exception:
            logger.debug("_enrich_entities_json: enrichment failed for %d rows", len(rows))

    def _extract_and_store_entities(
        self,
        workspace_id: str,
        memory_id: str,
        content: str,
    ) -> None:
        """Extract entities from content and store in entity_link/kg_node.

        Tries LLM extraction first (requires OPENAI_API_KEY), falls back
        to the regex-based ``extract_entities`` reducer.
        """
        from .llm import LLMClient

        llm = LLMClient()
        entities = llm.extract_entities_llm(content) if llm.available else None

        if entities:
            for ent in entities:
                name = ent.get("name", "")
                if not name or len(name) < 2:
                    continue
                etype = ent.get("entity_type", "unknown")
                aliases = ent.get("aliases", [])
                description = ent.get("description", name)

                try:
                    self._call(
                        "create_entity_link",
                        [
                            workspace_id,
                            name,
                            etype,
                            json.dumps(aliases[:10] if aliases else []),
                            description,
                        ],
                    )
                except RuntimeError:
                    logger.warning("store(): LLM entity extraction call failed for memory %s", memory_id)

                # Link entity to the source memory
                try:
                    self._call(
                        "link_entity_to_memory",
                        [
                            name,
                            memory_id,
                            etype,
                        ],
                    )
                except RuntimeError:
                    logger.warning("store(): link_entity_to_memory failed for entity '%s', memory %s", name, memory_id)
        else:
            # Fall back to regex-based extraction (no LLM key or LLM failed)
            try:
                self._call("extract_entities", [workspace_id, content])
            except RuntimeError:
                logger.warning("store(): regex entity extraction failed for memory %s", memory_id)

    def detect_patterns(
        self,
        workspace_id: str,
        *,
        limit: int = 200,
        include_clusters: bool = True,
        include_terms: bool = True,
        include_co_occur: bool = True,
    ) -> dict[str, Any]:
        """Run pattern detection on a workspace's memories.

        Args:
            workspace_id: The workspace to analyze.
            limit: Max memories to fetch for analysis.
            include_clusters: Run temporal clustering.
            include_terms: Run frequent term extraction.
            include_co_occur: Run co-occurrence detection.

        Returns:
            Dict with ``temporal_clusters``, ``frequent_terms``,
            ``co_occurrences``, ``total_memories``, ``summary``.
        """
        from ..pattern_detection import detect_patterns as _detect

        mems = self._query(
            "memory",
            workspace_id=workspace_id,
            filter_dict={},
        )
        mems = mems[:limit]
        return _detect(
            mems,
            include_clusters=include_clusters,
            include_terms=include_terms,
            include_co_occur=include_co_occur,
        )

    def search_with_filters(
        self,
        workspace_id: str,
        query: str = "",
        memory_type: str = "",
        tier: str = "",
        metadata_filter: str = "",
        location_filter: str = "",
        limit: int = 20,
        return_schema: str | type | None = None,
    ) -> list[dict[str, Any]]:
        """Search with metadata and location filters. Honcho parity.

        Args:
            return_schema: If ``"llm"``, returns ``list[LLMSearchResult]`` with compact
                    fields (id, content, relevance, type, snippet, created_at).
                    If a ``TypedDict`` subclass, keeps only the annotated fields.
                    ``None`` (default) returns raw dicts unchanged.
        """
        # For metadata/location filters, we do a keyword search first then filter in Python
        rows = self.search(workspace_id, query, memory_type, tier, limit, semantic=True, return_schema=return_schema)
        if metadata_filter:

            mf = (
                json.loads(metadata_filter) if isinstance(metadata_filter, str) else metadata_filter
            )
            filtered = []
            for r in rows:
                meta_str = r.get("metadata_json", "{}")
                try:
                    meta = json.loads(meta_str) if isinstance(meta_str, str) else meta_str
                except (json.JSONDecodeError, TypeError):
                    logger.debug("filter: failed to parse metadata_json, treating as empty")
                    meta = {}
                matches = all(meta.get(k) == v for k, v in mf.items())
                if matches:
                    filtered.append(r)
            rows = filtered[:limit]
        if location_filter:
            loc = location_filter.lower()
            rows = [
                r
                for r in rows
                if loc in r.get("content", "").lower() or loc in r.get("summary", "").lower()
            ][:limit]
        return rows

    def temporal_search_with_weight(
        self,
        workspace_id: str,
        query: str = "",
        memory_type: str = "",
        tier: str = "",
        limit: int = 20,
        recency_weight: float = 0.7,
        time_context: str = "",
        return_schema: str | type | None = None,
    ) -> list[dict[str, Any]]:
        """Time-weighted memory retrieval with configurable recency decay.

        Like the ``temporal`` strategy in :meth:`search`, but with:
        - Exponential recency boost controlled by ``recency_weight`` (0.0–1.0).
          Higher values penalize older memories more strongly.
          Default 0.7 provides a good balance (roughly corresponding to a
          7-day half-life with 70% recency influence).
        - ``time_context`` filters memories by age: "recent" (24h),
          "last_week", "last_month", "last_3_months", "last_year", or
          "" (no filter).

        Results are written to the ``HybridResult`` table with strategy
        ``temporal_weighted_<weight_int>``, keyed by a unique query hash
        that includes the recency_weight. Read back via SQL on
        ``hybrid_result`` filtered by workspace_id and query_hash.

        Args:
            workspace_id: The workspace to search.
            query: The search query (for query hash and optional semantic boosting).
            memory_type: Optional ``memory_type`` filter (e.g., "world_fact").
            tier: Optional tier filter ("L0", "L1", "L2").
            limit: Max results to return (default 20).
            recency_weight: How much to penalise old memories (0.0–1.0).
                0.0 = no recency bias, 1.0 = strong exponential decay.
            time_context: Temporal filter keyword as described above.
            return_schema: If ``"llm"``, returns ``list[LLMSearchResult]`` with compact
                    fields (id, content, relevance, type, snippet, created_at).
                    If a ``TypedDict`` subclass, keeps only the annotated fields.
                    ``None`` (default) returns raw dicts unchanged.

        Returns:
            List of hybrid_result rows matching the search.
        """
        emb_json = "[]"
        self._call(
            "temporal_search_with_weight",
            [
                workspace_id,
                query,
                emb_json,
                memory_type,
                tier,
                limit,
                recency_weight,
                time_context,
            ],
        )
        qhash = _query_hash(f"tw:{query}:{int(recency_weight * 100)}")
        rows = self._sql(
            "SELECT * FROM hybrid_result "
            f"WHERE workspace_id = '{_esc(workspace_id)}' "
            f"  AND query_hash = '{_esc(qhash)}' "
        )
        if return_schema is not None:
            rows = _apply_return_schema(rows, return_schema)
        return rows

    # -------------------------------------------------------------------
    # Cross-encoder re-ranking
    # -------------------------------------------------------------------

    def cross_encoder_rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        content_key: str = "memory_content",
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        """Cross-encoder re-rank candidates for more accurate relevance scoring.

        Uses the local ONNX cross-encoder model for re-ranking search results
        by semantic relevance to the query, beyond cosine-similarity.

        Args:
            query: The query string to evaluate relevance against.
            candidates: Array of candidate objects to re-rank.
            content_key: Key in each candidate dict containing the text (default "memory_content").
            top_k: Number of top candidates to return after re-ranking.

        Returns:
            Re-ranked candidates sorted by cross-encoder score (descending),
            each with a ``crossEncoderScore`` field added.
        """
        from ..cross_encoder import cross_encoder_rerank as _cross_encoder_rerank
        return _cross_encoder_rerank(
            query=query,
            candidates=candidates,
            content_key=content_key,
            top_k=top_k,
        )
