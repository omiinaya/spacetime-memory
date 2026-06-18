#!/usr/bin/env python3
"""Seed all Logseq pages and journals into spacetime-memory for eval."""
import os, sys, time, uuid, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))

import httpx
from spacetime_memory import Client

# ── Config ──
LOGSEQ_DIR = Path.home() / "logseq-graph"
DB = "c200e6dac0c27d57edf72c2068c3b23d35462f418337fa4ac8f3fbfea2469193"
EMB = os.environ.get("EMBEDDER_URL", "http://localhost:9092")
TANTIVY = "http://localhost:9091"

# Auth
resp = httpx.get(f"http://localhost:3001/v1/database/{DB}", timeout=5)
c = Client(database=DB, embedder_url=EMB, token=resp.headers.get("spacetime-identity-token", ""))
try:
    c._call("register", [f"logseq-{uuid.uuid4().hex[:6]}", "x" * 6, resp.headers.get("spacetime-identity", "")])
except Exception:
    pass

ws = c.create_workspace(f"logseq-{uuid.uuid4().hex[:4]}", "Logseq knowledge base")
WS = ws["id"]
c._call("set_workspace_visibility", [WS, True])
print(f"Workspace: {WS}")

http = httpx.Client(timeout=10)


def clean_markdown(text: str) -> str:
    """Strip Logseq properties and extract plain content."""
    lines = text.split("\n")
    result = []
    for line in lines:
        # Skip Logseq property lines
        if re.match(r"^\w+::\s", line):
            continue
        # Skip tags-only lines
        if re.match(r"^tags::", line, re.IGNORECASE):
            continue
        # Strip markdown formatting for better embedding
        line = re.sub(r"\[\[([^\]]+)\]\]", r"\1", line)  # wikilinks
        line = re.sub(r"#(\S+)", r"\1", line)  # hashtags
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)  # bold
        line = re.sub(r"`([^`]+)`", r"\1", line)  # inline code
        result.append(line)
    return "\n".join(result).strip()


# ── Read and seed pages ──
pages_dir = LOGSEQ_DIR / "pages"
page_files = sorted(pages_dir.glob("*.md"))
print(f"\nSeeding {len(page_files)} pages...")

t0 = time.time()
count = 0
for pf in page_files:
    raw = pf.read_text()
    # Extract title from first heading
    title = pf.stem
    m = re.search(r"^#\s+(.+)", raw, re.MULTILINE)
    if m:
        title = m.group(1)

    content = clean_markdown(raw)
    if len(content) < 20:
        continue

    # Truncate very long pages to ~2000 chars for embedding
    if len(content) > 2000:
        content = content[:2000]

    try:
        c.store(
            workspace_id=WS,
            content=content,
            summary=title,
            memory_type="world_fact",
            peer_id="logseq-seeder",
            confidence=0.85,
        )
        count += 1
    except Exception as e:
        print(f"  Error on {pf.name}: {e}")

    if count % 20 == 0:
        elapsed = time.time() - t0
        print(f"  {count}/{len(page_files)} ({elapsed:.0f}s)")

print(f"Pages seeded: {count} in {time.time()-t0:.0f}s")

# ── Seed journals ──
journals_dir = LOGSEQ_DIR / "journals"
journal_files = sorted(journals_dir.glob("*.md")) if journals_dir.exists() else []
print(f"\nSeeding {len(journal_files)} journal entries...")

jcount = 0
for jf in journal_files:
    raw = jf.read_text()
    content = clean_markdown(raw)
    if len(content) < 50:
        continue
    if len(content) > 2000:
        content = content[:2000]

    title = jf.stem.replace("_", "-")

    try:
        c.store(
            workspace_id=WS,
            content=content,
            summary=title,
            memory_type="experience",
            peer_id="logseq-seeder",
            confidence=0.8,
        )
        jcount += 1
    except Exception:
        pass

print(f"Journals seeded: {jcount}")

# ── Tantivy reindex ──
print("\nReindexing into Tantivy...")
mems = c._query("memory", workspace_id=WS, columns=["id", "content"])
for m in mems:
    http.post(f"{TANTIVY}/index", json={
        "workspace_id": WS,
        "entity_id": m["id"],
        "content": m["content"],
        "entity_type": "memory",
    })
print(f"Tantivy: {len(mems)} indexed")

# ── Output workspace ID for eval ──
with open("/tmp/logseq_workspace_id.txt", "w") as f:
    f.write(WS)
print(f"\nDone. Workspace: {WS}")
print(f"Total docs: {len(mems)}")
