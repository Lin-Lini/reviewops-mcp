from fastapi import APIRouter, Query
from ..db import fetch_all

router = APIRouter(prefix="/leaders", tags=["leaders"])


@router.get("/worst")
def leaders_worst(
    rubric: str,
    a0: str | None = None,
    min_reviews: int = Query(20, ge=1),
    n: int = Query(20, ge=1, le=200),
):
    w = ["%s = ANY(o.rub)", "r.rating BETWEEN 1 AND 5"]
    args = [rubric]

    if a0:
        w.append("o.a0 = %s")
        args.append(a0)

    where = " AND ".join(w)

    return fetch_all(
        f"""
        SELECT
          o.org_key,
          o.name_ru,
          o.address,
          count(*)::int as reviews,
          avg(NULLIF(r.rating,0))::float as avg_rating,
          sum((r.rating<=2)::int)::int as bad,
          (sum((r.rating<=2)::int)::float / nullif(count(*),0))::float as bad_share
        FROM org o
        JOIN rev r USING(org_key)
        WHERE {where}
        GROUP BY o.org_key, o.name_ru, o.address
        HAVING count(*) >= %s
        ORDER BY avg_rating ASC NULLS LAST, bad_share DESC
        LIMIT %s
        """,
        tuple(args + [min_reviews, n]),
    )


@router.get("/best")
def leaders_best(
    rubric: str,
    a0: str | None = None,
    min_reviews: int = Query(20, ge=1),
    n: int = Query(20, ge=1, le=200),
):
    w = ["o.rub @> ARRAY[%s]::text[]", "r.rating BETWEEN 1 AND 5"]
    args = [rubric]

    if a0:
        w.append("o.a0 = %s")
        args.append(a0)

    where = " AND ".join(w)

    return fetch_all(
        f"""
        SELECT
          o.org_key,
          o.name_ru,
          o.address,
          count(*)::int as reviews,
          avg(NULLIF(r.rating,0))::float as avg_rating,
          sum((r.rating=5)::int)::int as good
        FROM org o
        JOIN rev r USING(org_key)
        WHERE {where}
        GROUP BY o.org_key, o.name_ru, o.address
        HAVING count(*) >= %s
        ORDER BY avg_rating DESC NULLS LAST, reviews DESC
        LIMIT %s
        """,
        tuple(args + [min_reviews, n]),
    )