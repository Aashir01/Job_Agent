"""The Setup surface the dashboard uses: profile, platforms and run settings."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_db
from app.main import app

from .conftest import FakeDB

AUTH = {"X-Agent-Key": "test-agent-key"}


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


def test_profile_patch_rejects_an_unknown_field(client):
    """The failure that kept a real profile out of the database: PostgREST
    rejects the whole row (PGRST204) on an unknown column, so the API refuses it
    up front with something readable instead."""
    client.fake.tables["profile"] = [{"id": "p1", "full_name": "A"}]
    resp = client.patch("/profile", json={"courses": ["x"]}, headers=AUTH)
    assert resp.status_code == 400
    assert "courses" in resp.json()["detail"]


def test_profile_patch_updates_a_known_field(client):
    client.fake.tables["profile"] = [{"id": "p1", "full_name": "A", "skills": []}]
    resp = client.patch("/profile", json={"skills": ["Python"], "salary_floor_usd": 70000}, headers=AUTH)
    assert resp.status_code == 200
    updated = resp.json()["profile"]
    assert updated["skills"] == ["Python"]
    assert updated["salary_floor_usd"] == 70000


def test_profile_patch_rejects_an_empty_body(client):
    client.fake.tables["profile"] = [{"id": "p1"}]
    assert client.patch("/profile", json={}, headers=AUTH).status_code == 400


def test_sources_lists_every_platform_and_the_seeded_boards(client):
    client.fake.tables["source_seeds"] = [
        {"id": "b1", "kind": "greenhouse", "slug": "stripe", "company_name": "Stripe", "enabled": True}
    ]
    body = client.get("/sources", headers=AUTH).json()
    assert len(body["platforms"]) == 12
    assert {"id", "label", "kind"} <= set(body["platforms"][0])
    assert body["boards"][0]["slug"] == "stripe"
    # LinkedIn and Indeed are extension-only and must never appear as fetchable.
    assert "linkedin" not in {p["id"] for p in body["platforms"]}


def test_boards_reject_an_unknown_platform(client):
    resp = client.post("/sources/boards", json={"kind": "nope", "slug": "x"}, headers=AUTH)
    assert resp.status_code == 400


def test_boards_require_a_slug(client):
    resp = client.post("/sources/boards", json={"kind": "greenhouse"}, headers=AUTH)
    assert resp.status_code == 400


def test_a_board_can_be_enabled_and_disabled(client):
    client.fake.tables["source_seeds"] = [{"id": "b1", "kind": "lever", "slug": "plaid", "enabled": True}]
    resp = client.patch("/sources/boards/b1", json={"enabled": False}, headers=AUTH)
    assert resp.status_code == 200
    assert client.fake.tables["source_seeds"][0]["enabled"] is False


def test_run_settings_drop_platforms_that_do_not_exist(client):
    resp = client.patch(
        "/run-settings", json={"platforms": ["ashby", "not-a-platform"]}, headers=AUTH
    )
    assert resp.status_code == 200
    assert resp.json()["platforms"] == ["ashby"]


def test_run_settings_clamp_the_caps(client):
    resp = client.patch(
        "/run-settings",
        json={"filters": {"max_jobs": 999_999, "llm_calls": 0, "unknown": "ignored"}},
        headers=AUTH,
    )
    body = resp.json()["filters"]
    assert body["max_jobs"] == 2000
    # Zero is "unset", not "no calls at all".
    assert "llm_calls" not in body
    assert "unknown" not in body


def test_run_settings_round_trip(client):
    client.patch(
        "/run-settings",
        json={"platforms": ["remotive"], "filters": {"keywords": ["python"], "remote_only": True}},
        headers=AUTH,
    )
    body = client.get("/run-settings", headers=AUTH).json()
    assert body["platforms"] == ["remotive"]
    assert body["filters"] == {"keywords": ["python"], "remote_only": True}
    assert body["defaults"]["max_jobs"] > 0


def test_run_endpoint_saves_the_console_settings(client):
    """What is picked in the UI is persisted, so the cron inherits it too."""
    resp = client.post(
        "/batch/run?skip_scout=true", json={"platforms": ["remotive"]}, headers=AUTH
    )
    assert resp.status_code == 200
    assert resp.json()["settings"]["platforms"] == ["remotive"]
