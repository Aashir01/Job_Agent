"""§8: the Gatekeeper runs before the Tailor and the Scribe.

Killing a package costs one cheap call; building one costs five. These tests
assert the ordering holds and that the budget is real.
"""
from __future__ import annotations

import pytest

from app.batch import BatchRunner
from app.llm.base import LLMError, QuotaExhausted
from app.llm.router import LLMRouter, parse_json
from app.notify import DeliveryResult, Notifier


class RecordingLLM(LLMRouter):
    """Counts calls per agent so the test can prove what never ran."""

    def __init__(self, settings, db, responses=None):
        super().__init__(settings, db)
        self.by_agent: dict[str, int] = {}
        self.responses = responses or {}

    async def generate_json(self, prompt, *, agent, **kw):
        self.calls_this_batch += 1
        if self.calls_this_batch > self.settings.llm_calls_per_batch:
            raise QuotaExhausted("budget spent")
        self.by_agent[agent] = self.by_agent.get(agent, 0) + 1
        return self.responses.get(agent, {})


BLOCKED_ANALYSIS = {
    "required_skills": ["Python"],
    "seniority": "senior",
    "remote_policy": "geo_restricted",
    "geo_restriction": ["US"],
    "sponsorship_language": "no_sponsorship",
    "sponsorship_evidence": "We cannot provide visa sponsorship.",
    "resume_keywords": ["Python"],
}
CLEAN_ANALYSIS = {
    "required_skills": ["Python", "RAG"],
    "seniority": "senior",
    "remote_policy": "global",
    "geo_restriction": [],
    "sponsorship_language": "eor_or_contractor",
    "resume_keywords": ["Python", "RAG"],
}


def _seed(db, description="Build RAG systems."):
    db.tables["jobs"] = [
        {"id": "j1", "company_id": "c1", "title": "Senior AI Engineer",
         "description": description, "location_raw": "Remote", "analysis": None,
         "companies": {"id": "c1", "name": "Acme"}}
    ]
    db.tables["profile"] = [
        {"id": "p1", "full_name": "Test", "headline": "AI Engineer", "seniority": "senior",
         "work_auth": {"needs_sponsorship": True}, "salary_floor_usd": 60000}
    ]
    db.rpc_returns["match_bullets"] = [
        {"id": "b1", "role_context": "Acme", "text": "Built a RAG pipeline in Python",
         "tags": ["rag"], "strength": 5, "similarity": 0.85}
    ]
    db.rpc_returns["is_licensed_sponsor"] = False
    return db


async def test_a_blocked_job_never_reaches_the_tailor_or_the_scribe(db, settings):
    _seed(db, "Remote (US only). We cannot provide visa sponsorship.")
    llm = RecordingLLM(settings, db, {"analyst": BLOCKED_ANALYSIS})
    stats = await BatchRunner(db, settings, llm).run(skip_scout=True)

    assert stats.killed_by_gatekeeper == 1
    assert stats.packages_built == 0
    assert llm.by_agent == {"analyst": 1}, "only the one cheap call should have been spent"
    assert "tailor" not in llm.by_agent
    assert "scribe" not in llm.by_agent
    assert "connector" not in llm.by_agent
    assert db.tables["jobs"][0]["killed_reason"]
    assert "packages" not in db.tables


async def test_a_clean_job_builds_a_full_package(db, settings):
    _seed(db, "Work from anywhere. We hire through Deel as our employer of record.")
    llm = RecordingLLM(
        settings, db,
        {
            "analyst": CLEAN_ANALYSIS,
            "tailor": {"bullets": []},
            "scribe": {"cover_letter": "Four paragraphs.", "screening_answers": []},
            "connector": {"subject": "s", "pre_apply": "a", "follow_up_1": "b", "follow_up_2": "c"},
        },
    )
    stats = await BatchRunner(db, settings, llm).run(skip_scout=True)

    assert stats.packages_built == 1
    assert stats.killed_by_gatekeeper == 0
    package = db.tables["packages"][0]
    assert package["status"] == "queued", "a new package is never auto-approved"
    assert package["tier"] in ("fast_lane", "standard", "marginal")
    assert package["cover_letter"] == "Four paragraphs."
    assert package["eligibility"]["track"] == "remote_fte"


async def test_no_package_is_ever_created_pre_approved(db, settings):
    """§1: nothing with the user's name leaves without a click."""
    _seed(db, "Work from anywhere, we use an employer of record.")
    llm = RecordingLLM(settings, db, {"analyst": CLEAN_ANALYSIS, "tailor": {"bullets": []},
                                      "scribe": {"cover_letter": "x"}, "connector": {}})
    await BatchRunner(db, settings, llm).run(skip_scout=True)
    assert all(p["status"] == "queued" for p in db.tables["packages"])
    assert "applications" not in db.tables


async def test_a_low_scoring_job_is_killed_before_the_expensive_half(db, settings):
    _seed(db, "Work from anywhere.")
    db.rpc_returns["match_bullets"] = []          # nothing in the bank matches
    analysis = {**CLEAN_ANALYSIS,
                "required_skills": ["COBOL", "Mainframe", "AS/400", "RPG", "JCL"]}
    llm = RecordingLLM(settings, db, {"analyst": analysis})
    stats = await BatchRunner(db, settings, llm).run(skip_scout=True)

    assert stats.killed_by_score == 1
    assert stats.packages_built == 0
    assert "tailor" not in llm.by_agent


async def test_the_batch_budget_stops_the_run_rather_than_overspending(db, settings):
    settings.llm_calls_per_batch = 1
    db.tables["jobs"] = [
        {"id": f"j{i}", "company_id": "c1", "title": "Engineer", "description": "x",
         "location_raw": "Remote", "analysis": None, "companies": {"id": "c1", "name": "Acme"}}
        for i in range(5)
    ]
    db.tables["profile"] = [{"id": "p1", "work_auth": {"needs_sponsorship": True}}]
    db.rpc_returns["match_bullets"] = []
    llm = RecordingLLM(settings, db, {"analyst": BLOCKED_ANALYSIS})

    stats = await BatchRunner(db, settings, llm).run(skip_scout=True)
    assert stats.quota_exhausted is True
    assert llm.calls_this_batch <= 1
    assert stats.analysed < 5, "unprocessed jobs roll to the next batch"


async def test_the_batch_records_its_own_stats(db, settings):
    _seed(db, "Work from anywhere with an employer of record.")
    llm = RecordingLLM(settings, db, {"analyst": CLEAN_ANALYSIS, "tailor": {"bullets": []},
                                      "scribe": {"cover_letter": "x"}, "connector": {}})
    stats = await BatchRunner(db, settings, llm).run(skip_scout=True)
    batch = db.tables["batches"][0]
    assert batch["status"] in ("ok", "partial")
    assert batch["stats"]["packages_built"] == stats.packages_built
    assert batch["finished_at"]


async def test_one_bad_job_does_not_abort_the_batch(db, settings):
    db.tables["jobs"] = [
        {"id": "bad", "company_id": None, "title": "X", "description": "x",
         "location_raw": "Remote", "analysis": None, "companies": None},
        {"id": "good", "company_id": "c1", "title": "AI Engineer",
         "description": "Work from anywhere with an employer of record.",
         "location_raw": "Remote", "analysis": None, "companies": {"id": "c1", "name": "Acme"}},
    ]
    db.tables["profile"] = [{"id": "p1", "headline": "AI Engineer", "seniority": "senior",
                             "work_auth": {"needs_sponsorship": True}}]
    db.rpc_returns["match_bullets"] = [
        {"id": "b1", "role_context": "Acme", "text": "Built a RAG pipeline in Python",
         "tags": ["rag"], "strength": 5, "similarity": 0.9}
    ]

    class HalfBrokenLLM(RecordingLLM):
        async def generate_json(self, prompt, *, agent, **kw):
            if agent == "analyst" and "bad" in str(kw.get("job_id")):
                raise LLMError("provider exploded")
            return await super().generate_json(prompt, agent=agent, **kw)

    llm = HalfBrokenLLM(settings, db, {"analyst": CLEAN_ANALYSIS, "tailor": {"bullets": []},
                                       "scribe": {"cover_letter": "x"}, "connector": {}})
    stats = await BatchRunner(db, settings, llm).run(skip_scout=True)
    assert stats.analysed == 2
    assert stats.packages_built >= 1


def test_json_parsing_survives_the_ways_models_wrap_output():
    assert parse_json('{"a": 1}') == {"a": 1}
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"a": 1} — hope that helps') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json("no json at all here")


async def test_provider_usage_reaches_the_daily_ledger(db, settings):
    """§8: the ledger is the cross-batch view of what the free tier has left."""
    _seed(db, "Remote (US only). We cannot provide visa sponsorship.")

    class CountingLLM(RecordingLLM):
        async def generate_json(self, prompt, *, agent, **kw):
            result = await super().generate_json(prompt, agent=agent, **kw)
            self.calls_by_provider["gemini"] = self.calls_by_provider.get("gemini", 0) + 1
            return result

    llm = CountingLLM(settings, db, {"analyst": BLOCKED_ANALYSIS})
    stats = await BatchRunner(db, settings, llm).run(skip_scout=True)

    assert stats.llm_by_provider == {"gemini": 1}
    bumps = [params for fn, params in db.rpc_calls if fn == "bump_quota"]
    assert bumps == [{"resource_name": "gemini", "amount": 1}]


async def test_a_completed_batch_pushes_a_digest(db, settings):
    """The queue filling at 02:00 UTC is worth nothing if nobody is told."""
    _seed(db, "Work from anywhere with an employer of record.")
    settings.telegram_bot_token = "t"
    settings.telegram_chat_id = "c"

    sent: list = []

    class CapturingNotifier(Notifier):
        async def send(self, digest, client=None):
            sent.append(digest)
            return [DeliveryResult("telegram", True)]

    llm = RecordingLLM(settings, db, {"analyst": CLEAN_ANALYSIS, "tailor": {"bullets": []},
                                      "scribe": {"cover_letter": "x"}, "connector": {}})
    stats = await BatchRunner(db, settings, llm, CapturingNotifier(settings, db)).run(skip_scout=True)

    assert stats.notifications == {"telegram": True}
    assert len(sent) == 1
    assert "1 new application" in sent[0].headline


async def test_a_failed_batch_reports_the_failure(db, settings):
    settings.telegram_bot_token = "t"
    settings.telegram_chat_id = "c"
    sent: list = []

    class CapturingNotifier(Notifier):
        async def send(self, digest, client=None):
            sent.append(digest)
            return [DeliveryResult("telegram", True)]

    class ExplodingRunner(BatchRunner):
        async def _jobs_to_process(self, limit):
            raise RuntimeError("Supabase refused the connection")

    llm = RecordingLLM(settings, db, {})
    await ExplodingRunner(db, settings, llm, CapturingNotifier(settings, db)).run(skip_scout=True)

    assert len(sent) == 1
    assert sent[0].kind == "error"
    assert "Supabase refused" in sent[0].error


async def test_a_dead_notification_channel_never_fails_the_batch(db, settings):
    """A built package is a built package whether or not the phone buzzed."""
    _seed(db, "Work from anywhere with an employer of record.")
    settings.telegram_bot_token = "t"
    settings.telegram_chat_id = "c"

    class BrokenNotifier(Notifier):
        async def send(self, digest, client=None):
            raise RuntimeError("Telegram is unreachable")

    llm = RecordingLLM(settings, db, {"analyst": CLEAN_ANALYSIS, "tailor": {"bullets": []},
                                      "scribe": {"cover_letter": "x"}, "connector": {}})
    stats = await BatchRunner(db, settings, llm, BrokenNotifier(settings, db)).run(skip_scout=True)

    assert stats.packages_built == 1
    assert stats.notifications == {}
    assert db.tables["packages"][0]["status"] == "queued"


async def test_no_digest_work_happens_when_no_channel_is_configured(db, settings):
    _seed(db, "Work from anywhere with an employer of record.")
    llm = RecordingLLM(settings, db, {"analyst": CLEAN_ANALYSIS, "tailor": {"bullets": []},
                                      "scribe": {"cover_letter": "x"}, "connector": {}})
    stats = await BatchRunner(db, settings, llm).run(skip_scout=True)
    assert stats.notifications == {}
