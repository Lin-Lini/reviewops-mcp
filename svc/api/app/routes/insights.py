from __future__ import annotations

from fastapi import APIRouter
from ..db import fetch_all, fetch_one

router = APIRouter()

STOP_TERMS = {
    "очень","просто","только","когда","после","больше","место","время","итоге","сегодня",
    "потом","ничего","вообще","можно","через","этого","такие","такое","который","сразу",
}
STOP_BIGRAMS = {
    "потому что","того что","никто не","ничего не","при этом","как будто","в итоге",
    "первый раз","к сожалению","вообще не","это место","это заведение","данное заведение",
}

ASPECTS = [
    ("Ожидание и скорость", ["минут","ждали","долго","ожид","через","40 минут","30 минут","20 минут","10 минут","15 минут"]),
    ("Обслуживание и персонал", ["обслуживание","официант","официанты","персонал","хамств","груб","кассир","бариста"]),
    ("Качество еды", ["вкусно","невкусно","блюда","еда","холод","пресн","паста","пицц","картошка","фри","мяс"]),
    ("Цена и ценность", ["руб","дорог","цена","деньги","счет","стоимост"]),
    ("Заказ и ошибки", ["заказ","принесли","перепут","не принесли","ожидание заказа","доставка"]),
]

def _filter_terms(items: list[dict], n: int) -> list[dict]:
    out: list[dict] = []
    for it in items:
        w = (it.get("w") or "").strip()
        if not w or w in STOP_TERMS:
            continue
        out.append(it)
        if len(out) >= n:
            break
    return out

def _filter_bigrams(items: list[dict], n: int) -> list[dict]:
    out: list[dict] = []
    for it in items:
        g = (it.get("g") or "").strip()
        if not g or g in STOP_BIGRAMS:
            continue
        out.append(it)
        if len(out) >= n:
            break
    return out

def _build_reasons(terms: list[dict], bigrams: list[dict], top_k: int = 5) -> list[dict]:
    reasons: list[dict] = []
    for label, keys in ASPECTS:
        score = 0
        evidence: list[str] = []
        for it in bigrams:
            g = it.get("g") or ""
            for k in keys:
                if k in g:
                    score += int(it.get("cnt") or 0)
                    if g not in evidence:
                        evidence.append(g)
                    break
        for it in terms:
            w = it.get("w") or ""
            for k in keys:
                if k in w:
                    score += int(it.get("cnt") or 0)
                    if w not in evidence:
                        evidence.append(w)
                    break
        if score > 0:
            reasons.append({"label": label, "score": score, "evidence": evidence[:3]})
    reasons.sort(key=lambda x: x["score"], reverse=True)
    return reasons[:top_k]

@router.get("/insights/negative")
def negative_insights(
    rubric: str,
    a0: str | None = None,
    a1: str | None = None,
    n_terms: int = 30,
    n_samples: int = 10,
    max_docs: int = 5000,
):
    # total stats (fast)
    w_total = ["%s = ANY(o.rub)", "r.rating <> 0"]
    args_total = [rubric]
    if a0:
        w_total.append("o.a0 = %s")
        args_total.append(a0)
    if a1:
        w_total.append("o.a1 = %s")
        args_total.append(a1)
    where_total = " AND ".join(w_total)

    total_stats = fetch_one(
        f"""
        SELECT
          count(*)::int as total_reviews,
          avg(NULLIF(r.rating,0))::float as avg_rating_all,
          sum((r.rating<=2)::int)::int as bad_reviews,
          sum((r.rating=5)::int)::int as good_reviews
        FROM rev r
        JOIN org o USING(org_key)
        WHERE {where_total}
        """,
        tuple(args_total),
    ) or {}

    # negative slice (docs)
    w = ["%s = ANY(o.rub)", "r.rating BETWEEN 1 AND 2"]
    args = [rubric]
    if a0:
        w.append("o.a0 = %s")
        args.append(a0)
    if a1:
        w.append("o.a1 = %s")
        args.append(a1)
    where = " AND ".join(w)

    bad_stats = fetch_one(
        f"""
        SELECT
          count(*)::int as reviews,
          avg(NULLIF(r.rating,0))::float as avg_rating,
          sum((r.rating<=2)::int)::int as bad
        FROM rev r
        JOIN org o USING(org_key)
        WHERE {where}
        """,
        tuple(args),
    ) or {}

    docs_sql = f"""
    WITH docs AS (
      SELECT r.rev_id, r.text, r.rating, o.name_ru, o.address
      FROM rev r
      JOIN org o USING(org_key)
      WHERE {where}
      ORDER BY r.rating ASC
      LIMIT %s
    )
    """

    terms = fetch_all(
        docs_sql + """
        SELECT w, count(*)::int as cnt
        FROM (
          SELECT unnest(regexp_split_to_array(
            regexp_replace(lower(text), '[^а-яa-z0-9 ]+', ' ', 'g'),
            '\\s+'
          )) AS w
          FROM docs
        ) t
        WHERE length(w) >= 4
        GROUP BY w
        ORDER BY cnt DESC
        LIMIT %s
        """,
        tuple(args + [max_docs, n_terms]),
    )

    bigrams = fetch_all(
        docs_sql + """
        , toks AS (
          SELECT
            regexp_split_to_array(
              regexp_replace(lower(text), '[^а-яa-z0-9 ]+', ' ', 'g'),
              '\\s+'
            ) AS a
          FROM docs
        ),
        bg AS (
          SELECT (a[i] || ' ' || a[i+1]) AS g
          FROM toks, generate_subscripts(a, 1) AS i
          WHERE i < array_length(a, 1)
        )
        SELECT g, count(*)::int as cnt
        FROM bg
        WHERE length(g) >= 6
        GROUP BY g
        ORDER BY cnt DESC
        LIMIT %s
        """,
        tuple(args + [max_docs, n_terms]),
    )

    samples = fetch_all(
        docs_sql + """
        SELECT rev_id, rating, name_ru, address, left(text, 600) as text
        FROM docs
        LIMIT %s
        """,
        tuple(args + [max_docs, n_samples]),
    )

    f_terms = _filter_terms(terms, n_terms)
    f_bigrams = _filter_bigrams(bigrams, n_terms)
    reasons = _build_reasons(f_terms, f_bigrams, top_k=5)

    return {
        "filters": {"rubric": rubric, "a0": a0, "a1": a1},
        "stats": {"total": total_stats, "negative": bad_stats},
        "reasons": reasons,
        "top_terms": f_terms,
        "top_bigrams": f_bigrams,
        "samples": samples,
        "max_docs": max_docs,
    }
