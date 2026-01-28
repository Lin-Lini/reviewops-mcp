from typing import List, Literal, Optional, Dict, Any, Tuple
from pydantic import BaseModel, Field


Phase = Literal["input", "output"]


class Match(BaseModel):
    category: str
    pattern: str
    span: Tuple[int, int]
    excerpt: str


class ModerateRequest(BaseModel):
    # Универсальный формат. Если придёт «старый» формат — подхватим в main.py.
    phase: Phase = Field(default="input", description="input|output")
    text: str = Field(..., description="Текст для модерации")
    # Для проверки утечки системного промпта на выходе (опционально)
    system_prompt: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ModerateResult(BaseModel):
    action: Literal["allow", "redact", "block"]
    reasons: List[str] = []
    matches: List[Match] = []
    redacted_text: Optional[str] = None