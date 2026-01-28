from __future__ import annotations

import os, time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from psycopg_pool import ConnectionPool

DB = os.environ["DB"]
pool: ConnectionPool | None = None

class EventIn(BaseModel):
    trace_id: str
    service: str
    event: str
    ts: float | None = None
    payload: dict = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = ConnectionPool(conninfo=DB, min_size=1, max_size=5, open=True)
    yield
    if pool:
        pool.close()

app = FastAPI(lifespan=lifespan, title="reviewops-logsvc", version="0.1.0")

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/event")
def add_event(e: EventIn):
    if pool is None:
        raise HTTPException(status_code=500, detail="pool not ready")
    ts = e.ts if e.ts is not None else time.time()
    with pool.connection() as con:
        with con.cursor() as cur:
            cur.execute(
                "INSERT INTO log_event(trace_id, ts, service, event, payload) VALUES (%s, to_timestamp(%s), %s, %s, %s::jsonb)",
                (e.trace_id, ts, e.service, e.event, __import__("json").dumps(e.payload, ensure_ascii=False)),
            )
    return {"ok": True}

@app.get("/traces/{trace_id}")
def trace(trace_id: str, n: int = 200):
    if pool is None:
        raise HTTPException(status_code=500, detail="pool not ready")
    with pool.connection() as con:
        with con.cursor() as cur:
            cur.execute(
                "SELECT id, trace_id, ts, service, event, payload FROM log_event WHERE trace_id=%s ORDER BY ts ASC LIMIT %s",
                (trace_id, n),
            )
            cols=[c.name for c in cur.description]
            return [dict(zip(cols,row)) for row in cur.fetchall()]

@app.get("/events")
def events(n: int = 200):
    if pool is None:
        raise HTTPException(status_code=500, detail="pool not ready")
    with pool.connection() as con:
        with con.cursor() as cur:
            cur.execute(
                "SELECT id, trace_id, ts, service, event, payload FROM log_event ORDER BY ts DESC LIMIT %s",
                (n,),
            )
            cols=[c.name for c in cur.description]
            return [dict(zip(cols,row)) for row in cur.fetchall()]
