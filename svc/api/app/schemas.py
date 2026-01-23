from __future__ import annotations
from pydantic import BaseModel
from typing import Any

class HealthOut(BaseModel):
    ok: bool = True

class RubricItem(BaseModel):
    rubric: str
    cnt: int

class RegionItem(BaseModel):
    a0: str
    cnt: int

class OrgSearchItem(BaseModel):
    org_key: str
    name_ru: str
    address: str

class OrgCard(BaseModel):
    org_key: str
    name_ru: str
    address: str
    a0: str | None = None
    a1: str | None = None
    rub: list[str]

class OrgStats(BaseModel):
    n: int
    avg: float | None = None
    bad: int
    good: int

class OrgOneOut(BaseModel):
    org: OrgCard
    stats: OrgStats

class ReviewItem(BaseModel):
    rev_id: str
    rating: int
    text: str

class TextSearchItem(BaseModel):
    rev_id: str
    org_key: str
    rating: int
    snip: str

class InsightReason(BaseModel):
    label: str
    score: int
    evidence: list[str]

class InsightOut(BaseModel):
    filters: dict[str, Any]
    stats: dict[str, Any]
    reasons: list[InsightReason]
    top_terms: list[dict]
    top_bigrams: list[dict]
    samples: list[dict]
    max_docs: int
