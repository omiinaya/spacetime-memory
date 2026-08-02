#!/usr/bin/env python3
"""LoCoMo Benchmark for Spacetime-Memory.

Evaluates Spacetime-Memory on the LoCoMo (Long Context Memorization) benchmark
from snap-research. Downloads the dataset, ingests conversations into
SpacetimeDB workspaces, runs QA queries, and reports accuracy by category.

Usage:
    python scripts/locomo_benchmark.py [--limit N] [--convs N1,N2,...]
    python scripts/locomo_benchmark.py --quick          # 100 questions
    python scripts/locomo_benchmark.py --conv 1          # single conversation

Output:
    - Real-time progress to stderr
    - JSON report to stdout with per-category accuracy breakdown
    - Saves results to benchmark_results_locomo.json
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

# Ensure SDK is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))

import httpx
from spacetime_memory import Client

# ── Config ──
LOCOMO_DATA_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"

CATEGORY_NAMES = {
    1: "single-hop",
    2: "temporal",
    3: "multi-hop",
    4: "open-domain",
    5: "adversarial",
}

EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://localhost:9090")
STDB_URL = os.environ.get("SPACETIMEDB_URL", "http://localhost:3001")

# LLM judge config (uses OpenRouter directly for evaluation)
LLM_ENDPOINT = os.environ.get(
    "LLM_RERANK_ENDPOINT", "https://openrouter.ai/api/v1"
)
LLM_MODEL = os.environ.get("LLM_RERANK_MODEL", "deepseek/deepseek-v4-flash")
LLM_API_KEY = os.environ.get("LLM_RERANK_API_KEY", "")

# API key rotation — multiple OpenRouter keys for rate limit avoidance
_API_KEYS: list[str] = []
if LLM_API_KEY:
    _API_KEYS.append(LLM_API_KEY)
# Load additional keys from environment (OPENROUTER_KEY_1..8 etc.)
for _var, _val in sorted(os.environ.items()):
    if _var.startswith("OPENROUTER_KEY_") and _val and _val not in _API_KEYS:
        _API_KEYS.append(_val)
_API_KEY_IDX = 0


def _llm_call(body: dict, timeout: int = 30) -> dict:
    """Call the LLM endpoint with key rotation and retry."""
    global _API_KEY_IDX
    max_retries = 5
    for attempt in range(max_retries):
        key = _API_KEYS[_API_KEY_IDX % len(_API_KEYS)] if _API_KEYS else ""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}" if key else "",
        }
        try:
            resp = httpx.post(
                LLM_ENDPOINT.rstrip("/") + "/chat/completions",
                headers=headers,
                json=body,
                timeout=timeout,
            )
            if resp.status_code == 429:
                # Rate limited — rotate key and retry with backoff
                _API_KEY_IDX = (_API_KEY_IDX + 1) % max(1, len(_API_KEYS))
                wait = min(2 ** attempt, 30)
                print(f"    [RATE LIMITED] rotating key, retrying in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            wait = min(2 ** attempt, 30)
            print(f"    [TIMEOUT] retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
    raise RuntimeError(f"LLM call failed after {max_retries} retries")


# If not set via env, try loading from .hermes/.env
_env_path = os.path.expanduser("~/.hermes/.env")
if not LLM_API_KEY and os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            if line.strip().startswith("LITELLM_MASTER_KEY="):
                _, k = line.split("=", 1)
                LLM_API_KEY = k.strip().strip('"').strip("'")
            elif line.strip().startswith("OPENROUTER_API_KEY="):
                _, k = line.split("=", 1)
                LLM_API_KEY = k.strip().strip('"').strip("'")


# ── Helpers ──


def download_dataset(url: str) -> list[dict]:
    """Download the LoCoMo dataset from GitHub."""
    print(f"Downloading LoCoMo dataset from {url}...", file=sys.stderr)
    try:
        resp = urllib.request.urlopen(url, timeout=30)
        data = json.loads(resp.read().decode())
        print(f"  Loaded {len(data)} conversations", file=sys.stderr)
        return data
    except (OSError, json.JSONDecodeError) as e:
        print(f"  ERROR: Failed to download dataset: {e}", file=sys.stderr)
        sys.exit(1)


def _extract_judge_json(content: str) -> dict | None:
    """Extract is_correct/reasoning JSON from LLM response with multiple fallback strategies."""
    # Strategy 1: Try to find a JSON object in the response
    patterns = [
        # ```json ... ``` block
        r"```(?:json)?\s*\n?(\{.*?\})\n?\s*```",
        # bare JSON object with is_correct
        r"\{[^{}]*\"is_correct\"[^{}]*\}",
        # Relaxed: any object with is_correct value
        r"\{[^{}]*\"is_correct\"\s*:\s*(true|false)[^{}]*\}",
    ]
    for pat in patterns:
        m = re.search(pat, content, re.DOTALL | re.IGNORECASE)
        if m:
            candidate = m.group(1) if m.lastindex else m.group(0)
            try:
                result = json.loads(candidate)
                if "is_correct" in result:
                    return result
            except json.JSONDecodeError:
                continue

    # Strategy 2: Look for true/false after is_correct with loose regex
    m = re.search(r'"is_correct"\s*:\s*(true|false)', content, re.IGNORECASE)
    if m:
        is_correct = m.group(1).lower() == "true"
        rm = re.search(r'"reasoning"\s*:\s*"([^"]*)"', content, re.DOTALL)
        reasoning = rm.group(1) if rm else "extracted via regex"
        return {"is_correct": is_correct, "reasoning": reasoning}

    # Strategy 3: Look for yes/no in the response start
    lower = content.lower().strip()
    if lower.startswith("yes") or lower.startswith("true"):
        return {"is_correct": True, "reasoning": content[:200]}
    if lower.startswith("no") or lower.startswith("false"):
        return {"is_correct": False, "reasoning": content[:200]}

    return None


def llm_judge(question: str, expected: str, answer: str) -> dict:
    """Use an LLM to judge if answer matches expected.

    Returns dict with 'is_correct' (bool) and 'reasoning' (str).
    Uses multiple fallback strategies and retries.
    """
    # Quick exit for system errors
    if not answer or answer.startswith("ANSWER ERROR") or answer.startswith("SEARCH ERROR"):
        return {"is_correct": False, "reasoning": f"System failed to answer: {answer[:100]}"}

    prompt = f"""You are evaluating an AI memory system's ability to recall information from long conversations.

Question: {question}

Expected answer: {expected}

System's answer: {answer}

Task: Determine whether the system's answer is semantically correct (i.e., conveys the same information) as the expected answer. Be lenient — accept paraphrases, partial matches, and differently formatted dates/times as long as the core fact is correct.

Respond with a JSON object:
{{"is_correct": true/false, "reasoning": "brief explanation"}}
IMPORTANT: Your response MUST be valid JSON only, no markdown formatting."""
    body = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 200,
    }
    for attempt in range(3):
        try:
            data = _llm_call(body, timeout=30)
            content = data["choices"][0]["message"]["content"] or ""
            content = content.strip() if content else ""
            result = _extract_judge_json(content)
            if result is not None:
                return {"is_correct": bool(result.get("is_correct", False)), "reasoning": result.get("reasoning", "")}
        except (OSError, TypeError, AttributeError, KeyError, RuntimeError) as e:
            print(f"    [JUDGE ERROR attempt {attempt+1}] {e}", file=sys.stderr)

    # Last-resort heuristic: word overlap
    print(f"    [JUDGE] Falling back to heuristic for: {question[:60]}...", file=sys.stderr)
    expected_lower = expected.lower().strip()
    answer_lower = answer.lower().strip()
    if expected_lower and answer_lower:
        expected_words = set(expected_lower.split())
        answer_words = set(answer_lower.split())
        overlap = len(expected_words & answer_words) / max(len(expected_words), 1)
        is_correct = overlap > 0.4
        return {"is_correct": is_correct, "reasoning": f"heuristic overlap: {overlap:.0%}"}
    return {"is_correct": False, "reasoning": "heuristic fallback"}


def extract_turns(conversation: dict) -> list[dict]:
    """Extract all turns from a conversation with metadata."""
    turns = []
    conv = conversation.get("conversation", {})
    speaker_a = conv.get("speaker_a", "Speaker A")
    speaker_b = conv.get("speaker_b", "Speaker B")

    # Find all session keys (session_1, session_2, etc.)
    session_keys = sorted(
        [k for k in conv.keys() if k.startswith("session_") and not k.endswith("_date_time")],
        key=lambda x: int(x.split("_")[1]),
    )

    turn_id = 0
    for sk in session_keys:
        session_num = sk.split("_")[1]
        date_time_key = f"session_{session_num}_date_time"
        session_dt = conv.get(date_time_key, f"Session {session_num}")

        session_turns = conv.get(sk, [])
        for t in session_turns:
            turn_id += 1
            speaker_name = t.get("speaker", "")
            text = t.get("text", "")
            dia_id = t.get("dia_id", "")
            img_url = t.get("img_url", "")

            # Classify speaker
            speaker_label = "A" if "a" in speaker_name.lower() else "B" if "b" in speaker_name.lower() else "unknown"
            speaker_name_actual = speaker_a if speaker_label == "A" else speaker_b

            turns.append({
                "turn_id": turn_id,
                "session_num": int(session_num),
                "session_dt": session_dt,
                "speaker": speaker_name_actual,
                "speaker_label": speaker_label,
                "dia_id": dia_id,
                "text": text,
                "img_url": img_url,
            })
    return turns


def ingest_conversation(client: Client, workspace_id: str, conversation: dict) -> int:
    """Ingest all turns from a conversation into the workspace.

    Returns the number of memories stored.
    """
    turns = extract_turns(conversation)
    conv = conversation.get("conversation", {})
    speaker_a = conv.get("speaker_a", "Speaker A")
    speaker_b = conv.get("speaker_b", "Speaker B")
    sample_id = conversation.get("sample_id", "unknown")

    count = 0
    for t in turns:
        # Build content with context — prepend metadata for better retrieval signal
        content = t["text"]
        metadata = {
            "conversation_id": sample_id,
            "session_num": t["session_num"],
            "session_dt": t["session_dt"],
            "speaker": t["speaker"],
            "speaker_label": t["speaker_label"],
            "turn_id": t["turn_id"],
            "dia_id": t["dia_id"],
        }

        # Store as memory — content includes temporal metadata prefix for better semantic search
        try:
            # Include temporal metadata in content itself so it's part of the embedding,
            # improving retrieval for temporal questions
            content_with_meta = f"[Session {t['session_num']} | {t['session_dt']}] {t['speaker']}: {content}"
            client.store(
                workspace_id=workspace_id,
                content=content_with_meta,
                memory_type="locomo_turn",
                confidence=1.0,
                tier="L0",
                # Attach metadata via entities_json
                entities_json=json.dumps([
                    {"name": speaker_a, "entity_type": "person"},
                    {"name": speaker_b, "entity_type": "person"},
                    {"name": f"session_{t['session_num']}", "entity_type": "session"},
                    {"name": f"turn_{t['turn_id']}", "entity_type": "turn_id"},
                ]),
            )
            count += 1
        except (OSError, json.JSONDecodeError) as e:
            print(f"    [INGEST ERROR] turn {t['turn_id']}: {e}", file=sys.stderr)

    # Also store session summaries as memories
    session_summaries = conversation.get("session_summary", {})
    if session_summaries:
        for sess_key, summary in session_summaries.items():
            if summary:
                try:
                    client.store(
                        workspace_id=workspace_id,
                        content=f"[Session Summary] {summary}",
                        memory_type="locomo_summary",
                        confidence=0.9,
                        tier="L0",
                    )
                except (OSError, json.JSONDecodeError):
                    pass

    return count


def _extract_metadata_from_result(sr: dict) -> dict:
    """Extract temporal metadata from search result fields."""
    meta = {}

    # Try entities_json
    entities_raw = sr.get("entities_json", "[]")
    if entities_raw and isinstance(entities_raw, str):
        try:
            entities = json.loads(entities_raw)
            for e in entities:
                if isinstance(e, dict):
                    name = e.get("name", "")
                    etype = e.get("entity_type", "")
                    if etype == "session" and name.startswith("session_"):
                        meta["session_num"] = int(name.split("_")[1])
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    # Try metadata field (some search modes return this)
    if not meta.get("session_num"):
        s_meta = sr.get("metadata", "")
        if s_meta and isinstance(s_meta, str):
            try:
                md = json.loads(s_meta)
                if "session_num" in md:
                    meta["session_num"] = int(md["session_num"])
                    meta["session_dt"] = md.get("session_dt", "")
                    meta["turn_id"] = md.get("turn_id", 0)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

    # Direct fields as last resort
    if not meta.get("session_num"):
        for key in ("session_num", "turn_id"):
            val = sr.get(key) or sr.get(f"_{key}", None)
            if val is not None:
                try:
                    meta[key] = int(val)
                except (TypeError, ValueError):
                    meta[key] = val

    return meta


def run_qa(conversation: dict, workspace_id: str, client: Client) -> list[dict]:
    """Run all QA queries for a conversation and return results.

    Each result dict has: question, expected_answer, actual_answer,
    is_correct, category, reasoning, evidence.
    """
    qa_list = conversation.get("qa", [])
    sample_id = conversation.get("sample_id", "unknown")

    results = []

    for i, qa in enumerate(qa_list):
        question = qa.get("question", "")
        expected_answer = qa.get("answer", "")
        category = qa.get("category", 0)

        # Search workspace for relevant memories — broad search with no type filter
        # to include both locomo_turn and locomo_summary memories
        try:
            search_results = client.search(
                workspace_id=workspace_id,
                query=question,
                memory_type="",      # no filter — search all types
                limit=40,
                semantic=True,
                cross_encoder=False,
            )
        except (OSError, json.JSONDecodeError) as e:
            print(f"    [SEARCH ERROR] Q{i}: {e}", file=sys.stderr)
            results.append({
                "question": question,
                "expected_answer": expected_answer,
                "actual_answer": f"SEARCH ERROR: {e}",
                "is_correct": False,
                "category": category,
                "reasoning": f"Search failed: {e}",
                "evidence": [],
            })
            continue

        # Build context from search results — sorted roughly chronologically
        # and with metadata included for temporal questions
        scored_items = []
        for sr in search_results[:30]:
            content = sr.get("memory_content", "") or sr.get("content", "")
            score = sr.get("score", 0)
            meta = _extract_metadata_from_result(sr)
            session_num = meta.get("session_num", -1)

            if content:
                scored_items.append({
                    "content": content[:500],
                    "score": score,
                    "session_num": session_num,
                    "metadata": meta,
                })

        # Sort: for temporal questions, prefer chronological order;
        # for others, relevance score order
        if category == 2:  # temporal questions → chronological order
            scored_items.sort(key=lambda x: (x["session_num"] if x["session_num"] >= 0 else 9999))
        else:
            scored_items.sort(key=lambda x: x["score"], reverse=True)

        # Build context with metadata
        context_parts = []
        for item in scored_items[:20]:
            meta = item["metadata"]
            prefix_parts = []
            if "session_num" in meta and meta["session_num"] >= 0 and category == 2:
                prefix_parts.append(f"[Session {meta['session_num']}]")
            if "session_dt" in meta and meta.get("session_dt"):
                prefix_parts.append(f"[{meta['session_dt']}]")
            prefix = " ".join(prefix_parts)
            if prefix:
                context_parts.append(f"{prefix} (score={item['score']:.2f}) {item['content']}")
            else:
                context_parts.append(f"[score={item['score']:.2f}] {item['content']}")

        context = "\n\n".join(context_parts)

        # Use LLM to answer the question — different prompt for temporal vs factual
        if category == 2:
            answer_prompt = f"""You are an AI memory assistant. Based on the following conversation excerpts with timestamps, answer the TEMPORAL question.

The excerpts are from a long conversation between two people across multiple sessions.
Pay close attention to dates, times, and session numbers — the question asks WHEN something happened.

Conversation excerpts (chronologically ordered):
{context[:8000]}

Question: {question}

Provide a concise, factual answer with the specific date/time if available. Base your answer ONLY on the excerpts above. If the exact answer cannot be determined, say "I don't know"."""
        else:
            answer_prompt = f"""You are an AI memory assistant. Based on the following conversation excerpts, answer the question concisely.

Conversation excerpts:
{context[:8000]}

Question: {question}

Provide a concise, factual answer based ONLY on the excerpts above. If the answer cannot be determined from the excerpts, say "I don't know"."""

        try:
            ans_body = {
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": answer_prompt}],
                "temperature": 0.0,
                "max_tokens": 150,
            }
            ans_data = _llm_call(ans_body, timeout=30)
            actual_answer = ans_data["choices"][0]["message"]["content"] or ""
            actual_answer = actual_answer.strip() if actual_answer else ""
        except (OSError, json.JSONDecodeError, TypeError, AttributeError, KeyError) as e:
            print(f"    [ANSWER ERROR] Q{i}: {e}", file=sys.stderr)
            actual_answer = f"ANSWER ERROR: {e}"

        # Judge correctness
        judge_result = llm_judge(question, expected_answer, actual_answer)

        results.append({
            "question": question,
            "expected_answer": expected_answer,
            "actual_answer": actual_answer,
            "is_correct": judge_result["is_correct"],
            "category": category,
            "reasoning": judge_result["reasoning"],
            "evidence": qa.get("evidence", []),
        })

        # Print progress
        cat_name = CATEGORY_NAMES.get(category, f"cat-{category}")
        status = "CORRECT" if judge_result["is_correct"] else "WRONG"
        print(f"    Q{i + 1}/{len(qa_list)} [{cat_name}] {status}: {question[:60]}...", file=sys.stderr)

    return results


def aggregate_results(all_results: list[dict]) -> dict:
    """Aggregate results by category."""
    by_cat = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in all_results:
        cat = r.get("category", 0)
        by_cat[cat]["total"] += 1
        if r.get("is_correct", False):
            by_cat[cat]["correct"] += 1

    report = {}
    total_all = 0
    correct_all = 0
    for cat in sorted(by_cat.keys()):
        t = by_cat[cat]["total"]
        c = by_cat[cat]["correct"]
        acc = (c / t * 100) if t > 0 else 0.0
        cat_name = CATEGORY_NAMES.get(cat, f"cat-{cat}")
        report[cat_name] = {
            "total": t,
            "correct": c,
            "accuracy": round(acc, 2),
        }
        total_all += t
        correct_all += c

    # Primary metric: categories 1-4 (no adversarial)
    primary_cats = [1, 2, 3, 4]
    primary_total = sum(by_cat[c]["total"] for c in primary_cats)
    primary_correct = sum(by_cat[c]["correct"] for c in primary_cats)
    primary_acc = (primary_correct / primary_total * 100) if primary_total > 0 else 0.0

    overall_acc = (correct_all / total_all * 100) if total_all > 0 else 0.0
    report["__primary__"] = {
        "categories": [CATEGORY_NAMES[c] for c in primary_cats],
        "total": primary_total,
        "correct": primary_correct,
        "accuracy": round(primary_acc, 2),
    }
    report["__overall__"] = {
        "total": total_all,
        "correct": correct_all,
        "accuracy": round(overall_acc, 2),
    }
    return report


# ── Main ──

def main():
    import argparse

    parser = argparse.ArgumentParser(description="LoCoMo Benchmark for Spacetime-Memory")
    parser.add_argument("--limit", type=int, default=0, help="Limit total questions (default: all)")
    parser.add_argument("--conv", type=str, default="", help="Comma-separated conversation indices (1-based)")
    parser.add_argument("--quick", action="store_true", help="Quick mode: 100 random questions")
    parser.add_argument("--no-ingest", action="store_true", help="Skip ingest phase (resume)")
    parser.add_argument("--output", type=str, default="benchmark_results_locomo.json", help="Output file")
    parser.add_argument("--workspace", type=str, default="", help="Existing workspace ID (skips ingest)")
    args = parser.parse_args()

    # Set Python unbuffered for real-time output
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore
    sys.stderr.reconfigure(line_buffering=True)  # type: ignore

    print("=" * 60, file=sys.stderr)
    print("  LoCoMo Benchmark for Spacetime-Memory", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Connect to SpacetimeDB
    print("\nConnecting to SpacetimeDB...", file=sys.stderr)
    db_id = os.environ.get("SPACETIMEDB_DB", "")
    if not db_id:
        print("ERROR: SPACETIMEDB_DB must be set", file=sys.stderr)
        sys.exit(1)
    token_resp = httpx.get(f"{STDB_URL}/v1/database/{db_id}", timeout=10)
    token = token_resp.headers.get("spacetime-identity-token", "")
    identity = token_resp.headers.get("spacetime-identity", "")
    client = Client(
        database=db_id,
        embedder_url=EMBEDDER_URL,
        token=token or None,
    )
    try:
        random_suffix = os.urandom(4).hex()
        client._call("register", [f"locomo-bench-{random_suffix}", "lmeval2026", identity])
    except Exception:
        pass
    tok_display = client.token[:16] if client.token else "none"
    print(f"  Connected (token: {tok_display}...)", file=sys.stderr)

    # Download dataset
    dataset = download_dataset(LOCOMO_DATA_URL)

    # Filter conversations
    if args.conv:
        conv_indices = [int(x.strip()) - 1 for x in args.conv.split(",")]
        dataset = [dataset[i] for i in conv_indices if 0 <= i < len(dataset)]
        print(f"  Filtered to {len(dataset)} conversation(s)", file=sys.stderr)

    all_results = []

    for conv_idx, conversation in enumerate(dataset):
        sample_id = conversation.get("sample_id", f"conv_{conv_idx + 1}")
        print(f"\n{'─' * 50}", file=sys.stderr)
        print(f"  Conversation {conv_idx + 1}: {sample_id}", file=sys.stderr)
        print(f"{'─' * 50}", file=sys.stderr)

        # Create or use existing workspace
        workspace_name = f"locomo_{sample_id}"
        if args.workspace:
            workspace_id = args.workspace
            print(f"  Using existing workspace: {workspace_id}", file=sys.stderr)
        else:
            try:
                ws = client.create_workspace(name=workspace_name, description=f"LoCoMo benchmark: {sample_id}")
                workspace_id = ws.get("id", ws.get("workspace_id", ""))
                if not workspace_id:
                    # Try to find existing workspace
                    workspaces = client.list_workspaces()
                    for w in workspaces:
                        if w.get("name") == workspace_name:
                            workspace_id = w.get("id", w.get("workspace_id", ""))
                            break
                if not workspace_id:
                    print(f"  ERROR: Could not create/find workspace '{workspace_name}'", file=sys.stderr)
                    continue
                print(f"  Workspace ID: {workspace_id}", file=sys.stderr)
            except (OSError, json.JSONDecodeError) as e:
                print(f"  ERROR creating workspace: {e}", file=sys.stderr)
                continue

        # Ingest conversation
        if not args.no_ingest:
            print("  Ingesting conversation...", file=sys.stderr)
            ingested = ingest_conversation(client, workspace_id, conversation)
            print(f"  Ingested {ingested} turns", file=sys.stderr)
            # Small delay to let indexing complete
            time.sleep(2)
        else:
            print("  Skipping ingest (--no-ingest)", file=sys.stderr)

        # Run QA
        qa_list = conversation.get("qa", [])
        if args.limit > 0:
            qa_list = qa_list[:args.limit]
        if args.quick:
            import random
            random.seed(42)
            qa_list = random.sample(qa_list, min(100, len(qa_list)))

        print(f"  Running QA ({len(qa_list)} questions)...", file=sys.stderr)
        results = run_qa(conversation, workspace_id, client)
        all_results.extend(results)

        # Interim report
        report = aggregate_results(all_results)
        primary = report.get("__primary__", {})
        print(f"\n  Interim accuracy: {primary.get('accuracy', 0):.1f}% (primary, {primary.get('correct', 0)}/{primary.get('total', 0)})", file=sys.stderr)

    # Final report
    print(f"\n{'=' * 60}", file=sys.stderr)
    print("  FINAL RESULTS", file=sys.stderr)
    print(f"{'=' * 60}", file=sys.stderr)

    report = aggregate_results(all_results)
    for cat_name, data in sorted(report.items()):
        if cat_name.startswith("__"):
            continue
        print(f"  {cat_name:20s}: {data['accuracy']:6.2f}%  ({data['correct']:4d}/{data['total']:4d})", file=sys.stderr)

    primary = report.get("__primary__", {})
    overall = report.get("__overall__", {})
    print(f"\n  {'PRIMARY (cats 1-4)':20s}: {primary.get('accuracy', 0):6.2f}%  ({primary.get('correct', 0):4d}/{primary.get('total', 0):4d})", file=sys.stderr)
    print(f"  {'OVERALL':20s}: {overall.get('accuracy', 0):6.2f}%  ({overall.get('correct', 0):4d}/{overall.get('total', 0):4d})", file=sys.stderr)

    # Save to file
    output = {
        "benchmark": "LoCoMo",
        "timestamp": time.time(),
        "model": LLM_MODEL,
        "config": {
            "embedder_url": EMBEDDER_URL,
            "stdb_url": STDB_URL,
            "llm_endpoint": LLM_ENDPOINT,
            "llm_model": LLM_MODEL,
        },
        "report": report,
        "results": all_results,
    }
    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {output_path}", file=sys.stderr)

    # Print JSON to stdout for piping
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
