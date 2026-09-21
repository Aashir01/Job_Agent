"""The run console's persisted configuration.

One row: which platforms to poll, and the filters applied to what they return.
Both the dashboard and the scheduled batches read it, so what the user last
chose in the UI is what the 02:00 and 14:00 UTC runs use.

Kept deliberately tolerant. The row may not exist (nothing has been saved yet),
and the table may not exist either (migration 0005 not run) — neither is an
error, both mean "no preferences", and a batch should still run.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .agents.scout.registry import PLATFORM_IDS
from .db import Database

DEFAULTS: dict[str, Any] = {"platforms": [], "filters": {}}

# Ceilings, so a typo in the UI cannot ask for a 500,000-job batch.
MAX_JOBS_CEILING = 2000
LLM_CALLS_CEILING = 2000

_LIST_KEYS = ("locations", "keywords", "exclude_keywords", "seniority")


def clean_platforms(raw: Any) -> list[str]:
    """Keep known ids, in registry order, deduplicated."""
    given = {str(p) for p in (raw or [])}
    return [p for p in PLATFORM_IDS if p in given]


def _clean_list(raw: Any) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(v).strip() for v in raw if str(v).strip()]


def _clean_int(raw: Any, ceiling: int) -> int | None:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return max(1, min(ceiling, value)) if value > 0 else None


def normalise_filters(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Whitelist the known keys and coerce them. Unknown keys are dropped."""
    raw = raw or {}
    filters: dict[str, Any] = {}
    for key in _LIST_KEYS:
        values = _clean_list(raw.get(key))
        if values:
            filters[key] = values
    if raw.get("remote_only"):
        filters["remote_only"] = True
    if (floor := _clean_int(raw.get("salary_floor_usd"), 10_000_000)) is not None:
        filters["salary_floor_usd"] = floor
    if (max_jobs := _clean_int(raw.get("max_jobs"), MAX_JOBS_CEILING)) is not None:
        filters["max_jobs"] = max_jobs
    if (llm_calls := _clean_int(raw.get("llm_calls"), LLM_CALLS_CEILING)) is not None:
        filters["llm_calls"] = llm_calls
    return filters


async def load(db: Database) -> dict[str, Any]:
    """Never raises: a missing row or a missing table both mean 'no preferences'."""
    try:
        row = await db.select_one("run_settings")
    except Exception:
        return dict(DEFAULTS)
    if not row:
        return dict(DEFAULTS)
    return {
        "platforms": clean_platforms(row.get("platforms")),
        "filters": normalise_filters(row.get("filters")),
    }


async def save(db: Database, platforms: Any, filters: Any) -> dict[str, Any]:
    payload = {
        "platforms": clean_platforms(platforms),
        "filters": normalise_filters(filters),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    existing = await db.select_one("run_settings", columns="id")
    if existing:
        await db.update("run_settings", payload, eq={"id": existing["id"]}, returning=False)
    else:
        await db.insert("run_settings", payload, returning=False)
    return {"platforms": payload["platforms"], "filters": payload["filters"]}


def caps(config: dict[str, Any], settings: Any) -> tuple[int, int]:
    """(max jobs for the batch, LLM call budget) — the run's choice, else config."""
    filters = config.get("filters") or {}
    return (
        filters.get("max_jobs") or settings.scout_max_jobs_per_batch,
        filters.get("llm_calls") or settings.llm_calls_per_batch,
    )
