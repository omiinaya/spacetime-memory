#!/usr/bin/env python3
"""Logseq eval — seed directly into Tantivy + embedder, bypass STDB store."""
import os, sys, time, uuid, re, json
from pathlib import Path
import httpx

EMB = "http://localhost:9092"
TANTIVY = "http://localhost:9091"
LOGSEQ_DIR = Path.home() / "logseq-graph"

QUERIES = [
    ("Chappy stealth browser backlog", ["Chappy", "backlog"]),
    ("spacetime memory roadmap", ["spacetime", "roadmap"]),
    ("authentication roadmap spacetime", ["Auth Roadmap"]),
    ("CIS benchmarks download", ["CIS", "benchmark"]),
    ("admin dashboard consolidation", ["dashboard"]),
    ("CDP bridge extension", ["CDP Bridge"]),
    ("CLI reference", ["CLI Reference"]),
    ("Auth0 configuration", ["Auth0"]),
    ("Azure self-hosted VMs", ["Azure", "VMs"]),
    ("C Sharp quickstart", ["C#", "Quickstart"]),
    ("browser quickstart guide", ["Browser Quickstart"]),
    ("SpacetimeDB column types", ["Column Types"]),
    ("automatic migrations", ["Automatic Migrations"]),
    ("cheat sheet", ["Cheat Sheet"]),
    ("Clerk authentication", ["Clerk"]),
    ("ask AI chat", ["Ask AI"]),
    ("angular quickstart", ["Angular Quickstart"]),
    ("astro quickstart", ["Astro Quickstart"]),
    ("bun quickstart", ["Bun Quickstart"]),
    ("C++ quickstart", ["C++ Quickstart"]),
]


def clean_md(text):
    lines = text.split("\n")
    result = []
    for line in lines:
        if re.match(r"^\w+::\s", line) or re.match(r"^tags::", line, re.IGNORECASE):
            continue
        line = re.sub(r"\[\[([^\]]+)\]\]", r"\1", line)
        line = re.sub(r"#(\S+)", r"\1", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        result.append(line)
    return "\n".join(result).strip()


# We replicate the client's fusion logic here, bypassing STDB entirely.
# Fusion: semantic 0.75, keyword 0.25, min-max normalization.
# Cross-encoder: ONNX (ms-marco-MiniLM-L-6-v2).

def embed(text):
    resp = httpx.post(f"{EMB}/embed", json={"text": text}, timeout=30)
    return resp.json()["embedding"]


def tantivy_search(ws, query, limit=20):
    resp = httpx.post(f"{TANTIVY}/search", json={
        "workspace_id": ws, "query": query, "limit": limit
    }, timeout=10)
    return resp.json().get("results", [])


def fusion_search(ws, query, docs, top_k=5):
    """Replicate client's fusion: semantic + keyword, weighted min-max."""
    import numpy as np

    # Semantic search (embedding cosine sim)
    q_emb = np.array(embed(f"Represent this sentence for searching relevant passages: {query}"))
    semantic_scores = {}
    for doc in docs:
        sim = float(np.dot(q_emb, np.array(doc["embedding"])) / 
                   (np.linalg.norm(q_emb) * np.linalg.norm(np.array(doc["embedding"]))))
        semantic_scores[doc["id"]] = sim

    # Keyword scores from Tantivy
    kw_results = tantivy_search(ws, query, limit=20)
    kw_scores = {}
    for r in kw_results:
        eid = r.get("entity_id", "")
        if eid not in kw_scores or r["score"] > kw_scores[eid]:
            kw_scores[eid] = r["score"]

    # Min-max normalize each strategy
    for strat_scores in [semantic_scores, kw_scores]:
        if strat_scores:
            vals = list(strat_scores.values())
            mn, mx = min(vals), max(vals)
            rng = mx - mn if mx > mn else 1.0
            for k in strat_scores:
                strat_scores[k] = (strat_scores[k] - mn) / rng

    # Weighted fusion: semantic 0.75, keyword 0.25
    fused = {}
    all_ids = set(semantic_scores.keys()) | set(kw_scores.keys())
    for eid in all_ids:
        fused[eid] = semantic_scores.get(eid, 0) * 0.75 + kw_scores.get(eid, 0) * 0.25

    # Sort and return top_k with content
    ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)
    results = []
    id_to_doc = {d["id"]: d for d in docs}
    for eid, score in ranked[:top_k]:
        doc = id_to_doc.get(eid, {})
        results.append({"content": doc.get("content", ""), "score": score})
    return results


def ce_rerank(query, candidates):
    """Cross-encoder reranking."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))
    from spacetime_memory.cross_encoder import CrossEncoderReranker
    reranker = CrossEncoderReranker()
    # Score each candidate
    scored = []
    for r in candidates:
        content = r.get("content", "")
        if content:
            s = reranker._score_pair(query, content)
            scored.append((r, s))
        else:
            scored.append((r, 0.0))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [{"content": r["content"], "score": s} for r, s in scored]


def main():
    http = httpx.Client(timeout=30)

    # Create workspace in Tantivy
    ws_id = f"logseq-{uuid.uuid4().hex[:8]}"

    # ── Seed ──
    pages = sorted((LOGSEQ_DIR / "pages").glob("*.md"))
    journals = sorted((LOGSEQ_DIR / "journals").glob("*.md")) if (LOGSEQ_DIR / "journals").exists() else []

    docs = []
    count, skip = 0, 0
    print("Seeding Logseq pages...", flush=True)

    for pf in pages + journals:
        raw = pf.read_text()
        content = clean_md(raw)
        if len(content) < 30:
            continue
        if len(content) > 1000:
            content = content[:1000]

        doc_id = f"doc-{count}"
        try:
            emb_vec = embed(content)
            docs.append({"id": doc_id, "content": content, "embedding": emb_vec, "title": pf.stem})
            # Index into Tantivy
            http.post(f"{TANTIVY}/index", json={
                "workspace_id": ws_id, "entity_id": doc_id,
                "content": content, "entity_type": "memory"
            })
            count += 1
        except Exception as e:
            skip += 1
            if skip <= 3:
                print(f"  SKIP {pf.name[:50]}", flush=True)

        if count % 30 == 0:
            print(f"  {count} docs...", flush=True)

    print(f"  Seeded {count} docs (skipped {skip})", flush=True)

    # ── Eval ──
    print(f"\n{'='*60}")
    print(f"EVAL — {count} docs, {len(QUERIES)} queries")
    print(f"{'='*60}")

    for ce in [False, True]:
        label = "Cross-encoder" if ce else "Baseline (no rerank)"
        pv, mv, tm, zd = [], [], [], 0

        for qt, terms in QUERIES:
            t0 = time.time()
            results = fusion_search(ws_id, qt, docs, top_k=10)
            if ce:
                results = ce_rerank(qt, results)[:5]
            else:
                results = results[:5]
            elapsed = time.time() - t0
            tm.append(elapsed)

            hits = sum(1 for r in results
                       if any(t.lower() in r.get("content", "").lower() for t in terms))
            pv.append(hits / min(5, max(len(results), 1)))

            mr = 0.0
            for j, r in enumerate(results):
                if any(t.lower() in r.get("content", "").lower() for t in terms):
                    mr = 1.0 / (j + 1)
                    break
            mv.append(mr)
            if hits == 0:
                zd += 1

        p5 = sum(pv) / len(pv)
        mrr = sum(mv) / len(mv)
        avg_ms = sum(tm) / len(tm) * 1000

        print(f"\n  [{label}]")
        print(f"    P@5={p5:.1%}  MRR={mrr:.3f}  {avg_ms:.0f}ms  zeros={zd}")


if __name__ == "__main__":
    main()
