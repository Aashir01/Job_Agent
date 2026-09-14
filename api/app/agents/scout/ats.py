"""Company ATS boards — public JSON endpoints, no auth, no ToS problem.

These are the highest-signal sources: the posting is first-party, the
description is complete, and the ATS type tells the Courier how to submit later.
"""
from __future__ import annotations

import logging

import httpx

from .base import RawJob, Source, get_json, parse_when, safe, strip_html

log = logging.getLogger(__name__)


class GreenhouseBoard(Source):
    name = "greenhouse"
    ats_type = "greenhouse"

    def __init__(self, slug: str, company_name: str | None = None):
        self.slug = slug
        self.company_name = company_name or slug

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        data = await get_json(
            client,
            f"https://boards-api.greenhouse.io/v1/boards/{self.slug}/jobs",
            params={"content": "true"},
        )
        jobs = []
        for item in data.get("jobs", []):
            content = item.get("content") or ""
            # Greenhouse double-encodes the HTML entities in `content`.
            jobs.append(
                RawJob(
                    source=f"greenhouse:{self.slug}",
                    source_url=item.get("absolute_url", ""),
                    title=item.get("title", ""),
                    company_name=self.company_name,
                    description=strip_html(content),
                    location_raw=(item.get("location") or {}).get("name", ""),
                    posted_at=parse_when(item.get("updated_at") or item.get("first_published")),
                    ats_type=self.ats_type,
                    extra={"gh_id": item.get("id"), "departments": item.get("departments")},
                )
            )
        return safe(self.name, jobs)


class LeverBoard(Source):
    name = "lever"
    ats_type = "lever"

    def __init__(self, slug: str, company_name: str | None = None):
        self.slug = slug
        self.company_name = company_name or slug

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        data = await get_json(
            client, f"https://api.lever.co/v0/postings/{self.slug}", params={"mode": "json"}
        )
        jobs = []
        for item in data if isinstance(data, list) else []:
            cats = item.get("categories") or {}
            body = item.get("descriptionPlain") or strip_html(item.get("description"))
            for section in item.get("lists") or []:
                body += "\n\n" + section.get("text", "") + "\n" + strip_html(section.get("content"))
            jobs.append(
                RawJob(
                    source=f"lever:{self.slug}",
                    source_url=item.get("hostedUrl") or item.get("applyUrl", ""),
                    title=item.get("text", ""),
                    company_name=self.company_name,
                    description=body,
                    location_raw=cats.get("location", "") or "",
                    posted_at=parse_when(item.get("createdAt")),
                    ats_type=self.ats_type,
                    extra={"commitment": cats.get("commitment"), "team": cats.get("team")},
                )
            )
        return safe(self.name, jobs)


class AshbyBoard(Source):
    name = "ashby"
    ats_type = "ashby"

    def __init__(self, slug: str, company_name: str | None = None):
        self.slug = slug
        self.company_name = company_name or slug

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        data = await get_json(
            client,
            f"https://api.ashbyhq.com/posting-api/job-board/{self.slug}",
            params={"includeCompensation": "true"},
        )
        jobs = []
        for item in data.get("jobs", []):
            comp = item.get("compensation") or {}
            summary = comp.get("compensationTierSummary") or ""
            jobs.append(
                RawJob(
                    source=f"ashby:{self.slug}",
                    source_url=item.get("jobUrl") or item.get("applyUrl", ""),
                    title=item.get("title", ""),
                    company_name=item.get("organizationName") or self.company_name,
                    description=strip_html(item.get("descriptionHtml"))
                    or item.get("descriptionPlain", ""),
                    location_raw=item.get("location", "")
                    or ", ".join(item.get("secondaryLocations") or []),
                    posted_at=parse_when(item.get("publishedAt")),
                    ats_type=self.ats_type,
                    extra={
                        "is_remote": item.get("isRemote"),
                        "employment_type": item.get("employmentType"),
                        "compensation": summary,
                    },
                )
            )
        return safe(self.name, jobs)


class WorkableBoard(Source):
    name = "workable"
    ats_type = "workable"

    def __init__(self, slug: str, company_name: str | None = None):
        self.slug = slug
        self.company_name = company_name or slug

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        data = await get_json(
            client,
            f"https://apply.workable.com/api/v1/widget/accounts/{self.slug}",
            params={"details": "true"},
        )
        name = (data.get("name") or self.company_name) if isinstance(data, dict) else self.company_name
        jobs = []
        for item in (data.get("jobs") or []) if isinstance(data, dict) else []:
            city = item.get("city") or ""
            country = item.get("country") or ""
            location = ", ".join(p for p in (city, country) if p)
            if item.get("telecommuting"):
                location = f"Remote{' — ' + location if location else ''}"
            jobs.append(
                RawJob(
                    source=f"workable:{self.slug}",
                    source_url=item.get("url") or item.get("application_url", ""),
                    title=item.get("title", ""),
                    company_name=name,
                    description=strip_html(item.get("description"))
                    + "\n\n"
                    + strip_html(item.get("requirements")),
                    location_raw=location,
                    posted_at=parse_when(item.get("published_on") or item.get("created_at")),
                    ats_type=self.ats_type,
                    extra={"shortcode": item.get("shortcode"), "remote": item.get("telecommuting")},
                )
            )
        return safe(self.name, jobs)


class SmartRecruitersBoard(Source):
    name = "smartrecruiters"
    ats_type = "smartrecruiters"

    def __init__(self, slug: str, company_name: str | None = None):
        self.slug = slug
        self.company_name = company_name or slug

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        data = await get_json(
            client,
            f"https://api.smartrecruiters.com/v1/companies/{self.slug}/postings",
            params={"limit": 100},
        )
        jobs = []
        for item in data.get("content", []):
            loc = item.get("location") or {}
            parts = [loc.get("city"), loc.get("region"), loc.get("country")]
            location = ", ".join(p for p in parts if p)
            if loc.get("remote"):
                location = f"Remote{' — ' + location if location else ''}"
            jobs.append(
                RawJob(
                    source=f"smartrecruiters:{self.slug}",
                    source_url=item.get("ref")
                    or f"https://jobs.smartrecruiters.com/{self.slug}/{item.get('id')}",
                    title=item.get("name", ""),
                    company_name=(item.get("company") or {}).get("name") or self.company_name,
                    description=item.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get("text", ""),
                    location_raw=location,
                    posted_at=parse_when(item.get("releasedDate")),
                    ats_type=self.ats_type,
                    extra={"sr_id": item.get("id")},
                )
            )
        return safe(self.name, jobs)


ATS_SOURCES: dict[str, type[Source]] = {
    "greenhouse": GreenhouseBoard,
    "lever": LeverBoard,
    "ashby": AshbyBoard,
    "workable": WorkableBoard,
    "smartrecruiters": SmartRecruitersBoard,
}


def build_ats_source(kind: str, slug: str, company_name: str | None = None) -> Source:
    try:
        return ATS_SOURCES[kind](slug, company_name)  # type: ignore[call-arg]
    except KeyError:
        raise ValueError(f"unknown ATS kind {kind!r}; known: {sorted(ATS_SOURCES)}") from None
