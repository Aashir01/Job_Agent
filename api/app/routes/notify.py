"""Notification status and a test send.

Configuration itself lives in the environment, not the database: these are
credentials, and a dashboard that could rewrite them would be a way to
redirect the digest. The dashboard can see what is wired up and fire a test,
nothing more.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import get_settings
from ..db import Database, get_db
from ..notify import Digest, DigestJob, Notifier, build_batch_digest
from ..security import require_agent_key

router = APIRouter(prefix="/notify", tags=["notify"], dependencies=[Depends(require_agent_key)])

# What to set for each channel, shown in the dashboard so nobody has to grep
# the README to find out why nothing arrives.
CHANNEL_SETUP = {
    "telegram": {
        "label": "Telegram",
        "env": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
        "how": "Message @BotFather for a bot token, then @userinfobot for your chat id. "
               "Send your bot any message first — it cannot start a conversation with you.",
    },
    "discord": {
        "label": "Discord",
        "env": ["DISCORD_WEBHOOK_URL"],
        "how": "Server settings → Integrations → Webhooks → New webhook → Copy URL.",
    },
    "slack": {
        "label": "Slack",
        "env": ["SLACK_WEBHOOK_URL"],
        "how": "api.slack.com/apps → your app → Incoming Webhooks → Add New Webhook.",
    },
    "webhook": {
        "label": "Webhook (incl. WhatsApp relays)",
        "env": ["NOTIFY_WEBHOOK_URL"],
        "how": "Any URL that accepts a JSON POST. WhatsApp has no free first-party API, "
               "so reach it through a relay such as CallMeBot — the digest text is also "
               "sent as a ?text= query parameter for relays that expect one.",
    },
    "email": {
        "label": "Email",
        "env": ["NOTIFY_EMAIL", "RESEND_API_KEY", "FROM_EMAIL"],
        "how": "A Resend account and a verified sender domain. The digest never spends "
               "the daily outbound-application allowance.",
    },
}


@router.get("/status")
async def status() -> dict:
    settings = get_settings()
    active = set(settings.notify_channels)
    return {
        "configured": sorted(active),
        "any": bool(active),
        "dashboard_url": settings.dashboard_url or None,
        "notify_on_empty": settings.notify_on_empty,
        "notify_top_n": settings.notify_top_n,
        "channels": [
            {
                "id": key,
                "active": key in active,
                "label": meta["label"],
                "env": meta["env"],
                "how": meta["how"],
                # Say which half is missing, rather than only "not configured".
                "missing": [
                    name for name in meta["env"]
                    if not getattr(settings, name.lower(), "")
                ],
            }
            for key, meta in CHANNEL_SETUP.items()
        ],
    }


@router.post("/test")
async def send_test() -> dict:
    settings = get_settings()
    notifier = Notifier(settings)
    if not notifier.channels:
        return {
            "sent": False,
            "reason": "no channel is configured",
            "results": [],
        }
    digest = Digest(
        headline="Test digest — job-agent is wired up",
        lines=[
            "This is what a batch result will look like.",
            f"Channels: {', '.join(notifier.channels)}.",
        ],
        jobs=[
            DigestJob("Senior AI Engineer", "Example Corp", 91, "fast_lane",
                      "remote_fte", "Remote — Worldwide", "https://example.com/jobs/1"),
            DigestJob("ML Platform Engineer", "Another Co", 76, "standard",
                      "remote_fte", "Remote — EMEA", "https://example.com/jobs/2"),
        ],
        dashboard_url=settings.dashboard_url,
    )
    results = await notifier.send(digest)
    return {
        "sent": any(r.ok for r in results),
        "results": [{"channel": r.channel, "ok": r.ok, "detail": r.detail} for r in results],
    }


@router.post("/resend/{batch_id}")
async def resend_batch(batch_id: str, db: Database = Depends(get_db)) -> dict:
    """Re-push a past batch's digest — useful when a channel was added later."""
    settings = get_settings()
    batch = await db.select_one("batches", eq={"id": batch_id})
    stats = (batch or {}).get("stats") or {}
    digest = await build_batch_digest(db, stats, batch_id, settings)
    results = await Notifier(settings, db).send(digest)
    return {
        "sent": any(r.ok for r in results),
        "results": [{"channel": r.channel, "ok": r.ok, "detail": r.detail} for r in results],
    }
