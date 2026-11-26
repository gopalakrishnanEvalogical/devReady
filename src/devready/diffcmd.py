"""`devready diff REFERENCE ACTUAL`: what differs between two saved `check --format json` reports.

Report files are untrusted input: only check ids (validated), statuses and fixed words are
printed, never summary text. Reads two files; runs no checks and changes nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

from devready.baseline import _RANK, load_report
from devready.models import Status

_NOT_EVALUATED = (Status.SKIP, Status.ERROR)
_UNSAFE = re.compile(r"[^A-Za-z0-9._/@+-]")


def _classify(ref: tuple[Status, str] | None, act: tuple[Status, str] | None) -> str | None:
    """The change label for one check id, or None when nothing differs."""
    if ref is None:
        return "new"
    if act is None:
        return "missing"
    (rs, rtext), (as_, atext) = ref, act
    if rs is as_:
        return "details differ" if rtext != atext else None
    r_eval, a_eval = rs not in _NOT_EVALUATED, as_ not in _NOT_EVALUATED
    if r_eval != a_eval:
        return "now evaluated" if a_eval else "not evaluated"
    if not r_eval:  # skip <-> error
        return "changed"
    return "REGRESSION" if _RANK[as_] > _RANK[rs] else "improvement"


def _label(path: str) -> str:
    """A package path from a report, made safe to print."""
    return (_UNSAFE.sub("?", path)[:80]) or ". (root)"


def diff_reports(reference: Path, actual: Path) -> tuple[str, int] | None:
    """(report text, exit code 0/1), or None when either file is not a readable report."""
    ref, act = load_report(reference), load_report(actual)
    if ref is None or act is None or ref[0] != act[0]:
        return None
    rows: list[tuple[str, str, str, str, str]] = []  # package, id, reference, actual, change
    counts = {"REGRESSION": 0, "improvement": 0}
    others = 0
    failed = False
    for pkg in sorted(set(ref[1]) | set(act[1])):
        r_pkg, a_pkg = ref[1].get(pkg), act[1].get(pkg)
        if r_pkg is None or a_pkg is None:
            rows.append((pkg, "(whole package)", "-" if r_pkg is None else "present",
                         "-" if a_pkg is None else "present",
                         "new" if r_pkg is None else "missing"))  # fmt: skip
            others += 1
            continue
        for cid in sorted(set(r_pkg) | set(a_pkg)):
            change = _classify(r_pkg.get(cid), a_pkg.get(cid))
            if change is None:
                continue
            r, a = r_pkg.get(cid), a_pkg.get(cid)
            rows.append((pkg, cid, r[0].value if r else "-", a[0].value if a else "-", change))
            if change in counts:
                counts[change] += 1
            else:
                others += 1
            # same rule as --baseline: a new or worse FAIL breaks the build
            if a and a[0] is Status.FAIL and (r is None or r[0] is not Status.FAIL):
                failed = True

    lines: list[str] = []
    if rows:
        width = max(len("check_id"), *(len(r[1]) for r in rows))
        header = f"{'check_id':<{width}}  {'reference':<9}  {'actual':<9}  change"
        for pkg in dict.fromkeys(r[0] for r in rows):
            if ref[0]:
                lines += ["", f"-- {_label(pkg)} --"]
            lines.append(header)
            lines += [
                f"{cid:<{width}}  {rv:<9}  {av:<9}  {ch}" for p, cid, rv, av, ch in rows if p == pkg
            ]
        lines.append("")
    parts = []
    if counts["REGRESSION"]:
        n = counts["REGRESSION"]
        parts.append(f"{n} regression{'s' * (n != 1)}")
    if counts["improvement"]:
        n = counts["improvement"]
        parts.append(f"{n} improvement{'s' * (n != 1)}")
    if others:
        parts.append(f"{others} other difference{'s' * (others != 1)}")
    lines.append((", ".join(parts) + ".") if parts else "No differences.")
    lines.append("Compared two saved reports. Nothing was run or changed.")
    return "\n".join(lines).lstrip("\n"), 1 if failed else 0
