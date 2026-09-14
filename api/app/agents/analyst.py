"""Analyst: one cheap LLM call per job, strict JSON out (§6).

Everything downstream reads this parse instead of the raw JD, so the JD is
tokenised once and the Gatekeeper, Tailor and Scribe all agree on the facts.
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import Settings, get_settings
from ..db import Database
from ..llm.base import LLMError, QuotaExhausted
from ..llm.router import LLMRouter

log = logging.getLogger(__name__)

# Gemini enforces this server-side; Groq gets it restated in the prompt.
ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "required_skills": {"type": "array", "items": {"type": "string"}},
        "nice_to_haves": {"type": "array", "items": {"type": "string"}},
        "seniority": {
            "type": "string",
            "enum": ["intern", "junior", "mid", "senior", "staff", "principal", "lead", "unknown"],
        },
        "employment_type": {
            "type": "string",
            "enum": ["full_time", "contract", "part_time", "internship", "unknown"],
        },
        "salary_min": {"type": "integer"},
        "salary_max": {"type": "integer"},
        "salary_currency": {"type": "string"},
        "salary_is_inferred": {"type": "boolean"},
        "remote_policy": {
            "type": "string",
            "enum": ["global", "geo_restricted", "hybrid", "onsite", "unknown"],
        },
        "geo_restriction": {
            "type": "array",
            "items": {"type": "string"},
            "description": "ISO country or region codes the role is restricted to, e.g. US, EU, UK",
        },
        "geo_evidence": {"type": "string"},
        "sponsorship_language": {
            "type": "string",
            "enum": ["offers_sponsorship", "no_sponsorship", "eor_or_contractor", "silent"],
        },
        "sponsorship_evidence": {"type": "string"},
        "screening_questions": {"type": "array", "items": {"type": "string"}},
        "resume_keywords": {"type": "array", "items": {"type": "string"}},
        "company_facts": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "required_skills",
        "seniority",
        "remote_policy",
        "geo_restriction",
        "sponsorship_language",
        "resume_keywords",
    ],
}

SYSTEM = (
    "You extract structured facts from job descriptions. You never guess and never "
    "flatter the posting. If the description does not say something, use the 'unknown' "
    "or 'silent' value and leave the evidence field empty. Quote the description "
    "verbatim in evidence fields — never paraphrase evidence."
)

PROMPT = """Extract structured facts from this job posting.

COMPANY: {company}
TITLE: {title}
LOCATION AS POSTED: {location}
SOURCE: {source}

DESCRIPTION:
{description}

Rules:
- geo_restriction: list the places a candidate MUST be in. "Remote (US)" -> ["US"].
  "Remote - EMEA" -> ["EMEA"]. Genuinely worldwide -> []. A posting that says
  "remote" but also "must reside in X" IS restricted to X.
- remote_policy: "global" only when the posting places no location requirement at all.
- sponsorship_language: "no_sponsorship" for "we cannot sponsor" / "must have existing
  right to work"; "offers_sponsorship" for explicit visa support; "eor_or_contractor"
  when they mention an employer of record, Deel, Remote.com, Oyster, Velocity Global,
  or hiring as an international contractor; "silent" when the posting says nothing.
- salary: only fill these if the posting states a figure, unless you set
  salary_is_inferred true, in which case give a market band for the role and location.
- resume_keywords: 8-12 exact terms from this posting a resume should mirror.
- screening_questions: only those actually visible in the posting. Otherwise [].
- company_facts: up to 3 concrete facts about the company stated in the posting
  (funding, product, scale). Empty if the posting is generic.

Return the JSON object only."""


def _empty_analysis(reason: str) -> dict[str, Any]:
    return {
        "required_skills": [],
        "nice_to_haves": [],
        "seniority": "unknown",
        "employment_type": "unknown",
        "remote_policy": "unknown",
        "geo_restriction": [],
        "geo_evidence": "",
        "sponsorship_language": "silent",
        "sponsorship_evidence": "",
        "screening_questions": [],
        "resume_keywords": [],
        "company_facts": [],
        "analysis_error": reason,
    }


def _coerce(data: dict[str, Any]) -> dict[str, Any]:
    """Normalise whatever the model returned into the shape downstream expects."""
    out = _empty_analysis("")
    out.pop("analysis_error")

    def as_list(key: str, limit: int = 30) -> list[str]:
        value = data.get(key)
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return []
        return [str(v).strip() for v in value if str(v).strip()][:limit]

    out["required_skills"] = as_list("required_skills")
    out["nice_to_haves"] = as_list("nice_to_haves")
    out["screening_questions"] = as_list("screening_questions", 20)
    out["resume_keywords"] = as_list("resume_keywords", 12)
    out["company_facts"] = as_list("company_facts", 3)
    out["geo_restriction"] = [g.strip().upper()[:16] for g in as_list("geo_restriction", 12)]

    seniority = str(data.get("seniority", "unknown")).lower()
    out["seniority"] = seniority if seniority in {
        "intern", "junior", "mid", "senior", "staff", "principal", "lead"
    } else "unknown"

    employment = str(data.get("employment_type", "unknown")).lower()
    out["employment_type"] = employment if employment in {
        "full_time", "contract", "part_time", "internship"
    } else "unknown"

    policy = str(data.get("remote_policy", "unknown")).lower()
    out["remote_policy"] = policy if policy in {
        "global", "geo_restricted", "hybrid", "onsite"
    } else "unknown"
    # A stated restriction outranks a "global" label: postings lie about this
    # constantly, and it is exactly what the Gatekeeper exists to catch.
    if out["geo_restriction"] and out["remote_policy"] == "global":
        out["remote_policy"] = "geo_restricted"

    sponsorship = str(data.get("sponsorship_language", "silent")).lower()
    out["sponsorship_language"] = sponsorship if sponsorship in {
        "offers_sponsorship", "no_sponsorship", "eor_or_contractor"
    } else "silent"

    for key in ("geo_evidence", "sponsorship_evidence"):
        value = data.get(key)
        out[key] = str(value).strip()[:600] if value else ""

    for key in ("salary_min", "salary_max"):
        try:
            value = int(data[key])
            out[key] = value if 1_000 <= value <= 5_000_000 else None
        except (KeyError, TypeError, ValueError):
            out[key] = None
    if out["salary_min"] and out["salary_max"] and out["salary_max"] < out["salary_min"]:
        out["salary_min"], out["salary_max"] = out["salary_max"], out["salary_min"]

    currency = data.get("salary_currency")
    out["salary_currency"] = str(currency).upper()[:4] if currency else None
    out["salary_is_inferred"] = bool(data.get("salary_is_inferred"))
    return out


class Analyst:
    agent = "analyst"

    def __init__(self, db: Database, llm: LLMRouter, settings: Settings | None = None):
        self.db = db
        self.llm = llm
        self.settings = settings or get_settings()

    async def analyse(self, job: dict[str, Any], batch_id: str | None = None) -> dict[str, Any]:
        prompt = PROMPT.format(
            company=job.get("company_name") or "unknown",
            title=job.get("title") or "",
            location=job.get("location_raw") or "not stated",
            source=job.get("source") or "",
            # The tail of a JD is boilerplate; the top carries the requirements.
            description=(job.get("description") or "")[:12_000],
        )
        try:
            data = await self.llm.generate_json(
                prompt,
                agent=self.agent,
                tier="cheap",
                schema=ANALYSIS_SCHEMA,
                system=SYSTEM,
                batch_id=batch_id,
                job_id=job.get("id"),
                max_tokens=1600,
            )
        except QuotaExhausted:
            raise
        except (LLMError, ValueError) as exc:
            log.warning("analyst failed for job %s: %s", job.get("id"), exc)
            return _empty_analysis(str(exc)[:300])
        return _coerce(data)

    async def persist(self, job_id: str, analysis: dict[str, Any]) -> None:
        await self.db.update(
            "jobs",
            {
                "analysis": analysis,
                "analysed_at": "now()",
                "remote_policy": analysis.get("remote_policy"),
                "geo_restriction": analysis.get("geo_restriction") or [],
                "salary_min": analysis.get("salary_min"),
                "salary_max": analysis.get("salary_max"),
                "currency": analysis.get("salary_currency"),
            },
            eq={"id": job_id},
            returning=False,
        )
