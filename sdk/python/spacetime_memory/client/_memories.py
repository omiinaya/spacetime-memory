"""Memory storage, search, and management mixin."""
from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Any

from ._base import _tracing_span, logger
from ._utils import _esc


def _skip_entity_extract() -> bool:
    """True when bulk/benchmark callers disable per-store entity extraction."""
    return os.environ.get("STDB_SKIP_ENTITY_EXTRACT", "").strip() == "1"


def _normalize_images(
    images: str | list[str] | None = None,
    images_json: str = "",
    context: str = "store",
) -> str:
    """Normalize image input into a JSON-serialised string of URLs/data URIs.

    Accepts:
      - ``images=None`` or ``images=""`` -> returns ``images_json`` (legacy).
      - ``images="https://..."`` -> single URL wrapped in JSON array.
      - ``images=["https://...", ...]`` -> list of URLs/data URIs.
      - ``images="/path/to/file.png"`` -> file path read and converted
        to a ``data:image/...;base64,...`` URI.
      - ``images_json`` -> fallback if ``images`` is empty/falsy.

    Returns a JSON string (empty string if no images) so downstream
    reducer calls that store context remain unchanged.
    """
    resolved: list[str] | None = None

    if images is not None and images != "" and images != []:
        raw = images

        if isinstance(raw, str):
            # Already a JSON array string?
            if raw.startswith("[") and raw.endswith("]"):
                return raw  # passthrough
            # File path that exists?
            if os.path.isfile(raw):
                path = Path(raw)
                mime_type, _ = mimetypes.guess_type(str(path))
                if mime_type is None:
                    mime_type = "image/png"
                raw_bytes = path.read_bytes()
                b64 = base64.b64encode(raw_bytes).decode("ascii")
                resolved = [f"data:{mime_type};base64,{b64}"]
            else:
                # Treat as a URL
                resolved = [raw]
        elif isinstance(raw, list):
            resolved = []
            for item in raw:
                if os.path.isfile(item):
                    path = Path(item)
                    mime_type, _ = mimetypes.guess_type(str(path))
                    if mime_type is None:
                        mime_type = "image/png"
                    raw_bytes = path.read_bytes()
                    b64 = base64.b64encode(raw_bytes).decode("ascii")
                    resolved.append(f"data:{mime_type};base64,{b64}")
                else:
                    resolved.append(item)
    else:
        if images_json:
            return images_json
        return ""

    return json.dumps(resolved)


class MemoryMixin:
    """Spacetime-Memory memory mixin.

    Provides Client methods related to memory management.
    Inherits from ClientBase for connection infrastructure.
    """
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
        images_json: str = "",
        images: str | list[str] | None = None,
        dedup: bool = False,
        dedup_threshold: float = 0.95,
    ) -> dict[str, Any]:
        """Store a memory. Auto-indexes via the embedder.

        Args:
            veracity_tier: Mnemosyne veracity tier -- one of "stated",
                "unknown", "inferred", "imported", "tool". Overrides
                ``confidence`` using Bayesian compounding.
            veracity_sources: Number of independent confirmations of
                this fact (default 1 = no compounding). Used with
                ``veracity_tier`` to compute compounded confidence.
            images_json: JSON string of image attachments to associate
                with this memory (e.g., URLs or base64 data URIs).
                Stored in the ``context`` field.  Pass "" (default)
                to store no images.
            dedup: Zero-scheduler dedup-on-write. When True, run a semantic
                duplicate check before inserting; if a near-duplicate
                (similarity >= ``dedup_threshold``) exists in the workspace,
                reinforce it and return ``{"status": "reinforced", ...}``
                instead of inserting a duplicate.
            dedup_threshold: Cosine similarity threshold for dedup (0.95
                catches near-verbatim duplicates only).

        Returns:
            Dict with at least ``id`` — the real memory id (resolved from the
            reducer-written ``memory_insert_result`` table, with a
            content-match fallback).
        """
        # Compute Bayesian confidence from veracity tier if provided
        if veracity_tier and veracity_tier != "unknown":
            from ..veracity import VeracityTier, compound

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

        # ── Normalize image attachments ──
        images_json = _normalize_images(images=images, images_json=images_json, context="store")

        # ── Zero-scheduler dedup-on-write (opt-in) ──
        if dedup:
            try:
                pre_hits = self.search(workspace_id=workspace_id, query=content, semantic=True, limit=1)
                pre_results = pre_hits.get("results", []) if isinstance(pre_hits, dict) else (pre_hits or [])
                if pre_results:
                    top = pre_results[0]
                    top_score = top.get("score") or top.get("similarity") or 0.0
                    if top_score >= dedup_threshold:
                        dup_id = top.get("id") or top.get("memory_id") or top.get("entity_id")
                        if dup_id:
                            try:
                                self._call("reinforce_memory", [dup_id])
                            except Exception:
                                logger.warning("dedup: reinforce failed for %s", dup_id)
                            return {
                                "status": "reinforced",
                                "id": dup_id,
                                "deduplicated": True,
                                "score": top_score,
                            }
            except Exception:
                logger.warning("dedup: pre-store duplicate check failed, proceeding with insert")

        # ── Reducer call: store_memory ──
        # NOTE: images_json is normalized above but the Rust store_memory reducer
        # doesn't accept it as a separate arg yet. Wire it through the context
        # field when the reducer is updated.
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
                    # When bulk/benchmark ingestion disables entity extraction,
                    # pass a valid-JSON sentinel the reducer treats as "entities
                    # already provided" (it skips its regex extraction for
                    # anything non-empty and != "[]"). Saves the regex + O(n²)
                    # KG co-occurrence edge pass on every bulk store (~20s/chunk).
                    "[{}]" if _skip_entity_extract() else entities_json,
                    confidence,
                    source_session_id,
                    source_message_id,
                    images_json,
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
        # Resolve the real memory id via the reducer-written memory_insert_result
        # table (deterministic), falling back to content match (legacy).
        memory_id_tantivy = ""
        try:
            insert_rows = self._query(
                "memory_insert_result",
                workspace_id=workspace_id,
                filter_dict={"workspace_id": workspace_id},
            )
            prefix = content[:100]
            best_row = None
            for row in insert_rows:
                if row.get("content_prefix", "") == prefix:
                    if best_row is None or row.get("created_at", 0) > best_row.get("created_at", 0):
                        best_row = row
            if best_row:
                memory_id_tantivy = best_row.get("memory_id", "")
        except Exception:
            logger.debug("store: memory_insert_result lookup failed, falling back to content match")
        if not memory_id_tantivy:
            mems_after = self._query(
                "memory", workspace_id=workspace_id, filter_dict={}, columns=["id", "content"]
            )
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
                from ..binary_vectors import binarize

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

                # Entity extraction: LLM first, fall back to regex.
                # Skipped when STDB_SKIP_ENTITY_EXTRACT=1 — bulk benchmark
                # ingestion (LongMemEval/BEAM) stores raw retrieval chunks and
                # does NOT need per-chunk LLM entity extraction; that call costs
                # ~20s per store (an LLM round-trip per chunk) and made the LME
                # 500-question haystack ingest infeasible (100h+ → hours).
                if not _skip_entity_extract():
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

        # Surface the real memory id to callers (resolved above).
        if isinstance(result, dict):
            if memory_id_tantivy and not result.get("id"):
                result["id"] = memory_id_tantivy
            return result
        return {"status": "ok", "id": memory_id_tantivy or None}


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
                - ``images_json`` (str, optional) — JSON string of image
                  attachments to associate with this memory (e.g., URLs or
                  base64 data URIs).  Stored in the memory's ``context``
                  field.  Pass ``""`` (default) for no images.

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
            # Normalize image attachments for this item
            images_item = item.get("images", None)
            images_json_item = item.get("images_json", "")
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
                    "context": _normalize_images(images=images_item, images_json=images_json_item, context="batch"),
                }
            )

        if not clean_items:
            return []

        # Batch-embed via the local embedder's OpenAI-compatible endpoint
        try:
            emb_list = self._embed_batch_local(contents)
            if emb_list is None:
                emb_list = []
        except Exception:
            logger.warning("store_batch: get_embeddings_batch failed, returning empty embeddings")
            emb_list = []

        if emb_list:
            self._clear_embedder_errors()

        # Call batch reducer -- pass items as JSON string

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

        # Query all matching memories in one batch -- match by content prefix
        # (moved outside entity_items check so content_to_id is available for Tantivy indexing)
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

        if entity_items:
            # Fill in entity_ids for items with embeddings
            for ei, ti in zip(entity_items, terms_items):
                mid = content_to_id.get(ei["content"][:100], "")
                ei["entity_id"] = mid
                ti["entity_id"] = mid

        if entity_items:
            # Single batch call to index_entity_batch (all items with embeddings)
            # Must send as list of tuples: (workspace_id, entity_type, entity_id, content, embedding_json)
            # The Rust reducer expects Vec<(String, String, String, String, String)>
            entity_tuples = [
                (ei["workspace_id"], ei["entity_type"], ei["entity_id"], ei["content"], ei["embedding_json"])
                for ei in entity_items
            ]
            self._call("index_entity_batch", [json.dumps(entity_tuples)])

        # Tantivy BM25 + keyword indexing — runs for ALL items regardless of embeddings
        # (extracted from the entity_items block so it fires when embedder is unavailable)
        tantivy_items = []
        index_terms_list = []
        for clean_item in clean_items:
            prefix = clean_item["content"][:100]
            mid = content_to_id.get(prefix, "")
            if mid:
                tantivy_items.append({
                    "workspace_id": workspace_id,
                    "entity_id": mid,
                    "content": clean_item["content"],
                    "entity_type": "memory",
                })
                index_terms_list.append({
                    "workspace_id": workspace_id,
                    "entity_type": "memory",
                    "entity_id": mid,
                    "content": clean_item["content"],
                })

        # index_terms: one call per item (keyword indexing in STDB)
        for it in index_terms_list:
            try:
                self._call("index_terms", [it["workspace_id"], it["entity_type"], it["entity_id"], it["content"]])
            except RuntimeError:
                logger.warning("index_terms failed for %s", it.get("entity_id", "?"))

        # Tantivy batch index: all items in one HTTP POST
        if tantivy_items:
            self._tantivy_index_batch(tantivy_items)

        # Entity extraction — only for items with embeddings (they have entity_ids)
        for i, ei in enumerate(entity_items):
            if ei["entity_id"]:
                item = clean_items[i] if i < len(clean_items) else ei
                has_entities = (
                    json.loads(item.get("entities_json", "[]"))
                    if isinstance(item.get("entities_json"), str)
                    else item.get("entities_json", [])
                )
                if has_entities:
                    continue
                self._extract_and_store_entities(
                    workspace_id,
                    ei["entity_id"],
                    ei["content"],
                )

        return [{"status": "ok"} for _ in clean_items]


    # ------------------------------------------------------------------
    # Entity-aware search result boosting (mem0 v3 multi-signal parity)





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
            threshold: Minimum similarity ratio (0.0-1.0, default 0.5).
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
            New confidence score 0.0-1.0 (default ``0.8``).
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
        """
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
        """Deactivate a memory. Idempotent -- succeeds if already deleted."""
        # ── Look up workspace_id for cache invalidation ──
        ws_id: str | None = None
        if self._query_cache is not None:
            rows = self._query("memory", filter_dict={"id": memory_id})
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

    def batch_delete_memories(self, workspace_id: str, memory_ids: list[str]) -> dict[str, Any]:
        """Batch-deactivate multiple memories in a single reducer call.

        Much faster than N sequential ``delete_memory()`` calls because it
        sends all IDs in one network round-trip to the
        ``batch_delete_memories`` reducer.

        Parameters
        ----------
        workspace_id:
            Target workspace for scoping access control.
        memory_ids:
            List of memory ID strings to deactivate. Missing IDs are
            silently skipped (idempotent).

        Returns
        -------
        Dict with ``status``: ``"ok"`` on success.
        """
        if not memory_ids:
            return {"status": "ok", "note": "no IDs provided"}
        return self._call("batch_delete_memories", [workspace_id, json.dumps(memory_ids)])

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
                    or an integer string "1"-"5" for graded feedback.
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
        rows = self._query(
            "user_memory_result",
            workspace_id=workspace_id,
            filter_dict={"user_scope": user_scope},
        )
        return rows

    def auto_invalidate(self, old_memory_id: str, new_memory_id: str) -> dict[str, Any]:
        """Auto-invalidate an old memory fact in favor of a new contradictory fact.

        This sets ``valid_to`` on the old memory and leaves the new memory active.

        Args:
            old_memory_id: ID of the memory to be invalidated.
            new_memory_id: ID of the new memory that supersedes it.

        Returns:
            The reducer response dict.
        """
        return self._call("auto_invalidate", [old_memory_id, new_memory_id])



    def get_memory_images(self, memory_id: str) -> list[dict[str, Any]]:
        """Retrieve images associated with a memory.

        Parses the memory's context field for the ``__images__:`` prefix
        and returns the parsed JSON array of image objects.

        Args:
            memory_id: The memory ID to retrieve images for.

        Returns:
            A list of image dicts with ``url`` and ``alt_text`` keys,
            or an empty list if no images are found.
        """
        mems = self._sql(f"SELECT context FROM memory WHERE id = '{_esc(memory_id)}'")
        if not mems:
            return []
        context = mems[0].get("context", "") or ""
        if not context.startswith("__images__:"):
            return []
        try:
            json_part = context[len("__images__:"):]
            return json.loads(json_part)
        except (json.JSONDecodeError, TypeError):
            return []
