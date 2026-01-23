from __future__ import annotations

import json
from typing import Any

import httpx
from fastmcp import Client


def _get_attr(x: Any, name: str):
    try:
        return getattr(x, name)
    except Exception:
        return None


def _extract_text(it: Any) -> str | None:
    if isinstance(it, dict):
        if it.get("type") == "text" and isinstance(it.get("text"), str):
            return it["text"]
        return None
    t = _get_attr(it, "text")
    if isinstance(t, str):
        return t
    return None


def _unwrap(res: Any) -> Any:
    d = _get_attr(res, "data")
    if d is not None:
        return d

    sc = _get_attr(res, "structured_content")
    if sc is not None:
        return sc

    if isinstance(res, dict):
        if res.get("data") is not None:
            return res["data"]
        if res.get("structured_content") is not None:
            return res["structured_content"]

        c = res.get("content")
        if isinstance(c, list):
            for it in c:
                t = _extract_text(it)
                if isinstance(t, str):
                    s = t.strip()
                    if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                        try:
                            return json.loads(s)
                        except Exception:
                            pass
        return res

    c = _get_attr(res, "content")
    if isinstance(c, list):
        for it in c:
            t = _extract_text(it)
            if isinstance(t, str):
                s = t.strip()
                if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                    try:
                        return json.loads(s)
                    except Exception:
                        pass

    return res


class ToolClient:
    def __init__(self, mcp_url: str, data_api: str):
        self.mcp_url = mcp_url
        self.data_api = data_api
        self.mcp_ok = False

    async def call(self, name: str, args: dict) -> tuple[bool, Any]:
        try:
            async with Client(self.mcp_url) as c:
                res = await c.call_tool(name, args)
            self.mcp_ok = True
            return True, _unwrap(res)
        except Exception:
            self.mcp_ok = False

        async with httpx.AsyncClient(timeout=180) as hc:
            if name == "top_rubrics":
                r = await hc.get(f"{self.data_api}/rubrics/top", params={"n": args.get("n", 50)})
            elif name == "top_regions":
                r = await hc.get(f"{self.data_api}/regions/top", params={"n": args.get("n", 50)})
            elif name == "text_search":
                r = await hc.get(f"{self.data_api}/search/text", params={"qs": args["qs"], "n": args.get("n", 20)})
            elif name == "negative_insights":
                p = {
                    "rubric": args["rubric"],
                    "n_terms": args.get("n_terms", 20),
                    "n_samples": args.get("n_samples", 5),
                    "max_docs": args.get("max_docs", 3000),
                }
                if args.get("a0"):
                    p["a0"] = args["a0"]
                r = await hc.get(f"{self.data_api}/insights/negative", params=p)
            else:
                raise ValueError(f"unknown tool: {name}")

            r.raise_for_status()
            return False, r.json()
