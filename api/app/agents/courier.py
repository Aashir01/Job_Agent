"""Courier: the only agent that submits. Fires on approval, never before (§6).

Route, in order:
  1. an ATS API, where the company has one we hold credentials for
  2. the Chrome extension queue — the extension fills, the user clicks Submit
  3. email to a verified address

Both hard caps from §10 are enforced here, atomically, in the database.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import Settings, get_settings
from ..db import Database
from ..mailer import DailyCapReached, Mailer

log = logging.getLogger(__name__)

# ATS boards that accept a programmatic application, and what they need.
# Every one of these requires per-company credentials the public board API does
# not hand out, so in practice most packages take route 2. That is by design:
# the extension path keeps the user in their own session, which §1 requires.
ATS_API_SUPPORT = {"greenhouse": "board_token", "lever": "posting_id", "ashby": "api_key"}


class NotApproved(RuntimeError):
    """The human gate. A package that is not approved never goes anywhere."""


@dataclass
class SubmissionResult:
    ok: bool
    method: str                       # ats_api|extension|email
    application_id: str | None = None
    detail: str = ""


class Courier:
    agent = "courier"

    def __init__(self, db: Database, settings: Settings | None = None, mailer: Mailer | None = None):
        self.db = db
        self.settings = settings or get_settings()
        self.mailer = mailer or Mailer(db, self.settings)

    async def submit(self, package_id: str, client: httpx.AsyncClient | None = None) -> SubmissionResult:
        package = await self.db.select_one("packages", eq={"id": package_id})
        if not package:
            raise ValueError(f"no package {package_id}")

        # Re-read status from the database rather than trusting the caller:
        # this is the gate, and it must not be bypassable by a stale payload.
        if package.get("status") != "approved":
            raise NotApproved(
                f"package {package_id} is '{package.get('status')}', not 'approved' — "
                "the Courier only fires on approved packages"
            )

        job = await self.db.select_one("jobs", eq={"id": package["job_id"]})
        company = (
            await self.db.select_one("companies", eq={"id": job["company_id"]})
            if job and job.get("company_id")
            else None
        ) or {}

        method, detail = await self._route(package, job or {}, company, client)
        ok = method != "failed"

        application_id = None
        if ok:
            rows = await self.db.insert(
                "applications",
                {
                    "package_id": package_id,
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "method": method,
                    "status": "submitted",
                    "last_status_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            application_id = rows[0]["id"] if rows else None
            await self.db.update(
                "packages", {"status": "submitted"}, eq={"id": package_id}, returning=False
            )
            # §6: a company that accepted an international application is
            # evidence the flag should compound.
            if company.get("id") and (package.get("eligibility") or {}).get("track") == "remote_fte":
                await self.db.update(
                    "companies",
                    {"hires_internationally": True},
                    eq={"id": company["id"]},
                    returning=False,
                )
        else:
            await self.db.update(
                "packages", {"status": "failed"}, eq={"id": package_id}, returning=False
            )

        return SubmissionResult(ok, method, application_id, detail)

    async def _route(
        self,
        package: dict[str, Any],
        job: dict[str, Any],
        company: dict[str, Any],
        client: httpx.AsyncClient | None,
    ) -> tuple[str, str]:
        ats = (company.get("ats_type") or "").lower()
        if ats in ATS_API_SUPPORT and company.get("ats_credentials"):
            try:
                await self._submit_via_ats(package, job, company, client)
                return "ats_api", f"submitted through the {ats} API"
            except Exception as exc:
                log.warning("ATS submission failed, falling back to the extension: %s", exc)

        if job.get("source_url"):
            try:
                await self.enqueue_for_extension(package, job)
                return "extension", "queued for the extension; the user clicks Submit"
            except DailyCapReached as exc:
                return "failed", str(exc)

        contact = (
            await self.db.select_one(
                "contacts", eq={"company_id": company.get("id"), "email_confidence": "verified"}
            )
            if company.get("id")
            else None
        )
        if contact and contact.get("email"):
            try:
                result = await self.mailer.send(
                    contact["email"],
                    f"Application — {job.get('title', '')}",
                    package.get("cover_letter") or "",
                    client=client,
                )
            except DailyCapReached as exc:
                return "failed", str(exc)
            if result.ok:
                return "email", f"emailed {contact['email']}"
            return "failed", result.error or "email failed"

        return "failed", "no ATS credentials, no source URL and no verified contact email"

    async def enqueue_for_extension(self, package: dict[str, Any], job: dict[str, Any]) -> str:
        """§10: 20 extension submissions a day, enforced when the row is created."""
        count = await self.db.rpc(
            "bump_daily_counter",
            {
                "counter_name": "extension_submit",
                "cap": self.settings.max_extension_submits_per_day,
                "amount": 1,
            },
        )
        if count is None or int(count) < 0:
            raise DailyCapReached(
                f"daily extension submission cap of "
                f"{self.settings.max_extension_submits_per_day} is reached"
            )

        profile = await self.db.select_one("profile", limit=1) or {}
        payload = {
            "job_title": job.get("title"),
            "source_url": job.get("source_url"),
            "full_name": profile.get("full_name"),
            "email": profile.get("email"),
            "phone": profile.get("phone"),
            "location": profile.get("location"),
            "links": profile.get("links") or {},
            "resume_url": package.get("resume_url"),
            "cover_letter": package.get("cover_letter"),
            "screening_answers": (package.get("screening_answers") or {}).get("answers") or [],
            # The extension fills and stops. It never clicks Submit (§10).
            "autosubmit": False,
        }
        rows = await self.db.insert(
            "extension_queue",
            {"package_id": package["id"], "target_url": job["source_url"], "payload": payload},
            upsert=True,
            on_conflict="package_id",
        )
        return rows[0]["id"] if rows else ""

    async def _submit_via_ats(
        self,
        package: dict[str, Any],
        job: dict[str, Any],
        company: dict[str, Any],
        client: httpx.AsyncClient | None,
    ) -> None:
        raise NotImplementedError(
            f"{company.get('ats_type')} submission needs per-company credentials "
            "that the public board API does not issue"
        )

    async def send_pre_apply(
        self, application_id: str, client: httpx.AsyncClient | None = None
    ) -> bool:
        """The pre-apply note, sent only alongside an approved submission."""
        rows = await self.db.select(
            "outreach", eq={"application_id": application_id, "kind": "pre_apply"}, limit=1
        )
        if not rows or rows[0].get("sent_at"):
            return False
        note = rows[0]
        contact = (
            await self.db.select_one("contacts", eq={"id": note["contact_id"]})
            if note.get("contact_id")
            else None
        )
        if not contact or not contact.get("email"):
            return False
        if contact.get("email_confidence") == "unknown":
            log.info("skipping pre-apply note: %s is unverified", contact["email"])
            return False

        try:
            result = await self.mailer.send(
                contact["email"], f"Quick note — {contact.get('name', '')}".strip(),
                note["body"], client=client,
            )
        except DailyCapReached as exc:
            log.warning("pre-apply note not sent: %s", exc)
            return False
        if result.ok:
            await self.db.update(
                "outreach",
                {"sent_at": datetime.now(timezone.utc).isoformat()},
                eq={"id": note["id"]},
                returning=False,
            )
        return result.ok
