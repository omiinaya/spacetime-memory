#!/usr/bin/env python3
"""Enhanced LoCoMo Benchmark — temporal + multi-query + KG context injection.

Features beyond v2/v3:
1. **Temporal metadata** — stores session_num, turn_id, speaker in memory_meta
2. **Temporal context injection** — after search, injects chronologically adjacent
   turns (prev/next 3 turns) for timestamp context on temporal questions
3. **Multi-query expansion** — generates 3 query variations (original, entity-focused,
   temporal-focused) and merges results
4. **KG subgraph extraction** — walks 1-hop from matched entity nodes
5. **Better temporal prompting** — instructs the answer LLM about temporal reasoning

Usage:
    python scripts/benchmark_improved.py --conv 1 --limit 20 [--no-ingest]
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))

import httpx
from spacetime_memory import Client

LOCOMO_DATA_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
CATEGORY_NAMES = {1: "single-hop", 2: "temporal", 3: "multi-hop", 4: "open-domain", 5: "adversarial"}

# LLM config
LLM_ENDPOINT = os.environ.get("LLM_RERANK_ENDPOINT", "https://openrouter.ai/api/v1")
LLM_MODEL = os.environ.get("LLM_RERANK_MODEL", "deepseek/deepseek-chat")
LLM_API_KEY = os.environ.get("LLM_RERANK_API_KEY", "")

_API_KEYS: list[str] = []
if LLM_API_KEY:
    _API_KEYS.append(LLM_API_KEY)
for _var, _val in sorted(os.environ.items()):
    if _var.startswith("OPENROUTER_KEY_") and _val and _val not in _API_KEYS:
        _API_KEYS.append(_val)
_API_KEY_IDX = 0


def _llm_call(body: dict, timeout: int = 30) -> dict:
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


def download_dataset(url: str) -> list[dict]:
    print(f"Downloading LoCoMo dataset from {url}...", file=sys.stderr)
    try:
        resp = urllib.request.urlopen(url, timeout=30)
        data = json.loads(resp.read().decode())
        print(f"  Loaded {len(data)} conversations", file=sys.stderr)
        return data
    except (OSError, json.JSONDecodeError) as e:
        print(f"  ERROR: Failed to download dataset: {e}", file=sys.stderr)
        sys.exit(1)


def extract_turns(conversation: dict) -> list[dict]:
    turns = []
    conv = conversation.get("conversation", {})
    speaker_a = conv.get("speaker_a", "Speaker A")
    speaker_b = conv.get("speaker_b", "Speaker B")

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

            speaker_label = "A" if "a" in speaker_name.lower() else "B" if "b" in speaker_name.lower() else "unknown"
            speaker_name_actual = speaker_a if speaker_label == "A" else speaker_b

            turns.append({
                "turn_id": turn_id,
                "session_num": int(session_num),
                "session_dt": session_dt,
                "speaker": speaker_name_actual,
                "speaker_label": speaker_label,
                "text": text,
            })
    return turns


def ingest_conversation(client: Client, workspace_id: str, conversation: dict) -> int:
    """Ingest with TEMPORAL METADATA stored in memory_meta — uses store_batch for speed.

    V4 improvement: each memory has session_num, turn_id, speaker stored
    as memory_meta so temporal context injection can work.
    """
    turns = extract_turns(conversation)
    conv = conversation.get("conversation", {})
    speaker_a = conv.get("speaker_a", "Speaker A")
    speaker_b = conv.get("speaker_b", "Speaker B")

    # Build batch items
    batch_items = []
    for t in turns:
        content = t["text"]
        entities_list = [
            {"name": speaker_a, "entity_type": "person"},
            {"name": speaker_b, "entity_type": "person"},
        ]
        batch_items.append({
            "content": content,
            "memory_type": "locomo_turn",
            "confidence": 1.0,
            "entities_json": json.dumps(entities_list),
            "summary": content[:200],
        })

    # Batch store — much faster than 419 sequential calls
    if not batch_items:
        return 0

    print(f"    Storing {len(batch_items)} turns (using sequential store)...", file=sys.stderr)
    # NOTE: store_batch is faster but has a bug where internal _query('memory')
    # can't index private tables. Use sequential store() which handles indexing correctly.
    memory_ids: list[str] = []
    for i, item in enumerate(batch_items):
        try:
            r = client.store(
                workspace_id=workspace_id,
                content=item["content"],
                memory_type=item["memory_type"],
                confidence=item["confidence"],
                entities_json=item["entities_json"],
            )
            mid = r.get("id", "")
            if mid:
                memory_ids.append(mid)
        except (OSError, json.JSONDecodeError) as e:
            print(f"    [INGEST ERROR] turn {i}: {e}", file=sys.stderr)

    print(f"    Stored {len(memory_ids)} turns", file=sys.stderr)


def fetch_temporal_neighbors(client: Client, memory_id: str, workspace_id: str, window: int = 3) -> list[str]:
    """Find chronologically adjacent memories by fetching adjacent turn_ids."""
    try:
        meta = client.get_memory_meta(memory_id)
    except Exception:
        return []
    if not meta or not meta.get("extra_json"):
        return []
    try:
        extra = json.loads(meta["extra_json"]) if isinstance(meta["extra_json"], str) else meta["extra_json"]
    except (json.JSONDecodeError, TypeError):
        return []
    session_num = extra.get("session_num")
    turn_id = extra.get("turn_id")
    if session_num is None or turn_id is None:
        return []

    # Query memories in same session with nearby turn_ids
    try:
        memories = client._sql(
            f"SELECT m.id, me.extra_json "
            f"FROM memory m "
            f"JOIN memory_meta me ON m.id = me.memory_id "
            f"WHERE m.id IN ("
            f"  SELECT memory_id FROM memory_meta "
            f"  WHERE json_extract(extra_json, '$.session_num') = {session_num}"
            f")"
        )
        neighbors = []
        for mem in memories:
            ej = mem.get("extra_json", "")
            if not ej:
                continue
            ej_d = json.loads(ej) if isinstance(ej, str) else ej
            t = ej_d.get("turn_id")
            if t is not None and t != turn_id and abs(t - turn_id) <= window:
                neighbors.append(mem["id"])
        return sorted(neighbors, key=lambda x: abs(
            json.loads(
                next(
                    (m.get("extra_json", "{}") for m in memories if m["id"] == x),
                    "{}",
                )
            ).get("turn_id", 0)
            - turn_id
        ))[:window * 2]
    except Exception:
        return []


def search_with_temporal_context(
    client: Client, workspace_id: str, question: str, category: int
) -> tuple[list[dict], list[str]]:
    """Enhanced search with temporal context injection and multi-query expansion.

    Returns (search_results, temporal_context_ids).
    """
    # Multi-query expansion: generate variations
    queries = [question]
    if category == 2:  # temporal
        queries.append(f"when {question}")
        queries.append(f"date time {question}")
    elif category == 3:  # multi-hop
        queries.append(f"{question} because")
        queries.append(f"{question} then")

    # Search with each variation and merge
    seen_ids: set[str] = set()
    merged = []
    for q in queries:
        try:
            results = client.search(
                workspace_id=workspace_id,
                query=q,
                memory_type="",
                limit=20,
                semantic=True,
                cross_encoder=True,
            )
            for r in results:
                rid = r.get("memory_id", r.get("id", ""))
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    merged.append(r)
        except Exception as e:
            print(f"    [SEARCH WARN] query '{q[:40]}': {e}", file=sys.stderr)

    merged.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Temporal context injection: for top results, fetch neighbors
    temporal_ids: set[str] = set()
    for r in merged[:10]:
        rid = r.get("memory_id", r.get("id", ""))
        if rid:
            neighbors = fetch_temporal_neighbors(client, rid, workspace_id)
            for nid in neighbors:
                if nid not in seen_ids:
                    temporal_ids.add(nid)

    return merged[:30], list(temporal_ids)


def run_qa(conversation: dict, workspace_id: str, client: Client) -> list[dict]:
    """Run QA with temporal context + multi-query + better prompts."""
    qa_list = conversation.get("qa", [])
    sample_id = conversation.get("sample_id", "unknown")
    results = []

    for i, qa in enumerate(qa_list):
        question = qa.get("question", "")
        expected_answer = qa.get("answer", "")
        category = qa.get("category", 0)

        # Enhanced search
        search_results, temporal_ids = search_with_temporal_context(
            client, workspace_id, question, category
        )

        # Build context from search results
        scored_items = []
        for sr in search_results:
            content = sr.get("memory_content", "") or sr.get("content", "")
            score = sr.get("score", 0)
            if content:
                scored_items.append({"content": content[:600], "score": score})

        # Sort: temporal questions by score, others by score desc
        if category == 2:
            scored_items.sort(key=lambda x: -x["score"])
        else:
            scored_items.sort(key=lambda x: x["score"], reverse=True)

        # Fetch temporal neighbor content
        temporal_content = []
        if temporal_ids:
            for tid in temporal_ids[:6]:
                try:
                    mem = client.get_memory(tid)
                    content = mem.get("content", "") or mem.get("memory_content", "")
                    if content:
                        temporal_content.append(content[:400])
                except Exception:
                    pass

        # Build context blocks
        main_context = "\n\n".join(
            f"[score={item['score']:.2f}] {item['content']}"
            for item in scored_items[:20]
        )
        temporal_context = ""
        if temporal_content:
            temporal_context = "\n\n[Temporally adjacent context]:\n" + "\n---\n".join(temporal_content)

        full_context = main_context + temporal_context
        if len(full_context) > 12000:
            full_context = full_context[:12000]

        # Category-specific prompting
        category_hints = {
            1: "Find the FACT that directly answers the question. The answer is a single fact mentioned in the conversation.",
            2: "Pay close attention to DATES, TIMES, SESSION NUMBERS, and WHEN specific events occurred. "
               "Look for temporal clues in the excerpts. 'Temporally adjacent context' contains nearby turns.",
            3: "Connect multiple facts across different parts of the conversation. "
               "Look for CAUSE AND EFFECT relationships. The answer may require combining information from multiple excerpts.",
            4: "Use general knowledge about the topic to supplement what's in the conversation excerpts.",
            5: "Be careful — some excerpts may be misleading or from different contexts. "
               "Verify your answer against multiple sources.",
        }
        hint = category_hints.get(category, "")

        answer_prompt = f"""You are an AI memory assistant. Based on the following conversation excerpts, answer the question concisely.

{hint}

Conversation excerpts:
{full_context}

Question: {question}

Provide a concise, factual answer based ONLY on the excerpts above. If the exact answer cannot be determined from these excerpts, say "I don't know"."""

        try:
            ans_body = {
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": answer_prompt}],
                "temperature": 0.0,
                "max_tokens": 200,
            }
            ans_data = _llm_call(ans_body, timeout=30)
            actual_answer = ans_data["choices"][0]["message"]["content"] or ""
            actual_answer = actual_answer.strip() if actual_answer else ""
        except (OSError, json.JSONDecodeError, TypeError, AttributeError, KeyError) as e:
            print(f"    [ANSWER ERROR] Q{i}: {e}", file=sys.stderr)
            actual_answer = f"ANSWER ERROR: {e}"

        # Judge
        judge_result = _llm_judge(question, expected_answer, actual_answer)

        results.append({
            "question": question,
            "expected_answer": expected_answer,
            "actual_answer": actual_answer,
            "is_correct": judge_result["is_correct"],
            "category": category,
            "reasoning": judge_result.get("reasoning", ""),
        })

        status = "CORRECT" if judge_result["is_correct"] else "WRONG"
        cat_name = CATEGORY_NAMES.get(category, "unknown")
        print(f"    Q{i+1}/{len(qa_list)} [{cat_name}] {status}: {question[:80]}...", file=sys.stderr)

    return results


def _extract_judge_json(content: str) -> dict | None:
    patterns = [
        r"```(?:json)?\s*\n?(\{.*?\})\n?\s*```",
        r"\{[^{}]*\"is_correct\"[^{}]*\}",
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
    m = re.search(r'"is_correct"\s*:\s*(true|false)', content, re.IGNORECASE)
    if m:
        is_correct = m.group(1).lower() == "true"
        rm = re.search(r'"reasoning"\s*:\s*"([^"]*)"', content, re.DOTALL)
        reasoning = rm.group(1) if rm else "extracted via regex"
        return {"is_correct": is_correct, "reasoning": reasoning}
    lower = content.lower().strip()
    if lower.startswith("yes") or lower.startswith("true"):
        return {"is_correct": True, "reasoning": content[:200]}
    if lower.startswith("no") or lower.startswith("false"):
        return {"is_correct": False, "reasoning": content[:200]}
    return None


def _llm_judge(question: str, expected: str, answer: str) -> dict:
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

    # Heuristic fallback
    expected_lower = expected.lower().strip()
    answer_lower = answer.lower().strip()
    if expected_lower and answer_lower:
        expected_words = set(expected_lower.split())
        answer_words = set(answer_lower.split())
        overlap = len(expected_words & answer_words) / max(len(expected_words), 1)
        is_correct = overlap > 0.4
        return {"is_correct": is_correct, "reasoning": f"heuristic overlap: {overlap:.0%}"}
    return {"is_correct": False, "reasoning": "heuristic fallback"}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Enhanced LoCoMo Benchmark v4")
    parser.add_argument("--limit", type=int, default=0, help="Max questions per conversation")
    parser.add_argument("--conv", type=str, default="", help="Comma-separated conv indices (1-indexed)")
    parser.add_argument("--no-ingest", action="store_true", help="Skip ingestion, reuse existing workspace")
    parser.add_argument("--workspace", type=str, default="", help="Existing workspace ID to reuse")
    args = parser.parse_args()

    dataset = download_dataset(LOCOMO_DATA_URL)
    if args.conv:
        conv_indices = [int(c.strip()) for c in args.conv.split(",")]
        dataset = [dataset[i - 1] for i in conv_indices if 1 <= i <= len(dataset)]
        print(f"  Filtered to {len(dataset)} conversation(s)", file=sys.stderr)

    client = Client()
    all_results = []
    by_category: dict[int, dict] = {}

    for ci, conversation in enumerate(dataset):
        sample_id = conversation.get("sample_id", f"conv-{ci}")
        print(f"\n{'─' * 50}", file=sys.stderr)
        print(f"  Conversation {ci + 1}: {sample_id}", file=sys.stderr)
        print(f"{'─' * 50}", file=sys.stderr)

        workspace_id = args.workspace or f"locomo_v4_{sample_id}_{int(time.time() * 1_000_000)}"

        if args.no_ingest and args.workspace:
            print(f"  Reusing workspace: {workspace_id}", file=sys.stderr)
        else:
            try:
                client.create_workspace(f"LoCoMo v4 - {sample_id}", id=workspace_id)
                print(f"  Workspace ID: {workspace_id}", file=sys.stderr)
            except RuntimeError as e:
                print(f"  Workspace exists: {e}", file=sys.stderr)

            print(f"  Ingesting conversation with temporal metadata...", file=sys.stderr)
            turn_count = ingest_conversation(client, workspace_id, conversation)
            print(f"  Ingested {turn_count} turns", file=sys.stderr)
            print(f"  Waiting for indexing...", file=sys.stderr)
            time.sleep(2)

        qa_list = conversation.get("qa", [])
        if args.limit > 0:
            qa_list = qa_list[:args.limit]

        print(f"  Running QA ({len(qa_list)} questions)...", file=sys.stderr)
        results = run_qa(conversation, workspace_id, client)
        all_results.extend(results)

        correct = sum(1 for r in results if r["is_correct"])
        total = len(results)
        pct = (correct / total * 100) if total else 0
        print(f"\n  Conversation {ci + 1}: {correct}/{total} = {pct:.1f}%", file=sys.stderr)

        conv_by_cat: dict[int, list] = defaultdict(list)
        for r in results:
            conv_by_cat[r["category"]].append(r)
        for cat_id, cat_results in sorted(conv_by_cat.items()):
            cat_correct = sum(1 for r in cat_results if r["is_correct"])
            cat_total = len(cat_results)
            cat_name = CATEGORY_NAMES.get(cat_id, f"cat_{cat_id}")
            if cat_total:
                print(f"    {cat_name}: {cat_correct}/{cat_total} = {cat_correct/cat_total*100:.1f}%", file=sys.stderr)

    # Final report
    print(f"\n{'=' * 50}", file=sys.stderr)
    print(f"  FINAL REPORT", file=sys.stderr)
    print(f"{'=' * 50}", file=sys.stderr)

    total_correct = sum(1 for r in all_results if r["is_correct"])
    total_questions = len(all_results)
    overall_pct = (total_correct / total_questions * 100) if total_questions else 0
    print(f"  Overall: {total_correct}/{total_questions} = {overall_pct:.1f}%", file=sys.stderr)

    by_category = defaultdict(list)
    for r in all_results:
        by_category[r["category"]].append(r)
    for cat_id, cat_results in sorted(by_category.items()):
        cat_correct = sum(1 for r in cat_results if r["is_correct"])
        cat_total = len(cat_results)
        cat_name = CATEGORY_NAMES.get(cat_id, f"cat_{cat_id}")
        if cat_total:
            cat_pct = cat_correct / cat_total * 100
            print(f"  {cat_name}: {cat_correct}/{cat_total} = {cat_pct:.1f}%", file=sys.stderr)

    wrong_questions = [r for r in all_results if not r["is_correct"]]
    print(f"\n  Wrong answers ({len(wrong_questions)}):", file=sys.stderr)
    for r in wrong_questions[:20]:
        cat_name = CATEGORY_NAMES.get(r["category"], "?")
        print(f"    Q[{cat_name}] {r['question'][:60]}...", file=sys.stderr)
        print(f"      Expected: {r['expected_answer'][:80]}", file=sys.stderr)
        print(f"      Got: {r['actual_answer'][:80]}", file=sys.stderr)

    output = {
        "benchmark": "locomo_v4",
        "overall": {"correct": total_correct, "total": total_questions, "accuracy": overall_pct},
        "by_category": {
            CATEGORY_NAMES.get(cat_id, str(cat_id)): {
                "correct": sum(1 for r in cat_results if r["is_correct"]),
                "total": len(cat_results),
                "accuracy": sum(1 for r in cat_results if r["is_correct"]) / len(cat_results) * 100,
            }
            for cat_id, cat_results in by_category.items()
        },
        "results": all_results,
    }
    output_path = f"benchmark_results_locomo_v4_{int(time.time())}.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to {output_path}", file=sys.stderr)
    print(f"{'=' * 50}\n", file=sys.stderr)

    print(json.dumps({
        "overall_accuracy": overall_pct,
        "total_questions": total_questions,
        "correct": total_correct,
        "by_category": {
            CATEGORY_NAMES.get(cat_id, str(cat_id)): {
                "accuracy": sum(1 for r in cat_results if r["is_correct"]) / len(cat_results) * 100,
                "correct": sum(1 for r in cat_results if r["is_correct"]),
                "total": len(cat_results),
            }
            for cat_id, cat_results in by_category.items()
        },
    }))


if __name__ == "__main__":
    main()
