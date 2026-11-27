"""`devready generate`: propose pin files from the tool versions installed on this machine.

Print-only: nothing is written, and existing files are never read (so their content can never
be echoed) or replaced. Versions come from the same detection `check` uses, so a proposal that is
written to a project is accepted by `check` on the same machine.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from devready.checks.python_check import check_python
from devready.checks.tools import TOOLS, check_tool
from devready.versions import parse_version

NODE_PINS = (".nvmrc", ".node-version")
PYTHON_PIN = ".python-version"
CONFIG = ".devready.json"
FILES = (".nvmrc", PYTHON_PIN, CONFIG)


@dataclass(frozen=True)
class Entry:
    name: str
    status: str  # "proposed" | "exists" | "not_found"
    content: str = ""  # the file's content, only when proposed
    note: str = ""  # fixed text only


def _node(root: Path) -> str | None:
    tool = next(t for t in TOOLS if t[2] == "node")
    return check_tool(*tool)[1]


def detect(root: Path) -> tuple[str | None, str | None]:
    """(node version, python version) as `check` sees them for this project; None if absent."""
    return _node(root), check_python(root)[1]


def _exists(root: Path, name: str) -> bool:
    return os.path.lexists(root / name)  # never read: hostile content cannot be echoed


def propose(
    root: Path, detector: Callable[[Path], tuple[str | None, str | None]] | None = None
) -> list[Entry]:
    node_raw, py_raw = (detector or detect)(root)
    node = parse_version(node_raw) if node_raw else None
    py = parse_version(py_raw) if py_raw else None
    node_pin = f"{node[0]}" if node else None
    py_pin = f"{py[0]}.{py[1]}" if py and len(py) >= 2 else None
    require = {}
    if node_pin:
        require["node"] = f">={node_pin}"
    if py_pin:
        require["python"] = f">={py_pin}"

    out = []
    existing_node = next((n for n in NODE_PINS if _exists(root, n)), None)
    if existing_node:
        out.append(Entry(".nvmrc", "exists", note=f"{existing_node} already exists, not replaced"))
    elif node_pin:
        out.append(Entry(".nvmrc", "proposed", node_pin))
    else:
        out.append(Entry(".nvmrc", "not_found", note="Node.js not found, nothing proposed"))
    if _exists(root, PYTHON_PIN):
        out.append(Entry(PYTHON_PIN, "exists", note="already exists, not replaced"))
    elif py_pin:
        out.append(Entry(PYTHON_PIN, "proposed", py_pin))
    else:
        out.append(Entry(PYTHON_PIN, "not_found", note="Python not found, nothing proposed"))
    if _exists(root, CONFIG):
        out.append(Entry(CONFIG, "exists", note="already exists, not replaced"))
    elif require:
        out.append(Entry(CONFIG, "proposed", json.dumps({"require": require})))
    else:
        out.append(Entry(CONFIG, "not_found", note="no tool versions found, nothing proposed"))
    return out


def render(entries: list[Entry]) -> str:
    width = max(len(e.name) for e in entries)
    lines = ["DevReady - Proposed files (nothing was written)", ""]
    for e in entries:
        lines.append(f"  {e.name:<{width}}  {e.content if e.status == 'proposed' else e.note}")
    lines += [
        "",
        "These record the versions installed on THIS machine: review them before committing.",
        "DevReady never writes files: create the ones you want yourself with the values above.",
    ]
    return "\n".join(lines)


__all__ = ["FILES", "Entry", "detect", "propose", "render"]
