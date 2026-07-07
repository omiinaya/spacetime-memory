"""Internal utility functions extracted from monolithic client.py."""
from __future__ import annotations

import json
import re
from typing import Any


def _esc(val: str) -> str:
    """Basic SQL string escaping for single-quoted string literals."""
    return val.replace("'", "''")


def _query_hash(query: str) -> str:
    """Deterministic hash matching the Rust hybrid_query reducer."""
    h = 0
    for b in query.encode("utf-8"):
        h = ((h * 6364136223846793005) + b) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def _parse_sql_response(raw: str) -> list[dict[str, Any]]:
    """Parse SpacetimeDB's positional-array SQL response into dicts."""
    if not raw.strip():
        return []
    tables = json.loads(raw)
    results: list[dict[str, Any]] = []
    for table in tables:
        elements = table.get("schema", {}).get("elements", [])
        col_names: list[str] = []
        for el in elements:
            name_container = el.get("name", {})
            if isinstance(name_container, dict) and "some" in name_container:
                col_names.append(name_container["some"])
            else:
                col_names.append("?col?")
        for row in table.get("rows", []):
            row_dict: dict[str, Any] = {}
            for i, val in enumerate(row):
                key = col_names[i] if i < len(col_names) else f"col{i}"
                row_dict[key] = val
            results.append(row_dict)
    return results


def _make_snippet(text: str, max_chars: int = 200) -> str:
    """Truncate text at word boundary, appending '...' if truncated.

    Args:
        text: The full text to truncate.
        max_chars: Maximum character length before truncation (default 200).

    Returns:
        Truncated text ending at a word boundary, with ``...`` appended
        if the original exceeded *max_chars*.  Returns ``\"\"`` for
        falsy input.
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    # Break at last space within the truncated portion
    last_space = truncated.rfind(" ")
    if last_space > max_chars // 2:  # Only use word boundary if non-trivial
        truncated = truncated[:last_space]
    return truncated.rstrip() + "..."


# ---------------------------------------------------------------------------
# LLM Reranking (QMD parity)
# ---------------------------------------------------------------------------


