import os
import httpx
from fastmcp import FastMCP

DATA_API = os.getenv("DATA_API", "http://api:8000")

mcp = FastMCP("reviewops")

async def get(path: str, params: dict | None = None):
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.get(f"{DATA_API}{path}", params=params or {})
        r.raise_for_status()
        return r.json()

@mcp.tool()
async def top_rubrics(n: int = 50):
    return await get("/rubrics/top", {"n": n})

@mcp.tool()
async def top_regions(n: int = 50):
    return await get("/regions/top", {"n": n})

@mcp.tool()
async def text_search(qs: str, n: int = 20):
    return await get("/search/text", {"qs": qs, "n": n})

@mcp.tool()
async def negative_insights(
    rubric: str,
    a0: str | None = None,
    n_terms: int = 20,
    n_samples: int = 5,
    max_docs: int = 3000,
):
    p = {"rubric": rubric, "n_terms": n_terms, "n_samples": n_samples, "max_docs": max_docs}
    if a0:
        p["a0"] = a0
    return await get("/insights/negative", p)

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8787)
