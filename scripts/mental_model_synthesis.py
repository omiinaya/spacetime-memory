#!/usr/bin/env python3
"""Mental Model Synthesis — LLM-powered synthesis of higher-level abstractions.

Queries all mental models with status="pending", reads their source memories,
calls an OpenAI-compatible API to synthesize a mental model, and updates the
record with the generated content.

Usage:
    python3 scripts/mental_model_synthesis.py [--all] [--dry-run]

Options:
    --all      Process ALL pending models (default: only those created in last 24h)
    --dry-run  Print what would be synthesized without calling the LLM
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import httpx

# ── Config ──────────────────────────────────────────────────────────
HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get("SPACETIMEDB_DB", "spacetime-memory")
EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://localhost:9090")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

SQL_URL = f"http://{HOST}:{PORT}/v1/database/{DB}/sql"
CALL_URL = f"http://{HOST}:{PORT}/v1/database/{DB}/call"

_http = httpx.Client(timeout=60)


# ── Helpers ─────────────────────────────────────────────────────────

def _sql(query: str) -> list[dict[str, Any]]:
    resp = _http.post(SQL_URL, content=query, headers={"Content-Type": "text/plain"})
    if resp.status_code >= 400:
        print(f"  SQL error ({resp.status_code}): {resp.text[:200]}")
        return []
    return _parse_sql_response(resp.text)


def _call(reducer: str, args: list[Any]) -> bool:
    resp = _http.post(
        f"{CALL_URL}/{reducer}",
        content=json.dumps(args),
        headers={"Content-Type": "application/json"},
    )
    ok = resp.status_code < 400
    if not ok:
        print(f"  Reducer '{reducer}' error ({resp.status_code}): {resp.text[:200]}")
    return ok


def _parse_sql_response(raw: str) -> list[dict[str, Any]]:
    if not raw.strip():
        return []
    try:
        tables = json.loads(raw)
        rows: list[dict[str, Any]] = []
        for table in tables:
            cols = [e["name"]["some"] for e in table["schema"]["elements"]]
            for row in table.get("rows", []):
                r: dict[str, Any] = {}
                for i, col in enumerate(cols):
                    r[_to_camel(col)] = row[i]
                rows.append(r)
        return rows
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"  Parse error: {e}")
        return []


def _to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _esc(s: str) -> str:
    return s.replace("'", "''")


# ── LLM Call ────────────────────────────────────────────────────────


def call_llm(prompt: str) -> tuple[str, float] | None:
    """Call OpenAI-compatible API and return (content, confidence).

    Returns None on failure.
    """
    if not OPENAI_API_KEY:
        print("  [ERROR] OPENAI_API_KEY not set. Skipping LLM call.")
        return None

    url = f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "You are a cognitive synthesis engine."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
    }

    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=120)
        if resp.status_code >= 400:
            print(f"  LLM API error ({resp.status_code}): {resp.text[:300]}")
            return None
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return content, 0.85  # fixed confidence after LLM generation
    except Exception as e:
        print(f"  LLM call failed: {e}")
        return None


# ── Prompt Builder ──────────────────────────────────────────────────


def build_prompt(memories: list[dict[str, Any]]) -> str:
    """Build an LLM prompt from a list of memory records."""
    formatted = []
    for i, m in enumerate(memories, 1):
        content = m.get("content", "")
        summary = m.get("summary", "")
        mem_type = m.get("memoryType", "")
        line = f"{i}. [{mem_type}] {summary}: {content}" if summary else f"{i}. [{mem_type}] {content}"
        formatted.append(line)

    memories_text = "\n".join(formatted)

    prompt = f"""You are a cognitive synthesis engine. From the following experiences/memories, identify patterns, draw conclusions, and formulate a concise mental model.

Experiences:
{memories_text}

Synthesize a mental model that captures the key insight, pattern, or heuristic. Be specific and actionable. Keep it under 500 words."""
    return prompt


# ── Core Logic ──────────────────────────────────────────────────────


def get_pending_models(all_flag: bool = False) -> list[dict[str, Any]]:
    """Fetch mental models with status='pending'.

    If all_flag is False, only models created in the last 24 hours.
    """
    cutoff = int(time.time() * 1000) - 24 * 3_600_000 if not all_flag else 0
    where = "status = 'pending'"
    if cutoff > 0:
        where += f" AND updated_at > {cutoff}"

    rows = _sql(f"SELECT * FROM mental_model WHERE {where} ORDER BY created_at ASC")
    return rows


def get_memories(memory_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch memory records by IDs."""
    if not memory_ids:
        return []
    ids_quoted = [f"'{_esc(mid)}'" for mid in memory_ids]
    where = "id IN (" + ",".join(ids_quoted) + ")"
    rows = _sql(f"SELECT id, content, summary, memory_type FROM memory WHERE {where}")
    return rows


def process_model(model: dict[str, Any], dry_run: bool = False) -> bool:
    """Process a single pending mental model.

    Returns True on success.
    """
    model_id = model.get("id", "")
    workspace_id = model.get("workspaceId", "")
    memory_ids_json = model.get("sourceMemoryIds", "[]")

    try:
        memory_ids = json.loads(memory_ids_json)
    except json.JSONDecodeError:
        print(f"  [ERROR] Invalid source_memory_ids for model '{model_id[:16]}...'")
        _call("update_mental_model", [model_id, "", 0.0, "failed"])
        return False

    print(f"  Model {model_id[:16]}... ({len(memory_ids)} source memories)")

    if not memory_ids:
        print(f"    No source memories — marking as failed.")
        _call("update_mental_model", [model_id, "", 0.0, "failed"])
        return False

    # Fetch source memories
    memories = get_memories(memory_ids)
    if not memories:
        print(f"    No memories found — marking as failed.")
        _call("update_mental_model", [model_id, "", 0.0, "failed"])
        return False

    # Build prompt
    prompt = build_prompt(memories)
    print(f"    Prompt built from {len(memories)} memories")

    if dry_run:
        print(f"    [DRY-RUN] Would call LLM with prompt ({len(prompt)} chars)")
        print(f"    [DRY-RUN] Memories: {[m.get('id', '')[:16] + '...' for m in memories]}")
        return True

    # Call LLM
    result = call_llm(prompt)
    if result is None:
        print(f"    LLM call failed — marking as failed.")
        _call("update_mental_model", [model_id, "", 0.0, "failed"])
        return False

    content, confidence = result
    print(f"    LLM generated {len(content)} chars, confidence={confidence}")

    # Update the mental model
    success = _call("update_mental_model", [model_id, content, confidence, "completed"])
    if success:
        print(f"    [OK] Updated successfully")
    else:
        print(f"    [ERROR] Failed to update model")
        return False

    return True


def run(all_flag: bool = False, dry_run: bool = False) -> dict[str, Any]:
    """Main synthesis loop."""
    results = {
        "total": 0,
        "succeeded": 0,
        "failed": 0,
        "dry_run": dry_run,
    }

    models = get_pending_models(all_flag=all_flag)
    results["total"] = len(models)
    print(f"Found {len(models)} pending mental model(s)")

    for model in models:
        ok = process_model(model, dry_run=dry_run)
        if ok:
            results["succeeded"] += 1
        else:
            results["failed"] += 1

    return results


# ── CLI ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthesize mental models from pending requests using LLM.",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Process ALL pending models (default: only those from last 24h)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be synthesized without calling LLM",
    )
    args = parser.parse_args()

    print(f"[{time.strftime('%H:%M:%S')}] Mental model synthesis starting...")
    results = run(all_flag=args.all, dry_run=args.dry_run)

    mode = " [DRY-RUN]" if results["dry_run"] else ""
    print(
        f"[{time.strftime('%H:%M:%S')}] Done{mode}: "
        f"{results['total']} total, "
        f"{results['succeeded']} succeeded, "
        f"{results['failed']} failed"
    )

    if results["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
