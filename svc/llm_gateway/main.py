from __future__ import annotations

import os
from typing import Any, Dict

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="llm-gateway", version="0.1.0")

def _env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()

def _backend() -> str:
    b = _env("LLM_BACKEND", "local").lower()
    return "proxyapi" if b in ("proxyapi", "proxy", "remote") else "local"

def _timeout() -> float:
    try:
        return float(_env("LLM_TIMEOUT_S", "120"))
    except Exception:
        return 120.0

def _local_url() -> str:
    return _env("LOCAL_LLM_CHAT_URL", "http://llm_local:8080/v1/chat/completions")

def _proxy_base() -> str:
    # OpenAI-compatible base per ProxyAPI docs
    return _env("PROXYAPI_OPENAI_BASE", "https://openai.api.proxyapi.ru/v1")

def _proxy_key() -> str:
    return _env("PROXYAPI_KEY", "")

def _proxy_model() -> str:
    # Model naming scheme: gemini/<model> (ProxyAPI OpenAI-compatible router)
    return _env("PROXYAPI_MODEL", "gemini/gemini-2.5-flash-lite")

@app.get("/health")
async def health():
    return {"ok": True, "backend": _backend()}

@app.post("/v1/chat/completions")
async def chat_completions(req: Request):
    payload: Dict[str, Any] = await req.json()

    backend = _backend()
    timeout = _timeout()

    if backend == "proxyapi":
        key = _proxy_key()
        if not key:
            return JSONResponse({"error": {"message": "PROXYAPI_KEY is empty", "type": "config_error"}}, status_code=500)

        payload["model"] = _proxy_model()

        url = _proxy_base().rstrip("/") + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        }
    else:
        url = _local_url()
        headers = {"Content-Type": "application/json"}

    stream = bool(payload.get("stream", False))

    async with httpx.AsyncClient(timeout=timeout) as client:
        if stream:
            upstream = await client.stream("POST", url, json=payload, headers=headers)
            if upstream.status_code >= 400:
                body = await upstream.aread()
                return Response(content=body, status_code=upstream.status_code, media_type=upstream.headers.get("content-type", "application/json"))

            return StreamingResponse(
                upstream.aiter_bytes(),
                status_code=upstream.status_code,
                media_type=upstream.headers.get("content-type", "text/event-stream"),
            )

        r = await client.post(url, json=payload, headers=headers)
        return Response(
            content=r.content,
            status_code=r.status_code,
            media_type=r.headers.get("content-type", "application/json"),
        )
