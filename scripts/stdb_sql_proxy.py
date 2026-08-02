#!/usr/bin/env python3
"""Native SpacetimeDB SQL proxy for the web dashboard.

The browser cannot read the `spacetime-identity-token` response header because
STDB does not send `Access-Control-Expose-Headers` — so the dashboard cannot
query private tables (workspace, note, profile, hybrid_result) directly.

This proxy runs server-side, fetches a server-issued identity token from
`GET /v1/database/{db}` (headers ARE readable server-side), registers the
identity, then forwards SQL queries with `Authorization: Bearer <token>`.
The dashboard talks to this proxy instead of STDB directly — no CORS issue,
private tables work, and the dashboard keeps its native connection flow.

Usage:
    python3 scripts/stdb_sql_proxy.py [--port 5190] [--db spacetime-memory-v2]

Endpoints:
    GET  /health            → {"ok": true, "database": "..."}
    GET  /v1/database/{db}  → proxied to STDB (for token discovery + listing)
    POST /v1/database/{db}/sql → proxied SQL with auth (raw text body)
"""
import argparse
import json
import os
import urllib.request
import urllib.error

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

STDB_URL = os.environ.get("SPACETIMEDB_URL", "http://127.0.0.1:3001")
DEFAULT_DB = os.environ.get("SPACETIMEDB_DB", "spacetime-memory-v2")

app = FastAPI(title="Spacetime Memory SQL Proxy")

# Allow the dashboard (any origin — LAN tool) to call this proxy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cached identity token — fetched once, reused across requests
_cached_token = ""
_cached_identity = ""

# Persisted identity — a fresh anonymous token each boot would lose workspace
# grants on every restart. Save the server-issued token to disk (same pattern
# as the CLI's ~/.config/spacetime/cli.toml) so the dashboard identity is stable.
IDENTITY_FILE = os.path.expanduser("~/.config/spacetime/dashboard_proxy_identity.json")


def _load_persisted_identity() -> tuple[str, str]:
    try:
        with open(IDENTITY_FILE) as f:
            data = json.load(f)
        return data.get("token", ""), data.get("identity", "")
    except Exception:
        return "", ""


def _save_persisted_identity(token: str, identity: str):
    try:
        os.makedirs(os.path.dirname(IDENTITY_FILE), exist_ok=True)
        with open(IDENTITY_FILE, "w") as f:
            json.dump({"token": token, "identity": identity}, f)
    except Exception:
        pass


def _fetch_identity(db: str) -> tuple[str, str]:
    """Fetch a server-issued identity token for the database (server-side, no CORS).

    Uses the persisted identity if present (stable across restarts), otherwise
    requests a fresh token and saves it. Never touches credentials of other users.
    """
    global _cached_token, _cached_identity
    if _cached_token:
        return _cached_token, _cached_identity
    # Prefer persisted identity so workspace grants survive service restarts.
    p_token, p_identity = _load_persisted_identity()
    if p_token and p_identity:
        _cached_token, _cached_identity = p_token, p_identity
        return _cached_token, _cached_identity
    req = urllib.request.Request(f"{STDB_URL}/v1/database/{db}", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            token = resp.headers.get("spacetime-identity-token", "")
            identity = resp.headers.get("spacetime-identity", "")
            _cached_token = token
            _cached_identity = identity
            if token and identity:
                _save_persisted_identity(token, identity)
            return token, identity
    except Exception as e:
        raise RuntimeError(f"Failed to fetch identity token: {e}")


def _register(db: str, identity: str, token: str):
    """Register the identity so workspace ACLs treat it as a real user.

    Must send the Bearer token so the reducer sees the token's identity as
    ctx.sender() — without it, the account is created for an anonymous identity.
    """
    try:
        body = json.dumps([f"dashboard-{identity[:8]}", "dashboard789", "dashboard-pass-123"]).encode()
        req = urllib.request.Request(
            f"{STDB_URL}/v1/database/{db}/call/register",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass  # Already registered or registration not required


@app.get("/health")
async def health():
    return {"ok": True, "database": DEFAULT_DB, "proxy": "stdb-sql-proxy"}


@app.get("/v1/database/{db}")
async def database_info(db: str):
    """Proxy GET /v1/database/{db} — lets the dashboard confirm the module exists."""
    try:
        token, identity = _fetch_identity(db)
        if identity:
            _register(db, identity, token)
        req = urllib.request.Request(f"{STDB_URL}/v1/database/{db}", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read()
            return Response(content=body, media_type="application/json")
    except Exception as e:
        return Response(content=json.dumps({"error": str(e)}), status_code=500, media_type="application/json")


@app.post("/v1/database/{db}/query")
async def query_endpoint(db: str, request: Request):
    """Query a private content table via the query_table reducer flow.

    Body: {"table": "workspace", "workspace_id": "", "filter": {...}, "columns": [...]}
    Uses the SDK's _query() path server-side (reducer + result read-back),
    which handles private-table ACLs that raw SQL cannot.
    """
    try:
        token, identity = _fetch_identity(db)
        if identity:
            _register(db, identity, token)

        from spacetime_memory import Client

        client = Client(database=db, token=token or None, verbose=False)
        body = await request.json()
        table = body.get("table", "")
        workspace_id = body.get("workspace_id", "")
        filter_dict = body.get("filter") or {}
        columns = body.get("columns") or None
        rows = client._query(table, workspace_id, filter_dict, columns)
        return Response(content=json.dumps(rows), media_type="application/json")
    except Exception as e:
        return Response(content=json.dumps({"error": str(e)}), status_code=500, media_type="application/json")


@app.post("/v1/database/{db}/sql")
async def sql_proxy(db: str, request: Request):
    """Proxy a raw SQL query with Bearer auth."""
    raw = (await request.body()).decode("utf-8", "replace")
    try:
        token, identity = _fetch_identity(db)
        if identity:
            _register(db, identity, token)
        req = urllib.request.Request(
            f"{STDB_URL}/v1/database/{db}/sql",
            data=raw.encode(),
            headers={
                "Content-Type": "text/plain",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            return Response(content=body, media_type="application/json")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        return Response(content=json.dumps({"error": detail}), status_code=e.code, media_type="application/json")
    except Exception as e:
        return Response(content=json.dumps({"error": str(e)}), status_code=500, media_type="application/json")


@app.post("/v1/database/{db}/call/{reducer}")
async def call_reducer(db: str, reducer: str, request: Request):
    """Forward a reducer call (store_memory, delete_memory, create_node, ...) with Bearer auth.

    The dashboard's Memory Manager routes store/delete through this proxy — without
    forwarding, those UI actions 404'd. Reducers are the only way to touch private
    tables (workspace, note, ...), so this is the native write path for the UI.
    """
    raw = (await request.body()).decode("utf-8", "replace")
    try:
        token, identity = _fetch_identity(db)
        if identity:
            _register(db, identity, token)
        req = urllib.request.Request(
            f"{STDB_URL}/v1/database/{db}/call/{reducer}",
            data=raw.encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            return Response(content=body, media_type="application/json")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        return Response(content=json.dumps({"error": detail}), status_code=e.code, media_type="application/json")
    except Exception as e:
        return Response(content=json.dumps({"error": str(e)}), status_code=500, media_type="application/json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SpacetimeDB SQL proxy (dashboard auth)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("STDB_PROXY_PORT", "5190")))
    parser.add_argument("--db", type=str, default=DEFAULT_DB)
    args = parser.parse_args()
    os.environ["SPACETIMEDB_DB"] = args.db
    uvicorn.run(app, host="0.0.0.0", port=args.port)
