"""Run the pipeline without an HTTP server.

The scheduled workflows used to POST to a deployed API, which meant the cron
could not run at all until something was hosted — and every scheduled run
failed in six seconds on a missing ``API_URL``. GitHub Actions already has the
compute the batch needs, so it runs the same code in-process against Supabase
and nothing has to be deployed for the schedule to work.

    python -m app.cli batch --kind scheduled
    python -m app.cli chaser
    python -m app.cli registers
    python -m app.cli notify-test
    python -m app.cli doctor

Every command writes a GitHub step summary when GITHUB_STEP_SUMMARY is set, so
a run explains itself in the Actions UI without opening logs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any

from .config import get_settings
from .db import Database
from .notify import Notifier, build_chaser_digest, build_error_digest

log = logging.getLogger("job_agent.cli")


def summary(markdown: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(markdown.rstrip() + "\n\n")
    except OSError as exc:
        log.warning("could not write the step summary: %s", exc)


def _table(pairs: list[tuple[str, Any]]) -> str:
    rows = "\n".join(f"| {key} | {value} |" for key, value in pairs)
    return f"| | |\n|---|---|\n{rows}"


def require_config() -> None:
    settings = get_settings()
    missing = []
    if not settings.supabase_url:
        missing.append("SUPABASE_URL")
    if not settings.supabase_service_key:
        missing.append("SUPABASE_SERVICE_KEY")
    if missing:
        names = ", ".join(missing)
        summary(
            f"### Configuration missing\n\n"
            f"`{names}` {'is' if len(missing) == 1 else 'are'} not set.\n\n"
            "Add them under **Settings → Secrets and variables → Actions** in this "
            "repository. See `docs/DEPLOY.md`."
        )
        print(f"error: {names} must be set", file=sys.stderr)
        raise SystemExit(2)


# ── commands ──────────────────────────────────────────────────────────────
async def cmd_batch(args: argparse.Namespace) -> int:
    require_config()
    from .batch import BatchRunner

    settings = get_settings()
    db = Database(settings)
    try:
        runner = BatchRunner(db, settings)
        stats = await runner.run(kind=args.kind, skip_scout=args.skip_scout)
        data = stats.as_dict()
        scout = data.get("scout") or {}

        summary(
            f"### Batch — {data.get('packages_built', 0)} package(s) built\n\n"
            + _table([
                ("batch id", f"`{stats.batch_id}`"),
                ("postings seen", scout.get("fetched", 0)),
                ("new postings kept", scout.get("kept", 0)),
                ("analysed", data.get("analysed", 0)),
                ("killed — not eligible", data.get("killed_by_gatekeeper", 0)),
                ("killed — scored too low", data.get("killed_by_score", 0)),
                ("**packages built**", f"**{data.get('packages_built', 0)}**"),
                ("tiers", f"`{data.get('tiers', {})}`"),
                ("LLM calls", f"{data.get('llm_calls', 0)} (${data.get('llm_cost_usd', 0)})"),
                ("digest sent to", ", ".join(k for k, v in (data.get("notifications") or {}).items() if v) or "—"),
            ])
        )
        if data.get("quota_exhausted"):
            summary("> The LLM budget was spent. Remaining jobs roll into the next run.")
        for err in (data.get("errors") or [])[:5]:
            summary(f"> error: `{err}`")

        print(json.dumps({"batch_id": stats.batch_id, "stats": data}, indent=2, default=str))
        # A run that built nothing is not a failure: the Gatekeeper doing its
        # job looks identical to a quiet day, and neither should page anyone.
        return 1 if data.get("errors") and not data.get("packages_built") else 0
    finally:
        await db.aclose()


async def cmd_chaser(args: argparse.Namespace) -> int:
    require_config()
    from .agents.chaser import Chaser
    from .llm.router import LLMRouter

    settings = get_settings()
    db = Database(settings)
    try:
        chaser = Chaser(db, LLMRouter(settings, db), settings)
        queued = await chaser.queue_due_follow_ups()
        replies = await chaser.poll_replies()
        ghosted = await chaser.mark_ghosted(settings.ghost_after_days)
        result = {
            "follow_ups_now_due": queued,
            "replies": replies.as_dict(),
            "marked_ghosted": ghosted,
        }

        summary(
            "### Chaser\n\n"
            + _table([
                ("follow-ups now due", f"**{queued}** (each still needs your approval)"),
                ("replies found", replies.replies_found),
                ("marked ghosted", ghosted),
            ])
        )
        for err in replies.errors[:3]:
            summary(f"> {err}")

        digest = build_chaser_digest(result, settings)
        delivered = await Notifier(settings, db).send(digest)
        result["notifications"] = {r.channel: r.ok for r in delivered}
        print(json.dumps(result, indent=2, default=str))
        return 0
    finally:
        await db.aclose()


async def cmd_registers(args: argparse.Namespace) -> int:
    require_config()
    from .registers.refresh import refresh_all

    settings = get_settings()
    db = Database(settings)
    try:
        results = await refresh_all(db, settings)
        rows = [
            (country, f"{'ok' if out['ok'] else '**failed**'} — {out.get('rows', 0)} rows "
                      f"{out.get('error') or ''}")
            for country, out in results.items()
        ]
        summary("### Sponsorship registers\n\n" + _table(rows))
        print(json.dumps(results, indent=2, default=str))
        # A stale register still kills correctly; only report, never fail the run.
        return 0
    finally:
        await db.aclose()


async def cmd_notify_test(args: argparse.Namespace) -> int:
    from .notify import Digest, DigestJob

    settings = get_settings()
    notifier = Notifier(settings)
    if not notifier.channels:
        print(
            "No notification channel is configured. Set at least one of:\n"
            "  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID\n"
            "  DISCORD_WEBHOOK_URL\n"
            "  SLACK_WEBHOOK_URL\n"
            "  NOTIFY_WEBHOOK_URL\n"
            "  NOTIFY_EMAIL + RESEND_API_KEY + FROM_EMAIL",
            file=sys.stderr,
        )
        return 2

    digest = Digest(
        headline="Test digest — job-agent is wired up",
        lines=[
            "This is what a batch result will look like.",
            f"Channels configured: {', '.join(notifier.channels)}.",
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
    for result in results:
        print(f"  {result.channel:9} {'ok' if result.ok else 'FAILED  ' + result.detail}")
    return 0 if all(r.ok for r in results) else 1


async def cmd_doctor(args: argparse.Namespace) -> int:
    """Say exactly what is and is not configured, and whether the database answers."""
    settings = get_settings()
    checks: list[tuple[str, bool, str]] = [
        ("Supabase URL", bool(settings.supabase_url), settings.supabase_url or "unset"),
        ("Supabase service key", bool(settings.supabase_service_key),
         "set" if settings.supabase_service_key else "unset"),
        ("LLM provider", settings.llm_configured,
         ", ".join(n for n, v in (("openrouter", settings.openrouter_api_key),
                                  ("gemini", settings.gemini_api_key),
                                  ("groq", settings.groq_api_key)) if v) or "none"),
        ("Agent key (API auth)", bool(settings.agent_key),
         "set" if settings.agent_key else "unset — the HTTP API will refuse machine routes"),
        ("Notifications", bool(settings.notify_channels),
         ", ".join(settings.notify_channels) or "none configured"),
        ("Dashboard URL", bool(settings.dashboard_url), settings.dashboard_url or "unset"),
        ("Embeddings", True, settings.embedding_provider),
    ]

    if settings.configured:
        db = Database(settings)
        try:
            rows = await db.select("profile", columns="id,full_name", limit=1)
            checks.append(("Database reachable", True,
                           f"profile: {rows[0].get('full_name') if rows else 'no row yet'}"))
            for table in ("bullet_bank", "source_seeds", "jobs", "packages"):
                try:
                    found = await db.select(table, columns="id", limit=1000)
                    checks.append((f"  {table}", bool(found), f"{len(found)} row(s)"))
                except Exception as exc:
                    checks.append((f"  {table}", False, str(exc)[:120]))
        except Exception as exc:
            checks.append(("Database reachable", False, str(exc)[:200]))
        finally:
            await db.aclose()

    width = max(len(name) for name, _, _ in checks)
    for name, ok, detail in checks:
        print(f"  {'ok  ' if ok else 'MISS'}  {name.ljust(width)}  {detail}")

    summary(
        "### Configuration\n\n"
        + _table([(name, f"{'✅' if ok else '❌'} {detail}") for name, ok, detail in checks])
    )
    required = [name for name, ok, _ in checks[:3] if not ok]
    return 1 if required else 0


COMMANDS = {
    "batch": cmd_batch,
    "chaser": cmd_chaser,
    "registers": cmd_registers,
    "notify-test": cmd_notify_test,
    "doctor": cmd_doctor,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    sub = parser.add_subparsers(dest="command", required=True)

    batch = sub.add_parser("batch", help="discover, analyse and build packages")
    batch.add_argument("--kind", default="scheduled",
                       choices=["scheduled", "manual", "backfill"])
    batch.add_argument("--skip-scout", action="store_true",
                       help="process stored jobs only; poll no sources")

    sub.add_parser("chaser", help="queue due follow-ups and detect replies")
    sub.add_parser("registers", help="refresh the UK, NL and CA sponsor registers")
    sub.add_parser("notify-test", help="send a sample digest to every configured channel")
    sub.add_parser("doctor", help="report what is configured and reachable")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    try:
        return asyncio.run(COMMANDS[args.command](args))
    except KeyboardInterrupt:
        return 130
    except SystemExit:
        raise
    except Exception as exc:
        log.exception("%s failed", args.command)
        summary(f"### {args.command} failed\n\n```\n{exc}\n```")
        settings = get_settings()
        if settings.notify_channels and settings.notify_on_error:
            try:
                asyncio.run(
                    Notifier(settings).send(
                        build_error_digest(args.command.title(), str(exc)[:500], settings)
                    )
                )
            except Exception:
                log.warning("could not deliver the failure notification")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
