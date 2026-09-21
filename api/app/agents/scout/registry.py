"""The Scout's platform registry.

One list, shared by the Scout, the API and the dashboard, so a platform can never
be offered in the picker without an implementation behind it — or implemented and
silently unreachable from the UI.

Two shapes of platform:

* **Per-company ATS boards** need a slug, so they live in ``source_seeds`` one row
  per company. Selecting the platform enables every seeded board of that kind.
* **Aggregators** are general boards that take no configuration, except Adzuna,
  whose query is built from the run's keywords.
"""
from __future__ import annotations

from typing import Callable

from ...config import Settings
from .ats import ATS_SOURCES
from .base import Source
from .boards import (
    Adzuna,
    Arbeitnow,
    HackerNewsHiring,
    Himalayas,
    RemoteOK,
    Remotive,
    WeWorkRemotely,
)

ATS_PLATFORMS: tuple[str, ...] = (
    "greenhouse",
    "lever",
    "ashby",
    "workable",
    "smartrecruiters",
)

AGGREGATORS: dict[str, Callable[[Settings, list[str]], Source]] = {
    "remotive": lambda settings, keywords: Remotive(),
    "remoteok": lambda settings, keywords: RemoteOK(),
    "arbeitnow": lambda settings, keywords: Arbeitnow(),
    "himalayas": lambda settings, keywords: Himalayas(),
    "weworkremotely": lambda settings, keywords: WeWorkRemotely(),
    "hn_hiring": lambda settings, keywords: HackerNewsHiring(),
    # The one aggregator that takes a query: the user's keywords, or the
    # historical default so an unconfigured install behaves as before.
    "adzuna": lambda settings, keywords: Adzuna(
        settings.adzuna_app_id,
        settings.adzuna_app_key,
        what=", ".join(keywords) or "python engineer",
    ),
}

PLATFORM_IDS: tuple[str, ...] = ATS_PLATFORMS + tuple(AGGREGATORS)

LABELS: dict[str, str] = {
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "ashby": "Ashby",
    "workable": "Workable",
    "smartrecruiters": "SmartRecruiters",
    "remotive": "Remotive",
    "remoteok": "RemoteOK",
    "arbeitnow": "Arbeitnow",
    "himalayas": "Himalayas",
    "weworkremotely": "WeWorkRemotely",
    "hn_hiring": 'Hacker News "Who is hiring"',
    "adzuna": "Adzuna (needs an API key)",
}

# LinkedIn and Indeed are deliberately absent: they are harvested by the Chrome
# extension from pages the user is already on, never fetched server-side.

def is_ats(platform_id: str) -> bool:
    return platform_id in ATS_SOURCES


def known(platform_id: str) -> bool:
    return platform_id in PLATFORM_IDS


def build_aggregator(platform_id: str, settings: Settings, keywords: list[str]) -> Source | None:
    builder = AGGREGATORS.get(platform_id)
    return builder(settings, keywords) if builder else None


def select(platforms: list[str] | None) -> tuple[list[str], list[str]]:
    """Split a selection into (ats kinds, aggregator ids).

    An empty or absent selection means "all platforms", so an install that never
    opens the Setup page behaves exactly as it did before the picker existed.
    Unknown ids are dropped rather than raising: the saved row may predate a
    rename, and a stale id should not stop a batch.
    """
    if not platforms:
        return list(ATS_PLATFORMS), list(AGGREGATORS)
    ats = [p for p in platforms if is_ats(p)]
    aggs = [p for p in platforms if p in AGGREGATORS]
    return ats, aggs
