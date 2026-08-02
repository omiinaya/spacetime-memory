"""LLM reranking utilities extracted from monolithic client.py.

Extends with CrossEncoderReranker, NodeDistanceReranker, MMRReranker,
FusionReranker, SearchFilterDSL, and a recipe registry of 18 search recipes.

All rerankers implement a common interface::

    def rerank(query: str, candidates: list[dict], **kwargs) -> list[dict]:
        ...
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# =====================================================================
# Existing: JSON parsing & LLM reranker
# =====================================================================


def _parse_rerank_json(content: str) -> list[dict]:
    """Parse LLM reranker JSON output with 6 fallback strategies.

    LLMs frequently return malformed JSON — trailing commas, markdown fences,
    wrapped objects, line-by-line output.  This tries progressively more
    aggressive salvage strategies.

    Raises ValueError if all 6 strategies fail.
    """
    scores: list[dict] = []
    parse_ok = False
    errors: list[str] = []

    # Strategy 1: Direct parse
    try:
        scores = json.loads(content)
        if isinstance(scores, list):
            parse_ok = True
    except json.JSONDecodeError as e:
        errors.append(f"direct: {e}")

    # Strategy 2: Find JSON array boundaries
    if not parse_ok:
        m = re.search(r"\[.*\]", content, re.DOTALL)
        if m:
            try:
                scores = json.loads(m.group())
                if isinstance(scores, list):
                    parse_ok = True
            except json.JSONDecodeError as e:
                errors.append(f"array: {e}")

    # Strategy 3: Strict=False, try to salvage partial
    if not parse_ok:
        try:
            decoder = json.JSONDecoder()
            scores, _ = decoder.raw_decode(content)
            if isinstance(scores, dict):
                scores = [scores]
            if isinstance(scores, list):
                parse_ok = True
        except json.JSONDecodeError as e:
            errors.append(f"strict_false: {e}")

    # Strategy 4: Aggressive salvage — strip trailing commas, fix unquoted keys
    if not parse_ok:
        cleaned = content
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        m = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if m:
            try:
                scores = json.loads(m.group())
                if isinstance(scores, list):
                    parse_ok = True
            except json.JSONDecodeError as e:
                errors.append(f"salvage_array: {e}")

        if not parse_ok:
            # Look for a JSON object containing a "score" key
            m = re.search(r'\{[^}]*"score"[^}]*\}', cleaned, re.DOTALL)
            if m:
                try:
                    obj = json.loads(m.group())
                    if isinstance(obj, dict):
                        scores = [obj]
                        parse_ok = True
                except json.JSONDecodeError as e:
                    logger.debug("_parse_rerank_json: strategy 4 object salvage failed: %s", e)

    # Strategy 5: Dict wrapper — LLM returned {"scores": [...]} or similar
    if not parse_ok:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group())
                if isinstance(obj, dict):
                    for key in ("scores", "results", "rankings", "items", "data"):
                        if key in obj and isinstance(obj[key], list):
                            scores = obj[key]
                            parse_ok = True
                            break
                    if not parse_ok and "index" in obj:
                        scores = [obj]
                        parse_ok = True
            except json.JSONDecodeError as e:
                errors.append(f"dict_wrapper: {e}")

    # Strategy 6: Line-by-line extraction — one JSON object per line
    if not parse_ok and content.strip():
        lines = [line.strip() for line in content.split("\n") if line.strip().startswith("{")]
        if lines:
            extracted = []
            for line in lines:
                try:
                    obj = json.loads(line.rstrip(","))
                    if isinstance(obj, dict) and "index" in obj:
                        extracted.append(obj)
                except json.JSONDecodeError as e:
                    logger.debug("_parse_rerank_json: strategy 6 line-by-line parse failed: %s", e)
                    continue
            if extracted:
                scores = extracted
                parse_ok = True

    if not parse_ok:
        raise ValueError(f"JSON parse failed after 6 strategies: {'; '.join(errors[-2:])}")
    return scores


_RERANK_PROMPT = """Score each search result for relevance to the query (1-10).

10 — perfectly answers the query, exact match
7-9 — highly relevant, contains key information
4-6 — partially relevant, related concepts
1-3 — barely relevant, tangential mention

Query: {query}

Candidates:
{candidates}

Provide your scores as a JSON array in this exact format, no other text:
[{{"index": 0, "score": 8, "reason": "contains exact match for 'auth'"}}, ...]

JSON:"""


def llm_rerank(
    query: str,
    results: list[dict[str, Any]],
    endpoint: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    top_k: int = 10,
    timeout: int = 30,
    plugin_manager: Any | None = None,
) -> list[dict[str, Any]]:
    """Rerank search results using an LLM (QMD-style).

    Sends top *top_k* results to an OpenAI-compatible chat completions
    endpoint and returns the original result dicts with scores replaced by
    the LLM's relevance scores and a ``rerank_reason`` field appended.

    Falls back to original results if the LLM call fails.

    Args:
        query: The original search query.
        results: Search result dicts (must have ``content`` key).
        endpoint: OpenAI-compatible base URL (default: env ``LLM_RERANK_ENDPOINT``
                  or ``http://127.0.0.1:4000/v1``).
        model: Model name (default: env ``LLM_RERANK_MODEL`` or ``gpt-4o-mini``).
        api_key: API key (default: env ``LLM_RERANK_API_KEY`` or ``OPENAI_API_KEY``).
        top_k: Number of results to send for reranking (default 10).
        timeout: HTTP timeout in seconds (default 30).
        plugin_manager: Optional PluginManager whose ``pre_llm_call`` hooks
            run before the request is sent (Hermes lifecycle parity).
    """
    if not results:
        return results

    # Resolve config
    endpoint = endpoint or os.getenv("LLM_RERANK_ENDPOINT", "http://127.0.0.1:4000/v1")
    model = model or os.getenv("LLM_RERANK_MODEL", "ds-deepseek-v4-flash")
    api_key = api_key or os.getenv("LLM_RERANK_API_KEY") or os.getenv("OPENAI_API_KEY", "")

    # Build candidate list
    candidates_text = "\n".join(
        f"[{i}] {r.get('content', '')[:500]}" for i, r in enumerate(results[:top_k])
    )
    prompt = _RERANK_PROMPT.format(query=query, candidates=candidates_text)

    # Plugin pre_llm_call hook (Hermes lifecycle parity)
    messages: list[dict[str, str]] = [
        {"role": "user", "content": prompt},
    ]
    call_kwargs: dict[str, Any] = {"temperature": 0.0, "max_tokens": 256}
    if plugin_manager is not None:
        try:
            messages, model, call_kwargs = plugin_manager.dispatch_pre_llm_call(
                messages, model, **call_kwargs
            )
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("pre_llm_call dispatch failed: %s", e)

    try:
        # Retry with backoff for rate limits
        resp = None
        for attempt in range(3):
            try:
                body: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    **call_kwargs,
                }
                resp = httpx.post(
                    f"{endpoint.rstrip('/')}/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                    timeout=timeout,
                )
            except (httpx.ConnectError, httpx.TimeoutException):
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise
            if resp.status_code == 429:
                wait = 2**attempt
                logger.warning(
                    "LLM rerank rate-limited, retrying in %ds (attempt %d/3)", wait, attempt + 1
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        else:
            raise httpx.HTTPStatusError(
                "429 rate limit after 3 retries", request=resp.request, response=resp
            )
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = (msg.get("content") or "").strip()

        # Reasoning models (DeepSeek-R1, o1, etc.) put their output in
        # reasoning_content and leave content empty.  Fall back so the
        # JSON parser still has something to work with.
        if not content:
            reasoning = msg.get("reasoning_content") or ""
            if reasoning:
                content = reasoning.strip()

        # Strip markdown code fences if present
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        # Robust JSON parsing — LLMs sometimes return malformed JSON
        scores = _parse_rerank_json(content)

        # Merge LLM scores back into original results
        score_map: dict[int, tuple[float, str]] = {}
        for s in scores:
            idx = int(s["index"])
            score_map[idx] = (float(s["score"]) / 10.0, s.get("reason", ""))

        for i, r in enumerate(results[:top_k]):
            if i in score_map:
                r["score"] = score_map[i][0]
                r["rerank_reason"] = score_map[i][1]
            else:
                r["score"] = r.get("score", 0.0) * 0.5  # penalize unranked
                r["rerank_reason"] = "not reranked by LLM"

        # Re-sort by new scores
        results[:top_k] = sorted(
            results[:top_k],
            key=lambda r: r.get("score", 0.0),
            reverse=True,
        )

    except (
        json.JSONDecodeError,
        httpx.HTTPStatusError,
        httpx.ConnectError,
        httpx.TimeoutException,
    ) as exc:
        logger.warning("LLM rerank failed, returning original results: %s", exc)

    return results


# =====================================================================
# Reranker Protocol
# =====================================================================

RerankerFunc = Callable[[str, list[dict[str, Any]], dict[str, Any]], list[dict[str, Any]]]


class BaseReranker:
    """Base class for all rerankers.

    Subclasses implement ``_rerank(query, candidates, kwargs)`` and
    optionally ``__init__``.
    """

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Rerank candidates by relevance to *query*.

        Args:
            query: The original search query.
            candidates: List of result dicts (should have ``content`` or
                ``memory_content`` key).
            **kwargs: Reranker-specific options.

        Returns:
            Candidates re-sorted, with ``score`` updated.
        """
        raise NotImplementedError


# =====================================================================
# Cross-Encoder Reranker (via embedder service or client-side)
# =====================================================================


class CrossEncoderReranker(BaseReranker):
    """Cross-encoder reranker using the embedder service at /v1/rerank.

    Default endpoint: ``http://localhost:9090/v1/rerank``.
    Falls back to a client-side LLM-based pair scoring if the embedder
    service is unreachable.
    """

    def __init__(
        self,
        endpoint: str = "http://localhost:9090/v1/rerank",
        model: str = "bge-reranker-large",
        timeout: int = 30,
    ):
        self._endpoint = endpoint
        self._model = model
        self._timeout = timeout

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if not candidates:
            return candidates

        content_key = kwargs.get("content_key", "memory_content")
        top_k = kwargs.get("top_k", 20)

        # Try the embedder rerank endpoint first
        try:
            return self._rerank_via_service(query, candidates, content_key, top_k)
        except Exception:
            logger.warning(
                "Cross-encoder service at %s failed, falling back to LLM pair scoring",
                self._endpoint,
            )
            return self._rerank_via_llm(query, candidates, content_key, top_k)

    def _rerank_via_service(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        content_key: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Use the embedder /v1/rerank endpoint."""
        docs = [
            r.get(content_key) or r.get("content", "")
            for r in candidates[:top_k]
        ]
        resp = httpx.post(
            f"{self._endpoint.rstrip('/')}/rerank",
            json={"query": query, "documents": docs, "model": self._model},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        # Expected format: {"results": [{"index": 0, "relevance_score": 0.98}, ...]}
        results = data.get("results", data if isinstance(data, list) else [])
        score_map: dict[int, float] = {}
        for item in results:
            idx = item.get("index")
            score = item.get("relevance_score", item.get("score", 0.0))
            if idx is not None:
                score_map[int(idx)] = float(score)

        scored = []
        for i, r in enumerate(candidates[:top_k]):
            r["cross_encoder_score"] = score_map.get(i, 0.0)
            r["score"] = r["cross_encoder_score"]
            scored.append(r)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored + candidates[top_k:]

    def _rerank_via_llm(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        content_key: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Client-side fallback: score each pair via LLM."""
        scores_list: list[tuple[dict[str, Any], float]] = []
        for r in candidates[:top_k]:
            content = r.get(content_key) or r.get("content", "")
            if not content:
                scores_list.append((r, 0.0))
                continue
            # Simple LLM prompt for relevance scoring of a single pair
            prompt = (
                f"Rate the relevance of the following text to the query on a scale "
                f"of 0.0 to 1.0. Return ONLY a number between 0.0 and 1.0, no other text.\n\n"
                f"Query: {query}\n\nText: {content[:500]}\n\nRelevance score:"
            )
            try:
                resp = httpx.post(
                    f"{os.getenv('LLM_RERANK_ENDPOINT', 'http://127.0.0.1:4000/v1')}/chat/completions",
                    json={
                        "model": os.getenv("LLM_RERANK_MODEL", "ds-deepseek-v4-flash"),
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.0,
                        "max_tokens": 10,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"].strip()
                # Extract float
                m = re.search(r"(\d+\.?\d*)", text)
                score = float(m.group(1)) if m else 0.0
                score = max(0.0, min(1.0, score))
            except Exception:
                score = r.get("score", 0.0) * 0.9  # slight decay on failure
            r["cross_encoder_score"] = score
            r["score"] = score
            scores_list.append((r, score))

        scores_list.sort(key=lambda x: x[1], reverse=True)
        return [r for r, _ in scores_list] + candidates[top_k:]


# =====================================================================
# NodeDistanceReranker
# =====================================================================


class NodeDistanceReranker(BaseReranker):
    """Rerank candidates by graph distance from query entities.

    Computes distance from entities mentioned in the query to each candidate
    node using the existing ``kg_edge`` + ``kg_node`` tables.  Shorter
    distance = higher score.  Requires a ``client`` reference with ``_sql``,
    ``_query`` methods.
    """

    def __init__(self, client: Any | None = None):
        self._client = client

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if not candidates or self._client is None:
            return candidates

        max_distance = kwargs.get("max_distance", 5.0)
        workspace_id = kwargs.get("workspace_id", "")
        if not workspace_id:
            workspace_id = candidates[0].get("workspace_id", "")

        # 1. Find entities in the query
        query_entities = self._find_query_entities(query, workspace_id)
        if not query_entities:
            return candidates

        # 2. Compute distance for each candidate
        for r in candidates:
            content = r.get("memory_content") or r.get("content", "")
            eid = r.get("entity_id", "")
            nid = r.get("node_id", "") or r.get("id", "")

            if eid or nid:
                dist = self._min_graph_distance(query_entities, eid or nid, workspace_id)
            else:
                # Try to find entities in the candidate content
                content_lower = content.lower()
                dist = min(
                    (0.5 for qe in query_entities if qe.lower() in content_lower),
                    default=max_distance,
                )

            # Score: 1.0 - (distance / max_distance), clamped [0, 1]
            nd_score = max(0.0, 1.0 - (dist / max_distance)) if dist >= 0 else 0.0
            r["node_distance_score"] = nd_score
            if "score" in r:
                r["score"] = r["node_distance_score"]

        candidates.sort(key=lambda x: x.get("node_distance_score", 0.0), reverse=True)
        return candidates

    def _find_query_entities(
        self, query: str, workspace_id: str
    ) -> list[str]:
        """Find KG node labels matching the query."""
        entities: list[str] = []
        try:
            nodes = self._client._sql(
                "SELECT label FROM kg_node "
                f"WHERE workspace_id = '{_esc_sql(workspace_id)}' "
                f"AND (LOWER(label) LIKE '%' || LOWER('{_esc_sql(query[:200])}') || '%' "
                f"OR LOWER(summary) LIKE '%' || LOWER('{_esc_sql(query[:200])}') || '%') "
                "LIMIT 20"
            )
            for n in nodes:
                label = n.get("label", "")
                if label and label.lower() in query.lower():
                    entities.append(label)
        except Exception:
            logger.debug("NodeDistanceReranker: kg_node query failed")
        return entities

    def _min_graph_distance(
        self,
        query_entities: list[str],
        candidate_id: str,
        workspace_id: str,
        max_hops: int = 3,
    ) -> float:
        """BFS-style distance from query entities to candidate node."""
        from collections import deque

        try:
            # Build adjacency from kg_edge
            edges = self._client._sql(
                "SELECT source_node_id, target_node_id FROM kg_edge "
                f"WHERE workspace_id = '{_esc_sql(workspace_id)}' "
                "ORDER BY created_at DESC LIMIT 1000"
            )
        except Exception:
            return float("inf")

        adj: dict[str, set[str]] = {}
        for e in edges:
            src = e.get("source_node_id", "")
            tgt = e.get("target_node_id", "")
            if src:
                adj.setdefault(src, set()).add(tgt)
            if tgt:
                adj.setdefault(tgt, set()).add(src)

        # Find node IDs for query entities
        entity_node_ids: list[str] = []
        try:
            nodes = self._client._sql(
                "SELECT node_id, label FROM kg_node "
                f"WHERE workspace_id = '{_esc_sql(workspace_id)}'"
            )
            for n in nodes:
                if n.get("label", "") in query_entities:
                    entity_node_ids.append(n.get("node_id", ""))
        except Exception:
            pass

        if not entity_node_ids:
            return float("inf")

        # BFS from each entity node to candidate_id
        min_dist = float("inf")
        for start in entity_node_ids:
            if start == candidate_id:
                return 0.0
            visited: set[str] = set()
            q: deque[tuple[str, int]] = deque([(start, 0)])
            visited.add(start)
            while q:
                node, dist = q.popleft()
                if dist >= max_hops or dist >= min_dist:
                    continue
                for neighbor in adj.get(node, set()):
                    if neighbor == candidate_id:
                        min_dist = min(min_dist, dist + 1)
                        break
                    if neighbor not in visited:
                        visited.add(neighbor)
                        q.append((neighbor, dist + 1))

        return float(min_dist)


def _esc_sql(val: str) -> str:
    """Escape a string for SQL single-quoted literals."""
    return val.replace("'", "''")


# =====================================================================
# MMRReranker — Maximum Marginal Relevance
# =====================================================================


class MMRReranker(BaseReranker):
    """Maximum Marginal Relevance reranker.

    Balances relevance (from existing ``score``) and diversity (via cosine
    distance between candidate embeddings).  The lambda parameter controls
    the trade-off: 1.0 = pure relevance, 0.0 = pure diversity.
    """

    def __init__(self, lambda_param: float = 0.7):
        self._lambda = lambda_param

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if not candidates or len(candidates) <= 1:
            return candidates

        top_k = kwargs.get("top_k", len(candidates))
        lambda_param = kwargs.get("lambda", self._lambda)

        # Extract scores and compute pairwise diversity
        scored: list[tuple[int, float]] = [
            (i, float(c.get("score", 0.0)))
            for i, c in enumerate(candidates)
        ]

        # Compute pairwise cosine distances using embeddings if available,
        # otherwise fall back to token overlap
        embeddings = self._extract_embeddings(candidates)
        sim_matrix = self._compute_similarity_matrix(candidates, embeddings)

        # MMR greedy selection
        selected_indices: list[int] = []
        remaining = list(range(len(candidates)))

        # Pick the first (highest relevance)
        first = max(remaining, key=lambda i: scored[i][1])
        selected_indices.append(first)
        remaining.remove(first)

        while remaining and len(selected_indices) < top_k:
            mmr_scores: list[tuple[int, float]] = []
            for i in remaining:
                relevance = scored[i][1]
                # Max similarity to any already-selected item
                max_sim = max(sim_matrix[i][j] for j in selected_indices) if selected_indices else 0.0
                mmr = lambda_param * relevance - (1.0 - lambda_param) * max_sim
                mmr_scores.append((i, mmr))

            best_idx = max(mmr_scores, key=lambda x: x[1])[0]
            selected_indices.append(best_idx)
            remaining.remove(best_idx)

        # Build result list with MMR scores
        result = []
        for rank, idx in enumerate(selected_indices):
            r = dict(candidates[idx])
            r["mmr_score"] = float(r.get("score", 0.0))
            r["mmr_rank"] = rank
            r["score"] = r["mmr_score"]
            result.append(r)

        return result

    def _extract_embeddings(
        self, candidates: list[dict[str, Any]]
    ) -> list[list[float]]:
        """Try to extract embedding vectors from candidates."""
        embeddings: list[list[float]] = []
        for r in candidates:
            emb_json = r.get("embedding", "") or r.get("embedding_json", "") or "[]"
            if isinstance(emb_json, str):
                try:
                    emb = json.loads(emb_json)
                    if isinstance(emb, list) and all(isinstance(x, (int, float)) for x in emb):
                        embeddings.append([float(x) for x in emb])
                        continue
                except (json.JSONDecodeError, TypeError):
                    pass
            elif isinstance(emb_json, list):
                embeddings.append([float(x) for x in emb_json])
                continue
            embeddings.append([])
        return embeddings

    def _compute_similarity_matrix(
        self,
        candidates: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> list[list[float]]:
        """Compute pairwise similarity matrix."""
        n = len(candidates)
        matrix: list[list[float]] = [[0.0] * n for _ in range(n)]

        has_embeddings = any(len(e) > 0 for e in embeddings)

        for i in range(n):
            for j in range(n):
                if i == j:
                    matrix[i][j] = 1.0
                elif has_embeddings and len(embeddings[i]) > 0 and len(embeddings[j]) > 0:
                    matrix[i][j] = self._cosine_sim(embeddings[i], embeddings[j])
                else:
                    # Fallback: token overlap
                    text_i = (candidates[i].get("memory_content") or candidates[i].get("content", "") or "").lower()
                    text_j = (candidates[j].get("memory_content") or candidates[j].get("content", "") or "").lower()
                    tokens_i = set(text_i.split()[:50])
                    tokens_j = set(text_j.split()[:50])
                    if tokens_i and tokens_j:
                        overlap = len(tokens_i & tokens_j)
                        matrix[i][j] = overlap / max(len(tokens_i | tokens_j), 1)
                    else:
                        matrix[i][j] = 0.0

        return matrix

    @staticmethod
    def _cosine_sim(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na < 1e-12 or nb < 1e-12:
            return 0.0
        return max(0.0, min(1.0, dot / (na * nb)))


# =====================================================================
# FusionReranker
# =====================================================================


class FusionReranker(BaseReranker):
    """Weighted linear fusion of multiple reranker scores.

    Takes a list of ``(reranker, weight)`` pairs and fuses their scores.
    Each reranker in the chain is called in sequence, each one's score
    stored as ``<name>_score`` (e.g. ``cross_encoder_score``, ``mmr_score``).
    The final fused score is the weighted sum.
    """

    def __init__(
        self,
        rerankers: list[tuple[BaseReranker, float]] | None = None,
    ):
        self._rerankers: list[tuple[BaseReranker, float]] = rerankers or []

    def add(self, reranker: BaseReranker, weight: float = 1.0) -> FusionReranker:
        """Add a reranker with a weight."""
        self._rerankers.append((reranker, weight))
        return self

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if not candidates or not self._rerankers:
            return candidates

        # Track fusion scores per candidate
        fusion_scores: dict[int, float] = {}
        total_weight = sum(w for _, w in self._rerankers)

        for reranker, weight in self._rerankers:
            reranked = reranker.rerank(query, candidates, **kwargs)
            for i, r in enumerate(reranked):
                candidate_score = r.get("score", 0.0)
                fusion_scores[i] = fusion_scores.get(i, 0.0) + candidate_score * (weight / total_weight)

        for i, r in enumerate(candidates):
            r["fusion_score"] = fusion_scores.get(i, 0.0)
            r["score"] = r["fusion_score"]

        candidates.sort(key=lambda x: x.get("fusion_score", 0.0), reverse=True)
        return candidates


# =====================================================================
# SearchFilterDSL
# =====================================================================


@dataclass
class SearchFilter:
    """A parsed search filter.

    Attributes:
        node_labels: List of KG node labels to include (e.g. ["Person", "Org"]).
        edge_types: List of edge type names (e.g. ["knows", "works_at"]).
        temporal_after: Unix timestamp for earliest results.
        temporal_before: Unix timestamp for latest results.
        property_filters: Dict of property key -> condition dict.
            Condition dict keys: "eq", "neq", "gte", "lte", "gt", "lt", "in".
        memory_types: List of memory types to include.
        entity_ids: List of specific entity IDs.
        workspace_id: Optional workspace filter.
    """
    node_labels: list[str] = field(default_factory=list)
    edge_types: list[str] = field(default_factory=list)
    temporal_after: float | None = None
    temporal_before: float | None = None
    property_filters: dict[str, dict[str, Any]] = field(default_factory=dict)
    memory_types: list[str] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    workspace_id: str = ""

    def to_sql_where(self, table_alias: str = "") -> tuple[str, list[Any]]:
        """Convert to SQL WHERE clause and params.

        Returns:
            Tuple of ``(where_clause, params_list)``.  The WHERE clause
            uses ``?`` placeholders for SpacetimeDB / SQLite param binding.
            If no filters are active, returns ``("1=1", [])``.
        """
        clauses: list[str] = []
        params: list[Any] = []
        prefix = f"{table_alias}." if table_alias else ""

        if self.node_labels:
            placeholders = ",".join("?" for _ in self.node_labels)
            clauses.append(f"({prefix}label IN ({placeholders}) OR {prefix}node_type IN ({placeholders}))")
            params.extend(self.node_labels * 2)

        if self.edge_types:
            placeholders = ",".join("?" for _ in self.edge_types)
            clauses.append(f"{prefix}relation IN ({placeholders})")
            params.extend(self.edge_types)

        if self.temporal_after is not None:
            clauses.append(f"({prefix}created_at >= ? OR {prefix}updated_at >= ?)")
            params.extend([int(self.temporal_after * 1_000_000)] * 2)

        if self.temporal_before is not None:
            clauses.append(f"({prefix}created_at <= ? OR {prefix}updated_at <= ?)")
            params.extend([int(self.temporal_before * 1_000_000)] * 2)

        if self.memory_types:
            placeholders = ",".join("?" for _ in self.memory_types)
            clauses.append(f"{prefix}memory_type IN ({placeholders})")
            params.extend(self.memory_types)

        if self.entity_ids:
            placeholders = ",".join("?" for _ in self.entity_ids)
            clauses.append(f"{prefix}entity_id IN ({placeholders})")
            params.extend(self.entity_ids)

        # Property filters: stored in metadata_json as JSON
        for key, cond in self.property_filters.items():
            if "eq" in cond:
                clauses.append(f"json_extract({prefix}metadata_json, '$.{key}') = ?")
                params.append(cond["eq"])
            if "neq" in cond:
                clauses.append(f"json_extract({prefix}metadata_json, '$.{key}') != ?")
                params.append(cond["neq"])
            if "gte" in cond:
                clauses.append(f"CAST(json_extract({prefix}metadata_json, '$.{key}') AS REAL) >= ?")
                params.append(float(cond["gte"]))
            if "lte" in cond:
                clauses.append(f"CAST(json_extract({prefix}metadata_json, '$.{key}') AS REAL) <= ?")
                params.append(float(cond["lte"]))
            if "gt" in cond:
                clauses.append(f"CAST(json_extract({prefix}metadata_json, '$.{key}') AS REAL) > ?")
                params.append(float(cond["gt"]))
            if "lt" in cond:
                clauses.append(f"CAST(json_extract({prefix}metadata_json, '$.{key}') AS REAL) < ?")
                params.append(float(cond["lt"]))
            if "in" in cond:
                values = cond["in"]
                if isinstance(values, list):
                    placeholders = ",".join("?" for _ in values)
                    clauses.append(f"json_extract({prefix}metadata_json, '$.{key}') IN ({placeholders})")
                    params.extend(values)

        where = " AND ".join(clauses) if clauses else "1=1"
        return where, params

    @classmethod
    def parse(cls, filter_str: str) -> SearchFilter:
        """Parse a filter DSL string into a SearchFilter.

        Supported syntax::

            node_labels:["Person","Org"]
            edge_types:["knows","works_at"]
            temporal:{"after": 1700000000, "before": 1800000000}
            property_filters:{"confidence": {"gte": 0.5}}
            memory_types:["fact","observation"]

        Multiple filters can be combined with spaces or newlines.
        """
        result = cls()

        if not filter_str:
            return result

        # node_labels:
        m = re.search(r'node_labels:\s*(\[.*?\])', filter_str)
        if m:
            try:
                result.node_labels = json.loads(m.group(1))
            except (json.JSONDecodeError, TypeError):
                pass

        # edge_types:
        m = re.search(r'edge_types:\s*(\[.*?\])', filter_str)
        if m:
            try:
                result.edge_types = json.loads(m.group(1))
            except (json.JSONDecodeError, TypeError):
                pass

        # temporal:
        m = re.search(r'temporal:\s*(\{.*?\})', filter_str)
        if m:
            try:
                t = json.loads(m.group(1))
                result.temporal_after = t.get("after")
                result.temporal_before = t.get("before")
            except (json.JSONDecodeError, TypeError):
                pass

        # property_filters — must handle nested braces
        m = re.search(r'property_filters:\s*(\{)', filter_str)
        if m:
            start = m.start(1)
            depth = 0
            end = start
            for i, ch in enumerate(filter_str[start:], start):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            try:
                result.property_filters = json.loads(filter_str[start:end])
            except (json.JSONDecodeError, TypeError):
                pass

        # memory_types:
        m = re.search(r'memory_types:\s*(\[.*?\])', filter_str)
        if m:
            try:
                result.memory_types = json.loads(m.group(1))
            except (json.JSONDecodeError, TypeError):
                pass

        # entity_ids:
        m = re.search(r'entity_ids:\s*(\[.*?\])', filter_str)
        if m:
            try:
                result.entity_ids = json.loads(m.group(1))
            except (json.JSONDecodeError, TypeError):
                pass

        return result


# =====================================================================
# Search Recipes — 18 named search configurations
# =====================================================================


@dataclass
class SearchRecipe:
    """A named search configuration.

    Attributes:
        name: Human-readable name (e.g. ``"keyword"``, ``"semantic"``).
        description: What this recipe is good for.
        strategy: The search strategy to use.
        reranker: Optional reranker name.
        reranker_params: Extra params for the reranker.
        filter_dsl: Optional filter DSL string.
        top_k: Default result count.
        kwargs: Additional keyword args for the search call.
    """
    name: str
    description: str
    strategy: str = "hybrid"
    reranker: str = ""
    reranker_params: dict[str, Any] = field(default_factory=dict)
    filter_dsl: str = ""
    top_k: int = 20
    kwargs: dict[str, Any] = field(default_factory=dict)


# Pre-configured recipe registry
RECIPE_REGISTRY: dict[str, SearchRecipe] = {
    "keyword": SearchRecipe(
        name="keyword",
        description="Pure keyword/BM25 search — fastest, for exact term matches",
        strategy="keyword",
        top_k=20,
    ),
    "semantic": SearchRecipe(
        name="semantic",
        description="Pure semantic/embedding search — finds conceptually similar content",
        strategy="semantic",
        top_k=20,
    ),
    "hybrid": SearchRecipe(
        name="hybrid",
        description="Combined keyword + semantic with reciprocal rank fusion — best general purpose",
        strategy="hybrid",
        top_k=30,
    ),
    "temporal": SearchRecipe(
        name="temporal",
        description="Recency-weighted search — prefers newer memories",
        strategy="temporal",
        reranker="",
        top_k=20,
    ),
    "entity_focused": SearchRecipe(
        name="entity_focused",
        description="Prioritises results linked to KG entities matching the query",
        strategy="hybrid",
        reranker="node-distance",
        reranker_params={"max_distance": 3.0},
        top_k=20,
    ),
    "recency_boosted": SearchRecipe(
        name="recency_boosted",
        description="Semantic search with recency boost — blends relevance with freshness",
        strategy="hybrid",
        kwargs={"recency_boost": True},
        top_k=20,
    ),
    "exact_phrase": SearchRecipe(
        name="exact_phrase",
        description="Quoted-phrase substring search — for literal matches",
        strategy="keyword",
        filter_dsl="",
        kwargs={"exact_phrase": True},
        top_k=10,
    ),
    "boolean": SearchRecipe(
        name="boolean",
        description="Boolean logic search (AND/OR/NOT) — for structured queries",
        strategy="keyword",
        kwargs={"boolean_mode": True},
        top_k=20,
    ),
    "fuzzy": SearchRecipe(
        name="fuzzy",
        description="Fuzzy/typo-tolerant search — catches misspellings",
        strategy="keyword",
        kwargs={"fuzzy": True, "fuzzy_distance": 2},
        top_k=20,
    ),
    "structured": SearchRecipe(
        name="structured",
        description="Filter-heavy search using property filters — for data with rich metadata",
        strategy="hybrid",
        top_k=20,
    ),
    "multi_hop": SearchRecipe(
        name="multi_hop",
        description="Graph traversal: query → entities → connected entities → memories — for relational queries",
        strategy="graph",
        reranker="",
        top_k=20,
    ),
    "semantic_graph": SearchRecipe(
        name="semantic_graph",
        description="Semantic + graph fusion — blends embedding similarity with KG connectivity",
        strategy="hybrid",
        reranker="fusion",
        reranker_params={
            "rerankers": ["cross-encoder", "node-distance"],
            "weights": [0.6, 0.4],
        },
        top_k=20,
    ),
    "adaptive": SearchRecipe(
        name="adaptive",
        description="Auto-selects strategy based on query length and structure",
        strategy="hybrid",
        reranker="cross-encoder",
        reranker_params={"top_k": 15},
        top_k=25,
    ),
    "conversation": SearchRecipe(
        name="conversation",
        description="Context-aware search for multi-turn conversations — includes session context",
        strategy="hybrid",
        reranker="mmr",
        reranker_params={"lambda": 0.6},
        top_k=15,
    ),
    "factoid": SearchRecipe(
        name="factoid",
        description="Targeted fact retrieval — high precision, low recall",
        strategy="keyword",
        reranker="cross-encoder",
        reranker_params={"top_k": 10},
        top_k=10,
    ),
    "summary": SearchRecipe(
        name="summary",
        description="Broad-coverage search for summarisation — high recall, diverse results",
        strategy="hybrid",
        reranker="mmr",
        reranker_params={"lambda": 0.4, "top_k": 30},
        top_k=30,
    ),
    "question_answering": SearchRecipe(
        name="question_answering",
        description="QA-optimised: semantic retrieval + cross-encoder reranking — for answering questions",
        strategy="semantic",
        reranker="cross-encoder",
        reranker_params={"top_k": 10},
        top_k=15,
    ),
    "exploratory": SearchRecipe(
        name="exploratory",
        description="Maximum diversity exploration — for discovery and serendipity",
        strategy="hybrid",
        reranker="mmr",
        reranker_params={"lambda": 0.3, "top_k": 30},
        top_k=30,
    ),
}

# Legacy recipe names mapped to canonical names
_RECIPE_ALIASES: dict[str, str] = {
    "recent": "recency_boosted",
    "entity": "entity_focused",
    "exact": "exact_phrase",
    "bool": "boolean",
    "qa": "question_answering",
    "explore": "exploratory",
    "graph": "multi_hop",
    "semantic-graph": "semantic_graph",
    "conversational": "conversation",
}


def resolve_recipe(name: str) -> SearchRecipe | None:
    """Resolve a recipe name (with alias lookup).

    Args:
        name: Recipe name or alias.

    Returns:
        SearchRecipe or ``None`` if not found.
    """
    canonical = _RECIPE_ALIASES.get(name, name)
    return RECIPE_REGISTRY.get(canonical)


def list_recipes() -> list[dict[str, Any]]:
    """List all registered search recipes with their descriptions.

    Returns:
        List of dicts with ``name``, ``description``, ``strategy``,
        ``reranker``, ``top_k``.
    """
    return [
        {
            "name": r.name,
            "description": r.description,
            "strategy": r.strategy,
            "reranker": r.reranker,
            "top_k": r.top_k,
        }
        for r in RECIPE_REGISTRY.values()
    ]


def get_reranker_for_recipe(
    recipe: SearchRecipe,
    client: Any = None,
) -> BaseReranker | None:
    """Factory: create a reranker instance from a recipe's config.

    Args:
        recipe: The SearchRecipe.
        client: Optional client reference (needed for NodeDistanceReranker).

    Returns:
        A BaseReranker instance or ``None``.
    """
    name = recipe.reranker
    if not name:
        return None
    params = dict(recipe.reranker_params)

    if name == "cross-encoder":
        return CrossEncoderReranker(**{k: v for k, v in params.items() if k in ("endpoint", "model", "timeout")})
    elif name == "mmr":
        return MMRReranker(lambda_param=params.get("lambda", 0.7))
    elif name == "node-distance":
        return NodeDistanceReranker(client=client)
    elif name == "fusion":
        # Build fusion from sub-rerankers
        reranker_names = params.get("rerankers", [])
        weights = params.get("weights", [1.0] * len(reranker_names))
        sub_rerankers = []
        for rn, w in zip(reranker_names, weights):
            sub_recipe = SearchRecipe(
                name="sub",
                description="",
                reranker=rn,
                reranker_params={},
            )
            sub = get_reranker_for_recipe(sub_recipe, client=client)
            if sub:
                sub_rerankers.append((sub, float(w)))
        return FusionReranker(rerankers=sub_rerankers)
    else:
        logger.warning("Unknown reranker '%s' in recipe '%s'", name, recipe.name)
        return None


# =====================================================================
# Exports
# =====================================================================

__all__ = [
    # Existing
    "_parse_rerank_json",
    "llm_rerank",
    "_RERANK_PROMPT",
    # Reranker classes
    "BaseReranker",
    "CrossEncoderReranker",
    "NodeDistanceReranker",
    "MMRReranker",
    "FusionReranker",
    # Filter DSL
    "SearchFilter",
    "SearchFilterDSL",
    # Recipes
    "SearchRecipe",
    "RECIPE_REGISTRY",
    "resolve_recipe",
    "list_recipes",
    "get_reranker_for_recipe",
]

# Legacy alias
SearchFilterDSL = SearchFilter
