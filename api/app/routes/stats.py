"""Dashboard overview: one round-trip for the home strip (§7).

PostgREST cannot GROUP BY, and at this system's scale it does not need to —
the heaviest select below is bounded at 1000 rows and everything is counted
in Python.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from ..db import Database, get_db
from ..security import require_agent_key

router = APIRouter(tags=["stats"], dependencies=[Depends(require_agent_key)])

_TIERS = ("fast_lane", "standard", "marginal")


@router.get("/stats/overview")
async def overview(db: Database = Depends(get_db)) -> dict:
    today = datetime.now(timezone.utc).date()
    llm_since = (today - timedelta(days=13)).isoformat()
    decisions_since = (today - timedelta(days=29)).isoformat()

    queued, applications, outreach_due, ext_queue, latest_batch, llm_recent, decisions = (
        await db.select("packages", columns="id,tier", eq={"status": "queued"}, limit=500),
        await db.select("applications", columns="id,status", limit=500),
        await db.select(
            "outreach",
            columns="id",
            not_null=("due_at",),
            is_null=("sent_at", "approved_at"),
            limit=200,
        ),
        await db.select("extension_queue", columns="id,status", limit=200),
        await db.select("batches", order="started_at.desc", limit=1),
        # 300 calls/batch × 2 batches/day × 14 days can exceed PostgREST's
        # 1000-row page. The sparkline is a trend; a truncated tail is fine.
        await db.select(
            "llm_calls",
            columns="created_at,cost_usd,ok",
            gte={"created_at": f"{llm_since}T00:00:00Z"},
            order="created_at.asc",
            limit=1000,
        ),
        await db.select(
            "decisions",
            columns="verdict",
            gte={"decided_at": f"{decisions_since}T00:00:00Z"},
            limit=1000,
        ),
    )

    queue: dict[str, int] = {tier: 0 for tier in _TIERS}
    for row in queued:
        tier = row.get("tier") if row.get("tier") in queue else "untiered"
        queue[tier] = queue.get(tier, 0) + 1

    funnel: dict[str, int] = {}
    for row in applications:
        status = row.get("status") or "unknown"
        funnel[status] = funnel.get(status, 0) + 1

    extension: dict[str, int] = {}
    for row in ext_queue:
        status = row.get("status") or "unknown"
        extension[status] = extension.get(status, 0) + 1

    llm_daily = [
        {"day": (today - timedelta(days=offset)).isoformat(), "calls": 0, "cost_usd": 0.0}
        for offset in range(13, -1, -1)
    ]
    by_day = {point["day"]: point for point in llm_daily}
    for call in llm_recent:
        day = (call.get("created_at") or "")[:10]
        point = by_day.get(day)
        if point is None:
            continue
        point["calls"] += 1
        point["cost_usd"] = round(point["cost_usd"] + float(call.get("cost_usd") or 0), 6)

    verdicts: dict[str, int] = {}
    for row in decisions:
        verdict = row.get("verdict") or "unknown"
        verdicts[verdict] = verdicts.get(verdict, 0) + 1

    return {
        "day": today.isoformat(),
        "queue": {"total": len(queued), "by_tier": queue},
        "funnel": funnel,
        "applications_total": len(applications),
        "outreach_due": len(outreach_due),
        "extension_queue": extension,
        "latest_batch": latest_batch[0] if latest_batch else None,
        "llm_daily": llm_daily,
        "decisions_30d": verdicts,
    }
