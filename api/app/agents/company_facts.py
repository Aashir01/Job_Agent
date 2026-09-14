"""One specific, recent, checkable fact about the company (§6 Scribe).

Tries the company's own feed before anything else: a blog post or release note
is first-party, dated, and linkable, so the cover letter's one concrete claim
can be verified by the person reading it. Falls back to facts the Analyst
pulled out of the posting, and returns nothing rather than something vague —
a generic compliment is worse than no compliment.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from .scout.base import parse_when, strip_html

log = logging.getLogger(__name__)

FEED_PATHS = (
    "/blog/rss.xml", "/blog/feed", "/blog/feed.xml", "/feed", "/rss.xml",
    "/blog/index.xml", "/news/rss.xml", "/changelog/rss.xml", "/atom.xml",
)
MAX_AGE_DAYS = 240


@dataclass
class CompanyFact:
    text: str
    source: str
    url: str = ""
    published_at: datetime | None = None

    def cite(self) -> str:
        when = f" ({self.published_at:%b %Y})" if self.published_at else ""
        return f"{self.text}{when}"


async def fetch_company_fact(
    domain: str | None,
    company_name: str,
    analysis_facts: list[str] | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: float = 8.0,
) -> CompanyFact | None:
    """Best-effort. Never raises — a missing fact is not a failed package."""
    if domain:
        fact = await _from_feed(domain, client, timeout)
        if fact:
            return fact
    for candidate in analysis_facts or []:
        if len(candidate.strip()) > 25:
            return CompanyFact(candidate.strip(), source="job_description")
    log.info("no company fact found for %s", company_name)
    return None


async def _from_feed(
    domain: str, client: httpx.AsyncClient | None, timeout: float
) -> CompanyFact | None:
    import feedparser

    base = domain.strip().rstrip("/")
    if not base.startswith("http"):
        base = f"https://{base}"

    owns = client is None
    client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=True)
    try:
        for path in FEED_PATHS:
            try:
                resp = await client.get(f"{base}{path}", timeout=timeout)
            except httpx.HTTPError:
                continue
            if resp.status_code != 200 or "xml" not in resp.headers.get("content-type", "") and "<rss" not in resp.text[:200] and "<feed" not in resp.text[:200]:
                continue

            parsed = feedparser.parse(resp.text)
            cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
            for entry in parsed.entries[:6]:
                published = parse_when(entry.get("published") or entry.get("updated"))
                if published and published < cutoff:
                    continue
                title = (entry.get("title") or "").strip()
                if len(title) < 12:
                    continue
                summary = strip_html(entry.get("summary"))[:240]
                return CompanyFact(
                    text=f"{title}" + (f" — {summary}" if summary else ""),
                    source="company_feed",
                    url=entry.get("link", ""),
                    published_at=published,
                )
    finally:
        if owns:
            await client.aclose()
    return None
