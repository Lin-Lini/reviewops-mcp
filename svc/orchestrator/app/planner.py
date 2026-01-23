from __future__ import annotations

import json, re

def norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9а-я-]+", norm(s))

def infer_rubric(msg: str, rubrics: list[str]) -> str | None:
    m = norm(msg)
    for rb in rubrics:
        if norm(rb) in m:
            return rb
    if "кафе" in m:
        return "Кафе"
    return None

def infer_region(msg: str, regions: list[str]) -> str | None:
    mt = tokens(msg)
    if not mt or not regions:
        return None

    m = norm(msg)
    # exact containment first
    for r in regions:
        if norm(r) in m:
            return r

    # prefix match (mоскв- vs москве)
    for r in regions:
        rt = tokens(r)
        for t in rt:
            pref = t[:max(4, len(t) - 2)]
            for w in mt:
                if w.startswith(pref):
                    return r
    return None

async def pick_filters_with_llm(llm, msg: str, rubrics: list[str], regions: list[str]):
    rbs = rubrics[:60]
    regs = regions[:60]

    sys = (
        "Ты маршрутизатор для аналитики отзывов. "
        "Выбери rubric и a0 ТОЛЬКО из списков. "
        "Ответ строго JSON: {\"rubric\": <строка или null>, \"a0\": <строка или null>}."
    )
    user = (
        "Запрос: " + msg +
        "\n\nРубрики:\n- " + "\n- ".join(rbs) +
        "\n\nРегионы:\n- " + "\n- ".join(regs)
    )

    out = await llm.chat(
        [{"role": "system", "content": sys}, {"role": "user", "content": user}],
        max_tokens=80,
        temperature=0.0,
    )

    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None, None

    try:
        j = json.loads(m.group(0))
    except Exception:
        return None, None

    rb = j.get("rubric")
    a0 = j.get("a0")

    if rb is not None and rb not in rubrics:
        rb = None
    if a0 is not None and a0 not in regions:
        a0 = None

    return rb, a0
