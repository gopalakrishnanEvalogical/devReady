"""`devready doctor`: diagnosis, explanation and suggested fix in one report.

Reuses the check results, `EXPLANATIONS` and `Result.suggestion` (the same text `fix --plan`
prints). Adds no checks and never runs anything it suggests.
"""

from __future__ import annotations

import textwrap
from collections import Counter

from devready.explain import EXPLANATIONS
from devready.models import Result, Status

_LABEL = {Status.FAIL: "x FAIL", Status.WARN: "! WARN"}
_INDENT = 8


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' * (n != 1)}"


def _line(label: str, text: str, width: int) -> list[str]:
    pad = " " * _INDENT
    return textwrap.wrap(
        f"{label} {text}",
        width,
        initial_indent=pad,
        subsequent_indent=pad + " " * (len(label) + 1),
        break_on_hyphens=False,
    )


def doctor_report(results: list[Result], width: int = 80) -> str:
    """Plain-text report: each fail/warn with what it means and what to try."""
    n = Counter(r.status for r in results)
    lines = ["DevReady Doctor", ""]
    problems = [r for r in results if r.status in (Status.FAIL, Status.WARN)]
    for r in sorted(problems, key=lambda r: r.status is not Status.FAIL):  # failures first
        lines.append(f"{_LABEL[r.status]}  {r.check_id}   {r.summary}")
        meaning = EXPLANATIONS.get(r.check_id)
        if meaning:
            lines += _line("Means:", meaning, width)
        if r.suggestion:
            lines += _line("Fix:  ", r.suggestion, width)
        if r.docs_url:
            lines.append(f"{' ' * _INDENT}Docs:  {r.docs_url}")
        lines.append("")
    if not problems:
        lines += ["No problems found.", ""]
    tally = [
        f"{n[Status.PASS]} passed",
        _plural(n[Status.WARN], "warning"),
        _plural(n[Status.FAIL], "failure"),
    ]
    unknown = n[Status.SKIP] + n[Status.ERROR]
    if unknown:
        tally.append(f"{unknown} not evaluated")
    lines.append(", ".join(tally) + ".")
    lines.append("DevReady did not run any of these. Nothing was changed.")
    return "\n".join(lines)
