#!/usr/bin/env python3
"""Optimized LongMemEval benchmark — uses store_batch, skips Tantivy indexing."""

import json, time, uuid, os, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))
import httpx
from spacetime_memory import Client

SPLIT = os.environ.get("LMEVAL_SPLIT", "s")
MAX_Q = int(os.environ.get("LMEVAL_MAX_Q", "50"))
DB = os.environ.get("SPACETIMEDB_DB", "")
HOST = os.environ.get("SPACETIMEDB_HOST", "127.0.0.1")
PORT = int(os.environ.get("SPACETIMEDB_PORT", "3001"))
EMB = os.environ.get("EMBEDDER_URL", "http://127.0.0.1:9090")

DATASET_URLS = {
    "s": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json?download=true",
    "m": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_m_cleaned.json?download=true",
    "oracle": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json?download=true",
}


LOG = open("/tmp/lmeval_progress.log", "w", buffering=1)

def log(msg):
    LOG.write(msg + "\n")
    LOG.flush()


def main():
    cache = Path(f"data/longmemeval_{SPLIT}.json")
    if cache.exists():
        log(f"Loading cached dataset from {cache}")
        with open(cache) as f:
            dataset = json.load(f)
    else:
        url = DATASET_URLS.get(SPLIT)
        log(f"Downloading LongMemEval '{SPLIT}' split...")
        r = httpx.get(url, timeout=300, follow_redirects=True)
        r.raise_for_status()
        dataset = r.json()
        with open(cache, "w") as f:
            json.dump(dataset, f)
        log(f"  Saved {len(dataset)} questions")

    dataset = dataset[:MAX_Q]
    log(f"Dataset: {len(dataset)} questions, split={SPLIT}")

    # Connect
    tr = httpx.get(f"http://{HOST}:{PORT}/v1/database/{DB}", timeout=10)
    token = tr.headers.get("spacetime-identity-token", "")
    c = Client(database=DB, embedder_url=EMB, token=token, host=HOST, port=PORT)
    try:
        c._call("register", ["lmeval-" + uuid.uuid4().hex[:8], "lmeval2026", "benchpass"])
    except Exception:
        pass

    ws = c.create_workspace("lmeval-" + uuid.uuid4().hex[:8])
    WS = ws["id"]
    log(f"Workspace: {WS}")

    def flatten(s):
        if isinstance(s, list):
            return s
        if isinstance(s, dict) and "messages" in s:
            return s["messages"]
        return [{"role": "system", "content": str(s)}]

    def to_text(s):
        parts = [f'[{m.get("role","?")}]: {m.get("content","")}' for m in flatten(s)]
        return "\n".join(parts)

    results = {}
    t0 = time.time()

    for qi, q in enumerate(dataset):
        qid = q.get("question_id", qi)
        qtype = q.get("question_type", "?")
        qtext = q.get("question", "")
        haystack_ids = q.get("haystack_session_ids", [])
        haystack = q.get("haystack_sessions", [])
        answer_ids = set(q.get("answer_session_ids", []))

        # Seed sessions (batch of 5 for speed)
        batch = []
        for sid, session in zip(haystack_ids, haystack):
            text = to_text(session)
            batch.append({"content": text, "summary": f"Session {sid}", "memory_type": "session"})
        for i in range(0, len(batch), 5):
            c.store_batch(WS, batch[i:i + 5])

        # Search
        try:
            sr = c.search(WS, qtext, limit=5, semantic=True, cross_encoder=False)
        except Exception:
            sr = []

        # Check answer sessions
        found = set()
        for r in sr[:5]:
            rid = r.get("source_session_id", "") or r.get("id", "")
            if rid in answer_ids:
                found.add(rid)
            rc = (r.get("content") or "").lower()
            for ans_id in answer_ids:
                for hs_id, hs in zip(haystack_ids, haystack):
                    if hs_id == ans_id:
                        at = to_text(hs).lower()
                        if len(at) > 30 and (at[:30] in rc or rc[:30] in at):
                            found.add(ans_id)

        results[qid] = {
            "question_type": qtype,
            "n_answer_sessions": len(answer_ids),
            "found_in_top5": len(found),
            "all_found": len(found) >= len(answer_ids),
        }

        hits = sum(1 for r in results.values() if r["all_found"])
        pct = hits / len(results) * 100
        elapsed = time.time() - t0
        log(f"  [{qi+1}/{len(dataset)}] Recall@All@5={pct:.1f}%  this_q={elapsed:.1f}s")

    # Aggregate
    qtypes = defaultdict(lambda: {"hits": 0, "total": 0})
    for r in results.values():
        qtypes[r["question_type"]]["total"] += 1
        if r["all_found"]:
            qtypes[r["question_type"]]["hits"] += 1

    total_hits = sum(qt["hits"] for qt in qtypes.values())
    total_q = sum(qt["total"] for qt in qtypes.values())
    overall = total_hits / total_q * 100 if total_q else 0

    log(f"\n=== RESULTS ===")
    log(f"Overall Recall@All@5: {overall:.1f}% ({total_hits}/{total_q})")
    for qt, st in sorted(qtypes.items()):
        log(f"  {qt:<35}: {st['hits']}/{st['total']} = {st['hits']/st['total']*100:.1f}%")

    out = {
        "benchmark": "LongMemEval", "split": SPLIT, "questions": len(dataset),
        "overall": {"hits": total_hits, "total": total_q, "recall_at_all_5": round(overall / 100, 4) if overall else 0},
        "per_type": {qt: {"hits": st["hits"], "total": st["total"], "recall": round(st["hits"] / st["total"] * 100, 1) if st["total"] else 0} for qt, st in qtypes.items()},
    }
    path = f"/tmp/longmemeval_{SPLIT}_{MAX_Q}_results.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    log(f"Saved to {path}")
    log(f"Reference: Mnemosyne 98.9%, Mempalace 96.6%")


if __name__ == "__main__":
    main()
