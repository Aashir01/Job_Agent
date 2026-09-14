"""Follow-ups, reply tracking and the interview dossier (§6 Chaser)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..agents.chaser import Chaser
from ..config import get_settings
from ..db import Database, get_db
from ..llm.router import LLMRouter
from ..security import require_agent_key

router = APIRouter(tags=["chaser"], dependencies=[Depends(require_agent_key)])


class OutreachApproval(BaseModel):
    body: str | None = Field(None, max_length=4000, description="edited text, if the user changed it")
    send_now: bool = True


@router.post("/chaser/run")
async def run_chaser(db: Database = Depends(get_db)) -> dict:
    """Cadence work only. Drafts become *due*; they do not become *sent*."""
    settings = get_settings()
    chaser = Chaser(db, LLMRouter(settings, db), settings)
    queued = await chaser.queue_due_follow_ups()
    replies = await chaser.poll_replies()
    ghosted = await chaser.mark_ghosted(settings.ghost_after_days)
    return {
        "follow_ups_now_due": queued,
        "replies": replies.as_dict(),
        "marked_ghosted": ghosted,
        "note": "due follow-ups wait for per-send content approval before anything is sent",
    }


@router.get("/outreach/due")
async def due_outreach(db: Database = Depends(get_db)) -> dict:
    pending = await db.select(
        "outreach",
        columns="*,contacts(name,email,email_confidence),applications(package_id,status)",
        not_null=("due_at",),
        is_null=("sent_at", "approved_at"),
        order="due_at.asc",
        limit=100,
    )
    return {"due": pending, "total": len(pending)}


@router.post("/outreach/{outreach_id}/approve")
async def approve_outreach(
    outreach_id: str, body: OutreachApproval, db: Database = Depends(get_db)
) -> dict:
    """§6: the cadence was pre-approved; this is the per-send content approval."""
    note = await db.select_one("outreach", eq={"id": outreach_id})
    if not note:
        raise HTTPException(404, "no such outreach row")
    if note.get("sent_at"):
        raise HTTPException(409, "already sent")

    patch = {"approved_at": datetime.now(timezone.utc).isoformat()}
    if body.body:
        patch["body"] = body.body
    await db.update("outreach", patch, eq={"id": outreach_id}, returning=False)

    if not body.send_now:
        return {"ok": True, "approved": True, "sent": 0}

    settings = get_settings()
    sent, errors = await Chaser(db, None, settings).send_approved()
    return {"ok": True, "approved": True, "sent": sent, "errors": errors}


@router.get("/applications")
async def list_applications(
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(100, le=300),
    db: Database = Depends(get_db),
) -> dict:
    filters = {"status": status_filter} if status_filter else None
    rows = await db.select(
        "applications",
        columns="*,packages(tier,fit_score,jobs(title,source_url,track,companies(name)))",
        eq=filters,
        order="submitted_at.desc",
        limit=limit,
    )
    funnel: dict[str, int] = {}
    for row in rows:
        funnel[row.get("status") or "unknown"] = funnel.get(row.get("status") or "unknown", 0) + 1
    return {"applications": rows, "funnel": funnel}


@router.get("/applications/{application_id}/dossier")
async def get_dossier(application_id: str, db: Database = Depends(get_db)) -> dict:
    row = await db.select_one("dossiers", eq={"application_id": application_id})
    if not row:
        raise HTTPException(404, "no dossier yet — one is generated when a reply lands")
    return row
