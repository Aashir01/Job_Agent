#!/usr/bin/env python3
"""Load seed data into Supabase.

    python db/seeds/load.py --all
    python db/seeds/load.py --profile db/seeds/profile.json
    python db/seeds/load.py --bullets db/seeds/bullets.json
    python db/seeds/load.py --boards

Bullets are embedded on the way in — match_bullets() returns nothing for a row
with a null embedding, so an unembedded bullet bank silently produces empty
resumes rather than an error.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "api"))

from app.config import get_settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.embeddings import Embedder  # noqa: E402


async def load_profile(db: Database, path: pathlib.Path) -> None:
    data = json.loads(path.read_text())
    data.pop("_comment", None)
    existing = await db.select_one("profile", limit=1)
    if existing:
        # PostgREST rejects the whole row when it carries a column the table does
        # not define (PGRST204), so one extra seed key keeps the real profile out
        # entirely — and the example row stays behind, which looks like the
        # loader was never run. Drop what the table cannot hold, and say so.
        unknown = sorted(set(data) - set(existing))
        if unknown:
            print(f"  ignoring field(s) absent from the profile table: {', '.join(unknown)}")
            data = {k: v for k, v in data.items() if k in existing}
        await db.update("profile", data, eq={"id": existing["id"]}, returning=False)
        print(f"  profile updated: {data.get('full_name')}")
    else:
        await db.insert("profile", data, returning=False)
        print(f"  profile created: {data.get('full_name')}")


async def load_bullets(db: Database, path: pathlib.Path, replace: bool = False) -> None:
    payload = json.loads(path.read_text())
    bullets = payload["bullets"] if isinstance(payload, dict) else payload
    embedder = Embedder(get_settings())

    if replace:
        existing = await db.select("bullet_bank", columns="id", limit=1000)
        for row in existing:
            await db.delete("bullet_bank", eq={"id": row["id"]})
        print(f"  removed {len(existing)} existing bullets")

    rows = []
    unrated = []
    for bullet in bullets:
        text = (bullet.get("text") or "").strip()
        if not text:
            continue
        # An unrated bullet has not been through the user's eyes yet, and the
        # bank is the verified source of truth. Refuse it rather than guess a
        # strength — a wrong 3 quietly puts unreviewed wording on a resume.
        strength = bullet.get("strength")
        if strength is None:
            unrated.append(text[:70])
            continue
        tags = bullet.get("tags") or []
        rows.append(
            {
                "role_context": bullet.get("role_context"),
                "text": text,
                "metric": bullet.get("metric"),
                "tags": tags,
                "strength": max(1, min(5, int(strength))),
                # Embed the tags alongside the text: they carry the vocabulary
                # a JD will actually match on.
                "embedding": await embedder.embed(f"{text}\n{' '.join(tags)}"),
            }
        )
    if unrated:
        print(f"  skipped {len(unrated)} unrated bullets — set strength 1-5 on each:")
        for text in unrated[:5]:
            print(f"    · {text}…")
        if len(unrated) > 5:
            print(f"    · …and {len(unrated) - 5} more")
    if rows:
        await db.insert("bullet_bank", rows, returning=False)
    print(f"  loaded {len(rows)} bullets")


async def load_boards(db: Database, path: pathlib.Path) -> None:
    payload = json.loads(path.read_text())
    boards = payload["boards"] if isinstance(payload, dict) else payload
    rows = [
        {"kind": b["kind"], "slug": b["slug"], "company_name": b.get("company_name"), "enabled": True}
        for b in boards
    ]
    await db.insert(
        "source_seeds", rows, upsert=True, on_conflict="kind,slug",
        ignore_duplicates=True, returning=False,
    )
    print(f"  loaded {len(rows)} company boards")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--profile", type=pathlib.Path)
    parser.add_argument("--bullets", type=pathlib.Path)
    parser.add_argument("--boards", action="store_true")
    parser.add_argument("--replace-bullets", action="store_true",
                        help="clear the bank first instead of appending")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.configured:
        print("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set", file=sys.stderr)
        return 1

    db = Database(settings)
    try:
        if args.profile or args.all:
            path = args.profile or HERE / "profile.json"
            if not path.exists():
                path = HERE / "profile.example.json"
                print(f"  (no profile.json — using {path.name})")
            await load_profile(db, path)

        if args.bullets or args.all:
            path = args.bullets or HERE / "bullets.json"
            if not path.exists():
                path = HERE / "bullets.example.json"
                print(f"  (no bullets.json — using {path.name})")
            await load_bullets(db, path, replace=args.replace_bullets)

        if args.boards or args.all:
            await load_boards(db, HERE / "company_boards.json")
    finally:
        await db.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
