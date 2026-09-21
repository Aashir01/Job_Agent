"""Setup surface: the profile, the job platforms, and the run's filters (§6, §7).

Everything the dashboard's Setup page needs, so the user can change how the
agents hunt without touching a seed file or a shell. Nothing here submits
anything, and nothing here runs the pipeline — see ``POST /batch/run``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from ..agents.scout.ats import ATS_SOURCES
from ..agents.scout.registry import LABELS, PLATFORM_IDS, is_ats
from ..config import get_settings
from ..db import Database, get_db
from ..run_settings import (
    LLM_CALLS_CEILING,
    MAX_JOBS_CEILING,
    load as load_run_settings,
    save as save_run_settings,
)
from ..security import require_agent_key

log = logging.getLogger(__name__)
router = APIRouter(tags=["setup"], dependencies=[Depends(require_agent_key)])

# The columns the seed and the agents address. `id` and `updated_at` are the
# table's own. Anything else is refused with a 400 rather than forwarded to
# PostgREST, which rejects the whole row with an opaque PGRST204 — the failure
# that once kept a real profile out of the database entirely.
PROFILE_COLUMNS = (
    "full_name",
    "headline",
    "location",
    "work_auth",
    "links",
    "email",
    "phone",
    "seniority",
    "years_experience",
    "salary_floor_usd",
    "skills",
    "roles",
    "education",
    "projects",
    "alumni_networks",
)


# ── profile ───────────────────────────────────────────────────────────────
@router.get("/profile")
async def get_profile(db: Database = Depends(get_db)) -> dict:
    row = await db.select_one("profile")
    if not row:
        raise HTTPException(404, "no profile row")
    return {"profile": row}


@router.patch("/profile")
async def patch_profile(payload: dict[str, Any] = Body(...), db: Database = Depends(get_db)) -> dict:
    if not payload:
        raise HTTPException(400, "no fields to update")
    unknown = sorted(set(payload) - set(PROFILE_COLUMNS))
    if unknown:
        raise HTTPException(400, f"unknown profile field(s): {', '.join(unknown)}")

    existing = await db.select_one("profile", columns="id")
    if not existing:
        raise HTTPException(404, "no profile row")

    patch = {**payload, "updated_at": datetime.now(timezone.utc).isoformat()}
    updated = await db.update("profile", patch, eq={"id": existing["id"]})
    log.info("profile updated: %s", ", ".join(sorted(payload)))
    return {"profile": updated[0] if updated else {}}


# ── platforms and boards ──────────────────────────────────────────────────
@router.get("/sources")
async def list_sources(db: Database = Depends(get_db)) -> dict:
    platforms = [
        {
            "id": platform_id,
            "label": LABELS.get(platform_id, platform_id),
            "kind": "ats" if is_ats(platform_id) else "aggregator",
        }
        for platform_id in PLATFORM_IDS
    ]
    try:
        boards = await db.select("source_seeds", order="kind.asc,slug.asc", limit=500)
    except Exception as exc:  # pragma: no cover - only when the table is missing
        log.warning("could not read source_seeds: %s", exc)
        boards = []
    return {"platforms": platforms, "boards": boards}


@router.patch("/sources/boards/{board_id}")
async def set_board(board_id: str, payload: dict[str, Any] = Body(...), db: Database = Depends(get_db)) -> dict:
    if "enabled" not in payload:
        raise HTTPException(400, "expected {\"enabled\": true|false}")
    updated = await db.update(
        "source_seeds", {"enabled": bool(payload["enabled"])}, eq={"id": board_id}
    )
    if not updated:
        raise HTTPException(404, "no such board")
    return {"board": updated[0]}


@router.post("/sources/boards")
async def add_board(payload: dict[str, Any] = Body(...), db: Database = Depends(get_db)) -> dict:
    kind = str(payload.get("kind") or "").strip()
    slug = str(payload.get("slug") or "").strip()
    if kind not in ATS_SOURCES:
        raise HTTPException(400, f"unknown platform {kind!r}; known: {sorted(ATS_SOURCES)}")
    if not slug:
        raise HTTPException(400, "a board needs a slug (the company's token on that platform)")

    rows = await db.insert(
        "source_seeds",
        {
            "kind": kind,
            "slug": slug,
            "company_name": payload.get("company_name"),
            "enabled": True,
        },
        upsert=True,
        on_conflict="kind,slug",
    )
    if not rows:
        raise HTTPException(409, f"{kind}/{slug} is already on file")
    return {"board": rows[0]}


@router.delete("/sources/boards/{board_id}")
async def delete_board(board_id: str, db: Database = Depends(get_db)) -> dict:
    removed = await db.delete("source_seeds", eq={"id": board_id})
    if not removed:
        raise HTTPException(404, "no such board")
    return {"removed": len(removed)}


# ── run settings ──────────────────────────────────────────────────────────
@router.get("/run-settings")
async def get_run_settings(db: Database = Depends(get_db)) -> dict:
    settings = get_settings()
    config = await load_run_settings(db)
    return {
        **config,
        "defaults": {
            "max_jobs": settings.scout_max_jobs_per_batch,
            "llm_calls": settings.llm_calls_per_batch,
        },
        "ceilings": {"max_jobs": MAX_JOBS_CEILING, "llm_calls": LLM_CALLS_CEILING},
    }


@router.patch("/run-settings")
async def patch_run_settings(payload: dict[str, Any] = Body(...), db: Database = Depends(get_db)) -> dict:
    current = await load_run_settings(db)
    try:
        saved = await save_run_settings(
            db,
            payload.get("platforms", current["platforms"]),
            payload.get("filters", current["filters"]),
        )
    except Exception as exc:
        # Almost always "run_settings does not exist yet" — migration 0005.
        raise HTTPException(503, f"could not save run settings: {exc}") from exc
    log.info("run settings saved: %d platform(s)", len(saved["platforms"]))
    return saved
