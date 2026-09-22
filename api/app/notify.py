"""Push a digest of what a run found.

The point of the whole system is that you do not have to remember to look. A
batch that quietly fills a queue at 02:00 UTC is worth nothing if nobody opens
the dashboard, so every run ends by pushing what it found to whatever channels
are configured.

Channels are independent and best-effort: one failing never blocks another, and
a failed delivery never fails the batch. A run that found nothing says nothing
unless ``notify_on_empty`` is set — a digest that arrives twice a day saying
"0 new" trains you to ignore the ones that matter.

Telegram is the recommended default. WhatsApp has no free first-party API, so
it is reachable through ``notify_webhook_url`` and a relay (CallMeBot and
similar), not as a channel of its own.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

import httpx

from .config import Settings, get_settings
from .db import Database

log = logging.getLogger(__name__)

TIER_ICON = {"fast_lane": "🟢", "standard": "🟡", "marginal": "🟠"}
TIER_LABEL = {"fast_lane": "fast lane", "standard": "standard", "marginal": "marginal"}


@dataclass
class DigestJob:
    title: str
    company: str
    score: int
    tier: str
    track: str = ""
    location: str = ""
    url: str = ""

    @property
    def icon(self) -> str:
        return TIER_ICON.get(self.tier, "⚪")


@dataclass
class Digest:
    """What one run produced, in a shape every channel can render."""

    headline: str
    kind: str = "batch"                       # batch|chaser|error
    stats: dict[str, Any] = field(default_factory=dict)
    jobs: list[DigestJob] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    dashboard_url: str = ""
    error: str = ""
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_empty(self) -> bool:
        return not self.jobs and not self.lines and not self.error

    # ── renderers ─────────────────────────────────────────────────────────
    def as_text(self, top_n: int = 8) -> str:
        """Plain text. The lowest common denominator, used by webhooks and email."""
        out = [self.headline, ""]
        out += [f"• {line}" for line in self.lines]
        if self.jobs:
            out.append("")
            for job in self.jobs[:top_n]:
                bits = [f"{job.score:>3}  {job.title}"]
                if job.company:
                    bits.append(f"— {job.company}")
                out.append(f"{job.icon} {' '.join(bits)}")
                detail = "  ".join(filter(None, [job.location, job.track.replace("_", " ")]))
                if detail:
                    out.append(f"     {detail}")
                if job.url:
                    out.append(f"     {job.url}")
            if len(self.jobs) > top_n:
                out.append(f"…and {len(self.jobs) - top_n} more in the queue")
        if self.error:
            out += ["", f"Error: {self.error}"]
        if self.dashboard_url:
            out += ["", f"Review: {self.dashboard_url}"]
        return "\n".join(out).strip()

    def as_telegram_html(self, top_n: int = 8) -> str:
        """Telegram's HTML subset: b, i, code, a. Everything else is escaped."""
        esc = html.escape
        out = [f"<b>{esc(self.headline)}</b>"]
        if self.lines:
            out.append("")
            out += [f"• {esc(line)}" for line in self.lines]
        if self.jobs:
            out.append("")
            for job in self.jobs[:top_n]:
                title = esc(job.title)
                label = f'<a href="{esc(job.url)}">{title}</a>' if job.url else f"<b>{title}</b>"
                out.append(f"{job.icon} <b>{job.score}</b>  {label}")
                detail = " · ".join(
                    filter(None, [esc(job.company), esc(job.location),
                                  esc(job.track.replace("_", " "))])
                )
                if detail:
                    out.append(f"<i>{detail}</i>")
            if len(self.jobs) > top_n:
                out.append(f"<i>…and {len(self.jobs) - top_n} more in the queue</i>")
        if self.error:
            out += ["", f"<b>Error:</b> <code>{esc(self.error[:400])}</code>"]
        if self.dashboard_url:
            out += ["", f'<a href="{esc(self.dashboard_url)}">Open the review queue →</a>']
        return "\n".join(out)

    def as_html(self, top_n: int = 8) -> str:
        """Email body. Inline styles only — every client strips a <style> block."""
        esc = html.escape
        rows = []
        for job in self.jobs[:top_n]:
            title = esc(job.title)
            link = f'<a href="{esc(job.url)}" style="color:#0b7285;text-decoration:none">{title}</a>' if job.url else title
            detail = esc(" · ".join(filter(None, [job.company, job.location,
                                                  job.track.replace("_", " ")])))
            rows.append(
                f'<tr><td style="padding:8px 10px;border-bottom:1px solid #e9ecef;'
                f'font:600 15px ui-monospace,monospace;color:#212529">{job.score}</td>'
                f'<td style="padding:8px 10px;border-bottom:1px solid #e9ecef">'
                f'<div style="font:600 14px system-ui,sans-serif">{job.icon} {link}</div>'
                f'<div style="font:12px system-ui,sans-serif;color:#868e96">{detail}</div>'
                f"</td></tr>"
            )
        summary = "".join(f"<li>{esc(line)}</li>" for line in self.lines)
        more = (
            f'<p style="font:13px system-ui,sans-serif;color:#868e96">'
            f"…and {len(self.jobs) - top_n} more in the queue.</p>"
            if len(self.jobs) > top_n
            else ""
        )
        cta = (
            f'<p><a href="{esc(self.dashboard_url)}" style="display:inline-block;'
            f'background:#0b7285;color:#fff;padding:9px 16px;border-radius:7px;'
            f'font:600 14px system-ui,sans-serif;text-decoration:none">'
            f"Open the review queue</a></p>"
            if self.dashboard_url
            else ""
        )
        error = (
            f'<p style="font:13px system-ui,sans-serif;color:#c92a2a">{esc(self.error[:500])}</p>'
            if self.error
            else ""
        )
        return (
            f'<div style="max-width:640px;margin:0 auto;font-family:system-ui,sans-serif;color:#212529">'
            f'<h2 style="font-size:17px;margin:0 0 10px">{esc(self.headline)}</h2>'
            f'<ul style="font-size:13px;color:#495057;padding-left:18px">{summary}</ul>'
            f'{error}'
            f'<table style="width:100%;border-collapse:collapse;margin:14px 0">{"".join(rows)}</table>'
            f"{more}{cta}"
            f'<p style="font:11px system-ui,sans-serif;color:#adb5bd;border-top:1px solid #e9ecef;'
            f'padding-top:10px">Nothing has been sent to any employer. Every application '
            f"waits for your approval.</p></div>"
        )

    def as_payload(self, top_n: int = 8) -> dict[str, Any]:
        """Generic webhook body — also what a WhatsApp relay receives."""
        return {
            "kind": self.kind,
            "headline": self.headline,
            "text": self.as_text(top_n),
            "stats": self.stats,
            "error": self.error or None,
            "dashboard_url": self.dashboard_url or None,
            "at": self.at.isoformat(),
            "jobs": [
                {
                    "title": j.title, "company": j.company, "score": j.score,
                    "tier": j.tier, "track": j.track, "location": j.location, "url": j.url,
                }
                for j in self.jobs[:top_n]
            ],
        }


@dataclass
class DeliveryResult:
    channel: str
    ok: bool
    detail: str = ""


class Notifier:
    def __init__(self, settings: Settings | None = None, db: Database | None = None):
        self.settings = settings or get_settings()
        self.db = db

    @property
    def channels(self) -> list[str]:
        return self.settings.notify_channels

    async def send(
        self, digest: Digest, client: httpx.AsyncClient | None = None
    ) -> list[DeliveryResult]:
        if digest.is_empty and not self.settings.notify_on_empty:
            log.info("digest is empty and notify_on_empty is off; sending nothing")
            return []
        if digest.error and not self.settings.notify_on_error:
            return []
        if not self.channels:
            log.info("no notification channel configured; digest not sent")
            return []

        digest.dashboard_url = digest.dashboard_url or self.settings.dashboard_url
        owns = client is None
        client = client or httpx.AsyncClient(timeout=15.0)
        try:
            senders = {
                "telegram": self._telegram, "discord": self._discord,
                "slack": self._slack, "webhook": self._webhook, "email": self._email,
            }
            results = await asyncio.gather(
                *(senders[name](digest, client) for name in self.channels),
                return_exceptions=True,
            )
        finally:
            if owns:
                await client.aclose()

        out: list[DeliveryResult] = []
        for name, result in zip(self.channels, results):
            if isinstance(result, BaseException):
                out.append(DeliveryResult(name, False, f"{type(result).__name__}: {result}"[:200]))
                log.warning("notification via %s failed: %s", name, result)
            else:
                out.append(result)
        return out

    # ── channels ──────────────────────────────────────────────────────────
    async def _telegram(self, digest: Digest, client: httpx.AsyncClient) -> DeliveryResult:
        body = digest.as_telegram_html(self.settings.notify_top_n)
        # Telegram rejects anything over 4096 characters outright.
        if len(body) > 4000:
            body = body[:3900].rsplit("\n", 1)[0] + "\n<i>…truncated</i>"
        resp = await client.post(
            f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage",
            json={
                "chat_id": self.settings.telegram_chat_id,
                "text": body,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
        if resp.status_code >= 400:
            return DeliveryResult("telegram", False, f"{resp.status_code}: {resp.text[:200]}")
        return DeliveryResult("telegram", True)

    async def _discord(self, digest: Digest, client: httpx.AsyncClient) -> DeliveryResult:
        content = digest.as_text(self.settings.notify_top_n)
        resp = await client.post(
            self.settings.discord_webhook_url, json={"content": content[:1990]}
        )
        if resp.status_code >= 400:
            return DeliveryResult("discord", False, f"{resp.status_code}: {resp.text[:200]}")
        return DeliveryResult("discord", True)

    async def _slack(self, digest: Digest, client: httpx.AsyncClient) -> DeliveryResult:
        resp = await client.post(
            self.settings.slack_webhook_url,
            json={"text": digest.as_text(self.settings.notify_top_n)[:3900]},
        )
        if resp.status_code >= 400:
            return DeliveryResult("slack", False, f"{resp.status_code}: {resp.text[:200]}")
        return DeliveryResult("slack", True)

    async def _webhook(self, digest: Digest, client: httpx.AsyncClient) -> DeliveryResult:
        """Generic JSON POST.

        A relay that wants the message in the query string (CallMeBot's free
        WhatsApp endpoint works this way) gets it as ``?text=`` too, so one
        setting covers both shapes.
        """
        payload = digest.as_payload(self.settings.notify_top_n)
        resp = await client.post(
            self.settings.notify_webhook_url,
            json=payload,
            params={"text": payload["text"][:900]},
        )
        if resp.status_code >= 400:
            return DeliveryResult("webhook", False, f"{resp.status_code}: {resp.text[:200]}")
        return DeliveryResult("webhook", True)

    async def _email(self, digest: Digest, client: httpx.AsyncClient) -> DeliveryResult:
        """Digest email.

        Sent directly rather than through Mailer: the §10 cap of 30 exists to
        protect sending reputation with employers, and a note to yourself is
        not an outbound application. It must never eat that allowance.
        """
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {self.settings.resend_api_key}"},
            json={
                "from": self.settings.from_email,
                "to": [self.settings.notify_email],
                "subject": digest.headline[:180],
                "text": digest.as_text(self.settings.notify_top_n),
                "html": digest.as_html(self.settings.notify_top_n),
            },
        )
        if resp.status_code >= 400:
            return DeliveryResult("email", False, f"{resp.status_code}: {resp.text[:200]}")
        return DeliveryResult("email", True)


# ── digest builders ───────────────────────────────────────────────────────
async def build_batch_digest(
    db: Database, stats: dict[str, Any], batch_id: str, settings: Settings | None = None
) -> Digest:
    """Read back what the run actually queued, newest and highest first."""
    settings = settings or get_settings()
    jobs: list[DigestJob] = []
    try:
        rows = await db.select(
            "review_queue",
            eq={"status": "queued", "batch_id": batch_id},
            order="fit_score.desc",
            limit=max(settings.notify_top_n * 3, 30),
        )
        for row in rows:
            jobs.append(
                DigestJob(
                    title=row.get("title") or "Untitled role",
                    company=row.get("company_name") or "",
                    score=int(row.get("fit_score") or 0),
                    tier=row.get("tier") or "",
                    track=row.get("track") or "",
                    location=row.get("location_raw") or "",
                    url=row.get("source_url") or "",
                )
            )
    except Exception as exc:
        log.warning("could not read the queue for the digest: %s", exc)

    built = int(stats.get("packages_built") or 0)
    tiers = stats.get("tiers") or {}
    scout = stats.get("scout") or {}

    if built:
        tier_bits = ", ".join(
            f"{count} {TIER_LABEL.get(tier, tier)}" for tier, count in sorted(tiers.items())
        )
        headline = f"{built} new application{'s' if built != 1 else ''} ready to review"
        if tier_bits:
            headline += f" ({tier_bits})"
    else:
        headline = "Batch finished — nothing cleared the bar this run"

    lines = [
        f"{scout.get('kept', 0)} new postings found, {scout.get('fetched', 0)} seen",
        f"{stats.get('analysed', 0)} analysed · "
        f"{stats.get('killed_by_gatekeeper', 0)} not eligible · "
        f"{stats.get('killed_by_score', 0)} scored too low",
        f"{stats.get('llm_calls', 0)} LLM calls, ${stats.get('llm_cost_usd', 0)}",
    ]
    if stats.get("quota_exhausted"):
        lines.append("LLM budget spent — the rest roll into the next run")
    for err in (stats.get("errors") or [])[:2]:
        lines.append(f"error: {err}")

    return Digest(
        headline=headline,
        kind="batch",
        stats=stats,
        jobs=jobs,
        lines=lines,
        dashboard_url=settings.dashboard_url,
    )


def build_chaser_digest(result: dict[str, Any], settings: Settings | None = None) -> Digest:
    settings = settings or get_settings()
    replies = result.get("replies") or {}
    due = int(result.get("follow_ups_now_due") or 0)
    found = int(replies.get("replies_found") or 0)

    if found:
        headline = f"{found} repl{'ies' if found != 1 else 'y'} landed"
    elif due:
        headline = f"{due} follow-up{'s' if due != 1 else ''} due — approve to send"
    else:
        headline = "Chaser ran — nothing due"

    lines = [
        f"{due} follow-up{'s' if due != 1 else ''} now due (each needs your approval)",
        f"{found} repl{'ies' if found != 1 else 'y'} detected",
        f"{result.get('marked_ghosted', 0)} marked ghosted",
    ]
    for status in replies.get("advanced") or []:
        lines.append(f"application advanced to {status.get('status')}")

    empty = not due and not found and not result.get("marked_ghosted")
    return Digest(
        headline=headline,
        kind="chaser",
        stats=result,
        lines=[] if empty else lines,
        dashboard_url=(settings.dashboard_url + "/outreach") if settings.dashboard_url else "",
    )


def build_error_digest(what: str, error: str, settings: Settings | None = None) -> Digest:
    settings = settings or get_settings()
    return Digest(
        headline=f"{what} failed",
        kind="error",
        error=error,
        dashboard_url=settings.dashboard_url,
    )
