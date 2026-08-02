#!/usr/bin/env python3
"""Fast batch ingest for LoCoMo datasets using store_batch (5s vs 12min)."""

import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))

import httpx
from spacetime_memory import Client

LOCOMO_DATA_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://localhost:9090")
STDB_URL = os.environ.get("SPACETIMEDB_URL", "http://localhost:3001")


def download_dataset(url: str) -> list[dict]:
    print(f"Downloading dataset...", file=sys.stderr)
    try:
        resp = urllib.request.urlopen(url, timeout=30)
        data = json.loads(resp.read().decode())
        print(f"  Loaded {len(data)} conversations", file=sys.stderr)
        return data
    except (OSError, json.JSONDecodeError) as e:
        print(f"  ERROR downloading: {e}", file=sys.stderr)
        sys.exit(1)


def extract_turns(conversation: dict) -> list[dict]:
    """Extract all turns with metadata."""
    turns = []
    conv = conversation.get("conversation", {})
    speaker_a = conv.get("speaker_a", "Speaker A")
    speaker_b = conv.get("speaker_b", "Speaker B")

    session_keys = sorted(
        [k for k in conv.keys() if k.startswith("session_") and not k.endswith("_date_time")],
        key=lambda x: int(x.split("_")[1]),
    )

    turn_id = 0
    for sk in session_keys:
        session_num = sk.split("_")[1]
        date_time_key = f"session_{session_num}_date_time"
        session_dt = conv.get(date_time_key, f"Session {session_num}")
        session_turns = conv.get(sk, [])
        for t in session_turns:
            turn_id += 1
            speaker_name = t.get("speaker", "")
            text = t.get("text", "")
            turns.append({
                "turn_id": turn_id,
                "session_num": int(session_num),
                "session_dt": session_dt,
                "speaker": speaker_a if "a" in speaker_name.lower() else speaker_b,
                "text": text,
            })
    return turns


def batch_ingest(client: Client, workspace_id: str, conversation: dict) -> int:
    """Ingest all turns in a single batch call (fast!)."""
    turns = extract_turns(conversation)
    conv_data = conversation.get("conversation", {})
    speaker_a = conv_data.get("speaker_a", "Speaker A")
    speaker_b = conv_data.get("speaker_b", "Speaker B")

    # Build batch items
    batch_items = []
    for t in turns:
        # Content with session tag for temporal matching
        content = t["text"] + f" [Session {t['session_num']}]"
        batch_items.append({
            "content": content,
            "summary": content[:200],
            "memory_type": "locomo_turn",
            "confidence": 1.0,
            "entities_json": json.dumps([
                {"name": speaker_a, "entity_type": "person"},
                {"name": speaker_b, "entity_type": "person"},
                {"name": f"session_{t['session_num']}", "entity_type": "session"},
                {"name": t["session_dt"], "entity_type": "datetime"},
                {"name": f"turn_{t['turn_id']}", "entity_type": "turn_id"},
            ]),
        })

    # Also add session summaries
    for sess_key, summary in (conversation.get("session_summary", {}) or {}).items():
        if summary:
            batch_items.append({
                "content": f"[Summary] {summary}",
                "summary": f"[Summary] {summary}"[:200],
                "memory_type": "locomo_summary",
                "confidence": 0.9,
            })

    print(f"  Batch-ingesting {len(batch_items)} items...", file=sys.stderr)
    t0 = time.time()
    results = client.store_batch(workspace_id=workspace_id, items=batch_items)
    elapsed = time.time() - t0
    print(f"  Ingested {len(results)} items in {elapsed:.1f}s ({len(results)/max(elapsed,0.01):.0f} items/s)", file=sys.stderr)
    return len(results)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fast batch ingest for LoCoMo")
    parser.add_argument("--conv", type=str, default="", help="Comma-separated 1-based indices")
    parser.add_argument("--workspace", type=str, default="", help="Reuse existing workspace ID")
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    print("=" * 60, file=sys.stderr)
    print("  Fast Batch Ingest for LoCoMo", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Connect
    print("\nConnecting to SpacetimeDB...", file=sys.stderr)
    db_id = os.environ.get("SPACETIMEDB_DB", "")
    if not db_id:
        print("ERROR: SPACETIMEDB_DB must be set", file=sys.stderr)
        sys.exit(1)
    token_resp = httpx.get(f"{STDB_URL}/v1/database/{db_id}", timeout=10)
    token = token_resp.headers.get("spacetime-identity-token", "")
    identity = token_resp.headers.get("spacetime-identity", "")
    client = Client(database=db_id, embedder_url=EMBEDDER_URL, token=token or None)
    try:
        client._call("register", [f"fast-ingest-{secrets.token_hex(4)}", "lmeval2026", identity])
    except Exception:
        pass
    print(f"  Connected", file=sys.stderr)

    # Download
    dataset = download_dataset(LOCOMO_DATA_URL)

    if args.conv:
        conv_indices = [int(x.strip()) - 1 for x in args.conv.split(",")]
        dataset = [dataset[i] for i in conv_indices if 0 <= i < len(dataset)]
        print(f"  Selected {len(dataset)} conversation(s)", file=sys.stderr)

    for conv_idx, conversation in enumerate(dataset):
        sample_id = conversation.get("sample_id", f"conv_{conv_idx + 1}")
        print(f"\n{'─' * 50}", file=sys.stderr)
        print(f"  Conversation {conv_idx + 1}: {sample_id}", file=sys.stderr)
        print(f"{'─' * 50}", file=sys.stderr)

        workspace_name = f"locomo_v2_{sample_id}"
        if args.workspace:
            workspace_id = args.workspace
        else:
            try:
                ws = client.create_workspace(name=workspace_name, description=f"LoCoMo v2: {sample_id}")
                workspace_id = ws.get("id", ws.get("workspace_id", ""))
                if not workspace_id:
                    for w in client.list_workspaces():
                        if w.get("name") == workspace_name:
                            workspace_id = w.get("id", w.get("workspace_id", ""))
                            break
                if not workspace_id:
                    print(f"  ERROR: Could not create workspace", file=sys.stderr)
                    continue
                print(f"  Workspace: {workspace_id}", file=sys.stderr)
            except Exception as e:
                print(f"  ERROR creating workspace: {e}", file=sys.stderr)
                continue

        # Batch-ingest
        ingested = batch_ingest(client, workspace_id, conversation)

        # Print workspace ID for use with benchmak --no-ingest
        print(f"\nWORKSPACE_ID={workspace_id}", file=sys.stderr)
        print(f"INGESTED={ingested}", file=sys.stderr)


if __name__ == "__main__":
    main()
