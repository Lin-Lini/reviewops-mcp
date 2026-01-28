from __future__ import annotations

import httpx

class SecurityClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def verify(self, token: str) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.post(f"{self.base_url}/verify", json={"token": token})
                if r.status_code != 200:
                    return None
                return r.json()
        except Exception:
            return None
