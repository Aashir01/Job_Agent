"""Outbound email via Resend, under the §10 hard cap.

The cap is enforced in Postgres with an atomic counter, not in process memory:
two batches running at once must not each think they have 30 sends left.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from .config import Settings, get_settings
from .db import Database

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


class DailyCapReached(RuntimeError):
    """§10: volume destroys deliverability. The cap is not advisory."""


@dataclass
class SendResult:
    ok: bool
    provider_id: str | None = None
    error: str | None = None


class Mailer:
    def __init__(self, db: Database, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()

    async def reserve_send(self) -> None:
        """Claim one slot from today's allowance before composing anything."""
        count = await self.db.rpc(
            "bump_daily_counter",
            {"counter_name": "outbound_email", "cap": self.settings.max_outbound_emails_per_day, "amount": 1},
        )
        if count is None or int(count) < 0:
            raise DailyCapReached(
                f"daily outbound email cap of {self.settings.max_outbound_emails_per_day} is reached"
            )

    async def release_send(self) -> None:
        """Give the slot back when the send failed before leaving the building."""
        try:
            await self.db.rpc(
                "bump_daily_counter",
                {"counter_name": "outbound_email", "cap": 10_000, "amount": -1},
            )
        except Exception as exc:
            log.warning("could not release an email slot: %s", exc)

    async def send(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> SendResult:
        if not self.settings.resend_api_key or not self.settings.from_email:
            return SendResult(False, error="Resend is not configured")

        await self.reserve_send()
        owns = client is None
        client = client or httpx.AsyncClient(timeout=15.0)
        try:
            resp = await client.post(
                RESEND_URL,
                headers={"Authorization": f"Bearer {self.settings.resend_api_key}"},
                json={
                    "from": self.settings.from_email,
                    "to": [to],
                    "subject": subject[:200],
                    "text": body,
                    **({"reply_to": reply_to} if reply_to else {}),
                },
            )
        except httpx.HTTPError as exc:
            await self.release_send()
            return SendResult(False, error=f"transport: {exc}")
        finally:
            if owns:
                await client.aclose()

        if resp.status_code >= 400:
            await self.release_send()
            return SendResult(False, error=f"{resp.status_code}: {resp.text[:300]}")
        return SendResult(True, provider_id=(resp.json() or {}).get("id"))
