"""Run an Apify actor and treat its dataset as a job source.

Apify hosts actors for a great many sites, and this adapter runs one
synchronously and maps the dataset items onto postings, so an actor feeds Scout
the same way a JSON API does.

Point it only at sources whose terms permit automated access. LinkedIn and
Indeed stay excluded by design (see ``docs/DECISIONS.md``): their terms forbid
automated access, and the account at risk is the one the user's applications are
sent from. Nothing here hardcodes an actor — the actor id and its input come from
settings — but neither does anything here make an excluded site acceptable.

Actors name their fields however they like, so the mapping below is a
best-effort alias list rather than a schema. An item with no URL, or one that
``RawJob`` will not accept (a posting needs a title and a company too), is
dropped rather than failing the source.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterable

import httpx

from ...config import Settings
from .base import RawJob, Source, parse_when, safe, strip_html

log = logging.getLogger(__name__)

# Apify's synchronous endpoint returns the run's dataset in the response body.
RUN_SYNC = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
# Apify caps a synchronous run at 300s; one posting's worth of typing is not
# worth waiting longer than that for.
RUN_TIMEOUT_S = 300.0

_URL_KEYS = (
    "source_url", "url", "jobUrl", "job_url", "link", "applyUrl", "apply_url",
    "jobPostingUrl", "absolute_url",
)
_TITLE_KEYS = ("title", "position", "jobTitle", "job_title", "name")
_COMPANY_KEYS = (
    "company_name", "companyName", "company", "employer", "organization",
    "hiringOrganization",
)
_LOCATION_KEYS = (
    "location_raw", "location", "jobLocation", "place", "city", "addressLocality",
)
_DESCRIPTION_KEYS = (
    "description", "descriptionText", "description_text", "jobDescription",
    "jobDescriptionText", "content", "text",
)
_POSTED_KEYS = ("posted_at", "postedAt", "datePosted", "publishedAt", "createdAt", "date")


def _first(item: dict, keys: Iterable[str]) -> str:
    """First non-empty value among ``keys``, unwrapping ``{"name": ...}``.

    Actors following schema.org return ``hiringOrganization: {"name": "Acme"}``
    and friends, so a nested ``name`` (or ``value``) is read rather than
    stringified.
    """
    for key in keys:
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("value")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


class ApifyActor(Source):
    """One Apify actor, its dataset treated as a list of postings."""

    name = "apify"

    def __init__(
        self,
        api_key: str,
        actor_id: str,
        run_input: dict | None = None,
        max_items: int = 200,
        timeout_s: float = RUN_TIMEOUT_S,
    ):
        self.api_key = api_key
        self.actor_id = (actor_id or "").strip()
        self.run_input = run_input or {}
        self.max_items = max_items
        self.timeout_s = timeout_s

    async def fetch(self, client: httpx.AsyncClient) -> list[RawJob]:
        if not (self.api_key and self.actor_id):
            log.info("apify: no api key or actor id, skipping")
            return []

        # The shared Scout client carries a 20s timeout; a run needs its own.
        resp = await client.post(
            RUN_SYNC.format(actor=self.actor_id),
            params={"token": self.api_key},
            json=self.run_input,
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            log.warning("apify: expected a dataset list, got %s", type(items).__name__)
            return []

        jobs = [self._to_job(item) for item in items[: self.max_items]]
        return safe(self.name, [job for job in jobs if job is not None])

    def _to_job(self, item: Any) -> RawJob | None:
        if not isinstance(item, dict):
            return None
        url = _first(item, _URL_KEYS)
        if not url:
            return None
        posted = next((item[k] for k in _POSTED_KEYS if item.get(k)), None)
        return RawJob(
            source=self.name,
            source_url=url,
            title=_first(item, _TITLE_KEYS),
            company_name=_first(item, _COMPANY_KEYS),
            description=strip_html(_first(item, _DESCRIPTION_KEYS)),
            location_raw=_first(item, _LOCATION_KEYS),
            posted_at=parse_when(posted),
        )


def build(settings: Settings, keywords: list[str]) -> ApifyActor:
    """Build the configured actor source.

    ``keywords`` is deliberately unused: actor input schemas differ too much to
    guess at, so the query belongs in ``APIFY_INPUT`` where the actor's own
    documentation can be followed.
    """
    try:
        run_input = json.loads(settings.apify_input or "{}")
    except json.JSONDecodeError:
        log.warning("apify: APIFY_INPUT is not valid JSON; running with no input")
        run_input = {}
    if not isinstance(run_input, dict):
        log.warning("apify: APIFY_INPUT must be a JSON object; running with no input")
        run_input = {}
    return ApifyActor(
        settings.apify_api_key,
        settings.apify_actor_id,
        run_input,
        settings.apify_max_items,
    )
