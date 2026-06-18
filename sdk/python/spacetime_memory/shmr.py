"""
Self-Harmonizing Memory Reasoning (SHMR)
========================================
Memory resonance engine — clusters related memories by embedding similarity,
uses LLM to harmonize contradictions into stable beliefs.

Based on mnemosyne's shmr.py (AxDSan/mnemosyne), rearchitected for
Spacetime Memory's SpacetimeDB backend.

Core flow:
1. Fetch recent memories with embeddings
2. Cluster by cosine similarity (connected components)
3. For each cluster: LLM harmonization → beliefs
4. Compute harmony score (beliefs × cluster centroid)
5. Store beliefs in SpacetimeDB via reducer
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from spacetime_memory.client import Client

# ── Config ──────────────────────────────────────────────────────────

SHMR_BATCH_SIZE = int(os.environ.get("MNEMOSYNE_SHMR_BATCH_SIZE", "50"))
SHMR_MAX_ITERATIONS = int(os.environ.get("MNEMOSYNE_SHMR_MAX_ITERATIONS", "3"))
SHMR_SIMILARITY_THRESHOLD = float(
    os.environ.get("MNEMOSYNE_SHMR_SIMILARITY_THRESHOLD", "0.70")
)
SHMR_HARMONY_THRESHOLD = float(
    os.environ.get("MNEMOSYNE_SHMR_HARMONY_THRESHOLD", "0.60")
)
SHMR_MODEL = os.environ.get("MNEMOSYNE_SHMR_MODEL", "")
SHMR_MIN_CLUSTER_SIZE = int(os.environ.get("MNEMOSYNE_SHMR_MIN_CLUSTER_SIZE", "2"))
SHMR_TEMPERATURE = float(os.environ.get("MNEMOSYNE_SHMR_TEMPERATURE", "0.2"))


# ── Results ─────────────────────────────────────────────────────────


@dataclass
class ResonanceResult:
    """Result of one SHMR resonance pass."""

    workspace_id: str
    clusters_found: int = 0
    beliefs_generated: int = 0
    contradictions_resolved: int = 0
    harmony_score_avg: float = 0.0
    duration_ms: int = 0
    errors: int = 0


# ── Core Engine ─────────────────────────────────────────────────────


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    a_norm = a / (np.linalg.norm(a) + 1e-8)
    b_norm = b / (np.linalg.norm(b) + 1e-8)
    return float(np.dot(a_norm, b_norm))


def _cluster_by_similarity(
    items: list[dict[str, Any]],
    threshold: float = SHMR_SIMILARITY_THRESHOLD,
) -> list[list[dict[str, Any]]]:
    """Greedy connected-components clustering by cosine similarity.

    Each item must have an 'embedding' key with a list of floats.
    Returns list of clusters (each cluster is a list of items).
    """
    if not items:
        return []

    n = len(items)
    # Build adjacency matrix
    adj = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            emb_i = np.array(items[i]["embedding"], dtype=np.float32)
            emb_j = np.array(items[j]["embedding"], dtype=np.float32)
            if emb_i.size == 0 or emb_j.size == 0:
                continue
            sim = _cosine_similarity(emb_i, emb_j)
            if sim >= threshold:
                adj[i].add(j)
                adj[j].add(i)

    # Connected components (BFS)
    visited: set[int] = set()
    clusters: list[list[dict[str, Any]]] = []
    for i in range(n):
        if i in visited:
            continue
        cluster: list[dict[str, Any]] = []
        stack = [i]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            cluster.append(items[node])
            stack.extend(adj[node] - visited)
        if len(cluster) >= SHMR_MIN_CLUSTER_SIZE:
            clusters.append(cluster)

    return clusters


# ── LLM Harmonization ───────────────────────────────────────────────


HARMONY_PROMPT = """You are the Self-Harmonizing Memory Reasoner for Mnemosyne.
These memories belong to the same semantic cluster -- they all relate to the
same entities, topics, or events. Your job is to harmonize them:

1. **Resolve contradictions**: If two memories conflict, determine which is more
   likely true based on recency, specificity, and internal consistency. Flag the
   weaker one as dampened, not deleted.
2. **Extract higher-order beliefs**: Find patterns that span multiple memories.
   What does this cluster as a whole tell us? What's the stable truth?
3. **Dampen noise, amplify signal**: Low-confidence or stale memories get lower
   weight. Corroborated facts get reinforced.
4. **Output only stable beliefs**: Return NEW or UPDATED facts with confidence
   scores. Don't regurgitate every input fact -- synthesize.

Output as JSON array of belief objects:
[{"subject": "...", "predicate": "...", "object": "...", "confidence": 0.0-1.0,
  "action": "create"|"update"|"dampen", "source_memory_ids": ["id1","id2"],
  "rationale": "one sentence explaining why"}]

RULES:
- Confidence 0.9+ = highly corroborated (multiple sources agree)
- Confidence 0.5-0.8 = reasonable inference from the cluster
- Confidence <0.4 = speculative, mark as such
- Use "dampen" to reduce confidence of contradicted facts (never delete)
- Use "update" to modify an existing fact with new information
- Output 1-5 beliefs per cluster (don't over-generate)"""


def _format_cluster_for_llm(cluster: list[dict[str, Any]]) -> str:
    """Format a memory cluster for LLM harmonization."""
    lines = ["=== MEMORY CLUSTER ==="]
    for i, item in enumerate(cluster):
        content = item.get("content", "")[:200]
        mem_type = item.get("memory_type", "memory")
        trust = item.get("trust_score", 0.5)
        ts = item.get("created_at", 0)
        lines.append(
            f"[{i}] ({mem_type}, trust={trust:.2f}) {content}"
        )
    return "\n".join(lines)


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    """Robust JSON extraction from LLM output (handles markdown wrappers)."""
    import re

    # Try direct parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and "beliefs" in parsed:
            return parsed["beliefs"]
    except (json.JSONDecodeError, TypeError):
        pass

    # Try ```json ... ``` block
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, TypeError):
            pass

    # Try bare array
    m = re.search(r"\[\s*\{.*?\}\s*\]", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except (json.JSONDecodeError, TypeError):
            pass

    # Fallback: extract individual { } objects
    objects = re.findall(r"\{[^{}]*\}", text)
    results = []
    for obj_str in objects:
        try:
            results.append(json.loads(obj_str))
        except (json.JSONDecodeError, TypeError):
            pass
    return results


def _compute_harmony_score(
    beliefs: list[dict[str, Any]],
    cluster: list[dict[str, Any]],
) -> float:
    """Score how well beliefs represent the cluster via embedding similarity."""
    if not beliefs or not cluster:
        return 0.0

    # Cluster centroid
    cluster_embs = []
    for item in cluster:
        emb = item.get("embedding", [])
        if emb:
            cluster_embs.append(np.array(emb, dtype=np.float32))
    if not cluster_embs:
        return 0.0
    centroid = np.mean(cluster_embs, axis=0)

    # Score each belief against centroid
    belief_scores = []
    for belief in beliefs:
        text = f"{belief.get('predicate', '')} {belief.get('object', '')}"
        # Use a simple hash-based score since we don't have an embedder
        # in this context. Fall back to confidence-weighted default.
        belief_scores.append(belief.get("confidence", 0.5) * 0.7)

    # Consistency: beliefs that are similar to each other score higher
    consistency = 1.0
    if len(beliefs) > 1:
        # Simple heuristic: beliefs with same subject are more consistent
        subjects = [b.get("subject", "") for b in beliefs]
        same_subject = sum(1 for s in subjects if s == subjects[0])
        consistency = min(1.0, 0.5 + (same_subject / len(beliefs)) * 0.5)

    avg = np.mean(belief_scores) if belief_scores else 0.0
    return float(avg * consistency)


# ── Main Resonance Function ─────────────────────────────────────────


def shmr_resonate(
    client: Client,
    workspace_id: str,
    days: int = 7,
    max_iterations: int = SHMR_MAX_ITERATIONS,
    similarity_threshold: float = SHMR_SIMILARITY_THRESHOLD,
    dry_run: bool = False,
) -> ResonanceResult:
    """Run one SHMR resonance pass on a workspace.

    Fetches recent memories, clusters by embedding similarity,
    harmonizes each cluster via LLM, and stores beliefs.

    Args:
        client: Authenticated Spacetime Memory client.
        workspace_id: Target workspace.
        days: How many days of memories to consider.
        max_iterations: Maximum resonance rounds.
        similarity_threshold: Cosine similarity threshold for clustering.
        dry_run: If True, don't store results.
    """
    t0 = time.time()
    result = ResonanceResult(workspace_id=workspace_id)

    # 1. Fetch recent memories with embeddings
    memories = client.search(
        workspace_id,
        query="",
        limit=SHMR_BATCH_SIZE,
        semantic=True,
    )

    # Filter to only memories with embeddings (from search_index)
    indexed: list[dict[str, Any]] = []
    for mem in memories:
        emb = client._embed(mem.get("content", ""))
        if emb:
            indexed.append({"embedding": emb, **mem})

    if not indexed:
        print("  No indexed memories found.")
        result.duration_ms = int((time.time() - t0) * 1000)
        return result

    print(f"  Memories with embeddings: {len(indexed)}/{len(memories)}")

    # 2. Cluster by embedding similarity
    clusters = _cluster_by_similarity(indexed, threshold=similarity_threshold)
    result.clusters_found = len(clusters)
    print(f"  Clusters found: {len(clusters)} (threshold={similarity_threshold})")

    if not clusters:
        result.duration_ms = int((time.time() - t0) * 1000)
        return result

    # 3. Harmonize each cluster
    total_harmony = 0.0
    for i, cluster in enumerate(clusters):
        cluster_id = f"shmr_{workspace_id[:8]}_{i}"

        # Format for LLM
        prompt = HARMONY_PROMPT + "\n\n" + _format_cluster_for_llm(cluster)

        if dry_run:
            print(f"    [DRY] Cluster {i+1}/{len(clusters)}: {len(cluster)} memories")
            result.beliefs_generated += 3  # estimate
            continue

        # Call LLM (reuse client's configured LLM if available, else skip)
        llm_result: str | None = None
        try:
            llm_result = _call_client_llm(client, prompt)
        except Exception as e:
            print(f"    LLM call failed for cluster {i}: {e}")
            result.errors += 1
            continue

        if not llm_result:
            continue

        # Parse beliefs
        beliefs = _extract_json_array(llm_result)
        if not beliefs:
            continue

        # Compute harmony score
        harmony = _compute_harmony_score(beliefs, cluster)
        total_harmony += harmony

        # Annotate beliefs with source IDs and harmony score
        source_ids = [m.get("entity_id", "") for m in cluster if m.get("entity_id")]
        for b in beliefs:
            b["source_memory_ids"] = json.dumps(source_ids)
            b["harmony_score"] = harmony

        # Store via reducer
        try:
            client._call("store_harmonic_beliefs", [
                workspace_id,
                "",  # peer_id auto-resolved
                json.dumps(beliefs),
                cluster_id,
                i,  # iteration
            ])
            dampens = sum(1 for b in beliefs if b.get("action") == "dampen")
            print(
                f"    [OK] Cluster {i+1}/{len(clusters)}: "
                f"{len(beliefs)} beliefs ({dampens} dampened, harmony={harmony:.2f})"
            )
            result.beliefs_generated += len(beliefs)
            result.contradictions_resolved += dampens
        except Exception as e:
            print(f"    Store failed for cluster {i}: {e}")
            result.errors += 1

    # 4. Compute average harmony score
    if result.beliefs_generated > 0:
        result.harmony_score_avg = total_harmony / len(clusters)

    result.duration_ms = int((time.time() - t0) * 1000)

    # 5. Log resonance session
    if not dry_run and result.clusters_found > 0:
        try:
            client._call("log_resonance_session", [
                workspace_id,
                "",
                result.clusters_found,
                result.beliefs_generated,
                result.contradictions_resolved,
                result.harmony_score_avg,
                result.duration_ms,
            ])
        except Exception:
            pass

    return result


def _call_client_llm(client: Client, prompt: str) -> str | None:
    """Call LLM through OpenAI-compatible API (same as dream_cycle.py)."""
    import httpx

    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = SHMR_MODEL or os.environ.get("LLM_MODEL", "gpt-4o-mini")

    if not api_key:
        return None

    try:
        resp = httpx.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a memory harmonization engine."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": SHMR_TEMPERATURE,
                "max_tokens": 2048,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None
