"""FastAPI app — the whole pipeline runtime (§3).

One 256MB Fly machine runs every agent. The only things outside it are the
GitHub Actions cron that pokes /batch/run, Supabase, the Vercel dashboard and
the Chrome extension.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import NotConfigured, get_db
from .llm.base import QuotaExhausted
from .mailer import DailyCapReached
from .routes import batch, chaser, extension, health, packages, stats

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("job_agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    log.info(
        "job-agent starting: env=%s db=%s llm=%s embeddings=%s",
        settings.environment,
        "configured" if settings.configured else "MISSING",
        "configured" if settings.llm_configured else "MISSING",
        settings.embedding_provider,
    )
    yield
    await get_db().aclose()


app = FastAPI(
    title="job-agent",
    version="0.1.0",
    description=(
        "Autonomous job search. Agents draft; nothing with the user's name on it "
        "leaves without an explicit approval."
    ),
    lifespan=lifespan,
)

# The dashboard is the only browser origin that talks to this API, and it does
# so from its server actions. Extension calls carry the agent key too.
_origins = [o for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["X-Agent-Key", "Content-Type"],
)

app.include_router(health.router)
app.include_router(stats.router)
app.include_router(batch.router)
app.include_router(packages.router)
app.include_router(extension.router)
app.include_router(chaser.router)


@app.exception_handler(NotConfigured)
async def _not_configured(_, exc: NotConfigured) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(QuotaExhausted)
async def _quota(_, exc: QuotaExhausted) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": str(exc), "kind": "llm_budget"})


@app.exception_handler(DailyCapReached)
async def _cap(_, exc: DailyCapReached) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": str(exc), "kind": "daily_cap"})


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"service": "job-agent", "docs": "/docs", "health": "/health"}
