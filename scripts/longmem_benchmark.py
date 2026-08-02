#!/usr/bin/env python3
"""LongMemEval Benchmark — spacetime-memory evaluation.

LongMemEval (https://github.com/mem0ai/longmemeval) evaluates long-term
memory retrieval by testing recall of facts distributed across many
conversation turns (up to 500+ turns, ~50k tokens per session).

This script runs the STDB-based memory pipeline on the LongMemEval dataset.

Usage:
    # Download dataset and run
    python scripts/longmem_benchmark.py --limit 50

    # Full run (all 500 questions)
    python scripts/longmem_benchmark.py --output results_longmem.json
"""

import json
import os
import secrets
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))

import httpx
from spacetime_memory import Client

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LONGMEM_DATA_URL = (
    "https://raw.githubusercontent.com/mem0ai/longmemeval/main/data/longmem_eval.json"
)
STDB_URL = os.environ.get("SPACETIMEDB_URL", "http://localhost:3001")
LLM_ENDPOINT = os.environ.get("LLM_RERANK_ENDPOINT", "https://openrouter.ai/api/v1")
LLM_MODEL = os.environ.get("LLM_RERANK_MODEL", "deepseek/deepseek-chat")

_API_KEYS: list[str] = []
for var, val in sorted(os.environ.items()):
    if val and (var.startswith("OPENROUTER_KEY_") or var == "AUXILIARY_VISION_API_KEY"):
        _API_KEYS.append(val)
_API_KEY_IDX = 0

if not _API_KEYS:
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.strip().startswith("OPENROUTER_API_KEY="):
                    _, k = line.split("=", 1)
                    k = k.strip().strip('"').strip("'")
                    if k:
                        _API_KEYS.append(k)

# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


def download_dataset(url: str = LONGMEM_DATA_URL) -> list[dict]:
    """Download LongMemEval dataset from GitHub."""
    print("Downloading LongMemEval dataset...", file=sys.stderr)
    resp = urllib.request.urlopen(url)
    data = json.loads(resp.read())
    print(f"  Loaded {len(data)} conversations", file=sys.stderr)
    return data


def build_sessions(conv: dict) -> list[dict]:
    """Build session dicts from a LongMemEval conversation entry."""
    messages = conv.get("messages", conv.get("conversation", []))
    session_size = 10  # messages per session
    sessions = []
    for i in range(0, len(messages), session_size):
        chunk = messages[i : i + session_size]
        texts = []
        for msg in chunk:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if content:
                texts.append(f"[{role}]: {content}")
        if texts:
            sessions.append({
                "num": len(sessions) + 1,
                "text": "\n".join(texts),
                "n_turns": len(chunk),
                "datetime": f"Session {len(sessions) + 1}",
            })
    return sessions


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------


def _llm_call(body: dict, timeout: int = 60) -> dict:
    global _API_KEY_IDX
    for a in range(5):
        key = _API_KEYS[_API_KEY_IDX % len(_API_KEYS)] if _API_KEYS else ""
        hdrs = {"Content-Type": "application/json"}
        if key:
            hdrs["Authorization"] = f"Bearer {key}"
        try:
            r = httpx.post(
                LLM_ENDPOINT.rstrip("/") + "/chat/completions",
                headers=hdrs,
                json=body,
                timeout=timeout,
            )
            if r.status_code == 429:
                _API_KEY_IDX += 1
                time.sleep(min(2**a, 30))
                continue
            r.raise_for_status()
            return r.json()
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            if a == 4:
                raise
            time.sleep(min(2**a * 2, 30))
            continue
    raise RuntimeError("LLM call failed after 5 retries")


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------

DONT_KNOW_PHRASES = [
    "i don't know",
    "i don't have",
    "no information",
    "does not mention",
    "does not provide",
    "not mentioned",
    "not discussed",
    "impossible",
    "cannot determine",
    "none",
    "i do not know",
    "i'm not sure",
    "the context does not",
    "no answer",
    "no details",
]


def llm_judge(question: str, expected: str, answer: str) -> dict:
    """Judge with substring + keyword matching."""
    if not answer or str(answer).startswith("ERROR"):
        return {"is_correct": False, "reasoning": "system error"}

    e = str(expected or "").strip()
    a = str(answer or "").strip()

    if not e:
        a_lower = a.lower()
        dont_know = any(p in a_lower for p in DONT_KNOW_PHRASES)
        return {"is_correct": dont_know, "reasoning": f"adversarial ({dont_know})"}

    e_lower = e.lower().rstrip(".")
    a_lower = a.lower()

    # Exact substring
    if e_lower in a_lower:
        return {"is_correct": True, "reasoning": "substring match"}

    # Date pattern
    import re

    date_m = re.search(r"(\d{1,2}\s+\w+\s+\d{4})", e)
    if date_m and date_m.group(1).lower() in a_lower:
        return {"is_correct": True, "reasoning": "date match"}

    # Word overlap
    e_words = [w.lower().rstrip(".,;:!?") for w in e.split() if len(w) > 3]
    a_words = set(w.lower().rstrip(".,;:!?") for w in a.split())
    if e_words and sum(1 for w in e_words if w in a_words) / len(e_words) >= 0.4:
        return {"is_correct": True, "reasoning": "keyword overlap match"}

    # LLM judge fallback
    prompt = (
        f"Question: {question}\nExpected: {e}\nSystem: {a}\n\n"
        f"Is the system answer semantically correct? Be generous with extra text.\n"
        f"Reply Yes or No."
    )
    body = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 10,
    }
    try:
        data = _llm_call(body)
        c = (data["choices"][0]["message"]["content"] or "").strip().lower()
        return {"is_correct": c.startswith("yes"), "reasoning": c[:20]}
    except Exception:
        return {"is_correct": False, "reasoning": "judge fallback"}


# ---------------------------------------------------------------------------
# Storage + Retrieval
# ---------------------------------------------------------------------------


def store_conversation(client: Client, workspace_id: str, sessions: list[dict]):
    """Store conversation sessions into STDB."""
    batch = []
    for s in sessions:
        batch.append({
            "content": s["text"],
            "summary": f"Session {s['num']} ({s['n_turns']} messages)",
            "memory_type": "conversation",
            "entities_json": json.dumps([
                {"session_num": s["num"]},
            ]),
        })
    if batch:
        client.store_batch(workspace_id, batch)
        print(f"  Stored {len(batch)} sessions", file=sys.stderr)


def retrieve_answer(
    client: Client, workspace_id: str, sessions: list[dict], question: str
) -> tuple[str, list[int]]:
    """Retrieve relevant sessions and answer the question."""
    search_results = client.search(
        workspace_id, query=question, limit=10, semantic=True,
        cross_encoder=False,
    )

    if not search_results:
        search_results = client.search(
            workspace_id, query=question, limit=10, semantic=False,
            cross_encoder=False,
        )

    if not search_results:
        return "I don't know", []

    # Extract session numbers from entities_json
    matched = []
    seen = set()
    for sr in search_results:
        ej = sr.get("entities_json", "")
        try:
            ents = json.loads(ej) if isinstance(ej, str) else (ej or [])
        except json.JSONDecodeError:
            ents = []
        for ent in ents if isinstance(ents, list) else []:
            sn = ent.get("session_num") if isinstance(ent, dict) else None
            if sn is not None and sn not in seen:
                for s in sessions:
                    if s["num"] == sn:
                        matched.append(s)
                        seen.add(sn)
                        break
        if len(matched) >= 3:
            break

    if not matched:
        sr_content = search_results[0].get("content", "")
        for s in sessions:
            if s["text"][:100] in sr_content or sr_content[:100] in s["text"]:
                matched.append(s)
                if len(matched) >= 3:
                    break

    if not matched:
        return "I don't know", []

    # Build context
    context_parts = []
    for s in matched:
        context_parts.append(
            f"--- Session {s['num']} ---\n{s['text']}"
        )
    context = "\n\n".join(context_parts)

    prompt = (
        f"Answer the question based on the conversation context below.\n"
        f"If the information is not in the context, say 'I don't know'.\n\n"
        f"CONTEXT:\n{context}\n\n"
        f"QUESTION: {question}\n\n"
        f"Answer concisely:"
    )

    body = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 200,
    }
    try:
        data = _llm_call(body, timeout=60)
        ans = (data["choices"][0]["message"]["content"] or "").strip()
        return ans, [s["num"] for s in matched]
    except Exception as e:
        return f"ERROR: {e}", []


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate(results: list[dict]) -> dict:
    """Aggregate results by category."""
    cats = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in results:
        cat = r.get("category", "unknown")
        cats[cat]["total"] += 1
        if r.get("is_correct"):
            cats[cat]["correct"] += 1

    rpt = {}
    ta = ca = 0
    for cat in sorted(cats):
        c = cats[cat]
        acc = round(c["correct"] / c["total"] * 100, 2) if c["total"] else 0
        rpt[cat] = {"total": c["total"], "correct": c["correct"], "accuracy": acc}
        ta += c["total"]
        ca += c["correct"]

    rpt["__overall__"] = {"total": ta, "correct": ca, "accuracy": round(ca / ta * 100, 2) if ta else 0}
    return rpt


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(description="LongMemEval Benchmark")
    parser.add_argument("--limit", type=int, default=0, help="Questions per conversation (0=all)")
    parser.add_argument("--conv", type=str, default="", help="Comma-separated conversations to run")
    parser.add_argument("--output", type=str, default="benchmark_results_longmem.json")
    parser.add_argument("--no-store", action="store_true", help="Skip storage (use existing data)")
    parser.add_argument("--workspace", type=str, default="", help="Existing workspace ID")
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
    print("LongMemEval Benchmark — spacetime-memory", file=sys.stderr)

    # Connect
    db_id = os.environ.get("SPACETIMEDB_DB", "")
    client = Client(database=db_id, verbose=False)
    try:
        client._call("register", ["longmem-" + secrets.token_hex(8), "lmeval2026", "benchpass"])
    except Exception:
        pass
    print("  Connected to STDB", file=sys.stderr)

    dataset = download_dataset()
    if args.conv:
        ci = [int(x.strip()) - 1 for x in args.conv.split(",")]
        dataset = [dataset[i] for i in ci if 0 <= i < len(dataset)]

    all_results = []
    for ci, conv in enumerate(dataset):
        sid = conv.get("conv_id", conv.get("id", f"conv_{ci + 1}"))
        print(f"\n{'─' * 50}", file=sys.stderr)
        print(f"  Conversation {ci + 1}: {sid}", file=sys.stderr)

        sessions = build_sessions(conv)
        print(f"  Sessions: {len(sessions)}", file=sys.stderr)

        if args.workspace:
            ws_id = args.workspace
        else:
            resp = client.create_workspace(f"longmem_{sid}")
            ws_id = resp if isinstance(resp, str) else resp.get("id", "")
        print(f"  Workspace: {ws_id}", file=sys.stderr)

        if not args.no_store:
            store_conversation(client, ws_id, sessions)
            time.sleep(0.5)  # Let indexing settle

        qa_list = conv.get("qa", conv.get("questions", []))
        if args.limit > 0:
            qa_list = qa_list[:args.limit]
        print(f"  QA ({len(qa_list)} questions)...", file=sys.stderr)

        for qi, qa in enumerate(qa_list):
            q = qa.get("question", "")
            e = qa.get("expected_answer", qa.get("answer", ""))
            cat = qa.get("category", qa.get("type", "general"))

            ans, matched = retrieve_answer(client, ws_id, sessions, q)
            j = llm_judge(q, e, ans)

            marker = "✓" if j["is_correct"] else "✗"
            print(f"  Q{qi + 1}/{len(qa_list)} [{cat}] {marker}: {q[:70]}...", file=sys.stderr)

            all_results.append({
                "question": q,
                "expected_answer": e,
                "actual_answer": ans,
                "matched_sessions": matched,
                "is_correct": j["is_correct"],
                "category": cat,
                "reasoning": j["reasoning"],
            })

            # Rotate API keys and rate-limit
            time.sleep(0.3)

        # Cleanup workspace if we created it
        if not args.workspace and not args.no_store:
            try:
                client.delete_workspace(ws_id)
            except Exception:
                pass

    # Report
    print(f"\n{'=' * 50}", file=sys.stderr)
    print(f"  FINAL", file=sys.stderr)
    rpt = aggregate(all_results)
    for k, v in sorted(rpt.items()):
        if k.startswith("_"):
            continue
        print(f"  {k:20s}: {v['accuracy']:6.2f}%  ({v['correct']:4d}/{v['total']:4d})", file=sys.stderr)
    o = rpt.get("__overall__", {})
    print(f"  {'---':20s}", file=sys.stderr)
    print(f"  {'OVERALL':20s}: {o.get('accuracy', 0):6.2f}%  ({o.get('correct', 0):4d}/{o.get('total', 0):4d})", file=sys.stderr)

    open(args.output, "w").write(
        json.dumps({"benchmark": "LongMemEval", "timestamp": time.time(), "report": rpt, "results": all_results}, indent=2)
    )
    print(f"Saved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
