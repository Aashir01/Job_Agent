"""Resume diffs. The dashboard shows the user exactly what the Tailor changed."""
from __future__ import annotations

import difflib
import re
from typing import Any

_NUM_RE = re.compile(r"\d[\d,.]*%?")


def inline_diff(before: str, after: str) -> list[dict[str, str]]:
    """Word-level opcodes, renderable as highlighted spans."""
    a = re.findall(r"\S+\s*", before or "")
    b = re.findall(r"\S+\s*", after or "")
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            ops.append({"op": "equal", "text": "".join(a[i1:i2])})
        elif tag == "delete":
            ops.append({"op": "delete", "text": "".join(a[i1:i2])})
        elif tag == "insert":
            ops.append({"op": "insert", "text": "".join(b[j1:j2])})
        else:
            ops.append({"op": "delete", "text": "".join(a[i1:i2])})
            ops.append({"op": "insert", "text": "".join(b[j1:j2])})
    return ops


def numbers_in(text: str) -> set[str]:
    """Every figure in the text, normalised. Used to prove none were invented."""
    return {n.rstrip(".").replace(",", "") for n in _NUM_RE.findall(text or "")}


def build_resume_diff(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """``packages.resume_diff`` payload.

    Each entry carries the bullet_bank id it came from, so every line on the
    rendered resume is auditable back to a row the user wrote themselves.
    """
    changed = [e for e in entries if e["original"].strip() != e["final"].strip()]
    return {
        "bullet_count": len(entries),
        "changed_count": len(changed),
        "verbatim_count": len(entries) - len(changed),
        "entries": [
            {
                "bullet_id": e["bullet_id"],
                "role_context": e.get("role_context"),
                "original": e["original"],
                "final": e["final"],
                "changed": e["original"].strip() != e["final"].strip(),
                "rejected_rewrite": e.get("rejected_rewrite"),
                "reject_reason": e.get("reject_reason"),
                "similarity": e.get("similarity"),
                "ops": inline_diff(e["original"], e["final"]),
            }
            for e in entries
        ],
    }
