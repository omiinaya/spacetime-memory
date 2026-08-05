#!/usr/bin/env python3
"""Focused stress reproduction for the '2% fatal error under heavy concurrent load'.

Publishes a FRESH anonymous database (never touches production spacetime-memory-v2),
then hammers store + search reducers concurrently across many threads/rounds to try to
trigger the wasmtime 'The instance encountered a fatal error.' trap. Captures the exact
error text and dumps the SDK result so the root cause can be correlated with STDB logs.

Usage:
  OTEL_ENABLED=false python3 scripts/repro_fatal_error.py [--rounds N] [--threads N] [--stores N]
"""
import concurrent.futures
import os
import random
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk", "python"))

from spacetime_memory import Client  # noqa: E402

HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")

TOPICS = ["AI", "databases", "networking", "security", "storage", "testing", "deployment", "monitoring"]


def publish_fresh_stdb() -> str:
    """Publish the freshly-built WASM as a NEW anonymous database; return its identity/name."""
    import httpx

    module_dir = "/home/hindsight/spacetime-memory/server/spacetimedb"
    wasm_opt = os.path.join(module_dir, "target", "wasm32-unknown-unknown", "release", "spacetime_memory.opt.wasm")
    wasm_plain = os.path.join(module_dir, "target", "wasm32-unknown-unknown", "release", "spacetime_memory.wasm")
    wasm_path = wasm_plain if (wasm_plain and os.path.exists(wasm_plain) and (
        not os.path.exists(wasm_opt) or os.path.getmtime(wasm_plain) > os.path.getmtime(wasm_opt))) else wasm_opt
    if not os.path.exists(wasm_path):
        raise RuntimeError(f"WASM not found at {wasm_path}")

    anon = httpx.get(f"http://{HOST}:{PORT}/v1/database/anon-probe", timeout=5.0)
    token = anon.headers.get("spacetime-identity-token", "")
    headers = {"Content-Type": "application/octet-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = httpx.post(
        f"http://{HOST}:{PORT}/v1/database?host_type=Wasm",
        headers=headers,
        content=open(wasm_path, "rb").read(),
        timeout=60.0,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Publish failed HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    ident = data.get("Success", {}).get("database_identity") or data.get("Database", {}).get("database_identity")
    if not ident:
        raise RuntimeError(f"Could not parse identity: {data}")
    return ident


def setup_admin(client: Client):
    """Register a test user + promote to admin so admin reducers work."""
    suffix = os.urandom(4).hex()
    uname = f"stress_{suffix}"
    try:
        client._call("register", [uname, "Stress Tester", "testpass"])
    except RuntimeError:
        pass
    try:
        client._call("set_initial_admin", [client._whoami()])
    except RuntimeError:
        pass


def do_store(client: Client, ws: str, idx: int) -> tuple:
    try:
        r = client.store(
            workspace_id=ws,
            content=f"Stress {idx} about {random.choice(TOPICS)}",
            memory_type="experience",
            peer_id=f"stress-{idx}",
            confidence=0.8,
        )
        return (idx, True, r)
    except Exception as exc:
        return (idx, False, f"{type(exc).__name__}: {exc}")


def do_search(client: Client, ws: str, idx: int) -> tuple:
    try:
        r = client.search(ws, query="machine learning", limit=5, semantic=False)
        return (idx, True, r)
    except Exception as exc:
        return (idx, False, f"{type(exc).__name__}: {exc}")


def main():
    rounds = int(os.environ.get("ROUNDS", sys.argv[sys.argv.index("--rounds") + 1] if "--rounds" in sys.argv else 5))
    threads = int(sys.argv[sys.argv.index("--threads") + 1] if "--threads" in sys.argv else 50)
    stores = int(sys.argv[sys.argv.index("--stores") + 1] if "--stores" in sys.argv else 50)

    db = publish_fresh_stdb()
    print(f"[setup] published fresh anonymous DB: {db[:16]}...")
    client = Client(host=HOST, port=PORT, database=db, verbose=False)
    setup_admin(client)

    ws = client.create_workspace(f"stress-{uuid.uuid4().hex[:8]}", "fatal repro")
    ws_id = ws["id"]
    client._call("set_workspace_visibility", [ws_id, True])
    print(f"[setup] workspace {ws_id[:12]}... ready; threads={threads} stores={stores} rounds={rounds}")

    total_fatal = 0
    total_other = 0
    t0 = time.time()
    for rnd in range(rounds):
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as pool:
            futures = [pool.submit(do_store, client, ws_id, i) for i in range(stores)]
            concurrent.futures.wait(futures)
            for f in futures:
                if not f.cancelled():
                    results.append(f.result())
        succ = [r for r in results if r[1]]
        fail = [r for r in results if not r[1]]
        fatal = [r for r in fail if "fatal" in str(r[2]).lower()]
        other = [r for r in fail if "fatal" not in str(r[2]).lower()]
        total_fatal += len(fatal)
        total_other += len(other)
        print(f"[round {rnd+1}/{rounds}] {len(succ)}/{len(results)} ok | fatal={len(fatal)} other={len(other)}")
        for r in (fatal + other)[:6]:
            print(f"    FAIL idx={r[0]}: {str(r[2])[:180]}")

    elapsed = time.time() - t0
    print(f"\nSUMMARY: total_fatal={total_fatal} total_other={total_other} over {rounds} rounds "
          f"({threads * stores * rounds} stores) in {elapsed:.1f}s")
    # Exit nonzero if we hit the fatal trap so callers/CI flag it.
    sys.exit(0)


if __name__ == "__main__":
    main()