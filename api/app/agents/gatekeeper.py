"""Gatekeeper: kill packages before any expensive call (§6).

Economics, from §8: killing a package costs one cheap call (the Analyst's,
already spent); building one costs five. So everything here is rules and
lookups — no LLM, no network beyond the sponsorship registers already cached
in Postgres.

Two rule sets run in order. The remote track is primary: most "remote" jobs are
geo-restricted and never say so in the title. The relocation track is the
fallback, and it is a register lookup — not on the register, not eligible.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from ..config import Settings, get_settings
from ..db import Database

log = logging.getLogger(__name__)

Verdict = Literal["clear", "uncertain", "blocked"]
Track = Literal["remote_fte", "relocation", "contract"]


# ── §6: universal kill phrases ────────────────────────────────────────────
KILL_PHRASES: tuple[tuple[str, str], ...] = (
    (r"no\s+visa\s+sponsorship", "states no visa sponsorship"),
    (r"(?:we|do)\s+(?:are\s+)?(?:not|n't|cannot|can't|unable to)\s+(?:able to\s+)?(?:offer|provide|sponsor)\w*\s+(?:visa|sponsorship|work permits?)",
     "states it cannot sponsor"),
    (r"sponsorship\s+is\s+not\s+(?:available|offered|provided)", "sponsorship not available"),
    (r"must\s+have\s+(?:an?\s+)?existing\s+right\s+to\s+work", "requires existing right to work"),
    (r"must\s+(?:already\s+)?be\s+(?:legally\s+)?(?:authori[sz]ed|eligible)\s+to\s+work",
     "requires existing work authorisation"),
    (r"without\s+(?:the\s+)?need\s+for\s+(?:visa\s+)?sponsorship", "requires no-sponsorship status"),
    (r"(?:us|u\.s\.)\s+citizens?\s+(?:or|and)\s+(?:permanent residents?|green card)",
     "restricted to US citizens or permanent residents"),
    (r"security\s+clearance\s+(?:is\s+)?required", "requires a security clearance"),
    (r"(?:must|required to)\s+(?:hold|possess)\s+(?:a\s+)?(?:us|uk|eu)\s+(?:citizenship|passport)",
     "requires a specific citizenship"),
)

# ── §6: geo restriction phrasing that a title never shows ─────────────────
GEO_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"remote\s*\(?\s*(?:only\s+)?(?:in\s+|within\s+|from\s+)?(?:the\s+)?(us|usa|united states|uk|united kingdom|eu|emea|apac|latam|canada|india|germany|netherlands|poland|brazil)\s*(?:only)?\s*\)?",
     "remote-but-restricted"),
    (r"must\s+(?:reside|be\s+(?:based|located|resident))\s+(?:in|within)\s+([A-Za-z ,./\-]{2,60})",
     "residency requirement"),
    (r"eligible\s+to\s+work\s+in\s+(?:the\s+)?([A-Za-z ,./\-]{2,60})", "work-eligibility requirement"),
    (r"(?:within|in)\s+(?:the\s+)?([A-Za-z]{2,20})\s+time\s*zones?", "timezone requirement"),
    (r"(?:candidates?|applicants?)\s+must\s+be\s+located\s+in\s+([A-Za-z ,./\-]{2,60})",
     "location requirement"),
    (r"authori[sz]ed\s+to\s+work\s+in\s+(?:the\s+)?([A-Za-z ,./\-]{2,40})", "work-eligibility requirement"),
    (r"this\s+(?:role|position)\s+is\s+(?:only\s+)?open\s+to\s+(?:candidates\s+in\s+)?([A-Za-z ,./\-]{2,60})",
     "explicit open-to restriction"),
)

# Companies already running one of these can hire from Pakistan with no visa
# involved. The single most valuable signal in the system (§6).
EOR_PROVIDERS: tuple[str, ...] = (
    "deel", "remote.com", "remote com", "oyster hr", "oysterhr", "oyster",
    "velocity global", "globalization partners", "g-p", "papaya global",
    "rippling eor", "multiplier", "omnipresent", "safeguard global",
    "employer of record", "eor",
)
EOR_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in EOR_PROVIDERS) + r")\b", re.I
)
INTERNATIONAL_HIRING_PATTERN = re.compile(
    r"(hire\s+(?:from\s+)?anywhere|work\s+from\s+anywhere|fully\s+distributed|"
    r"globally\s+distributed|remote[- ]first|any\s+time\s*zone|anywhere\s+in\s+the\s+world|"
    r"international\s+contractors?|contractor\s+of\s+record)",
    re.I,
)
CONTRACT_PATTERN = re.compile(
    r"\b(contract(?:or)?|freelance|b2b|statement of work|sow|6[- ]month|12[- ]month|fixed[- ]term)\b",
    re.I,
)

# Regions a Pakistan-based candidate can plausibly serve from without relocating.
# Overridable per profile via work_auth.remote_ok_regions.
DEFAULT_REMOTE_OK_REGIONS = frozenset(
    {"WORLDWIDE", "GLOBAL", "ANYWHERE", "REMOTE", "EMEA", "APAC", "ASIA", "MEA", "PK", "PAKISTAN"}
)
# Relocation destinations the spec names (§6) plus the registers we hold.
RELOCATION_TARGETS = frozenset({"UK", "GB", "UNITED KINGDOM", "NL", "NETHERLANDS", "DE", "GERMANY",
                                "CA", "CANADA", "EU", "IE", "IRELAND"})

REGISTER_COUNTRY = {
    "UK": "UK", "GB": "UK", "UNITED KINGDOM": "UK", "ENGLAND": "UK", "SCOTLAND": "UK",
    "NL": "NL", "NETHERLANDS": "NL", "HOLLAND": "NL", "AMSTERDAM": "NL",
    "CA": "CA", "CANADA": "CA", "TORONTO": "CA", "VANCOUVER": "CA",
}

# §6: Germany — EU Blue Card salary floor. The shortage-occupation (Engpassberuf)
# threshold applies to IT roles; both figures are gross annual EUR and are reset
# each January, so they live in one place.
BLUE_CARD_THRESHOLD_EUR = 48_300
BLUE_CARD_SHORTAGE_THRESHOLD_EUR = 43_759.80
BLUE_CARD_YEAR = 2025


@dataclass
class Eligibility:
    """Serialised straight into ``packages.eligibility``."""

    verdict: Verdict
    track: Track
    evidence: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.verdict in ("clear", "uncertain")

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "track": self.track,
            "evidence": self.evidence,
            "blockers": self.blockers,
            "signals": self.signals,
        }


def _normalise_region(value: str) -> str:
    return re.sub(r"[^A-Z ]", "", (value or "").upper()).strip()


def _haystack(job: dict[str, Any]) -> str:
    analysis = job.get("analysis") or {}
    return "\n".join(
        str(part)
        for part in (
            job.get("title"),
            job.get("location_raw"),
            job.get("description"),
            analysis.get("geo_evidence"),
            analysis.get("sponsorship_evidence"),
        )
        if part
    )


def find_kill_phrase(text: str) -> tuple[str, str] | None:
    for pattern, label in KILL_PHRASES:
        match = re.search(pattern, text, re.I)
        if match:
            return label, match.group(0)[:160]
    return None


def find_geo_signals(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for pattern, label in GEO_PATTERNS:
        for match in re.finditer(pattern, text, re.I):
            found.append((label, match.group(0)[:160]))
            if len(found) >= 6:
                return found
    return found


class Gatekeeper:
    def __init__(self, db: Database, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()
        self._register_cache: dict[tuple[str, str], bool] = {}

    # ── entry point ───────────────────────────────────────────────────────
    async def evaluate(
        self, job: dict[str, Any], company: dict[str, Any] | None, profile: dict[str, Any] | None
    ) -> Eligibility:
        analysis = job.get("analysis") or {}
        company = company or {}
        work_auth = (profile or {}).get("work_auth") or {}
        text = _haystack(job)

        evidence: list[str] = []
        blockers: list[str] = []
        signals: dict[str, Any] = {}

        # An EOR signal is checked before the kill phrases: a company that runs
        # payroll through Deel can hire from Pakistan whatever its boilerplate
        # says about visas.
        eor_match = EOR_PATTERN.search(text)
        company_hires_internationally = bool(company.get("hires_internationally"))
        signals["eor_mentioned"] = bool(eor_match)
        signals["company_hires_internationally"] = company_hires_internationally
        if eor_match:
            evidence.append(f"mentions an employer of record: “{eor_match.group(0)}”")
        if company_hires_internationally:
            evidence.append(f"{company.get('name') or 'company'} has hired internationally before")

        intl = INTERNATIONAL_HIRING_PATTERN.search(text)
        if intl:
            evidence.append(f"remote-first language: “{intl.group(0)}”")
        signals["international_language"] = bool(intl)

        # Universal kill phrases (§6).
        kill = find_kill_phrase(text)
        sponsorship = analysis.get("sponsorship_language", "silent")
        needs_sponsorship = work_auth.get("needs_sponsorship", True)
        has_eor_route = bool(eor_match) or company_hires_internationally or sponsorship == "eor_or_contractor"

        if kill and needs_sponsorship and not has_eor_route:
            label, quote = kill
            blockers.append(f"{label}: “{quote}”")
        elif kill and has_eor_route:
            evidence.append(
                f"kill phrase present (“{kill[1]}”) but an EOR route exists — flagged, not killed"
            )
            signals["kill_phrase_overridden"] = kill[1]

        if sponsorship == "no_sponsorship" and needs_sponsorship and not has_eor_route:
            quote = analysis.get("sponsorship_evidence") or "no sponsorship offered"
            blocker = f"posting rules out sponsorship: “{quote[:140]}”"
            if blocker not in blockers:
                blockers.append(blocker)
        elif sponsorship == "offers_sponsorship":
            evidence.append("posting explicitly offers visa sponsorship")
        elif sponsorship == "eor_or_contractor":
            evidence.append("posting mentions EOR or international contractor hiring")

        # Route to a track, then apply that track's rules.
        track = self.classify_track(job, analysis, has_eor_route)
        signals["track"] = track

        if track == "relocation":
            await self._relocation_rules(job, analysis, company, evidence, blockers, signals)
        else:
            self._remote_rules(job, analysis, work_auth, has_eor_route, text, evidence, blockers, signals)

        verdict: Verdict
        if blockers:
            verdict = "blocked"
        elif signals.get("geo_uncertain") or not evidence:
            verdict = "uncertain"
        else:
            verdict = "clear"

        return Eligibility(verdict, track, evidence[:10], blockers[:10], signals)

    # ── §2 track routing ──────────────────────────────────────────────────
    def classify_track(
        self, job: dict[str, Any], analysis: dict[str, Any], has_eor_route: bool
    ) -> Track:
        employment = analysis.get("employment_type", "unknown")
        title = job.get("title") or ""
        if employment == "contract" or CONTRACT_PATTERN.search(title):
            return "contract"

        policy = analysis.get("remote_policy", "unknown")
        geos = {_normalise_region(g) for g in analysis.get("geo_restriction") or []}

        if policy in ("onsite", "hybrid"):
            return "relocation" if geos & RELOCATION_TARGETS else "remote_fte"
        if policy == "global" or has_eor_route:
            return "remote_fte"
        if geos and not (geos & self._remote_ok_regions()):
            # Remote but restricted somewhere we cannot sit — only worth anything
            # if moving there is on the table.
            return "relocation" if geos & RELOCATION_TARGETS else "remote_fte"
        return "remote_fte"

    def _remote_ok_regions(self, work_auth: dict[str, Any] | None = None) -> frozenset[str]:
        custom = (work_auth or {}).get("remote_ok_regions")
        if custom:
            return frozenset(_normalise_region(c) for c in custom)
        return DEFAULT_REMOTE_OK_REGIONS

    # ── primary track (§6) ────────────────────────────────────────────────
    def _remote_rules(
        self,
        job: dict[str, Any],
        analysis: dict[str, Any],
        work_auth: dict[str, Any],
        has_eor_route: bool,
        text: str,
        evidence: list[str],
        blockers: list[str],
        signals: dict[str, Any],
    ) -> None:
        policy = analysis.get("remote_policy", "unknown")
        geos = [_normalise_region(g) for g in analysis.get("geo_restriction") or []]
        allowed = self._remote_ok_regions(work_auth)
        signals["remote_policy"] = policy
        signals["geo_restriction"] = geos

        phrase_signals = find_geo_signals(text)
        if phrase_signals:
            signals["geo_phrases"] = [quote for _, quote in phrase_signals]

        if policy in ("onsite", "hybrid"):
            blockers.append(f"role is {policy} and not in a relocation target country")
            return

        if policy == "global" and not geos:
            evidence.append("posting places no location requirement")
            return

        if geos:
            reachable = [g for g in geos if g in allowed]
            if reachable:
                evidence.append(f"restricted to {', '.join(geos)}, which is reachable")
                return
            if has_eor_route:
                evidence.append(
                    f"restricted to {', '.join(geos)} but the company hires via an EOR — worth a shot"
                )
                signals["geo_uncertain"] = True
                return
            blockers.append(
                f"geo-restricted to {', '.join(geos)} with no EOR route"
                + (f" — “{phrase_signals[0][1]}”" if phrase_signals else "")
            )
            return

        # No parsed restriction, but phrasing suggests one the Analyst missed.
        if phrase_signals and not has_eor_route:
            label, quote = phrase_signals[0]
            signals["geo_uncertain"] = True
            evidence.append(f"possible unparsed {label}: “{quote}” — needs a human look")
            return

        if has_eor_route:
            evidence.append("company has an international hiring route")
        else:
            signals["geo_uncertain"] = True

    # ── secondary track (§6) ──────────────────────────────────────────────
    async def _relocation_rules(
        self,
        job: dict[str, Any],
        analysis: dict[str, Any],
        company: dict[str, Any],
        evidence: list[str],
        blockers: list[str],
        signals: dict[str, Any],
    ) -> None:
        geos = [_normalise_region(g) for g in analysis.get("geo_restriction") or []]
        location = _normalise_region(job.get("location_raw") or "")
        countries = {
            REGISTER_COUNTRY[key]
            for key in list(geos) + location.split()
            if key in REGISTER_COUNTRY
        }
        if not countries:
            for key, code in REGISTER_COUNTRY.items():
                if key in location or any(key in g for g in geos):
                    countries.add(code)
        signals["relocation_countries"] = sorted(countries)

        is_germany = "GERMANY" in location or "DE" in geos or "GERMANY" in " ".join(geos)
        company_name = company.get("name") or ""

        if "UK" in countries:
            licensed = company.get("uk_sponsor_licensed")
            if licensed is None:
                licensed = await self._on_register("UK", company_name)
            if licensed:
                evidence.append(f"{company_name} is on the UK Register of Licensed Sponsors")
            else:
                blockers.append(
                    f"{company_name or 'company'} is not on the UK Register of Licensed Sponsors"
                )

        if "NL" in countries:
            recognised = company.get("nl_recognised_sponsor")
            if recognised is None:
                recognised = await self._on_register("NL", company_name)
            if recognised:
                evidence.append(f"{company_name} is an IND recognised sponsor")
            else:
                blockers.append(f"{company_name or 'company'} is not an IND recognised sponsor")

        if "CA" in countries:
            if await self._on_register("CA", company_name):
                evidence.append(f"{company_name} appears in LMIA-exempt / Global Talent Stream data")
            else:
                signals["geo_uncertain"] = True
                evidence.append("Canada: no LMIA-exemption record — verify before applying")

        if is_germany:
            salary = analysis.get("salary_max") or analysis.get("salary_min") or job.get("salary_max")
            currency = (analysis.get("salary_currency") or job.get("currency") or "EUR").upper()
            signals["blue_card_threshold_eur"] = BLUE_CARD_SHORTAGE_THRESHOLD_EUR
            if salary and currency == "EUR":
                if salary >= BLUE_CARD_SHORTAGE_THRESHOLD_EUR:
                    evidence.append(
                        f"€{salary:,} clears the {BLUE_CARD_YEAR} EU Blue Card shortage-occupation "
                        f"floor of €{BLUE_CARD_SHORTAGE_THRESHOLD_EUR:,.0f}"
                    )
                else:
                    blockers.append(
                        f"€{salary:,} is below the {BLUE_CARD_YEAR} EU Blue Card shortage-occupation "
                        f"floor of €{BLUE_CARD_SHORTAGE_THRESHOLD_EUR:,.0f}"
                    )
            else:
                signals["geo_uncertain"] = True
                evidence.append("Germany: no stated salary, so Blue Card eligibility is unverified")

        if not countries and not is_germany:
            signals["geo_uncertain"] = True

    async def _on_register(self, country: str, company_name: str) -> bool:
        if not company_name:
            return False
        key = (country, company_name.lower())
        if key in self._register_cache:
            return self._register_cache[key]
        try:
            result = await self.db.rpc(
                "is_licensed_sponsor", {"country_code": country, "company_name": company_name}
            )
            on_register = bool(result)
        except Exception as exc:
            log.warning("sponsor register lookup failed for %s/%s: %s", country, company_name, exc)
            on_register = False
        self._register_cache[key] = on_register
        return on_register

    # ── §6: the flag that compounds ───────────────────────────────────────
    async def record_international_hire(self, company_id: str, reason: str) -> None:
        """Set ``companies.hires_internationally`` once evidence appears. This
        flag is the single most valuable asset the system accumulates, so it is
        only ever set to true here — never cleared by a later silent posting."""
        if not company_id:
            return
        await self.db.update(
            "companies",
            {"hires_internationally": True, "notes": reason[:500]},
            eq={"id": company_id},
            returning=False,
        )
