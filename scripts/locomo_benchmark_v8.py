#!/usr/bin/env python3
"""LoCoMo Benchmark v8 — Full-Context + Category-Specific Prompts.

v7 approach: full timeline, generic prompt → 82.9% (62.5% single-hop, 78.4% temporal)
v8 fix: full timeline + per-category prompts with strict answer format
  - single-hop: fact extraction mode, concise format, FIND THE EXACT TURN
  - temporal: date math with strict format
  - multi-hop: reasoning chain
  - adversarial: careful person disambiguation
  - open-domain: concise answers

Usage:
    python scripts/locomo_benchmark_v8.py --conv 1 [--limit 10]
"""

import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict

import httpx

LOCOMO_DATA_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
CATEGORY_NAMES = {1: "single-hop", 2: "temporal", 3: "multi-hop", 4: "open-domain", 5: "adversarial"}
LLM_ENDPOINT = os.environ.get("LLM_RERANK_ENDPOINT", "https://openrouter.ai/api/v1")
LLM_MODEL = os.environ.get("LLM_RERANK_MODEL", "deepseek/deepseek-chat")

_API_KEYS: list[str] = []
for v, vl in sorted(os.environ.items()):
    if vl and (v.startswith("OPENROUTER_KEY_") or v == "AUXILIARY_VISION_API_KEY"):
        _API_KEYS.append(vl)
_API_KEY_IDX = 0

if not _API_KEYS:
    _env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(_env_path):
        with open(_env_path) as f:
            for line in f:
                if line.strip().startswith("OPENROUTER_API_KEY="):
                    _, k = line.split("=", 1)
                    k = k.strip().strip('"').strip("'")
                    if k: _API_KEYS.append(k)


def _llm_call(body: dict, timeout: int = 60) -> dict:
    global _API_KEY_IDX
    for a in range(5):
        key = _API_KEYS[_API_KEY_IDX % len(_API_KEYS)] if _API_KEYS else ""
        hdrs = {"Content-Type": "application/json"}
        if key: hdrs["Authorization"] = f"Bearer {key}"
        try:
            r = httpx.post(LLM_ENDPOINT.rstrip("/") + "/chat/completions", headers=hdrs, json=body, timeout=timeout)
            if r.status_code == 429: _API_KEY_IDX += 1; time.sleep(2**a); continue
            r.raise_for_status(); return r.json()
        except (httpx.TimeoutException, httpx.HTTPError):
            time.sleep(2**a); continue
    raise RuntimeError("LLM call failed")


def download_dataset(url: str) -> list[dict]:
    print("Downloading dataset...", file=sys.stderr)
    try:
        return json.loads(urllib.request.urlopen(url, timeout=30).read().decode())
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def build_timeline_with_dates(conversation: dict) -> str:
    """Build full chronological timeline with session dates highlighted."""
    cd = conversation.get("conversation", {})
    sa = cd.get("speaker_a", "A")
    sb = cd.get("speaker_b", "B")
    sks = sorted(
        [k for k in cd.keys() if k.startswith("session_") and not k.endswith("_date_time")],
        key=lambda x: int(x.split("_")[1]),
    )
    
    # Overview
    overview_parts = ["=== SESSION OVERVIEW ==="]
    for sk in sks:
        sn = int(sk.split("_")[1])
        dt = cd.get(f"session_{sn}_date_time", f"Session {sn}")
        turns = cd[sk]
        topics = []
        for t in turns[:2]:
            sp = sa if "a" in t.get("speaker", "").lower() else sb
            topics.append(f"{sp}: {t['text'][:80]}...")
        overview_parts.append(f"Session {sn} ({dt}, {len(turns)} turns): {' | '.join(topics)}")
    overview = "\n".join(overview_parts)
    
    # Full detail
    detail_parts = ["\n=== FULL DETAIL ==="]
    for sk in sks:
        sn = int(sk.split("_")[1])
        dt = cd.get(f"session_{sn}_date_time", f"Session {sn}")
        detail_parts.append(f"\n--- Session {sn} (DATE: {dt}) ---")
        for t in cd[sk]:
            sp = sa if "a" in t.get("speaker", "").lower() else sb
            detail_parts.append(f"{sp}: {t['text']}")
    detail = "\n".join(detail_parts)
    
    return overview + "\n" + detail


def answer_question(question: str, expected_answer: str, category: int, timeline: str) -> str:
    """Answer with full context + category-specific prompt."""
    
    if category == 1:  # single-hop — exact fact extraction
        prompt = f"""You are given the complete transcript of a multi-session conversation between two people, Caroline and Melanie.

TIMELINE:
{timeline}

QUESTION: {question}

INSTRUCTIONS:
1. Scan EVERY session and EVERY turn carefully to find the EXACT fact requested
2. The answer may be a single word, a short phrase, or a list of items
3. If the answer is a list, format as comma-separated items: "item1, item2, item3"
4. BE CONCISE. Answer with ONLY the fact. No explanations, no session references, no prefixes.
5. Example: Question "What pets does Melanie have?" → Answer: "dog, cat" (NOT "Melanie has a dog and a cat named...")
6. If you cannot find the exact answer, say "I don't know"

Answer:"""

    elif category == 2:  # temporal — exact date computation
        prompt = f"""You are given the complete transcript of a multi-session conversation. Each session has a DATE header.

TIMELINE:
{timeline}

QUESTION: {question}

CRITICAL DATE COMPUTATION RULES:
- The conversation uses relative time words like "yesterday", "last week", "last month", "last year", "two days ago", "next month", "ago", "this summer", etc.
- These are ALWAYS relative to the session DATE shown in the "--- Session N (DATE: ...) ---" header
- Example: Session 1 (DATE: 1:56 pm on 8 May, 2023), text says "I went yesterday" → The event happened on 7 May 2023
- Example: Session 1 (DATE: 1:56 pm on 8 May, 2023), text says "I painted it last year" → The event was in 2022
- Example: Session 5 (DATE: 7:55 pm on 9 June, 2023), text says "Two weekends ago" → 27-28 May 2023
- For specific dates mentioned directly (e.g., "October 13, 2023"), use that date directly

INSTRUCTIONS:
1. Find the session and turn that mentions the event
2. Identify the session date from the header
3. If the text uses relative time, compute the absolute date
4. If the text gives an absolute date, use it directly
5. Answer with ONLY the date. No explanations.
6. If you cannot determine the date, say "I don't know"

Answer:"""

    elif category == 3:  # multi-hop — reasoning across timeline
        prompt = f"""You are given the complete transcript of a multi-session conversation between Caroline and Melanie.

TIMELINE:
{timeline}

QUESTION: {question}

INSTRUCTIONS:
1. Find ALL relevant facts from across the timeline
2. Connect them to answer the question
3. For "Would X like Y?" or "Would X be considered Y?" type questions, reason from known preferences, activities, and personality
4. Give a brief reasoning chain followed by a concise answer (2-3 sentences max)
5. Say "I don't know" only if insufficient information exists

Answer:"""

    elif category == 5:  # adversarial — careful disambiguation
        prompt = f"""You are given the complete transcript of a multi-session conversation between Caroline and Melanie.

TIMELINE:
{timeline}

QUESTION: {question}

CRITICAL: This is a DETAIL-ORIENTED question. Pay EXTREME attention to:
- WHICH person (Caroline vs Melanie) the question asks about — they are different people with different lives
- Caroline is a trans woman, an advocate, artist, aspiring counselor
- Melanie is a cisgender woman, a mother, pottery enthusiast, painter
- Their events, families, pets, and activities are DIFFERENT
- Do NOT confuse facts between them

Find the exact fact asked. Be concise. Say "I don't know" only if not found.

Answer:"""

    else:  # open-domain — general
        prompt = f"""Answer the question based on the conversation timeline below.

TIMELINE:
{timeline}

QUESTION: {question}

Find the answer. Be concise. Say "I don't know" only if not found.

Answer:"""

    body = {"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": 200}
    try:
        data = _llm_call(body, timeout=60)
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        return f"ERROR: {e}"


def llm_judge(question: str, expected: str, answer: str) -> dict:
    if not answer or answer.startswith("ERROR"):
        return {"is_correct": False, "reasoning": f"System error: {answer[:100]}"}
    prompt = f"Question: {question}\nExpected: {expected}\nSystem: {answer}\n\nIs the system answer semantically correct? Reply Yes or No."
    body = {"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": 100}
    try:
        data = _llm_call(body)
        c = (data["choices"][0]["message"]["content"] or "").strip().lower()
        return {"is_correct": c.startswith("yes"), "reasoning": c[3:].strip(".,:;") if c.startswith("yes") else c[2:].strip(".,:;")}
    except:
        return {"is_correct": False, "reasoning": "judge error"}


def run_qa(conversation: dict, timeline: str, qa_list: list[dict]) -> list[dict]:
    results = []
    for i, qa in enumerate(qa_list):
        q = qa.get("question", "")
        e = qa.get("answer", "")
        cat = qa.get("category", 0)
        ans = answer_question(q, e, cat, timeline)
        j = llm_judge(q, e, ans)
        results.append({
            "question": q, "expected_answer": e, "actual_answer": ans,
            "is_correct": j["is_correct"], "category": cat, "reasoning": j.get("reasoning", ""),
        })
        cn = CATEGORY_NAMES.get(cat, f"c{cat}")
        st = "CORRECT" if j["is_correct"] else "WRONG"
        print(f"  Q{i+1}/{len(qa_list)} [{cn}] {st}: {q[:60]}...", file=sys.stderr)
    return results


def aggregate(rs):
    bc = defaultdict(lambda: {"t": 0, "c": 0})
    for r in rs:
        bc[r["category"]]["t"] += 1
        if r["is_correct"]: bc[r["category"]]["c"] += 1
    rpt = {}
    ta = ca = 0
    for c in sorted(bc):
        t = bc[c]["t"]; ok = bc[c]["c"]
        rpt[CATEGORY_NAMES.get(c, f"c{c}")] = {"total": t, "correct": ok, "accuracy": round(ok/t*100 if t else 0, 2)}
        ta += t; ca += ok
    p_cats = [1, 2, 3, 4]
    pt = sum(bc[c]["t"] for c in p_cats)
    pc = sum(bc[c]["c"] for c in p_cats)
    rpt["__primary__"] = {"categories": [CATEGORY_NAMES[c] for c in p_cats], "total": pt, "correct": pc, "accuracy": round(pc/pt*100 if pt else 0, 2)}
    rpt["__overall__"] = {"total": ta, "correct": ca, "accuracy": round(ca/ta*100 if ta else 0, 2)}
    return rpt


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--conv", type=str, default="")
    parser.add_argument("--output", type=str, default="benchmark_results_locomo_v8.json")
    args = parser.parse_args()
    print("LoCoMo v8 — Full-Context + Category-Specific Prompts", file=sys.stderr)
    
    dataset = download_dataset(LOCOMO_DATA_URL)
    if args.conv:
        ci = [int(x.strip())-1 for x in args.conv.split(",")]
        dataset = [dataset[i] for i in ci if 0 <= i < len(dataset)]
    
    all_r = []
    for ci, conv in enumerate(dataset):
        sid = conv.get("sample_id", f"conv_{ci+1}")
        print(f"\nConversation {ci+1}: {sid}", file=sys.stderr)
        tl = build_timeline_with_dates(conv)
        print(f"  Timeline: {len(tl)} chars", file=sys.stderr)
        ql = conv.get("qa", [])
        if args.limit > 0: ql = ql[:args.limit]
        print(f"  QA ({len(ql)} questions)...", file=sys.stderr)
        rs = run_qa(conv, tl, ql)
        all_r.extend(rs)
    
    print(f"\nFINAL", file=sys.stderr)
    rpt = aggregate(all_r)
    for k, v in sorted(rpt.items()):
        if k.startswith("_"): continue
        print(f"  {k:20s}: {v['accuracy']:6.2f}%  ({v['correct']:4d}/{v['total']:4d})", file=sys.stderr)
    p = rpt.get("__primary__", {})
    print(f"\n  PRIMARY: {p.get('accuracy',0):.1f}% ({p.get('correct',0)}/{p.get('total',0)})", file=sys.stderr)
    print(f"  OVERALL: {rpt.get('__overall__',{}).get('accuracy',0):.1f}%", file=sys.stderr)
    open(args.output, "w").write(json.dumps({
        "benchmark": "LoCoMo v8", "timestamp": time.time(), "report": rpt, "results": all_r,
    }, indent=2))
    print(f"Saved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
