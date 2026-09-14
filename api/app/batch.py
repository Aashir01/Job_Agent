"""Batch orchestrator (§3, §4).

Scout → Analyst → Gatekeeper → Tailor → Scribe → Connector → packages.

The ordering is the economics (§8): the Gatekeeper runs before the Tailor and
the Scribe, so a package that cannot be applied to costs one cheap call instead
of five. Everything past the Gatekeeper is only ever reached by a job that
survived it.

Nothing in this module submits anything. The Courier is downstream of the human
gate and is invoked from the approval route, never from here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .agents.analyst import Analyst
from .agents.connector import Connector
from .agents.gatekeeper import Gatekeeper
from .agents.scoring import DecisionBias, ScoringInputs, assign_tier, score_package
from .agents.scout.runner import Scout
from .agents.scribe import Scribe
from .agents.tailor import Tailor
from .config import Settings, get_settings
from .db import Database
from .embeddings import Embedder
from .llm.base import QuotaExhausted
from .llm.router import LLMRouter

log = logging.getLogger(__name__)


@dataclass
class BatchStats:
    batch_id: str = ""
    scout: dict[str, Any] = field(default_factory=dict)
    analysed: int = 0
    killed_by_gatekeeper: int = 0
    killed_by_score: int = 0
    packages_built: int = 0
    tiers: dict[str, int] = field(default_factory=dict)
    rejected_rewrites: int = 0
    llm_calls: int = 0
    llm_cost_usd: float = 0.0
    quota_exhausted: bool = False
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scout": self.scout,
            "analysed": self.analysed,
            "killed_by_gatekeeper": self.killed_by_gatekeeper,
            "killed_by_score": self.killed_by_score,
            "packages_built": self.packages_built,
            "tiers": self.tiers,
            "rejected_rewrites": self.rejected_rewrites,
            "llm_calls": self.llm_calls,
            "llm_cost_usd": round(self.llm_cost_usd, 6),
            "quota_exhausted": self.quota_exhausted,
            "errors": self.errors[:20],
        }


class BatchRunner:
    def __init__(self, db: Database, settings: Settings | None = None, llm: LLMRouter | None = None):
        self.db = db
        self.settings = settings or get_settings()
        self.llm = llm or LLMRouter(self.settings, db)
        self.embedder = Embedder(self.settings)

        self.scout = Scout(db, self.settings, self.embedder)
        self.analyst = Analyst(db, self.llm, self.settings)
        self.gatekeeper = Gatekeeper(db, self.settings)
        self.tailor = Tailor(db, self.llm, self.settings, self.embedder)
        self.scribe = Scribe(db, self.llm, self.settings)
        self.connector = Connector(db, self.llm, self.settings)

    async def run(self, kind: str = "scheduled", skip_scout: bool = False) -> BatchStats:
        self.llm.reset_budget()
        rows = await self.db.insert("batches", {"kind": kind, "status": "running"})
        batch_id = rows[0]["id"] if rows else ""
        stats = BatchStats(batch_id=batch_id)
        log.info("batch %s started (%s)", batch_id, kind)

        try:
            if not skip_scout:
                scout_result = await self.scout.run()
                stats.scout = scout_result.as_dict()
                log.info("scout: %s", stats.scout)

            profile = await self.db.select_one("profile", limit=1) or {}
            if not profile:
                stats.errors.append("no profile row — packages will be thin")

            bias = DecisionBias(self.db)
            await bias.load()

            jobs = await self._jobs_to_process()
            log.info("batch %s: %d jobs to process", batch_id, len(jobs))

            for job in jobs:
                if self.llm.budget_remaining <= 0:
                    stats.quota_exhausted = True
                    log.warning(
                        "batch %s: LLM budget spent with %d jobs unprocessed; they roll to the "
                        "next batch", batch_id, len(jobs) - stats.analysed
                    )
                    break
                try:
                    await self._process_job(job, profile, bias, batch_id, stats)
                except QuotaExhausted as exc:
                    stats.quota_exhausted = True
                    stats.errors.append(str(exc))
                    break
                except Exception as exc:
                    log.exception("job %s failed", job.get("id"))
                    stats.errors.append(f"job {job.get('id')}: {type(exc).__name__}: {exc}"[:300])

            status = "partial" if (stats.errors or stats.quota_exhausted) else "ok"
        except Exception as exc:
            log.exception("batch %s failed", batch_id)
            stats.errors.append(f"{type(exc).__name__}: {exc}"[:500])
            status = "failed"

        stats.llm_calls = self.llm.calls_this_batch
        stats.llm_cost_usd = self.llm.cost_this_batch
        if batch_id:
            await self.db.update(
                "batches",
                {
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "status": status,
                    "stats": stats.as_dict(),
                    "error": "; ".join(stats.errors[:3]) or None,
                },
                eq={"id": batch_id},
                returning=False,
            )
        log.info("batch %s finished: %s", batch_id, stats.as_dict())
        return stats

    async def _jobs_to_process(self) -> list[dict[str, Any]]:
        """Unanalysed jobs, newest first. A job the Gatekeeper already killed
        carries ``killed_reason`` and is never reconsidered for free."""
        jobs = await self.db.select(
            "jobs",
            columns="*,companies(id,name,domain,ats_type,uk_sponsor_licensed,"
            "nl_recognised_sponsor,hires_internationally,email_pattern)",
            eq={"analysis": None},
            order="discovered_at.desc",
            limit=self.settings.scout_max_jobs_per_batch,
        )
        return jobs

    async def _process_job(
        self,
        job: dict[str, Any],
        profile: dict[str, Any],
        bias: DecisionBias,
        batch_id: str,
        stats: BatchStats,
    ) -> None:
        company = job.get("companies") or {}
        job["company_name"] = company.get("name")

        # ── Analyst: one cheap call ───────────────────────────────────────
        analysis = await self.analyst.analyse(job, batch_id)
        await self.analyst.persist(job["id"], analysis)
        job["analysis"] = analysis
        stats.analysed += 1

        # ── Gatekeeper: free, and it runs before anything expensive ───────
        eligibility = await self.gatekeeper.evaluate(job, company, profile)
        await self.db.update(
            "jobs", {"track": eligibility.track}, eq={"id": job["id"]}, returning=False
        )

        if eligibility.signals.get("eor_mentioned") and company.get("id"):
            await self.gatekeeper.record_international_hire(
                company["id"], "EOR language found in a posting"
            )

        if not eligibility.passed:
            stats.killed_by_gatekeeper += 1
            await self.db.update(
                "jobs",
                {"killed_reason": "; ".join(eligibility.blockers)[:500]},
                eq={"id": job["id"]},
                returning=False,
            )
            return

        # ── Score before building: a low score is another free kill ───────
        bullets = await self.tailor.retrieve_bullets(job, analysis)
        score = score_package(
            ScoringInputs(
                job=job,
                analysis=analysis,
                eligibility=eligibility,
                bullets=bullets,
                profile=profile,
                bias=bias.nudge(company.get("id"), eligibility.track),
            ),
            self.settings,
        )
        tier = assign_tier(score.weighted, eligibility, self.settings)
        if tier is None:
            stats.killed_by_score += 1
            await self.db.update(
                "jobs",
                {"killed_reason": f"scored {score.weighted} (raw {score.raw}), below the floor"},
                eq={"id": job["id"]},
                returning=False,
            )
            return

        # ── Everything past here is the expensive half ────────────────────
        tailored = await self.tailor.tailor(job, analysis, profile, batch_id)
        stats.rejected_rewrites += tailored.rejected

        written = await self.scribe.write(
            job, analysis, profile, tailored.bullets, company, eligibility.as_dict(), batch_id
        )
        connected = await self.connector.run(
            job, company, profile, tailored.bullets, analysis, batch_id
        )

        package_rows = await self.db.insert(
            "packages",
            {
                "job_id": job["id"],
                "status": "queued",
                "tier": tier,
                "fit_score": score.weighted,
                "fit_rationale": score.rationale,
                "reasons_against": score.reasons_against,
                "eligibility": eligibility.as_dict(),
                "resume_diff": tailored.diff,
                "cover_letter": written.cover_letter,
                "screening_answers": written.as_answers_json(),
                "outreach_drafts": connected.drafts,
                "referral_plan": connected.referral_plan,
                "score_components": score.components,
                "warnings": (written.warnings + connected.notes)[:12],
                "batch_id": batch_id,
            },
        )
        if not package_rows:
            stats.errors.append(f"package insert returned nothing for job {job['id']}")
            return

        package_id = package_rows[0]["id"]
        if tailored.docx:
            if path := await self.tailor.upload(package_id, tailored.docx):
                await self.db.update(
                    "packages", {"resume_url": path}, eq={"id": package_id}, returning=False
                )

        stats.packages_built += 1
        stats.tiers[tier] = stats.tiers.get(tier, 0) + 1
