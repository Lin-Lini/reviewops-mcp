from fastapi import APIRouter
from ..db import fetch_all

router = APIRouter()

@router.get("/search/text")
def txt_search(qs: str, n: int = 20):
    s = qs.strip()
    return fetch_all(
        "SELECT rev_id, org_key, rating, "
        "ts_headline('russian', text, plainto_tsquery('russian', %s)) as snip "
        "FROM rev "
        "WHERE tsv @@ plainto_tsquery('russian', %s) "
        "LIMIT %s",
        (s, s, n)
    )
