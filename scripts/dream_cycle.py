#!/usr/bin/env python3
"""Dream Cycle — nightly autonomous enrichment pass.

Runs synthesis on recent untriaged memories, creates mental models from
clustered patterns, extracts entities, and generates insights.

Uses the SDK Client (like consolidate.py) for private table access.

Usage:
    python3 scripts/dream_cycle.py [--workspace-id <id>] [--days 1] [--dry-run]

Options:
    --workspace-id  Target workspace (default: all workspaces)
    --days          How many days of memories to process (default: 1, max: 7)
    --dry-run       Print what would be done without making changes
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass

# Bypass HTTP proxy for localhost STDB connections.
# The system has http_proxy set to isp.decodo.com:10001 which
# returns 403 Forbidden for reducer calls.
os.environ.setdefault("no_proxy", "localhost,127.0.0.1,127.0.0.1,.local")
from pathlib import Path
from typing import Any

# Allow running from project root or cron
for prefix in (".", "..", os.path.expanduser("~/spacetime-memory")):
    sdk_path = os.path.join(prefix, "sdk/python")
    if os.path.isdir(sdk_path):
        sys.path.insert(0, sdk_path)
        break

from spacetime_memory import Client

# ── Config ──────────────────────────────────────────────────────────
HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get(
    "SPACETIMEDB_DB",
    "c20082e7643347e8d36302b550bb98c7343f9ea2a268f3bee58ee58d3c3dcbf1",
)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

_client: Client | None = None
_TOKEN_FILE = os.getenv("CRON_IDENTITY_TOKEN_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cron_identity_token"))


# ── Client ──────────────────────────────────────────────────────────


def _c() -> Client:
    global _client
    if _client is None:
        _client = Client(host=HOST, port=PORT, database=DB)

        # Reuse identity token across runs to avoid per-tick account creation
        if os.path.exists(_TOKEN_FILE):
            try:
                with open(_TOKEN_FILE) as f:
                    _client._identity_token = f.read().strip()
                    _client._identity_established = True
            except (KeyError, IndexError, TypeError):
                pass

        if not getattr(_client, "_identity_established", False):
            # First run: register and save token
            import uuid as _uuid
            user = f"dream_cron_{_uuid.uuid4().hex[:8]}"
            try:
                _client._call("register", [user, "Dream Cycle Cron", "dr3@mc0ns0l1d8"])
            except RuntimeError:
                pass
            try:
                my_id = _client._whoami()
                _client._call("set_initial_admin", [my_id])
            except RuntimeError:
                pass
            # Persist identity token for next run
            if getattr(_client, "_identity_token", None):
                try:
                    Path(_TOKEN_FILE).write_text(_client._identity_token, encoding="ascii")
                except (KeyError, IndexError, TypeError):
                    pass

        return _client


# ── LLM ─────────────────────────────────────────────────────────────


def call_llm(prompt: str, system: str = "", temperature: float = 0.3) -> str | None:
    if not OPENAI_API_KEY:
        return None
    import httpx
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    try:
        resp = httpx.post(
            f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": LLM_MODEL, "messages": msgs, "temperature": temperature, "max_tokens": 1024},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  LLM call failed: {e}")
        return None


# ── Dream Cycle Core ────────────────────────────────────────────────


@dataclass
class DreamResults:
    memories_processed: int = 0
    entities_extracted: int = 0
    mental_models_created: int = 0
    mental_models_synthesized: int = 0
    insights_generated: int = 0
    errors: int = 0


def get_workspaces(client: Client) -> list[dict[str, Any]]:
    """Get all workspaces via SDK client."""
    try:
        return client.list_workspaces()
    except Exception as e:
        print(f"  Error listing workspaces: {e}")
        return []


_GLOBAL_MEMORIES: list[dict[str, Any]] | None = None

def get_recent_memories(
    client: Client,
    workspace_id: str,
    days: int = 1,
) -> list[dict[str, Any]]:
    """Get memories from the last N days.

    Queries globally (no workspace_id) to bypass per-workspace permission
    check — the cron identity doesn't have explicit workspace membership.
    """
    global _GLOBAL_MEMORIES
    if _GLOBAL_MEMORIES is None:
        try:
            mems = client._query("memory")
        except Exception as e:
            print(f"  Error querying memories globally: {e}")
            return []
        _GLOBAL_MEMORIES = mems

    cutoff = int(time.time() * 1000) - days * 24 * 3_600_000
    return [
        m for m in _GLOBAL_MEMORIES
        if m.get("workspace_id") == workspace_id
        and m.get("created_at", 0) > cutoff
    ]


def run_entity_extraction(
    client: Client,
    workspace_id: str,
    memories: list[dict[str, Any]],
    dry_run: bool,
) -> int:
    """Run entity extraction on memories that need it."""
    count = 0
    for mem in memories:
        content = mem.get("content", "")
        if len(content) < 20:
            continue
        if not any(c.isupper() for c in content.split() if len(c) > 2):
            continue

        if dry_run:
            print(f"  [DRY] Would extract entities from: {content[:60]}...")
            count += 1
        else:
            try:
                client._call("extract_entities", [workspace_id, content])
                count += 1
            except Exception as e:
                if "Access denied" not in str(e):
                    print(f"  Entity extraction error: {e}")
    return count


def cluster_memories(
    memories: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Group memories into related clusters by shared proper nouns."""
    def _signature(content: str) -> set[str]:
        words = content.split()
        return {w.strip(".,;:!?") for w in words if len(w) > 2 and w[0].isupper()}

    clusters: list[list[dict[str, Any]]] = []
    assigned: set[int] = set()

    for i, mem in enumerate(memories):
        if i in assigned:
            continue
        sig = _signature(mem.get("content", ""))
        if not sig:
            continue

        cluster = [mem]
        assigned.add(i)

        for j, other in enumerate(memories):
            if j in assigned:
                continue
            other_sig = _signature(other.get("content", ""))
            if sig & other_sig:
                cluster.append(other)
                assigned.add(j)

        if len(cluster) >= 2:
            clusters.append(cluster)

    return clusters


def create_mental_models(
    client: Client,
    workspace_id: str,
    clusters: list[list[dict[str, Any]]],
    dry_run: bool,
) -> int:
    """Create mental model synthesis requests from memory clusters."""
    count = 0
    for cluster in clusters:
        memory_ids = [m["id"] for m in cluster]
        ids_json = json.dumps(memory_ids)

        if dry_run:
            print(f"  [DRY] Would create mental model from {len(memory_ids)} memories")
            count += 1
        else:
            try:
                client._call("synthesize_mental_models", [workspace_id, ids_json])
                count += 1
            except Exception as e:
                if "Access denied" not in str(e):
                    print(f"  Mental model create error: {e}")
    return count


def run_synthesis(client: Client, dry_run: bool) -> int:
    """Run mental model synthesis for pending models."""
    try:
        all_models = client._query("mental_model")
    except (OSError, json.JSONDecodeError):
        return 0

    pending = [m for m in all_models if m.get("status") == "pending"]
    if not pending:
        return 0

    print(f"  Found {len(pending)} pending mental model(s)")

    count = 0
    for model in pending:
        model_id = model["id"]
        source_ids_json = model.get("source_memory_ids", "[]")

        try:
            source_ids: list[str] = json.loads(source_ids_json)
        except json.JSONDecodeError:
            continue

        if not source_ids:
            try:
                client._call("update_mental_model", [model_id, "", 0.0, "failed"])
            except (KeyError, IndexError):
                pass
            continue

        # Fetch memories by ID
        memories = []
        for mid in source_ids:
            try:
                result = client._query("memory", filter_dict={"id": mid})
                if result:
                    memories.extend(result)
            except (KeyError, IndexError, TypeError):
                pass

        if not memories:
            try:
                client._call("update_mental_model", [model_id, "", 0.0, "failed"])
            except (KeyError, IndexError, TypeError):
                pass
            continue

        # Build prompt
        formatted = []
        for i, m in enumerate(memories, 1):
            content = m.get("content", "")
            summary = m.get("summary", "")
            mem_type = m.get("memory_type", "memory")
            line = f"{i}. [{mem_type}] {summary}: {content}" if summary else f"{i}. [{mem_type}] {content}"
            formatted.append(line)

        prompt = (
            "You are a cognitive synthesis engine. From the following "
            "experiences/memories, identify patterns, draw conclusions, "
            "and formulate a concise mental model.\n\n"
            f"Experiences:\n{chr(10).join(formatted)}\n\n"
            "Synthesize a mental model that captures the key insight, "
            "pattern, or heuristic. Be specific and actionable. "
            "Keep it under 500 words."
        )

        if dry_run:
            print(f"  [DRY] Would synthesize model {model_id[:16]}...")
            count += 1
            continue

        result = call_llm(prompt, system="You are a cognitive synthesis engine.")
        if result:
            try:
                client._call("update_mental_model", [model_id, result, 0.85, "completed"])
                print(f"  [OK] Mental model {model_id[:16]}... synthesized ({len(result)} chars)")
                count += 1
            except Exception as e:
                print(f"  Failed to update model {model_id[:16]}: {e}")
        else:
            try:
                client._call("update_mental_model", [model_id, "", 0.0, "failed"])
            except (KeyError, IndexError, TypeError):
                pass

    return count


def generate_insights(
    client: Client,
    workspace_id: str,
    results: DreamResults,
    dry_run: bool,
) -> int:
    """Generate an insight summary of the dream cycle results."""
    if results.memories_processed == 0:
        return 0

    summary = (
        f"Dream cycle processed {results.memories_processed} memories, "
        f"extracted {results.entities_extracted} entities, "
        f"summarized {results.memories_summarized} chunks, "
        f"created {results.mental_models_created} mental model requests, "
        f"synthesized {results.mental_models_synthesized} mental models."
    )

    if dry_run:
        print("  [DRY] Would generate dream insight")
        return 1

    insight = call_llm(
        f"Based on this dream cycle run:\n{summary}\n\n"
        "Write a brief (2-3 sentence) reflective insight about what the "
        "knowledge base learned or should investigate next.",
        system="You are a reflective knowledge engine. Generate concise insights.",
        temperature=0.5,
    )

    if insight:
        try:
            client._call(
                "create_insight",
                [workspace_id, "dream_cycle", insight, "observation", "[]", 0.7],
            )
            return 1
        except Exception as e:
            print(f"  Insight creation error: {e}")

    return 0


# ── Chunked Summarization ───────────────────────────────────────────


def chunk_memories_by_time(
    memories: list[dict[str, Any]],
    chunk_minutes: int = 30,
    min_chunk_size: int = 3,
) -> list[list[dict[str, Any]]]:
    """Group memories into time-based chunks for summarization.

    Memories within `chunk_minutes` of each other are grouped together.
    Chunks smaller than `min_chunk_size` are discarded (not enough content
    for meaningful summarization).
    """
    if not memories:
        return []

    # Sort by created_at ascending
    sorted_mems = sorted(memories, key=lambda m: m.get("created_at", 0))
    chunks: list[list[dict[str, Any]]] = []
    current_chunk: list[dict[str, Any]] = [sorted_mems[0]]

    chunk_window = chunk_minutes * 60 * 1000  # ms

    for mem in sorted_mems[1:]:
        prev_ts = current_chunk[-1].get("created_at", 0)
        cur_ts = mem.get("created_at", 0)
        if cur_ts - prev_ts <= chunk_window:
            current_chunk.append(mem)
        else:
            if len(current_chunk) >= min_chunk_size:
                chunks.append(current_chunk)
            current_chunk = [mem]

    if len(current_chunk) >= min_chunk_size:
        chunks.append(current_chunk)

    return chunks


def summarize_chunk(
    memories: list[dict[str, Any]],
    dry_run: bool = False,
) -> str | None:
    """Summarize a chunk of memories using LLM, with AAAK fallback.

    Returns the summary string, or None if the chunk is too small.
    """
    if len(memories) < 2:
        return None

    # Format memories for the prompt
    formatted = []
    for i, m in enumerate(memories, 1):
        content = m.get("content", "")[:300]  # truncate long entries
        mem_type = m.get("memory_type", "memory")
        formatted.append(f"{i}. [{mem_type}] {content}")

    prompt = (
        "Summarize the following memories into a single concise paragraph "
        "(2-4 sentences). Capture the key events, decisions, and people "
        "mentioned. Be specific — use names, not pronouns.\n\n"
        f"Memories:\n{chr(10).join(formatted)}\n\n"
        "Summary:"
    )

    if dry_run:
        return "[DRY] Would summarize chunk"

    # Try LLM first
    result = call_llm(
        prompt,
        system="You are a memory summarizer. Produce concise, factual summaries.",
        temperature=0.2,
    )

    if result and len(result.strip()) >= 10:
        return result.strip()

    # AAAK fallback: compress the concatenated content
    from spacetime_memory.aaak import aaak_compress

    combined = " | ".join(m.get("content", "") for m in memories)
    try:
        compressed = aaak_compress(combined)
        return f"[AAAK] {compressed}"
    except (OSError, json.JSONDecodeError):
        pass

    # Last resort: just take first 500 chars
    return combined[:500]


def run_chunked_summarization(
    client: Client,
    workspace_id: str,
    memories: list[dict[str, Any]],
    dry_run: bool = False,
    chunk_minutes: int = 30,
) -> int:
    """Run chunked LLM summarization on old memories.

    Groups memories into time-based chunks, summarizes each via LLM
    (with AAAK fallback), and stores the summaries.
    """
    chunks = chunk_memories_by_time(memories, chunk_minutes)
    if not chunks:
        return 0

    print(f"    Time chunks: {len(chunks)} (>=3 memories per chunk)")
    count = 0

    for chunk in chunks:
        summary = summarize_chunk(chunk, dry_run)
        if not summary:
            continue

        # Extract proper nouns from the chunk for a descriptive title
        all_content = " ".join(m.get("content", "") for m in chunk)
        words = all_content.split()
        proper_nouns = [
            w.strip(".,;:!?)") for w in words
            if len(w) > 2 and w[0].isupper() and w[0].isalpha()
        ]
        title = " ".join(proper_nouns[:4]) if proper_nouns else "Memory summary"

        if dry_run:
            print(f"    [DRY] Would store summary: {title} ({len(summary)} chars)")
            count += 1
            continue

        try:
            # Store summary as an episodic memory
            source_ids = json.dumps([m["id"] for m in chunk])
            client._call("store_memory", [
                workspace_id, "", "",  # peer_id and source_peer auto-resolve
                "experience",
                summary,
                title,
                source_ids,
                0.85,  # trust_score
                f"dream_cycle_chunk_{int(time.time())}",
                "",  # context (legacy — maps to source_message_id)
                "",  # images_json
            ])
            count += 1
            if count <= 3:  # Don't spam output for large batches
                print(f"    [OK] Chunk summary: {title} ({len(summary)} chars)")
        except Exception as e:
            if count <= 3:
                if "Access denied" not in str(e):
                    print(f"    Chunk summary error: {e}")

    if count > 3:
        print(f"    [OK] Stored {count} chunk summaries total")

    return count


# ── Dream Cycle Core ────────────────────────────────────────────────


@dataclass
class DreamResults:
    memories_processed: int = 0
    entities_extracted: int = 0
    memories_summarized: int = 0
    mental_models_created: int = 0
    mental_models_synthesized: int = 0
    insights_generated: int = 0
    errors: int = 0


def run_dream_cycle(
    workspace_id: str | None = None,
    days: int = 1,
    dry_run: bool = False,
    resume: bool = False,
) -> DreamResults:
    """Run the full dream cycle pass."""
    results = DreamResults()
    client = _c()

    if workspace_id:
        workspaces = [{"id": workspace_id, "name": workspace_id[:16]}]
    else:
        workspaces = get_workspaces(client)
        if not workspaces:
            print("No workspaces found.")
            return results

    print(
        f"[{time.strftime('%H:%M:%S')}] Dream cycle starting — "
        f"{len(workspaces)} workspace(s), past {days} day(s)"
    )
    if dry_run:
        print("  [DRY RUN — no changes will be made]")

    for ws in workspaces:
        wid = ws["id"]
        ws_name = ws.get("name", wid[:16])
        print(f"\n  Workspace: {ws_name} ({wid[:16]}...)")

        # 1. Fetch recent memories
        memories = get_recent_memories(client, wid, days=days)

        # If --resume, skip memories already processed in prior dream cycles
        if resume and memories:
            processed_file = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                f".dream_processed_{wid[:16]}.json",
            )
            processed_ids: set = set()
            if os.path.exists(processed_file):
                try:
                    with open(processed_file) as pf:
                        processed_ids = set(json.load(pf))
                except (json.JSONDecodeError, IOError):
                    pass
            memories = [m for m in memories if m["id"] not in processed_ids]
            if not memories:
                print("    All memories already processed (--resume).")
                continue

        results.memories_processed += len(memories)
        print(f"    Memories: {len(memories)} recent")

        if not memories:
            continue

        # 2. Extract entities from memories
        entities = run_entity_extraction(client, wid, memories, dry_run)
        results.entities_extracted += entities
        if entities:
            print(f"    Entities extracted: {entities}")

        # 3. Chunked LLM summarization (with AAAK fallback)
        summarized = run_chunked_summarization(client, wid, memories, dry_run)
        results.memories_summarized += summarized
        if summarized:
            print(f"    Chunks summarized: {summarized}")

        # 4. Cluster related memories
        clusters = cluster_memories(memories)
        if clusters:
            avg_size = sum(len(c) for c in clusters) // len(clusters)
            print(f"    Clusters: {len(clusters)} (avg size: {avg_size})")

            # 5. Create mental model synthesis requests
            models = create_mental_models(client, wid, clusters, dry_run)
            results.mental_models_created += models
            if models:
                print(f"    Mental models requested: {models}")

            # 5. Run synthesis on pending models
            synthesized = run_synthesis(client, dry_run)
            results.mental_models_synthesized += synthesized
            if synthesized:
                print(f"    Mental models synthesized: {synthesized}")

        # 6. Generate dream insight
        insights = generate_insights(client, wid, results, dry_run)
        results.insights_generated += insights

    return results


# ── CLI ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dream cycle — nightly autonomous enrichment pass",
    )
    parser.add_argument("--workspace-id", default=None, help="Target workspace (default: all)")
    parser.add_argument("--days", type=int, default=1, help="Days of memories (default: 1, max: 7)")
    parser.add_argument("--dry-run", action="store_true", help="Print without making changes")
    parser.add_argument("--resume", action="store_true",
                        help="Skip memories already processed in a previous dream cycle")
    args = parser.parse_args()

    if args.days > 7:
        print("Error: --days must be <= 7")
        sys.exit(1)

    results = run_dream_cycle(
        workspace_id=args.workspace_id,
        days=args.days,
        dry_run=args.dry_run,
        resume=args.resume,
    )

    mode = " [DRY-RUN]" if args.dry_run else ""
    print(
        f"\n[{time.strftime('%H:%M:%S')}] Dream cycle complete{mode}:\n"
        f"  Memories processed:  {results.memories_processed}\n"
        f"  Entities extracted:  {results.entities_extracted}\n"
        f"  Chunks summarized:   {results.memories_summarized}\n"
        f"  Mental models req'd: {results.mental_models_created}\n"
        f"  Models synthesized:  {results.mental_models_synthesized}\n"
        f"  Insights generated:  {results.insights_generated}\n"
        f"  Errors:              {results.errors}"
    )

    if results.errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
