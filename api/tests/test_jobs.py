"""The raw job feed: every stored posting, not only the packaged ones.

Filters are built into PostgREST expressions, so several of these assert on the
query the route constructed rather than on rows — the in-memory fake does not
evaluate a raw `or` expression.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import Database, get_db
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

JOB = {
    "id": "j1",
    "source": "greenhouse:stripe",
    "source_url": "https://e.com/1",
    "title": "Senior AI Engineer",
    "location_raw": "Remote — EU",
    "remote_policy": "global",
    "track": "remote_fte",
    "analysis": {"seniority": "senior"},
    "killed_reason": None,
    "discovered_at": "2026-09-30T10:00:00Z",
}


def test_the_feed_requires_the_agent_key(client):
    assert client.get("/jobs").status_code == 401


def test_the_feed_returns_stored_jobs(client):
    client.fake.tables["jobs"] = [dict(JOB)]
    body = client.get("/jobs", headers=AUTH).json()

    assert [job["id"] for job in body["jobs"]] == ["j1"]
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert body["has_more"] is False


def test_the_read_embeds_the_company_and_any_package(client):
    client.fake.tables["jobs"] = [dict(JOB)]
    client.get("/jobs", headers=AUTH)
    columns = client.fake.reads[-1]["columns"]
    assert "companies(id,name,hires_internationally)" in columns
    assert "packages(id,tier,fit_score,status)" in columns


def test_a_full_page_reports_that_more_exists(client):
    """One row past the page answers 'is there more' without a count round trip."""
    client.fake.tables["jobs"] = [{**JOB, "id": f"j{i}"} for i in range(3)]
    body = client.get("/jobs?limit=2", headers=AUTH).json()

    assert len(body["jobs"]) == 2
    assert body["has_more"] is True
    assert client.fake.reads[-1]["limit"] == 3


def test_the_platform_filter_is_a_prefix_match(client):
    """A seeded ATS board stores 'greenhouse:stripe', so equality would return
    nothing for the platform the user actually picked."""
    client.fake.tables["jobs"] = [dict(JOB)]
    client.get("/jobs?platform=greenhouse", headers=AUTH)
    assert client.fake.reads[-1]["ilike"] == {"source": "greenhouse*"}


def test_the_other_filters_reach_the_query(client):
    client.fake.tables["jobs"] = [dict(JOB)]
    client.get(
        "/jobs?status=analysed&track=remote_fte&remote_policy=global"
        "&sort=oldest&limit=25&offset=50",
        headers=AUTH,
    )
    read = client.fake.reads[-1]

    assert read["eq"] == {"remote_policy": "global", "track": "remote_fte"}
    assert read["not_null"] == ["analysis"]
    assert read["is_null"] is None
    assert read["order"] == "discovered_at.asc"
    assert read["limit"] == 26          # one past the page
    assert read["offset"] == 50


def test_unanalysed_and_killed_filter_on_different_columns(client):
    client.fake.tables["jobs"] = [dict(JOB)]

    client.get("/jobs?status=unanalysed", headers=AUTH)
    assert client.fake.reads[-1]["is_null"] == ["analysis"]
    assert client.fake.reads[-1]["not_null"] is None

    client.get("/jobs?status=killed", headers=AUTH)
    assert client.fake.reads[-1]["not_null"] == ["killed_reason"]


def test_search_becomes_a_postgrest_or_across_three_columns(client):
    client.fake.tables["jobs"] = [dict(JOB)]
    client.get("/jobs?q=ai engineer", headers=AUTH)
    assert client.fake.reads[-1]["or_"] == (
        "(title.ilike.*ai engineer*,location_raw.ilike.*ai engineer*,"
        "source.ilike.*ai engineer*)"
    )


def test_a_search_term_cannot_inject_filter_syntax(client):
    """The term lands inside a PostgREST expression, where `,` `(` `)` and `*`
    are syntax — a term carrying one must narrow the query, not break it."""
    client.fake.tables["jobs"] = [dict(JOB)]
    client.get("/jobs?q=a,b(c)*d", headers=AUTH)

    or_ = client.fake.reads[-1]["or_"]
    term = or_.split("title.ilike.*", 1)[1].split("*", 1)[0]
    assert term == "a b c d"


def test_an_unknown_filter_value_is_rejected(client):
    assert client.get("/jobs?status=nonsense", headers=AUTH).status_code == 422
    assert client.get("/jobs?sort=nonsense", headers=AUTH).status_code == 422
    assert client.get("/jobs?limit=9999", headers=AUTH).status_code == 422


async def test_select_encodes_ilike_and_or_into_the_request():
    """The Database layer is where the PostgREST syntax is built, so it is worth
    asserting on the wire rather than trusting the caller's intent."""
    captured: dict[str, str] = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json=[])

    transport = httpx.AsyncClient(
        base_url="https://example.supabase.co/rest/v1",
        transport=httpx.MockTransport(handler),
    )
    db = Database(
        Settings(supabase_url="https://example.supabase.co", supabase_service_key="k"),
        client=transport,
    )
    try:
        await db.select(
            "jobs",
            columns="id",
            ilike={"source": "greenhouse*"},
            or_="(title.ilike.*x*)",
            not_null=["analysis"],
            is_null=None,
            limit=10,
            offset=5,
        )
    finally:
        await transport.aclose()

    query = parse_qs(urlparse(captured["url"]).query)

    assert query["source"] == ["ilike.greenhouse*"]
    assert query["or"] == ["(title.ilike.*x*)"]
    assert query["analysis"] == ["not.is.null"]
    assert query["limit"] == ["10"]
    assert query["offset"] == ["5"]
