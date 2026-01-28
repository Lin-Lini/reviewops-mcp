from __future__ import annotations

STOP_TERMS = {
    "очень","просто","только","когда","после","больше","место","время","итоге","сегодня",
    "потом","ничего","вообще","можно","через","этого","такие","такое","который","сразу",
}

STOP_BIGRAMS = {
    "потому что","того что","никто не","ничего не","при этом","как будто","в итоге",
    "первый раз","к сожалению","вообще не","это место","это заведение","данное заведение",
}

ASPECTS = [
    ("Ожидание и скорость", ["минут", "ждал", "ожидан", "час", "очеред"]),
    ("Обслуживание/персонал", ["персонал", "официант", "кассир", "сервис", "администратор", "отношен", "хам"]),
    ("Еда/качество", ["блюд", "пицц", "паста", "волос", "невкус", "вкус", "холод", "пресн", "порци"]),
    ("Заказ и ошибки", ["заказ", "принес", "оплат", "позици", "перепут", "доставк"]),
    ("Цены/счёт", ["дорог", "рубл", "цена", "счет", "стоим"]),
]

def filter_terms(terms: list[dict], n: int) -> list[dict]:
    out = []
    for it in terms:
        w = (it.get("w") or "").strip()
        if not w:
            continue
        if w in STOP_TERMS:
            continue
        out.append(it)
        if len(out) >= n:
            break
    return out

def filter_bigrams(bigrams: list[dict], n: int) -> list[dict]:
    out = []
    for it in bigrams:
        g = (it.get("g") or "").strip()
        if not g:
            continue
        if g in STOP_BIGRAMS:
            continue
        out.append(it)
        if len(out) >= n:
            break
    return out

def build_reasons(terms: list[dict], bigrams: list[dict], top_k: int = 5) -> list[dict]:
    reasons: list[dict] = []
    for label, keys in ASPECTS:
        score = 0
        evidence: list[str] = []

        for it in bigrams:
            g = it.get("g") or ""
            cnt = int(it.get("cnt") or 0)
            for k in keys:
                if k in g:
                    score += 2 * max(cnt, 1)
                    evidence.append(g)

        for it in terms:
            w = it.get("w") or ""
            cnt = int(it.get("cnt") or 0)
            for k in keys:
                if k in w:
                    score += 1 * max(cnt, 1)
                    evidence.append(w)

        if score:
            # unique evidence
            seen = set()
            uniq = []
            for e in evidence:
                if e not in seen:
                    seen.add(e)
                    uniq.append(e)
            reasons.append({"label": label, "score": score, "evidence": uniq[:6]})

    reasons.sort(key=lambda x: x["score"], reverse=True)
    return reasons[:top_k]
