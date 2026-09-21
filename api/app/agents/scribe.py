"""Scribe: cover letter and screening answers (§6).

Four paragraphs, one specific recent company fact, and a draft answer to every
screening question the Analyst found. This is where the package's single
good-model call goes.

The same no-fabrication rule as the Tailor applies: every claim about the
user must come from the profile or the bullet bank, so both are handed to the
model as the only permitted source of facts, and the output is checked for
invented figures before it is stored.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

import httpx

from ..config import Settings, get_settings
from ..db import Database
from ..diff import numbers_in
from ..llm.base import LLMError, QuotaExhausted
from ..llm.router import LLMRouter
from .company_facts import CompanyFact, fetch_company_fact

log = logging.getLogger(__name__)

LETTER_SCHEMA = {
    "type": "object",
    "properties": {
        "cover_letter": {"type": "string"},
        "screening_answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["question", "answer"],
            },
        },
    },
    "required": ["cover_letter"],
}

SYSTEM = (
    "You draft job application material for one specific candidate. The profile and "
    "bullet list you are given are the ONLY facts about the candidate that exist. "
    "You may not add an employer, a technology, a metric, a degree, a year of "
    "experience or an outcome that is not in them. If the posting asks for something "
    "the candidate does not have, say plainly what they do have instead — never imply "
    "the gap is filled. Write plainly: no 'I am thrilled', no 'passionate', no "
    "'fast-paced environment', no filler."
)

PROMPT = """Draft a cover letter and screening answers.

## The candidate
{profile}

## Verified achievements — the only facts you may cite
{bullets}

## The role
Company: {company}
Title: {title}
Location: {location}
Required: {required}
Keywords they use: {keywords}

## One specific thing about this company
{fact}

## Job description (excerpt)
{description}

## Screening questions to answer
{questions}

Write the cover letter as exactly four paragraphs:
1. What the candidate does and why this specific role, naming the company fact above.
   If no fact is given, open with the role itself — do not invent one.
2. The single strongest matching achievement from the list, with its real number.
3. A second, different achievement covering another requirement of this posting.
4. Work arrangement and a plain close. {work_note}

Answer every screening question in two or three sentences, first person,
drawing only on the verified achievements. Mark confidence "low" on any answer
you could not fully support.

Return JSON: {{"cover_letter": "...", "screening_answers": [{{"question": "...", "answer": "...", "confidence": "high|medium|low"}}]}}"""

_BUZZ_RE = re.compile(
    r"\b(thrilled|excited to apply|passionate about|fast-paced|synergy|rockstar|ninja|"
    r"dynamic environment|think outside the box|hit the ground running)\b",
    re.I,
)

# Technologies a claim can hide behind. The figure check cannot see a sentence
# like "gained hands-on experience with Kubernetes and Docker" — there is no
# number in it — so names are checked against the candidate's own material
# instead. Kept to names that would matter if they were invented: a fabricated
# tool is the commonest drift, and it never carries a figure to trip over.
_TECH_TERMS = frozenset(
    """airflow kafka spark hadoop dbt snowflake databricks bigquery redshift mlflow sagemaker
    kubernetes k8s docker terraform ansible jenkins github actions gitlab circleci ci/cd cicd
    aws gcp azure vertex ai redis graphql grpc postgresql postgres mysql mongodb elasticsearch
    supabase pgvector faiss qdrant fastapi django flask langchain langgraph crewai
    pytorch tensorflow scikit-learn pandas numpy python react nextjs typescript javascript rust""".split()
)

# Word boundaries so "java" does not fire on "javascript" and "rust" not on
# "trust". Only word characters count — a sentence-final "Kubernetes." must still
# match, which is why '.' is not treated as part of the term.
_TECH_RE = {
    term: re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.I)
    for term in sorted(_TECH_TERMS)
}


@dataclass
class ScribeResult:
    cover_letter: str = ""
    screening_answers: list[dict[str, Any]] = field(default_factory=list)
    company_fact: CompanyFact | None = None
    warnings: list[str] = field(default_factory=list)

    def as_answers_json(self) -> dict[str, Any]:
        return {
            "answers": self.screening_answers,
            "company_fact": (
                {
                    "text": self.company_fact.text,
                    "source": self.company_fact.source,
                    "url": self.company_fact.url,
                }
                if self.company_fact
                else None
            ),
            "warnings": self.warnings,
        }


def _unevidenced_technologies(text: str, evidence: str) -> list[str]:
    """Technologies named in the draft that appear nowhere in the evidence."""
    haystack = (evidence or "").lower()
    return [term for term, rx in _TECH_RE.items() if term not in haystack and rx.search(text)]


def audit_claims(text: str, allowed_numbers: set[str], evidence: str = "") -> list[str]:
    """Flag claims that appear nowhere in the verified material.

    Years ("2024") and small counts are ignored — the interesting fabrications
    are percentages and magnitudes.

    ``evidence`` is the candidate's own material — their bullets, profile and
    the company fact they were told to cite. The job description is deliberately
    excluded: it says what the employer wants, not what the candidate has done,
    so a skill that appears only there is still an unevidenced claim. Passing it
    switches on the technology check; the figure check runs either way.
    """
    warnings = []
    for number in numbers_in(text):
        if number in allowed_numbers:
            continue
        bare = number.rstrip("%")
        if bare.isdigit() and (len(bare) == 4 and bare.startswith(("19", "20")) or int(bare) <= 12):
            continue
        warnings.append(f"unverified figure in the draft: {number}")
    if evidence:
        for term in _unevidenced_technologies(text, evidence):
            warnings.append(
                f"technology with no evidence in the profile or bullet bank: {term}"
            )
    if match := _BUZZ_RE.search(text):
        warnings.append(f"filler phrase to edit out: “{match.group(0)}”")
    return warnings


class Scribe:
    agent = "scribe"

    def __init__(self, db: Database, llm: LLMRouter, settings: Settings | None = None):
        self.db = db
        self.llm = llm
        self.settings = settings or get_settings()

    async def write(
        self,
        job: dict[str, Any],
        analysis: dict[str, Any],
        profile: dict[str, Any],
        bullets: Sequence[Any],
        company: dict[str, Any] | None = None,
        eligibility: dict[str, Any] | None = None,
        batch_id: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> ScribeResult:
        company = company or {}
        fact = await fetch_company_fact(
            company.get("domain"),
            company.get("name") or "",
            analysis.get("company_facts"),
            client=client,
        )

        bullet_lines = []
        allowed_numbers: set[str] = set()
        evidence_parts: list[str] = []
        for bullet in bullets:
            text = getattr(bullet, "final", None) or (
                bullet.get("text") if isinstance(bullet, dict) else str(bullet)
            )
            context = getattr(bullet, "role_context", None) or (
                bullet.get("role_context") if isinstance(bullet, dict) else ""
            )
            bullet_lines.append(f"- [{context}] {text}")
            allowed_numbers |= numbers_in(text)
            evidence_parts += [text, context]
        allowed_numbers |= numbers_in(str(profile.get("years_experience") or ""))
        # The audit's allow-list: what the candidate can legitimately claim, plus
        # the company fact they were told to name. The job description is not in
        # it — naming a requirement is not the same as having the experience.
        evidence = " ".join(
            evidence_parts + [self._evidence_block(profile), fact.cite() if fact else ""]
        )

        questions = analysis.get("screening_questions") or []
        work_note = self._work_note(eligibility or {}, profile)

        prompt = PROMPT.format(
            profile=self._profile_block(profile),
            bullets="\n".join(bullet_lines) or "(none — do not claim any achievement)",
            company=company.get("name") or "the company",
            title=job.get("title") or "",
            location=job.get("location_raw") or "not stated",
            required=", ".join(analysis.get("required_skills") or []) or "not stated",
            keywords=", ".join(analysis.get("resume_keywords") or []) or "none",
            fact=fact.cite() if fact else "(none found — do not invent one)",
            description=(job.get("description") or "")[:3500],
            questions="\n".join(f"- {q}" for q in questions) or "(none visible in the posting)",
            work_note=work_note,
        )

        try:
            data = await self.llm.generate_json(
                prompt,
                agent=self.agent,
                tier="good",  # §6: the one good-model call per package
                schema=LETTER_SCHEMA,
                system=SYSTEM,
                temperature=0.35,
                max_tokens=2200,
                batch_id=batch_id,
                job_id=job.get("id"),
            )
        except QuotaExhausted:
            raise
        except (LLMError, ValueError) as exc:
            log.warning("scribe failed for job %s: %s", job.get("id"), exc)
            return ScribeResult(warnings=[f"cover letter not drafted: {exc}"[:300]], company_fact=fact)

        letter = str(data.get("cover_letter") or "").strip()
        answers = []
        for item in data.get("screening_answers") or []:
            if isinstance(item, dict) and item.get("question"):
                answers.append(
                    {
                        "question": str(item["question"])[:500],
                        "answer": str(item.get("answer") or "")[:2000],
                        "confidence": str(item.get("confidence") or "medium").lower(),
                    }
                )

        warnings = audit_claims(letter, allowed_numbers, evidence)
        for answer in answers:
            warnings += [
                f"{w} (screening answer)"
                for w in audit_claims(answer["answer"], allowed_numbers, evidence)
            ]
        unanswered = [q for q in questions if not any(a["question"][:40] in q or q[:40] in a["question"] for a in answers)]
        if unanswered:
            warnings.append(f"{len(unanswered)} screening question(s) left unanswered")

        return ScribeResult(letter, answers, fact, warnings[:12])

    def _profile_block(self, profile: dict[str, Any]) -> str:
        links = profile.get("links") or {}
        parts = [
            f"Name: {profile.get('full_name') or ''}",
            f"Headline: {profile.get('headline') or ''}",
            f"Based in: {profile.get('location') or ''}",
        ]
        if years := profile.get("years_experience"):
            parts.append(f"Years of experience: {years}")
        if links:
            parts.append("Links: " + ", ".join(f"{k}: {v}" for k, v in links.items() if v))
        return "\n".join(parts)

    def _evidence_block(self, profile: dict[str, Any]) -> str:
        """Everything the candidate can legitimately claim.

        Wider than ``_profile_block``, which is only prompt copy: this is the
        audit's allow-list, so it carries the skills, roles, education and
        projects the model is not shown but which the candidate genuinely owns.
        """
        return " ".join(
            [
                str(profile.get("headline") or ""),
                " ".join(profile.get("skills") or []),
                json.dumps(profile.get("roles") or []),
                json.dumps(profile.get("education") or []),
                json.dumps(profile.get("projects") or []),
            ]
        )

    def _work_note(self, eligibility: dict[str, Any], profile: dict[str, Any]) -> str:
        """Tell the truth about work authorisation, in one clause."""
        work_auth = profile.get("work_auth") or {}
        track = eligibility.get("track", "remote_fte")
        if track == "relocation":
            return (
                "State plainly that the candidate would relocate and requires visa "
                "sponsorship, and that they are ready to start the process."
            )
        if work_auth.get("needs_sponsorship", True):
            return (
                f"State that the candidate works remotely from "
                f"{profile.get('location') or 'their location'}, is available in overlapping "
                "hours, and can be engaged through an employer of record or as a contractor. "
                "Do not claim existing work authorisation anywhere."
            )
        return "State availability and preferred working arrangement in one sentence."
