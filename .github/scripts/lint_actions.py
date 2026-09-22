#!/usr/bin/env python3
"""Catch expressions GitHub will reject before a run does.

The failure this exists for: `${{ toJSON(secrets) }}` appeared inside a
composite action's own manifest — in an input *description*, which still gets
evaluated. The `secrets` context does not exist there, so the manifest failed
to load and the check it performed silently never ran. The workflow that called
it looked fine; the step just errored and the job carried on past it.

Run: python .github/scripts/lint_actions.py
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.S)
# Contexts a composite action manifest may reference.
# https://docs.github.com/actions/reference/contexts-reference
COMPOSITE_OK = {
    "inputs", "steps", "github", "runner", "env", "job", "matrix",
    "needs", "strategy", "hashFiles", "always", "success", "failure",
    "cancelled", "toJSON", "fromJSON", "format", "join", "contains",
    "startsWith", "endsWith",
}
# Only the *leading* identifier of a path is the context name: in
# `steps.check.outputs.ready` the context is `steps`, and `check`/`outputs` are
# just keys. But a context can also stand alone — `toJSON(secrets)` passes the
# whole object — so match leading identifiers whether or not a `.` or `(`
# follows, and filter against what composite actions may use.
# `-` is in the lookbehind so a hyphenated key (inputs.secrets-json)
# is not read as a second identifier.
NAMED_VALUE = re.compile(r"(?<![.\w-])([A-Za-z_][A-Za-z0-9_]*)")
STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
LITERALS = {"true", "false", "null"}


def check_composite(path: pathlib.Path) -> list[str]:
    problems = []
    text = path.read_text()
    for match in EXPRESSION.finditer(text):
        # Strip string literals first: their contents are data, not references.
        body = STRING_LITERAL.sub("''", match.group(1))
        line = text[: match.start()].count("\n") + 1
        for name in NAMED_VALUE.findall(body):
            if name not in COMPOSITE_OK and name not in LITERALS:
                problems.append(
                    f"{path.relative_to(ROOT)}:{line}: `{name}` is not available inside a "
                    f"composite action — the manifest will fail to load "
                    f"(expression: {body.strip()[:60]})"
                )
    return problems


def check_callers(action_dirs: set[str]) -> list[str]:
    """Every caller of the preflight action must pass the secrets context,
    since the action itself cannot reach it."""
    problems = []
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        text = path.read_text()
        for action in action_dirs:
            if f"uses: ./{action}" not in text:
                continue
            # The `with:` block for that use must supply secrets-json.
            block = text.split(f"uses: ./{action}", 1)[1][:400]
            if "secrets-json:" not in block:
                problems.append(
                    f"{path.relative_to(ROOT)}: uses {action} without passing secrets-json"
                )
            elif "toJSON(secrets)" not in block:
                problems.append(
                    f"{path.relative_to(ROOT)}: secrets-json must be the whole context "
                    f"(toJSON(secrets)), not a single secret"
                )
    return problems


def main() -> int:
    problems: list[str] = []
    action_dirs: set[str] = set()
    for manifest in sorted((ROOT / ".github/actions").rglob("action.yml")):
        action_dirs.add(str(manifest.parent.relative_to(ROOT)))
        problems += check_composite(manifest)
    problems += check_callers(action_dirs)

    if problems:
        print("Action expression problems:\n")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"ok — {len(action_dirs)} composite action(s) and their callers check out")
    return 0


if __name__ == "__main__":
    sys.exit(main())
