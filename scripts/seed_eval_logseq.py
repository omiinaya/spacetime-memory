#!/usr/bin/env python3
"""Seed Logseq + eval baseline vs cross-encoder. One shot."""
import os, sys, time, uuid, re, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))
import httpx
from spacetime_memory import Client

DB = open(os.path.join(os.path.dirname(__file__), "..", "data", "database_identity")).read().strip()
EMB = os.environ.get("EMBEDDER_URL", "http://localhost:9092")
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


def main():
    resp = httpx.get(f"http://localhost:3001/v1/database/{DB}", timeout=5)
    token = resp.headers.get("spacetime-identity-token", "")
    identity = resp.headers.get("spacetime-identity", "")
    c = Client(database=DB, embedder_url=EMB, token=token)
    http = httpx.Client(timeout=30)

    peer = f"logseq-{uuid.uuid4().hex[:6]}"
    try:
        c._call("register", [peer, "eval123", identity])
        print(f"  Registered as {peer}", flush=True)
    except Exception as e:
        print(f"  Register warning: {e}", flush=True)

    # ── Seed ──
    ws = c.create_workspace(f"logseq-{uuid.uuid4().hex[:4]}", "Logseq eval")
    WS = ws["id"]
    c._call("set_workspace_visibility", [WS, True])

    pages = sorted((LOGSEQ_DIR / "pages").glob("*.md"))
    journals = sorted((LOGSEQ_DIR / "journals").glob("*.md")) if (LOGSEQ_DIR / "journals").exists() else []

    count = 0
    skip = 0
    for pf in pages + journals:
        raw = pf.read_text()
        content = clean_md(raw)
        if len(content) < 30:
            continue
        if len(content) > 1000:
            content = content[:1000]
        try:
            c.store(workspace_id=WS, content=content, summary=pf.stem,
                    memory_type="world_fact", peer_id=peer, confidence=0.85)
            count += 1
        except Exception as e:
            skip += 1
            if skip <= 3:
                print(f"  SKIP {pf.name[:50]} — {e}", flush=True)
        if count % 30 == 0:
            print(f"  Seeded {count}...", flush=True)

    print(f"  Seeded {count} docs total (skipped {skip})", flush=True)

    # ── Tantivy index ──
    print("  Indexing Tantivy...", flush=True)
    mems = c._query("memory", workspace_id=WS, columns=["id", "content"])
    for m in mems:
        try:
            http.post(f"{TANTIVY}/index", json={
                "workspace_id": WS, "entity_id": m["id"],
                "content": m.get("content", ""), "entity_type": "memory"
            }, timeout=5)
        except Exception:
            pass
    print(f"  Tantivy: {len(mems)} docs", flush=True)

    # ── Eval ──
    print(f"\n{'='*60}")
    print(f"EVAL — {len(mems)} Logseq docs, {len(QUERIES)} queries")
    print(f"{'='*60}")

    for ce in [False, True]:
        label = "Cross-encoder" if ce else "Baseline"
        pv, mv, tm, zd, details = [], [], [], 0, []

        for qt, terms in QUERIES:
            t0 = time.time()
            res = c.search(WS, query=qt, limit=5, semantic=True, rerank=False, cross_encoder=ce)
            elapsed = time.time() - t0
            tm.append(elapsed)

            hits = sum(1 for r in res[:5]
                       if any(t.lower() in r.get("memory_content", "").lower() for t in terms))
            pv.append(hits / min(5, max(len(res), 1)))

            mr = 0.0
            for j, r in enumerate(res):
                if any(t.lower() in r.get("memory_content", "").lower() for t in terms):
                    mr = 1.0 / (j + 1)
                    break
            mv.append(mr)
            if hits == 0:
                zd += 1
                details.append({"query": qt, "top3": [r.get("memory_content", "")[:80] for r in res[:3]]})

        p5 = sum(pv) / len(pv)
        mrr = sum(mv) / len(mv)
        avg_ms = sum(tm) / len(tm) * 1000

        print(f"\n  [{label}]")
        print(f"    P@5={p5:.1%}  MRR={mrr:.3f}  {avg_ms:.0f}ms  zeros={zd}")

        if not ce and zd:
            print(f"    Zero-score queries:")
            for d in details:
                top = d.get("top3", ["N/A"])[0]
                print(f"      ✗ {d['query'][:50]}")
                print(f"        → {top[:90]}")

    # Save workspace ID for reuse
    with open("/tmp/logseq_workspace_id.txt", "w") as f:
        f.write(WS)
    print(f"\nWorkspace: {WS}")


if __name__ == "__main__":
    main()
