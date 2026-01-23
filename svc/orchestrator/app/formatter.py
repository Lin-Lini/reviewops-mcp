from __future__ import annotations

import re

def clip(s: str, n: int) -> str:
    s = (s or "").replace("\r", " ").replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n].rstrip() + "…"

def compact_context(ins: dict, max_samples: int = 3, sample_len: int = 220) -> dict:
    # Prefer API-provided reasons
    filters = ins.get("filters") or {}
    stats = ins.get("stats") or {}
    reasons = ins.get("reasons") or []
    samples = ins.get("samples") or []

    out = {
        "filters": filters,
        "stats": stats,
        "reasons": reasons[:5],
        "samples": [
            {
                "rating": s.get("rating"),
                "name_ru": s.get("name_ru"),
                "address": s.get("address"),
                "text": clip(s.get("text", ""), sample_len),
            }
            for s in samples[:max_samples]
        ],
    }
    return out

def context_to_text(ctx: dict) -> str:
    f = ctx.get("filters") or {}
    st = ctx.get("stats") or {}
    reasons = ctx.get("reasons") or []
    samples = ctx.get("samples") or []

    lines = []
    lines.append(f"Срез: rub={f.get('rubric')}, a0={f.get('a0')}")

    # stats may have total/negative
    if isinstance(st, dict) and st.get("total") and st.get("negative"):
        t = st["total"]
        n = st["negative"]
        lines.append(f"Всего отзывов: {t.get('total_reviews')}, средняя оценка: {t.get('avg_rating_all')}")
        lines.append(f"Негатив (1-2★): {n.get('reviews')}, средняя негативная: {n.get('avg_rating')}")
    else:
        lines.append(str(st))

    if reasons:
        lines.append("Причины (агрегаты):")
        for i, r in enumerate(reasons[:5], 1):
            ev = ", ".join(r.get("evidence") or [])
            lines.append(f"{i}) {r.get('label')} (score={r.get('score')}): {ev}")

    if samples:
        lines.append("Цитаты:")
        for i, s in enumerate(samples[:3], 1):
            lines.append(f"{i}) ({s.get('rating')}★) {s.get('name_ru')} | {clip(s.get('address',''), 70)}")
            lines.append(f"   «{s.get('text')}»")

    return "\n".join(lines)
