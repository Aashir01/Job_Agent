"""Chrome extension endpoints (§3, §6 source 4).

Two jobs. It hands the extension approved packages to fill into a career page
inside the user's own session, and it accepts LinkedIn/Indeed postings the user
happened to browse past. Nothing here scrapes anything server-side, and nothing
here submits: the extension fills, the user clicks the site's own Submit (§10).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl

from ..db import Database, get_db
from ..security import require_agent_key

log = logging.getLogger(__name__)
router = APIRouter(prefix="/extension", tags=["extension"], dependencies=[Depends(require_agent_key)])


class QueueStatus(BaseModel):
    status: Literal["filled", "submitted", "abandoned"]
    note: str | None = Field(None, max_length=500)


class Sighting(BaseModel):
    source: Literal["linkedin", "indeed"]
    source_url: HttpUrl
    title: str = Field(..., max_length=300)
    company_name: str = Field("", max_length=200)
    location_raw: str = Field("", max_length=300)


class SightingBatch(BaseModel):
    sightings: list[Sighting] = Field(..., max_length=50)


@router.get("/queue/next")
async def next_in_queue(db: Database = Depends(get_db)) -> dict:
    """Hand over one pending fill job and mark it claimed."""
    rows = await db.select(
        "extension_queue", eq={"status": "pending"}, order="created_at.asc", limit=1
    )
    if not rows:
        return {"item": None}
    item = rows[0]
    await db.update(
        "extension_queue",
        {"status": "claimed", "claimed_at": datetime.now(timezone.utc).isoformat()},
        eq={"id": item["id"]},
        returning=False,
    )
    # Never hand the extension anything that would let it submit on its own.
    payload = dict(item.get("payload") or {})
    payload["autosubmit"] = False
    return {"item": {"id": item["id"], "target_url": item["target_url"], "payload": payload}}


@router.get("/queue")
async def list_queue(
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, le=200),
    db: Database = Depends(get_db),
) -> dict:
    """The extension itself only ever claims /next; this list is the dashboard's
    monitor, so it returns every status when no filter is given."""
    filters = {"status": status_filter} if status_filter else None
    rows = await db.select(
        "extension_queue",
        columns="*,packages(tier,jobs(title,companies(name)))",
        eq=filters,
        order="created_at.desc",
        limit=limit,
    )
    return {"items": rows}


@router.post("/queue/{item_id}/status")
async def update_queue_item(item_id: str, body: QueueStatus, db: Database = Depends(get_db)) -> dict:
    item = await db.select_one("extension_queue", eq={"id": item_id})
    if not item:
        raise HTTPException(404, "no such queue item")

    patch = {"status": body.status}
    if body.status in ("submitted", "abandoned"):
        patch["completed_at"] = datetime.now(timezone.utc).isoformat()
    await db.update("extension_queue", patch, eq={"id": item_id}, returning=False)

    # "submitted" here means the user clicked the site's Submit button, which is
    # the only thing that makes an application real.
    if body.status == "submitted" and item.get("package_id"):
        await db.update(
            "packages", {"status": "submitted"}, eq={"id": item["package_id"]}, returning=False
        )
    elif body.status == "abandoned" and item.get("package_id"):
        await db.update(
            "packages", {"status": "approved"}, eq={"id": item["package_id"]}, returning=False
        )
    return {"ok": True, "status": body.status}


@router.post("/sightings")
async def record_sightings(body: SightingBatch, db: Database = Depends(get_db)) -> dict:
    """Discovery only. A sighting is a URL and a title the user already saw in
    their own browser — it is never fetched, expanded or enriched server-side."""
    rows = [
        {
            "source": s.source,
            "source_url": str(s.source_url),
            "title": s.title,
            "company_name": s.company_name,
            "location_raw": s.location_raw,
        }
        for s in body.sightings
    ]
    if not rows:
        return {"recorded": 0}
    stored = await db.insert(
        "passive_sightings", rows, upsert=True, on_conflict="source_url", ignore_duplicates=True
    )
    return {"recorded": len(stored), "submitted": len(rows)}


@router.get("/profile")
async def fill_profile(db: Database = Depends(get_db)) -> dict:
    """The field map the content script fills career-page forms from."""
    profile = await db.select_one("profile", limit=1)
    if not profile:
        raise HTTPException(404, "no profile row")
    return {
        "full_name": profile.get("full_name"),
        "location": profile.get("location"),
        "links": profile.get("links") or {},
        "work_auth": profile.get("work_auth") or {},
    }
