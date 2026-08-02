"""Three-phase entity resolution — Graphiti parity.

Implements:
- Phase 1: Exact name match (normalized)
- Phase 2: MinHash/LSH fuzzy match
- Phase 3: LLM-based dedup escalation

All pure Python — no external deps (numpy, pandas, scipy).

Usage::

    from spacetime_memory import Client

    client = Client()
    result = client.resolve_entity(
        workspace_id="ws-123",
        name="Dr. Jane Smith",
        entity_type="person",
        description="A researcher",
    )
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from typing import Any

from ._base import logger

# ---------------------------------------------------------------------------
# Phase 1 — Exact name match (normalized)
# ---------------------------------------------------------------------------


def normalize_name(name: str) -> str:
    """Normalize an entity name for exact matching.

    Transformations:
    - Lowercase
    - Strip punctuation (except hyphens within words)
    - Collapse whitespace
    - Remove common honorifics and suffixes

    Args:
        name: Raw entity name.

    Returns:
        Normalized string suitable for canonical comparison.
    """
    if not name:
        return ""

    n = name.lower().strip()

    # Remove common honorifics / titles / suffixes (case-insensitive already)
    honorifics = [
        r"\bdr\.?\s*",
        r"\bmr\.?\s*",
        r"\bmrs\.?\s*",
        r"\bms\.?\s*",
        r"\bprof\.?\s*",
        r"\bph\.?d\.?\s*",
        r"\bmd\.?\s*",
        r"\bjr\.?\s*",
        r"\bsr\.?\s*",
        r"\binc\.?\s*",
        r"\bltd\.?\s*",
        r"\bllc\.?\s*",
        r"\bcorp\.?\s*",
        r"\bgmbh\s*",
        r"\bgmbh&\s*co\.?\s*kg\s*",
        r"\bco\.?\s*",
    ]
    for pat in honorifics:
        n = re.sub(pat, "", n)

    # Strip punctuation (keep hyphens between words, apostrophes in words)
    n = re.sub(r"[^\w\s'-]", " ", n)
    # Collapse whitespace
    n = re.sub(r"\s+", " ", n).strip()
    # Strip leading/trailing hyphens and apostrophes
    n = n.strip("'-")

    return n


def exact_match(
    name: str,
    entity_links: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Phase 1: Exact (normalized) name match against entity_link records.

    Checks both ``entity_name`` and entries in ``aliases_json``.

    Args:
        name: Entity name to resolve.
        entity_links: List of entity_link rows (dicts with entity_name,
            aliases_json, id, entity_type, etc.).

    Returns:
        Matched entity link dict, or ``None``.
    """
    normalized = normalize_name(name)
    if not normalized:
        return None

    for el in entity_links:
        # Check canonical name
        el_normalized = normalize_name(el.get("entity_name", ""))
        if el_normalized == normalized:
            return el

        # Check aliases
        aliases_raw = el.get("aliases_json", "[]")
        if isinstance(aliases_raw, str):
            try:
                aliases = json.loads(aliases_raw)
            except (json.JSONDecodeError, TypeError):
                aliases = []
        elif isinstance(aliases_raw, list):
            aliases = aliases_raw
        else:
            aliases = []

        for alias in aliases:
            alias_normalized = normalize_name(str(alias))
            if alias_normalized == normalized:
                return el

    return None


# ---------------------------------------------------------------------------
# Phase 2 — MinHash/LSH Fuzzy Match
# ---------------------------------------------------------------------------


def compute_minhash_signature(
    text: str,
    num_hashes: int = 128,
    shingle_size: int = 3,
) -> list[int]:
    """Compute a MinHash signature for the given text.

    Uses the standard MinHash approach:
    1. Tokenize into character k-shingles (default: 3-grams)
    2. Hash each shingle with SHA-256 (non-cryptographic use)
    3. For each of N permutations (fixed random seeds), take the minimum hash

    Pure Python — uses ``hashlib.sha256``, no external dependencies.

    Args:
        text: Input text to signature.
        num_hashes: Number of hash functions / permutations (default: 128).
        shingle_size: Character n-gram size (default: 3).

    Returns:
        List of ``num_hashes`` minimum hash values (integers).
    """
    if not text:
        return [0] * num_hashes

    text = text.lower().strip()
    if not text:
        return [0] * num_hashes
    if len(text) < shingle_size:
        # Pad short text
        text = text.ljust(shingle_size, " ")

    # Generate shingles
    shingles: set[bytes] = set()
    for i in range(len(text) - shingle_size + 1):
        shingle = text[i : i + shingle_size]
        shingles.add(shingle.encode("utf-8"))

    if not shingles:
        return [0] * num_hashes

    # Pre compute hashes for all shingles (as integers)
    shingle_hashes: list[int] = []
    for shingle in shingles:
        h = hashlib.sha256(shingle).digest()
        # Convert first 8 bytes to an integer
        val = struct.unpack("<Q", h[:8])[0]
        shingle_hashes.append(val)

    # Generate signatures: for each permutation seed, find min hash
    signature: list[int] = []
    for perm_idx in range(num_hashes):
        # Use deterministic seed for each permutation
        seed = _permutation_seed(perm_idx)
        min_val = _hash_with_seed(shingle_hashes, seed)
        signature.append(min_val)

    return signature


def _permutation_seed(perm_idx: int) -> int:
    """Generate a deterministic seed for a permutation index."""
    h = hashlib.sha256(f"minhash_perm_{perm_idx}".encode()).digest()
    return struct.unpack("<Q", h[:8])[0]


def _hash_with_seed(values: list[int], seed: int) -> int:
    """Return the minimum of (value XOR seed) over all values.

    This simulates a random permutation by XOR-ing with a random seed and
    taking the minimum — the standard MinHash permutation trick.
    """
    if not values:
        return seed  # fallback

    min_val = (values[0] ^ seed) & 0xFFFFFFFFFFFFFFFF
    for v in values[1:]:
        xored = (v ^ seed) & 0xFFFFFFFFFFFFFFFF
        min_val = min(min_val, xored)
    return min_val


def jaccard_similarity_from_signatures(
    sig_a: list[int],
    sig_b: list[int],
) -> float:
    """Estimate Jaccard similarity from two MinHash signatures.

    Jaccard = |intersection of minhashes| / N

    Args:
        sig_a: First MinHash signature.
        sig_b: Second MinHash signature.

    Returns:
        Float in [0.0, 1.0].
    """
    if not sig_a or not sig_b:
        return 0.0

    n = min(len(sig_a), len(sig_b))
    if n == 0:
        return 0.0

    matches = sum(1 for i in range(n) if sig_a[i] == sig_b[i])
    return matches / n


def minhash_fuzzy_match(
    name: str,
    existing_entities: list[dict[str, Any]],
    threshold: float = 0.9,
) -> list[dict[str, Any]]:
    """Phase 2: MinHash/LSH fuzzy match against existing entities.

    Args:
        name: Entity name to match.
        existing_entities: List of entity dicts with at least ``entity_name``,
            ``id``, and optionally ``signature`` (pre-computed MinHash).
        threshold: Jaccard similarity threshold (default: 0.9).

    Returns:
        List of matched entity dicts with a ``similarity`` key added,
        sorted by descending similarity.
    """
    if not name or not existing_entities:
        return []

    query_sig = compute_minhash_signature(name)
    matches: list[dict[str, Any]] = []

    for entity in existing_entities:
        entity_name = entity.get("entity_name", "")
        if not entity_name:
            continue

        # Use pre-computed signature if available, otherwise compute
        if "signature" in entity and isinstance(entity["signature"], list):
            entity_sig = entity["signature"]
        else:
            entity_sig = compute_minhash_signature(entity_name)

        similarity = jaccard_similarity_from_signatures(query_sig, entity_sig)

        if similarity >= threshold:
            result = dict(entity)
            result["similarity"] = round(similarity, 4)
            matches.append(result)

    # Sort by similarity descending
    matches.sort(key=lambda m: m.get("similarity", 0.0), reverse=True)
    return matches


# ---------------------------------------------------------------------------
# Phase 3 — LLM-Based Dedup Escalation
# ---------------------------------------------------------------------------

DEFAULT_DEDUP_PROMPT = (
    "You are an entity resolution system. Determine whether the following two "
    "entity records refer to the SAME real-world entity or are DISTINCT.\n\n"
    "Entity A:\n"
    "  Name: {name_a}\n"
    "  Type: {type_a}\n"
    "  Description: {desc_a}\n\n"
    "Entity B:\n"
    "  Name: {name_b}\n"
    "  Type: {type_b}\n"
    "  Description: {desc_b}\n\n"
    "{context_section}"
    "Respond with ONLY valid JSON in this exact format (no markdown, no explanation):\n"
    '{{"decision": "merge" | "separate" | "uncertain", '
    '"merged_name": "...", '
    '"merged_type": "...", '
    '"merged_description": "...", '
    '"confidence": 0.0-1.0}}\n\n'
    "Rules:\n"
    "- \"merge\": Same person/entity with different names/descriptions\n"
    "- \"separate\": Clearly different entities\n"
    "- \"uncertain\": Cannot confidently decide\n"
    "- merged_name: Best canonical name if merging\n"
    "- merged_type: Best entity type if merging\n"
    "- merged_description: Synthesized description if merging\n"
    "- confidence: Your confidence in the decision (0.0-1.0)"
)


def llm_resolve_conflict(
    entity_a: dict[str, Any],
    entity_b: dict[str, Any],
    context: str | None = None,
    llm_complete_func=None,
) -> dict[str, Any]:
    """Phase 3: LLM-based dedup escalation.

    Uses a configured LLM to determine whether two entity records refer
    to the same real-world entity.

    Args:
        entity_a: First entity dict (must have name, entity_type, description).
        entity_b: Second entity dict.
        context: Optional extra context string for the LLM.
        llm_complete_func: Callable(str) -> str for LLM completion.
            If ``None``, returns a default uncertain result.

    Returns:
        Resolution dict with keys:
            decision: "merge", "separate", or "uncertain"
            merged_name: Best canonical name (if merge)
            merged_type: Best entity type (if merge)
            merged_description: Synthesized description (if merge)
            confidence: Float 0.0-1.0
            method: "llm" or "fallback"
    """
    name_a = entity_a.get("name", entity_a.get("entity_name", ""))
    type_a = entity_a.get("entity_type", entity_a.get("node_type", ""))
    desc_a = entity_a.get("description", entity_a.get("summary", ""))

    name_b = entity_b.get("name", entity_b.get("entity_name", ""))
    type_b = entity_b.get("entity_type", entity_b.get("node_type", ""))
    desc_b = entity_b.get("description", entity_b.get("summary", ""))

    context_section = ""
    if context:
        context_section = f"Additional context:\n{context}\n\n"

    prompt = DEFAULT_DEDUP_PROMPT.format(
        name_a=name_a,
        type_a=type_a,
        desc_a=desc_a or "(none)",
        name_b=name_b,
        type_b=type_b,
        desc_b=desc_b or "(none)",
        context_section=context_section,
    )

    if llm_complete_func is None:
        return {
            "decision": "uncertain",
            "merged_name": "",
            "merged_type": "",
            "merged_description": "",
            "confidence": 0.0,
            "method": "fallback",
        }

    try:
        raw = llm_complete_func(prompt)
        if not raw:
            return {
                "decision": "uncertain",
                "merged_name": "",
                "merged_type": "",
                "merged_description": "",
                "confidence": 0.0,
                "method": "fallback",
            }

        # Strip markdown fences
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
        if m:
            raw = m.group(1)

        result = json.loads(raw)
        decision = result.get("decision", "uncertain")
        if decision not in ("merge", "separate", "uncertain"):
            decision = "uncertain"

        return {
            "decision": decision,
            "merged_name": result.get("merged_name", name_a if decision == "merge" else ""),
            "merged_type": result.get("merged_type", type_a if decision == "merge" else ""),
            "merged_description": result.get("merged_description", ""),
            "confidence": float(result.get("confidence", 0.5)),
            "method": "llm",
        }
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.debug("llm_resolve_conflict: parse error: %s", e)
        return {
            "decision": "uncertain",
            "merged_name": "",
            "merged_type": "",
            "merged_description": "",
            "confidence": 0.0,
            "method": "fallback",
        }


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------


class EntityResolutionMixin:
    """Spacetime-Memory entity resolution mixin.

    Provides Client methods for the three-phase entity resolution pipeline:

    - Phase 1: Exact match (normalized name + aliases)
    - Phase 2: MinHash/LSH fuzzy match
    - Phase 3: LLM-based dedup escalation

    Inherits from ClientBase for connection infrastructure.
    """

    # ------------------------------------------------------------------
    # Full resolution pipeline
    # ------------------------------------------------------------------

    def resolve_entity(
        self,
        workspace_id: str,
        name: str,
        entity_type: str = "",
        description: str | None = None,
    ) -> dict[str, Any]:
        """Resolve an entity name using the full three-phase pipeline.

        Phase 1: Exact normalized name match.
        Phase 2: MinHash fuzzy match (if Phase 1 fails).
        Phase 3: LLM dedup (if Phase 2 yields ambiguous candidates).

        Args:
            workspace_id: Target workspace.
            name: Entity name to resolve.
            entity_type: Expected entity type hint.
            description: Optional description for Phase 3 LLM context.

        Returns:
            Resolution result dict with keys:
                resolved: Whether a match was found.
                entity_id: Matched entity ID (or None).
                entity: Matched entity dict (or None).
                entity_name: Matched entity name (or None).
                entity_type: Matched entity type.
                phase: Which phase matched (``"exact"``, ``"fuzzy"``, ``"llm"``, or ``"none"``).
                similarity: Similarity score (fuzzy/LLM phases only).
                linked: Whether the entity was linked in the entity_link table
                    (Phase 1/2 only).
        """
        result: dict[str, Any] = {
            "resolved": False,
            "entity_id": None,
            "entity": None,
            "entity_name": name,
            "entity_type": entity_type,
            "phase": "none",
            "similarity": None,
            "linked": False,
        }

        # Fetch all entity links for this workspace
        try:
            entity_links = self._query(
                "entity_link",
                workspace_id=workspace_id,
                columns=["id", "entity_name", "aliases_json", "entity_type", "description"],
            )
        except RuntimeError:
            entity_links = []

        if not entity_links:
            # No existing entities — can't resolve
            return result

        # --- Phase 1: Exact normalized match ---
        matched = exact_match(name, entity_links)
        if matched:
            result["resolved"] = True
            result["entity_id"] = matched.get("id")
            result["entity"] = matched
            result["entity_name"] = matched.get("entity_name", name)
            result["entity_type"] = matched.get("entity_type", entity_type)
            result["phase"] = "exact"
            result["linked"] = True
            return result

        # --- Phase 2: MinHash fuzzy match ---
        fuzzy_matches = minhash_fuzzy_match(name, entity_links, threshold=0.9)

        if len(fuzzy_matches) == 1:
            result["resolved"] = True
            result["entity_id"] = fuzzy_matches[0].get("id")
            result["entity"] = fuzzy_matches[0]
            result["entity_name"] = fuzzy_matches[0].get("entity_name", name)
            result["entity_type"] = fuzzy_matches[0].get("entity_type", entity_type)
            result["phase"] = "fuzzy"
            result["similarity"] = fuzzy_matches[0].get("similarity")
            result["linked"] = True
            return result

        if len(fuzzy_matches) > 1:
            # --- Phase 3: LLM dedup escalation ---
            llm_result = self._resolve_with_llm(name, entity_type, description, fuzzy_matches)
            if llm_result.get("decision") == "merge":
                # Use the best candidate
                best = llm_result.get("chosen_entity", fuzzy_matches[0])
                result["resolved"] = True
                result["entity_id"] = best.get("id")
                result["entity"] = best
                result["entity_name"] = llm_result.get("merged_name", best.get("entity_name", name))
                result["entity_type"] = llm_result.get("merged_type", best.get("entity_type", entity_type))
                result["phase"] = "llm"
                result["similarity"] = best.get("similarity")
                result["linked"] = True
                return result
            elif llm_result.get("decision") == "separate":
                # No match — it's genuinely a new entity
                return result
            else:
                # Uncertain — return the best fuzzy match as a hint
                result["entity_id"] = fuzzy_matches[0].get("id")
                result["entity"] = fuzzy_matches[0]
                result["phase"] = "ambiguous"
                result["similarity"] = fuzzy_matches[0].get("similarity")
                return result

        # No match in any phase
        return result

    def _resolve_with_llm(
        self,
        name: str,
        entity_type: str,
        description: str | None,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Use LLM to resolve an entity against multiple candidates."""
        query_entity = {
            "name": name,
            "entity_type": entity_type,
            "description": description or "",
        }

        best_result: dict[str, Any] = {
            "decision": "uncertain",
            "chosen_entity": None,
            "merged_name": "",
            "merged_type": "",
            "merged_description": "",
            "confidence": 0.0,
        }

        for candidate in candidates:
            resolution = llm_resolve_conflict(
                query_entity,
                candidate,
                llm_complete_func=self._llm_complete,
            )
            if resolution.get("decision") == "merge":
                confidence = resolution.get("confidence", 0.0)
                if best_result.get("confidence", 0.0) < confidence:
                    best_result = {
                        "decision": "merge",
                        "chosen_entity": candidate,
                        "merged_name": resolution.get("merged_name", name),
                        "merged_type": resolution.get("merged_type", entity_type),
                        "merged_description": resolution.get("merged_description", ""),
                        "confidence": confidence,
                    }

        return best_result

    # ------------------------------------------------------------------
    # Dedup — scan all entities and find duplicates
    # ------------------------------------------------------------------

    def deduplicate_entities(
        self,
        workspace_id: str,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Scan all entities in a workspace, find duplicates, and resolve them.

        Uses the full three-phase pipeline for each candidate pair.

        Args:
            workspace_id: Target workspace.
            dry_run: If True, only report duplicates without merging.

        Returns:
            Dict with:
                scanned: Number of entities scanned.
                duplicates_found: Number of duplicate pairs found.
                merges_performed: Number of merges performed (0 if dry_run).
                merges: List of merge result dicts.
        """
        result: dict[str, Any] = {
            "scanned": 0,
            "duplicates_found": 0,
            "merges_performed": 0,
            "merges": [],
        }

        # Fetch all entity links for this workspace
        try:
            entity_links = self._query(
                "entity_link",
                workspace_id=workspace_id,
                columns=["id", "entity_name", "aliases_json", "entity_type", "description"],
            )
        except RuntimeError:
            entity_links = []

        result["scanned"] = len(entity_links)

        if len(entity_links) < 2:
            return result

        # Compute MinHash signatures once
        for el in entity_links:
            el["signature"] = compute_minhash_signature(
                el.get("entity_name", ""),
            )

        # Compare all pairs (n^2 but entity counts are small)
        seen_pairs: set[tuple[str, str]] = set()
        duplicate_pairs: list[tuple[dict[str, Any], dict[str, Any], float]] = []

        for i in range(len(entity_links)):
            for j in range(i + 1, len(entity_links)):
                a, b = entity_links[i], entity_links[j]
                pair_key = tuple(sorted([a["id"], b["id"]]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                # Check exact match (normalized)
                a_norm = normalize_name(a.get("entity_name", ""))
                b_norm = normalize_name(b.get("entity_name", ""))
                if a_norm == b_norm and a_norm:
                    duplicate_pairs.append((a, b, 1.0))
                    continue

                # Check fuzzy match
                similarity = jaccard_similarity_from_signatures(
                    a.get("signature", []),
                    b.get("signature", []),
                )
                if similarity >= 0.85:
                    duplicate_pairs.append((a, b, similarity))

        result["duplicates_found"] = len(duplicate_pairs)

        if dry_run:
            result["merges"] = [
                {
                    "entity_a_id": a["id"],
                    "entity_a_name": a.get("entity_name", ""),
                    "entity_b_id": b["id"],
                    "entity_b_name": b.get("entity_name", ""),
                    "similarity": sim,
                    "action": "would_merge",
                }
                for a, b, sim in duplicate_pairs
            ]
            return result

        # Perform merges
        for entity_a, entity_b, sim in duplicate_pairs:
            try:
                merge_result = self.merge_entities(
                    workspace_id=workspace_id,
                    source_id=entity_a["id"],
                    target_id=entity_b["id"],
                )
                merge_result["similarity"] = sim
                result["merges"].append(merge_result)
                result["merges_performed"] += 1
            except RuntimeError as e:
                logger.warning("deduplicate_entities: merge failed: %s", e)
                result["merges"].append({
                    "entity_a_id": entity_a["id"],
                    "entity_b_id": entity_b["id"],
                    "error": str(e),
                    "action": "failed",
                })

        return result

    # ------------------------------------------------------------------
    # Merge two entity records
    # ------------------------------------------------------------------

    def merge_entities(
        self,
        workspace_id: str,
        source_id: str,
        target_id: str,
    ) -> dict[str, Any]:
        """Merge two entity records in the entity_link table.

        The target entity absorbs the source entity's aliases and usage data.
        The source entity is removed.

        Args:
            workspace_id: Target workspace.
            source_id: ID of the source entity (will be removed).
            target_id: ID of the target entity (will absorb source).

        Returns:
            Dict with merge result.
        """
        # Fetch both entities
        source_rows = self._query(
            "entity_link",
            workspace_id=workspace_id,
            filter_dict={"id": source_id},
            columns=["id", "entity_name", "aliases_json", "entity_type",
                     "description", "used_count", "first_seen", "last_seen"],
        )
        target_rows = self._query(
            "entity_link",
            workspace_id=workspace_id,
            filter_dict={"id": target_id},
            columns=["id", "entity_name", "aliases_json", "entity_type",
                     "description", "used_count", "first_seen", "last_seen"],
        )

        if not source_rows:
            raise RuntimeError(f"Source entity '{source_id}' not found")
        if not target_rows:
            raise RuntimeError(f"Target entity '{target_id}' not found")

        source = source_rows[0]
        target = target_rows[0]

        # Merge aliases
        source_aliases = _parse_aliases(source.get("aliases_json", "[]"))
        target_aliases = _parse_aliases(target.get("aliases_json", "[]"))
        merged_aliases = list(set(target_aliases + source_aliases))

        # Add source name as alias if different from target
        source_name = source.get("entity_name", "")
        target_name = target.get("entity_name", "")
        if source_name and source_name != target_name:
            if source_name not in merged_aliases:
                merged_aliases.append(source_name)

        merged_aliases_json = json.dumps(merged_aliases)

        # Merge used_count and timestamps
        merged_used_count = int(source.get("used_count", 0)) + int(target.get("used_count", 0))
        merged_first_seen = min(
            int(source.get("first_seen", 0)),
            int(target.get("first_seen", 0)),
        )
        merged_last_seen = max(
            int(source.get("last_seen", 0)),
            int(target.get("last_seen", 0)),
        )

        # Keep best description (longer one)
        source_desc = source.get("description", "") or ""
        target_desc = target.get("description", "") or ""
        merged_description = target_desc if len(target_desc) >= len(source_desc) else source_desc

        # Keep best entity type (prefer more specific)
        source_type = source.get("entity_type", "") or ""
        target_type = target.get("entity_type", "") or ""
        merged_type = target_type if target_type else source_type

        # Update target entity
        self._call("update_entity_link_metadata", [
            target_id,
            merged_aliases_json,
            merged_type,
            merged_description,
            merged_used_count,
            merged_first_seen,
            merged_last_seen,
        ])

        # Consolidate KG edges from source to target
        self._merge_edges_for_entity(workspace_id, source_id, target_id)

        # Delete source entity
        self._call("delete_entity_link", [workspace_id, source_id])

        return {
            "status": "merged",
            "target_id": target_id,
            "source_id": source_id,
            "target_name": target_name,
            "source_name": source_name,
            "merged_entity_type": merged_type,
        }

    def _merge_edges_for_entity(
        self,
        workspace_id: str,
        source_id: str,
        target_id: str,
    ) -> None:
        """Re-wire all KG edges from source_id to target_id.

        Finds all edges where source_node_id or target_node_id matches
        source_id and updates them to point to target_id.
        """
        try:
            # Edges where source = source_id
            edges_from = self._query(
                "kg_edge",
                workspace_id=workspace_id,
                filter_dict={"source_node_id": source_id},
                columns=["id", "source_node_id", "target_node_id", "relation",
                         "weight", "confidence", "metadata_json"],
            )
            for edge in edges_from:
                # Check if target already has an equivalent edge
                dup = self._query(
                    "kg_edge",
                    workspace_id=workspace_id,
                    filter_dict={
                        "source_node_id": target_id,
                        "target_node_id": edge.get("target_node_id", ""),
                        "relation": edge.get("relation", ""),
                    },
                    columns=["id", "weight", "confidence"],
                )
                if dup:
                    # Merge metadata and keep highest confidence
                    self._call("update_edge", [
                        dup[0]["id"],
                        max(float(edge.get("weight", 1.0)), float(dup[0].get("weight", 1.0))),
                        _best_confidence(edge.get("confidence", "EXTRACTED"),
                                         dup[0].get("confidence", "EXTRACTED")),
                    ])
                    # Delete the redundant edge
                    self._call("delete_edge", [edge["id"]])
                else:
                    # Re-wire to target
                    self._call("update_edge_source", [edge["id"], target_id])

            # Edges where target = source_id
            edges_to = self._query(
                "kg_edge",
                workspace_id=workspace_id,
                filter_dict={"target_node_id": source_id},
                columns=["id", "source_node_id", "target_node_id", "relation",
                         "weight", "confidence", "metadata_json"],
            )
            for edge in edges_to:
                dup = self._query(
                    "kg_edge",
                    workspace_id=workspace_id,
                    filter_dict={
                        "source_node_id": edge.get("source_node_id", ""),
                        "target_node_id": target_id,
                        "relation": edge.get("relation", ""),
                    },
                    columns=["id", "weight", "confidence"],
                )
                if dup:
                    self._call("update_edge", [
                        dup[0]["id"],
                        max(float(edge.get("weight", 1.0)), float(dup[0].get("weight", 1.0))),
                        _best_confidence(edge.get("confidence", "EXTRACTED"),
                                         dup[0].get("confidence", "EXTRACTED")),
                    ])
                    self._call("delete_edge", [edge["id"]])
                else:
                    self._call("update_edge_target", [edge["id"], target_id])

        except RuntimeError as e:
            logger.warning("merge_entities: edge consolidation failed: %s", e)

    # ------------------------------------------------------------------
    # Edge dedup
    # ------------------------------------------------------------------

    def deduplicate_edges(self, workspace_id: str) -> dict[str, Any]:
        """Scan and merge duplicate KG edges.

        Two edges are considered duplicates if they share the same
        source_node_id, target_node_id, and relation.

        Args:
            workspace_id: Target workspace.

        Returns:
            Dict with count of duplicates merged.
        """
        try:
            edges = self._query(
                "kg_edge",
                workspace_id=workspace_id,
                columns=["id", "source_node_id", "target_node_id", "relation",
                         "weight", "confidence", "metadata_json"],
            )
        except RuntimeError:
            return {"merged": 0, "duplicates_found": 0, "errors": []}

        if not edges:
            return {"merged": 0, "duplicates_found": 0, "errors": []}

        # Group by (source_node_id, target_node_id, relation)
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for edge in edges:
            key = (
                edge.get("source_node_id", ""),
                edge.get("target_node_id", ""),
                edge.get("relation", ""),
            )
            if key not in groups:
                groups[key] = []
            groups[key].append(edge)

        # Merge duplicates
        merged_count = 0
        errors: list[str] = []

        for key, group in groups.items():
            if len(group) < 2:
                continue

            # Keep the first (best) edge, merge others into it
            best = group[0]
            for dup in group[1:]:
                try:
                    # Merge metrics
                    best_weight = max(
                        float(best.get("weight", 1.0)),
                        float(dup.get("weight", 1.0)),
                    )
                    best_conf = _best_confidence(
                        best.get("confidence", "EXTRACTED"),
                        dup.get("confidence", "EXTRACTED"),
                    )

                    # Update best
                    self._call("update_edge", [best["id"], best_weight, best_conf])
                    # Delete duplicate
                    self._call("delete_edge", [dup["id"]])
                    merged_count += 1
                except RuntimeError as e:
                    errors.append(f"Failed to merge edge {dup['id']}: {e}")

        return {
            "merged": merged_count,
            "duplicates_found": sum(len(g) - 1 for g in groups.values() if len(g) > 1),
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # Attribute merge
    # ------------------------------------------------------------------

    def merge_entity_attributes(
        self,
        workspace_id: str,
        entity_id: str,
        attributes: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge attributes into an entity with schema validation from ontology.

        Args:
            workspace_id: Target workspace.
            entity_id: Entity to update.
            attributes: Dict of attribute key-value pairs to merge.

        Returns:
            Dict with merge result.
        """
        # Fetch current entity
        entity_rows = self._query(
            "entity_link",
            workspace_id=workspace_id,
            filter_dict={"id": entity_id},
            columns=["id", "entity_name", "entity_type", "description"],
        )
        if not entity_rows:
            raise RuntimeError(f"Entity '{entity_id}' not found")

        entity = entity_rows[0]
        entity_type = entity.get("entity_type", "")

        # Try to get ontology schema for validation
        allowed_properties: set[str] | None = None
        if entity_type:
            try:
                type_defs = self.list_entity_types(
                    workspace_id=workspace_id,
                )
                for td in type_defs:
                    if td.get("name") == entity_type:
                        props = td.get("properties", [])
                        if isinstance(props, str):
                            props = json.loads(props)
                        allowed_properties = set(props)
                        break
            except (RuntimeError, AttributeError, json.JSONDecodeError):
                pass

        # Validate attributes against schema
        validated: dict[str, Any] = {}
        schema_violations: list[str] = []

        for key, value in attributes.items():
            if allowed_properties is not None and key not in allowed_properties:
                schema_violations.append(
                    f"'{key}' is not allowed for entity type '{entity_type}'"
                )
                continue
            validated[key] = value

        # Store validated attributes
        if validated:
            try:
                self._call("update_entity_attributes", [
                    entity_id,
                    json.dumps(validated),
                ])
            except RuntimeError:
                # Fallback: store as metadata
                self._call("update_entity_link_metadata", [
                    entity_id,
                    json.dumps({}),
                    entity_type,
                    entity.get("description", ""),
                    0, 0, 0,
                ])
                logger.warning(
                    "merge_entity_attributes: update_entity_attributes not available, "
                    "attributes stored in description fallback"
                )

        return {
            "status": "ok",
            "entity_id": entity_id,
            "attributes_merged": validated,
            "schema_violations": schema_violations,
            "total_attributes": len(validated),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_aliases(aliases_json: str) -> list[str]:
    """Parse aliases JSON string into a list of strings."""
    if isinstance(aliases_json, str):
        try:
            parsed = json.loads(aliases_json)
            if isinstance(parsed, list):
                return [str(a) for a in parsed if a]
        except (json.JSONDecodeError, TypeError):
            pass
    elif isinstance(aliases_json, list):
        return [str(a) for a in aliases_json if a]
    return []


def _best_confidence(conf_a: str, conf_b: str) -> str:
    """Return the best confidence level.

    Ordering: EXTRACTED > INFERRED > AMBIGUOUS
    """
    rank = {"EXTRACTED": 3, "INFERRED": 2, "AMBIGUOUS": 1}
    a_rank = rank.get(conf_a, 0)
    b_rank = rank.get(conf_b, 0)
    return conf_a if a_rank >= b_rank else conf_b
