"""The review queue and the human gate (§1, §7).

Approving is the only path to submission. It sets the status and then calls the
Courier inline, so there is exactly one place in the system where an outbound
action begins, and it is behind a click.
"""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..agents.courier import Courier, NotApproved
from ..config import get_settings
from ..db import Database, get_db
from ..security import require_agent_key

log = logging.getLogger(__name__)
router = APIRouter(prefix="/packages", tags=["packages"], dependencies=[Depends(require_agent_key)])

REVIEWABLE = ("draft", "queued")
TIER_ORDER = {"fast_lane": 0, "standard": 1, "marginal": 2}


class RejectBody(BaseModel):
    reason: str = Field("", max_length=500)
    reason_code: str | None = Field(None, max_length=40)


class ApproveBody(BaseModel):
    submit: bool = Field(True, description="run the Courier immediately")
    send_pre_apply: bool = Field(False, description="also send the drafted pre-apply note")
    edited_fields: list[str] = Field(default_factory=list)


class EditBody(BaseModel):
    cover_letter: str | None = None
    screening_answers: dict[str, Any] | None = None
    outreach_drafts: dict[str, str] | None = None


@router.get("")
async def review_queue(
    tier: Literal["fast_lane", "standard", "marginal"] | None = None,
    status_filter: str = Query("queued", alias="status"),
    limit: int = Query(50, le=200),
    db: Database = Depends(get_db),
) -> dict:
    """§7: one read backs the whole dashboard."""
    filters: dict[str, Any] = {"status": status_filter}
    if tier:
        filters["tier"] = tier
    rows = await db.select(
        "review_queue", eq=filters, order="fit_score.desc,created_at.desc", limit=limit
    )
    rows.sort(key=lambda r: (TIER_ORDER.get(r.get("tier"), 9), -(r.get("fit_score") or 0)))
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.get("tier") or "untiered"] = counts.get(row.get("tier") or "untiered", 0) + 1
    return {"packages": rows, "counts": counts, "total": len(rows)}


@router.get("/{package_id}")
async def get_package(package_id: str, db: Database = Depends(get_db)) -> dict:
    row = await db.select_one("review_queue", eq={"id": package_id})
    if not row:
        raise HTTPException(404, "no such package")
    extras = await db.select_one(
        "packages", columns="outreach_drafts,referral_plan,score_components,warnings",
        eq={"id": package_id},
    )
    return {**row, **(extras or {})}


@router.get("/{package_id}/resume")
async def download_resume(package_id: str, db: Database = Depends(get_db)) -> StreamingResponse:
    """Stream the tailored .docx through the API.

    The `packages` storage bucket is private, so the browser cannot fetch the
    object directly. Everything that touches the service key stays server-side;
    the dashboard proxies this and never sees the key.
    """
    package = await db.select_one("packages", columns="resume_url", eq={"id": package_id})
    if not package or not package.get("resume_url"):
        raise HTTPException(404, "no resume was built for this package")

    row = await db.select_one("review_queue", columns="title,company_name", eq={"id": package_id})
    stem = " ".join(part for part in ((row or {}).get("company_name"), (row or {}).get("title")) if part)
    stem = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-") or "resume"

    settings = get_settings()
    url = (
        f"{settings.supabase_url.rstrip('/')}/storage/v1/object/packages/"
        f"{package['resume_url']}"
    )
    key = settings.supabase_service_key
    resp = await db.client.get(
        url, headers={"apikey": key, "Authorization": f"Bearer {key}"}
    )
    if resp.status_code >= 400:
        raise HTTPException(502, f"resume storage returned {resp.status_code}")

    return StreamingResponse(
        io.BytesIO(resp.content),
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{stem}.docx"',
            "Content-Length": str(len(resp.content)),
        },
    )


@router.patch("/{package_id}")
async def edit_package(package_id: str, body: EditBody, db: Database = Depends(get_db)) -> dict:
    patch = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not patch:
        raise HTTPException(400, "nothing to update")
    rows = await db.update("packages", patch, eq={"id": package_id})
    if not rows:
        raise HTTPException(404, "no such package")
    return {"ok": True, "edited_fields": sorted(patch)}


@router.post("/{package_id}/approve")
async def approve(package_id: str, body: ApproveBody, db: Database = Depends(get_db)) -> dict:
    """The gate. Everything outbound in this system starts on this line."""
    package = await db.select_one("packages", eq={"id": package_id})
    if not package:
        raise HTTPException(404, "no such package")
    if package["status"] not in REVIEWABLE:
        raise HTTPException(409, f"package is '{package['status']}' and cannot be approved")

    await db.update("packages", {"status": "approved"}, eq={"id": package_id}, returning=False)
    await _record_decision(db, package_id, "approved", "", body.edited_fields)

    if not body.submit:
        return {"ok": True, "status": "approved", "submitted": False}

    courier = Courier(db, get_settings())
    try:
        result = await courier.submit(package_id)
    except NotApproved as exc:
        raise HTTPException(409, str(exc)) from exc

    if result.ok and body.send_pre_apply and result.application_id:
        await _materialise_outreach(db, package, result.application_id)
        await courier.send_pre_apply(result.application_id)
    elif result.ok and result.application_id:
        await _materialise_outreach(db, package, result.application_id)

    return {
        "ok": result.ok,
        "status": "submitted" if result.ok else "failed",
        "method": result.method,
        "detail": result.detail,
        "application_id": result.application_id,
    }


@router.post("/{package_id}/reject")
async def reject(package_id: str, body: RejectBody, db: Database = Depends(get_db)) -> dict:
    package = await db.select_one("packages", eq={"id": package_id})
    if not package:
        raise HTTPException(404, "no such package")
    if package["status"] not in REVIEWABLE:
        raise HTTPException(409, f"package is '{package['status']}' and cannot be rejected")
    await db.update("packages", {"status": "rejected"}, eq={"id": package_id}, returning=False)
    await _record_decision(db, package_id, "rejected", body.reason_code or body.reason, [])
    return {"ok": True, "status": "rejected"}


@router.post("/fast-lane/approve-all")
async def approve_fast_lane(
    submit: bool = Query(True),
    limit: int = Query(20, le=50, description="bounded by the daily extension cap"),
    db: Database = Depends(get_db),
) -> dict:
    """§7: batch approve the entire fast lane with one action.

    Capped, because §10's 20-submissions-a-day limit is the real ceiling and
    hitting it halfway through a batch approve should be visible, not silent.
    """
    rows = await db.select(
        "packages", eq={"status": "queued", "tier": "fast_lane"},
        order="fit_score.desc", limit=limit,
    )
    results = []
    for package in rows:
        await db.update("packages", {"status": "approved"}, eq={"id": package["id"]}, returning=False)
        await _record_decision(db, package["id"], "approved", "fast lane batch approve", [])
        if not submit:
            results.append({"package_id": package["id"], "ok": True, "method": "none"})
            continue
        try:
            result = await Courier(db, get_settings()).submit(package["id"])
            if result.ok and result.application_id:
                await _materialise_outreach(db, package, result.application_id)
            results.append(
                {"package_id": package["id"], "ok": result.ok, "method": result.method,
                 "detail": result.detail}
            )
            if not result.ok and "cap" in result.detail.lower():
                break  # the daily cap is reached; stop rather than pile up failures
        except Exception as exc:
            log.exception("fast lane submit failed for %s", package["id"])
            results.append({"package_id": package["id"], "ok": False, "detail": str(exc)[:200]})
    return {"approved": len(results), "results": results}


async def _record_decision(
    db: Database, package_id: str, verdict: str, reason: str, edited_fields: list[str]
) -> None:
    """§5: every approve/reject trains the scorer."""
    await db.insert(
        "decisions",
        {
            "package_id": package_id,
            "verdict": verdict,
            "reason": reason[:500] or None,
            "edited_fields": edited_fields or None,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        },
        returning=False,
    )


async def _materialise_outreach(db: Database, package: dict, application_id: str) -> None:
    """Turn the Connector's drafts into outreach rows now that an application
    exists to hang them from. They land unsent and unapproved."""
    drafts = package.get("outreach_drafts") or {}
    contact = None
    job = await db.select_one("jobs", columns="company_id", eq={"id": package["job_id"]})
    if job and job.get("company_id"):
        contact = await db.select_one("contacts", eq={"company_id": job["company_id"]})
    rows = [
        {
            "application_id": application_id,
            "contact_id": contact["id"] if contact else None,
            "kind": kind,
            "body": drafts[kind],
            "sent_at": None,
            "approved_at": None,
        }
        for kind in ("pre_apply", "follow_up_1", "follow_up_2")
        if drafts.get(kind)
    ]
    if rows:
        await db.insert("outreach", rows, returning=False)
