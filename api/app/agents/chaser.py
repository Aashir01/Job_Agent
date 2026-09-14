"""Chaser: follow-ups, reply detection, interview prep (§6).

The cadence is pre-approved — day 3 and day 10 — so the Chaser may schedule and
draft without asking. The content is not: each body waits for an explicit
approval before the Courier's mailer will send it. That keeps §1 intact
(nothing with the user's name leaves without a click) while removing the part
of follow-up that people actually fail at, which is remembering.
"""
from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..config import Settings, get_settings
from ..db import Database
from ..llm.base import LLMError
from ..llm.router import LLMRouter
from ..mailer import DailyCapReached, Mailer

log = logging.getLogger(__name__)

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

OPEN_STATUSES = ("submitted", "acknowledged")
REPLY_HINTS = re.compile(
    r"(interview|schedule|availability|next steps?|call|screen|chat|"
    r"unfortunately|not moving forward|other candidates|regret|offer)",
    re.I,
)
REJECTION_HINTS = re.compile(
    r"(unfortunately|not moving forward|decided to (?:move|proceed) with|"
    r"other candidates|will not be progressing|regret to inform)",
    re.I,
)
INTERVIEW_HINTS = re.compile(
    r"(schedule (?:a|an)|book a time|availability|calendly|interview|technical screen)", re.I
)


@dataclass
class ChaseResult:
    queued: int = 0
    sent: int = 0
    replies_found: int = 0
    advanced: list[dict[str, str]] = field(default_factory=list)
    dossiers: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "queued": self.queued,
            "sent": self.sent,
            "replies_found": self.replies_found,
            "advanced": self.advanced,
            "dossiers": self.dossiers,
            "errors": self.errors,
        }


DOSSIER_SCHEMA = {
    "type": "object",
    "properties": {
        "company_snapshot": {"type": "string"},
        "likely_questions": {"type": "array", "items": {"type": "string"}},
        "your_matching_stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"question": {"type": "string"}, "story": {"type": "string"}},
                "required": ["question", "story"],
            },
        },
        "questions_to_ask": {"type": "array", "items": {"type": "string"}},
        "gaps_to_prepare": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["likely_questions", "questions_to_ask"],
}

DOSSIER_PROMPT = """Build an interview prep dossier.

ROLE: {title} at {company}
JOB DESCRIPTION (excerpt):
{description}

THE CANDIDATE'S VERIFIED ACHIEVEMENTS — the only material for the stories:
{bullets}

WHAT THEY SAID IN THE REPLY:
{reply}

Give:
- company_snapshot: three sentences on what this company does and where this role sits.
- likely_questions: 8 questions this specific posting invites.
- your_matching_stories: for the 5 most likely, which verified achievement answers it
  and how to frame it. Never invent an achievement; if nothing fits, say so plainly.
- questions_to_ask: 5 questions that show the candidate read the posting.
- gaps_to_prepare: requirements the achievements do not cover, stated bluntly.

Return the JSON object only."""


class Chaser:
    agent = "chaser"

    def __init__(
        self,
        db: Database,
        llm: LLMRouter | None = None,
        settings: Settings | None = None,
        mailer: Mailer | None = None,
    ):
        self.db = db
        self.llm = llm
        self.settings = settings or get_settings()
        self.mailer = mailer or Mailer(db, self.settings)

    # ── cadence ───────────────────────────────────────────────────────────
    async def queue_due_follow_ups(self) -> int:
        """Mark drafted follow-ups due. Drafting already happened in the
        Connector; this only decides that today is the day."""
        now = datetime.now(timezone.utc)
        applications = await self.db.select(
            "applications", in_={"status": list(OPEN_STATUSES)}, limit=500
        )
        queued = 0
        for app in applications:
            submitted = _parse(app.get("submitted_at"))
            if not submitted:
                continue
            age = (now - submitted).days
            for kind, due_days in (
                ("follow_up_1", self.settings.follow_up_1_days),
                ("follow_up_2", self.settings.follow_up_2_days),
            ):
                if age < due_days:
                    continue
                rows = await self.db.select(
                    "outreach", eq={"application_id": app["id"], "kind": kind}, limit=1
                )
                if not rows or rows[0].get("sent_at") or rows[0].get("due_at"):
                    continue
                await self.db.update(
                    "outreach",
                    {"due_at": now.isoformat()},
                    eq={"id": rows[0]["id"]},
                    returning=False,
                )
                queued += 1
        return queued

    async def send_approved(self, client: httpx.AsyncClient | None = None) -> tuple[int, list[str]]:
        """Send only what a human has approved. §1, without exception."""
        due = await self.db.select(
            "outreach", columns="*,contacts(email,email_confidence,name)", limit=100
        )
        sent, errors = 0, []
        for note in due:
            if note.get("sent_at") or not note.get("approved_at") or not note.get("due_at"):
                continue
            contact = note.get("contacts") or {}
            if not contact.get("email") or contact.get("email_confidence") == "unknown":
                errors.append(f"outreach {note['id']}: no verified address")
                continue
            try:
                result = await self.mailer.send(
                    contact["email"],
                    f"Following up — {contact.get('name') or ''}".strip(" —"),
                    note["body"],
                    client=client,
                )
            except DailyCapReached as exc:
                errors.append(str(exc))
                break
            if result.ok:
                await self.db.update(
                    "outreach",
                    {"sent_at": datetime.now(timezone.utc).isoformat()},
                    eq={"id": note["id"]},
                    returning=False,
                )
                sent += 1
            else:
                await self.db.update(
                    "outreach", {"send_error": result.error}, eq={"id": note["id"]}, returning=False
                )
                errors.append(f"outreach {note['id']}: {result.error}")
        return sent, errors

    # ── Gmail reply detection ─────────────────────────────────────────────
    async def poll_replies(self, client: httpx.AsyncClient | None = None) -> ChaseResult:
        result = ChaseResult()
        token = await self._gmail_token(client)
        if not token:
            result.errors.append("Gmail is not configured; skipping reply detection")
            return result

        owns = client is None
        client = client or httpx.AsyncClient(timeout=20.0)
        try:
            resp = await client.get(
                f"{GMAIL_API}/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={"q": "newer_than:14d -in:sent -category:promotions", "maxResults": 50},
            )
            if resp.status_code >= 400:
                result.errors.append(f"gmail list {resp.status_code}: {resp.text[:200]}")
                return result

            open_apps = await self.db.select(
                "applications",
                columns="id,status,submitted_at,packages(job_id,jobs(title,companies(name,domain)))",
                in_={"status": list(OPEN_STATUSES)},
                limit=300,
            )
            index = self._index_applications(open_apps)
            if not index:
                return result

            for message in (resp.json().get("messages") or [])[:50]:
                detail = await client.get(
                    f"{GMAIL_API}/messages/{message['id']}",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"format": "full"},
                )
                if detail.status_code >= 400:
                    continue
                payload = detail.json()
                sender, subject, body = _extract_message(payload)
                match = self._match_application(sender, subject, body, index)
                if not match:
                    continue
                result.replies_found += 1
                status = self._classify(subject, body)
                await self.db.update(
                    "applications",
                    {"status": status, "last_status_at": datetime.now(timezone.utc).isoformat()},
                    eq={"id": match["id"]},
                    returning=False,
                )
                result.advanced.append({"application_id": match["id"], "status": status})
                if status in ("replied", "screen", "interview") and self.llm:
                    if await self.build_dossier(match["id"], body):
                        result.dossiers += 1
        finally:
            if owns:
                await client.aclose()
        return result

    def _index_applications(self, applications: list[dict]) -> dict[str, dict]:
        index: dict[str, dict] = {}
        for app in applications:
            job = ((app.get("packages") or {}).get("jobs")) or {}
            company = job.get("companies") or {}
            for key in (company.get("domain"), company.get("name"), job.get("title")):
                if key:
                    index[str(key).lower().strip()] = app
        return index

    def _match_application(
        self, sender: str, subject: str, body: str, index: dict[str, dict]
    ) -> dict | None:
        sender_domain = sender.split("@")[-1].strip(">").lower() if "@" in sender else ""
        if sender_domain and sender_domain in index:
            return index[sender_domain]
        haystack = f"{subject}\n{body[:600]}".lower()
        for key, app in index.items():
            if len(key) > 4 and key in haystack:
                return app
        return None

    def _classify(self, subject: str, body: str) -> str:
        text = f"{subject}\n{body}"
        if REJECTION_HINTS.search(text):
            return "rejected"
        if INTERVIEW_HINTS.search(text):
            return "interview"
        if REPLY_HINTS.search(text):
            return "replied"
        return "acknowledged"

    async def _gmail_token(self, client: httpx.AsyncClient | None) -> str | None:
        refresh = getattr(self.settings, "gmail_refresh_token", "")
        client_id = getattr(self.settings, "google_client_id", "")
        secret = getattr(self.settings, "google_client_secret", "")
        if not (refresh and client_id and secret):
            return None
        owns = client is None
        client = client or httpx.AsyncClient(timeout=15.0)
        try:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": secret,
                    "refresh_token": refresh,
                    "grant_type": "refresh_token",
                },
            )
            if resp.status_code >= 400:
                log.warning("gmail token refresh failed: %s", resp.text[:200])
                return None
            return resp.json().get("access_token")
        except httpx.HTTPError as exc:
            log.warning("gmail token refresh failed: %s", exc)
            return None
        finally:
            if owns:
                await client.aclose()

    # ── interview prep ────────────────────────────────────────────────────
    async def build_dossier(self, application_id: str, reply_text: str = "") -> bool:
        if not self.llm:
            return False
        existing = await self.db.select("dossiers", eq={"application_id": application_id}, limit=1)
        if existing:
            return False

        app = await self.db.select_one(
            "applications",
            columns="id,packages(job_id,resume_diff,jobs(title,description,companies(name)))",
            eq={"id": application_id},
        )
        if not app:
            return False
        package = app.get("packages") or {}
        job = package.get("jobs") or {}
        company = job.get("companies") or {}

        diff = package.get("resume_diff") or {}
        bullets = [e.get("final", "") for e in diff.get("entries") or []]
        if not bullets:
            rows = await self.db.select("bullet_bank", columns="text", order="strength.desc", limit=10)
            bullets = [r["text"] for r in rows]

        prompt = DOSSIER_PROMPT.format(
            title=job.get("title") or "",
            company=company.get("name") or "",
            description=(job.get("description") or "")[:4000],
            bullets="\n".join(f"- {b}" for b in bullets) or "(none on file)",
            reply=(reply_text or "(no reply text captured)")[:1500],
        )
        try:
            content = await self.llm.generate_json(
                prompt, agent=self.agent, tier="good", schema=DOSSIER_SCHEMA, max_tokens=2400
            )
        except (LLMError, ValueError) as exc:
            log.warning("dossier generation failed for %s: %s", application_id, exc)
            return False

        await self.db.insert(
            "dossiers", {"application_id": application_id, "content": content}, returning=False
        )
        return True

    async def mark_ghosted(self, after_days: int = 30) -> int:
        """Nothing back well past the second follow-up is a 'no' worth recording."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=after_days)).isoformat()
        rows = await self.db.select(
            "applications", in_={"status": list(OPEN_STATUSES)}, lte={"submitted_at": cutoff}, limit=200
        )
        for app in rows:
            await self.db.update(
                "applications",
                {"status": "ghosted", "last_status_at": datetime.now(timezone.utc).isoformat()},
                eq={"id": app["id"]},
                returning=False,
            )
        return len(rows)


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _extract_message(payload: dict[str, Any]) -> tuple[str, str, str]:
    headers = {
        h.get("name", "").lower(): h.get("value", "")
        for h in (payload.get("payload") or {}).get("headers") or []
    }
    body = _walk_parts(payload.get("payload") or {})
    return headers.get("from", ""), headers.get("subject", ""), body


def _walk_parts(part: dict[str, Any]) -> str:
    if part.get("mimeType") == "text/plain":
        data = (part.get("body") or {}).get("data")
        if data:
            try:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", "replace")
            except Exception:
                return ""
    for child in part.get("parts") or []:
        if text := _walk_parts(child):
            return text
    return ""
