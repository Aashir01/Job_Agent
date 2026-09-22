"""HTTP-level checks: auth, and the approval gate as the dashboard sees it."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_db
from app.main import app

from .conftest import FakeDB


@pytest.fixture
def client(monkeypatch, settings):
    """FastAPI resolves Depends() against the function object captured at
    import time, so the in-memory database has to go in through
    dependency_overrides — monkeypatching the module attribute is too late."""
    fake = FakeDB()
    for key, value in settings.model_dump().items():
        monkeypatch.setenv(key.upper(), str(value))
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = lambda: fake
    with TestClient(app) as test_client:
        test_client.fake = fake
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


AUTH = {"X-Agent-Key": "test-agent-key"}


def test_health_is_open(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_machine_routes_reject_a_missing_key(client):
    assert client.get("/packages").status_code == 401


def test_machine_routes_reject_a_wrong_key(client):
    assert client.get("/packages", headers={"X-Agent-Key": "nope"}).status_code == 401


def test_review_queue_orders_fast_lane_first(client):
    client.fake.tables["review_queue"] = [
        {"id": "p3", "status": "queued", "tier": "marginal", "fit_score": 65},
        {"id": "p1", "status": "queued", "tier": "fast_lane", "fit_score": 90},
        {"id": "p2", "status": "queued", "tier": "standard", "fit_score": 75},
    ]
    body = client.get("/packages", headers=AUTH).json()
    assert [p["id"] for p in body["packages"]] == ["p1", "p2", "p3"]
    assert body["counts"]["fast_lane"] == 1


def test_approving_a_rejected_package_is_a_conflict(client):
    client.fake.tables["packages"] = [{"id": "p1", "job_id": "j1", "status": "rejected"}]
    resp = client.post("/packages/p1/approve", json={"submit": False}, headers=AUTH)
    assert resp.status_code == 409


def test_approval_without_submit_stops_at_approved(client):
    """The user can approve now and let the Courier run later."""
    client.fake.tables["packages"] = [{"id": "p1", "job_id": "j1", "status": "queued"}]
    resp = client.post("/packages/p1/approve", json={"submit": False}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "status": "approved", "submitted": False}
    assert client.fake.tables["packages"][0]["status"] == "approved"
    assert "applications" not in client.fake.tables


def test_every_verdict_is_recorded_for_the_scorer(client):
    """§5: every approve/reject trains the scorer."""
    client.fake.tables["packages"] = [{"id": "p1", "job_id": "j1", "status": "queued"}]
    client.post("/packages/p1/reject", json={"reason": "wrong stack", "reason_code": "stack"},
                headers=AUTH)
    decision = client.fake.tables["decisions"][0]
    assert decision["verdict"] == "rejected"
    assert decision["reason"] == "stack"


def test_rejecting_does_not_create_an_application(client):
    client.fake.tables["packages"] = [{"id": "p1", "job_id": "j1", "status": "queued"}]
    client.post("/packages/p1/reject", json={"reason": "no"}, headers=AUTH)
    assert "applications" not in client.fake.tables
    assert client.fake.tables["packages"][0]["status"] == "rejected"


def test_editing_a_package_records_which_fields_changed(client):
    client.fake.tables["packages"] = [{"id": "p1", "job_id": "j1", "status": "queued"}]
    resp = client.patch("/packages/p1", json={"cover_letter": "edited"}, headers=AUTH)
    assert resp.json()["edited_fields"] == ["cover_letter"]
    assert client.fake.tables["packages"][0]["cover_letter"] == "edited"


def test_the_extension_is_never_handed_an_autosubmit_flag(client):
    """§10: the extension fills; the user submits."""
    client.fake.tables["extension_queue"] = [
        {"id": "q1", "package_id": "p1", "target_url": "https://e.com/apply",
         "status": "pending", "payload": {"autosubmit": True, "full_name": "Test"}}
    ]
    item = client.get("/extension/queue/next", headers=AUTH).json()["item"]
    assert item["payload"]["autosubmit"] is False
    assert client.fake.tables["extension_queue"][0]["status"] == "claimed"


def test_a_user_submitted_fill_marks_the_package_submitted(client):
    client.fake.tables["extension_queue"] = [
        {"id": "q1", "package_id": "p1", "target_url": "https://e.com", "status": "claimed"}
    ]
    client.fake.tables["packages"] = [{"id": "p1", "status": "approved"}]
    client.post("/extension/queue/q1/status", json={"status": "submitted"}, headers=AUTH)
    assert client.fake.tables["packages"][0]["status"] == "submitted"


def test_an_abandoned_fill_returns_the_package_to_approved(client):
    client.fake.tables["extension_queue"] = [
        {"id": "q1", "package_id": "p1", "target_url": "https://e.com", "status": "claimed"}
    ]
    client.fake.tables["packages"] = [{"id": "p1", "status": "approved"}]
    client.post("/extension/queue/q1/status", json={"status": "abandoned"}, headers=AUTH)
    assert client.fake.tables["packages"][0]["status"] == "approved"


def test_passive_sightings_are_recorded_without_being_fetched(client):
    resp = client.post(
        "/extension/sightings",
        json={"sightings": [{"source": "linkedin", "source_url": "https://linkedin.com/jobs/1",
                             "title": "AI Engineer", "company_name": "Acme"}]},
        headers=AUTH,
    )
    assert resp.status_code == 200
    stored = client.fake.tables["passive_sightings"][0]
    assert stored["source"] == "linkedin"
    # A sighting is a URL and a title, nothing enriched.
    assert set(stored) <= {"id", "source", "source_url", "title", "company_name", "location_raw"}


def test_sightings_reject_an_unsupported_source(client):
    resp = client.post(
        "/extension/sightings",
        json={"sightings": [{"source": "glassdoor", "source_url": "https://x.com/1", "title": "X"}]},
        headers=AUTH,
    )
    assert resp.status_code == 422


def test_notify_status_names_the_missing_half_of_each_channel(client, monkeypatch):
    """'Not configured' is useless when you set one of two variables."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    get_settings.cache_clear()
    body = client.get("/notify/status", headers=AUTH).json()
    telegram = next(c for c in body["channels"] if c["id"] == "telegram")
    assert telegram["active"] is False
    assert telegram["missing"] == ["TELEGRAM_CHAT_ID"]
    assert "BotFather" in telegram["how"]
    get_settings.cache_clear()


def test_notify_status_lists_every_channel_with_setup_instructions(client):
    body = client.get("/notify/status", headers=AUTH).json()
    assert {c["id"] for c in body["channels"]} == {
        "telegram", "discord", "slack", "webhook", "email"
    }
    assert all(c["how"] and c["env"] for c in body["channels"])
    assert body["any"] is False


def test_notify_test_says_why_rather_than_failing_silently(client):
    body = client.post("/notify/test", headers=AUTH).json()
    assert body["sent"] is False
    assert "no channel" in body["reason"]


def test_notify_routes_need_the_agent_key(client):
    assert client.get("/notify/status").status_code == 401
    assert client.post("/notify/test").status_code == 401
