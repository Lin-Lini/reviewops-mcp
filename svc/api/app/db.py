from __future__ import annotations

from typing import Any, Iterable
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None

def init_pool(dsn: str) -> None:
    global _pool
    if _pool is not None:
        return
    _pool = ConnectionPool(conninfo=dsn, min_size=1, max_size=8, open=True)

def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None

def fetch_all(sql: str, args: Iterable[Any] = ()) -> list[dict]:
    if _pool is None:
        raise RuntimeError("DB pool is not initialized")
    with _pool.connection() as con:
        with con.cursor() as cur:
            cur.execute(sql, args)
            if cur.description is None:
                return []
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

def fetch_one(sql: str, args: Iterable[Any] = ()) -> dict | None:
    rows = fetch_all(sql, args)
    return rows[0] if rows else None
