"""Compare a run with a saved report (`devready check --format json > baseline.json`).

DevReady only reads the baseline; saving or committing it is up to you. That covers both a
shared team baseline (committed file) and diffing against an earlier local run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from devready.checks.project import _read
from devready.models import Result, Status

_ID = re.compile(r"^[a-z_]+(\.[a-z_]+)+$")
_RANK = {Status.PASS: 0, Status.SKIP: 0, Status.WARN: 1, Status.ERROR: 2, Status.FAIL: 3}


def _report(path: Path) -> dict:
    """A v1 report; raises ValueError/KeyError/TypeError when the file is not one."""
    text = _read(path)
    data = json.loads(text) if text else None
    if data["schema_version"] != 1:
        raise ValueError("not schema_version 1")
    return data


def _statuses(results: list) -> dict[str, Status]:
    return {
        r["check_id"]: Status(r["status"])
        for r in results
        if isinstance(r["check_id"], str) and _ID.match(r["check_id"])
    }


def load_baseline(path: Path) -> dict[str, Status] | None:
    """check_id -> status, or None if the file is missing, too big, or not a v1 report."""
    try:
        return _statuses(_report(path)["results"])
    except (ValueError, KeyError, TypeError):
        return None


def load_project_baselines(path: Path) -> dict[str, dict[str, Status]] | None:
    """package path -> (check_id -> status) from a saved `check --recursive --format json`."""
    try:
        return {p["path"]: _statuses(p["results"]) for p in _report(path)["projects"]}
    except (ValueError, KeyError, TypeError):
        return None


def diff(results: list[Result], base: dict[str, Status]) -> tuple[list[Result], bool]:
    """(results that are new or changed status, whether any FAIL got worse)."""
    changed = [r for r in results if base.get(r.check_id) is not r.status]
    worse = any(
        r.status is Status.FAIL and _RANK[r.status] > _RANK.get(base.get(r.check_id), 0)
        for r in changed
    )
    return changed, worse


def _entries(results: list) -> dict[str, tuple[Status, str]]:
    """check_id -> (status, summary); entries with an invalid id are dropped."""
    out = {}
    for r in results:
        cid = r["check_id"]
        if isinstance(cid, str) and _ID.match(cid):
            summary = r["summary"] if isinstance(r["summary"], str) else ""
            out[cid] = (Status(r["status"]), summary)
    return out


def load_report(path: Path) -> tuple[bool, dict[str, dict[str, tuple[Status, str]]]] | None:
    """(is --recursive report, package path -> check_id -> (status, summary)), or None.

    A plain report is returned under the package path "". None when the file is missing, too
    big, a symlink or not a v1 report. Summaries are untrusted: callers compare, never print.
    """
    try:
        data = _report(path)
        if "projects" in data:
            return True, {str(p["path"]): _entries(p["results"]) for p in data["projects"]}
        return False, {"": _entries(data["results"])}
    except (ValueError, KeyError, TypeError):
        return None
