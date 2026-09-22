"""§6 Scout: normalisation and the two-stage dedupe."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.agents.scout.ats import GreenhouseBoard, LeverBoard
from app.agents.scout.base import RawJob, dedupe_hash, normalise_name, parse_salary, parse_when, strip_html
from app.agents.scout.registry import AGGREGATORS, PLATFORM_IDS
from app.agents.scout.runner import Scout, _balanced_take
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


async def test_company_resolution_does_not_degrade_past_a_page_of_companies(db, settings):
    """Regression: resolve_company read the first 200 companies and compared
    names in Python, so past that it created duplicates — and a duplicate
    company splits `hires_internationally`, the one asset that compounds.
    It now looks up the indexed generated column."""
    db.rpc_returns["match_jobs"] = []
    db.tables["companies"] = [
        {"id": f"c{i}", "name": f"Filler {i}", "name_normalised": f"filler{i}"}
        for i in range(500)
    ]
    db.tables["companies"].append(
        {"id": "target", "name": "Acme, Inc.", "name_normalised": "acme",
         "hires_internationally": True}
    )

    class Source:
        name = "s"

        async def fetch(self, client):
            return [RawJob("s", "https://e.com/new", "AI Engineer", "acme inc")]

    await Scout(db, settings).run([Source()])

    assert len(db.tables["companies"]) == 501, "a duplicate company row was created"
    acme = [c for c in db.tables["companies"] if c.get("name_normalised") == "acme"]
    assert len(acme) == 1
    assert acme[0]["hires_internationally"] is True, "the compounding flag was split"
    assert db.tables["jobs"][0]["company_id"] == "target"


async def test_company_lookup_is_one_query_not_a_table_scan(db, settings):
    db.rpc_returns["match_jobs"] = []
    scout = Scout(db, settings)
    reads: list[dict] = []
    original = db.select

    async def counting_select(table, **kw):
        if table == "companies":
            reads.append(kw)
        return await original(table, **kw)

    db.select = counting_select  # type: ignore[method-assign]
    await scout.resolve_company(RawJob("s", "https://e.com/1", "Engineer", "Acme"))

    assert len(reads) <= 1
    assert reads and reads[0].get("eq", {}).get("name_normalised") == "acme", (
        "the lookup must filter on the indexed column, not read the table"
    )


# ── platform selection, and the truncation that starved 27 healthy sources ──
def test_balanced_take_spreads_the_cap_across_sources():
    """A plain ``[:limit]`` let whichever source was polled first take the whole
    allowance — which is how all 47 stored jobs came from a single ATS while
    Greenhouse, Lever and the aggregators were never reached."""
    jobs = [
        RawJob(f"src{i}", f"https://e.com/{i}/{n}", "Engineer", "Acme")
        for i in range(3)
        for n in range(100)
    ]
    taken = _balanced_take(jobs, 30)

    assert len(taken) == 30
    assert {j.source for j in taken} == {"src0", "src1", "src2"}, "one source still dominated"


def test_balanced_take_is_a_no_op_under_the_cap():
    jobs = [RawJob("s", f"https://e.com/{n}", "Engineer", "Acme") for n in range(5)]
    assert _balanced_take(jobs, 10) == jobs


async def test_build_sources_honours_the_selection(db, settings):
    db.tables["source_seeds"] = [
        {"kind": "greenhouse", "slug": "stripe", "company_name": "Stripe", "enabled": True},
        {"kind": "ashby", "slug": "cohere", "company_name": "Cohere", "enabled": True},
    ]
    sources = await Scout(db, settings).build_sources(platforms=["ashby", "remotive"])
    assert sorted(s.name for s in sources) == ["ashby", "remotive"]


async def test_build_sources_without_a_selection_keeps_every_platform(db, settings):
    db.tables["source_seeds"] = [
        {"kind": "greenhouse", "slug": "stripe", "company_name": "Stripe", "enabled": True}
    ]
    sources = await Scout(db, settings).build_sources()
    assert {s.name for s in sources} == {"greenhouse"} | set(AGGREGATORS)
    assert set(AGGREGATORS) <= set(PLATFORM_IDS)


async def test_disabled_boards_are_skipped(db, settings):
    db.tables["source_seeds"] = [
        {"kind": "ashby", "slug": "cohere", "enabled": False},
        {"kind": "ashby", "slug": "ramp", "enabled": True},
    ]
    sources = await Scout(db, settings).build_sources(platforms=["ashby"])
    assert [getattr(s, "slug", None) for s in sources] == ["ramp"]


async def test_a_board_that_404s_is_switched_off(db, settings):
    """A 404 is the board saying it is gone — renamed, moved ATS, or private.
    It never recovers on its own, so polling it twice a day forever is waste."""
    db.tables["source_seeds"] = [
        {"id": "s1", "kind": "greenhouse", "slug": "gone", "enabled": True},
        {"id": "s2", "kind": "greenhouse", "slug": "alive", "enabled": True},
    ]
    db.rpc_returns["match_jobs"] = []

    class Board:
        ats_type = "greenhouse"

        def __init__(self, name, slug, dead):
            self.name, self.slug, self.dead = name, slug, dead

        async def fetch(self, client):
            if self.dead:
                request = httpx.Request("GET", f"https://boards.example/{self.slug}")
                raise httpx.HTTPStatusError(
                    "404", request=request, response=httpx.Response(404, request=request)
                )
            return [RawJob(f"greenhouse:{self.slug}", "https://e.com/1", "Engineer", "Alive Co")]

    await Scout(db, settings).run(
        [Board("greenhouse", "gone", True), Board("greenhouse", "alive", False)]
    )

    seeds = {s["slug"]: s for s in db.tables["source_seeds"]}
    assert seeds["gone"]["enabled"] is False
    assert seeds["gone"]["last_error"]
    assert seeds["alive"].get("enabled") is not False, "a healthy board must stay on"


async def test_a_timeout_does_not_switch_a_board_off(db, settings):
    """Transient failures recover. Disabling on one is how a good source is lost."""
    db.tables["source_seeds"] = [
        {"id": "s1", "kind": "lever", "slug": "flaky", "enabled": True}
    ]
    db.rpc_returns["match_jobs"] = []

    class Flaky:
        name, slug, ats_type = "lever", "flaky", "lever"

        async def fetch(self, client):
            raise httpx.ReadTimeout("too slow")

    await Scout(db, settings).run([Flaky()])
    seed = db.tables["source_seeds"][0]
    assert seed.get("enabled") is not False
    assert "ReadTimeout" in seed["last_error"]


async def test_a_500_does_not_switch_a_board_off(db, settings):
    db.tables["source_seeds"] = [
        {"id": "s1", "kind": "ashby", "slug": "wobbly", "enabled": True}
    ]
    db.rpc_returns["match_jobs"] = []

    class Wobbly:
        name, slug, ats_type = "ashby", "wobbly", "ashby"

        async def fetch(self, client):
            request = httpx.Request("GET", "https://api.ashbyhq.com/wobbly")
            raise httpx.HTTPStatusError(
                "500", request=request, response=httpx.Response(500, request=request)
            )

    await Scout(db, settings).run([Wobbly()])
    assert db.tables["source_seeds"][0].get("enabled") is not False


async def test_a_poll_where_every_board_fails_still_records_why(db, settings):
    """The `no candidates` path is the one a fully rotted seed list takes, so
    returning early from it is how a dead board shows as "never polled, no
    error" — precisely when the error is the thing you need."""
    db.tables["source_seeds"] = [
        {"id": "s1", "kind": "greenhouse", "slug": "gone", "enabled": True}
    ]
    db.rpc_returns["match_jobs"] = []

    class Gone:
        name, slug, ats_type = "greenhouse", "gone", "greenhouse"

        async def fetch(self, client):
            request = httpx.Request("GET", "https://boards.example/gone")
            raise httpx.HTTPStatusError(
                "404", request=request, response=httpx.Response(404, request=request)
            )

    result = await Scout(db, settings).run([Gone()])
    assert result.kept == 0

    seed = db.tables["source_seeds"][0]
    assert seed["last_polled_at"], "the poll was never recorded"
    assert "404" in seed["last_error"]
    assert seed["enabled"] is False
