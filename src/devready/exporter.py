"""Report rendering shared by `check` and `export`, and the safe file writing `export` does.

`export` is the only command that writes files, and only inside the directory you name, with
fixed file names. It never overwrites an existing file without --force and never follows a
symlink. Nothing else is ever written.
"""

from __future__ import annotations

import json
from pathlib import Path

from devready.formats import junit, junit_projects, sarif_projects
from devready.models import Result
from devready.runner import report, report_projects

# format -> fixed file name. The user picks the directory only, never a file name.
FORMATS = {"json": "report.json", "sarif": "report.sarif", "junit": "report.junit.xml"}


class ExportError(Exception):
    """A usage problem: the message is fixed text, safe to print."""


def render(
    fmt: str, projects: list[tuple[str, list[Result]]], recursive: bool, sarif_base: str = ""
) -> str:
    """The json, junit or sarif report text (without the trailing newline `print` adds)."""
    results = [r for _, rs in projects for r in rs]
    if fmt == "json":
        return json.dumps(report_projects(projects) if recursive else report(results), indent=2)
    if fmt == "junit":
        return junit_projects(projects) if recursive else junit(results)
    if fmt == "sarif":
        return sarif_projects(projects, sarif_base)
    raise ValueError(fmt)


def parse_formats(value: str) -> list[str]:
    names = list(dict.fromkeys(n.strip() for n in value.split(",")))
    if not value.strip() or any(n not in FORMATS for n in names):
        raise ExportError(f"--formats takes a comma-separated list of: {', '.join(FORMATS)}")
    return names


def _is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def plan(out_dir: Path, formats: list[str], force: bool) -> list[tuple[str, Path]]:
    """(format, target) pairs, or ExportError. Checks everything before anything is written."""
    if _is_link(out_dir):
        raise ExportError("--output-dir is a symlink; refusing to write through it")
    if out_dir.exists():
        if not out_dir.is_dir():
            raise ExportError("--output-dir exists and is not a directory")
    elif not out_dir.parent.is_dir():
        raise ExportError("the parent of --output-dir does not exist; create it first")
    targets = [(fmt, out_dir / FORMATS[fmt]) for fmt in formats]
    for _, target in targets:
        if _is_link(target):
            raise ExportError(f"{target.name} is a symlink; refusing to write through it")
        if target.exists() and (not force or not target.is_file()):
            raise ExportError(f"{target.name} already exists; use --force to overwrite it")
    return targets


def write(targets: list[tuple[str, Path]], texts: dict[str, str]) -> list[Path]:
    """Write each report (with the trailing newline `check` prints). Returns the paths written."""
    written = []
    if targets:
        targets[0][1].parent.mkdir(exist_ok=True)
    for fmt, target in targets:
        if _is_link(target):  # re-checked: it could have changed since plan()
            raise ExportError(f"{target.name} is a symlink; refusing to write through it")
        target.write_bytes((texts[fmt] + "\n").encode("utf-8"))
        written.append(target)
    return written
