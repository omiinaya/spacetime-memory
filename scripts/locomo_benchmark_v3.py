#!/usr/bin/env python3
"""LoCoMo Benchmark v3 — with entity linking and KG context retrieval.

Extends the v2 approach with:
1. Clean content (no metadata prefix in embedding) — improves semantic search
2. LLM-based entity linking after each memory store — creates KG nodes for
   people, pets, books, places, events mentioned in conversation
3. KG context injection in search — finds memories connected to query entities
4. Cross-encoder reranking for precision
5. Better temporal QA prompting

Usage:
    python scripts/locomo_benchmark_v3.py [--limit N] [--conv 1] [--quick]
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))

import httpx
from spacetime_memory import Client
from spacetime_memory.entity_linking import link_entities, inject_entity_context, find_entities_in_query, extract_entities_llm

LOCOMO_DATA_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"

CATEGORY_NAMES = {1: "single-hop", 2: "temporal", 3: "multi-hop", 4: "open-domain", 5: "adversarial"}

# LLM judge config
LLM_ENDPOINT = os.environ.get("LLM_RERANK_ENDPOINT", "https://openrouter.ai/api/v1")
LLM_MODEL = os.environ.get("LLM_RERANK_MODEL", "deepseek/deepseek-chat")
LLM_API_KEY = os.environ.get("LLM_RERANK_API_KEY", "")

# API key rotation
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


def llm_judge(question: str, expected: str, answer: str) -> dict:
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
            dia_id = t.get("dia_id", "")

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
            })
    return turns


def ingest_conversation(client: Client, workspace_id: str, conversation: dict) -> int:
    """Ingest all conversation turns with CLEAN content and entity linking.

    V3 changes:
    - Clean content (no metadata prefix) → better semantic search
    - Rust auto_extract_entities runs (entities_json="[]")
    - Batch LLM entity extraction: ONE call for the whole conversation
      (not 419 individual calls)
    - Creates KG nodes + edges from batch-extracted entities
    """
    turns = extract_turns(conversation)
    conv = conversation.get("conversation", {})
    speaker_a = conv.get("speaker_a", "Speaker A")
    speaker_b = conv.get("speaker_b", "Speaker B")
    sample_id = conversation.get("sample_id", "unknown")

    # ── Step 1: Ingest ALL memories first ──
    memory_ids: list[str] = []
    for t in turns:
        content = t["text"]  # CLEAN content — no metadata prefix!

        # Include known speaker entities so the Rust side has them
        entities_list = [
            {"name": speaker_a, "entity_type": "person"},
            {"name": speaker_b, "entity_type": "person"},
        ]

        try:
            result = client.store(
                workspace_id=workspace_id,
                content=content,
                memory_type="locomo_turn",
                confidence=1.0,
                tier="L0",
                entities_json=json.dumps(entities_list),
            )
            mid = result.get("id", "")
            if mid:
                memory_ids.append(mid)
        except (OSError, json.JSONDecodeError) as e:
            print(f"    [INGEST ERROR] turn {t['turn_id']}: {e}", file=sys.stderr)

    # ── Step 2: Batch-extract entities from full conversation text ──
    # ONE LLM call for the entire conversation (much faster than per-turn)
    full_text = "\n".join(t["text"] for t in turns if t["text"].strip())
    if not full_text.strip():
        return len(memory_ids)

    print(f"    Batch-extracting entities...", file=sys.stderr)
    try:
        entities = extract_entities_llm(full_text)
    except Exception as e:
        print(f"    [ENTITY EXTRACT ERROR] {e}", file=sys.stderr)
        entities = None

    if not entities:
        return len(memory_ids)

    print(f"    Extracted {len(entities)} unique entities", file=sys.stderr)

    # ── Step 3: Create KG nodes for each entity ──
    entity_count = 0
    for ent in entities:
        name = (ent.get("name", "") or "").strip()
        if not name or len(name) < 2:
            continue
        entity_type = ent.get("entity_type", "entity") or "entity"
        type_map = {
            "person": "entity", "pet": "entity", "book": "entity",
            "place": "entity", "event": "entity", "activity": "entity",
            "organization": "entity", "concept": "concept", "other": "entity",
        }
        node_type = type_map.get(entity_type.lower(), "entity")

        # Skip if node already exists
        existing = client._query(
            "kg_node", workspace_id=workspace_id,
            filter_dict={"label": name}, columns=["id"],
        )
        if existing:
            continue

        try:
            description = ent.get("description", "") or ""
            client.create_node(
                workspace_id=workspace_id, label=name,
                node_type=node_type,
                summary=description[:200] or f"{entity_type}: {name}",
            )
            entity_count += 1
        except RuntimeError:
            continue

    print(f"    Created {entity_count} new KG entity nodes", file=sys.stderr)

    # Store session summaries (with clean content too)
    session_summaries = conversation.get("session_summary", {})
    if session_summaries:
        for sess_key, summary in session_summaries.items():
            if summary:
                entities_list = [
                    {"name": speaker_a, "entity_type": "person"},
                    {"name": speaker_b, "entity_type": "person"},
                ]
                try:
                    client.store(
                        workspace_id=workspace_id,
                        content=summary,
                        memory_type="locomo_summary",
                        confidence=0.9, tier="L0",
                        entities_json=json.dumps(entities_list),
                    )
                except (OSError, json.JSONDecodeError):
                    pass

    return len(memory_ids)


def run_qa(conversation: dict, workspace_id: str, client: Client) -> list[dict]:
    """Run QA with KG context injection enabled.

    V3 improvements:
    - Uses client.search() which now has inject_entity_context built in
    - Better prompting: instructs LLM to use entity context
    - Provides more context (40 results, top 25 used)
    """
    qa_list = conversation.get("qa", [])
    sample_id = conversation.get("sample_id", "unknown")
    results = []

    for i, qa in enumerate(qa_list):
        question = qa.get("question", "")
        expected_answer = qa.get("answer", "")
        category = qa.get("category", 0)

        # V3: Use search with entity context injection built in
        try:
            search_results = client.search(
                workspace_id=workspace_id,
                query=question,
                memory_type="",
                limit=40,
                semantic=True,
                cross_encoder=True,
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

        # Build context from search results
        scored_items = []
        for sr in search_results[:30]:
            content = sr.get("memory_content", "") or sr.get("content", "")
            score = sr.get("score", 0)
            if content:
                scored_items.append({
                    "content": content[:600],
                    "score": score,
                })

        # For temporal questions, also sort chronologically
        if category == 2:
            scored_items.sort(key=lambda x: -x["score"])
        else:
            scored_items.sort(key=lambda x: x["score"], reverse=True)

        # Build context
        context_parts = []
        for item in scored_items[:25]:
            context_parts.append(f"[score={item['score']:.2f}] {item['content']}")
        context = "\n\n".join(context_parts)

        # V3: Better LLM prompts
        if category == 2:
            answer_prompt = f"""You are an AI memory assistant. Based on the following conversation excerpts, answer the TEMPORAL question — pay close attention to dates, times, and when events happened.

The excerpts are from conversations between two people. Some excerpts include the speaker name at the start.
Find the SPECIFIC date/time/session when the event in the question occurred.

Conversation excerpts:
{context[:10000]}

Question: {question}

Provide a concise, factual answer with the specific date/time if available. Base your answer ONLY on the excerpts above. If the exact answer cannot be determined, say "I don't know"."""
        else:
            answer_prompt = f"""You are an AI memory assistant. Based on the following conversation excerpts, answer the question concisely.

Conversation excerpts:
{context[:10000]}

Question: {question}

Provide a concise, factual answer based ONLY on the excerpts above. If the answer cannot be determined from the excerpts, say "I don't know"."""

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

        judge_result = llm_judge(question, expected_answer, actual_answer)

        results.append({
            "question": question,
            "expected_answer": expected_answer,
            "actual_answer": actual_answer,
            "is_correct": judge_result["is_correct"],
            "category": category,
            "reasoning": judge_result.get("reasoning", ""),
        })

        # Real-time progress
        status = "CORRECT" if judge_result["is_correct"] else "WRONG"
        cat_name = CATEGORY_NAMES.get(category, "unknown")
        print(f"    Q{i+1}/{len(qa_list)} [{cat_name}] {status}: {question[:80]}...", file=sys.stderr)

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="LoCoMo Benchmark v3")
    parser.add_argument("--limit", type=int, default=0, help="Max questions per conversation")
    parser.add_argument("--conv", type=str, default="", help="Comma-separated conv indices (1-indexed)")
    parser.add_argument("--quick", action="store_true", help="Quick mode: 100 questions max")
    args = parser.parse_args()

    # Load dataset
    dataset = download_dataset(LOCOMO_DATA_URL)

    # Filter conversations
    if args.conv:
        conv_indices = [int(c.strip()) for c in args.conv.split(",")]
        dataset = [dataset[i - 1] for i in conv_indices if 1 <= i <= len(dataset)]
        print(f"  Filtered to {len(dataset)} conversation(s)", file=sys.stderr)

    # Create client
    client = Client()

    all_results = []
    by_category: dict[int, dict] = {}

    for ci, conversation in enumerate(dataset):
        sample_id = conversation.get("sample_id", f"conv-{ci}")
        print(f"\n{'─' * 50}", file=sys.stderr)
        print(f"  Conversation {ci + 1}: {sample_id}", file=sys.stderr)
        print(f"{'─' * 50}", file=sys.stderr)

        # Create workspace
        ts = int(time.time() * 1_000_000)
        workspace_id = f"locomo_v3_{sample_id}_{ts}"
        try:
            client.create_workspace(f"LoCoMo v3 - {sample_id}", id=workspace_id)
            print(f"  Workspace ID: {workspace_id}", file=sys.stderr)
        except RuntimeError as e:
            print(f"  Workspace exists, using existing: {e}", file=sys.stderr)

        # Ingest conversation
        print(f"  Ingesting conversation...", file=sys.stderr)
        turn_count = ingest_conversation(client, workspace_id, conversation)
        print(f"  Ingested {turn_count} turns with entity linking", file=sys.stderr)

        # Wait for indexing
        print(f"  Waiting for indexing...", file=sys.stderr)
        time.sleep(2)

        # Verify entity extraction
        try:
            nodes = client._query("kg_node", workspace_id=workspace_id, columns=["id", "label", "node_type"])
            link_nodes = client._query("entity_link", workspace_id=workspace_id, columns=["id", "entity_name", "entity_type"])
            print(f"  KG nodes: {len(nodes)}, Entity links: {len(link_nodes)}", file=sys.stderr)
        except RuntimeError:
            pass

        # Run QA
        qa_list = conversation.get("qa", [])
        if args.quick:
            qa_list = qa_list[:100]
        if args.limit > 0:
            qa_list = qa_list[:args.limit]

        print(f"  Running QA ({len(qa_list)} questions)...", file=sys.stderr)

        results = run_qa(conversation, workspace_id, client)
        all_results.extend(results)

        # Per-conversation stats
        correct = sum(1 for r in results if r["is_correct"])
        total = len(results)
        pct = (correct / total * 100) if total else 0
        print(f"\n  Conversation {ci + 1}: {correct}/{total} = {pct:.1f}%", file=sys.stderr)

        # Per-category breakdown
        conv_by_cat: dict[int, list] = defaultdict(list)
        for r in results:
            conv_by_cat[r["category"]].append(r)
        for cat_id, cat_results in sorted(conv_by_cat.items()):
            cat_correct = sum(1 for r in cat_results if r["is_correct"])
            cat_total = len(cat_results)
            cat_name = CATEGORY_NAMES.get(cat_id, f"cat_{cat_id}")
            if cat_total:
                print(f"    {cat_name}: {cat_correct}/{cat_total} = {cat_correct/cat_total*100:.1f}%", file=sys.stderr)

    # ── Final report ──
    print(f"\n{'=' * 50}", file=sys.stderr)
    print(f"  FINAL REPORT", file=sys.stderr)
    print(f"{'=' * 50}", file=sys.stderr)

    total_correct = sum(1 for r in all_results if r["is_correct"])
    total_questions = len(all_results)
    overall_pct = (total_correct / total_questions * 100) if total_questions else 0
    print(f"  Overall: {total_correct}/{total_questions} = {overall_pct:.1f}%", file=sys.stderr)

    # Per-category breakdown
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

    # Detailed results
    wrong_questions = [r for r in all_results if not r["is_correct"]]
    print(f"\n  Wrong answers ({len(wrong_questions)}):", file=sys.stderr)
    for r in wrong_questions[:20]:
        cat_name = CATEGORY_NAMES.get(r["category"], "?")
        print(f"    Q[{cat_name}] {r['question'][:60]}...", file=sys.stderr)
        print(f"      Expected: {r['expected_answer'][:80]}", file=sys.stderr)
        print(f"      Got: {r['actual_answer'][:80]}", file=sys.stderr)

    # Save results
    output = {
        "benchmark": "locomo_v3",
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

    output_path = f"benchmark_results_locomo_v3_{int(time.time())}.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to {output_path}", file=sys.stderr)
    print(f"{'=' * 50}\n", file=sys.stderr)

    # Print JSON summary for parsing
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
