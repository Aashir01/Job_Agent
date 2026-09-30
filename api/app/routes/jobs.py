"""The full job feed — everything Scout stored, not only what became a package.

The review queue answers "what should I look at next", and by construction it
can only answer that about postings that survived the Gatekeeper and scored well
enough to be packaged. Everything the Scout found and then threw away is
invisible there, which makes "why is my queue thin?" guesswork.

This is the other view: every stored posting, with the company it resolved to
and any package built from it, filterable by hand. It is read-only.
"""
from __future__ import annotations

import logging
import re
from typing import Literal

from fastapi import APIRouter, Depends, Query

from ..db import Database, get_db
from ..security import require_agent_key

log = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_agent_key)])

# One read backs the whole page: the company it resolved to and any packages
# built from it. `packages` is a to-many embed, so it arrives as a list per job.
COLUMNS = (
    "id,source,source_url,title,location_raw,remote_policy,track,geo_restriction,"
    "salary_min,salary_max,currency,posted_at,discovered_at,analysed_at,"
    "killed_reason,company_id,"
    "companies(id,name,hires_internationally),"
    "packages(id,tier,fit_score,status)"
)

SORTS = {
    "newest": "discovered_at.desc",
    "oldest": "discovered_at.asc",
    "title": "title.asc",
}

# The search term is interpolated into a PostgREST `or` filter, where these
# characters are syntax. A term carrying one would break the query rather than
# narrow it, so they are stripped rather than escaped.
_UNSAFE = re.compile(r"[,()*\\\"%]")


def _search_term(raw: str) -> str:
    """Strip the syntax characters, then collapse what is left.

    Replacing each of ``)`` and ``*`` with a space would otherwise leave the
    term with a double space in it, which is only noise in the pattern.
    """
    return " ".join(_UNSAFE.sub(" ", raw).split())[:80]


@router.get("")
async def list_jobs(
    q: str | None = Query(None, description="match title, location or source"),
    platform: str | None = Query(None, description="a platform id, e.g. greenhouse"),
    remote_policy: Literal["global", "geo_restricted", "hybrid", "onsite"] | None = None,
    track: Literal["remote_fte", "relocation", "contract"] | None = None,
    status: Literal["all", "unanalysed", "analysed", "killed"] = "all",
    sort: Literal["newest", "oldest", "title"] = "newest",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Database = Depends(get_db),
) -> dict:
    eq: dict[str, str] = {}
    if remote_policy:
        eq["remote_policy"] = remote_policy
    if track:
        eq["track"] = track

    # A platform id is a prefix of the stored source: seeded ATS boards store
    # "greenhouse:stripe", so matching the id alone would miss every one of them.
    ilike = {"source": f"{platform}*"} if platform else None

    not_null: list[str] = []
    is_null: list[str] = []
    if status == "analysed":
        not_null.append("analysis")
    elif status == "unanalysed":
        is_null.append("analysis")
    elif status == "killed":
        not_null.append("killed_reason")

    or_ = None
    if q:
        term = _search_term(q)
        if term:
            or_ = (
                f"(title.ilike.*{term}*,location_raw.ilike.*{term}*,"
                f"source.ilike.*{term}*)"
            )

    # One row beyond the page answers "is there more" without a count round trip.
    rows = await db.select(
        "jobs",
        columns=COLUMNS,
        eq=eq or None,
        ilike=ilike,
        or_=or_,
        not_null=not_null or None,
        is_null=is_null or None,
        order=SORTS[sort],
        limit=limit + 1,
        offset=offset,
    )
    return {
        "jobs": rows[:limit],
        "limit": limit,
        "offset": offset,
        "has_more": len(rows) > limit,
    }
