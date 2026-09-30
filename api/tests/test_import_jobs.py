"""Manual import of postings the user collected themselves (§6, source 4).

LinkedIn and Indeed are never fetched server-side. These test the file parser
and that an imported posting lands in the queue by the same rules as a
discovered one.
"""
from __future__ import annotations

from app.agents.scout.runner import Scout
from app.import_jobs import UNKNOWN_COMPANY, build_jobs, is_thin, parse_postings

FILE = """\
# saved jobs, 2026-09-30

https://www.linkedin.com/jobs/view/4123456789
title: Senior AI Engineer
company: Acme, Inc.
location: Remote — EU

We are hiring a Senior AI Engineer to build RAG pipelines
with LangChain and FastAPI.

Location: this line is part of the posting, not a field.

https://www.linkedin.com/jobs/view/4123499999
"""


def test_the_file_parses_into_one_posting_per_url():
    records, problems = parse_postings(FILE)
    assert problems == []
    assert [r["url"] for r in records] == [
        "https://www.linkedin.com/jobs/view/4123456789",
        "https://www.linkedin.com/jobs/view/4123499999",
    ]


def test_fields_before_the_description_become_the_posting():
    record = parse_postings(FILE)[0][0]
    assert record["title"] == "Senior AI Engineer"
    assert record["company_name"] == "Acme, Inc."
    assert record["location_raw"] == "Remote — EU"
    assert "RAG pipelines" in record["description"]


def test_a_location_inside_the_description_stays_text():
    """Fields are only read before the description starts, so a sentence in the
    posting that reads 'Location: …' is not mistaken for the field."""
    record = parse_postings(FILE)[0][0]
    assert "Location: this line is part of the posting" in record["description"]


def test_a_line_before_any_url_is_reported_not_silently_dropped():
    records, problems = parse_postings("title: floating\nhttps://e.com/1\n")
    assert len(records) == 1
    assert problems and "before any URL" in problems[0]


def test_a_bare_url_still_produces_a_unique_posting():
    """Without a derived title every bare URL would share the empty-string
    dedupe hash and all but the first would be discarded as a duplicate."""
    jobs = build_jobs([
        {"url": "https://www.linkedin.com/jobs/view/111"},
        {"url": "https://www.linkedin.com/jobs/view/222"},
    ])
    assert jobs[0].title != jobs[1].title
    assert jobs[0].dedupe_hash != jobs[1].dedupe_hash
    assert all(job.is_valid() for job in jobs)
    assert jobs[0].company_name == UNKNOWN_COMPANY


def test_thin_postings_are_identifiable_for_the_summary():
    records, _ = parse_postings(FILE)
    assert is_thin(records[1])       # the bare URL
    assert not is_thin(records[0])   # title and company given


async def test_an_imported_posting_lands_unanalysed_and_ready(db, settings):
    db.rpc_returns["match_jobs"] = []
    jobs = build_jobs([{
        "url": "https://www.linkedin.com/jobs/view/4123456789",
        "title": "Senior AI Engineer",
        "company_name": "Acme",
        "description": "RAG, LangChain, FastAPI",
    }], "linkedin")

    result = await Scout(db, settings).persist(jobs)

    assert result.kept == 1
    stored = db.tables["jobs"][0]
    assert stored["source"] == "linkedin"
    assert stored["company_id"] == db.tables["companies"][0]["id"]
    assert len(stored["embedding"]) == 384
    # No analysis yet, so the next batch picks it up like any other new posting.
    assert stored.get("analysis") is None


async def test_re_importing_the_same_file_stores_nothing_new(db, settings):
    db.rpc_returns["match_jobs"] = []
    records, _ = parse_postings(FILE)

    first = await Scout(db, settings).persist(build_jobs(records, "linkedin"))
    assert first.kept == 2

    again = await Scout(db, settings).persist(build_jobs(records, "linkedin"))
    assert again.kept == 0
    assert again.duplicates_url == 2
    assert len(db.tables["jobs"]) == 2


async def test_scout_skips_a_posting_that_was_imported(db, settings):
    """The importer and Scout share one persist path, so an imported URL is
    already known and will never be re-fetched or duplicated."""
    db.rpc_returns["match_jobs"] = []
    url = "https://www.linkedin.com/jobs/view/4123456789"
    await Scout(db, settings).persist(
        build_jobs([{"url": url, "title": "AI Engineer", "company_name": "Acme"}])
    )

    class Source:
        name = "linkedin"

        async def fetch(self, client):
            from app.agents.scout.base import RawJob
            return [RawJob("linkedin", url, "AI Engineer", "Acme")]

    result = await Scout(db, settings).run([Source()])
    assert result.kept == 0
    assert result.duplicates_url == 1
