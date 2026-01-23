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
