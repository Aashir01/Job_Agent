"""Discovery filters, applied in the Scout before anything costs money."""
from __future__ import annotations

from app.agents.scout.base import RawJob
from app.agents.scout.filters import apply_filters


def job(title, location="Remote", description="", salary_min=None, salary_max=None,
        currency=None, source="x"):
    return RawJob(
        source,
        f"https://e.com/{source}/{title}/{location}",
        title,
        "Acme",
        description=description,
        location_raw=location,
        salary_min=salary_min,
        salary_max=salary_max,
        currency=currency,
    )


def test_no_filters_keeps_everything():
    kept, drops = apply_filters([job("A"), job("B")], None)
    assert len(kept) == 2
    assert drops == {}


def test_keywords_keep_only_matching_postings():
    kept, drops = apply_filters(
        [job("Python Engineer"), job("Sales Executive", description="quota")],
        {"keywords": ["python"]},
    )
    assert [j.title for j in kept] == ["Python Engineer"]
    assert drops == {"keywords": 1}


def test_exclude_keywords_drop_on_any_match():
    kept, drops = apply_filters(
        [job("Python Engineer", description="security clearance required")],
        {"exclude_keywords": ["clearance"]},
    )
    assert kept == []
    assert drops == {"exclude_keywords": 1}


def test_remote_only_drops_onsite_roles():
    kept, drops = apply_filters(
        [
            job("Engineer", location="Remote (EU)"),
            job("Engineer", location="Berlin, Germany", description="on-site role"),
        ],
        {"remote_only": True},
    )
    assert [j.location_raw for j in kept] == ["Remote (EU)"]
    assert drops == {"remote_only": 1}


def test_locations_keep_remote_roles_and_matches_only():
    kept, drops = apply_filters(
        [job("A", location="London, UK"), job("B", location="Remote"), job("C", location="Tokyo, Japan")],
        {"locations": ["london"]},
    )
    assert {j.location_raw for j in kept} == {"London, UK", "Remote"}
    assert drops == {"locations": 1}


def test_seniority_drops_only_an_explicit_mismatch():
    kept, drops = apply_filters(
        [job("Senior Engineer"), job("Junior Engineer"), job("Engineer")],
        {"seniority": ["senior"]},
    )
    # An unlevelled title is ambiguous, not a mismatch.
    assert {j.title for j in kept} == {"Senior Engineer", "Engineer"}
    assert drops == {"seniority": 1}


def test_sre_is_not_mistaken_for_senior():
    """'sr' has to match a whole word, or every SRE is senior by accident."""
    kept, drops = apply_filters([job("Site Reliability Engineer")], {"seniority": ["junior"]})
    assert len(kept) == 1
    assert drops == {}


def test_salary_floor_never_drops_an_undisclosed_salary():
    kept, drops = apply_filters(
        [job("A", salary_min=30000, salary_max=40000, currency="USD"), job("B")],
        {"salary_floor_usd": 60000},
    )
    assert [j.title for j in kept] == ["B"]
    assert drops == {"salary_floor": 1}


def test_salary_floor_leaves_non_usd_ranges_alone():
    """A EUR range is not comparable to a USD floor."""
    kept, drops = apply_filters(
        [job("A", salary_min=30000, salary_max=40000, currency="EUR")],
        {"salary_floor_usd": 60000},
    )
    assert len(kept) == 1
    assert drops == {}
