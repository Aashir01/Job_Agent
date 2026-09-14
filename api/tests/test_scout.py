"""§6 Scout: normalisation and the two-stage dedupe."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.agents.scout.ats import GreenhouseBoard, LeverBoard
from app.agents.scout.base import RawJob, dedupe_hash, normalise_name, parse_salary, parse_when, strip_html
from app.agents.scout.runner import Scout
from app.embeddings import cosine, hashing_embed


def test_company_name_normalisation_collapses_legal_suffixes():
    assert normalise_name("Acme, Inc.") == normalise_name("acme inc") == "acme"
    assert normalise_name("Beta B.V.") == normalise_name("Beta BV")


def test_dedupe_hash_ignores_punctuation_and_case():
    assert dedupe_hash("Acme Inc", "Senior Engineer", "Remote") == dedupe_hash(
        "Acme, Inc.", "senior engineer", "REMOTE"
    )


def test_dedupe_hash_separates_genuinely_different_roles():
    assert dedupe_hash("Acme", "Senior Engineer", "Remote") != dedupe_hash(
        "Acme", "Staff Engineer", "Remote"
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Salary: $120,000 - $160,000", (120000, 160000, "USD")),
        ("€70.000 – €95.000 per year", (70000, 95000, "EUR")),
        ("Founded 2019 - 2024", (None, None, None)),
        ("Team of 5 - 10 engineers", (None, None, None)),
    ],
)
def test_salary_parsing(text, expected):
    assert parse_salary(text) == expected


def test_strip_html_keeps_list_structure():
    assert "• One" in strip_html("<ul><li>One</li><li>Two</li></ul>")


def test_parse_when_handles_the_formats_sources_actually_send():
    assert parse_when("2026-01-15T10:00:00Z").year == 2026
    assert parse_when(1700000000).year == 2023
    assert parse_when(1700000000000).year == 2023   # milliseconds
    assert parse_when("not a date") is None
    assert parse_when(None) is None


def test_stale_postings_are_dropped_but_undated_ones_are_kept():
    old = RawJob("x", "https://e.com/1", "Eng", "Acme",
                 posted_at=datetime.now(timezone.utc) - timedelta(days=90))
    undated = RawJob("x", "https://e.com/2", "Eng", "Acme")
    assert not old.is_fresh(21)
    assert undated.is_fresh(21)


def test_cross_posted_roles_collide_above_the_dedupe_threshold():
    """§6: the same role, cross-posted with different punctuation and a
    '(Remote)' bolted on, must land above cosine 0.92."""
    a = hashing_embed("Senior AI Engineer — build RAG pipelines with LangChain and FastAPI at Acme")
    b = hashing_embed("Senior AI Engineer (Remote): build RAG pipelines with LangChain and FastAPI, Acme")
    assert cosine(a, b) > 0.92


def test_distinct_roles_stay_well_clear_of_the_threshold():
    """A false dedupe loses a job outright, so the far side matters more than
    the near side. These sit an order of magnitude below the cut."""
    role = hashing_embed("Senior AI Engineer at Acme building RAG pipelines with LangChain")
    other_role = hashing_embed("Engineering Manager at Acme leading the platform team and roadmap")
    unrelated = hashing_embed("Warehouse forklift operator, night shift, Ohio, must lift 50lbs")
    assert cosine(role, other_role) < 0.5
    assert cosine(role, unrelated) < 0.5


def test_an_inserted_word_barely_moves_a_full_length_posting():
    """Regression: character n-grams were once strided over the whole joined
    text, so inserting a single word misaligned every feature after it and
    dropped two near-identical postings to ~0.49. Taken per word instead, an
    edit costs about what it should."""
    jd = (
        "Senior AI Engineer. You will build RAG pipelines with LangChain and FastAPI, "
        "own the retrieval evaluation harness, and work with the platform team on latency. "
        "We use Python, Postgres and pgvector. Remote friendly, strong written communication."
    )
    edited = jd.replace("You will build", "You will quickly build")
    assert cosine(hashing_embed(jd), hashing_embed(edited)) > 0.95


async def test_greenhouse_adapter_normalises_a_board_payload():
    payload = {
        "jobs": [
            {
                "id": 1,
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                "title": "Senior AI Engineer",
                "location": {"name": "Remote - US"},
                "content": "&lt;p&gt;Build RAG systems.&lt;/p&gt;",
                "updated_at": "2026-01-10T09:00:00Z",
            }
        ]
    }
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as client:
        jobs = await GreenhouseBoard("acme", "Acme").fetch(client)
    assert len(jobs) == 1
    assert jobs[0].ats_type == "greenhouse"
    assert jobs[0].location_raw == "Remote - US"
    assert jobs[0].company_name == "Acme"


async def test_lever_adapter_merges_the_list_sections():
    payload = [
        {
            "hostedUrl": "https://jobs.lever.co/acme/1",
            "text": "Backend Engineer",
            "categories": {"location": "Remote", "commitment": "Full-time"},
            "descriptionPlain": "We build things.",
            "lists": [{"text": "Requirements", "content": "<li>Python</li>"}],
            "createdAt": 1700000000000,
        }
    ]
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as client:
        jobs = await LeverBoard("acme", "Acme").fetch(client)
    assert "Requirements" in jobs[0].description and "Python" in jobs[0].description


async def test_one_dead_source_does_not_kill_the_batch(db, settings):
    class Dead:
        name = "dead"

        async def fetch(self, client):
            raise RuntimeError("502 from the board")

    class Alive:
        name = "alive"

        async def fetch(self, client):
            return [RawJob("alive", "https://e.com/1", "Engineer", "Acme")]

    jobs, errors = await Scout(db, settings).poll([Dead(), Alive()])
    assert len(jobs) == 1
    assert "dead" in errors


async def test_scout_skips_jobs_already_in_the_database(db, settings):
    db.tables["jobs"] = [{"id": "j0", "source_url": "https://e.com/1", "dedupe_hash": "x"}]
    db.rpc_returns["match_jobs"] = []

    class Source:
        name = "s"

        async def fetch(self, client):
            return [RawJob("s", "https://e.com/1", "Engineer", "Acme")]

    result = await Scout(db, settings).run([Source()])
    assert result.kept == 0
    assert result.duplicates_url == 1


async def test_scout_drops_a_near_duplicate_the_hash_missed(db, settings):
    """Stage 2: the same role, cross-posted with a different title."""
    db.rpc_returns["match_jobs"] = [{"id": "j0", "similarity": 0.97}]

    class Source:
        name = "s"

        async def fetch(self, client):
            return [RawJob("s", "https://e.com/new", "Sr. AI Engineer", "Acme")]

    result = await Scout(db, settings).run([Source()])
    assert result.duplicates_embedding == 1
    assert result.kept == 0


async def test_scout_persists_a_genuinely_new_posting(db, settings):
    db.rpc_returns["match_jobs"] = []

    class Source:
        name = "s"

        async def fetch(self, client):
            return [RawJob("s", "https://e.com/new", "AI Engineer", "Acme", description="RAG work")]

    result = await Scout(db, settings).run([Source()])
    assert result.kept == 1
    stored = db.tables["jobs"][0]
    assert stored["source_url"] == "https://e.com/new"
    assert len(stored["embedding"]) == 384
    assert db.tables["companies"][0]["name"] == "Acme"


async def test_the_same_company_is_not_created_twice(db, settings):
    db.rpc_returns["match_jobs"] = []

    class Source:
        name = "s"

        async def fetch(self, client):
            return [
                RawJob("s", "https://e.com/1", "AI Engineer", "Acme, Inc."),
                RawJob("s", "https://e.com/2", "Backend Engineer", "acme inc"),
            ]

    await Scout(db, settings).run([Source()])
    assert len(db.tables["companies"]) == 1
