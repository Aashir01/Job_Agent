"""Jooble's REST adapter: request shape, mapping, and quota-friendly paging.

The free plan is a lifetime quota of 500 requests per key, so the paging
behaviour is a correctness concern here, not a nicety.
"""
from __future__ import annotations

import json

import httpx

from app.agents.scout.boards import Jooble
from app.agents.scout.registry import AGGREGATORS, LABELS, PLATFORM_IDS

RESPONSE = {
    "totalCount": 2,
    "jobs": [
        {
            "id": 1,
            "title": "Senior AI Engineer",
            "location": "Austin, TX",
            "snippet": "<b>Build</b> RAG pipelines.",
            "salary": "$120,000 - $160,000",
            "source": "jooble",
            "type": "Full-time",
            "link": "https://jooble.org/jdp/1",
            "company": "Acme",
            "updated": "2026-09-01T12:55:35Z",
        },
        {"id": 2, "title": "No link and no company"},
    ],
}


def _client(payload, calls=None):
    def handler(request):
        if calls is not None:
            calls.append(request)
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_the_jooble_source_is_offered_where_the_others_are():
    assert "jooble" in PLATFORM_IDS
    assert "jooble" in AGGREGATORS
    assert "Jooble" in LABELS["jooble"]


async def test_it_makes_no_http_call_without_a_key():
    def explode(request):
        raise AssertionError("an unconfigured source must not make a request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(explode)) as client:
        assert await Jooble("").fetch(client) == []


async def test_it_sends_the_keywords_and_location_the_api_requires():
    calls = []
    async with _client({"jobs": []}, calls) as client:
        await Jooble("key", keywords="data engineer", location="Pakistan").fetch(client)

    body = json.loads(calls[0].content)
    assert body["keywords"] == "data engineer"
    assert body["location"] == "Pakistan"
    assert body["page"] == "1"
    assert calls[0].url.path.endswith("/api/key")


async def test_it_maps_a_job_onto_a_posting():
    async with _client(RESPONSE) as client:
        jobs = await Jooble("key").fetch(client)

    # The second item has no link or company, so RawJob rejects it.
    assert [job.source_url for job in jobs] == ["https://jooble.org/jdp/1"]

    job = jobs[0]
    assert job.source == "jooble"
    assert job.title == "Senior AI Engineer"
    assert job.company_name == "Acme"
    assert job.location_raw == "Austin, TX"
    assert job.description == "Build RAG pipelines."     # html stripped
    assert (job.salary_min, job.salary_max) == (120000, 160000)
    assert job.posted_at is not None


async def test_it_spends_one_request_per_run_by_default():
    """500 requests is a lifetime allowance, so the default must not page."""
    calls = []
    async with _client(RESPONSE, calls) as client:
        await Jooble("key").fetch(client)

    assert len(calls) == 1


async def test_it_stops_as_soon_as_a_page_is_empty():
    calls = []
    async with _client({"jobs": []}, calls) as client:
        await Jooble("key", pages=5).fetch(client)

    assert len(calls) == 1


async def test_a_rejected_key_is_reported_rather_than_raised():
    transport = httpx.MockTransport(lambda r: httpx.Response(403, json={}))
    async with httpx.AsyncClient(transport=transport) as client:
        assert await Jooble("bad-key").fetch(client) == []
