"""Connector: find the human, draft the note. Sends nothing (§6).

Everything here stops at a draft row. The Courier is the only agent that puts
anything on the wire, and only after the human gate.

LinkedIn is never touched server-side. Referral hunting produces a *search
plan* the Chrome extension resolves passively while the user browses their own
session, which is the only way to do it without violating the platform's terms.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

import httpx

from ..config import Settings, get_settings
from ..db import Database
from ..llm.base import LLMError, QuotaExhausted
from ..llm.router import LLMRouter

log = logging.getLogger(__name__)

# The patterns worth trying when companies.email_pattern is unknown, ordered by
# how common they are in practice.
FALLBACK_PATTERNS = ("{first}.{last}@", "{first}@", "{f}{last}@", "{first}{last}@", "{first}_{last}@")

_NON_ALPHA = re.compile(r"[^a-z]")


def split_name(full_name: str) -> tuple[str, str]:
    parts = [p for p in re.split(r"\s+", (full_name or "").strip()) if p]
    if not parts:
        return "", ""
    first = _NON_ALPHA.sub("", parts[0].lower())
    last = _NON_ALPHA.sub("", parts[-1].lower()) if len(parts) > 1 else ""
    return first, last


def guess_email(pattern: str | None, full_name: str, domain: str | None) -> str | None:
    """Render companies.email_pattern for one person."""
    if not domain:
        return None
    first, last = split_name(full_name)
    if not first:
        return None
    template = (pattern or FALLBACK_PATTERNS[0]).strip()
    if not template.endswith("@"):
        template = template.split("@")[0] + "@"
    local = (
        template[:-1]
        .replace("{first}", first)
        .replace("{last}", last)
        .replace("{f}", first[:1])
        .replace("{l}", last[:1] if last else "")
    )
    local = re.sub(r"[^a-z0-9._\-]", "", local).strip("._-")
    domain = domain.replace("https://", "").replace("http://", "").strip("/").split("/")[0]
    return f"{local}@{domain}" if local else None


async def domain_accepts_mail(domain: str) -> bool:
    """MX lookup only. Never an SMTP probe — RCPT-TO probing gets the sending
    domain blacklisted, which §10 is explicit about protecting."""
    if not domain:
        return False
    try:
        import dns.asyncresolver
        import dns.resolver
    except ImportError:
        log.info("dnspython not installed; skipping MX verification")
        return False
    try:
        answers = await dns.asyncresolver.resolve(domain, "MX", lifetime=5.0)
        return len(answers) > 0
    except Exception:
        return False


async def verify_with_hunter(
    email: str, api_key: str, client: httpx.AsyncClient | None = None
) -> str:
    """Returns verified|pattern_guess|unknown. Hunter's free tier is 25/month,
    so this is called only for the contact actually being written to."""
    if not api_key:
        return "unknown"
    owns = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    try:
        resp = await client.get(
            "https://api.hunter.io/v2/email-verifier",
            params={"email": email, "api_key": api_key},
        )
        if resp.status_code != 200:
            return "unknown"
        status = (resp.json().get("data") or {}).get("status", "")
    except httpx.HTTPError:
        return "unknown"
    finally:
        if owns:
            await client.aclose()
    return "verified" if status in ("valid", "accept_all") else "unknown"


OUTREACH_SCHEMA = {
    "type": "object",
    "properties": {
        "pre_apply": {"type": "string"},
        "follow_up_1": {"type": "string"},
        "follow_up_2": {"type": "string"},
        "subject": {"type": "string"},
    },
    "required": ["pre_apply", "follow_up_1", "follow_up_2", "subject"],
}

SYSTEM = (
    "You write short, specific outreach notes from one engineer to another. Under 120 "
    "words each. No flattery, no 'I hope this finds you well', no bullet lists. You may "
    "only cite achievements from the list you are given. Never claim a mutual connection, "
    "a referral, or a prior conversation unless it is stated in the referral context."
)

PROMPT = """Draft three notes about one application.

FROM: {candidate} — {headline}, based in {location}
TO: {contact_name}{contact_role} at {company}
ROLE APPLIED FOR: {title}
WHY THEM: {why}
VERIFIED ACHIEVEMENTS (the only ones you may cite):
{bullets}
REFERRAL CONTEXT: {referral}

1. pre_apply — sent just before the application. One line on what the candidate
   built that is relevant to this specific role, one question about the team.
2. follow_up_1 — {d1} days after applying, if silent. Adds one new piece of
   information, does not repeat the first note.
3. follow_up_2 — {d2} days after applying, if still silent. Short, closes the
   loop gracefully, leaves the door open.

Also give one email subject line under 60 characters. No emoji.

Return JSON with keys: pre_apply, follow_up_1, follow_up_2, subject."""


@dataclass
class ConnectorResult:
    contacts: list[dict[str, Any]] = field(default_factory=list)
    drafts: dict[str, str] = field(default_factory=dict)
    referral_plan: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class Connector:
    agent = "connector"

    def __init__(self, db: Database, llm: LLMRouter, settings: Settings | None = None):
        self.db = db
        self.llm = llm
        self.settings = settings or get_settings()

    async def run(
        self,
        job: dict[str, Any],
        company: dict[str, Any],
        profile: dict[str, Any],
        bullets: Sequence[Any],
        analysis: dict[str, Any] | None = None,
        batch_id: str | None = None,
    ) -> ConnectorResult:
        result = ConnectorResult()
        company_id = company.get("id")

        known = (
            await self.db.select("contacts", eq={"company_id": company_id}, limit=20)
            if company_id
            else []
        )
        result.contacts = list(known)

        for contact in known:
            if contact.get("email") or not contact.get("name"):
                continue
            email = guess_email(company.get("email_pattern"), contact["name"], company.get("domain"))
            if not email:
                continue
            confidence = "pattern_guess"
            if await domain_accepts_mail(email.split("@")[-1]):
                confidence = await verify_with_hunter(email, self.settings.hunter_api_key)
                if confidence == "unknown":
                    confidence = "pattern_guess"
            else:
                result.notes.append(f"{email.split('@')[-1]} has no MX record — email route is dead")
                continue
            await self.db.update(
                "contacts",
                {"email": email, "email_confidence": confidence},
                eq={"id": contact["id"]},
                returning=False,
            )
            contact["email"], contact["email_confidence"] = email, confidence

        result.referral_plan = self.referral_plan(profile, company)
        if not known:
            result.notes.append(
                "no contact on file — the extension will harvest one as the user browses"
            )

        target = known[0] if known else {}
        result.drafts = await self.draft(
            job, company, profile, bullets, target, analysis or {}, result.referral_plan, batch_id
        )
        return result

    def referral_plan(self, profile: dict[str, Any], company: dict[str, Any]) -> list[dict[str, Any]]:
        """A search plan for the extension, not a server-side scrape (§6, §10)."""
        alumni_orgs = [
            entry.get("institution")
            for entry in profile.get("education") or []
            if entry.get("institution")
        ] or list(profile.get("alumni_networks") or [])
        company_name = company.get("name") or ""
        plan = [
            {
                "kind": "alumni",
                "org": org,
                "company": company_name,
                "hint": f'LinkedIn people search: "{org}" at "{company_name}"',
            }
            for org in alumni_orgs
        ]
        if country := (profile.get("work_auth") or {}).get("passport"):
            plan.append(
                {
                    "kind": "nationality_network",
                    "org": country,
                    "company": company_name,
                    "hint": f'Engineers from {country} at "{company_name}"',
                }
            )
        return plan

    async def draft(
        self,
        job: dict[str, Any],
        company: dict[str, Any],
        profile: dict[str, Any],
        bullets: Sequence[Any],
        contact: dict[str, Any],
        analysis: dict[str, Any],
        referral_plan: list[dict[str, Any]],
        batch_id: str | None,
    ) -> dict[str, str]:
        lines = []
        for bullet in list(bullets)[:6]:
            text = getattr(bullet, "final", None) or (
                bullet.get("text") if isinstance(bullet, dict) else str(bullet)
            )
            lines.append(f"- {text}")

        prompt = PROMPT.format(
            candidate=profile.get("full_name") or "the candidate",
            headline=profile.get("headline") or "",
            location=profile.get("location") or "",
            contact_name=contact.get("name") or "the hiring manager",
            contact_role=f" ({contact['role']})" if contact.get("role") else "",
            company=company.get("name") or "the company",
            title=job.get("title") or "",
            why=", ".join((analysis.get("company_facts") or [])[:2]) or "not stated in the posting",
            bullets="\n".join(lines) or "(none — cite nothing specific)",
            referral=(
                "; ".join(p["hint"] for p in referral_plan)
                if referral_plan
                else "no known connection — do not imply one"
            ),
            d1=self.settings.follow_up_1_days,
            d2=self.settings.follow_up_2_days,
        )
        try:
            data = await self.llm.generate_json(
                prompt,
                agent=self.agent,
                tier="cheap",
                schema=OUTREACH_SCHEMA,
                system=SYSTEM,
                temperature=0.4,
                max_tokens=1200,
                batch_id=batch_id,
                job_id=job.get("id"),
            )
        except QuotaExhausted:
            raise
        except (LLMError, ValueError) as exc:
            log.warning("connector draft failed: %s", exc)
            return {}
        return {
            key: str(data.get(key) or "")[:2500]
            for key in ("subject", "pre_apply", "follow_up_1", "follow_up_2")
        }

    async def persist_drafts(
        self, application_id: str, contact_id: str | None, drafts: dict[str, str]
    ) -> None:
        """Rows land unsent. ``sent_at`` stays null until the Courier fires."""
        rows = [
            {
                "application_id": application_id,
                "contact_id": contact_id,
                "kind": kind,
                "body": drafts[kind],
                "sent_at": None,
            }
            for kind in ("pre_apply", "follow_up_1", "follow_up_2")
            if drafts.get(kind)
        ]
        if rows:
            await self.db.insert("outreach", rows, returning=False)
