"""Batch trigger and history. Called by the GitHub Actions cron (§3, §4)."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query

from ..batch import BatchRunner
from ..config import get_settings
from ..db import Database, get_db
from ..registers.refresh import refresh_all
from ..run_settings import load as load_run_settings, save as save_run_settings
from ..security import require_agent_key

log = logging.getLogger(__name__)
router = APIRouter(prefix="/batch", tags=["batch"], dependencies=[Depends(require_agent_key)])


@router.post("/run")
async def run_batch(
    background: BackgroundTasks,
    kind: str = Query("scheduled", pattern="^(scheduled|manual|backfill)$"),
    skip_scout: bool = Query(False),
    wait: bool = Query(False, description="run inline instead of in the background"),
    payload: dict[str, Any] | None = Body(None),
    db: Database = Depends(get_db),
) -> dict:
    # A body from the run console is saved *before* the run starts, so the same
    # choices also govern the scheduled batches: the cron reads the same row.
    # The cron itself sends no body and keeps using whatever was last saved.
    saved = None
    if payload:
        current = await load_run_settings(db)
        try:
            saved = await save_run_settings(
                db,
                payload.get("platforms", current["platforms"]),
                payload.get("filters", current["filters"]),
            )
        except Exception as exc:
            # A configuration the user just chose must not be silently ignored —
            # running without it would be worse than not running at all.
            raise HTTPException(
                503,
                f"could not save the run configuration ({exc}). Apply "
                "db/migrations/0005_run_settings.sql, or start the run without a body.",
            ) from exc

    runner = BatchRunner(db, get_settings())
    if wait:
        stats = await runner.run(kind=kind, skip_scout=skip_scout)
        return {
            "started": True,
            "completed": True,
            "batch_id": stats.batch_id,
            "stats": stats.as_dict(),
            "settings": saved,
        }

    # The cron job should not hold an HTTP connection for eight minutes.
    background.add_task(runner.run, kind, skip_scout)
    return {"started": True, "completed": False, "kind": kind, "settings": saved}


@router.get("")
async def list_batches(limit: int = Query(20, le=100), db: Database = Depends(get_db)) -> dict:
    rows = await db.select("batches", order="started_at.desc", limit=limit)
    return {"batches": rows}


@router.get("/{batch_id}")
async def get_batch(batch_id: str, db: Database = Depends(get_db)) -> dict:
    row = await db.select_one("batches", eq={"id": batch_id})
    if not row:
        raise HTTPException(404, "no such batch")
    calls = await db.select(
        "llm_calls", columns="agent,provider,cost_usd,ok", eq={"batch_id": batch_id}, limit=1000
    )
    by_agent: dict[str, dict] = {}
    for call in calls:
        entry = by_agent.setdefault(call["agent"], {"calls": 0, "cost_usd": 0.0, "failures": 0})
        entry["calls"] += 1
        entry["cost_usd"] = round(entry["cost_usd"] + float(call.get("cost_usd") or 0), 6)
        entry["failures"] += 0 if call.get("ok") else 1
    return {"batch": row, "llm_by_agent": by_agent}


@router.post("/registers/refresh")
async def refresh_registers(db: Database = Depends(get_db)) -> dict:
    """Weekly. Kept on the batch router because it is machine-triggered too."""
    return {"results": await refresh_all(db, get_settings())}
