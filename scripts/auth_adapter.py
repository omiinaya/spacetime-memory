#!/usr/bin/env python3
"""OpenCode Zen router — ALL model traffic routed through our own proxy chain.

Every model goes to OpenCode Zen free tier (x-api-key: public) via :4002.
No OpenRouter, no external providers. Cardinal rule: everything through the
spacetime-llm proxy / OpenCode Zen free tier.
"""
import json, os
import uvicorn
from fastapi import FastAPI, Request, Response
import httpx

OPENCODE_ZEN = os.environ.get("OPENCODE_ZEN", "http://localhost:4002")
PORT = int(os.environ.get("PORT", "4004"))

app = FastAPI()
# Async client — sync httpx.Client serializes concurrent requests from the
# benchmark workloads (one in-flight request blocks all others), which made
# every LLM call queue behind the slowest one (~17s for a trivial prompt).
oc_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(request: Request, path: str):
    body = await request.body()
    req_headers = dict(request.headers)

    # Strip leading v1/ if present (upstream already has it)
    clean_path = path
    if clean_path.startswith("v1/"):
        clean_path = clean_path[3:]

    url = f"{OPENCODE_ZEN}/v1/{clean_path}"
    headers = {
        "x-api-key": "public",
        "Content-Type": req_headers.get("content-type", "application/json"),
    }
    resp = await oc_client.request(method=request.method, url=url, content=body, headers=headers)

    out_headers = {k: v for k, v in resp.headers.items()
                   if k.lower() not in ("content-length", "transfer-encoding", "content-encoding")}

    # Move reasoning_content -> content for OpenCode Zen models.
    # Some models (mimo) emit the answer in `reasoning` instead of
    # `reasoning_content`; hoist whichever reasoning field is present so
    # downstream benchmark clients always see a usable `content`.
    ct = resp.headers.get("content-type", "")
    if "application/json" in ct:
        try:
            data = resp.json()
            modified = False
            for ch in data.get("choices", []):
                msg = ch.get("message", {})
                c = msg.get("content", "")
                r = msg.get("reasoning_content", "") or msg.get("reasoning", "")
                if not c and r:
                    msg["content"] = r
                    msg.pop("reasoning_content", None)
                    msg.pop("reasoning", None)
                    modified = True
            if modified:
                nb = json.dumps(data).encode()
                out_headers["content-length"] = str(len(nb))
                return Response(content=nb, status_code=resp.status_code, headers=out_headers)
        except (json.JSONDecodeError, KeyError, AttributeError):
            pass

    return Response(content=resp.content, status_code=resp.status_code, headers=out_headers)


if __name__ == "__main__":
    print(f"[router] :{PORT} OCZ={OPENCODE_ZEN} (all models, no OpenRouter)", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="error")
