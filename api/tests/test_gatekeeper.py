"""The Gatekeeper is where the money is saved. These are its load-bearing rules."""
from __future__ import annotations

import pytest

from app.agents.gatekeeper import (
    BLUE_CARD_SHORTAGE_THRESHOLD_EUR,
    Gatekeeper,
    find_geo_signals,
    find_kill_phrase,
)



def job(**kw):
    base = {
        "id": "j1",
        "title": "Senior AI Engineer",
        "description": "Build RAG systems.",
        "location_raw": "Remote",
        "analysis": {
            "remote_policy": "global",
            "geo_restriction": [],
            "sponsorship_language": "silent",
            "employment_type": "full_time",
            "required_skills": ["Python"],
        },
    }
    analysis = {**base["analysis"], **kw.pop("analysis", {})}
    return {**base, **kw, "analysis": analysis}


@pytest.mark.parametrize(
    "text",
    [
        "We are unable to offer visa sponsorship for this position.",
        "No visa sponsorship is available.",
        "Candidates must have existing right to work in the UK.",
        "You must already be authorized to work in the United States.",
        "Sponsorship is not available for this role.",
    ],
)
def test_kill_phrases_are_caught(text):
    assert find_kill_phrase(text) is not None


def test_innocent_text_is_not_killed():
    assert find_kill_phrase("We sponsor conferences and offer a learning budget.") is None


def test_geo_restriction_hidden_in_the_body_is_found():
    signals = find_geo_signals(
        "Fully remote role! Candidates must be located in the United States."
    )
    assert signals and "United States" in signals[0][1]


async def test_blocks_a_us_only_remote_role(db, profile):
    gate = Gatekeeper(db)
    result = await gate.evaluate(
        job(
            description="Remote (US only). You must already be authorized to work in the US.",
            analysis={"remote_policy": "geo_restricted", "geo_restriction": ["US"],
                      "sponsorship_language": "no_sponsorship"},
        ),
        company={"name": "Acme"},
        profile=profile,
    )
    assert result.verdict == "blocked"
    assert not result.passed
    assert result.blockers


async def test_eor_language_rescues_a_geo_restricted_role(db, profile):
    """§6: a company already on Deel can hire from Pakistan with no visa."""
    gate = Gatekeeper(db)
    result = await gate.evaluate(
        job(
            description="Remote (US preferred). We hire globally through Deel as our employer of record.",
            analysis={"remote_policy": "geo_restricted", "geo_restriction": ["US"],
                      "sponsorship_language": "eor_or_contractor"},
        ),
        company={"name": "Acme"},
        profile=profile,
    )
    assert result.passed
    assert result.track == "remote_fte"
    assert result.signals["eor_mentioned"]


async def test_company_flag_outweighs_boilerplate(db, profile):
    """The compounding flag is worth more than a copy-pasted legal line."""
    gate = Gatekeeper(db)
    result = await gate.evaluate(
        job(description="We cannot provide visa sponsorship.",
            analysis={"sponsorship_language": "no_sponsorship"}),
        company={"name": "Acme", "hires_internationally": True},
        profile=profile,
    )
    assert result.passed
    assert "kill_phrase_overridden" in result.signals


async def test_worldwide_remote_is_clear(db, profile):
    gate = Gatekeeper(db)
    result = await gate.evaluate(
        job(description="Work from anywhere in the world.", location_raw="Remote — Worldwide"),
        company={"name": "Acme"},
        profile=profile,
    )
    assert result.verdict == "clear"
    assert result.track == "remote_fte"


async def test_uk_role_blocked_when_not_on_the_register(db, profile):
    db.rpc_returns["is_licensed_sponsor"] = False
    gate = Gatekeeper(db)
    result = await gate.evaluate(
        job(location_raw="London, United Kingdom",
            analysis={"remote_policy": "onsite", "geo_restriction": ["UK"]}),
        company={"name": "Unlicensed Ltd"},
        profile=profile,
    )
    assert result.track == "relocation"
    assert result.verdict == "blocked"
    assert any("Register of Licensed Sponsors" in b for b in result.blockers)


async def test_uk_role_passes_when_on_the_register(db, profile):
    db.rpc_returns["is_licensed_sponsor"] = True
    gate = Gatekeeper(db)
    result = await gate.evaluate(
        job(location_raw="London, United Kingdom",
            analysis={"remote_policy": "onsite", "geo_restriction": ["UK"]}),
        company={"name": "Licensed Ltd"},
        profile=profile,
    )
    assert result.passed and result.track == "relocation"


async def test_german_role_below_blue_card_floor_is_blocked(db, profile):
    gate = Gatekeeper(db)
    result = await gate.evaluate(
        job(location_raw="Berlin, Germany",
            analysis={"remote_policy": "onsite", "geo_restriction": ["DE"],
                      "salary_max": 38000, "salary_currency": "EUR"}),
        company={"name": "Kleine GmbH"},
        profile=profile,
    )
    assert result.verdict == "blocked"
    assert any("Blue Card" in b for b in result.blockers)


async def test_german_role_above_blue_card_floor_passes(db, profile):
    gate = Gatekeeper(db)
    result = await gate.evaluate(
        job(location_raw="Berlin, Germany",
            analysis={"remote_policy": "onsite", "geo_restriction": ["DE"],
                      "salary_max": int(BLUE_CARD_SHORTAGE_THRESHOLD_EUR) + 10_000,
                      "salary_currency": "EUR"}),
        company={"name": "Grosse GmbH"},
        profile=profile,
    )
    assert result.passed


async def test_contract_role_is_routed_to_the_contract_track(db, profile):
    gate = Gatekeeper(db)
    result = await gate.evaluate(
        job(title="Contract ML Engineer (6-month)", analysis={"employment_type": "contract"}),
        company={"name": "Acme"},
        profile=profile,
    )
    assert result.track == "contract"


async def test_the_international_flag_is_only_ever_set_true(db):
    """§6: never cleared by a later silent posting."""
    db.tables["companies"] = [{"id": "c1", "hires_internationally": True}]
    await Gatekeeper(db).record_international_hire("c1", "EOR language")
    assert db.tables["companies"][0]["hires_internationally"] is True
