"""Liveness and the quota picture (§8)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from ..config import get_settings
from ..db import Database, get_db
from ..security import require_agent_key

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "ok": True,
        "environment": settings.environment,
        "database_configured": settings.configured,
        "llm_configured": bool(settings.gemini_api_key or settings.groq_api_key),
        "embedding_provider": settings.embedding_provider,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/quota", dependencies=[Depends(require_agent_key)])
async def quota(db: Database = Depends(get_db)) -> dict:
    settings = get_settings()
    today = datetime.now(timezone.utc).date().isoformat()
    counters = await db.select("daily_counters", eq={"day": today})
    ledger = await db.select("quota_ledger", eq={"day": today})
    spend = await db.select(
        "llm_calls", columns="cost_usd,provider,ok", gte={"created_at": f"{today}T00:00:00Z"},
        limit=1000,
    )
    return {
        "day": today,
        "caps": {
            "outbound_email": settings.max_outbound_emails_per_day,
            "extension_submit": settings.max_extension_submits_per_day,
            "llm_calls_per_batch": settings.llm_calls_per_batch,
        },
        "counters": {row["counter"]: row["count"] for row in counters},
        "ledger": {row["resource"]: row["used"] for row in ledger},
        "llm_calls_today": len(spend),
        "llm_failures_today": sum(1 for row in spend if not row.get("ok")),
        "llm_cost_usd_today": round(sum(float(row.get("cost_usd") or 0) for row in spend), 6),
    }
