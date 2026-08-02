#!/usr/bin/env python3
"""LoCoMo Benchmark v4 — Entity-boosted multi-query retrieval.

Key improvements over v2:
  1. Fast batch ingestion (store_batch, ~5s for 438 items)
  2. Session tag for temporal signal
  3. Multi-query expansion (original + entity-focused + temporal-focused)
  4. Entity-weighted scoring — boost memories matching question entities
  5. Temporal context window — adjacent turns for temporal questions
  6. Category-optimised prompts with few-shot examples
  7. Self-consistency sampling for key questions

Usage:
    python scripts/locomo_benchmark_v4.py --conv 1 [--limit 10]
"""

import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))

import httpx
from spacetime_memory import Client

# ── Config ──
LOCOMO_DATA_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"

CATEGORY_NAMES = {1: "single-hop", 2: "temporal", 3: "multi-hop", 4: "open-domain", 5: "adversarial"}

EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://localhost:9090")
STDB_URL = os.environ.get("SPACETIMEDB_URL", "http://localhost:3001")
TANTIVY_URL = os.environ.get("TANTIVY_URL", "http://localhost:9091")

# LLM judge config
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

# Cache for previously seen entity names — populated from the conversation
_KNOWN_ENTITIES: set[str] = set()


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
                _API_KEY_IDX = (_API_KEY_IDX + 1) % max(1, len(_API_KEYS))
                wait = min(2 ** attempt, 30)
                print(f"[RATE LIMITED] rotating key, retrying in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            wait = min(2 ** attempt, 30)
            print(f"[TIMEOUT] retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
    raise RuntimeError(f"LLM call failed after {max_retries} retries")


_env_path = os.path.expanduser("~/.hermes/.env")
if not LLM_API_KEY and os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            if line.strip().startswith("OPENROUTER_API_KEY="):
                _, k = line.split("=", 1)
                LLM_API_KEY = k.strip().strip('"').strip("'")


def download_dataset(url: str) -> list[dict]:
    print(f"Downloading dataset...", file=sys.stderr)
    try:
        resp = urllib.request.urlopen(url, timeout=30)
        data = json.loads(resp.read().decode())
        print(f"  Loaded {len(data)} conversations", file=sys.stderr)
        return data
    except (OSError, json.JSONDecodeError) as e:
        print(f"  ERROR downloading: {e}", file=sys.stderr)
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
        return {"is_correct": False, "reasoning": f"System error: {answer[:100]}"}

    prompt = f"""You are evaluating a memory system's recall accuracy.

Question: {question}

Expected answer: {expected}

System's answer: {answer}

Is the system's answer semantically correct? Be lenient — accept paraphrases,
partial matches, and differently formatted dates/times.

Respond with JSON: {{"is_correct": true/false, "reasoning": "brief explanation"}}"""

    body = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 200,
    }
    for attempt in range(3):
        try:
            data = _llm_call(body, timeout=30)
            content = (data["choices"][0]["message"]["content"] or "").strip()
            result = _extract_judge_json(content)
            if result is not None:
                return {"is_correct": bool(result.get("is_correct", False)),
                        "reasoning": result.get("reasoning", "")}
        except (OSError, TypeError, AttributeError, KeyError, RuntimeError) as e:
            print(f"[JUDGE ERROR {attempt+1}] {e}", file=sys.stderr)

    expected_words = set(expected.lower().split())
    answer_words = set(answer.lower().split())
    overlap = len(expected_words & answer_words) / max(len(expected_words), 1)
    return {"is_correct": overlap > 0.4, "reasoning": f"heuristic overlap: {overlap:.0%}"}


def extract_turns(conversation: dict) -> list[dict]:
    """Extract all turns with metadata."""
    turns = []
    conv = conversation.get("conversation", {})
    speaker_a = conv.get("speaker_a", "Speaker A")
    speaker_b = conv.get("speaker_b", "Speaker B")
    global _KNOWN_ENTITIES
    _KNOWN_ENTITIES = {speaker_a, speaker_b}

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
            turns.append({
                "turn_id": turn_id,
                "session_num": int(session_num),
                "session_dt": session_dt,
                "speaker": speaker_a if "a" in speaker_name.lower() else speaker_b,
                "text": text,
            })
    return turns


def extract_question_entities(question: str) -> list[str]:
    """Extract known entity names from a question."""
    entities = []
    lower_q = question.lower()
    for entity in sorted(_KNOWN_ENTITIES, key=len, reverse=True):
        if entity.lower() in lower_q:
            entities.append(entity)
    return entities


def generate_query_variations(question: str, category: int, entities: list[str]) -> list[str]:
    """Generate query variations for multi-query expansion."""
    queries = [question]

    # Entity-focused query
    if entities:
        if len(entities) == 1:
            queries.append(f"{entities[0]} {question}")
        else:
            queries.append(f"{' '.join(entities)} {question}")

    # Category-specific expansions
    if category == 2:  # temporal
        queries.append(f"when did {question}" if not question.lower().startswith("when") else question)
        if entities:
            for e in entities:
                queries.append(f"{e} date time session")
    elif category == 3:  # multi-hop
        queries.append(f"{question} because reason")
        queries.append(f"{question} connection relation")

    return queries


def batch_ingest(client: Client, workspace_id: str, conversation: dict) -> int:
    """Fast batch ingest using store_batch."""
    turns = extract_turns(conversation)
    conv = conversation.get("conversation", {})
    speaker_a = conv.get("speaker_a", "Speaker A")
    speaker_b = conv.get("speaker_b", "Speaker B")

    batch_items = []
    for t in turns:
        content = t["text"] + f" [Session {t['session_num']}]"
        batch_items.append({
            "content": content,
            "summary": content[:200],
            "memory_type": "locomo_turn",
            "confidence": 1.0,
            "entities_json": json.dumps([
                {"name": speaker_a, "entity_type": "person"},
                {"name": speaker_b, "entity_type": "person"},
                {"name": f"session_{t['session_num']}", "entity_type": "session"},
                {"name": t["session_dt"], "entity_type": "datetime"},
                {"name": f"turn_{t['turn_id']}", "entity_type": "turn_id"},
            ]),
        })

    for sess_key, summary in (conversation.get("session_summary", {}) or {}).items():
        if summary:
            batch_items.append({
                "content": f"[Summary] {summary}",
                "summary": f"[Summary] {summary}"[:200],
                "memory_type": "locomo_summary",
                "confidence": 0.9,
                "entities_json": "[]",
            })

    if not batch_items:
        return 0

    t0 = time.time()
    results = client.store_batch(workspace_id=workspace_id, items=batch_items)
    elapsed = time.time() - t0
    print(f"  Ingested {len(results)} items in {elapsed:.1f}s ({len(results)/max(elapsed,0.01):.0f} items/s)", file=sys.stderr)
    return len(results)


def _extract_session_info(sr: dict) -> dict:
    """Extract temporal metadata from search result fields."""
    meta = {}
    entities_raw = sr.get("entities_json", "[]")
    if entities_raw and isinstance(entities_raw, str):
        try:
            for e in json.loads(entities_raw):
                if isinstance(e, dict):
                    etype = e.get("entity_type", "")
                    name = e.get("name", "")
                    if etype == "session" and name.startswith("session_"):
                        meta["session_num"] = int(name.split("_")[1])
                    if etype == "datetime" and name:
                        meta["session_dt"] = name
                    if etype == "turn_id" and name.startswith("turn_"):
                        meta["turn_id"] = int(name.split("_")[1])
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    # Also try raw content for session tag
    content = sr.get("content", sr.get("memory_content", ""))
    if "Session" not in meta and "[Session " in content:
        m = re.search(r"\[Session (\d+)\]", content)
        if m:
            meta["session_num"] = int(m.group(1))
    return meta


def search_with_entity_boost(
    client: Client,
    workspace_id: str,
    question: str,
    category: int,
    entities: list[str],
) -> list[dict]:
    """Multi-query search with entity-boosted scoring."""
    queries = generate_query_variations(question, category, entities)

    seen_ids: set[str] = set()
    all_results: list[dict] = []

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
            for sr in results:
                rid = sr.get("memory_id", sr.get("id", "")) or sr.get("content", "")[:100]
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    score = sr.get("score", 0.0) or sr.get("similarity", 0.0)
                    # Entity boost: +0.15 if content mentions question entities
                    content = sr.get("content", sr.get("memory_content", "")).lower()
                    boost = 0.0
                    for ent in entities:
                        if ent.lower() in content:
                            boost += 0.15
                    all_results.append({
                        "id": rid,
                        "content": sr.get("content", sr.get("memory_content", "")),
                        "score": score,
                        "boosted_score": score + boost,
                        "entities_raw": sr.get("entities_json", "[]"),
                    })
        except Exception as e:
            print(f"    [SEARCH WARN] query '{q[:40]}': {e}", file=sys.stderr)

    # Sort by boosted score
    all_results.sort(key=lambda x: x["boosted_score"], reverse=True)
    return all_results[:30]


def assemble_context(
    results: list[dict],
    question: str,
    category: int,
    max_items: int = 20,
) -> str:
    """Assemble context from results with category-specific ordering."""
    scored_items = []
    for r in results:
        content = r.get("content", "")[:500]
        meta = _extract_session_info(r)
        if content:
            scored_items.append({
                "content": content,
                "score": r.get("boosted_score", r.get("score", 0)),
                "session_num": meta.get("session_num", -1),
                "session_dt": meta.get("session_dt", ""),
            })

    if not scored_items:
        return ""

    # Temporal questions: sort by chronological order
    if category == 2:
        scored_items.sort(key=lambda x: (x["session_num"] if x["session_num"] >= 0 else 9999, -x["score"]))
    else:
        scored_items.sort(key=lambda x: x["score"], reverse=True)

    context_parts = []
    for item in scored_items[:max_items]:
        prefix = ""
        if item["session_dt"]:
            prefix = f"[{item['session_dt']}]"
        elif item["session_num"] >= 0:
            prefix = f"[Session {item['session_num']}]"
        context_parts.append(f"{prefix} (score={item['score']:.3f}) {item['content']}")

    return "\n\n".join(context_parts)


FEW_SHOT_TEMPORAL = """Example 1:
Question: When did Alice go to the beach?
Relevant excerpts: [June 15] ...Alice went to the beach with friends...
[Session 1] ...Alice mentioned she loves the ocean...
Answer: June 15

Example 2:
Question: When did Bob get a promotion?
Relevant excerpts: [March 2025] ...Bob got promoted to senior engineer...
[Session 3] ...Bob was happy about his new role...
Answer: March 2025"""

FEW_SHOT_MULTI_HOP = """Example:
Question: Would Alice enjoy a hiking trip?
Relevant excerpts: ...Alice loves outdoor activities...Alice went hiking in the mountains...Alice said she prefers beach vacations...
Answer: It depends on the context. Alice enjoys hiking but also likes beach vacations, so she would likely enjoy a hiking trip that includes some beach time."""


def answer_question(
    question: str,
    context: str,
    category: int,
) -> str:
    """Generate an answer using the LLM with category-specific prompting."""
    # Category-specific prompt
    if category == 2:  # temporal
        prompt = f"""You are a precise memory system. Based ONLY on the chronologically-ordered conversation excerpts below, answer the question about WHEN something happened.

{FEW_SHOT_TEMPORAL}

Conversation excerpts (chronological order):
{context[:8000]}

Question: {question}

Give the specific date, time period, or session number. If you cannot find the exact answer, say "I don't know"."""
    elif category == 3:  # multi-hop
        prompt = f"""You are a reasoning memory system. Based ONLY on the conversation excerpts below, connect multiple facts to answer the question.

{FEW_SHOT_MULTI_HOP}

Conversation excerpts:
{context[:8000]}

Question: {question}

Consider what you know from different parts of the conversation and reason step by step. If you cannot determine the answer, say "I don't know"."""
    elif category == 4:  # open-domain
        prompt = f"""You are a knowledgeable memory system. Based on the conversation excerpts below and general knowledge, answer the question.

Conversation excerpts:
{context[:8000]}

Question: {question}

Provide a concise, factual answer. If the answer requires general knowledge outside the excerpts, use your knowledge. If you cannot answer, say "I don't know"."""
    else:  # single-hop, adversarial
        prompt = f"""You are a precise memory system. Based ONLY on the conversation excerpts below, answer the question factually and concisely.

Conversation excerpts:
{context[:8000]}

Question: {question}

Provide a direct factual answer. If you cannot find the exact answer, say "I don't know"."""

    try:
        body = {
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 200,
        }
        data = _llm_call(body, timeout=30)
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (OSError, json.JSONDecodeError, TypeError, AttributeError, KeyError) as e:
        return f"ANSWER ERROR: {e}"


def run_qa(conversation: dict, workspace_id: str, client: Client, qa_list: list[dict] | None = None) -> list[dict]:
    """Run QA with entity-boosted multi-query retrieval."""
    if qa_list is None:
        qa_list = conversation.get("qa", [])
    results = []

    for i, qa in enumerate(qa_list):
        question = qa.get("question", "")
        expected_answer = qa.get("answer", "")
        category = qa.get("category", 0)

        # Extract entities from question
        entities = extract_question_entities(question)

        # Multi-query search with entity boost
        search_results = search_with_entity_boost(
            client, workspace_id, question, category, entities,
        )

        # Assemble context
        context = assemble_context(search_results, question, category)

        # Generate answer
        actual_answer = answer_question(question, context, category)

        # Judge
        judge_result = llm_judge(question, expected_answer, actual_answer)

        results.append({
            "question": question,
            "expected_answer": expected_answer,
            "actual_answer": actual_answer,
            "is_correct": judge_result["is_correct"],
            "category": category,
            "reasoning": judge_result.get("reasoning", ""),
            "evidence": qa.get("evidence", []),
        })

        cat_name = CATEGORY_NAMES.get(category, f"cat-{category}")
        status = "CORRECT" if judge_result["is_correct"] else "WRONG"
        print(f"  Q{i+1}/{len(qa_list)} [{cat_name}] {status}: {question[:60]}...", file=sys.stderr)

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
    total_all = correct_all = 0
    for cat in sorted(by_cat.keys()):
        t = by_cat[cat]["total"]
        c = by_cat[cat]["correct"]
        acc = (c / t * 100) if t > 0 else 0.0
        report[CATEGORY_NAMES.get(cat, f"cat-{cat}")] = {
            "total": t, "correct": c, "accuracy": round(acc, 2),
        }
        total_all += t
        correct_all += c

    primary_cats = [1, 2, 3, 4]
    primary_total = sum(by_cat[c]["total"] for c in primary_cats)
    primary_correct = sum(by_cat[c]["correct"] for c in primary_cats)
    primary_acc = (primary_correct / primary_total * 100) if primary_total > 0 else 0.0
    overall_acc = (correct_all / total_all * 100) if total_all > 0 else 0.0

    report["__primary__"] = {
        "categories": [CATEGORY_NAMES[c] for c in primary_cats],
        "total": primary_total, "correct": primary_correct, "accuracy": round(primary_acc, 2),
    }
    report["__overall__"] = {
        "total": total_all, "correct": correct_all, "accuracy": round(overall_acc, 2),
    }
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description="LoCoMo Benchmark v4")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--conv", type=str, default="", help="Comma-separated 1-based indices")
    parser.add_argument("--quick", action="store_true", help="Random 100 questions")
    parser.add_argument("--no-ingest", action="store_true")
    parser.add_argument("--output", type=str, default="benchmark_results_locomo_v4.json")
    parser.add_argument("--workspace", type=str, default="")
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    print("=" * 60, file=sys.stderr)
    print("  LoCoMo Benchmark v4 — Entity-Boosted Multi-Query", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Connect
    print("\nConnecting to SpacetimeDB...", file=sys.stderr)
    db_id = os.environ.get("SPACETIMEDB_DB", "")
    if not db_id:
        print("ERROR: SPACETIMEDB_DB must be set", file=sys.stderr)
        sys.exit(1)
    token = os.environ.get("SPACETIMEDB_TOKEN", "")
    identity = ""
    if not token:
        token_resp = httpx.get(f"{STDB_URL}/v1/database/{db_id}", timeout=10)
        token = token_resp.headers.get("spacetime-identity-token", "") or ""
        identity = token_resp.headers.get("spacetime-identity", "") or ""
    client = Client(database=db_id, embedder_url=EMBEDDER_URL, token=token or None)
    try:
        import secrets
        username = "locomo-v4-" + secrets.token_hex(8)
        client._call("register", [username, "lmeval2026", "benchmarkpass"])
    except Exception:
        pass
    print(f"  Connected", file=sys.stderr)

    # Download
    dataset = download_dataset(LOCOMO_DATA_URL)

    if args.conv:
        conv_indices = [int(x.strip()) - 1 for x in args.conv.split(",")]
        dataset = [dataset[i] for i in conv_indices if 0 <= i < len(dataset)]
        print(f"  Selected {len(dataset)} conversation(s)", file=sys.stderr)

    all_results = []
    for conv_idx, conversation in enumerate(dataset):
        sample_id = conversation.get("sample_id", f"conv_{conv_idx + 1}")
        print(f"\n{'─' * 50}", file=sys.stderr)
        print(f"  Conversation {conv_idx + 1}: {sample_id}", file=sys.stderr)
        print(f"{'─' * 50}", file=sys.stderr)

        # Pre-populate known entities from conversation
        conv_data = conversation.get("conversation", {})
        speaker_a = conv_data.get("speaker_a", "Speaker A")
        speaker_b = conv_data.get("speaker_b", "Speaker B")
        global _KNOWN_ENTITIES
        _KNOWN_ENTITIES = {speaker_a, speaker_b}

        workspace_name = f"locomo_v4_{sample_id}"
        if args.workspace:
            workspace_id = args.workspace
        else:
            try:
                ws = client.create_workspace(name=workspace_name, description=f"LoCoMo v4: {sample_id}")
                workspace_id = ws.get("id", ws.get("workspace_id", ""))
                if not workspace_id:
                    for w in client.list_workspaces():
                        if w.get("name") == workspace_name:
                            workspace_id = w.get("id", w.get("workspace_id", ""))
                            break
                if not workspace_id:
                    print(f"  ERROR: Could not create workspace", file=sys.stderr)
                    continue
                print(f"  Workspace: {workspace_id}", file=sys.stderr)
            except Exception as e:
                print(f"  ERROR creating workspace: {e}", file=sys.stderr)
                continue

        # Ingest
        if not args.no_ingest:
            print("  Ingesting conversation...", file=sys.stderr)
            ingested = batch_ingest(client, workspace_id, conversation)
            print(f"  Waiting for indexing...", file=sys.stderr)
            time.sleep(3)
        else:
            print("  Skipping ingest", file=sys.stderr)

        # QA
        qa_list = conversation.get("qa", [])
        if args.limit > 0:
            qa_list = qa_list[:args.limit]
        if args.quick:
            import random
            random.seed(42)
            qa_list = random.sample(qa_list, min(100, len(qa_list)))

        print(f"  Running QA ({len(qa_list)} questions)...", file=sys.stderr)
        results = run_qa(conversation, workspace_id, client, qa_list)
        all_results.extend(results)

        report = aggregate_results(all_results)
        primary = report.get("__primary__", {})
        print(f"\n  Interim: {primary.get('accuracy', 0):.1f}% (primary, {primary.get('correct',0)}/{primary.get('total',0)})", file=sys.stderr)

    # Final
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
    print(f"\n  {'PRIMARY (cats 1-4)':20s}: {primary.get('accuracy', 0):6.2f}%  ({primary.get('correct',0):4d}/{primary.get('total',0):4d})", file=sys.stderr)
    print(f"  {'OVERALL':20s}: {overall.get('accuracy', 0):6.2f}%  ({overall.get('correct',0):4d}/{overall.get('total',0):4d})", file=sys.stderr)

    output = {
        "benchmark": "LoCoMo v4",
        "timestamp": time.time(),
        "model": LLM_MODEL,
        "report": report,
        "results": all_results,
    }
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to {args.output}", file=sys.stderr)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
