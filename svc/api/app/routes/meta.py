from fastapi import APIRouter
from ..db import fetch_all

router = APIRouter()

@router.get("/health")
async def health():
    return {"ok": True}

@router.get("/rubrics/top")
def rubrics_top(n: int = 50):
    return fetch_all(
        "SELECT x as rubric, count(*)::int as cnt "
        "FROM org, unnest(rub) x "
        "GROUP BY x ORDER BY cnt DESC LIMIT %s",
        (n,)
    )

@router.get("/regions/top")
def regions_top(n: int = 50):
    # only for filter selection (fast)
    return fetch_all(
        "SELECT a0, count(*)::int as cnt "
        "FROM org "
        "WHERE a0 IS NOT NULL "
        "GROUP BY a0 "
        "ORDER BY cnt DESC LIMIT %s",
        (n,)
    )
