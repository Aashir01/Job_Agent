"""Weekly refresh of the sponsorship registers the Gatekeeper reads (§6).

All three sources are free public CSVs. They move around — the Home Office
republishes under a dated filename every few weeks — so the URLs are settings,
and a failed refresh keeps the previous rows rather than emptying the table. A
stale register still kills correctly; an empty one passes everything.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from ..config import Settings, get_settings
from ..db import Database

log = logging.getLogger(__name__)

_NORM_RE = re.compile(r"[^a-z0-9]+")
# Kept in lockstep with strip_org_suffix() in 0003_indexes_rpc_rls.sql and with
# normalise_name() in agents/scout/base.py — all three must agree or the
# Gatekeeper silently stops matching companies to registers.
_SUFFIX_RE = re.compile(r"(incorporated|limited|gmbh|bv|ltd|llc|inc|plc|sa|ag)$")


def normalise(name: str) -> str:
    return _NORM_RE.sub("", (name or "").lower())


def strip_suffix(key: str) -> str:
    return _SUFFIX_RE.sub("", key or "")


@dataclass
class RegisterSource:
    country: str
    url: str
    name_columns: tuple[str, ...]
    route_columns: tuple[str, ...] = ()
    rating_columns: tuple[str, ...] = ()


# Defaults point at the current publications. Override per deployment via
# settings when the Home Office rotates the filename.
DEFAULT_SOURCES: dict[str, RegisterSource] = {
    "UK": RegisterSource(
        country="UK",
        url="https://assets.publishing.service.gov.uk/media/worker_and_temporary_worker.csv",
        name_columns=("Organisation Name", "Organisation name", "Name"),
        route_columns=("Route",),
        rating_columns=("Type & Rating", "Type and Rating"),
    ),
    "NL": RegisterSource(
        country="NL",
        url="https://ind.nl/en/public-register-recognised-sponsors/public-register-regular-labour-and-highly-skilled-migrants.csv",
        name_columns=("Organisation", "Organisation name", "Company", "Naam"),
        route_columns=("Type",),
    ),
    "CA": RegisterSource(
        country="CA",
        url="https://open.canada.ca/data/dataset/lmia-exempt-employers.csv",
        name_columns=("Employer", "Employer Name", "Operating Name"),
        route_columns=("Program", "Stream"),
    ),
}


def _pick(row: dict[str, str], candidates: tuple[str, ...]) -> str:
    for key in candidates:
        if value := (row.get(key) or "").strip():
            return value
    # Header casing drifts between publications; fall back to a loose match.
    lowered = {k.lower().strip(): v for k, v in row.items() if k}
    for key in candidates:
        if value := (lowered.get(key.lower()) or "").strip():
            return value
    return ""


def parse_csv(text: str, source: RegisterSource) -> list[dict[str, str]]:
    # Publications carry a preamble line often enough to be worth handling.
    lines = text.splitlines()
    start = 0
    for index, line in enumerate(lines[:5]):
        if any(col.lower() in line.lower() for col in source.name_columns):
            start = index
            break
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in reader:
        name = _pick(raw, source.name_columns)
        if not name:
            continue
        key = normalise(name)
        route = _pick(raw, source.route_columns)
        dedupe_key = f"{key}|{route}"
        if not key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        rows.append(
            {
                "country": source.country,
                "org_name": name[:300],
                "org_name_normalised": key[:300],
                "org_name_stripped": strip_suffix(key)[:300],
                "route": route[:120] or None,
                "rating": _pick(raw, source.rating_columns)[:120] or None,
            }
        )
    return rows


async def refresh_register(
    db: Database,
    source: RegisterSource,
    client: httpx.AsyncClient | None = None,
    chunk_size: int = 500,
) -> tuple[int, str | None]:
    """Fetch, parse, and swap. Returns (row_count, error)."""
    owns = client is None
    client = client or httpx.AsyncClient(timeout=120.0, follow_redirects=True)
    try:
        resp = await client.get(source.url)
        resp.raise_for_status()
        rows = parse_csv(resp.text, source)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:300]
        log.error("register refresh failed for %s: %s", source.country, error)
        await db.insert(
            "register_refreshes",
            {"country": source.country, "row_count": 0, "source_url": source.url,
             "ok": False, "error": error},
            returning=False,
        )
        return 0, error
    finally:
        if owns:
            await client.aclose()

    if not rows:
        error = "parsed zero rows — keeping the previous register"
        await db.insert(
            "register_refreshes",
            {"country": source.country, "row_count": 0, "source_url": source.url,
             "ok": False, "error": error},
            returning=False,
        )
        return 0, error

    # Only delete once the new rows are in hand, so a bad fetch can't empty
    # the register and quietly turn the Gatekeeper into a pass-through.
    await db.delete("sponsor_registers", eq={"country": source.country})
    now = datetime.now(timezone.utc).isoformat()
    for start in range(0, len(rows), chunk_size):
        chunk = [{**row, "refreshed_at": now} for row in rows[start : start + chunk_size]]
        await db.insert("sponsor_registers", chunk, returning=False)

    await db.insert(
        "register_refreshes",
        {"country": source.country, "row_count": len(rows), "source_url": source.url, "ok": True},
        returning=False,
    )
    log.info("register %s refreshed: %d organisations", source.country, len(rows))
    return len(rows), None


async def refresh_all(
    db: Database, settings: Settings | None = None, countries: tuple[str, ...] = ("UK", "NL", "CA")
) -> dict[str, dict]:
    settings = settings or get_settings()
    results: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        for country in countries:
            source = DEFAULT_SOURCES.get(country)
            if not source:
                results[country] = {"ok": False, "error": "unknown register"}
                continue
            override = getattr(settings, f"register_url_{country.lower()}", "")
            if override:
                source = RegisterSource(**{**source.__dict__, "url": override})
            count, error = await refresh_register(db, source, client)
            results[country] = {"ok": error is None, "rows": count, "error": error}

    # Propagate onto the company rows the Gatekeeper checks first.
    await backfill_company_flags(db)
    return results


async def backfill_company_flags(db: Database) -> int:
    """Stamp uk_sponsor_licensed / nl_recognised_sponsor onto known companies
    so the common path is a column read, not an RPC."""
    companies = await db.select("companies", columns="id,name", limit=2000)
    updated = 0
    for company in companies:
        name = company.get("name")
        if not name:
            continue
        patch = {}
        for country, column in (("UK", "uk_sponsor_licensed"), ("NL", "nl_recognised_sponsor")):
            try:
                on_register = await db.rpc(
                    "is_licensed_sponsor", {"country_code": country, "company_name": name}
                )
            except Exception:
                continue
            patch[column] = bool(on_register)
        if patch:
            await db.update("companies", patch, eq={"id": company["id"]}, returning=False)
            updated += 1
    return updated
