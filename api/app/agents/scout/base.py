"""Scout shared types and normalisation.

Scout polls sources, normalises to a common shape, and dedupes. It makes no
LLM calls — everything here is free.
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import httpx

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_BLANKS_RE = re.compile(r"\n{3,}")
_NORM_RE = re.compile(r"[^a-z0-9]+")


def strip_html(raw: str | None) -> str:
    if not raw:
        return ""
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
    text = re.sub(r"(?i)<(br|/p|/div|/li|/tr|/h[1-6])\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li\b[^>]*>", "\n• ", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    return _BLANKS_RE.sub("\n\n", text).strip()


def normalise_name(name: str | None) -> str:
    """Company-name key: 'Acme, Inc.' and 'acme inc' collapse to one string."""
    if not name:
        return ""
    key = _NORM_RE.sub("", name.lower())
    for suffix in ("incorporated", "limited", "gmbh", "bv", "ltd", "llc", "inc", "plc", "sa", "ag"):
        if key.endswith(suffix) and len(key) > len(suffix) + 2:
            key = key[: -len(suffix)]
            break
    return key


def parse_when(value: Any) -> datetime | None:
    """Best-effort timestamp parse across the wire formats sources actually use."""
    if value in (None, "", 0):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        # Epoch seconds vs milliseconds.
        seconds = value / 1000 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, IndexError):
        return None


_SALARY_RE = re.compile(
    r"(?P<cur>[$€£]|USD|EUR|GBP|CAD|PKR)?\s*"
    r"(?P<lo>\d{1,3}(?:[,.]\d{3})+|\d{2,3}(?:\.\d)?[kK]|\d{5,7})"
    r"\s*(?:-|–|—|to)\s*"
    r"(?P<cur2>[$€£]|USD|EUR|GBP|CAD)?\s*"
    r"(?P<hi>\d{1,3}(?:[,.]\d{3})+|\d{2,3}(?:\.\d)?[kK]|\d{5,7})"
)
_CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP"}


def _to_int(token: str) -> int | None:
    token = token.strip().replace(",", "")
    try:
        if token.lower().endswith("k"):
            return int(float(token[:-1]) * 1000)
        if token.count(".") == 1 and len(token.split(".")[1]) == 3:
            token = token.replace(".", "")  # European thousands separator
        return int(float(token))
    except ValueError:
        return None


def parse_salary(text: str | None) -> tuple[int | None, int | None, str | None]:
    """Pull a salary range out of free text. Returns (min, max, currency)."""
    if not text:
        return None, None, None
    match = _SALARY_RE.search(text)
    if not match:
        return None, None, None
    lo, hi = _to_int(match.group("lo")), _to_int(match.group("hi"))
    if lo is None or hi is None or hi < lo:
        return None, None, None
    # Reject ranges that are obviously not annual pay (years, headcounts, ids).
    if hi < 10_000 or lo > 2_000_000:
        return None, None, None
    symbol = match.group("cur") or match.group("cur2")
    currency = _CURRENCY.get(symbol, symbol.upper() if symbol else None)
    return lo, hi, currency


def dedupe_hash(company: str | None, title: str | None, location: str | None) -> str:
    """Cheap exact-duplicate key. The embedding check (§6) catches the rest."""
    key = "|".join(
        (
            normalise_name(company),
            _NORM_RE.sub("", (title or "").lower()),
            _NORM_RE.sub("", (location or "").lower())[:24],
        )
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


@dataclass(slots=True)
class RawJob:
    """One posting, normalised. Source-agnostic from here on."""

    source: str
    source_url: str
    title: str
    company_name: str
    description: str = ""
    location_raw: str = ""
    posted_at: datetime | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    currency: str | None = None
    ats_type: str | None = None
    company_domain: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.title = (self.title or "").strip()[:300]
        self.company_name = (self.company_name or "").strip()[:200]
        self.location_raw = (self.location_raw or "").strip()[:300]
        self.description = (self.description or "").strip()[:40_000]
        if self.salary_min is None and self.salary_max is None:
            lo, hi, cur = parse_salary(f"{self.title}\n{self.description[:4000]}")
            self.salary_min, self.salary_max, self.currency = lo, hi, cur or self.currency

    @property
    def dedupe_hash(self) -> str:
        return dedupe_hash(self.company_name, self.title, self.location_raw)

    @property
    def embed_text(self) -> str:
        return f"{self.title}\n{self.company_name}\n{self.location_raw}\n{self.description[:6000]}"

    def is_valid(self) -> bool:
        return bool(self.title and self.source_url and self.company_name)

    def is_fresh(self, max_age_days: int) -> bool:
        if self.posted_at is None:
            return True  # unknown age is not a reason to drop a posting
        return self.posted_at >= datetime.now(timezone.utc) - timedelta(days=max_age_days)


class Source:
    """A pollable job source."""

    name: str = "source"
    ats_type: str | None = None

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        raise NotImplementedError


async def get_json(client: httpx.AsyncClient, url: str, **kw: Any) -> Any:
    resp = await client.get(url, **kw)
    resp.raise_for_status()
    return resp.json()


def safe(source_name: str, jobs: Iterable[RawJob]) -> list[RawJob]:
    """Drop malformed rows rather than failing a whole source."""
    kept = []
    for job in jobs:
        if job.is_valid():
            kept.append(job)
        else:
            log.debug("%s: dropped malformed posting %r", source_name, job.source_url)
    return kept
