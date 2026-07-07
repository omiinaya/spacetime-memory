# flake8: noqa: F811
"""Memory storage, search, and management mixin."""
from __future__ import annotations

from typing import Any

from ._base import ClientBase, logger, _TRACER, _tracing_span, EmbedderUnavailableError, SpacetimeDBError, NotFoundError, ApiError
from ._utils import _esc, _query_hash, _parse_sql_response, _make_snippet
from ._rerank import _parse_rerank_json



class MemoryMixin:
    """Spacetime-Memory memory mixin.

    Provides Client methods related to memory management.
    Inherits from ClientBase for connection infrastructure.
    """
    pass
    def store(
        self,
        workspace_id: str,
        content: str = "",
        summary: str = "",
        memory_type: str = "experience",
        peer_id: str = "",
        observer_id: str = "",
        entities_json: str = "[]",
        confidence: float = 0.8,
        source_session_id: str = "",
        source_message_id: str = "",
        tier: str = "",
        veracity_tier: str = "",
        veracity_sources: int = 1,
    ) -> dict[str, Any]:
        """Store a memory. Auto-indexes via the embedder.

        Args:
            veracity_tier: Mnemosyne veracity tier — one of "stated",
                "unknown", "inferred", "imported", "tool". Overrides
                ``confidence`` using Bayesian compounding.
            veracity_sources: Number of independent confirmations of
                this fact (default 1 = no compounding). Used with
                ``veracity_tier`` to compute compounded confidence.
        """
        # Compute Bayesian confidence from veracity tier if provided
        if veracity_tier and veracity_tier != "unknown":
            from ..veracity import compound, VeracityTier

            try:
                tier_enum = VeracityTier(veracity_tier)
                confidence = compound(tier=tier_enum, sources=max(1, veracity_sources))
            except ValueError:
                logger.warning("Unknown VeracityTier string '%s', keeping default confidence", veracity_tier)

        # ── Plugin dispatch: on_store ──
        metadata: dict[str, Any] = {
            "memory_type": memory_type,
            "confidence": confidence,
            "tier": tier,
            "veracity_tier": veracity_tier,
        }
        if self.plugin_manager is not None:
            content, metadata = self.plugin_manager.dispatch_store(content, metadata)

        # ── Reducer call: store_memory ──
        with _tracing_span("store.call", workspace_id=workspace_id, memory_type=memory_type):
            result = self._call(
                "store_memory",
                [
                    workspace_id,
                    peer_id,
                    observer_id,
                    memory_type,
                    content,
                    summary,
                    entities_json,
                    confidence,
                    source_session_id,
                    source_message_id,
                ],
            )
        # ── Invalidate query cache for this workspace ──
        if self._query_cache is not None:
            self._query_cache.invalidate(workspace_id=workspace_id)

        # ── Emit memory.created event ──
        self._emit_event(
            "memory.created",
            {
                "content": content[:200],
                "summary": summary,
                "memory_type": memory_type,
                "workspace_id": workspace_id,
            },
            workspace_id=workspace_id,
        )

        # Index into Tantivy BM25 sidecar regardless of embedder availability.
        # The memory_id is resolved by content match after the store_memory reducer.
        mems_after = self._query(
            "memory", workspace_id=workspace_id, filter_dict={}, columns=["id", "content"]
        )
        memory_id_tantivy = ""
        for m in reversed(mems_after):
            if m.get("content", "") == content:
                memory_id_tantivy = m["id"]
                break
        if memory_id_tantivy:
            self._tantivy_index(workspace_id, memory_id_tantivy, content, "memory")

        # If the embedder is reachable, index embeddings in the sidecar
        emb = self._embed(content)
        if emb:
            # Use the already-resolved memory_id
            memory_id = memory_id_tantivy
            if memory_id:
                # Compute and cache MIB binary vector (32x compression)
                from .binary_vectors import binarize

                try:
                    self._binary_cache[memory_id] = binarize(emb)
                except (ValueError, Exception):
                    logger.warning("store_batch: binary compression failed for memory %s, skipping", memory_id)
                self._call(
                    "index_entity",
                    [
                        workspace_id,
                        "memory",
                        memory_id,
                        content,
                        json.dumps(emb),
                    ],
                )
                # Populate BM25 inverted index (legacy STDB term_index)
                self._call(
                    "index_terms",
                    [
                        workspace_id,
                        "memory",
                        memory_id,
                        content,
                    ],
                )

                # Entity extraction: LLM first, fall back to regex
                self._extract_and_store_entities(workspace_id, memory_id, content)

        if tier and tier in ("L0", "L1", "L2"):
            mems = self._query(
                "memory",
                workspace_id=workspace_id,
                filter_dict={"peer_id": peer_id},
                columns=["id"],
            )
            if mems:
                self._call("update_memory_tier", [mems[-1]["id"], tier])

        return result

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

    def store_batch(
        self,
        workspace_id: str,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Store multiple memories in a single reducer call.

        Embeds all items in one batch call to the embedder, then sends a
        single ``store_memory_batch`` reducer with all items.  Much faster
        than N sequential ``store()`` calls when the embedder sidecar is
        the bottleneck.

        After the STDB reducer, indexes all items into the Tantivy BM25
        sidecar in a single batch HTTP call (``/index/batch``) instead of
        N sequential calls.

        Args:
            workspace_id: Target workspace UUID.
            items: List of dicts, each with:
                - ``content`` (str, required)
                - ``summary`` (str, optional)
                - ``memory_type`` (str, default ``"experience"``)
                - ``peer_id`` (str, optional)
                - ``observer_id`` (str, optional)
                - ``entities_json`` (str, optional)
                - ``confidence`` (float, default 0.8)
                - ``source_session_id`` (str, optional)
                - ``source_message_id`` (str, optional)

        Returns:
            List of reducer result dicts.
        """
        # Extract contents for batch embedding
        contents = []
        clean_items = []
        for item in items:
            content = item.get("content", "")
            if not content:
                continue
            contents.append(content)
            clean_items.append(
                {
                    "workspace_id": workspace_id,
                    "peer_id": item.get("peer_id", ""),
                    "observer_id": item.get("observer_id", ""),
                    "memory_type": item.get("memory_type", "experience"),
                    "content": content,
                    "summary": item.get("summary", content[:200]),
                    "entities_json": item.get("entities_json", "[]"),
                    "confidence": item.get("confidence", 0.8),
                    "source_session_id": item.get("source_session_id", ""),
                    "source_message_id": item.get("source_message_id", ""),
                }
            )

        if not clean_items:
            return []

        # Batch-embed
        try:

            resp = self._http.post(
                f"{self.embedder_url}/embed",
                content=json.dumps({"texts": contents}),
                headers={"Content-Type": "application/json"},
                timeout=max(10.0 * len(contents), 30.0),
            )
            if resp.status_code < 400:
                emb_list = resp.json().get("embeddings", [])
                if not emb_list and resp.json().get("embedding"):
                    emb_list = [resp.json().get("embedding", [])]
            else:
                emb_list = []
        except RuntimeError:
            logger.warning("store_batch: get_embeddings_batch failed, returning empty embeddings")
            emb_list = []

        # Call batch reducer — pass items as JSON string

        with _tracing_span(
            "store_batch.call", workspace_id=workspace_id, batch_size=len(clean_items)
        ):
            self._call("store_memory_batch", [json.dumps(clean_items)])

        # Batch-index all items with embeddings via single reducer calls.
        # Query back the inserted memories by content prefix, then call
        # index_entity_batch and index_terms_batch instead of N individual calls.
        entity_items = []
        terms_items = []

        for i, item in enumerate(clean_items):
            emb = emb_list[i] if i < len(emb_list) else None
            if emb:
                entity_items.append({
                    "workspace_id": workspace_id,
                    "entity_type": "memory",
                    "entity_id": "",  # filled below after query
                    "content": item["content"],
                    "embedding_json": json.dumps(emb),
                })
                terms_items.append({
                    "workspace_id": workspace_id,
                    "entity_type": "memory",
                    "entity_id": "",  # filled below after query
                    "content": item["content"],
                })

        if entity_items:
            # Query all matching memories in one batch — match by content prefix
            mems = self._query(
                "memory",
                workspace_id=workspace_id,
                columns=["id", "content"],
            )
            # Build a map from content[:100] -> most recent memory id
            content_to_id: dict[str, str] = {}
            for m in sorted(
                mems,
                key=lambda x: x.get("created_at", 0),
                reverse=True,
            ):
                key = m.get("content", "")[:100]
                if key not in content_to_id:
                    content_to_id[key] = m["id"]

            # Fill in entity_ids
            for ei, ti in zip(entity_items, terms_items):
                mid = content_to_id.get(ei["content"][:100], "")
                ei["entity_id"] = mid
                ti["entity_id"] = mid

            # Single batch call to index_entity_batch (all items with embeddings)
            self._call("index_entity_batch", [json.dumps(entity_items)])

            # Single batch call to index_terms_batch (only items with matched IDs)
            valid_terms = [t for t in terms_items if t["entity_id"]]
            if valid_terms:
                self._call("index_terms_batch", [json.dumps(valid_terms)])

            # Single batch Tantivy index call — all items with matched IDs in one HTTP request
            tantivy_items = []
            for ei in entity_items:
                if ei["entity_id"]:
                    tantivy_items.append({
                        "workspace_id": workspace_id,
                        "entity_id": ei["entity_id"],
                        "content": ei["content"],
                        "entity_type": ei["entity_type"],
                    })
            if tantivy_items:
                self._tantivy_index_batch(tantivy_items)

            # Entity extraction is LLM-based — still per-item (not a reducer)
            for ei in entity_items:
                if ei["entity_id"]:
                    self._extract_and_store_entities(
                        workspace_id,
                        ei["entity_id"],
                        ei["content"],
                    )

        return [{"status": "ok"} for _ in clean_items]

    def _fuse_and_deduplicate(
        self,
        rows: list[dict[str, Any]],
        tantivy_rows: list[dict[str, Any]],
        per_strat: dict[str, list[dict]],
        strat_min: dict[str, float],
        strat_max: dict[str, float],
        strategy_weights: dict[str, float],
    ) -> list[dict[str, Any]]:
        """Min-max normalize per strategy, weighted-sum fuse, dedup by entity_id."""
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

    def _keyword_fallback(
        self,
        workspace_id: str,
        query: str,
        memory_type: str,
        tier: str,
        limit: int,
        before: float | int | None = None,
        after: float | int | None = None,
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
            _STOPWORDS = {
                "a",
                "an",
                "the",
                "is",
                "are",
                "was",
                "were",
                "be",
                "been",
                "who",
                "what",
                "where",
                "when",
                "why",
                "how",
                "which",
                "do",
                "does",
                "did",
                "has",
                "have",
                "had",
                "can",
                "will",
                "would",
                "tell",
                "me",
                "about",
                "of",
                "in",
                "on",
                "at",
                "to",
                "for",
                "with",
                "and",
                "or",
                "not",
                "we",
                "our",
                "us",
                "i",
                "you",
                "they",
                "it",
                "its",
                "s",
                "that",
                "this",
                "there",
                "from",
            }
            keywords = [
                w.lower().rstrip("?,.:;!\"'")
                for w in query.split()
                if len(w.rstrip("?,.:;!\"'")) > 1
                and w.lower().rstrip("?,.:;!\"'") not in _STOPWORDS
            ]
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

    # ------------------------------------------------------------------
    # Entity-aware search result boosting (mem0 v3 multi-signal parity)

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
        before: float | int | None = None,
        after: float | int | None = None,
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
        """
        # -- Resolve temporal_filter into before/after --
        if temporal_filter is not None:
            if after is None and "from" in temporal_filter:
                after = temporal_filter["from"]
            if before is None and "to" in temporal_filter:
                before = temporal_filter["to"]

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
                # Double-check: try a health ping. Use the OpenAI base URL
                # when embedding through the proxy, fall back to embedder_url.
                health_url = self.embedder_url
                import os as _os

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
                except (httpx.ConnectError, httpx.TimeoutException):
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
            strategies = json.dumps(strategies_list)

            # ── Over-fetch (Mem0 pattern): fetch a large candidate pool ──
            # The cross-encoder needs plenty of candidates.  Min-max fusion
            # breaks on huge sets (all low scores collapse to same range),
            # so we fuse on a managed subset and let the cross-encoder handle
            # the rest.
            fetch_limit = max(limit * 4, 60)
            fusion_limit = max(limit * 3, 20)

            with _tracing_span(
                "search.hybrid",
                workspace_id=workspace_id,
                query_length=len(search_query),
                fetch_limit=fetch_limit,
            ):
                self._call(
                    "hybrid_search",
                    [
                        workspace_id,
                        search_query,
                        emb_json,
                        memory_type,
                        tier,
                        fetch_limit,
                        strategies,
                    ],
                )
            qhash = _query_hash(search_query)
            rows = self._sql(
                "SELECT * FROM hybrid_result "
                f"WHERE workspace_id = '{_esc(workspace_id)}' "
                f"  AND query_hash = '{_esc(qhash)}' "
            )

            # ── Weighted min-max fusion ──
            # Normalize each strategy to [0,1] via min-max, then weighted sum.
            # Semantic (0.65): strongest signal — bge-m3 (1024d)
            # Keyword (0.25): Tantivy's real Okapi BM25 with stemming + IDF.
            # Binary (0.05): MIB binary vector Hamming similarity — fast, orthogonal signal.
            # Graph (0.00), temporal (0.05): removed — graph is substring-matching
            #   and temporal is recency-only. Neither contributes meaningfully.
            #   All signal from semantic (0.65) + Tantivy keyword (0.25).
            STRATEGY_WEIGHTS = fusion_weights or {
                "semantic": 0.65,
                "keyword": 0.25,
                "binary": 0.05,
                "graph": 0.00,
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
            query_emb = self._embed(search_query)
            if query_emb and self._binary_cache:
                from .binary_vectors import binarize, hamming_similarity

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
                import math
                try:
                    query_vec = json.loads(emb_json)
                    qnorm = math.sqrt(sum(x * x for x in query_vec))
                    semantic_rows: list[dict[str, Any]] = []
                    # Fetch all search_index rows for this workspace
                    si_rows = self._sql(
                        "SELECT * FROM search_index "
                        f"WHERE workspace_id = '{_esc(workspace_id)}'"
                    )
                    # Pre-fetch memory trust_scores in one batch
                    mem_ids = set(
                        r["entity_id"] for r in si_rows
                        if r.get("entity_type") == "memory"
                    )
                    trust_scores: dict[str, float] = {}
                    if mem_ids:
                        for mid in mem_ids:
                            mem_rows = self._sql(
                                "SELECT trust_score FROM memory "
                                f"WHERE id = '{_esc(mid)}'"
                            )
                            if mem_rows:
                                trust_scores[mid] = float(mem_rows[0].get("trust_score", 0.5))
                    for si in si_rows:
                        si_emb_str = si.get("embedding_json", "")
                        if not si_emb_str or si_emb_str in ("[]", "null", ""):
                            continue
                        si_vec = json.loads(si_emb_str)
                        if len(si_vec) != len(query_vec):
                            continue
                        si_norm = math.sqrt(sum(x * x for x in si_vec))
                        if qnorm == 0.0 or si_norm == 0.0:
                            continue
                        dot = sum(a * b for a, b in zip(query_vec, si_vec))
                        score = max(0.0, min(1.0, dot / (qnorm * si_norm)))
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
                    # Fallback: re-run with semantic in strategies
                    strategies_list = ["semantic", "keyword", "graph", "temporal"]
                    strategies = json.dumps(strategies_list)
                    self._call(
                        "hybrid_search",
                        [
                            workspace_id,
                            search_query,
                            emb_json,
                            memory_type,
                            tier,
                            fetch_limit,
                            strategies,
                        ],
                    )
                    # Re-fetch rows after fallback re-run
                    rows = self._sql(
                        "SELECT * FROM hybrid_result "
                        f"WHERE workspace_id = '{_esc(workspace_id)}' "
                        f"  AND query_hash = '{_esc(qhash)}' "
                    )

            # Add STDB rows for semantic, graph, temporal (plus legacy keyword
            # as fallback — any row not in Tantivy still participates)
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
            )

            # ── Look up content and apply veracity weighting ──
            rows = self._enrich_content(rows, workspace_id)

            # ── Entity-aware search result boosting (mem0 v3 parity) ──
            rows = self._boost_with_entity_signal(query, rows, workspace_id)

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
                    from .cross_encoder import cross_encoder_rerank

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
                )
            # ── MMR diversity reranking ──
            if mmr_lambda > 0:
                from .mmr import mmr_rerank

                rows = mmr_rerank(rows, lambda_param=mmr_lambda)
            # ── Weibull temporal boost ──
            from .weibull import apply_temporal_boost

            rows = apply_temporal_boost(rows)
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
        # ── Date range filter (before/after) — only needed in non-semantic path ──
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
        return rows

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
        from .pattern_detection import detect_patterns as _detect

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

    def search_sessions_semantic(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Semantically search across all sessions/workspaces.

        Embes the query, calls the ``search_sessions_semantic`` reducer,
        and reads results from the ``session_search_result`` table.

        Falls back to an empty list when no embedder is available.
        """
        emb = self._embed(query)
        if not emb:
            return []

        emb_json = json.dumps(emb)
        self._call("search_sessions_semantic", [emb_json, limit])

        qhash = f"sessions:{limit}"
        rows = self._sql(f"SELECT * FROM session_search_result WHERE query_hash = '{_esc(qhash)}'")
        rows.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        return rows[:limit]

    def get_memory(self, memory_id: str) -> list[dict[str, Any]]:
        """Get a single memory by ID.  Auto-reinforces on read."""
        results = self._query("memory", filter_dict={"id": memory_id})
        if results:
            try:
                self._call("reinforce_memory", [memory_id])
            except RuntimeError:
                logger.warning("reinforce_memory: _call failed for memory %s", memory_id)
        return results

    def fuzzy_get(
        self,
        workspace_id: str,
        name: str,
        *,
        field: str = "content",
        threshold: float = 0.5,
        limit: int = 50,
    ) -> dict[str, Any] | None:
        """Find the closest-matching memory by string similarity (QMD parity).

        Fetches up to *limit* memories from the workspace and uses
        ``difflib.SequenceMatcher`` to find the one whose *field* value is
        most similar to *name*.

        Returns the best match if similarity >= *threshold*, otherwise
        ``None``.

        Args:
            workspace_id: The workspace to search.
            name: The target name to fuzzy-match against.
            field: Which memory field to compare (default ``\"content\"``).
            threshold: Minimum similarity ratio (0.0–1.0, default 0.5).
            limit: Max memories to scan (default 50).
        """
        from difflib import SequenceMatcher

        rows = self._query(
            "memory",
            workspace_id=workspace_id,
            filter_dict={},
        )
        if not rows:
            return None

        best = None
        best_ratio = 0.0
        for r in rows[:limit]:
            text = r.get(field, "")
            if not text:
                continue
            ratio = SequenceMatcher(
                None, name.lower(), text.lower()
            ).ratio()  # isjunk=None: treat all chars equally
            if ratio > best_ratio:
                best_ratio = ratio
                best = r

        if best and best_ratio >= threshold:
            return best
        return None

    def glob_get(
        self,
        workspace_id: str,
        pattern: str,
        *,
        field: str = "id",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return all memories matching a glob pattern (QMD parity).

        Uses ``fnmatch``-style wildcards (``*``, ``?``, ``[...]``) against
        the specified *field*.  Example::

            c.glob_get(\"ws-1\", \"auth-*\")      # IDs starting with \"auth-\"
            c.glob_get(\"ws-1\", \"auth-*\", field=\"content\")  # content match

        Args:
            workspace_id: The workspace to search.
            pattern: Glob pattern (e.g. ``\"journals/2025-05*\"``,
                     ``\"*auth*\"``).
            field: Which memory field to match against (default ``\"id\"``).
            limit: Max memories to scan (default 200).

        Returns:
            List of matching memory dicts (empty list if none match).
        """
        from fnmatch import fnmatch

        rows = self._query(
            "memory",
            workspace_id=workspace_id,
            filter_dict={},
        )
        matches = []
        for r in rows[:limit]:
            val = r.get(field, "")
            if isinstance(val, str) and fnmatch(val.lower(), pattern.lower()):
                matches.append(r)
        return matches

    def update_memory(
        self,
        memory_id: str,
        content: str,
        summary: str = "",
        confidence: float = 0.8,
        expires_at: int | None = None,
    ) -> dict[str, Any]:
        """Update a memory's content/summary/confidence.

        Parameters
        ----------
        memory_id:
            Target memory ID.
        content:
            New body text.
        summary:
            New short summary (default ``""`` = no summary).
        confidence:
            New confidence score 0.0–1.0 (default ``0.8``).
        expires_at:
            Expiration timestamp in microseconds (epoch).
            Special values:
            - ``None`` (default): preserve the current expiration.
            - ``0``: clear expiration (memory never expires).
            - ``>0``: set to the given absolute timestamp.

        Note
        ----
        This method sends 5 arguments when ``expires_at`` is explicitly set,
        or 4 arguments when ``expires_at`` is ``None`` (default).  The 4-arg
        form is backward-compatible with pre-``expires_at`` WASM binaries.
        The 5-arg form requires the ``expires_at`` reducer (rebuilt WASM).
        """  # noqa: E501
        if expires_at is None:
            # Backward-compatible: 4-arg call may fail on newer WASM that expects 5.
            # Try 5-arg with 0 (no expiration change = preserve current).
            return self._call(
                "update_memory",
                [memory_id, content, summary, confidence, 0],
            )
        # Forward-looking 5-arg call (requires rebuilt WASM with expires_at support)
        return self._call(
            "update_memory",
            [memory_id, content, summary, confidence, expires_at],
        )

    def delete_memory(self, memory_id: str) -> dict[str, Any]:
        """Deactivate a memory. Idempotent — succeeds if already deleted."""
        # ── Look up workspace_id for cache invalidation ──
        ws_id: str | None = None
        if self._query_cache is not None:
            rows = self._sql(f"SELECT workspace_id FROM memory WHERE id = '{_esc(memory_id)}'")
            if rows:
                ws_id = str(rows[0].get("workspace_id", ""))

        try:
            result = self._call("deactivate_memory", [memory_id])
            # ── Invalidate query cache ──
            if self._query_cache is not None and ws_id:
                self._query_cache.invalidate(workspace_id=ws_id)
            # ── Emit memory.deleted event ──
            self._emit_event(
                "memory.deleted",
                {
                    "memory_id": memory_id,
                },
                workspace_id=ws_id or "",
            )
            return result
        except RuntimeError as e:
            if "not found" in str(e).lower():
                return {"status": "ok", "note": "already deleted"}
            raise

    def batch_delete_memories(self, memory_ids: list[str]) -> dict[str, Any]:
        """Batch-deactivate multiple memories in a single reducer call.

        Much faster than N sequential ``delete_memory()`` calls because it
        sends all IDs in one network round-trip to the
        ``batch_delete_memories`` reducer.

        Parameters
        ----------
        memory_ids:
            List of memory ID strings to deactivate. Missing IDs are
            silently skipped (idempotent).

        Returns
        -------
        Dict with ``status``: ``"ok"`` on success.
        """
        if not memory_ids:
            return {"status": "ok", "note": "no IDs provided"}
        return self._call("batch_delete_memories", [json.dumps(memory_ids)])

    def update_memory_tier(self, memory_id: str, tier: str) -> dict[str, Any]:
        """Change a memory's compression tier.

        Parameters
        ----------
        memory_id:
            Target memory ID.
        tier:
            New tier. Must be one of ``"L0"``, ``"L1"``, or ``"L2"``.
            L0 = highest importance / shortest retention window,
            L2 = lowest importance / longest retention window.
        """
        if tier not in ("L0", "L1", "L2"):
            raise ValueError(f"Invalid tier '{tier}'. Must be L0, L1, or L2.")
        return self._call("update_memory_tier", [memory_id, tier])

    def set_memory_scope(self, memory_id: str, user_scope: str) -> dict[str, Any]:
        """Scope an existing memory to a specific user identity for isolation.

        Parameters
        ----------
        memory_id:
            The UUID of the memory to scope.
        user_scope:
            The user identity hash to scope the memory to. Pass empty string
            to make the memory shared/unscoped.
        """
        return self._call("set_memory_scope", [memory_id, user_scope])

    def set_workspace_context(self, workspace_id: str, context: str) -> dict[str, Any]:
        """Attach a context string to a workspace for QMD-style context trees."""
        return self._call("set_workspace_context", [workspace_id, context])

    def set_memory_context(self, memory_id: str, context: str) -> dict[str, Any]:
        """Attach a context string to a memory for QMD-style context trees."""
        return self._call("set_memory_context", [memory_id, context])

    def get_context_chain(self, memory_id: str) -> dict[str, Any]:
        """Return the context chain for a memory: workspace context + memory context."""
        mems = self._query(
            "memory", filter_dict={"id": memory_id}, columns=["id", "workspace_id", "context"]
        )
        if not mems:
            return {"workspace_context": "", "memory_context": ""}
        ws_id = mems[0].get("workspace_id", "")
        mem_ctx = mems[0].get("context", "")

        ws_ctx = ""
        if ws_id:
            wss = self._query("workspace", filter_dict={"id": ws_id}, columns=["context"])
            if wss:
                ws_ctx = wss[0].get("context", "")

        return {
            "workspace_context": ws_ctx,
            "memory_context": mem_ctx,
        }

    def reinforce(self, memory_id: str) -> dict[str, Any]:
        """Reinforce a memory (bump access_count + strength)."""
        return self._call("reinforce_memory", [memory_id])

    def rate_memory(self, memory_id: str, rating: str, peer_id: str) -> dict[str, Any]:
        """Rate a memory to adjust its trust score.

        Args:
            memory_id: The memory to rate.
            rating: "helpful" (score 5), "unhelpful" (score 1),
                    or an integer string "1"–"5" for graded feedback.
            peer_id: The peer submitting the rating.
        """
        return self._call("rate_memory", [memory_id, rating, peer_id])

    def escalate_memories(
        self, workspace_id: str, l2_to_l1: int = 5, l1_to_l0: int = 20
    ) -> dict[str, Any]:
        """Batch-escalate memory tiers based on access_count thresholds.

        Args:
            workspace_id: The workspace to escalate memories in.
            l2_to_l1: Access count threshold for L2→L1 escalation (default: 5).
            l1_to_l0: Access count threshold for L1→L0 escalation (default: 20).
        """
        return self._call("escalate_memories", [workspace_id, l2_to_l1, l1_to_l0])

    def list_memories(
        self, workspace_id: str, memory_type: str = "", limit: int = 50
    ) -> list[dict[str, Any]]:
        """List active memories in a workspace."""
        filt = {}
        if memory_type:
            filt["memory_type"] = memory_type
        rows = self._query("memory", workspace_id=workspace_id, filter_dict=filt)
        rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        return rows[:limit]

    def get_user_memories(self, user_scope: str, workspace_id: str) -> list[dict[str, Any]]:
        """Get all memories scoped to a specific user within a workspace.

        Calls the ``get_user_memories`` reducer which populates the
        ``user_memory_result`` table, then reads from it.

        Args:
            user_scope: The user identity hash to filter by.
            workspace_id: The workspace to search in.

        Returns:
            List of memory records scoped to the given user.
        """
        self._call("get_user_memories", [user_scope, workspace_id])
        rows = self._sql(
            "SELECT * FROM user_memory_result WHERE "
            f"user_scope = '{_esc(user_scope)}' AND "
            f"workspace_id = '{_esc(workspace_id)}'"
        )
        return rows

    # -----------------------------------------------------------------------
    # Directory (context directory tree)
    # -----------------------------------------------------------------------

    def list_directory(self, directory_id: str) -> list[dict[str, Any]]:
        """Get children of a directory."""
        self._call("get_children", [directory_id, True])
        return self._sql(
            f"SELECT * FROM directory_result WHERE query_hash = '{_esc(directory_id)}'"
        )

    def traverse_directory(self, workspace_id: str, root_directory_id: str) -> list[dict[str, Any]]:
        """Recursive BFS traversal of directory tree."""
        self._call("traverse_recursive", [workspace_id, root_directory_id])
        return self._sql(
            f"SELECT * FROM directory_result WHERE query_hash = '{_esc(root_directory_id)}'"
        )

    def get_directory(self, workspace_id: str, path_or_id: str) -> list[dict[str, Any]]:
        """Get a directory by ID or path."""
        self._call("get_directory", [workspace_id, path_or_id])
        return self._sql(
            f"SELECT * FROM directory_result WHERE workspace_id = '{_esc(workspace_id)}'"
        )

    def create_directory(
        self, workspace_id: str, name: str, path: str, parent_id: str = "", description: str = ""
    ) -> dict[str, Any]:
        """Create a directory in the context directory tree."""
        return self._call("create_directory", [workspace_id, name, path, parent_id, description])

    def link_memory_to_directory(
        self, directory_id: str, memory_id: str, workspace_id: str
    ) -> dict[str, Any]:
        """Link a memory to a directory."""
        return self._call("link_memory_to_directory", [directory_id, memory_id, workspace_id])

    def unlink_memory_from_directory(self, directory_id: str, memory_id: str) -> dict[str, Any]:
        """Unlink a memory from a directory."""
        return self._call("unlink_memory_from_directory", [directory_id, memory_id])

    def search_directory_contents(
        self, workspace_id: str, directory_path: str
    ) -> list[dict[str, Any]]:
        """Recursively search directory contents.

        Finds a directory by path, recursively collects all subdirectories
        and memory entries within the tree, and returns the result.

        Args:
            workspace_id: Target workspace.
            directory_path: Path of the root directory to search.

        Returns:
            List with a single DirectoryContentResult dict containing:
            id, workspace_id, directory_path, directory_id,
            subdirectory_ids_json (JSON array of sub-directory IDs),
            memory_ids_json (JSON array of contained memory IDs),
            created_at.
        """
        self._call("search_directory_contents", [workspace_id, directory_path])
        return self._sql(
            f"SELECT * FROM directory_content_result "
            f"WHERE workspace_id = '{_esc(workspace_id)}' "
            f"AND directory_path = '{_esc(directory_path)}' "
            f"ORDER BY created_at DESC LIMIT 1"
        )

    # -----------------------------------------------------------------------
    # Batch update & history (Mem0 parity)
    # -----------------------------------------------------------------------

    def batch_update_memories(
        self, workspace_id: str, memory_ids: list[str], updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Batch update multiple memories. Mem0 parity.
        updates can contain: content, summary, confidence, tier, is_active,
        expires_at

        Performs client-side batching: loops over each memory_id and
        calls the existing ``update_memory`` reducer individually.
        """
        updated = 0
        errors: list[str] = []
        for mem_id in memory_ids:
            try:
                # Fetch current memory to preserve unchanged fields
                current_rows = self._query(
                    "memory",
                    filter_dict={"id": mem_id},
                )
                if not current_rows:
                    errors.append(f"Memory '{mem_id}' not found")
                    continue
                current = current_rows[0]
                mem_ws = current.get("workspace_id", "")
                if workspace_id and mem_ws and mem_ws != workspace_id:
                    errors.append(f"Memory '{mem_id}' not in workspace '{workspace_id}'")
                    continue
                content = updates.get("content", current.get("content", ""))
                summary = updates.get("summary", current.get("summary", ""))
                confidence = updates.get("confidence", current.get("confidence", 0.8))
                expires_at = updates.get("expires_at", 0)
                self.update_memory(mem_id, content, summary, confidence, expires_at)
                updated += 1
            except Exception as e:
                errors.append(f"Memory '{mem_id}': {e}")

        if errors:
            return {"status": "partial", "updated": updated, "errors": errors}
        return {"status": "ok", "updated": updated}

    def get_memory_history(self, memory_id: str) -> list[dict[str, Any]]:
        """Get version history for a memory. Mem0 parity.

        Returns revision history from the ``memory_revision`` table,
        ordered by version ascending.  Each entry shows what changed
        in that revision (previous vs new content/summary/confidence).

        The current (latest) state is appended as the final entry
        with no ``previous_*`` fields.
        """
        # Fetch revision history from the memory_revision table
        revisions = self._query(
            "memory_revision",
            filter_dict={"memory_id": memory_id},
        )
        # Sort by version ascending
        revisions.sort(key=lambda r: r.get("version", 0))

        result: list[dict[str, Any]] = []
        for rev in revisions:
            result.append(
                {
                    "version": rev.get("version", 0),
                    "previous_content": rev.get("previous_content", ""),
                    "previous_summary": rev.get("previous_summary", ""),
                    "previous_confidence": rev.get("previous_confidence", 1.0),
                    "content": rev.get("new_content", ""),
                    "summary": rev.get("new_summary", ""),
                    "confidence": rev.get("new_confidence", 1.0),
                    "changed_at": rev.get("changed_at", 0),
                    "changed_by": rev.get("changed_by", ""),
                }
            )

        # Append the current state as the latest version
        rows = self._query(
            "memory",
            filter_dict={"id": memory_id},
            columns=["content", "summary", "version", "updated_at", "confidence"],
        )
        if rows:
            r = rows[0]
            current_version = r.get("version", 1)
            # Only append if we don't already have this version
            if not result or result[-1].get("version") != current_version:
                result.append(
                    {
                        "version": current_version,
                        "previous_content": "",
                        "previous_summary": "",
                        "previous_confidence": 0.0,
                        "content": r.get("content", ""),
                        "summary": r.get("summary", ""),
                        "confidence": r.get("confidence", 1.0),
                        "changed_at": r.get("updated_at", 0),
                        "changed_by": "",
                    }
                )

        return result

    def get_note_history(self, note_id: str) -> list[dict[str, Any]]:
        """Get version history for a note.

        Returns revision history from the ``note_revision`` table,
        ordered by version ascending.  Each entry shows what changed
        in that revision (previous vs new title/content).

        The current (latest) state is appended as the final entry
        with no ``previous_*`` fields.
        """
        # Fetch revision history from the note_revision table
        revisions = self._query(
            "note_revision",
            filter_dict={"note_id": note_id},
        )
        # Sort by version ascending
        revisions.sort(key=lambda r: r.get("version", 0))

        result: list[dict[str, Any]] = []
        for rev in revisions:
            result.append(
                {
                    "version": rev.get("version", 0),
                    "previous_title": rev.get("previous_title", ""),
                    "previous_content": rev.get("previous_content", ""),
                    "title": rev.get("new_title", ""),
                    "content": rev.get("new_content", ""),
                    "changed_at": rev.get("changed_at", 0),
                    "changed_by": rev.get("changed_by", ""),
                }
            )

        # Append the current state as the latest version
        rows = self._query(
            "note",
            filter_dict={"id": note_id},
            columns=["title", "content", "version", "updated_at"],
        )
        if rows:
            r = rows[0]
            current_version = r.get("version", 1)
            # Only append if we don't already have this version
            if not result or result[-1].get("version") != current_version:
                result.append(
                    {
                        "version": current_version,
                        "previous_title": "",
                        "previous_content": "",
                        "title": r.get("title", ""),
                        "content": r.get("content", ""),
                        "changed_at": r.get("updated_at", 0),
                        "changed_by": "",
                    }
                )

        return result

    # -----------------------------------------------------------------------
    # Reputation decay configuration (Weibull / Linear)
    # -----------------------------------------------------------------------

    def set_decay_model(
        self,
        workspace_id: str,
        model: str = "linear",
        decay_rate: float = 0.005,
        max_days: int = 90,
        weibull_shape: float = 0.6,
        weibull_scale: float = 30.0,
    ) -> dict[str, Any]:
        """Configure the decay model for a workspace.

        Args:
            workspace_id: Workspace to configure.
            model: ``"linear"`` (default) or ``"weibull"``.
            decay_rate: For linear — fraction of trust to decay per day (e.g. 0.005 = 0.5%/day).
            max_days: For linear — max age in days before trust hits floor.
            weibull_shape: For Weibull — k parameter (< 1 = rapid-then-slow forgetting, default 0.6).
            weibull_scale: For Weibull — λ parameter (characteristic time in days, default 30.0).

        Returns:
            The reducer response.
        """
        if model not in ("linear", "weibull"):
            raise ValueError(f"Unknown decay model '{model}'. Use 'linear' or 'weibull'.")

        if model == "linear":
            return self._call(
                "apply_reputation_decay",
                [
                    workspace_id,
                    decay_rate,
                    max_days,
                ],
            )
        else:
            return self._call(
                "apply_weibull_decay",
                [
                    workspace_id,
                    weibull_shape,
                    weibull_scale,
                ],
            )

    def get_decay_config(self, workspace_id: str) -> dict[str, Any] | None:
        """Get the current decay configuration for a workspace.

        Returns None if no config has been set yet.
        """
        rows = self._query("workspace_config", filter_dict={"id": workspace_id})
        if rows:
            return rows[0]
        return None

    def recommend_memories(
        self,
        workspace_id: str,
        limit: int = 20,
        min_urgency: float = 0.3,
    ) -> list[dict[str, Any]]:
        """Recommend memories that need attention (review, reinforce, discard).

        Returns memories sorted by urgency — low-trust, decaying, or
        consistently-poor memories that need human attention.

        Args:
            workspace_id: Target workspace.
            limit: Max recommendations (default 20).
            min_urgency: Minimum urgency threshold 0.0–1.0 (default 0.3).
        """
        self._call(
            "recommend_memories",
            [
                workspace_id,
                limit,
                min_urgency,
            ],
        )
        # Public result table — queryable via SQL directly
        return self._sql(
            f"SELECT * FROM memory_recommendation WHERE workspace_id = '{_esc(workspace_id)}'"
        )

    def get_peer_reputation(self, peer_id: str) -> dict[str, Any] | None:
        """Get reputation stats for a peer.

        Calls the get_peer_reputation reducer and reads the result
        from the peer_reputation_result table.
        Returns None if the peer has no feedback history.
        """
        self._call("get_peer_reputation", [peer_id])
        rows = self._sql(
            "SELECT * FROM peer_reputation_result WHERE "
            f"peer_id = '{_esc(peer_id)}'"
        )
        if rows:
            return rows[0]
        return None

    # -----------------------------------------------------------------------
    # Document management (Supermemory parity)
    # -----------------------------------------------------------------------

    def create_document(
        self,
        workspace_id: str,
        title: str,
        content: str = "",
        content_type: str = "text",
        file_path: str = "",
        source_url: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a document with auto-chunking.

        Documents with content ≥ 100 chars are automatically split into
        overlapping ~500-char chunks (sentence-boundary-aware).

        Args:
            workspace_id: Target workspace.
            title: Document title.
            content: Document body text. Auto-chunked if ≥ 100 chars.
            content_type: ``"text"``, ``"pdf"``, ``"image"``, ``"video"``, ``"code"``, or ``"url"``.
            file_path: Optional file path reference.
            source_url: Optional source URL.
            metadata: Optional metadata dict (serialized to JSON).
        """
        meta_json = json.dumps(metadata or {})
        return self._call(
            "create_document",
            [
                workspace_id,
                title,
                content,
                content_type,
                file_path,
                source_url,
                meta_json,
            ],
        )

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """Get a document by ID."""
        rows = self._query("document", filter_dict={"id": doc_id})
        if rows:
            return rows[0]
        return None

    def list_documents(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all documents in a workspace."""
        return self._query("document", filter_dict={"workspace_id": workspace_id})

    def get_document_chunks(self, doc_id: str) -> list[dict[str, Any]]:
        """Get all chunks for a document, ordered by chunk_index."""
        rows = self._query("doc_chunk", filter_dict={"document_id": doc_id})
        rows.sort(key=lambda r: r.get("chunk_index", 0))
        return rows

    def delete_document(self, doc_id: str) -> dict[str, Any]:
        """Delete a document and all its chunks (cascading)."""
        return self._call("delete_document", [doc_id])

    # -----------------------------------------------------------------------
    # Knowledge graph pattern detection
    # -----------------------------------------------------------------------

    def detect_bridge_nodes(
        self,
        workspace_id: str,
        limit: int = 20,
        min_communities: int = 2,
    ) -> list[dict[str, Any]]:
        """Detect bridge nodes — concepts that connect multiple communities.

        Returns nodes sorted by bridge score (higher = more integrative).
        """
        self._call(
            "detect_bridge_nodes",
            [
                workspace_id,
                limit,
                min_communities,
            ],
        )
        # Public result table — queryable via SQL directly
        return self._sql(f"SELECT * FROM bridge_result WHERE workspace_id = '{_esc(workspace_id)}'")

    def compute_kg_stats(self, workspace_id: str) -> dict[str, Any] | None:
        """Compute knowledge graph statistics for a workspace.

        Returns a single stats row with node_count, edge_count,
        community_count, orphan_nodes, avg_degree, etc.
        """
        self._call("compute_kg_stats", [workspace_id])
        # Public result table — queryable via SQL directly
        rows = self._sql(
            f"SELECT * FROM kg_stats_result WHERE workspace_id = '{_esc(workspace_id)}'"
        )
        if rows:
            return rows[0]
        return None

    def get_memory_stats(self, workspace_id: str) -> dict[str, Any] | None:
        """Collect per-workspace memory metrics.

        Stats returned:
        - ``total_memories`` — count of all memories
        - ``active_memories`` — count of active memories
        - ``by_tier`` — JSON map of tier → count (L0, L1, L2)
        - ``by_type`` — JSON map of memory_type → count
        - ``avg_confidence`` — average confidence score
        - ``avg_age_seconds`` — average age in seconds
        - ``total_revisions`` — number of memory revisions
        - ``top_tags`` — JSON array of top-10 used tags
        - ``total_users`` — count of distinct user_scope values

        Returns a dict of stat_key → stat_value, or ``None`` if no stats
        were computed.
        """
        self._call("get_memory_stats", [workspace_id])
        # Public result table — queryable via SQL directly
        rows = self._sql(
            f"SELECT * FROM workspace_memory_stats_result WHERE workspace_id = '{_esc(workspace_id)}'"
        )
        if rows:
            return {r["stat_key"]: r["stat_value"] for r in rows}
        return None

    # -----------------------------------------------------------------------
    # Search with metadata/location filters (Honcho parity)
    # -----------------------------------------------------------------------

    def search_with_filters(
        self,
        workspace_id: str,
        query: str = "",
        memory_type: str = "",
        tier: str = "",
        metadata_filter: str = "",
        location_filter: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search with metadata and location filters. Honcho parity."""
        # For metadata/location filters, we do a keyword search first then filter in Python
        rows = self.search(workspace_id, query, memory_type, tier, limit, semantic=True)
        if metadata_filter:

            mf = (
                json.loads(metadata_filter) if isinstance(metadata_filter, str) else metadata_filter
            )
            filtered = []
            for r in rows:
                meta_str = r.get("metadata_json", "{}")
                try:
                    meta = json.loads(meta_str) if isinstance(meta_str, str) else meta_str
                except Exception:
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

    # -----------------------------------------------------------------------
    # Knowledge Graph
    # -----------------------------------------------------------------------

    def temporal_search_with_weight(
        self,
        workspace_id: str,
        query: str = "",
        memory_type: str = "",
        tier: str = "",
        limit: int = 20,
        recency_weight: float = 0.7,
        time_context: str = "",
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
        return self._sql(
            "SELECT * FROM hybrid_result "
            f"WHERE workspace_id = '{_esc(workspace_id)}' "
            f"  AND query_hash = '{_esc(qhash)}' "
        )

    # -----------------------------------------------------------------------
    # Merge suggestions
    # -----------------------------------------------------------------------

    def get_peer_sessions(self, peer_id: str) -> list[dict[str, Any]]:
        """List sessions a peer has participated in."""
        # Query session_participant to find session IDs, then fetch each session
        parts = self._query("session_participant", filter_dict={"peer_id": peer_id})
        rows = []
        for sp in parts:
            sessions = self._query("session", filter_dict={"id": sp.get("session_id", "")})
            for s in sessions:
                s["role"] = sp.get("role", "")
                s["joined_at"] = sp.get("joined_at", 0)
                rows.append(s)
        rows.sort(key=lambda r: r.get("joined_at", 0), reverse=True)
        return rows

    def get_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieve messages for a session."""
        rows = self._query("message", filter_dict={"session_id": session_id})
        rows.sort(key=lambda r: r.get("created_at", 0))
        return rows

    def get_session_steps(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieve all reasoning steps for a session.

        Calls the ``get_session_steps`` reducer which writes to the
        ``session_step_result`` table, then queries that table.

        Args:
            session_id: The session to get steps for.

        Returns:
            A list of step dicts ordered by creation time, each with keys:
            query_hash, id, session_id, workspace_id, step_type, content,
            summary, parent_step_id, created_at.
        """
        self._call("get_session_steps", [session_id])
        query_hash = f"steps:{session_id}"
        rows = self._query("session_step_result", filter_dict={"query_hash": query_hash})
        rows.sort(key=lambda r: r.get("created_at", 0))
        return rows

    def add_agent_step(
        self,
        session_id: str,
        workspace_id: str,
        step_type: str,
        content: str,
        summary: str = "",
        parent_step_id: str = "",
    ) -> dict[str, Any]:
        """Record an agent reasoning step (thought, action, tool_call, etc.).

        Calls the ``add_agent_step`` reducer to append a reasoning step to a
        session's chain of thought.

        Args:
            session_id: The session to attach the step to.
            workspace_id: The workspace containing the session.
            step_type: One of ``"thought"``, ``"action"``, ``"observation"``,
                ``"tool_call"``, or ``"tool_result"``.
            content: The step content (text or JSON).
            summary: Optional short summary of the step.
            parent_step_id: Optional parent step ID for chain-of-thought
                linking.

        Returns:
            The reducer status dict. On success the calling tool can extract
            the created step id from the ``"id"`` key.
        """
        return self._call(
            "add_agent_step",
            [session_id, workspace_id, step_type, content, summary, parent_step_id],
        )

    # -----------------------------------------------------------------------
    # Profiles
    # -----------------------------------------------------------------------

    def create_tag(self, workspace_id: str, name: str, color: str = "#808080") -> None:
        """Create a new tag for organizing memories.

        Args:
            workspace_id: Target workspace.
            name: Tag display name.
            color: Hex color string (default: ``"#808080"``).
        """
        self._call("create_tag", [workspace_id, name, color])

    def tag_memory(self, memory_id: str, tag_id: str) -> None:
        """Attach a tag to a memory.

        Args:
            memory_id: The memory to tag.
            tag_id: The tag to attach.
        """
        self._call("tag_memory", [memory_id, tag_id])

    def untag_memory(self, memory_id: str, tag_id: str) -> None:
        """Remove a tag from a memory.

        Args:
            memory_id: The tagged memory.
            tag_id: The tag to detach.
        """
        self._call("untag_memory", [memory_id, tag_id])

    def batch_tag_memories(self, tag_id: str, memory_ids: list[str]) -> dict[str, Any]:
        """Batch-attach a tag to multiple memories in a single reducer call.

        Eliminates O(n) network round-trips for bulk tagging by sending all
        memory IDs in one call to the ``batch_tag_memories`` reducer.

        Args:
            tag_id: The tag to attach.
            memory_ids: List of memory ID strings to tag. Already-tagged
                memories are silently skipped (idempotent).

        Returns:
            Dict with ``status``: ``"ok"`` on success.
        """
        if not memory_ids:
            return {"status": "ok", "note": "no memory IDs provided"}
        return self._call("batch_tag_memories", [tag_id, json.dumps(memory_ids)])

    def batch_untag_memories(self, tag_id: str, memory_ids: list[str]) -> dict[str, Any]:
        """Batch-remove a tag from multiple memories in a single reducer call.

        Eliminates O(n) network round-trips for bulk untagging by sending all
        memory IDs in one call to the ``batch_untag_memories`` reducer.

        Args:
            tag_id: The tag to detach.
            memory_ids: List of memory ID strings to untag. Missing
                associations are silently skipped (idempotent).

        Returns:
            Dict with ``status``: ``"ok"`` on success.
        """
        if not memory_ids:
            return {"status": "ok", "note": "no memory IDs provided"}
        return self._call("batch_untag_memories", [tag_id, json.dumps(memory_ids)])

    def list_tags(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all tags in a workspace.

        Args:
            workspace_id: Target workspace.

        Returns:
            List of tag dicts with id, workspace_id, name, color, created_at.
        """
        # Note: the list_tags reducer was changed to return () for STDB v2.6 compat.
        # We now query the tag table directly via _query.
        self._call("list_tags", [workspace_id])  # auth gate
        return self._query("tag", workspace_id=workspace_id, columns=["id", "workspace_id", "name", "color", "created_at"])

    def delete_tag(self, tag_id: str) -> None:
        """Delete a tag and all its memory associations.

        Args:
            tag_id: The tag ID to delete.
        """
        self._call("delete_tag", [tag_id])

    def list_tags_by_memory(self, memory_id: str) -> list[dict[str, Any]]:
        """List all tags attached to a specific memory.

        Calls the ``list_tags_by_memory`` reducer which writes to the
        ``memory_tag_result`` table, then queries that table.

        Args:
            memory_id: The memory to look up tags for.

        Returns:
            A list of dicts with keys: id, memory_id, tag_id, tag_name, tag_color.
        """
        self._call("list_tags_by_memory", [memory_id])
        return self._sql(
            f"SELECT id, memory_id, tag_id, tag_name, tag_color "
            f"FROM memory_tag_result "
            f"WHERE memory_id = '{_esc(memory_id)}'"
        )

    def update_tag(self, tag_id: str, name: str = "", color: str = "#808080") -> None:
        """Update a tag's name and/or color.

        Args:
            tag_id: The tag ID to update.
            name: New display name (empty string leaves unchanged).
            color: New hex color string.
        """
        self._call("update_tag", [tag_id, name, color])

    def search_by_tags(
        self,
        workspace_id: str,
        tag_ids: list[str],
        query: str = "",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search memories by tag filter, optionally with semantic ranking.

        Only memories that have ALL specified tags are returned (intersection).

        Args:
            workspace_id: Target workspace.
            tag_ids: List of tag IDs to filter by (AND intersection).
            query: Optional query string for semantic ranking. Pass empty
                string to skip semantic similarity (results ordered by recency).
            limit: Maximum number of results.

        Returns:
            List of hybrid_result rows matching all tags, sorted by
            relevance (if query provided) or recency.
        """
        # Get embedding if query provided
        emb_json = "[]"
        if query:
            query_text = (
                f"Represent this sentence for searching relevant passages: {query}"
            )
            emb = self._embed(query_text)
            emb_json = json.dumps(emb) if emb else "[]"

        tag_ids_json = json.dumps(tag_ids)
        self._call(
            "search_by_tags",
            [
                workspace_id,
                tag_ids_json,
                emb_json,
                limit,
            ],
        )
        qhash = _query_hash(f"tagged:{tag_ids_json}")
        return self._sql(
            "SELECT * FROM hybrid_result "
            f"WHERE workspace_id = '{_esc(workspace_id)}' "
            f"  AND query_hash = '{_esc(qhash)}' "
            "ORDER BY score DESC"
        )

    # -------------------------------------------------------------------
    # Connector Configuration
    # -------------------------------------------------------------------

