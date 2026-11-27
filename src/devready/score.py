"""`devready score`: a 0-100 readiness number derived from a check run.

Formula (public, deliberately simple): every evaluated check counts equally; pass = 1, warn = 0.5,
fail = 0. `skip` and `error` mean "not evaluated": they are left out of the score and reported
separately, never counted as passing. score = round-half-up(100 * points / evaluated), and `n/a`
when nothing was evaluated (never 100). This is derived data and not part of the frozen `check`
report; see docs/schema-score.json.
"""

from __future__ import annotations

from collections import Counter

from devready.models import Result, Status


def compute(results: list[Result]) -> dict:
    n = Counter(r.status for r in results)
    evaluated = n[Status.PASS] + n[Status.WARN] + n[Status.FAIL]
    doubled = 2 * n[Status.PASS] + n[Status.WARN]  # points * 2, so the maths stays in integers
    # round half up, exactly: floor(100 * points / evaluated + 1/2)
    score = (100 * doubled + evaluated) // (2 * evaluated) if evaluated else None
    return {
        "schema_version": 1,
        "score": score,
        "evaluated": evaluated,
        "not_evaluated": n[Status.SKIP] + n[Status.ERROR],
        "counts": {s.value: n[s] for s in Status},
    }


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' * (n != 1)}"


def text(data: dict) -> str:
    c = data["counts"]
    head = (
        f"DevReady score: {data['score']} / 100"
        if data["score"] is not None
        else "DevReady score: n/a (nothing was evaluated)"
    )
    detail = (
        f"{_plural(c['warn'], 'warning')}, {_plural(c['fail'], 'failure')}, "
        f"{data['not_evaluated']} not evaluated."
    )
    return f"{head}\n{detail} Run `devready check` for details."


def _color(score: int | None) -> str:
    if score is None:
        return "#9f9f9f"
    for floor, color in ((90, "#4c1"), (70, "#dfb317"), (50, "#fe7d37")):
        if score >= floor:
            return color
    return "#e05d44"


def badge(score: int | None) -> str:
    """A static SVG badge. Fixed template; the only variable parts are a number and a colour."""
    value = "n/a" if score is None else f"{int(score)}%"
    vw = 10 + 7 * len(value)
    total = 62 + vw
    label = f"devready score: {value}"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" role="img" '
        f'aria-label="{label}"><title>{label}</title>'
        f'<rect width="62" height="20" fill="#555"/>'
        f'<rect x="62" width="{vw}" height="20" fill="{_color(score)}"/>'
        f'<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11" '
        f'text-anchor="middle"><text x="31" y="14">devready</text>'
        f'<text x="{62 + vw // 2}" y="14">{value}</text></g></svg>'
    )
