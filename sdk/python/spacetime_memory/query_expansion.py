"""LLM-powered query expansion for better retrieval.

Expands a user query with synonyms, related terms, vendor/product names,
and acronyms before sending it to the hybrid search pipeline.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_EXPAND_PROMPT = (
    "Expand this search query to improve retrieval in a knowledge base. "
    "Add related terms, synonyms, vendor/product names, acronyms, and "
    "technical alternatives that would appear in stored facts. "
    "Keep the original intent. Do NOT answer the query. "
    "Return ONLY the expanded query string, no explanation."
)


def expand_query(
    query: str,
    endpoint: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: int = 15,
) -> str:
    """Expand a query with synonyms and related terms for better retrieval.

    Uses the same LLM endpoint/model as the reranker (env vars
    ``LLM_RERANK_ENDPOINT``, ``LLM_RERANK_MODEL``, ``LLM_RERANK_API_KEY``).

    Returns the expanded query string, or the original query on failure.
    """
    endpoint = endpoint or os.getenv(
        "LLM_RERANK_ENDPOINT", "http://localhost:4000/v1"
    )
    model = model or os.getenv("LLM_RERANK_MODEL", "gpt-4o-mini")
    api_key = (
        api_key
        or os.getenv("LLM_RERANK_API_KEY")
        or os.getenv("OPENAI_API_KEY", "")
    )

    try:
        resp = httpx.post(
            f"{endpoint.rstrip('/')}/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _EXPAND_PROMPT},
                    {"role": "user", "content": query},
                ],
                "temperature": 0.0,
                "max_tokens": 200,
            },
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = (msg.get("content") or "").strip()

        # Reasoning model fallback
        if not content:
            reasoning = msg.get("reasoning_content") or ""
            if reasoning:
                content = reasoning.strip()
            else:
                return query

        # Merge original + expanded — keep phrases from both
        if len(content) > 5 and content.lower() != query.lower():
            merged = f"{query} {content}"
            logger.info("Expanded query: %r -> %r", query, merged[:200])
            return merged
        return query

    except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError):
        logger.exception("Query expansion failed, using original query")
        return query
