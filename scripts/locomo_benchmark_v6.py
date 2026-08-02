#!/usr/bin/env python3
"""LoCoMo Benchmark v6 — Full-Context Timeline.

Gives the LLM the ENTIRE conversation timeline as context (fits in 32K window).
No search needed. No embeddings needed. Just pure LLM reasoning.

Approach:
  1. Load conversation, build complete chronological timeline
  2. For each question, present full timeline + question
  3. LLM finds answer directly from the complete context
  4. Judge validates correctness

Usage:
    python scripts/locomo_benchmark_v6.py --conv 1 [--limit 10]
"""

import json
import os
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

_env_path = os.path.expanduser("~/.hermes/.env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            if line.strip().startswith("OPENROUTER_API_KEY="):
                _, k = line.split("=", 1)
                k = k.strip().strip('"').strip("'")
                if k and k not in _API_KEYS:
                    _API_KEYS.append(k)


def _llm_call(body: dict, timeout: int = 30) -> dict:
    global _API_KEY_IDX
    for a in range(5):
        key = _API_KEYS[_API_KEY_IDX % len(_API_KEYS)] if _API_KEYS else ""
        hdrs = {"Content-Type": "application/json"}
        if key: hdrs["Authorization"] = f"Bearer {key}"
        try:
            r = httpx.post(LLM_ENDPOINT.rstrip("/") + "/chat/completions", headers=hdrs, json=body, timeout=timeout)
            if r.status_code == 429: _API_KEY_IDX = (_API_KEY_IDX + 1) % max(1, len(_API_KEYS)); time.sleep(2**a); continue
            r.raise_for_status(); return r.json()
        except (httpx.TimeoutException, httpx.HTTPError, httpx.ConnectError):
            time.sleep(2**a); continue
    raise RuntimeError("LLM call failed")


def download_dataset(url: str) -> list[dict]:
    print("Downloading dataset...", file=sys.stderr)
    try:
        return json.loads(urllib.request.urlopen(url, timeout=30).read().decode())
    except (OSError, json.JSONDecodeError) as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def build_timeline(conversation: dict) -> str:
    """Build FULL chronological timeline string from conversation data."""
    cd = conversation.get("conversation", {})
    speaker_a = cd.get("speaker_a", "Speaker A")
    speaker_b = cd.get("speaker_b", "Speaker B")
    session_keys = sorted(
        [k for k in cd.keys() if k.startswith("session_") and not k.endswith("_date_time")],
        key=lambda x: int(x.split("_")[1]),
    )
    parts = []
    for sk in session_keys:
        snum = int(sk.split("_")[1])
        dt_key = f"session_{snum}_date_time"
        dt = cd.get(dt_key, f"Session {snum}")
        parts.append(f"\n=== Session {snum} ({dt}) ===\n")
        for t in cd.get(sk, []):
            speaker_raw = t.get("speaker", "")
            speaker = speaker_a if "a" in speaker_raw.lower() else speaker_b
            parts.append(f"{speaker}: {t.get('text', '')}")
    return "\n".join(parts).strip()


def answer_question(question: str, timeline: str, category: int) -> str:
    """Answer a question from the full timeline context."""
    prompt = f"""You have the COMPLETE conversation timeline below. Answer based ONLY on this timeline.

TIMELINE:
{timeline}

QUESTION: {question}

IMPORTANT: Relative time words like "yesterday", "last week", "last month", "last year", "two days ago" are relative to the session date shown in === Session N (DATE) ===. Compute absolute dates from these relative references.

First find the relevant session/entry, then answer concisely. Say "I don't know" only if the timeline does not contain the answer.

Answer:"""
    try:
        body = {"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": 300}
        data = _llm_call(body, timeout=60)
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        return f"ERROR: {e}"


def llm_judge(question: str, expected: str, answer: str) -> dict:
    if not answer or answer.startswith("ERROR"):
        return {"is_correct": False, "reasoning": f"System error: {answer[:100]}"}
    prompt = f"""You are a strict judge. Determine if the System Answer matches the Expected Answer.

Question: {question}
Expected answer: {expected}
System answer: {answer}

Is the system answer semantically correct? Accept paraphrases and partial matches.
Reply with a single word: Yes or No. Then briefly explain."""

    body = {"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": 100}
    try:
        data = _llm_call(body)
        content = (data["choices"][0]["message"]["content"] or "").strip()
        lower = content.lower()
        is_correct = lower.startswith("yes")
        reasoning = content[3:].strip().strip(".,:;") if is_correct else content[2:].strip().strip(".,:;")
        return {"is_correct": is_correct, "reasoning": reasoning[:200]}
    except Exception:
        return {"is_correct": False, "reasoning": "judge error"}


def run_qa(conversation: dict, timeline: str, qa_list: list[dict]) -> list[dict]:
    results = []
    for i, qa in enumerate(qa_list):
        question = qa.get("question", "")
        expected = qa.get("answer", "")
        category = qa.get("category", 0)
        answer = answer_question(question, timeline, category)
        judge = llm_judge(question, expected, answer)
        results.append({
            "question": question, "expected_answer": expected,
            "actual_answer": answer, "is_correct": judge["is_correct"],
            "category": category, "reasoning": judge.get("reasoning", ""),
        })
        cat_name = CATEGORY_NAMES.get(category, f"cat-{category}")
        status = "CORRECT" if judge["is_correct"] else "WRONG"
        print(f"  Q{i+1}/{len(qa_list)} [{cat_name}] {status}: {question[:60]}...", file=sys.stderr)
    return results


def aggregate_results(all_results: list[dict]) -> dict:
    by_cat = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in all_results:
        c = r.get("category", 0)
        by_cat[c]["total"] += 1
        if r.get("is_correct"): by_cat[c]["correct"] += 1
    report = {}
    t_all = c_all = 0
    for c in sorted(by_cat):
        t, ok = by_cat[c]["total"], by_cat[c]["correct"]
        report[CATEGORY_NAMES.get(c, f"cat-{c}")] = {"total": t, "correct": ok, "accuracy": round(ok/t*100 if t else 0, 2)}
        t_all += t; c_all += ok
    p = [1,2,3,4]
    pt = sum(by_cat[c]["total"] for c in p)
    pc = sum(by_cat[c]["correct"] for c in p)
    report["__primary__"] = {"total": pt, "correct": pc, "accuracy": round(pc/pt*100 if pt else 0, 2)}
    report["__overall__"] = {"total": t_all, "correct": c_all, "accuracy": round(c_all/t_all*100 if t_all else 0, 2)}
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description="LoCoMo Benchmark v6 — Full-Context Timeline")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--conv", type=str, default="")
    parser.add_argument("--output", type=str, default="benchmark_results_locomo_v6.json")
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    print("=" * 60, file=sys.stderr)
    print("  LoCoMo Benchmark v6 — Full-Context Timeline", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    dataset = download_dataset(LOCOMO_DATA_URL)
    if args.conv:
        ci = [int(x.strip()) - 1 for x in args.conv.split(",")]
        dataset = [dataset[i] for i in ci if 0 <= i < len(dataset)]

    all_results = []
    for ci, conversation in enumerate(dataset):
        sid = conversation.get("sample_id", f"conv_{ci+1}")
        print(f"\n{'─'*50}", file=sys.stderr)
        print(f"  Conversation {ci+1}: {sid}", file=sys.stderr)
        print(f"{'─'*50}", file=sys.stderr)

        timeline = build_timeline(conversation)
        print(f"  Timeline: {len(timeline)} chars, ~{len(timeline)//4} tokens", file=sys.stderr)

        qa_list = conversation.get("qa", [])
        if args.limit > 0:
            qa_list = qa_list[:args.limit]

        print(f"  QA ({len(qa_list)} questions)...", file=sys.stderr)
        results = run_qa(conversation, timeline, qa_list)
        all_results.extend(results)

        report = aggregate_results(all_results)
        prim = report.get("__primary__", {})
        print(f"\n  Interim: {prim.get('accuracy', 0):.1f}% ({prim.get('correct',0)}/{prim.get('total',0)})", file=sys.stderr)

    print(f"\n{'='*60}", file=sys.stderr)
    print("  FINAL RESULTS", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    report = aggregate_results(all_results)
    for k, v in sorted(report.items()):
        if k.startswith("_"): continue
        print(f"  {k:20s}: {v['accuracy']:6.2f}%  ({v['correct']:4d}/{v['total']:4d})", file=sys.stderr)
    prim = report.get("__primary__", {})
    ovr = report.get("__overall__", {})
    print(f"\n  {'PRIMARY':20s}: {prim.get('accuracy',0):6.2f}%  ({prim.get('correct',0):4d}/{prim.get('total',0):4d})", file=sys.stderr)
    print(f"  {'OVERALL':20s}: {ovr.get('accuracy',0):6.2f}%  ({ovr.get('correct',0):4d}/{ovr.get('total',0):4d})", file=sys.stderr)

    output = {"benchmark": "LoCoMo v6", "timestamp": time.time(), "model": LLM_MODEL, "report": report, "results": all_results}
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to {args.output}", file=sys.stderr)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
