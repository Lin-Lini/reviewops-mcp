from __future__ import annotations

import time
import httpx

class LogClient:
    def __init__(self, base_url: str, enabled: bool = True):
        self.base_url = base_url.rstrip("/")
        self.enabled = enabled

    async def emit(self, trace_id: str, service: str, event: str, payload: dict | None = None):
        if not self.enabled:
            return
        data = {
            "trace_id": trace_id,
            "service": service,
            "event": event,
            "ts": time.time(),
            "payload": payload or {},
        }
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                await c.post(f"{self.base_url}/event", json=data)
        except Exception:
            # logging must never break product
            return
