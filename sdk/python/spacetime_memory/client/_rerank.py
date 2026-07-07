"""LLM reranking utilities extracted from monolithic client.py."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


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

    try:
        # Retry with backoff for rate limits
        resp = None
        for attempt in range(3):
            try:
                resp = httpx.post(
                    f"{endpoint.rstrip('/')}/chat/completions",
                    json={
                        "model": model,
                        "messages": [
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.0,
                        "max_tokens": 2048,
                    },
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


