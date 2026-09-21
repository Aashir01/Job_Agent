"""Scout: poll, normalise, dedupe, persist. No LLM calls, no approval needed.

Dedupe is two-stage (§6):
  1. exact ``source_url``, then the cheap ``dedupe_hash``
  2. embedding cosine > 0.92 against everything already stored

Stage 1 catches the same posting seen twice; stage 2 catches the same role
cross-posted to Remotive, RemoteOK and the company's own Greenhouse board with
three different titles.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence

import httpx

from ...config import Settings, get_settings
from ...db import Database
from ...embeddings import Embedder
from .ats import build_ats_source
from .base import RawJob, Source, normalise_name
from .filters import apply_filters
from .registry import build_aggregator, select

log = logging.getLogger(__name__)

USER_AGENT = (
    "job-agent/0.1 (+https://github.com/Aashir01/Job_Agent) "
    "personal job search; contact via repository"
)


@dataclass
class ScoutResult:
    fetched: int = 0
    kept: int = 0
    duplicates_url: int = 0
    duplicates_hash: int = 0
    duplicates_embedding: int = 0
    stale: int = 0
    # Where the postings came from, and what the run's filters dropped. Without
    # these a thin batch is unexplainable from the dashboard.
    by_source: dict[str, int] = field(default_factory=dict)
    filtered: dict[str, int] = field(default_factory=dict)
    inserted_job_ids: list[str] = field(default_factory=list)
    source_errors: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "fetched": self.fetched,
            "kept": self.kept,
            "duplicates_url": self.duplicates_url,
            "duplicates_hash": self.duplicates_hash,
            "duplicates_embedding": self.duplicates_embedding,
            "stale": self.stale,
            "filtered": self.filtered,
            "by_source": self.by_source,
            "inserted": len(self.inserted_job_ids),
            "source_errors": self.source_errors,
        }


def _balanced_take(jobs: Sequence[RawJob], limit: int) -> list[RawJob]:
    """Cap the batch round-robin across sources instead of by arrival order.

    Sources are polled and concatenated in code order, so a plain ``[:limit]``
    lets whichever platform happens to be polled first consume the whole
    allowance — which is how every stored job came to be from a single ATS.
    Taking one posting per source per pass keeps every platform in the running.
    """
    if limit <= 0 or len(jobs) <= limit:
        return list(jobs)

    buckets: dict[str, list[RawJob]] = {}
    for job in jobs:
        buckets.setdefault(job.source, []).append(job)

    taken: list[RawJob] = []
    position = 0
    while len(taken) < limit:
        progressed = False
        for bucket in buckets.values():
            if position < len(bucket):
                taken.append(bucket[position])
                progressed = True
                if len(taken) >= limit:
                    break
        if not progressed:
            break
        position += 1
    return taken


class Scout:
    def __init__(
        self,
        db: Database,
        settings: Settings | None = None,
        embedder: Embedder | None = None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.embedder = embedder or Embedder(self.settings)

    # ── source assembly ───────────────────────────────────────────────────
    async def build_sources(
        self, platforms: Sequence[str] | None = None, keywords: Sequence[str] | None = None
    ) -> list[Source]:
        """Seeded company boards first (§6 build order), then the open boards.

        ``platforms`` narrows the poll to a selection made in the run console; an
        empty selection means every platform, so an install that never opens the
        Setup page polls exactly what it used to.
        """
        ats_kinds, aggregator_ids = select(list(platforms) if platforms else None)

        sources: list[Source] = []
        try:
            seeds = await self.db.select(
                "source_seeds", eq={"enabled": True}, order="kind.asc,slug.asc", limit=500
            )
        except Exception as exc:
            log.warning("could not read source_seeds (%s); using open boards only", exc)
            seeds = []

        for seed in seeds:
            if seed.get("kind") not in ats_kinds:
                continue
            try:
                sources.append(
                    build_ats_source(seed["kind"], seed["slug"], seed.get("company_name"))
                )
            except ValueError as exc:
                log.warning("skipping seed %s/%s: %s", seed.get("kind"), seed.get("slug"), exc)

        for platform_id in aggregator_ids:
            source = build_aggregator(platform_id, self.settings, list(keywords or []))
            if source is not None:
                sources.append(source)
        return sources

    # ── polling ───────────────────────────────────────────────────────────
    async def poll(
        self,
        sources: Sequence[Source] | None = None,
        platforms: Sequence[str] | None = None,
        keywords: Sequence[str] | None = None,
    ) -> tuple[list[RawJob], dict[str, str]]:
        if sources is None:
            sources = await self.build_sources(platforms, keywords)
        sources = list(sources)
        semaphore = asyncio.Semaphore(self.settings.scout_concurrency)
        errors: dict[str, str] = {}

        async with httpx.AsyncClient(
            timeout=self.settings.http_timeout_s,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/xml, */*"},
        ) as client:

            async def run(source: Source) -> list[RawJob]:
                async with semaphore:
                    try:
                        jobs = await source.fetch(client)
                        log.info("scout %s: %d postings", source.name, len(jobs))
                        return jobs
                    except Exception as exc:  # one dead board must not kill the batch
                        key = getattr(source, "slug", None)
                        label = f"{source.name}:{key}" if key else source.name
                        errors[label] = f"{type(exc).__name__}: {exc}"[:300]
                        log.warning("scout %s failed: %s", label, exc)
                        return []

            batches = await asyncio.gather(*(run(s) for s in sources))

        return [job for batch in batches for job in batch], errors

    # ── dedupe + persist ──────────────────────────────────────────────────
    async def run(
        self,
        sources: Sequence[Source] | None = None,
        platforms: Sequence[str] | None = None,
        filters: dict | None = None,
        limit: int | None = None,
    ) -> ScoutResult:
        keywords = [str(k) for k in ((filters or {}).get("keywords") or []) if str(k).strip()]
        raw, errors = await self.poll(sources, platforms, keywords)
        result = ScoutResult(fetched=len(raw), source_errors=errors)

        # Free to drop, expensive to carry: a filtered posting never reaches the
        # Analyst, so this runs before anything is stored or scored.
        raw, result.filtered = apply_filters(raw, filters)

        seen_urls: set[str] = set()
        seen_hashes: set[str] = set()
        candidates: list[RawJob] = []

        for job in raw:
            if not job.is_fresh(self.settings.job_max_age_days):
                result.stale += 1
                continue
            if job.source_url in seen_urls:
                result.duplicates_url += 1
                continue
            if job.dedupe_hash in seen_hashes:
                result.duplicates_hash += 1
                continue
            seen_urls.add(job.source_url)
            seen_hashes.add(job.dedupe_hash)
            candidates.append(job)

        candidates = _balanced_take(
            candidates, limit or self.settings.scout_max_jobs_per_batch
        )
        if not candidates:
            return result

        known_urls = await self._known(
            "jobs", "source_url", [j.source_url for j in candidates]
        )
        known_hashes = await self._known(
            "jobs", "dedupe_hash", [j.dedupe_hash for j in candidates]
        )

        for job in candidates:
            if job.source_url in known_urls:
                result.duplicates_url += 1
                continue
            if job.dedupe_hash in known_hashes:
                result.duplicates_hash += 1
                continue

            embedding = await self.embedder.embed(job.embed_text)
            if await self._is_near_duplicate(embedding):
                result.duplicates_embedding += 1
                continue

            company_id = await self.resolve_company(job)
            row = {
                "company_id": company_id,
                "source": job.source,
                "source_url": job.source_url,
                "title": job.title,
                "description": job.description,
                "posted_at": job.posted_at.isoformat() if job.posted_at else None,
                "location_raw": job.location_raw,
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "currency": job.currency,
                "dedupe_hash": job.dedupe_hash,
                "embedding": embedding,
            }
            inserted = await self.db.insert(
                "jobs", row, upsert=True, on_conflict="source_url", ignore_duplicates=True
            )
            if inserted:
                result.inserted_job_ids.append(inserted[0]["id"])
                result.kept += 1
                result.by_source[job.source] = result.by_source.get(job.source, 0) + 1
                # Keep the in-run guard current so a later near-duplicate in the
                # same batch is compared against this row too.
                known_hashes.add(job.dedupe_hash)
            else:
                result.duplicates_url += 1

        await self._mark_polled(sources, errors, result.by_source)
        return result

    async def _known(self, table: str, column: str, values: list[str]) -> set[str]:
        found: set[str] = set()
        # PostgREST puts the filter in the URL; chunk to stay under header limits.
        for start in range(0, len(values), 100):
            chunk = [v for v in values[start : start + 100] if v]
            if not chunk:
                continue
            rows = await self.db.select(table, columns=column, in_={column: chunk}, limit=len(chunk))
            found.update(r[column] for r in rows if r.get(column))
        return found

    async def _is_near_duplicate(self, embedding: list[float]) -> bool:
        try:
            matches = await self.db.rpc(
                "match_jobs",
                {
                    "query_embedding": embedding,
                    "match_threshold": self.settings.dedupe_cosine_threshold,
                    "match_count": 1,
                },
            )
        except Exception as exc:
            log.warning("match_jobs rpc failed (%s); keeping the posting", exc)
            return False
        return bool(matches)

    async def resolve_company(self, job: RawJob) -> str | None:
        """Find or create the company row.

        Looked up by ``companies.name_normalised``, a stored generated column
        with a unique index, so "Acme", "Acme, Inc." and "acme inc" resolve to
        one row however many companies are on file. The
        ``hires_internationally`` flag the Gatekeeper compounds over time lives
        on that row, so a duplicate would split the system's most valuable
        asset — hence the constraint rather than a convention.
        """
        key = normalise_name(job.company_name)
        if not key:
            return None

        row = await self.db.select_one(
            "companies", columns="id,name,ats_type,domain", eq={"name_normalised": key}
        )
        if row:
            patch = {}
            if job.ats_type and not row.get("ats_type"):
                patch["ats_type"] = job.ats_type
            if job.company_domain and not row.get("domain"):
                patch["domain"] = job.company_domain
            if patch:
                await self.db.update("companies", patch, eq={"id": row["id"]}, returning=False)
            return row["id"]

        created = await self.db.insert(
            "companies",
            {
                "name": job.company_name,
                "domain": job.company_domain,
                "ats_type": job.ats_type or "other",
            },
            upsert=True,
            on_conflict="name_normalised",
        )
        if created:
            return created[0]["id"]
        # Another concurrent insert won the race; re-read rather than duplicate.
        row = await self.db.select_one("companies", columns="id", eq={"name_normalised": key})
        return row["id"] if row else None

    async def _mark_polled(
        self,
        sources: Sequence[Source] | None,
        errors: dict[str, str] | None = None,
        by_source: dict[str, int] | None = None,
    ) -> None:
        if not sources:
            return
        now = datetime.now(timezone.utc).isoformat()
        errors = errors or {}
        by_source = by_source or {}
        for source in sources:
            slug = getattr(source, "slug", None)
            if not slug:
                continue
            label = f"{source.name}:{slug}"
            try:
                await self.db.update(
                    "source_seeds",
                    {
                        "last_polled_at": now,
                        "last_error": errors.get(label),
                        "jobs_found": by_source.get(label, 0),
                    },
                    eq={"kind": source.name, "slug": slug},
                    returning=False,
                )
            except Exception:
                # Before 0005 the table has no jobs_found column; a board's health
                # should not cost us the record that we polled it at all.
                try:
                    await self.db.update(
                        "source_seeds",
                        {"last_polled_at": now},
                        eq={"kind": source.name, "slug": slug},
                        returning=False,
                    )
                except Exception:
                    pass
