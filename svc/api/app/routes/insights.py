from __future__ import annotations

import re
from collections import Counter

from fastapi import APIRouter

from ..db import fetch_all, fetch_one
from ..lib.reasons import filter_terms, filter_bigrams, build_reasons

router = APIRouter()

_NON_ALNUM = re.compile(r"[^а-яa-z0-9 ]+", re.IGNORECASE)
_WORDS4 = re.compile(r"[а-яa-z0-9]{4,}", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    t = (text or "").lower()
    t = _NON_ALNUM.sub(" ", t)
    return _WORDS4.findall(t)


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
    w_total = ["o.rub @> ARRAY[%s]::text[]", "r.rating <> 0"]
    args_total = [rubric]
    if a0:
        w_total.append("o.a0 = %s")
        args_total.append(a0)
    if a1:
        w_total.append("o.a1 = %s")
        args_total.append(a1)
    where_total = " AND ".join(w_total)

    total_stats = (
        fetch_one(
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
        )
        or {}
    )

    w = ["o.rub @> ARRAY[%s]::text[]", "r.rating BETWEEN 1 AND 2"]
    args = [rubric]
    if a0:
        w.append("o.a0 = %s")
        args.append(a0)
    if a1:
        w.append("o.a1 = %s")
        args.append(a1)
    where = " AND ".join(w)

    bad_stats = (
        fetch_one(
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
        )
        or {}
    )

    TEXT_LIMIT = 800
    docs = fetch_all(
        f"""
        WITH docs AS (
          SELECT r.rev_id, left(r.text, %s) as text, r.rating, o.name_ru, o.address
          FROM rev r
          JOIN org o USING(org_key)
          WHERE {where}
          ORDER BY r.rating ASC
          LIMIT %s
        )
        SELECT rev_id, rating, name_ru, address, text
        FROM docs
        """,
        tuple([TEXT_LIMIT] + args + [max_docs]),
    )

    term_cnt: Counter[str] = Counter()
    bigram_cnt: Counter[str] = Counter()

    for d in docs:
        toks = _tokenize(d.get("text") or "")
        if not toks:
            continue
        term_cnt.update(toks)
        for i in range(len(toks) - 1):
            bigram_cnt[f"{toks[i]} {toks[i+1]}"] += 1

    terms_raw = [{"w": w, "cnt": int(c)} for w, c in term_cnt.most_common(max(n_terms * 25, 250))]
    bigrams_raw = [{"g": g, "cnt": int(c)} for g, c in bigram_cnt.most_common(max(n_terms * 35, 400))]

    f_terms = filter_terms(terms_raw, n_terms)
    f_bigrams = filter_bigrams(bigrams_raw, n_terms)
    reasons = build_reasons(f_terms, f_bigrams, top_k=5)

    samples = []
    for d in docs[: max(n_samples, 0)]:
        txt = (d.get("text") or "")[:600]
        samples.append(
            {
                "rev_id": d.get("rev_id"),
                "rating": d.get("rating"),
                "name_ru": d.get("name_ru"),
                "address": d.get("address"),
                "text": txt,
            }
        )

    return {
        "filters": {"rubric": rubric, "a0": a0, "a1": a1},
        "stats": {"total": total_stats, "negative": bad_stats},
        "reasons": reasons,
        "top_terms": f_terms,
        "top_bigrams": f_bigrams,
        "samples": samples,
        "max_docs": max_docs,
    }
