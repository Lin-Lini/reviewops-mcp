from __future__ import annotations

from typing import Any

import httpx


class ModeratorClient:
    def __init__(self, base_url: str, enabled: bool = False):
        self.base_url = base_url.rstrip("/")
        self.enabled = enabled

    async def moderate(self, phase: str, text: str, system_prompt: str | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {"action": "allow", "reasons": [], "matches": [], "redacted_text": None}

        payload: dict[str, Any] = {"phase": phase, "text": text}
        if system_prompt:
            payload["system_prompt"] = system_prompt

        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.post(f"{self.base_url}/moderate", json=payload)
                if r.status_code != 200:
                    return {"action": "allow", "reasons": ["moderator_unavailable"], "matches": [], "redacted_text": None}
                j = r.json()
                if isinstance(j, dict) and j.get("action") in {"allow", "redact", "block"}:
                    return j
        except Exception:
            return {"action": "allow", "reasons": ["moderator_error"], "matches": [], "redacted_text": None}

        return {"action": "allow", "reasons": ["moderator_bad_response"], "matches": [], "redacted_text": None}
