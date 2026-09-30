"""Load postings the user collected by hand.

LinkedIn and Indeed are never fetched server-side. Their terms of service forbid
automated access, and the account that would be doing the fetching is the user's
own — the same one the tracked applications are sent from. So this takes what
the user already has instead: a file of job URLs, each optionally carrying the
title, company and description they can see on the page.

Imported rows are ordinary ``jobs`` rows. Scout skips them afterwards because the
URL is already stored, and the Analyst, Gatekeeper, Tailor and Scribe treat them
exactly like something Scout discovered.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

from .agents.scout.base import RawJob

log = logging.getLogger(__name__)

_URL_RE = re.compile(r"^https?://\S+$", re.I)
_FIELD_RE = re.compile(r"^(title|company|company_name|location|location_raw)\s*:\s*(.+)$", re.I)
_FIELDS = {
    "title": "title",
    "company": "company_name",
    "company_name": "company_name",
    "location": "location_raw",
    "location_raw": "location_raw",
}

# Every posting needs a company, because ``companies.name_normalised`` is what
# the Gatekeeper's ``hires_internationally`` flag accumulates on. A URL-only
# posting still has to resolve somewhere, and it has to be the *same* somewhere
# every time, so that flag is not split across a row per import.
UNKNOWN_COMPANY = "(company not given)"


def parse_postings(text: str) -> tuple[list[dict], list[str]]:
    """Parse the import file into records, plus the lines that were ignored.

    One posting per block, and a block starts at a URL line::

        # comments and blank lines are ignored
        https://www.linkedin.com/jobs/view/4123456789
        title: Senior AI Engineer
        company: Acme
        location: Remote — EU

        <every line from here to the next URL is the description, verbatim>

    ``title:``, ``company:`` and ``location:`` are only read *before* the
    description starts, so a sentence inside a posting that happens to read
    "Location: Berlin" is text, not a field.
    """
    records: list[dict] = []
    problems: list[str] = []
    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if current is not None:
            current["description"] = "\n".join(current.pop("_lines")).strip()
            records.append(current)
            current = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _URL_RE.match(stripped):
            flush()
            current = {"url": stripped, "_lines": []}
            continue
        if current is None:
            problems.append(f"line before any URL: {stripped[:80]!r}")
            continue
        if not current["_lines"]:
            field = _FIELD_RE.match(stripped)
            if field:
                current[_FIELDS[field.group(1).lower()]] = field.group(2).strip()
                continue
        current["_lines"].append(line.rstrip())

    flush()
    return records, problems


def build_jobs(records: Iterable[dict], source: str = "linkedin") -> list[RawJob]:
    """Turn parsed records into postings.

    A posting with no title still gets one, derived from its URL. It has to:
    ``dedupe_hash`` is computed from company, title and location, so a run of
    bare URLs would otherwise share a single empty-string hash and every posting
    after the first would be thrown away as a duplicate of it.
    """
    return [
        RawJob(
            source=source,
            source_url=record.get("url", ""),
            title=record.get("title") or _derived_title(record.get("url", ""), source),
            company_name=record.get("company_name") or UNKNOWN_COMPANY,
            description=record.get("description", ""),
            location_raw=record.get("location_raw", ""),
        )
        for record in records
    ]


def is_thin(record: dict) -> bool:
    """True when the user gave a URL but no title or company to go with it."""
    return not (record.get("title") and record.get("company_name"))


def _derived_title(url: str, source: str) -> str:
    tail = re.sub(r"[^0-9A-Za-z]+", "", url.rstrip("/").rsplit("/", 1)[-1])[:24]
    label = source.capitalize() or "Imported"
    return f"{label} posting {tail}" if tail else f"{label} posting"
