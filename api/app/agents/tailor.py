"""Tailor: select, reorder, lightly reword. Never invent (§6, §10).

The hard rule — "output must be traceable to a bullet_bank row" — is enforced
mechanically, after the model speaks, not by asking the model nicely:

  1. every figure in a rewritten bullet must already exist in its source bullet
  2. every content word must come from the source bullet or the job description
  3. the rewrite may not balloon in length

A rewrite that fails any check is discarded and the user's own wording is used
verbatim. The rejection is recorded in the diff so the user can see the model
tried to drift.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from ..config import Settings, get_settings
from ..db import Database
from ..diff import build_resume_diff, numbers_in
from ..docx_render import render_resume
from ..embeddings import Embedder
from ..llm.base import LLMError, QuotaExhausted
from ..llm.router import LLMRouter

log = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z][a-z0-9+#.\-]*")

# Function words a rewrite may use freely: they carry no claim.
CONNECTORS = frozenset(
    """a an the and or but for to of in on at by with from as is are was were be been being
    that this these those it its into over under across through during while when where which
    who whom whose than then so such using used use via per about after before within between
    up down out off no not more most less least also both each other another all any some
    own same very can will would should could may might must our we i my me us their them
    they he she you your his her new first second third led drove built made ran did done""".split()
)

# Verbs the user's own bullets already imply — allowed as connective tissue when
# rewording, because they restate rather than add. Anything stronger (e.g.
# "architected", "spearheaded") must already appear in the source bullet.
SAFE_VERBS = frozenset(
    """developed created delivered implemented improved reduced increased shipped
    maintained supported wrote tested deployed automated designed integrated scaled
    optimized optimised migrated refactored owned analysed analyzed measured""".split()
)


def _words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall((text or "").lower()) if len(w) > 1}


@dataclass
class TailoredBullet:
    bullet_id: str
    role_context: str
    original: str
    final: str
    similarity: float = 0.0
    strength: int = 3
    metric: str | None = None
    rejected_rewrite: str | None = None
    reject_reason: str | None = None

    @property
    def changed(self) -> bool:
        return self.original.strip() != self.final.strip()


@dataclass
class TailorResult:
    bullets: list[TailoredBullet] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    summary: str = ""
    docx: bytes = b""
    diff: dict[str, Any] = field(default_factory=dict)
    rejected: int = 0


def verify_rewrite(original: str, rewrite: str, jd_vocabulary: set[str]) -> tuple[bool, str]:
    """The traceability gate. Returns (accepted, reason_if_rejected)."""
    rewrite = (rewrite or "").strip()
    if not rewrite:
        return False, "empty rewrite"

    original_numbers = numbers_in(original)
    for number in numbers_in(rewrite):
        if number not in original_numbers:
            return False, f"introduced a figure not in the source bullet: {number}"

    if len(rewrite) > len(original) * 1.6 + 24:
        return False, "rewrite is substantially longer than the source bullet"

    allowed = _words(original) | jd_vocabulary | CONNECTORS | SAFE_VERBS
    invented = sorted(w for w in _words(rewrite) if w not in allowed)
    # Allow at most one stray token — plurals and tense shifts are legitimate.
    stems_ok = [
        w for w in invented
        if not any(w.startswith(a[:5]) or a.startswith(w[:5]) for a in allowed if len(a) >= 5)
    ]
    if stems_ok:
        return False, f"introduced unsupported terms: {', '.join(stems_ok[:4])}"
    return True, ""


REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "bullets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
                "required": ["id", "text"],
            },
        }
    },
    "required": ["bullets"],
}

SYSTEM = (
    "You reword existing resume bullets to mirror a job description's vocabulary. "
    "You are forbidden from adding any experience, technology, metric, employer or "
    "outcome that is not already present in the bullet you are given. You may "
    "substitute a synonym the job description uses, reorder a clause, or tighten "
    "wording. If a bullet cannot be improved without adding something, return it "
    "unchanged. Adding anything is a failure, not a helpful initiative."
)

PROMPT = """Reword these resume bullets to mirror this job posting's vocabulary.

JOB TITLE: {title}
TERMS THIS POSTING USES: {keywords}
REQUIRED SKILLS: {skills}

BULLETS (reword each; keep every figure exactly as written):
{bullets}

Return JSON: {{"bullets": [{{"id": "<the id given>", "text": "<reworded>"}}]}}
Every id must appear exactly once. Change nothing you cannot justify from the
bullet's own text."""


class Tailor:
    agent = "tailor"

    def __init__(
        self,
        db: Database,
        llm: LLMRouter,
        settings: Settings | None = None,
        embedder: Embedder | None = None,
    ):
        self.db = db
        self.llm = llm
        self.settings = settings or get_settings()
        self.embedder = embedder or Embedder(self.settings)

    async def retrieve_bullets(self, job: dict[str, Any], analysis: dict[str, Any]) -> list[dict]:
        query = "\n".join(
            filter(
                None,
                [
                    job.get("title"),
                    " ".join(analysis.get("required_skills") or []),
                    " ".join(analysis.get("resume_keywords") or []),
                    (job.get("description") or "")[:3000],
                ],
            )
        )
        embedding = await self.embedder.embed(query)
        try:
            rows = await self.db.rpc(
                "match_bullets",
                {
                    "query_embedding": embedding,
                    "match_count": self.settings.tailor_bullet_count,
                    "min_strength": self.settings.tailor_min_bullet_strength,
                },
            )
        except Exception as exc:
            log.warning("match_bullets rpc failed (%s); falling back to a plain read", exc)
            rows = await self.db.select(
                "bullet_bank",
                columns="id,role_context,text,metric,tags,strength",
                order="strength.desc",
                limit=self.settings.tailor_bullet_count,
            )
        return rows or []

    async def tailor(
        self,
        job: dict[str, Any],
        analysis: dict[str, Any],
        profile: dict[str, Any],
        batch_id: str | None = None,
    ) -> TailorResult:
        bullets = await self.retrieve_bullets(job, analysis)
        if not bullets:
            log.warning("bullet_bank is empty — cannot build a resume for job %s", job.get("id"))
            return TailorResult()

        # Reorder: relevance first, then the user's own strength rating.
        bullets = sorted(
            bullets,
            key=lambda b: ((b.get("similarity") or 0) * 0.75 + (b.get("strength") or 3) / 5 * 0.25),
            reverse=True,
        )

        jd_vocabulary = _words(
            " ".join(
                (analysis.get("resume_keywords") or [])
                + (analysis.get("required_skills") or [])
                + (analysis.get("nice_to_haves") or [])
                + [job.get("title") or ""]
            )
        )

        rewrites = await self._rewrite(job, analysis, bullets, batch_id)

        tailored: list[TailoredBullet] = []
        rejected = 0
        for bullet in bullets:
            bullet_id = str(bullet["id"])
            original = (bullet.get("text") or "").strip()
            candidate = (rewrites.get(bullet_id) or "").strip()
            final, rejected_text, reason = original, None, None

            if candidate and candidate != original:
                ok, why = verify_rewrite(original, candidate, jd_vocabulary)
                if ok:
                    final = candidate
                else:
                    rejected += 1
                    rejected_text, reason = candidate, why
                    log.info("tailor rejected a rewrite of %s: %s", bullet_id, why)

            tailored.append(
                TailoredBullet(
                    bullet_id=bullet_id,
                    role_context=bullet.get("role_context") or "Experience",
                    original=original,
                    final=final,
                    similarity=round(bullet.get("similarity") or 0.0, 4),
                    strength=bullet.get("strength") or 3,
                    metric=bullet.get("metric"),
                    rejected_rewrite=rejected_text,
                    reject_reason=reason,
                )
            )

        skills = self._skills(analysis, bullets, profile)
        summary = self._summary(profile, analysis, skills)
        docx = self._render(profile, tailored, skills, summary)
        diff = build_resume_diff(
            [
                {
                    "bullet_id": b.bullet_id,
                    "role_context": b.role_context,
                    "original": b.original,
                    "final": b.final,
                    "rejected_rewrite": b.rejected_rewrite,
                    "reject_reason": b.reject_reason,
                    "similarity": b.similarity,
                }
                for b in tailored
            ]
        )
        diff["rejected_rewrites"] = rejected
        return TailorResult(tailored, skills, summary, docx, diff, rejected)

    async def _rewrite(
        self,
        job: dict[str, Any],
        analysis: dict[str, Any],
        bullets: Sequence[dict],
        batch_id: str | None,
    ) -> dict[str, str]:
        listing = "\n".join(f"[{b['id']}] {b.get('text', '')}" for b in bullets)
        prompt = PROMPT.format(
            title=job.get("title") or "",
            keywords=", ".join(analysis.get("resume_keywords") or []) or "none extracted",
            skills=", ".join(analysis.get("required_skills") or []) or "none extracted",
            bullets=listing,
        )
        try:
            data = await self.llm.generate_json(
                prompt,
                agent=self.agent,
                tier="cheap",
                schema=REWRITE_SCHEMA,
                system=SYSTEM,
                temperature=0.15,
                max_tokens=2000,
                batch_id=batch_id,
                job_id=job.get("id"),
            )
        except QuotaExhausted:
            raise
        except (LLMError, ValueError) as exc:
            log.warning("tailor rewrite failed (%s); using bullets verbatim", exc)
            return {}
        out: dict[str, str] = {}
        for item in data.get("bullets") or []:
            if isinstance(item, dict) and item.get("id"):
                out[str(item["id"])] = str(item.get("text") or "")
        return out

    def _skills(
        self, analysis: dict[str, Any], bullets: Sequence[dict], profile: dict[str, Any]
    ) -> list[str]:
        """Only skills the bank can actually evidence. §10: no keyword stuffing."""
        evidence = _words(
            " ".join(
                [b.get("text", "") for b in bullets]
                + [t for b in bullets for t in (b.get("tags") or [])]
                + [profile.get("headline") or ""]
                + (profile.get("skills") or [])
            )
        )
        ordered: list[str] = []
        for skill in (analysis.get("required_skills") or []) + (analysis.get("resume_keywords") or []):
            if skill and skill not in ordered and _words(skill) & evidence:
                ordered.append(skill)
        for skill in profile.get("skills") or []:
            if skill not in ordered:
                ordered.append(skill)
        return ordered[:18]

    def _summary(self, profile: dict[str, Any], analysis: dict[str, Any], skills: list[str]) -> str:
        """Composed, not generated. Every clause comes from verified fields."""
        headline = profile.get("headline") or "Engineer"
        years = profile.get("years_experience")
        lead = f"{headline}"
        if years:
            lead += f" with {years} years of experience"
        top = ", ".join(skills[:5])
        if top:
            lead += f" across {top}"
        return lead.rstrip(".") + "."

    def _render(
        self,
        profile: dict[str, Any],
        bullets: Sequence[TailoredBullet],
        skills: list[str],
        summary: str,
    ) -> bytes:
        grouped: dict[str, list[str]] = {}
        for bullet in bullets:
            grouped.setdefault(bullet.role_context, []).append(bullet.final)

        roles_meta = {r.get("role_context") or r.get("title"): r for r in profile.get("roles") or []}
        experience = []
        for context, lines in grouped.items():
            meta = roles_meta.get(context, {})
            experience.append(
                {
                    "title": meta.get("title") or context,
                    "company": meta.get("company") or "",
                    "location": meta.get("location") or "",
                    "dates": meta.get("dates") or "",
                    "bullets": lines,
                }
            )
        return render_resume(
            profile,
            experience,
            skills,
            summary=summary,
            projects=profile.get("projects") or (),
            education=profile.get("education") or (),
        )

    async def upload(self, package_id: str, docx: bytes) -> str | None:
        """Store the .docx in Supabase storage; return its path."""
        if not docx:
            return None
        path = f"resumes/{package_id}.docx"
        url = f"{self.settings.supabase_url.rstrip('/')}/storage/v1/object/packages/{path}"
        key = self.settings.supabase_service_key
        try:
            resp = await self.db.client.post(
                url,
                content=docx,
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Type":
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "x-upsert": "true",
                },
            )
            if resp.status_code >= 400:
                log.error("resume upload failed %s: %s", resp.status_code, resp.text[:300])
                return None
        except Exception as exc:
            log.error("resume upload failed: %s", exc)
            return None
        return path
