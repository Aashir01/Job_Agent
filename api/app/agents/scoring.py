"""Fit scoring, track weighting (§2) and review tiering (§7).

The raw score is evidence-based and explainable — every point traces to a
stated requirement or a bullet in the bank. The track multiplier is applied
last, so a relocation role must be meaningfully stronger than a remote one to
outrank it, exactly as §2 requires.

§9 Sprint 4 closes the loop: past approve/reject decisions bias the score.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from ..config import Settings, get_settings
from ..db import Database
from .gatekeeper import Eligibility

log = logging.getLogger(__name__)

SENIORITY_RANK = {
    "intern": 0, "junior": 1, "mid": 2, "senior": 3,
    "lead": 4, "staff": 4, "principal": 5, "unknown": 2,
}

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.]*")


def _terms(values: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for value in values:
        for token in _TOKEN_RE.findall((value or "").lower()):
            if len(token) > 1:
                out.add(token)
        joined = " ".join(_TOKEN_RE.findall((value or "").lower()))
        if joined:
            out.add(joined)
    return out


@dataclass
class Score:
    raw: int
    weighted: int
    track: str
    multiplier: float
    rationale: str
    reasons_against: str
    components: dict[str, float] = field(default_factory=dict)


@dataclass
class ScoringInputs:
    job: dict[str, Any]
    analysis: dict[str, Any]
    eligibility: Eligibility
    bullets: Sequence[dict[str, Any]]
    profile: dict[str, Any]
    bias: float = 0.0


# Component weights sum to 100 before the track multiplier.
W_SKILLS = 42
W_ELIGIBILITY = 22
W_SENIORITY = 14
W_EVIDENCE = 12
W_SALARY = 10


def score_package(inputs: ScoringInputs, settings: Settings | None = None) -> Score:
    settings = settings or get_settings()
    job, analysis, elig = inputs.job, inputs.analysis, inputs.eligibility
    components: dict[str, float] = {}
    for_reasons: list[str] = []
    against: list[str] = []

    # ── skills overlap: what the JD demands vs what the bank can evidence ──
    required = [s for s in analysis.get("required_skills") or [] if s]
    nice = [s for s in analysis.get("nice_to_haves") or [] if s]
    bank_terms = _terms(
        [b.get("text", "") for b in inputs.bullets]
        + [t for b in inputs.bullets for t in (b.get("tags") or [])]
        + [inputs.profile.get("headline") or ""]
    )

    def covered(skills: Sequence[str]) -> list[str]:
        return [s for s in skills if _terms([s]) & bank_terms]

    hit_required = covered(required)
    hit_nice = covered(nice)

    if required:
        ratio = len(hit_required) / len(required)
        components["skills"] = W_SKILLS * ratio
        if hit_required:
            for_reasons.append(
                f"covers {len(hit_required)}/{len(required)} required skills "
                f"({', '.join(hit_required[:5])})"
            )
        missing = [s for s in required if s not in hit_required]
        if missing:
            against.append(f"no verified evidence for {', '.join(missing[:5])}")
    else:
        # An unparsed JD is not a strong match; it is an unknown one.
        components["skills"] = W_SKILLS * 0.45
        against.append("the posting lists no explicit requirements to match against")

    if nice:
        components["skills"] += min(4.0, 4.0 * len(hit_nice) / len(nice))
        if hit_nice:
            for_reasons.append(f"also covers nice-to-haves: {', '.join(hit_nice[:3])}")

    # ── eligibility: the Gatekeeper's verdict is worth real points ─────────
    verdict_points = {"clear": 1.0, "uncertain": 0.45, "blocked": 0.0}
    components["eligibility"] = W_ELIGIBILITY * verdict_points.get(elig.verdict, 0.0)
    if elig.verdict == "clear":
        for_reasons.append("eligibility is clean")
    elif elig.verdict == "uncertain":
        against.append("eligibility could not be confirmed")
    if elig.signals.get("eor_mentioned") or elig.signals.get("company_hires_internationally"):
        components["eligibility"] = min(W_ELIGIBILITY, components["eligibility"] + 4)
        for_reasons.append("company has a proven international hiring route")
    against.extend(elig.blockers[:3])

    # ── seniority fit ─────────────────────────────────────────────────────
    want = SENIORITY_RANK.get(analysis.get("seniority", "unknown"), 2)
    have = SENIORITY_RANK.get(str(inputs.profile.get("seniority", "senior")).lower(), 3)
    gap = want - have
    if gap <= 0:
        components["seniority"] = W_SENIORITY * (1.0 if gap >= -1 else 0.6)
        if gap < -1:
            against.append("the role is more junior than the profile")
    elif gap == 1:
        components["seniority"] = W_SENIORITY * 0.6
        against.append("the role is one level above the profile")
    else:
        components["seniority"] = W_SENIORITY * 0.2
        against.append(f"the role is {gap} levels above the profile")

    # ── bullet evidence strength ──────────────────────────────────────────
    if inputs.bullets:
        top = sorted(
            inputs.bullets, key=lambda b: (b.get("similarity") or 0), reverse=True
        )[:5]
        sim = sum((b.get("similarity") or 0) for b in top) / len(top)
        strength = sum((b.get("strength") or 3) for b in top) / (len(top) * 5)
        components["evidence"] = W_EVIDENCE * (0.6 * max(0.0, min(1.0, sim)) + 0.4 * strength)
        with_metrics = [b for b in top if b.get("metric")]
        if with_metrics:
            for_reasons.append(f"{len(with_metrics)} matching bullets carry hard numbers")
    else:
        components["evidence"] = 0.0
        against.append("no bullet_bank evidence matches this posting")

    # ── salary ────────────────────────────────────────────────────────────
    floor = inputs.profile.get("salary_floor_usd")
    smin = analysis.get("salary_min") or job.get("salary_min")
    smax = analysis.get("salary_max") or job.get("salary_max")
    if smax and floor:
        if smax >= floor:
            components["salary"] = W_SALARY
            for_reasons.append(f"pay tops out at {smax:,}, above the {floor:,} floor")
        elif smax >= floor * 0.8:
            components["salary"] = W_SALARY * 0.5
            against.append(f"pay tops out at {smax:,}, under the {floor:,} floor")
        else:
            components["salary"] = 0.0
            against.append(f"pay tops out at {smax:,}, well under the {floor:,} floor")
    elif smin or smax:
        components["salary"] = W_SALARY * 0.7
    else:
        components["salary"] = W_SALARY * 0.5
        against.append("no salary disclosed")

    raw = sum(components.values()) + inputs.bias
    raw_int = max(0, min(100, round(raw)))

    track = elig.track
    multiplier = settings.track_weights.get(track, 1.0)
    weighted = max(0, min(100, round(raw_int * multiplier)))

    if multiplier < 1.0:
        against.append(
            f"{track.replace('_', ' ')} track — weighted ×{multiplier:.2f} per the priority policy"
        )

    rationale = "; ".join(for_reasons[:6]) or "no positive signal beyond a parseable posting"
    reasons_against = "; ".join(dict.fromkeys(against))[:1200] or "none identified"

    return Score(
        raw=raw_int,
        weighted=weighted,
        track=track,
        multiplier=multiplier,
        rationale=rationale[:1200],
        reasons_against=reasons_against,
        components={k: round(v, 2) for k, v in components.items()},
    )


def assign_tier(score: int, eligibility: Eligibility, settings: Settings | None = None) -> str | None:
    """§7. Returns None when the package should not be built at all."""
    settings = settings or get_settings()
    if not eligibility.passed:
        return None
    if score < settings.tier_marginal_min:
        return None
    # Uncertain eligibility never rides the fast lane, however high it scores —
    # that is exactly the case a human has to look at.
    if eligibility.verdict == "uncertain":
        return "marginal" if score < settings.tier_standard_min else "standard"
    if score >= settings.tier_fast_lane_min:
        return "fast_lane"
    if score >= settings.tier_standard_min:
        return "standard"
    return "marginal"


class DecisionBias:
    """§9 Sprint 4: every approve/reject trains the scorer.

    Deliberately simple — a per-company and per-track running average of past
    verdicts, applied as a small additive nudge. It shifts borderline packages
    across a tier boundary; it cannot rescue a blocked one or manufacture a
    fast-lane pass.
    """

    MAX_NUDGE = 8.0

    def __init__(self, db: Database):
        self.db = db
        self.by_company: dict[str, float] = {}
        self.by_track: dict[str, float] = {}
        self.loaded = False

    async def load(self, limit: int = 500) -> None:
        try:
            rows = await self.db.select(
                "decisions",
                columns="verdict,package_id,packages(job_id,jobs(company_id,track))",
                order="decided_at.desc",
                limit=limit,
            )
        except Exception as exc:
            log.warning("decision bias unavailable (%s); scoring without it", exc)
            self.loaded = True
            return

        company_tally: dict[str, list[int]] = {}
        track_tally: dict[str, list[int]] = {}
        for row in rows:
            verdict = 1 if row.get("verdict") == "approved" else -1
            package = row.get("packages") or {}
            job = package.get("jobs") or {}
            if company_id := job.get("company_id"):
                company_tally.setdefault(company_id, []).append(verdict)
            if track := job.get("track"):
                track_tally.setdefault(track, []).append(verdict)

        self.by_company = {k: sum(v) / len(v) for k, v in company_tally.items() if len(v) >= 2}
        self.by_track = {k: sum(v) / len(v) for k, v in track_tally.items() if len(v) >= 5}
        self.loaded = True

    def nudge(self, company_id: str | None, track: str | None) -> float:
        value = 0.0
        if company_id and company_id in self.by_company:
            value += self.by_company[company_id] * 6.0
        if track and track in self.by_track:
            value += self.by_track[track] * 3.0
        return max(-self.MAX_NUDGE, min(self.MAX_NUDGE, value))
