#!/usr/bin/env python3
"""LoCoMo Benchmark v5 — Hybrid Timeline Retrieval.

Key insight: semantic search finds relevant turns but loses temporal signal.
Structured timeline is too broad. Hybrid approach:

  1. Semantic search for the question → top 40 results
  2. Parse session/datetime from each result's entities_json
  3. Sort chronologically (by session_num, then turn_id)
  4. Format as structured timeline with clear temporal anchors
  5. LLM reasons over the chronologically-sorted relevant context

Usage:
    python scripts/locomo_benchmark_v5.py --conv 1 [--limit 10]
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

LOCOMO_DATA_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
CATEGORY_NAMES = {1: "single-hop", 2: "temporal", 3: "multi-hop", 4: "open-domain", 5: "adversarial"}

STDB_URL = os.environ.get("SPACETIMEDB_URL", "http://localhost:3001")
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

_env_path = os.path.expanduser("~/.hermes/.env")
if not LLM_API_KEY and os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            if line.strip().startswith("OPENROUTER_API_KEY="):
                _, k = line.split("=", 1)
                LLM_API_KEY = k.strip().strip('"').strip("'")

_STDB_IDENTITY_CACHE: str | None = None


def _llm_call(body: dict, timeout: int = 30) -> dict:
    global _API_KEY_IDX
    for a in range(5):
        key = _API_KEYS[_API_KEY_IDX % len(_API_KEYS)] if _API_KEYS else ""
        hdrs = {"Content-Type": "application/json"}
        if key:
            hdrs["Authorization"] = f"Bearer {key}"
        try:
            r = httpx.post(LLM_ENDPOINT.rstrip("/") + "/chat/completions", headers=hdrs, json=body, timeout=timeout)
            if r.status_code == 429:
                _API_KEY_IDX = (_API_KEY_IDX + 1) % max(1, len(_API_KEYS))
                time.sleep(min(2 ** a, 30))
                continue
            r.raise_for_status()
            return r.json()
        except (httpx.TimeoutException, httpx.HTTPError, httpx.ConnectError) as e:
            import sys as _sys
            print(f"  [_LLM ERROR] {type(e).__name__}: {str(e)[:100]}", file=_sys.stderr)
            time.sleep(min(2 ** a, 10))
            continue
    raise RuntimeError(f"LLM call failed after 5 retries")
    raise RuntimeError("LLM call failed")


def download_dataset(url: str) -> list[dict]:
    print("Downloading dataset...", file=sys.stderr)
    try:
        return json.loads(urllib.request.urlopen(url, timeout=30).read().decode())
    except (OSError, json.JSONDecodeError) as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def _extract_judge_json(content: str) -> dict | None:
    """Extract is_correct from LLM judge response. Expects Yes/No format."""
    if not content:
        return None
    lower = content.lower().strip()
    # Check for Yes/No at start
    if lower.startswith("yes"):
        # Extract reasoning after "Yes"
        reasoning = content[3:].strip().strip(".,:;")
        return {"is_correct": True, "reasoning": reasoning[:200]}
    if lower.startswith("no"):
        reasoning = content[2:].strip().strip(".,:;")
        return {"is_correct": False, "reasoning": reasoning[:200]}
    # Fallback: check for true/false
    if "true" in lower.split()[:3]:
        return {"is_correct": True, "reasoning": content[:200]}
    if "false" in lower.split()[:3]:
        return {"is_correct": False, "reasoning": content[:200]}
    return None


def llm_judge(question: str, expected: str, answer: str) -> dict:
    if not answer or answer.startswith("ANSWER ERROR") or answer.startswith("SEARCH ERROR"):
        return {"is_correct": False, "reasoning": f"System error: {answer[:100]}"}
    prompt = f"You are a strict judge. Determine if the System Answer matches the Expected Answer.\nQuestion: {question}\nExpected: {expected}\nSystem: {answer}\n\nReply with a single word: Yes or No. Then a brief explanation."

    body = {"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": 100}
    for _ in range(3):
        try:
            d = _llm_call(body)
            content = (d["choices"][0]["message"]["content"] or "").strip()
            import sys as _sys
            print("  [JUDGE RAW] {}".format(content[:200]), file=_sys.stderr)
            r = _extract_judge_json(content)
            if r: return {"is_correct": bool(r["is_correct"]), "reasoning": r.get("reasoning", "")}
        except (OSError, TypeError, KeyError, RuntimeError):
            continue
    ow = set(expected.lower().split())
    aw = set(answer.lower().split())
    return {"is_correct": len(ow & aw) / max(len(ow), 1) > 0.4, "reasoning": "heuristic"}


def batch_ingest(client: Client, workspace_id: str, conversation: dict) -> int:
    conv_data = conversation.get("conversation", {})
    speaker_a = conv_data.get("speaker_a", "A")
    speaker_b = conv_data.get("speaker_b", "B")
    session_keys = sorted(
        [k for k in conv_data.keys() if k.startswith("session_") and not k.endswith("_date_time")],
        key=lambda x: int(x.split("_")[1]),
    )
    batch_items = []
    turn_id = 0
    for sk in session_keys:
        snum = int(sk.split("_")[1])
        dt_key = f"session_{snum}_date_time"
        session_dt = conv_data.get(dt_key, f"Session {snum}")
        for t in conv_data[sk]:
            turn_id += 1
            speaker_raw = t.get("speaker", "")
            speaker_name = speaker_a if "a" in speaker_raw.lower() else speaker_b
            content = t.get("text", "") + f" [Session {snum}]"
            batch_items.append({
                "content": content,
                "summary": content[:200],
                "memory_type": "locomo_turn",
                "confidence": 1.0,
                "entities_json": json.dumps([
                    {"name": speaker_a, "entity_type": "person"},
                    {"name": speaker_b, "entity_type": "person"},
                    {"name": f"session_{snum}", "entity_type": "session"},
                    {"name": session_dt, "entity_type": "datetime"},
                    {"name": f"turn_{turn_id}", "entity_type": "turn_id"},
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

    if not batch_items: return 0
    t0 = time.time()
    r = client.store_batch(workspace_id=workspace_id, items=batch_items)
    elapsed = time.time() - t0
    print(f"  Ingested {len(r)} items in {elapsed:.1f}s ({len(r)/elapsed:.0f} items/s)", file=sys.stderr)
    return len(r)


def _parse_session_info(sr: dict) -> dict:
    """Extract session metadata from search result entities_json or content."""
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
    if "session_num" not in meta:
        content = sr.get("content", sr.get("memory_content", ""))
        m = re.search(r"\[Session (\d+)\]", content)
        if m:
            meta["session_num"] = int(m.group(1))
    return meta


def retrieve_and_timeline(
    client: Client,
    workspace_id: str,
    question: str,
    category: int,
    session_map: dict[str, dict],  # content_prefix -> {session_num, session_dt}
) -> str:
    """Retrieve relevant turns and format as structured timeline.

    1. Semantic search → top 40 results
    2. Map each result to its session date via session_map
    3. Deduplicate by content, sort chronologically
    4. Format as timeline: [Session N - Date] Speaker: text
    """
    results = client.search(
        workspace_id=workspace_id,
        query=question,
        memory_type="",
        limit=40,
        semantic=False,  # keyword-only for speed; set True when vector embeddings available
        cross_encoder=False,
    )

    # Parse and collect entries
    entries = []
    seen_turns: set[str] = set()
    for sr in results:
        content = sr.get("content", sr.get("memory_content", ""))
        if not content:
            continue
        # Dedup by content[:80]
        dedup_key = content[:80]
        if dedup_key in seen_turns:
            continue
        seen_turns.add(dedup_key)

        # Look up session info from session_map
        prefix = content[:100]
        session_info = session_map.get(prefix, {})
        session_num = session_info.get("session_num", -1)
        session_dt = session_info.get("session_dt", "")
        score = sr.get("score", 0.0) or sr.get("similarity", 0.0)

        entries.append({
            "session_num": session_num,
            "session_dt": session_dt,
            "turn_id": session_info.get("turn_id", -1),
            "content": content,
            "score": score,
        })

    if not entries:
        return "(no relevant context found)"

    # Debug: show what entries and session dates were found
    import sys as _sys
    print(f"  [TIMELINE for Q] {len(entries)} entries, {len([e for e in entries if e['session_dt']])} with dates", file=_sys.stderr)
    for e in entries[:3]:
        print(f"  [ENTRY] S{e['session_num']} dt={e['session_dt']!r}: {e['content'][:80]}", file=_sys.stderr)

    # For temporal questions, add a few more context turns from same sessions
    if category == 2:
        # Collect session numbers we have
        session_nums = set(e["session_num"] for e in entries if e["session_num"] >= 0)
        if session_nums:
            # Search again with a broader query to get more context from those sessions
            broader_q = " ".join([question, " ".join([f"Session {s}" for s in sorted(session_nums)[:5]])])
            try:
                more = client.search(workspace_id=workspace_id, query=broader_q, memory_type="", limit=20, semantic=True, cross_encoder=True)
                for sr in more:
                    content = sr.get("content", sr.get("memory_content", ""))
                    if not content: continue
                    dedup_key = content[:80]
                    if dedup_key in seen_turns: continue
                    seen_turns.add(dedup_key)
                    meta = _parse_session_info(sr)
                    entries.append({
                        "session_num": meta.get("session_num", -1),
                        "session_dt": meta.get("session_dt", ""),
                        "turn_id": meta.get("turn_id", -1),
                        "content": content,
                        "score": sr.get("score", 0.0) * 0.8,  # lower weight for broader search
                    })
            except Exception:
                pass

    # Sort chronologically: session_num, then turn_id, then score
    entries.sort(key=lambda e: (
        e["session_num"] if e["session_num"] >= 0 else 9999,
        e["turn_id"] if e["turn_id"] >= 0 else 9999,
        -e["score"],
    ))

    # Format as structured timeline (limit to ~20 entries)
    timeline_parts = []
    current_session = -1
    for e in entries[:20]:
        if e["session_num"] != current_session and e["session_num"] >= 0:
            current_session = e["session_num"]
            dt_str = e["session_dt"] if e["session_dt"] else f"Session {current_session}"
            timeline_parts.append(f"\n=== {dt_str} ===\n")
        # Clean content: remove [Session N] suffix
        clean_content = re.sub(r" *\[Session \d+\]", "", e["content"])
        turn_tag = f"[T{e['turn_id']}] " if e["turn_id"] >= 0 else ""
        timeline_parts.append(f"{turn_tag}{clean_content}")

    return "\n".join(timeline_parts).strip()


def answer_with_timeline(question: str, timeline: str, category: int) -> str:
    """Generate answer using structured timeline context."""

    if category == 2:  # temporal
        prompt = f"""You are a precise temporal reasoning system. You have a conversation timeline below.

TIMELINE:
{timeline}

QUESTION: {question}

IMPORTANT: The conversation may use relative time words like "yesterday", "last week",
"last month", "last year", "two days ago", etc. These are RELATIVE to the session date.
You MUST compute the absolute date from the relative reference + session date.

Examples:
- Session date: "1:56 pm on 8 May, 2023", text: "I went yesterday" -> Answer: 7 May 2023
- Session date: "1:56 pm on 8 May, 2023", text: "I painted it last year" -> Answer: 2022
- Session date: "7:55 pm on 9 June, 2023", text: "Two weekends ago" -> Answer: 27-28 May 2023

First, find which session entry contains the answer. Identify the relative time word.
Compute the absolute date. Then answer concisely with just the date.

Say "I don't know" only if the timeline does not contain the answer."""

    elif category == 3:  # multi-hop
        prompt = f"""You have a MEMORY of a conversation shown below as a chronological timeline.

TIMELINE:
{timeline}

QUESTION: {question}

Connect facts from different parts of the timeline to answer. Reason step by step, citing which entries support your conclusion. Answer concisely. Say "I don't know" if the timeline doesn't contain enough information."""

    else:
        prompt = f"""You have a MEMORY of a conversation shown below as a chronological timeline.

TIMELINE:
{timeline}

QUESTION: {question}

Find the answer in the timeline above. Answer concisely with just the fact. Say "I don't know" if the timeline doesn't contain the answer."""

    try:
        body = {"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": 250}
        data = _llm_call(body, timeout=45)
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (OSError, json.JSONDecodeError) as e:
        return f"ANSWER ERROR: {e}"


def run_qa(conversation: dict, workspace_id: str, client: Client, all_turns: list[dict], all_entities: set[str], qa_list: list[dict] | None = None) -> list[dict]:
    if qa_list is None:
        qa_list = conversation.get("qa", [])

    # Build session_map: content_prefix -> {session_num, session_dt, turn_id}
    session_map: dict[str, dict] = {}
    for t in all_turns:
        text = t["text"] + " [Session {}]".format(t["session_num"])
        prefix = text[:100]
        if prefix not in session_map:
            session_map[prefix] = {
                "session_num": t["session_num"],
                "session_dt": t["session_dt"],
                "turn_id": t["turn_id"],
            }

    results = []
    for i, qa in enumerate(qa_list):
        question = qa.get("question", "")
        expected_answer = qa.get("answer", "")
        category = qa.get("category", 0)

        # Retrieve and timeline (with session_map for dates)
        timeline = retrieve_and_timeline(client, workspace_id, question, category, session_map)

        # Answer
        actual_answer = answer_with_timeline(question, timeline, category)

        # Judge
        jr = llm_judge(question, expected_answer, actual_answer)

        results.append({
            "question": question, "expected_answer": expected_answer,
            "actual_answer": actual_answer, "is_correct": jr["is_correct"],
            "category": category, "reasoning": jr.get("reasoning", ""),
            "evidence": qa.get("evidence", []),
        })

        cat_name = CATEGORY_NAMES.get(category, f"cat-{category}")
        status = "CORRECT" if jr["is_correct"] else "WRONG"
        print(f"  Q{i+1}/{len(qa_list)} [{cat_name}] {status}: {question[:60]}...", file=sys.stderr)

    return results


def aggregate_results(all_results: list[dict]) -> dict:
    by_cat = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in all_results:
        cat = r.get("category", 0)
        by_cat[cat]["total"] += 1
        if r.get("is_correct", False):
            by_cat[cat]["correct"] += 1
    report = {}
    t_all = c_all = 0
    for cat in sorted(by_cat.keys()):
        t = by_cat[cat]["total"]
        c = by_cat[cat]["correct"]
        report[CATEGORY_NAMES.get(cat, f"cat-{cat}")] = {"total": t, "correct": c, "accuracy": round((c/t*100) if t else 0, 2)}
        t_all += t; c_all += c
    p = [1, 2, 3, 4]
    pt = sum(by_cat[c]["total"] for c in p)
    pc = sum(by_cat[c]["correct"] for c in p)
    report["__primary__"] = {"categories": [CATEGORY_NAMES[c] for c in p], "total": pt, "correct": pc, "accuracy": round((pc/pt*100) if pt else 0, 2)}
    report["__overall__"] = {"total": t_all, "correct": c_all, "accuracy": round((c_all/t_all*100) if t_all else 0, 2)}
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description="LoCoMo Benchmark v5")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--conv", type=str, default="")
    parser.add_argument("--no-ingest", action="store_true")
    parser.add_argument("--output", type=str, default="benchmark_results_locomo_v5.json")
    parser.add_argument("--workspace", type=str, default="")
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    print("=" * 60, file=sys.stderr)
    print("  LoCoMo Benchmark v5 — Hybrid Timeline Retrieval", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    db_id = os.environ.get("SPACETIMEDB_DB", "")
    if not db_id: print("ERROR: SPACETIMEDB_DB required", file=sys.stderr); sys.exit(1)
    token = os.environ.get("SPACETIMEDB_TOKEN", "")
    if not token:
        tr = httpx.get(f"{STDB_URL}/v1/database/{db_id}", timeout=10)
        token = tr.headers.get("spacetime-identity-token", "") or ""
    client = Client(database=db_id, token=token)
    try:
        client._call("register", ["v5-" + secrets.token_hex(8), "lmeval2026", "benchpass"])
    except Exception:
        pass
    print("  Connected", file=sys.stderr)

    dataset = download_dataset(LOCOMO_DATA_URL)
    if args.conv:
        ci = [int(x.strip()) - 1 for x in args.conv.split(",")]
        dataset = [dataset[i] for i in ci if 0 <= i < len(dataset)]

    all_results = []
    for ci, conversation in enumerate(dataset):
        sid = conversation.get("sample_id", f"conv_{ci+1}")
        print(f"\n{'─' * 50}", file=sys.stderr)
        print(f"  Conversation {ci+1}: {sid}", file=sys.stderr)
        print(f"{'─' * 50}", file=sys.stderr)

        # Extract all turns for session_map and entity tracking
        cd = conversation.get("conversation", {})
        speaker_a = cd.get("speaker_a", "Speaker A")
        speaker_b = cd.get("speaker_b", "Speaker B")
        all_entities = {speaker_a, speaker_b}
        all_turns = []
        session_keys = sorted(
            [k for k in cd.keys() if k.startswith("session_") and not k.endswith("_date_time")],
            key=lambda x: int(x.split("_")[1]),
        )
        for sk in session_keys:
            snum = int(sk.split("_")[1])
            dt_key = f"session_{snum}_date_time"
            session_dt = cd.get(dt_key, f"Session {snum}")
            for t in cd.get(sk, []):
                speaker_raw = t.get("speaker", "")
                speaker_name = speaker_a if "a" in speaker_raw.lower() else speaker_b
                all_turns.append({
                    "turn_id": len(all_turns) + 1,
                    "session_num": snum,
                    "session_dt": session_dt,
                    "speaker": speaker_name,
                    "text": t.get("text", ""),
                })

        ws_name = f"locomo_v5_{sid}"
        ws_id = args.workspace
        if not ws_id:
            try:
                ws = client.create_workspace(name=ws_name, description=f"LoCoMo v5: {sid}")
                ws_id = ws.get("id", ws.get("workspace_id", ""))
                if not ws_id:
                    for w in client.list_workspaces():
                        if w.get("name") == ws_name:
                            ws_id = w.get("id", w.get("workspace_id", "")); break
                if not ws_id: print("  ERROR: no workspace", file=sys.stderr); continue
                print(f"  Workspace: {ws_id}", file=sys.stderr)
            except Exception as e:
                print(f"  ERROR: {e}", file=sys.stderr); continue

        if not args.no_ingest:
            print("  Ingesting...", file=sys.stderr)
            batch_ingest(client, ws_id, conversation)
            print("  Waiting for index...", file=sys.stderr)
            time.sleep(3)

        qa_list = conversation.get("qa", [])
        if args.limit > 0:
            qa_list = qa_list[:args.limit]

        print(f"  QA ({len(qa_list)} questions)...", file=sys.stderr)
        results = run_qa(conversation, ws_id, client, all_turns, all_entities, qa_list)
        all_results.extend(results)
        report = aggregate_results(all_results)
        prim = report.get("__primary__", {})
        print(f"\n  Interim: {prim.get('accuracy', 0):.1f}% ({prim.get('correct',0)}/{prim.get('total',0)})", file=sys.stderr)

    print(f"\n{'=' * 60}", file=sys.stderr)
    print("  FINAL RESULTS", file=sys.stderr)
    print(f"{'=' * 60}", file=sys.stderr)
    report = aggregate_results(all_results)
    for k, v in sorted(report.items()):
        if k.startswith("_"): continue
        print(f"  {k:20s}: {v['accuracy']:6.2f}%  ({v['correct']:4d}/{v['total']:4d})", file=sys.stderr)
    prim = report.get("__primary__", {})
    ovr = report.get("__overall__", {})
    print(f"\n  {'PRIMARY':20s}: {prim.get('accuracy',0):6.2f}%  ({prim.get('correct',0):4d}/{prim.get('total',0):4d})", file=sys.stderr)
    print(f"  {'OVERALL':20s}: {ovr.get('accuracy',0):6.2f}%  ({ovr.get('correct',0):4d}/{ovr.get('total',0):4d})", file=sys.stderr)
    output = {"benchmark": "LoCoMo v5", "timestamp": time.time(), "model": LLM_MODEL, "report": report, "results": all_results}
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to {args.output}", file=sys.stderr)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
