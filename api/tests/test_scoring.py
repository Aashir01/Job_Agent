"""§2 priority weighting and §7 tiering."""
from __future__ import annotations

from app.agents.gatekeeper import Eligibility
from app.agents.scoring import DecisionBias, ScoringInputs, assign_tier, score_package

BULLETS = [
    {"id": "b1", "text": "Built a RAG pipeline in Python with LangChain and FastAPI",
     "tags": ["rag", "fastapi"], "strength": 5, "similarity": 0.82, "metric": "38%"},
    {"id": "b2", "text": "Shipped an evaluation harness measuring retrieval precision",
     "tags": ["evaluation"], "strength": 4, "similarity": 0.61},
]
ANALYSIS = {
    "required_skills": ["Python", "RAG", "FastAPI", "LangChain"],
    "nice_to_haves": ["Evaluation"],
    "seniority": "senior",
    "salary_max": 140000,
}


def _inputs(track, profile, verdict="clear", **kw):
    return ScoringInputs(
        job={"title": "Senior AI Engineer", "salary_max": 140000},
        analysis={**ANALYSIS, **kw.pop("analysis", {})},
        eligibility=Eligibility(verdict, track, ["eligibility is clean"], [], {}),
        bullets=kw.pop("bullets", BULLETS),
        profile=profile,
        **kw,
    )


def test_track_multipliers_match_the_spec(settings, profile):
    scores = {
        track: score_package(_inputs(track, profile), settings)
        for track in ("remote_fte", "relocation", "contract")
    }
    assert scores["remote_fte"].multiplier == 1.00
    assert scores["relocation"].multiplier == 0.70
    assert scores["contract"].multiplier == 0.40
    # Identical raw fit, so the ordering is purely the priority policy.
    assert len({s.raw for s in scores.values()}) == 1
    assert (
        scores["remote_fte"].weighted
        > scores["relocation"].weighted
        > scores["contract"].weighted
    )


def test_a_relocation_role_must_be_much_stronger_to_outrank_a_remote_one(settings, profile):
    """§2: 'meaningfully stronger', not marginally."""
    weak_remote = score_package(
        _inputs("remote_fte", profile, analysis={"required_skills": ["Python", "Rust", "Go", "Scala"]}),
        settings,
    )
    perfect_relocation = score_package(_inputs("relocation", profile), settings)
    assert perfect_relocation.raw > weak_remote.raw
    assert perfect_relocation.weighted <= weak_remote.weighted + 5


def test_blocked_eligibility_never_produces_a_package(settings):
    blocked = Eligibility("blocked", "remote_fte", [], ["no sponsorship"], {})
    assert assign_tier(99, blocked, settings) is None


def test_uncertain_eligibility_never_rides_the_fast_lane(settings):
    """§7: the uncertain case is exactly what a human has to look at."""
    uncertain = Eligibility("uncertain", "remote_fte", [], [], {})
    assert assign_tier(98, uncertain, settings) == "standard"


def test_tier_boundaries(settings):
    clean = Eligibility("clear", "remote_fte", ["ok"], [], {})
    assert assign_tier(85, clean, settings) == "fast_lane"
    assert assign_tier(84, clean, settings) == "standard"
    assert assign_tier(70, clean, settings) == "standard"
    assert assign_tier(69, clean, settings) == "marginal"
    assert assign_tier(59, clean, settings) is None


def test_missing_skills_appear_in_reasons_against(settings, profile):
    score = score_package(
        _inputs("remote_fte", profile,
                analysis={"required_skills": ["Python", "Kubernetes", "Terraform"]}),
        settings,
    )
    assert "Kubernetes" in score.reasons_against


def test_no_bullets_is_scored_as_no_evidence(settings, profile):
    score = score_package(_inputs("remote_fte", profile, bullets=[]), settings)
    assert score.components["evidence"] == 0.0
    assert "no bullet_bank evidence" in score.reasons_against


async def test_decision_bias_reflects_past_verdicts(db):
    db.tables["decisions"] = [
        {"verdict": "rejected", "packages": {"jobs": {"company_id": "c1", "track": "contract"}}},
        {"verdict": "rejected", "packages": {"jobs": {"company_id": "c1", "track": "contract"}}},
    ]
    bias = DecisionBias(db)
    await bias.load()
    assert bias.nudge("c1", None) < 0
    assert bias.nudge("unknown-company", None) == 0.0


async def test_decision_bias_is_bounded(db):
    db.tables["decisions"] = [
        {"verdict": "approved", "packages": {"jobs": {"company_id": "c1", "track": "remote_fte"}}}
    ] * 40
    bias = DecisionBias(db)
    await bias.load()
    assert abs(bias.nudge("c1", "remote_fte")) <= DecisionBias.MAX_NUDGE
