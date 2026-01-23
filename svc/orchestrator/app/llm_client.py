from __future__ import annotations

import httpx

class LLMClient:
    def __init__(self, chat_url: str, model: str):
        self.chat_url = chat_url
        self.model = model

    async def chat(self, messages, max_tokens: int = 256, temperature: float = 0.2):
        payload = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(self.chat_url, json=payload)
            r.raise_for_status()
            j = r.json()
            return j["choices"][0]["message"]["content"]
