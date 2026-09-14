"""§1: the human gate. §10: the hard daily caps."""
from __future__ import annotations

import pytest

from app.agents.courier import Courier, NotApproved
from app.mailer import DailyCapReached, Mailer


def _seed(db, status="approved"):
    db.tables["packages"] = [
        {"id": "pkg1", "job_id": "j1", "status": status, "cover_letter": "hi",
         "screening_answers": {"answers": []}, "eligibility": {"track": "remote_fte"}}
    ]
    db.tables["jobs"] = [{"id": "j1", "company_id": "c1", "title": "AI Engineer",
                          "source_url": "https://boards.example.com/j/1"}]
    db.tables["companies"] = [{"id": "c1", "name": "Acme", "ats_type": "greenhouse"}]
    db.tables["profile"] = [{"id": "p1", "full_name": "Test", "links": {}}]
    return db


@pytest.mark.parametrize("status", ["draft", "queued", "rejected", "failed", "submitted"])
async def test_courier_refuses_anything_not_approved(db, settings, status):
    _seed(db, status)
    with pytest.raises(NotApproved):
        await Courier(db, settings).submit("pkg1")


async def test_courier_reads_status_from_the_database_not_the_caller(db, settings):
    """The gate cannot be bypassed by handing in a stale payload."""
    _seed(db, "queued")
    db.tables["packages"][0]["status"] = "queued"
    with pytest.raises(NotApproved):
        await Courier(db, settings).submit("pkg1")


async def test_approved_package_is_queued_for_the_extension(db, settings):
    _seed(db)
    db.rpc_returns["bump_daily_counter"] = 1
    result = await Courier(db, settings).submit("pkg1")
    assert result.ok and result.method == "extension"
    assert db.tables["extension_queue"][0]["payload"]["autosubmit"] is False
    assert db.tables["packages"][0]["status"] == "submitted"
    assert db.tables["applications"][0]["method"] == "extension"


async def test_the_extension_is_never_told_to_submit(db, settings):
    """§10: the extension fills; the user submits."""
    _seed(db)
    db.rpc_returns["bump_daily_counter"] = 1
    await Courier(db, settings).submit("pkg1")
    payload = db.tables["extension_queue"][0]["payload"]
    assert payload.get("autosubmit") is False


async def test_extension_cap_is_enforced(db, settings):
    """§10: 20 submissions a day, refused atomically at the database."""
    _seed(db)
    db.rpc_returns["bump_daily_counter"] = -1  # the RPC's "cap exceeded" signal
    result = await Courier(db, settings).submit("pkg1")
    assert not result.ok
    assert "cap" in result.detail.lower()
    assert db.tables["packages"][0]["status"] == "failed"
    assert "applications" not in db.tables or not db.tables["applications"]


async def test_submitting_marks_the_company_as_hiring_internationally(db, settings):
    _seed(db)
    db.rpc_returns["bump_daily_counter"] = 1
    await Courier(db, settings).submit("pkg1")
    assert db.tables["companies"][0]["hires_internationally"] is True


async def test_mailer_refuses_past_the_daily_cap(db, settings):
    db.rpc_returns["bump_daily_counter"] = -1
    mailer = Mailer(db, settings)
    with pytest.raises(DailyCapReached):
        await mailer.reserve_send()


async def test_mailer_reserves_a_slot_before_sending(db, settings):
    db.rpc_returns["bump_daily_counter"] = 3
    await Mailer(db, settings).reserve_send()
    assert db.rpc_calls[0][0] == "bump_daily_counter"
    assert db.rpc_calls[0][1]["cap"] == settings.max_outbound_emails_per_day


async def test_unverified_contacts_never_receive_a_pre_apply_note(db, settings):
    db.tables["outreach"] = [
        {"id": "o1", "application_id": "a1", "kind": "pre_apply", "body": "hi",
         "contact_id": "ct1", "sent_at": None}
    ]
    db.tables["contacts"] = [{"id": "ct1", "email": "x@acme.com", "email_confidence": "unknown"}]
    assert await Courier(db, settings).send_pre_apply("a1") is False
    assert db.tables["outreach"][0]["sent_at"] is None
