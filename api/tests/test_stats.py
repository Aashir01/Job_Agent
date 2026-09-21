"""The dashboard overview endpoint: shape, bucketing and the empty case."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_db
from app.main import app

from .conftest import FakeDB


@pytest.fixture
def client(monkeypatch, settings):
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


def test_overview_requires_the_agent_key(client):
    assert client.get("/stats/overview").status_code == 401


def test_overview_on_an_empty_database(client):
    body = client.get("/stats/overview", headers=AUTH).json()
    assert body["queue"] == {
        "total": 0,
        "by_tier": {"fast_lane": 0, "standard": 0, "marginal": 0},
    }
    assert body["funnel"] == {}
    assert body["outreach_due"] == 0
    assert body["latest_batch"] is None
    assert len(body["llm_daily"]) == 14
    assert body["llm_daily"][-1]["day"] == body["day"]


def test_queue_buckets_by_tier_and_untiered(client):
    client.fake.tables["packages"] = [
        {"id": "p1", "status": "queued", "tier": "fast_lane"},
        {"id": "p2", "status": "queued", "tier": "fast_lane"},
        {"id": "p3", "status": "queued", "tier": "marginal"},
        {"id": "p4", "status": "queued", "tier": None},
        {"id": "p5", "status": "submitted", "tier": "fast_lane"},  # not queued: excluded
    ]
    body = client.get("/stats/overview", headers=AUTH).json()
    assert body["queue"]["by_tier"] == {"fast_lane": 2, "standard": 0, "marginal": 1, "untiered": 1}
    assert body["queue"]["total"] == 4


def test_outreach_due_excludes_sent_and_approved(client):
    client.fake.tables["outreach"] = [
        {"id": "o1", "due_at": "2026-09-14T09:00:00Z", "sent_at": None, "approved_at": None},
        {"id": "o2", "due_at": "2026-09-14T09:00:00Z", "sent_at": "2026-09-14T10:00:00Z"},
        {"id": "o3", "due_at": "2026-09-14T09:00:00Z", "approved_at": "2026-09-14T10:00:00Z"},
        {"id": "o4", "due_at": None},
    ]
    body = client.get("/stats/overview", headers=AUTH).json()
    assert body["outreach_due"] == 1


def test_llm_daily_aggregates_per_day(client):
    today = client.get("/stats/overview", headers=AUTH).json()["day"]
    client.fake.tables["llm_calls"] = [
        {"created_at": f"{today}T01:00:00Z", "cost_usd": 0.001, "ok": True},
        {"created_at": f"{today}T02:00:00Z", "cost_usd": 0.002, "ok": True},
        {"created_at": "2020-01-01T00:00:00Z", "cost_usd": 9.0, "ok": True},  # outside window
    ]
    body = client.get("/stats/overview", headers=AUTH).json()
    today_point = body["llm_daily"][-1]
    assert today_point["calls"] == 2
    assert today_point["cost_usd"] == 0.003
    assert sum(p["calls"] for p in body["llm_daily"]) == 2
