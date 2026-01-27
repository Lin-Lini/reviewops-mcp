from fastapi import APIRouter, Query
from ..db import fetch_all, fetch_one

router = APIRouter()

@router.get("/org/search")
def org_search(qs: str = Query(..., min_length=1), n: int = 20):
    s = qs.strip()
    return fetch_all(
        "SELECT org_key, name_ru, address "
        "FROM org "
        "WHERE name_ru %% %s OR address %% %s "
        "ORDER BY greatest(similarity(name_ru,%s), similarity(address,%s)) DESC "
        "LIMIT %s",
        (s, s, s, s, n)
    )

@router.get("/org/{org_key}")
def org_one(org_key: str):
    o = fetch_one(
        "SELECT org_key, name_ru, address, a0, a1, rub "
        "FROM org WHERE org_key=%s",
        (org_key,)
    )
    if not o:
        return None
    st = fetch_one(
        "SELECT count(*)::int as n, avg(NULLIF(rating,0))::float as avg, "
        "sum((rating<=2)::int)::int as bad, sum((rating=5)::int)::int as good "
        "FROM rev WHERE org_key=%s",
        (org_key,)
    )
    return {"org": o, "stats": st}

@router.get("/org/{org_key}/reviews")
def org_reviews(org_key: str, rmin: int = 0, rmax: int = 5, n: int = 50):
    return fetch_all(
        "SELECT rev_id, rating, text FROM rev "
        "WHERE org_key=%s AND rating BETWEEN %s AND %s "
        "ORDER BY rating ASC LIMIT %s",
        (org_key, rmin, rmax, n)
    )

@router.get("/org/{org_key}/insights/negative")
def org_negative_insights(
    org_key: str,
    n_terms: int = Query(20, ge=1, le=200),
    n_samples: int = Query(5, ge=1, le=50),
    max_docs: int = Query(3000, ge=100, le=20000),
):
    stats = fetch_one(
        """
        SELECT
          count(*)::int as reviews,
          avg(NULLIF(r.rating,0))::float as avg_rating,
          sum((r.rating<=2)::int)::int as bad
        FROM rev r
        WHERE r.org_key = %s AND r.rating BETWEEN 1 AND 2
        """,
        (org_key,)
    ) or {"reviews": 0, "avg_rating": None, "bad": 0}

    docs_sql = """
    WITH docs AS (
      SELECT rev_id, text, rating
      FROM rev
      WHERE org_key = %s AND rating BETWEEN 1 AND 2
      ORDER BY rating ASC
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
        WHERE length(w) >= 5
        GROUP BY w
        ORDER BY cnt DESC
        LIMIT %s
        """,
        (org_key, max_docs, n_terms)
    )

    bigrams = fetch_all(
        docs_sql + """
        , toks AS (
          SELECT regexp_split_to_array(
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
        WHERE length(g) >= 8
        GROUP BY g
        ORDER BY cnt DESC
        LIMIT %s
        """,
        (org_key, max_docs, n_terms)
    )

    samples = fetch_all(
        docs_sql + """
        SELECT rev_id, rating, left(text, 600) as text
        FROM docs
        LIMIT %s
        """,
        (org_key, max_docs, n_samples)
    )

    return {
        "filters": {"org_key": org_key},
        "stats": stats,
        "top_terms": terms,
        "top_bigrams": bigrams,
        "samples": samples,
        "max_docs": max_docs,
    }
