#!/usr/bin/env python3
"""Bootstrap bullets.json from an existing .docx resume (§9 Sprint 2).

    python db/seeds/bootstrap_bullets.py ~/resume.docx > db/seeds/bullets.json

It extracts every bullet-shaped paragraph, guesses the role heading each one
sits under, and pulls out any figure it contains. It deliberately stops there:
``strength`` comes out as null, and the loader will not accept a bullet the
user has not rated. The bank is the verified source of truth, so nothing
reaches it without the user having looked at it.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

METRIC_RE = re.compile(r"\d[\d,.]*\s*(?:%|x\b|k\b|m\b|hrs?\b|ms\b|s\b)?", re.I)
BULLET_RE = re.compile(r"^\s*[•●▪\-\*–]\s*")
HEADING_WORDS = re.compile(
    r"(engineer|developer|scientist|analyst|intern|consultant|founder|lead|manager)", re.I
)


def looks_like_bullet(paragraph) -> bool:
    style = (paragraph.style.name or "").lower()
    return "list" in style or bool(BULLET_RE.match(paragraph.text))


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2

    try:
        from docx import Document
    except ImportError:
        print("pip install python-docx", file=sys.stderr)
        return 1

    path = pathlib.Path(sys.argv[1]).expanduser()
    if not path.exists():
        print(f"no such file: {path}", file=sys.stderr)
        return 1

    document = Document(str(path))
    role_context = "Experience"
    bullets = []

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue

        if looks_like_bullet(paragraph):
            clean = BULLET_RE.sub("", text).strip()
            if len(clean) < 25:
                continue
            metrics = [m.strip() for m in METRIC_RE.findall(clean) if any(c.isdigit() for c in m)]
            bullets.append(
                {
                    "role_context": role_context,
                    "text": clean,
                    "metric": metrics[0] if metrics else None,
                    "tags": [],
                    "strength": None,
                }
            )
        elif HEADING_WORDS.search(text) and len(text) < 120:
            role_context = text

    print(
        json.dumps(
            {
                "_comment": [
                    f"Extracted from {path.name}. Nothing here is loadable yet:",
                    "set `strength` (1-5) on every bullet you want used, add tags,",
                    "and fix any wording the extractor mangled. Bullets left at",
                    "null strength are rejected by load.py — the bank is the",
                    "verified source of truth and you are the one verifying it.",
                ],
                "bullets": bullets,
            },
            indent=2,
        )
    )
    print(f"extracted {len(bullets)} bullets — rate each one before loading", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
