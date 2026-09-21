"""Analyst coercion, register ingestion, Connector, Scribe and Chaser."""
from __future__ import annotations

import httpx
import pytest

from app.agents.analyst import Analyst, _coerce
from app.agents.chaser import Chaser
from app.agents.connector import Connector, guess_email, split_name
from app.agents.scribe import Scribe, audit_claims
from app.llm.router import LLMRouter
from app.registers.refresh import DEFAULT_SOURCES, normalise, parse_csv, strip_suffix


# ── Analyst ───────────────────────────────────────────────────────────────
def test_a_stated_geo_restriction_overrides_a_global_label():
    """Postings lie about this constantly; it is what the Gatekeeper exists for."""
    out = _coerce({"remote_policy": "global", "geo_restriction": ["us"]})
    assert out["remote_policy"] == "geo_restricted"
    assert out["geo_restriction"] == ["US"]


def test_unknown_enum_values_fall_back_rather_than_leak_through():
    out = _coerce({"seniority": "wizard", "sponsorship_language": "maybe",
                   "employment_type": "gig", "remote_policy": "sometimes"})
    assert out["seniority"] == "unknown"
    assert out["sponsorship_language"] == "silent"
    assert out["employment_type"] == "unknown"
    assert out["remote_policy"] == "unknown"


def test_reversed_salary_bounds_are_corrected():
    out = _coerce({"salary_min": 180000, "salary_max": 120000})
    assert (out["salary_min"], out["salary_max"]) == (120000, 180000)


def test_absurd_salaries_are_discarded():
    assert _coerce({"salary_min": 3, "salary_max": 9})["salary_min"] is None


def test_keyword_output_is_capped_at_twelve():
    """§6 asks for 8-12 keywords; more is keyword stuffing waiting to happen."""
    assert len(_coerce({"resume_keywords": ["kw"] * 50})["resume_keywords"]) == 12


def test_a_string_where_a_list_belongs_is_tolerated():
    assert _coerce({"required_skills": "Python"})["required_skills"] == ["Python"]


async def test_analyst_returns_a_usable_shape_when_the_model_fails(db, settings):
    class BrokenLLM(LLMRouter):
        async def generate_json(self, prompt, **kw):
            raise ValueError("no JSON object in model output")

    analysis = await Analyst(db, BrokenLLM(settings, db), settings).analyse({"id": "j1"})
    assert analysis["remote_policy"] == "unknown"
    assert analysis["analysis_error"]
    assert analysis["geo_restriction"] == []


# ── Registers ─────────────────────────────────────────────────────────────
def test_register_csv_skips_a_preamble_and_dedupes():
    rows = parse_csv(
        "Published 1 January\n"
        "Organisation Name,Town/City,Type & Rating,Route\n"
        "Acme Ltd,London,Worker (A rating),Skilled Worker\n"
        "Acme Ltd,London,Worker (A rating),Skilled Worker\n"
        "Beta B.V.,Leeds,Worker (A rating),Global Business Mobility\n",
        DEFAULT_SOURCES["UK"],
    )
    assert len(rows) == 2
    assert rows[0]["org_name_normalised"] == "acmeltd"


def test_register_keys_meet_the_scout_s_company_key():
    """A job board writes 'Acme'; the Home Office writes 'Acme Ltd'. If these
    two normalisations drift apart the Gatekeeper silently stops matching."""
    from app.agents.scout.base import normalise_name

    rows = parse_csv("Organisation Name,Route\nAcme Ltd,Skilled Worker\n", DEFAULT_SOURCES["UK"])
    assert rows[0]["org_name_stripped"] == normalise_name("Acme") == "acme"
    assert strip_suffix(normalise("Beta B.V.")) == normalise_name("Beta BV")


def test_rows_without_an_organisation_name_are_skipped():
    rows = parse_csv("Organisation Name,Route\n,Skilled Worker\nAcme,Skilled Worker\n",
                     DEFAULT_SOURCES["UK"])
    assert len(rows) == 1


async def test_a_failed_fetch_leaves_the_previous_register_intact(db):
    """An empty register is worse than a stale one: it passes everything."""
    from app.registers.refresh import refresh_register

    db.tables["sponsor_registers"] = [{"id": "s1", "country": "UK", "org_name": "Acme"}]
    transport = httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))
    async with httpx.AsyncClient(transport=transport) as client:
        count, error = await refresh_register(db, DEFAULT_SOURCES["UK"], client)
    assert count == 0 and error
    assert db.tables["sponsor_registers"] == [{"id": "s1", "country": "UK", "org_name": "Acme"}]
    assert db.tables["register_refreshes"][0]["ok"] is False


async def test_a_parsed_zero_row_response_also_leaves_the_register_intact(db):
    from app.registers.refresh import refresh_register

    db.tables["sponsor_registers"] = [{"id": "s1", "country": "UK", "org_name": "Acme"}]
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text="Nothing,Here\n"))
    async with httpx.AsyncClient(transport=transport) as client:
        count, error = await refresh_register(db, DEFAULT_SOURCES["UK"], client)
    assert count == 0 and "zero rows" in error
    assert len(db.tables["sponsor_registers"]) == 1


# ── Connector ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "pattern,expected",
    [
        ("{first}.{last}@", "jane.doe@acme.com"),
        ("{f}{last}@", "jdoe@acme.com"),
        ("{first}@", "jane@acme.com"),
        ("{first}_{last}@", "jane_doe@acme.com"),
        (None, "jane.doe@acme.com"),
    ],
)
def test_email_patterns_render(pattern, expected):
    assert guess_email(pattern, "Jane Q. Doe", "https://acme.com/careers") == expected


def test_no_domain_means_no_guess():
    assert guess_email("{first}.{last}@", "Jane Doe", None) is None


def test_middle_names_do_not_end_up_in_the_surname():
    assert split_name("Aashir Zafar Ali") == ("aashir", "ali")


def test_referral_plan_is_a_search_plan_not_a_scrape(profile):
    """§6: LinkedIn is never touched server-side."""
    plan = Connector.referral_plan(
        Connector.__new__(Connector),
        {**profile, "education": [{"institution": "University of Sargodha"}]},
        {"name": "Acme"},
    )
    kinds = {p["kind"] for p in plan}
    assert "alumni" in kinds and "nationality_network" in kinds
    assert all("hint" in p for p in plan), "the extension resolves these, not the server"


async def test_a_domain_with_no_mx_record_is_not_emailed(db, settings):
    db.tables["contacts"] = [{"id": "ct1", "company_id": "c1", "name": "Jane Doe"}]

    class SilentLLM(LLMRouter):
        async def generate_json(self, prompt, **kw):
            return {}

    result = await Connector(db, SilentLLM(settings, db), settings).run(
        {"id": "j1", "title": "Engineer"},
        {"id": "c1", "name": "Acme", "domain": "invalid-domain-that-does-not-exist.test"},
        {"full_name": "Test"},
        [],
    )
    assert any("no MX record" in n for n in result.notes)
    assert db.tables["contacts"][0].get("email") is None


async def test_outreach_drafts_are_persisted_unsent(db, settings):
    connector = Connector.__new__(Connector)
    connector.db = db
    await connector.persist_drafts("a1", "ct1", {"pre_apply": "hi", "follow_up_1": "again",
                                                 "follow_up_2": "last"})
    assert len(db.tables["outreach"]) == 3
    assert all(row["sent_at"] is None for row in db.tables["outreach"])


# ── Scribe ────────────────────────────────────────────────────────────────
def test_claim_audit_passes_verified_figures():
    assert audit_claims("Cut latency 38% across 1,200 documents in 2024.", {"38%", "1200"}) == []


def test_claim_audit_flags_an_invented_figure():
    warnings = audit_claims("Grew revenue 250%.", {"38%"})
    assert any("250%" in w for w in warnings)


def test_claim_audit_flags_filler():
    assert any("thrilled" in w for w in audit_claims("I am thrilled.", set()))


def test_claim_audit_flags_an_unevidenced_technology():
    """The fabrication the figure check cannot see: a claim with no number in it."""
    warnings = audit_claims(
        "I gained hands-on experience with Kubernetes and Docker in production environments.",
        set(),
        "Python FastAPI PostgreSQL pgvector LangChain Docker",
    )
    assert any("kubernetes" in w for w in warnings)
    assert not any("docker" in w for w in warnings), "Docker is in the profile"


def test_claim_audit_flags_a_technology_at_the_end_of_a_sentence():
    """Sentence punctuation must not hide the name."""
    warnings = audit_claims("I also deployed on Kubernetes.", set(), "Python")
    assert any("kubernetes" in w for w in warnings)


def test_claim_audit_passes_technologies_the_bank_can_evidence():
    assert audit_claims("I built retrieval pipelines in Python with pgvector.", set(), "Python pgvector") == []


def test_claim_audit_skips_the_technology_check_without_evidence():
    """Callers that pass no evidence keep the old figure-and-filler behaviour."""
    assert audit_claims("I used Kubernetes.", set()) == []


async def test_scribe_reports_unanswered_screening_questions(db, settings):
    class PartialLLM(LLMRouter):
        async def generate_json(self, prompt, **kw):
            return {"cover_letter": "Four paragraphs.", "screening_answers": []}

    result = await Scribe(db, PartialLLM(settings, db), settings).write(
        {"id": "j1", "title": "Engineer", "description": "x"},
        {"screening_questions": ["Why us?", "Salary expectation?"]},
        {"full_name": "Test", "work_auth": {"needs_sponsorship": True}},
        [],
        {"name": "Acme"},
    )
    assert any("unanswered" in w for w in result.warnings)


async def test_scribe_survives_a_dead_provider(db, settings):
    class DeadLLM(LLMRouter):
        async def generate_json(self, prompt, **kw):
            raise ValueError("provider down")

    result = await Scribe(db, DeadLLM(settings, db), settings).write(
        {"id": "j1", "title": "Engineer", "description": "x"}, {}, {"full_name": "Test"}, [],
        {"name": "Acme"},
    )
    assert result.cover_letter == ""
    assert result.warnings


# ── Chaser ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "text,expected",
    [
        ("Unfortunately we're moving forward with other candidates.", "rejected"),
        ("Could you share your availability for a technical screen?", "interview"),
        ("We'd like to set up a call about next steps.", "replied"),
        ("Thanks for applying to Acme!", "acknowledged"),
    ],
)
def test_reply_classification(text, expected):
    assert Chaser._classify(Chaser.__new__(Chaser), "", text) == expected


async def test_follow_ups_become_due_but_never_send_themselves(db, settings):
    """§6: cadence pre-approved, content per-send."""
    from datetime import datetime, timedelta, timezone

    submitted = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    db.tables["applications"] = [{"id": "a1", "status": "submitted", "submitted_at": submitted}]
    db.tables["outreach"] = [
        {"id": "o1", "application_id": "a1", "kind": "follow_up_1", "body": "hi",
         "sent_at": None, "due_at": None, "approved_at": None}
    ]
    queued = await Chaser(db, None, settings).queue_due_follow_ups()
    assert queued == 1
    assert db.tables["outreach"][0]["due_at"] is not None
    assert db.tables["outreach"][0]["sent_at"] is None
    assert db.tables["outreach"][0]["approved_at"] is None


async def test_an_unapproved_follow_up_is_not_sent(db, settings):
    db.tables["outreach"] = [
        {"id": "o1", "application_id": "a1", "kind": "follow_up_1", "body": "hi",
         "sent_at": None, "due_at": "2026-01-01T00:00:00Z", "approved_at": None,
         "contacts": {"email": "x@acme.com", "email_confidence": "verified"}}
    ]
    sent, errors = await Chaser(db, None, settings).send_approved()
    assert sent == 0
    assert db.tables["outreach"][0]["sent_at"] is None


async def test_a_follow_up_is_not_due_before_its_day(db, settings):
    from datetime import datetime, timedelta, timezone

    submitted = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    db.tables["applications"] = [{"id": "a1", "status": "submitted", "submitted_at": submitted}]
    db.tables["outreach"] = [
        {"id": "o1", "application_id": "a1", "kind": "follow_up_1", "body": "hi",
         "sent_at": None, "due_at": None}
    ]
    assert await Chaser(db, None, settings).queue_due_follow_ups() == 0


async def test_long_silent_applications_are_marked_ghosted(db, settings):
    db.tables["applications"] = [
        {"id": "a1", "status": "submitted", "submitted_at": "2020-01-01T00:00:00Z"}
    ]
    assert await Chaser(db, None, settings).mark_ghosted(30) == 1
    assert db.tables["applications"][0]["status"] == "ghosted"
