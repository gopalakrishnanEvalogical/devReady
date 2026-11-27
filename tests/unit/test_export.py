import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import jsonschema
import pytest

from devready.cli import main
from devready.exporter import FORMATS, ExportError, parse_formats, plan, render, write
from devready.formats import junit, junit_projects, sarif_projects
from devready.models import Result, Status
from devready.runner import report, report_projects

DOCS = Path(__file__).parents[2] / "docs"
SCHEMA = json.loads((DOCS / "schema.json").read_text())
MULTI = json.loads((DOCS / "schema-multi.json").read_text())
MISSING = "DR_EXPORT_TEST_MISSING"

RESULTS = [
    Result("a.ok", "A", Status.PASS, "fine"),
    Result("c.fail", "C", Status.FAIL, "broken", "Switch versions"),
]


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.delenv(MISSING, raising=False)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".devready.json").write_text(json.dumps({"env": [MISSING]}))
    return proj


def _export(project, out, *extra):
    return main(["export", "--project", str(project), "--output-dir", str(out), *extra])


def test_writes_all_three_formats_that_validate(project, tmp_path, capsys):
    out = tmp_path / "reports"
    assert _export(project, out, "--only", "project") == 1  # a failing check still fails CI
    printed = capsys.readouterr().out
    assert sorted(p.name for p in out.iterdir()) == sorted(FORMATS.values())
    assert "Wrote 3 reports from one run:" in printed
    for name in FORMATS.values():
        assert name in printed
    data = json.loads((out / "report.json").read_text())
    jsonschema.validate(data, SCHEMA)
    sarif = json.loads((out / "report.sarif").read_text())
    assert sarif["version"] == "2.1.0" and sarif["runs"][0]["results"]
    suite = ET.fromstring((out / "report.junit.xml").read_text())
    assert suite.tag in ("testsuite", "testsuites")


def test_files_come_from_the_same_run_and_match_check_output(project, tmp_path, capsys):
    out = tmp_path / "reports"
    _export(project, out, "--only", "project")
    capsys.readouterr()
    main(["check", "--project", str(project), "--format", "json", "--only", "project"])
    assert (out / "report.json").read_text() == capsys.readouterr().out.replace("\r\n", "\n")
    ids = {r["check_id"] for r in json.loads((out / "report.json").read_text())["results"]}
    sarif_ids = {
        r["ruleId"] for r in json.loads((out / "report.sarif").read_text())["runs"][0]["results"]
    }
    assert sarif_ids <= ids and "project.env.required" in ids


def test_exit_zero_when_nothing_fails(project, tmp_path, capsys):
    (project / ".devready.json").write_text("{}")
    assert _export(project, tmp_path / "r2", "--only", "disk", "--formats", "json") == 0
    assert sorted(p.name for p in (tmp_path / "r2").iterdir()) == ["report.json"]


def test_formats_subset_and_duplicates(project, tmp_path):
    out = tmp_path / "r"
    _export(project, out, "--formats", "junit, json,junit", "--only", "project")
    assert sorted(p.name for p in out.iterdir()) == ["report.json", "report.junit.xml"]


@pytest.mark.parametrize("bad", ["", "xml", "json,pdf", ",", "json;sarif"])
def test_unknown_format_is_usage_error_and_writes_nothing(project, tmp_path, capsys, bad):
    out = tmp_path / "r"
    assert _export(project, out, "--formats", bad) == 2
    assert not out.exists()
    assert "--formats takes" in capsys.readouterr().err


def test_existing_file_refused_without_force_and_nothing_written(project, tmp_path, capsys):
    out = tmp_path / "r"
    out.mkdir()
    (out / "report.sarif").write_text("KEEP")
    assert _export(project, out) == 2
    assert "already exists; use --force" in capsys.readouterr().err
    assert (out / "report.sarif").read_text() == "KEEP"
    assert not (out / "report.json").exists()  # all-or-nothing: no partial export


def test_force_overwrites(project, tmp_path):
    out = tmp_path / "r"
    out.mkdir()
    (out / "report.json").write_text("OLD")
    assert _export(project, out, "--force", "--only", "project") == 1
    assert json.loads((out / "report.json").read_text())["schema_version"] == 1


def test_creates_directory_only_when_parent_exists(project, tmp_path, capsys):
    assert _export(project, tmp_path / "missing" / "deep", "--only", "project") == 2
    assert "parent of --output-dir does not exist" in capsys.readouterr().err
    assert not (tmp_path / "missing").exists()


def test_output_dir_that_is_a_file_is_refused(project, tmp_path, capsys):
    f = tmp_path / "file"
    f.write_text("x")
    assert _export(project, f) == 2
    assert "not a directory" in capsys.readouterr().err


def _symlink(link, target, is_dir):
    try:
        os.symlink(target, link, target_is_directory=is_dir)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need privileges on this machine")


def test_symlinked_directory_refused(project, tmp_path, capsys):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    _symlink(link, real, True)
    assert _export(project, link) == 2
    assert "symlink" in capsys.readouterr().err
    assert list(real.iterdir()) == []


def test_symlinked_report_file_refused_even_with_force(project, tmp_path, capsys):
    out = tmp_path / "r"
    out.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("SAFE")
    _symlink(out / "report.json", victim, False)
    assert _export(project, out, "--force") == 2
    assert victim.read_text() == "SAFE"


def test_recursive_export(project, tmp_path):
    (project / "package.json").write_text(json.dumps({"workspaces": ["packages/*"]}))
    (project / "packages" / "a").mkdir(parents=True)
    (project / "packages" / "a" / ".nvmrc").write_text("18\n")
    out = tmp_path / "r"
    _export(project, out, "--recursive", "--only", "project")
    data = json.loads((out / "report.json").read_text())
    jsonschema.validate(data, MULTI)
    assert {p["path"] for p in data["projects"]} >= {".", "packages/a"}


def test_bad_project_is_usage_error_and_writes_nothing(tmp_path):
    out = tmp_path / "r"
    assert _export(tmp_path / "nope", out) == 2
    assert not out.exists()


def test_render_matches_the_formatters():
    projects = [("", RESULTS)]
    assert json.loads(render("json", projects, False)) == report(RESULTS)
    assert render("junit", projects, False) == junit(RESULTS)
    assert render("sarif", projects, False, "x") == sarif_projects(projects, "x")
    multi = [(".", RESULTS), ("pkg", RESULTS)]
    assert json.loads(render("json", multi, True)) == report_projects(multi)
    assert render("junit", multi, True) == junit_projects(multi)
    with pytest.raises(ValueError):
        render("text", projects, False)


def test_plan_and_write_unit(tmp_path):
    targets = plan(tmp_path / "out", ["json"], False)
    paths = write(targets, {"json": "{}"})
    assert paths[0].read_bytes() == b"{}\n"
    with pytest.raises(ExportError):
        plan(tmp_path / "out", ["json"], False)
    assert plan(tmp_path / "out", ["json"], True)
    assert parse_formats("json,sarif") == ["json", "sarif"]


def test_hostile_report_text_is_not_a_file_name(project, tmp_path):
    (project / ".devready.json").write_text(json.dumps({"skip": ["../../evil"]}))
    out = tmp_path / "r"
    _export(project, out, "--only", "project")
    assert sorted(p.name for p in out.iterdir()) == sorted(FORMATS.values())  # fixed names only
    assert not (tmp_path / "evil").exists()


def test_links_are_refused_even_where_real_symlinks_are_unavailable(tmp_path, monkeypatch):
    import devready.exporter as ex

    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(ex, "_is_link", lambda p: p == out)
    with pytest.raises(ExportError, match="symlink"):
        plan(out, ["json"], True)
    monkeypatch.setattr(ex, "_is_link", lambda p: p.name == "report.json")
    with pytest.raises(ExportError, match="symlink"):
        plan(out, ["json"], True)  # --force never writes through a link
