#!/usr/bin/env python3
"""Smart router: OpenCode Zen for answers, OpenRouter for JSON-capable judge."""
import json, os
import uvicorn
from fastapi import FastAPI, Request, Response
import httpx

OPENCODE_ZEN = os.environ.get("OPENCODE_ZEN", "http://localhost:4002")
OPENROUTER = os.environ.get("OPENROUTER", "https://openrouter.ai")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY",
    "sk-or-v1-REPLACED")
PORT = int(os.environ.get("PORT", "4004"))

ROUTER_MODELS = ("gemma", "openai/", "anthropic/", "openrouter")

app = FastAPI()
# Async clients — sync httpx.Client serializes concurrent requests from the
# benchmark workloads (one in-flight request blocks all others), which made
# every LLM call queue behind the slowest one (~17s for a trivial prompt).
oc_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
or_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(request: Request, path: str):
    body = await request.body()
    req_headers = dict(request.headers)

    # Determine target from model
    target = "oc"
    if body:
        try:
            model = json.loads(body).get("model", "")
            if any(x in model for x in ROUTER_MODELS):
                target = "or"
        except json.JSONDecodeError:
            pass

    # Strip leading v1/ if present (upstreams already have it or have their own paths)
    clean_path = path
    if clean_path.startswith("v1/"):
        clean_path = clean_path[3:]

    if target == "or":
        url = f"{OPENROUTER}/api/v1/{clean_path}"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": req_headers.get("content-type", "application/json"),
        }
        resp = await or_client.request(method=request.method, url=url, content=body, headers=headers)
    else:
        url = f"{OPENCODE_ZEN}/v1/{clean_path}"
        headers = {
            "x-api-key": "public",
            "Content-Type": req_headers.get("content-type", "application/json"),
        }
        resp = await oc_client.request(method=request.method, url=url, content=body, headers=headers)

    out_headers = {k: v for k, v in resp.headers.items()
                   if k.lower() not in ("content-length", "transfer-encoding", "content-encoding")}

    # Move reasoning_content -> content for OpenCode Zen models
    ct = resp.headers.get("content-type", "")
    if "application/json" in ct and target == "oc":
        try:
            data = resp.json()
            modified = False
            for ch in data.get("choices", []):
                msg = ch.get("message", {})
                c = msg.get("content", "")
                r = msg.get("reasoning_content", "")
                if not c and r:
                    msg["content"] = r
                    msg.pop("reasoning_content", None)
                    modified = True
            if modified:
                nb = json.dumps(data).encode()
                out_headers["content-length"] = str(len(nb))
                return Response(content=nb, status_code=resp.status_code, headers=out_headers)
        except (json.JSONDecodeError, KeyError, AttributeError):
            pass

    return Response(content=resp.content, status_code=resp.status_code, headers=out_headers)


if __name__ == "__main__":
    print(f"[router] :{PORT} OCZ={OPENCODE_ZEN} OR={OPENROUTER}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="error")
