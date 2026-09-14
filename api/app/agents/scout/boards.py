"""Remote-first boards and aggregators (§6 sources 2 and 3).

Lower signal than a company's own ATS — descriptions are often truncated and
the "remote" label is frequently a lie the Gatekeeper has to catch — but they
surface companies the seed list doesn't know about yet.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import httpx

from .base import RawJob, Source, get_json, parse_when, safe, strip_html

log = logging.getLogger(__name__)


class Remotive(Source):
    name = "remotive"

    def __init__(self, category: str = "software-dev", limit: int = 100):
        self.category = category
        self.limit = limit

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        data = await get_json(
            client,
            "https://remotive.com/api/remote-jobs",
            params={"category": self.category, "limit": self.limit},
        )
        jobs = [
            RawJob(
                source="remotive",
                source_url=item.get("url", ""),
                title=item.get("title", ""),
                company_name=item.get("company_name", ""),
                description=strip_html(item.get("description")),
                location_raw=item.get("candidate_required_location", "") or "Remote",
                posted_at=parse_when(item.get("publication_date")),
                salary_min=None,
                extra={"job_type": item.get("job_type"), "salary_text": item.get("salary")},
            )
            for item in data.get("jobs", [])
        ]
        return safe(self.name, jobs)


class RemoteOK(Source):
    name = "remoteok"

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        data = await get_json(client, "https://remoteok.com/api")
        jobs = []
        # The first element is a legal-notice object, not a posting.
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict) or not item.get("position"):
                continue
            jobs.append(
                RawJob(
                    source="remoteok",
                    source_url=item.get("url", ""),
                    title=item.get("position", ""),
                    company_name=item.get("company", ""),
                    description=strip_html(item.get("description")),
                    location_raw=item.get("location") or "Remote",
                    posted_at=parse_when(item.get("date") or item.get("epoch")),
                    salary_min=item.get("salary_min") or None,
                    salary_max=item.get("salary_max") or None,
                    currency="USD" if item.get("salary_min") else None,
                    extra={"tags": item.get("tags")},
                )
            )
        return safe(self.name, jobs)


class Arbeitnow(Source):
    name = "arbeitnow"

    def __init__(self, pages: int = 2):
        self.pages = pages

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        jobs = []
        for page in range(1, self.pages + 1):
            data = await get_json(
                client, "https://www.arbeitnow.com/api/job-board-api", params={"page": page}
            )
            items = data.get("data", [])
            if not items:
                break
            for item in items:
                jobs.append(
                    RawJob(
                        source="arbeitnow",
                        source_url=item.get("url", ""),
                        title=item.get("title", ""),
                        company_name=item.get("company_name", ""),
                        description=strip_html(item.get("description")),
                        location_raw=item.get("location", "")
                        or ("Remote" if item.get("remote") else ""),
                        posted_at=parse_when(item.get("created_at")),
                        extra={
                            "tags": item.get("tags"),
                            "visa_sponsorship": item.get("visa_sponsorship"),
                            "remote": item.get("remote"),
                        },
                    )
                )
        return safe(self.name, jobs)


class Himalayas(Source):
    name = "himalayas"

    def __init__(self, limit: int = 100):
        self.limit = limit

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        data = await get_json(
            client, "https://himalayas.app/jobs/api", params={"limit": self.limit}
        )
        jobs = []
        for item in data.get("jobs", []):
            locations = item.get("locationRestrictions") or []
            jobs.append(
                RawJob(
                    source="himalayas",
                    source_url=item.get("applicationLink") or item.get("guid", ""),
                    title=item.get("title", ""),
                    company_name=item.get("companyName", ""),
                    description=strip_html(item.get("description")),
                    location_raw=", ".join(locations) if locations else "Remote — Worldwide",
                    posted_at=parse_when(item.get("pubDate")),
                    salary_min=item.get("minSalary") or None,
                    salary_max=item.get("maxSalary") or None,
                    currency=item.get("salaryCurrency") or None,
                    extra={"location_restrictions": locations, "seniority": item.get("seniority")},
                )
            )
        return safe(self.name, jobs)


class WeWorkRemotely(Source):
    """RSS. feedparser handles the format drift so we don't have to."""

    name = "weworkremotely"
    FEEDS = (
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
        "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    )

    def __init__(self, feeds: tuple[str, ...] | None = None):
        self.feeds = feeds or self.FEEDS

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        import feedparser

        jobs = []
        for url in self.feeds:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                log.warning("weworkremotely feed %s failed: %s", url, exc)
                continue
            parsed = feedparser.parse(resp.text)
            for entry in parsed.entries:
                # WWR titles are "Company: Role".
                raw_title = entry.get("title", "")
                company, _, role = raw_title.partition(":")
                if not role:
                    company, role = "", raw_title
                jobs.append(
                    RawJob(
                        source="weworkremotely",
                        source_url=entry.get("link", ""),
                        title=role.strip(),
                        company_name=company.strip(),
                        description=strip_html(entry.get("summary")),
                        location_raw=entry.get("region", "") or "Remote",
                        posted_at=parse_when(entry.get("published")),
                    )
                )
        return safe(self.name, jobs)


class Adzuna(Source):
    """Free tier: needs an app id + key. Skipped entirely when unconfigured."""

    name = "adzuna"

    def __init__(self, app_id: str, app_key: str, countries=("gb", "nl", "de", "ca"),
                 what: str = "python engineer", results: int = 50):
        self.app_id = app_id
        self.app_key = app_key
        self.countries = countries
        self.what = what
        self.results = results

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        if not (self.app_id and self.app_key):
            log.info("adzuna: no credentials, skipping")
            return []
        jobs = []
        for country in self.countries:
            try:
                data = await get_json(
                    client,
                    f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
                    params={
                        "app_id": self.app_id,
                        "app_key": self.app_key,
                        "results_per_page": self.results,
                        "what": self.what,
                        "content-type": "application/json",
                    },
                )
            except httpx.HTTPError as exc:
                log.warning("adzuna %s failed: %s", country, exc)
                continue
            for item in data.get("results", []):
                jobs.append(
                    RawJob(
                        source=f"adzuna:{country}",
                        source_url=item.get("redirect_url", ""),
                        title=item.get("title", ""),
                        company_name=(item.get("company") or {}).get("display_name", ""),
                        description=strip_html(item.get("description")),
                        location_raw=(item.get("location") or {}).get("display_name", ""),
                        posted_at=parse_when(item.get("created")),
                        salary_min=int(item["salary_min"]) if item.get("salary_min") else None,
                        salary_max=int(item["salary_max"]) if item.get("salary_max") else None,
                        currency={"gb": "GBP", "nl": "EUR", "de": "EUR", "ca": "CAD"}.get(country),
                    )
                )
        return safe(self.name, jobs)


_HN_HEADER_RE = re.compile(r"^(?P<company>[^|]{2,80})\|(?P<rest>.+)$")


class HackerNewsHiring(Source):
    """'Ask HN: Who is hiring?' via the free Algolia index.

    Top-level comments are the postings. The convention is
    ``Company | Location | Role | REMOTE | ...`` on the first line.
    """

    name = "hn_hiring"

    def __init__(self, max_comments: int = 300):
        self.max_comments = max_comments

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        story = await get_json(
            client,
            "https://hn.algolia.com/api/v1/search_by_date",
            params={"tags": "story,author_whoishiring", "query": "Who is hiring", "hitsPerPage": 5},
        )
        hits = [h for h in story.get("hits", []) if "who is hiring" in (h.get("title") or "").lower()]
        if not hits:
            log.info("hn_hiring: no thread found")
            return []
        story_id = hits[0]["objectID"]
        month = hits[0].get("title", "")

        comments = await get_json(
            client,
            "https://hn.algolia.com/api/v1/search_by_date",
            params={
                "tags": f"comment,story_{story_id}",
                "hitsPerPage": min(self.max_comments, 1000),
            },
        )
        jobs = []
        for hit in comments.get("hits", []):
            body = strip_html(hit.get("comment_text"))
            if not body or hit.get("parent_id") != int(story_id):
                continue
            first_line = body.split("\n", 1)[0].strip()
            match = _HN_HEADER_RE.match(first_line)
            if not match:
                continue
            fields = [f.strip() for f in first_line.split("|")]
            company = fields[0]
            role = next(
                (f for f in fields[1:] if re.search(r"engineer|developer|scientist|ml|ai|backend|full.?stack", f, re.I)),
                fields[2] if len(fields) > 2 else "Engineer",
            )
            location = next(
                (f for f in fields[1:] if re.search(r"remote|onsite|hybrid|[A-Z]{2},|,\s*[A-Z]{2}\b", f)),
                fields[1] if len(fields) > 1 else "",
            )
            jobs.append(
                RawJob(
                    source="hn_hiring",
                    source_url=f"https://news.ycombinator.com/item?id={hit['objectID']}",
                    title=role[:200],
                    company_name=company,
                    description=body,
                    location_raw=location,
                    posted_at=parse_when(hit.get("created_at")),
                    extra={"thread": month, "hn_id": hit["objectID"]},
                )
            )
        return safe(self.name, jobs)
