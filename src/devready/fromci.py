"""`devready init --from-ci FILE`: a starter .devready.json from a GitHub Actions workflow.

The standard library has no YAML parser, so this reads `node-version:` and `python-version:`
lines only. It never executes anything and never guesses: expressions (`${{ ... }}`), matrices and
lists, `lts/*`-style aliases, version files and values that differ between jobs are reported as
"could not read" instead. Only values matching the safe version pattern are ever emitted; nothing
else from the file is echoed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from devready.checks.project import _read
from devready.versions import SAFE_SPEC, satisfies

_LINE = re.compile(
    r"^\s*(?:-\s+)?(node|python)-version(-file)?\s*:\s*(.*?)\s*$"
)  # value may carry a trailing comment, stripped below
_PLAIN = re.compile(r"^v?(\d+(?:\.\d+){0,2})(?:\.x)?$")
_FILE_NAME = re.compile(r"^[A-Za-z0-9._/-]{1,60}$")
_REUSABLE = re.compile(r"^\s*(?:-\s+)?uses\s*:\s*\S*\.github/workflows/", re.M)


class WorkflowError(Exception):
    """The workflow file could not be read; the message is fixed text."""


def _value(raw: str) -> str:
    raw = re.sub(r"\s+#.*$", "", raw).strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        raw = raw[1:-1].strip()
    return raw


def _classify(raw: str) -> tuple[str, str]:
    """('spec', requirement) or ('skip', reason). Reasons are fixed words."""
    if not raw or raw.startswith("[") or raw == "-" or re.fullmatch(r"[|>][+-]?\d?", raw):
        return "skip", "a matrix or list"
    if "${{" in raw:
        return "skip", "an expression"
    if m := _PLAIN.match(raw):
        return "spec", f">={m.group(1)}"
    if raw[0] in "<>=^~" and SAFE_SPEC.match(raw) and satisfies((0, 0, 0), raw) is not None:
        return "spec", raw
    if re.fullmatch(r"(?i)lts/[\w*-]+|latest|current|stable|node|\*|x", raw):
        return "skip", "not a fixed version, such as lts/* or latest"
    return "skip", "not a recognized version"


def parse(text: str) -> tuple[dict[str, str], list[str]]:
    """(require, notes). Notes are the fixed-word explanations for what could not be read."""
    found: dict[str, list[tuple[str, str]]] = {"node": [], "python": []}
    for line in text.splitlines():
        if line.lstrip().startswith("#") or not (m := _LINE.match(line)):
            continue
        tool, is_file, raw = m.group(1), m.group(2), _value(m.group(3))
        if is_file:
            name = raw if _FILE_NAME.match(raw) else "a file"
            found[tool].append(("file", name))
        else:
            found[tool].append(_classify(raw))
    require, notes = {}, []
    for tool, entries in found.items():
        label = "Node" if tool == "node" else "Python"
        if not entries:
            notes.append(f"{label}: no {tool}-version found in the workflow")
            continue
        files = [v for k, v in entries if k == "file"]
        skips = [v for k, v in entries if k == "skip"]
        specs = {v for k, v in entries if k == "spec"}
        if files:
            notes.append(f"{label}: already pinned by {files[0]}")
        elif skips:
            notes.append(f"{label}: could not read ({skips[0]})")
        elif len(specs) > 1:
            notes.append(f"{label}: could not read (several different versions)")
        else:
            require[tool] = specs.pop()
    if _REUSABLE.search(text):
        notes.append("Workflow calls a reusable workflow; its versions are not read")
    return require, notes


def load(path: Path) -> str:
    """The workflow text, or WorkflowError (missing, not a regular file, a symlink, over 1 MB)."""
    try:
        text = _read(path)
    except OSError:
        text = None
    if text is None:
        raise WorkflowError("workflow file is missing, not a regular file, or over 1 MB")
    return text


def render(require: dict[str, str]) -> str:
    """Same shape as `devready init`, with `require` filled in."""
    return json.dumps({"skip": [], "require": require, "env": []}, indent=2)
