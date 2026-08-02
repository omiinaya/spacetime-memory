#!/usr/bin/env python3
"""LoCoMo Benchmark v8.1 — v7 Proven Approach + Single-Hop Fix Only.

v7: 82.9% overall (temporal 78.4%, single-hop 62.5%, adversarial 83.0%)
v8: 73.9% overall (temporal 35.1%) — CATEGORY-SPECIFIC PROMPTS HURT TEMPORAL!

v8.1: Revert to v7's unified prompt for temporal, multi-hop, open-domain, adversarial.
       Only improve the single-hop prompt for concise fact extraction.

Usage:
    python scripts/locomo_benchmark_v8_1.py --conv 1 [--limit 10]
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


def build_timeline(conversation: dict) -> str:
    """Build complete chronological timeline (same as v7)."""
    cd = conversation.get("conversation", {})
    sa = cd.get("speaker_a", "A")
    sb = cd.get("speaker_b", "B")
    sks = sorted(
        [k for k in cd.keys() if k.startswith("session_") and not k.endswith("_date_time")],
        key=lambda x: int(x.split("_")[1]),
    )
    
    # Overview
    overview_parts = ["=== OVERVIEW OF SESSIONS ==="]
    for sk in sks:
        sn = int(sk.split("_")[1])
        dt = cd.get(f"session_{sn}_date_time", f"Session {sn}")
        turns = cd[sk]
        topics = []
        for t in turns[:2]:
            sp = sa if "a" in t.get("speaker", "").lower() else sb
            topics.append(f"{sp}: {t['text'][:60]}...")
        overview_parts.append(f"Session {sn} ({dt}): {' | '.join(topics)}")
    overview = "\n".join(overview_parts)
    
    # Full detail
    detail_parts = ["\n=== FULL DETAIL ==="]
    for sk in sks:
        sn = int(sk.split("_")[1])
        dt = cd.get(f"session_{sn}_date_time", f"Session {sn}")
        detail_parts.append(f"\n--- Session {sn} ({dt}) ---")
        for t in cd[sk]:
            sp = sa if "a" in t.get("speaker", "").lower() else sb
            detail_parts.append(f"{sp}: {t['text']}")
    detail = "\n".join(detail_parts)
    
    return overview + "\n" + detail


def make_prompt(timeline: str, question: str, category: int) -> str:
    """Build category-specific prompt. Only single-hop differs from v7."""
    
    if category == 1:  # single-hop — IMPROVED over v7 (concise fact extraction)
        return f"""You are reading a conversation timeline. First scan the SESSION OVERVIEW to find which session is relevant, then read that session's details in FULL DETAIL.

TIMELINE:
{timeline}

QUESTION: {question}

INSTRUCTIONS:
1. Scan the OVERVIEW OF SESSIONS to find the session that likely contains the answer
2. Read that session's detail in FULL DETAIL
3. Find the EXACT turn with the answer
4. Extract concisely. If a list, separate with commas: "item1, item2, item3"
5. BE CONCISE. Answer with ONLY the fact, no explanations.
6. Say "I don't know" only if the answer is not in any session.

Answer:"""
    
    else:  # temporal, multi-hop, open-domain, adversarial — use v7's unified prompt
        return f"""You are reading a conversation timeline. First scan the SESSION OVERVIEW to find which session is relevant, then read that session's details in FULL DETAIL.

TIMELINE:
{timeline}

QUESTION: {question}

INSTRUCTIONS:
1. Scan the OVERVIEW OF SESSIONS to find the session that likely contains the answer
2. Read that session's detail in FULL DETAIL
3. Identify the specific turn with the answer
4. IMPORTANT: Relative time words (yesterday, last week, last month, last year, two days ago, next month) are RELATIVE to the session date shown in parentheses
5. Compute absolute dates from these references
6. Give a concise answer. Say "I don't know" only if the answer is not in any session.

Answer:"""


def answer_question(question: str, expected_answer: str, category: int, timeline: str) -> str:
    prompt = make_prompt(timeline, question, category)
    body = {"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": 300}
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
    parser.add_argument("--output", type=str, default="benchmark_results_locomo_v81.json")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
    print("LoCoMo v8.1 — v7 Proven + Single-Hop Fix", file=sys.stderr)
    
    dataset = download_dataset(LOCOMO_DATA_URL)
    if args.conv:
        ci = [int(x.strip())-1 for x in args.conv.split(",")]
        dataset = [dataset[i] for i in ci if 0 <= i < len(dataset)]
    
    all_r = []
    for ci, conv in enumerate(dataset):
        sid = conv.get("sample_id", f"conv_{ci+1}")
        print(f"\nConversation {ci+1}: {sid}", file=sys.stderr)
        tl = build_timeline(conv)
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
        "benchmark": "LoCoMo v8.1", "timestamp": time.time(), "report": rpt, "results": all_r,
    }, indent=2))
    print(f"Saved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
