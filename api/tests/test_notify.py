"""The digest is how the system reaches you when the dashboard is closed."""
from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.notify import (
    Digest,
    DigestJob,
    Notifier,
    build_batch_digest,
    build_chaser_digest,
    build_error_digest,
)


def _settings(**kw) -> Settings:
    return Settings(supabase_url="https://x.supabase.co", supabase_service_key="k", **kw)


def _digest(**kw) -> Digest:
    base = dict(
        headline="2 new applications ready to review",
        lines=["40 new postings found"],
        jobs=[
            DigestJob("Senior AI Engineer", "Acme", 91, "fast_lane", "remote_fte",
                      "Remote", "https://e.com/1"),
            DigestJob("ML Engineer", "Beta", 74, "standard", "remote_fte", "EU",
                      "https://e.com/2"),
        ],
    )
    return Digest(**{**base, **kw})


# ── channel detection ─────────────────────────────────────────────────────
def test_no_channels_when_nothing_is_configured():
    assert _settings().notify_channels == []


def test_telegram_needs_both_halves():
    assert _settings(telegram_bot_token="t").notify_channels == []
    assert _settings(telegram_chat_id="c").notify_channels == []
    assert _settings(telegram_bot_token="t", telegram_chat_id="c").notify_channels == ["telegram"]


def test_email_needs_a_sender_as_well_as_a_recipient():
    assert _settings(notify_email="me@x.com").notify_channels == []
    assert _settings(
        notify_email="me@x.com", resend_api_key="r", from_email="bot@x.com"
    ).notify_channels == ["email"]


# ── rendering ─────────────────────────────────────────────────────────────
def test_telegram_html_escapes_everything_from_a_posting():
    """Job titles come from third-party boards. Telegram rejects the whole
    message on a malformed tag, so an unescaped '<' silently loses the digest."""
    digest = _digest(jobs=[DigestJob("C++ & <script>alert(1)</script>", "A & B", 80,
                                     "standard", "", "", "https://e.com/x?a=1&b=2")])
    body = digest.as_telegram_html()
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "C++ &amp; " in body
    assert "a=1&amp;b=2" in body


def test_html_email_escapes_too():
    body = _digest(jobs=[DigestJob("<b>x</b>", "A&B", 70, "standard")]).as_html()
    assert "&lt;b&gt;x&lt;/b&gt;" in body
    assert "A&amp;B" in body


def test_text_digest_lists_scores_companies_and_links():
    text = _digest().as_text()
    assert "91" in text and "Senior AI Engineer" in text and "Acme" in text
    assert "https://e.com/1" in text


def test_digest_truncation_is_announced_not_silent():
    digest = _digest(jobs=[DigestJob(f"Role number {i}", "Co", 70, "standard")
                           for i in range(50)])
    text = digest.as_text(top_n=5)
    assert "Role number 4" in text
    assert "Role number 40" not in text
    assert "45 more" in text


def test_payload_carries_structured_jobs_for_a_relay():
    payload = _digest().as_payload()
    assert payload["kind"] == "batch"
    assert [j["score"] for j in payload["jobs"]] == [91, 74]
    assert payload["text"]


# ── delivery ──────────────────────────────────────────────────────────────
async def test_an_empty_digest_is_not_sent_by_default():
    """Two 'nothing found' messages a day trains you to ignore the real ones."""
    sent = []
    transport = httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200, json={}))
    notifier = Notifier(_settings(telegram_bot_token="t", telegram_chat_id="c"))
    async with httpx.AsyncClient(transport=transport) as client:
        results = await notifier.send(Digest(headline="nothing"), client)
    assert results == []
    assert not sent


async def test_an_empty_digest_is_sent_when_asked_for():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}))
    notifier = Notifier(
        _settings(telegram_bot_token="t", telegram_chat_id="c", notify_on_empty=True)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        results = await notifier.send(Digest(headline="nothing"), client)
    assert [r.ok for r in results] == [True]


async def test_one_failing_channel_does_not_stop_the_others():
    def handler(request: httpx.Request) -> httpx.Response:
        if "telegram" in str(request.url):
            return httpx.Response(429, text="Too Many Requests")
        return httpx.Response(204)

    notifier = Notifier(
        _settings(telegram_bot_token="t", telegram_chat_id="c",
                  discord_webhook_url="https://discord.example/hook")
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await notifier.send(_digest(), client)
    by_channel = {r.channel: r for r in results}
    assert by_channel["telegram"].ok is False
    assert "429" in by_channel["telegram"].detail
    assert by_channel["discord"].ok is True


async def test_a_transport_error_is_reported_not_raised():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    notifier = Notifier(_settings(discord_webhook_url="https://discord.example/hook"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await notifier.send(_digest(), client)
    assert results[0].ok is False
    assert "ConnectError" in results[0].detail


async def test_telegram_message_is_capped_below_the_api_limit():
    """Telegram rejects anything over 4096 characters outright."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    digest = _digest(jobs=[DigestJob("A very long role title " * 12, "Company", 80,
                                     "standard", "remote_fte", "Remote")
                           for _ in range(60)])
    notifier = Notifier(
        _settings(telegram_bot_token="t", telegram_chat_id="c", notify_top_n=60)
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await notifier.send(digest, client)
    import json

    body = json.loads(captured[0].content)
    assert len(body["text"]) <= 4096
    assert "truncated" in body["text"]


async def test_the_digest_email_does_not_spend_the_outbound_application_cap(db):
    """§10's cap of 30 protects deliverability with employers. A note to
    yourself must never eat that allowance."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"id": "e1"})

    notifier = Notifier(
        _settings(notify_email="me@x.com", resend_api_key="r", from_email="bot@x.com"), db
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await notifier.send(_digest(), client)
    assert results[0].ok
    assert not [c for c, _ in db.rpc_calls if c == "bump_daily_counter"]


# ── builders ──────────────────────────────────────────────────────────────
async def test_batch_digest_reads_back_what_the_run_queued(db):
    db.tables["review_queue"] = [
        {"id": "p1", "status": "queued", "batch_id": "b1", "fit_score": 91,
         "tier": "fast_lane", "title": "Senior AI Engineer", "company_name": "Acme",
         "track": "remote_fte", "location_raw": "Remote", "source_url": "https://e.com/1"},
        {"id": "p2", "status": "queued", "batch_id": "b1", "fit_score": 72,
         "tier": "standard", "title": "ML Engineer", "company_name": "Beta"},
    ]
    stats = {"packages_built": 2, "tiers": {"fast_lane": 1, "standard": 1},
             "scout": {"kept": 40, "fetched": 900}, "analysed": 38,
             "killed_by_gatekeeper": 20, "killed_by_score": 16, "llm_calls": 45}
    digest = await build_batch_digest(db, stats, "b1", _settings(dashboard_url="https://d.example"))

    assert "2 new applications" in digest.headline
    assert "fast lane" in digest.headline
    assert [j.score for j in digest.jobs] == [91, 72]
    assert digest.dashboard_url == "https://d.example"
    assert any("40 new postings" in line for line in digest.lines)


async def test_batch_digest_says_so_plainly_when_nothing_cleared_the_bar(db):
    digest = await build_batch_digest(
        db, {"packages_built": 0, "scout": {"kept": 300}, "killed_by_gatekeeper": 300}, "b1"
    )
    assert "nothing cleared the bar" in digest.headline


async def test_a_digest_survives_an_unreadable_queue(db):
    """A read failure must not lose the run's summary."""

    async def boom(*a, **k):
        raise RuntimeError("PostgREST is down")

    db.select = boom  # type: ignore[method-assign]
    digest = await build_batch_digest(db, {"packages_built": 3}, "b1")
    assert "3 new applications" in digest.headline
    assert digest.jobs == []


def test_chaser_digest_is_quiet_when_nothing_happened():
    digest = build_chaser_digest({"follow_ups_now_due": 0, "replies": {"replies_found": 0},
                                  "marked_ghosted": 0})
    assert digest.is_empty


def test_chaser_digest_leads_with_replies_over_follow_ups():
    digest = build_chaser_digest({"follow_ups_now_due": 5,
                                  "replies": {"replies_found": 2}, "marked_ghosted": 0})
    assert "2 replies landed" in digest.headline


def test_error_digest_is_never_suppressed_as_empty():
    digest = build_error_digest("Batch", "Supabase refused the connection")
    assert not digest.is_empty
    assert "Supabase refused" in digest.as_text()


def test_jobs_get_a_deep_link_into_the_queue():
    """Tapping a job on a phone should land on that package, not on a list."""
    digest = Digest(
        headline="1 ready",
        jobs=[DigestJob("Senior AI Engineer", "Acme", 91, "fast_lane", package_id="pkg-1")],
        dashboard_url="https://dash.example",
    )
    digest._link_jobs()
    assert digest.jobs[0].review_url == "https://dash.example/?package=pkg-1"
    assert "?package=pkg-1" in digest.as_telegram_html()
    assert digest.as_payload()["jobs"][0]["review_url"].endswith("?package=pkg-1")


def test_no_deep_link_without_a_dashboard_url():
    digest = Digest(headline="1 ready",
                    jobs=[DigestJob("Role", "Co", 80, "standard", package_id="pkg-1")])
    digest._link_jobs()
    assert digest.jobs[0].review_url == ""
    assert "?package=" not in digest.as_text()


async def test_the_batch_digest_carries_the_package_id(db):
    db.tables["review_queue"] = [
        {"id": "pkg-9", "status": "queued", "batch_id": "b1", "fit_score": 88,
         "tier": "fast_lane", "title": "AI Engineer", "company_name": "Acme"}
    ]
    digest = await build_batch_digest(
        db, {"packages_built": 1}, "b1", _settings(dashboard_url="https://d.example")
    )
    assert digest.jobs[0].package_id == "pkg-9"
