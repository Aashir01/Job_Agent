"""Discovery filters, applied in the Scout before anything costs money.

Discovery is free and the Analyst is not, so a posting dropped here saves the
call it would otherwise have spent. Every filter is deterministic — no model is
asked whether a job is relevant.

Two rules keep a filter from emptying the queue on a technicality:

* **Unknown never means no.** A missing salary, location or seniority is not a
  reason to drop a posting; only a disclosed mismatch is.
* **Only comparable salaries are compared.** A GBP or EUR range is not measured
  against a USD floor.
"""
from __future__ import annotations

import re
from typing import Any, Sequence

from .base import RawJob

REMOTE_MARKERS = (
    "remote",
    "anywhere",
    "work from home",
    "wfh",
    "distributed team",
    "telecommute",
)

LEVELS: dict[str, tuple[str, ...]] = {
    "intern": ("intern", "internship"),
    "junior": ("junior", "jr", "entry level", "graduate"),
    "mid": ("mid", "mid-level", "intermediate"),
    "senior": ("senior", "sr"),
    "staff": ("staff",),
    "principal": ("principal",),
    "lead": ("lead", "head of"),
    "director": ("director", "vp", "chief"),
}

_LEVEL_RE = {
    level: re.compile(r"\b(?:" + "|".join(re.escape(t) for t in terms) + r")\b")
    for level, terms in LEVELS.items()
}


def _any_term_in(haystack: str, terms: Sequence[str]) -> bool:
    return any(term.strip().lower() in haystack for term in terms if term and str(term).strip())


def _levels_in(title: str) -> set[str]:
    lowered = title.lower()
    return {level for level, rx in _LEVEL_RE.items() if rx.search(lowered)}


def _is_remote(job: RawJob) -> bool:
    return _any_term_in(f"{job.title}\n{job.location_raw}".lower(), REMOTE_MARKERS) or _any_term_in(
        job.description[:2000].lower(), ("remote", "anywhere")
    )


def apply_filters(
    jobs: Sequence[RawJob], filters: dict[str, Any] | None
) -> tuple[list[RawJob], dict[str, int]]:
    """Return (kept, drops-by-reason). Order matters: cheapest and most decisive first."""
    filters = filters or {}
    drops: dict[str, int] = {}
    kept: list[RawJob] = []

    keywords = [k for k in (filters.get("keywords") or []) if str(k).strip()]
    excludes = [k for k in (filters.get("exclude_keywords") or []) if str(k).strip()]
    locations = [k for k in (filters.get("locations") or []) if str(k).strip()]
    seniority = {str(k).strip().lower() for k in (filters.get("seniority") or []) if str(k).strip()}
    remote_only = bool(filters.get("remote_only"))
    floor = filters.get("salary_floor_usd")

    def drop(reason: str) -> None:
        drops[reason] = drops.get(reason, 0) + 1

    for job in jobs:
        haystack = f"{job.title}\n{job.location_raw}\n{job.description[:2000]}".lower()

        if keywords and not _any_term_in(haystack, keywords):
            drop("keywords")
            continue

        if excludes and _any_term_in(haystack, excludes):
            drop("exclude_keywords")
            continue

        if remote_only and not _is_remote(job):
            drop("remote_only")
            continue

        if locations and not (
            _any_term_in(job.location_raw.lower(), locations) or _is_remote(job) or not job.location_raw
        ):
            drop("locations")
            continue

        if seniority:
            present = _levels_in(job.title)
            # An unlevelled title is ambiguous, not a mismatch.
            if present and not (present & seniority):
                drop("seniority")
                continue

        if floor:
            disclosed = job.salary_max or job.salary_min
            comparable = job.currency in (None, "USD")
            if disclosed and comparable and disclosed < int(floor):
                drop("salary_floor")
                continue

        kept.append(job)

    return kept, drops
