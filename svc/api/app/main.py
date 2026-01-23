from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI

from .settings import get_settings
from .db import init_pool, close_pool
from .routes.meta import router as meta_router
from .routes.org import router as org_router
from .routes.search import router as search_router
from .routes.insights import router as insights_router
from .routes.leaders import router as leaders_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    init_pool(s.db_dsn)
    yield
    close_pool()

app = FastAPI(lifespan=lifespan, title="reviewops-api", version="0.2.0")

app.include_router(meta_router, tags=["meta"])
app.include_router(org_router, tags=["org"])
app.include_router(search_router, tags=["search"])
app.include_router(insights_router, tags=["insights"])
app.include_router(leaders_router, tags=["leaders"])