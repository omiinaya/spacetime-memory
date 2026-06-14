#!/usr/bin/env python3
"""Eval on Logseq data."""
import os, sys, time, uuid, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))

import httpx
from spacetime_memory import Client

_env = os.path.expanduser("~/.hermes/.env")
if os.path.exists(_env):
    with open(_env) as f:
        for line in f:
            if line.strip().startswith("LITELLM_MASTER_KEY="):
                _, k = line.split("=", 1)
                os.environ["LLM_RERANK_API_KEY"] = k.strip().strip('"').strip("'")
os.environ.setdefault("LLM_RERANK_ENDPOINT", "http://192.168.1.111:4000/v1")
os.environ.setdefault("LLM_RERANK_MODEL", "ds-deepseek-v4-flash")

DB = "c200bd2c4073807f98d79813c26afd931482f2f422a3a860d78d91298ddaa816"
EMB = os.environ.get("EMBEDDER_URL", "http://localhost:9092")
WS = open("/tmp/logseq_workspace_id.txt").read().strip()

print(f"Workspace: {WS[:16]}...", flush=True)

resp = httpx.get(f"http://localhost:3001/v1/database/{DB}", timeout=5)
c = Client(database=DB, embedder_url=EMB, token=resp.headers.get("spacetime-identity-token", ""))
try:
    c._call("register", [f"evl-{uuid.uuid4().hex[:6]}", "x" * 6, resp.headers.get("spacetime-identity", "")])
except Exception:
    pass

mems = c._query("memory", workspace_id=WS, columns=["id"])
print(f"Docs: {len(mems)}", flush=True)

queries = [
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


def run(qs, rerank):
    pv, mv, tm, zd = [], [], [], 0
    for qt, terms in qs:
        t0 = time.time()
        res = c.search(WS, query=qt, limit=5, semantic=True, rerank=rerank)
        t = time.time() - t0
        h = sum(
            1
            for r in res[:5]
            if any(tt.lower() in r.get("memory_content", "").lower() for tt in terms)
        )
        pv.append(h / min(5, max(len(res), 1)))
        mr = next(
            (
                1.0 / (i + 1)
                for i, r in enumerate(res)
                if any(tt.lower() in r.get("memory_content", "").lower() for tt in terms)
            ),
            0.0,
        )
        mv.append(mr)
        tm.append(t)
        if h == 0:
            zd += 1
    return {
        "P@5": sum(pv) / len(pv),
        "MRR": sum(mv) / len(mv),
        "ms": sum(tm) / len(tm) * 1000,
        "zeros": zd,
    }


n = run(queries, False)
print(f"NO RERANK:  P@5={n['P@5']:.1%}  MRR={n['MRR']:.3f}  {n['ms']:.0f}ms  zeros={n['zeros']}", flush=True)

y = run(queries, True)
print(f"WITH RERANK: P@5={y['P@5']:.1%}  MRR={y['MRR']:.3f}  {y['ms']:.0f}ms  zeros={y['zeros']}", flush=True)
print(f"Delta: P@5={(y['P@5']-n['P@5']):+.0%}  MRR={(y['MRR']-n['MRR']):+.3f}", flush=True)

with open("/tmp/eval_logseq.json", "w") as f:
    json.dump({"no_rerank": n, "with_rerank": y, "docs": len(mems), "queries": len(queries)}, f, indent=2)
print("Saved to /tmp/eval_logseq.json", flush=True)
