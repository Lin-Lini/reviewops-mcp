from __future__ import annotations

import json
import re
from difflib import SequenceMatcher


def norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9а-я-]+", norm(s))


def _j(s: str) -> dict | None:
    if not s:
        return None
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def _score_item(item: str, msg: str) -> float:
    ni = norm(item)
    nm = norm(msg)
    if not ni:
        return 0.0
    if ni in nm:
        return 2.0
    mt = tokens(msg)
    it = tokens(item)

    sc = _sim(item, msg) * 0.7
    for t in it:
        if len(t) < 3:
            continue
        pref = t[: max(4, len(t) - 2)]
        for w in mt:
            if w.startswith(pref):
                sc = max(sc, 1.15)
    return sc


def _shortlist(msg: str, items: list[str], k: int) -> list[str]:
    if not items:
        return []
    scored = [(_score_item(x, msg), x) for x in items]
    scored.sort(key=lambda t: t[0], reverse=True)
    out = []
    for s, x in scored:
        if s < 0.25:
            break
        out.append(x)
        if len(out) >= k:
            break
    return out or items[:k]


def _best(x: str | None, items: list[str], th: float = 0.78) -> str | None:
    if not x:
        return None
    nx = norm(x)

    for it in items:
        if norm(it) == nx:
            return it

    best = None
    bs = 0.0
    for it in items:
        s = _sim(x, it)
        if s > bs:
            bs = s
            best = it

    return best if best and bs >= th else None


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
    for r in regions:
        if norm(r) in m:
            return r

    for r in regions:
        rt = tokens(r)
        for t in rt:
            if len(t) < 4:
                continue
            pref = t[: max(4, len(t) - 2)]
            for w in mt:
                if w.startswith(pref):
                    return r

    return None


async def pick_filters_with_llm(llm, msg: str, rubrics: list[str], regions: list[str]):
    rbs = _shortlist(msg, rubrics, k=80)
    regs = _shortlist(msg, regions, k=140)

    sys = (
        "Ты приводишь фильтры к каноническому виду.\n"
        "Верни ТОЛЬКО JSON: {\"rubric\": <строка или null>, \"a0\": <строка или null>}.\n"
        "Правила:\n"
        "- rubric: именительный падеж, единственное число, как в справочнике рубрик.\n"
        "- a0: регион РФ (субъект), именительный падеж, как в справочнике регионов.\n"
        "- Если в запросе словоформы (\"в Москве\", \"в Питере\", \"по краснодарскому краю\"), "
        "преобразуй в канон (\"Москва\", \"Санкт-Петербург\", \"Краснодарский край\").\n"
        "- Не выдумывай: если не уверен, ставь null.\n"
        "Примеры:\n"
        "Запрос: \"негатив по кафе в москве\" -> {\"rubric\":\"Кафе\",\"a0\":\"Москва\"}\n"
        "Запрос: \"жалобы на рестораны в питере\" -> {\"rubric\":\"Ресторан\",\"a0\":\"Санкт-Петербург\"}\n"
        "Запрос: \"проблемы в магазинах продуктов по краснодарскому краю\" -> "
        "{\"rubric\":\"Магазин продуктов\",\"a0\":\"Краснодарский край\"}\n"
    )

    user = (
        "Запрос: " + msg +
        "\n\nСправочник рубрик:\n- " + "\n- ".join(rbs) +
        "\n\nСправочник регионов (a0):\n- " + "\n- ".join(regs)
    )

    out = await llm.chat(
        [{"role": "system", "content": sys}, {"role": "user", "content": user}],
        max_tokens=140,
        temperature=0.0,
    )

    j = _j(out) or {}
    rb = j.get("rubric")
    a0 = j.get("a0")

    rb = rb.strip() if isinstance(rb, str) else None
    a0 = a0.strip() if isinstance(a0, str) else None
    rb = rb or None
    a0 = a0 or None

    rb = rb if rb in rubrics else _best(rb, rubrics, th=0.80)
    a0 = a0 if a0 in regions else _best(a0, regions, th=0.80)

    return rb, a0

async def pick_mode_with_llm(llm, msg: str):
    sys = (
        "Ты маршрутизатор запросов.\n"
        "Верни ТОЛЬКО JSON: {\"mode\": \"search|insights|leaders|compare\"}.\n"
        "Правила:\n"
        "- search: если пользователь просит найти/поиск/отзывы по слову.\n"
        "- compare: если просит сравнить (vs, сравни, и т.п.).\n"
        "- leaders: если просит лучшие/худшие/топ/антилидеры.\n"
        "- insights: если просит причины негатива/почему/что улучшить/разбери.\n"
        "Если не уверен — выбери insights."
    )

    user = "Запрос: " + msg

    out = await llm.chat(
        [{"role": "system", "content": sys}, {"role": "user", "content": user}],
        max_tokens=60,
        temperature=0.0,
    )

    j = _j(out) or {}
    mode = j.get("mode")
    mode = mode.strip().lower() if isinstance(mode, str) else None

    if mode not in ("search", "compare", "leaders", "insights"):
        return None
    return mode

async def pick_compare_with_llm(llm, msg: str, rubrics: list[str], regions: list[str]):
    # минимальные алиасы (не “вся Россия”, а популярный сленг)
    m = msg.lower()
    m = m.replace("спб", "санкт-петербург")
    m = m.replace("питер", "санкт-петербург")
    m = m.replace("мск", "москва")
    m = m.replace("екб", "екатеринбург")

    rbs = _shortlist(m, rubrics, k=90)
    regs = _shortlist(m, regions, k=120)

    sys = (
        "Ты маршрутизатор для сравнения.\n"
        "ВЫВЕДИ ТОЛЬКО JSON без текста вокруг.\n"
        "Формат строго: {\"rubric\": <строка или null>, \"a0_1\": <строка>, \"a0_2\": <строка>}.\n"
        "a0_1 и a0_2 должны быть РАЗНЫЕ.\n"
        "a0_1 и a0_2 должны быть В ТОЧНОСТИ ОДНОЙ СТРОКОЙ ИЗ СПРАВОЧНИКА регионов ниже (копируй строку).\n"
        "Если пользователь написал сленг (например 'питер', 'спб', 'мск'), выбери каноническое значение из списка.\n"
        "Если не уверен в rubric, ставь null.\n"
        "Если в запросе явно упомянуты 1–2 региона, выбери их. Иначе выбери два самых вероятных из списка.\n"
    )

    user = (
        "Запрос: " + m +
        "\n\nСправочник рубрик (строго эти значения):\n- " + "\n- ".join(rbs) +
        "\n\nСправочник регионов (a0) (строго эти значения):\n- " + "\n- ".join(regs)
    )

    out = await llm.chat(
        [{"role": "system", "content": sys}, {"role": "user", "content": user}],
        max_tokens=180,
        temperature=0.0,
    )

    j = _j(out) or {}
    rb = j.get("rubric")
    a1 = j.get("a0_1")
    a2 = j.get("a0_2")

    rb = rb.strip() if isinstance(rb, str) else None
    a1 = a1.strip() if isinstance(a1, str) else None
    a2 = a2.strip() if isinstance(a2, str) else None

    # 1) если LLM вернула ровно из shortlist — отлично
    rb = rb if rb in rubrics else _best(rb, rubrics, th=0.78)
    a1 = a1 if a1 in regions else _best(a1, regions, th=0.72)
    a2 = a2 if a2 in regions else _best(a2, regions, th=0.72)

    # 2) если всё ещё не вышло — fallback на топ-2 из shortlist регионов
    # (это лучше, чем None/None и 2x 130 секунд)
    if (not a1 or not a2) and len(regs) >= 2:
        a1 = a1 or regs[0]
        a2 = a2 or regs[1]

    if not a1 or not a2 or a1 == a2:
        return rb, None, None

    return rb, a1, a2
