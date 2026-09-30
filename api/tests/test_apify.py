"""The Apify actor source: gating, field mapping, and registry wiring.

Nothing here points at LinkedIn or Indeed — see docs/DECISIONS.md for why those
stay excluded.
"""
from __future__ import annotations

import httpx

from app.agents.scout.apify import ApifyActor, build
from app.agents.scout.registry import AGGREGATORS, LABELS, PLATFORM_IDS
from app.config import Settings


def _client(payload):
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    )


def test_the_apify_source_is_offered_where_the_others_are():
    assert "apify" in PLATFORM_IDS
    assert "apify" in AGGREGATORS
    assert "Apify" in LABELS["apify"]


async def test_it_makes_no_http_call_until_it_is_configured():
    """Same shape as an install that never set up Adzuna: inert, not broken."""
    def explode(request):
        raise AssertionError("an unconfigured source must not make a request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(explode)) as client:
        assert await ApifyActor("", "someone~actor").fetch(client) == []
        assert await ApifyActor("token", "").fetch(client) == []


async def test_it_maps_a_dataset_item_onto_a_posting():
    dataset = [
        {
            "url": "https://boards.example.com/jobs/1",
            "title": "Senior AI Engineer",
            "companyName": "Acme",
            "location": "Remote — EU",
            "description": "<p>Build RAG pipelines.</p>",
            "datePosted": "2026-09-01T00:00:00Z",
        }
    ]
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["token"] = request.url.params.get("token")
        return httpx.Response(200, json=dataset)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs = await ApifyActor("token", "someone~actor").fetch(client)

    assert seen["method"] == "POST"
    assert seen["path"].endswith("/run-sync-get-dataset-items")
    assert seen["token"] == "token"

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "apify"
    assert job.source_url == "https://boards.example.com/jobs/1"
    assert job.title == "Senior AI Engineer"
    assert job.company_name == "Acme"
    assert job.location_raw == "Remote — EU"
    assert job.description == "Build RAG pipelines."      # html stripped
    assert job.posted_at is not None


async def test_it_reads_schema_org_shaped_fields():
    """Actors following schema.org nest the values, so {"name": …} is unwrapped
    rather than stringified."""
    dataset = [
        {
            "jobUrl": "https://e.com/2",
            "name": "ML Engineer",
            "hiringOrganization": {"name": "Beta Ltd"},
        }
    ]
    async with _client(dataset) as client:
        jobs = await ApifyActor("t", "a").fetch(client)

    assert jobs[0].company_name == "Beta Ltd"
    assert jobs[0].title == "ML Engineer"


async def test_items_without_a_url_are_dropped_rather_than_failing_the_source():
    dataset = [
        {"title": "No url here", "company": "Acme"},
        {"url": "https://e.com/3", "title": "Good one", "company": "Acme"},
        "not a dict at all",
    ]
    async with _client(dataset) as client:
        jobs = await ApifyActor("t", "a").fetch(client)

    assert [job.source_url for job in jobs] == ["https://e.com/3"]


async def test_a_dataset_larger_than_the_cap_is_truncated():
    dataset = [
        {"url": f"https://e.com/{i}", "title": f"Engineer {i}", "company": "Acme"}
        for i in range(10)
    ]
    async with _client(dataset) as client:
        jobs = await ApifyActor("t", "a", max_items=3).fetch(client)

    assert len(jobs) == 3


async def test_a_non_list_dataset_is_reported_not_crashed():
    async with _client({"error": "actor failed"}) as client:
        assert await ApifyActor("t", "a").fetch(client) == []


def test_the_actor_input_comes_from_settings_and_bad_json_is_ignored():
    good = Settings(
        apify_api_key="t", apify_actor_id="someone~actor",
        apify_input='{"query": "python engineer"}',
    )
    assert build(good, []).run_input == {"query": "python engineer"}

    broken = Settings(
        apify_api_key="t", apify_actor_id="someone~actor", apify_input="{not json",
    )
    assert build(broken, []).run_input == {}
