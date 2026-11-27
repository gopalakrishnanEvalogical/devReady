"""Org policy file (#44): one minimum toolchain for every repo, kept outside `.devready.json`.

{"policy_version": 1, "require": {"node": ">=20", "git": ">=2.40", "docker": "*"},
 "skip": ["platform.autocrlf"], "env": ["NPM_TOKEN"]}

Local files only, same read rules as project.py. A spec must be one the version matcher
understands, or "*" (installed, any version). An unreadable or invalid file gives one ERROR
result that never echoes the file's content or its path.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path

from devready.checks.config import _ENV_NAME, _ID
from devready.checks.project import _compare, _read
from devready.checks.runtimes import RUNTIMES
from devready.checks.tools import TOOLS, check_tool
from devready.models import Result, Status
from devready.versions import parse_version, satisfies

REQUIRABLE = {tool[2] for tool in TOOLS} | set(RUNTIMES) | {"python", "docker"}


def _spec_ok(spec: object) -> bool:
    return isinstance(spec, str) and (spec == "*" or satisfies((0, 0, 0), spec) is not None)


def _valid(policy: object) -> bool:
    keys = {"policy_version", "require", "skip", "env"}
    if not isinstance(policy, dict) or not set(policy) <= keys:
        return False
    version = policy.get("policy_version")
    req, skip, env = policy.get("require", {}), policy.get("skip", []), policy.get("env", [])
    return (
        type(version) is int  # JSON true would equal 1
        and version == 1
        and isinstance(req, dict)
        and all(k in REQUIRABLE and _spec_ok(v) for k, v in req.items())
        and isinstance(skip, list)
        and all(isinstance(i, str) and _ID.match(i) for i in skip)
        and isinstance(env, list)
        and all(isinstance(n, str) and _ENV_NAME.match(n) for n in env)
    )


def _error(summary: str, suggestion: str) -> Result:
    return Result("policy.file", "Policy", Status.ERROR, summary, suggestion)


def load_policy(path: Path) -> tuple[dict | None, Result | None]:
    """(policy, None) if valid, else (None, one policy.file ERROR result)."""
    try:
        text = _read(path)
    except (OSError, ValueError):
        text = None
    if text is None:
        return None, _error(
            "Policy file is missing, not a regular file, or over 1 MB",
            "Check the --policy path or DEVREADY_POLICY. Symlinks are not followed.",
        )
    try:
        policy = json.loads(text.removeprefix("\ufeff"))
    except ValueError:
        policy = None
    if _valid(policy):
        return policy, None
    return None, _error(
        "Policy file is invalid; it was ignored",
        'Needs "policy_version": 1. Optional: "require" (tool: version spec or "*"), '
        '"skip" (check ids), "env" (variable names).',
    )


# key -> (title, executable, version args, docs); fixed argv only, never built from policy text.
def _probes() -> dict[str, tuple]:
    probes = {exe: (title, exe, ("--version",), docs) for _, title, exe, docs in TOOLS}
    probes["docker"] = ("Docker", "docker", ("--version",), "https://docs.docker.com/get-docker/")
    for key, (title, exe, args, docs, *_) in RUNTIMES.items():
        probes[key] = (title, exe, args, docs)
    return probes


def check_policy(
    policy: dict,
    python: tuple[Result, str | None],
    cache: dict[str, tuple[Result, str | None]],
    probe: Callable = check_tool,
    environ: Mapping[str, str] = os.environ,
) -> list[Result]:
    """Evaluate policy `require` and `env` for one project; ids are `policy.<tool>.require`.

    `python` is the project's own interpreter result (a .venv may differ per package). Other
    tools are probed once through `cache` with the same fixed `--version` commands the checks use.
    A requirement for a tool that is not installed fails; one that is installed but whose version
    cannot be read or compared is `skip` (not evaluated), never `pass`.
    """
    probes = _probes()
    out: list[Result] = []
    for key, spec in policy.get("require", {}).items():
        cid, title = f"policy.{key}.require", f"{probes.get(key, (key.title(),))[0]} policy"
        if key == "python":
            found, version = python
        else:
            if key not in cache:
                label, exe, args, docs = probes[key]
                cache[key] = probe(cid, label, exe, docs, args)
            found, version = cache[key]
        if version is None:
            if found.status is Status.WARN:  # not on PATH
                out.append(
                    Result(
                        cid,
                        title,
                        Status.FAIL,
                        f"Policy requires {key}; it was not found on PATH",
                        f"Install {key}, or ask whoever owns the policy.",
                        found.docs_url,
                    )
                )
            else:
                out.append(
                    Result(
                        cid,
                        title,
                        Status.SKIP,
                        "Installed version could not be read; not evaluated",
                    )
                )
        elif spec == "*":
            out.append(Result(cid, title, Status.PASS, f"{version} installed (policy requires it)"))
        else:
            out.append(
                _compare(cid, title, "policy", spec, parse_version(version), Status.FAIL, "", key)
            )
    wanted = policy.get("env", [])
    if wanted:
        missing = [n for n in wanted if n not in environ]
        cid, title = "policy.env.required", "Policy env"
        if missing:
            out.append(
                Result(
                    cid,
                    title,
                    Status.FAIL,
                    f"policy: {len(missing)} of {len(wanted)} not set: {', '.join(missing[:10])}",
                    "Set these variables in your shell or CI (values are never read).",
                )
            )
        else:
            out.append(
                Result(cid, title, Status.PASS, f"policy: all {len(wanted)} variables are set")
            )
    return out
