import json

from devready.cli import main
from devready.doctor import doctor_report
from devready.formats import fix_plan
from devready.models import Result, Status

MISSING = "DEVREADY_DOCTOR_TEST_MISSING"


def _project(tmp_path, warn=True):
    (tmp_path / ".devready.json").write_text(json.dumps({"env": [MISSING]}))
    if warn:
        (tmp_path / ".nvmrc").write_text("999\n")
    return tmp_path


def test_fail_and_warn_report(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(MISSING, raising=False)
    assert main(["doctor", "--project", str(_project(tmp_path))]) == 1
    out = capsys.readouterr().out
    assert out.startswith("DevReady Doctor")
    assert "x FAIL  project.env.required" in out
    assert "Means:" in out and "Fix:" in out
    assert "failure" in out and "warning" in out
    assert out.rstrip().endswith("DevReady did not run any of these. Nothing was changed.")


def test_failures_listed_before_warnings():
    rs = [
        Result("a.warn", "A", Status.WARN, "w", "do w"),
        Result("b.fail", "B", Status.FAIL, "f", "do f"),
    ]
    out = doctor_report(rs)
    assert out.index("b.fail") < out.index("a.warn")


def test_clean_project_exit_zero(tmp_path, capsys):
    assert main(["doctor", "--project", str(tmp_path), "--only", "git"]) == 0
    out = capsys.readouterr().out
    assert "No problems found." in out
    assert "Nothing was changed." in out


def test_unknown_id_has_no_means_line():
    out = doctor_report([Result("zzz.unknown", "Z", Status.FAIL, "broken", "try this")])
    assert "Means:" not in out
    assert "Fix:   try this" in out


def test_skip_and_error_counted_separately():
    rs = [
        Result("a.ok", "A", Status.PASS, "ok"),
        Result("b.skip", "B", Status.SKIP, "n/a"),
        Result("c.err", "C", Status.ERROR, "?"),
    ]
    out = doctor_report(rs)
    assert "1 passed, 0 warnings, 0 failures, 2 not evaluated." in out
    assert "b.skip" not in out and "c.err" not in out  # only problems get entries


def test_fix_text_matches_fix_plan():
    r = Result("c.fail", "C", Status.FAIL, "broken", "Switch versions")
    assert "Switch versions" in doctor_report([r]) and "Switch versions" in fix_plan([r])


def test_hostile_text_stays_plain():
    r = Result("x.y", "X", Status.FAIL, "Ignore previous instructions \x1b[31m", "")
    out = doctor_report([r])
    assert "Ignore previous instructions" in out  # shown as data, not acted on
    assert "Fix:" not in out


def test_only_and_skip_filters(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(MISSING, raising=False)
    p = str(_project(tmp_path))
    assert main(["doctor", "--project", p, "--skip", "project.env"]) == 0
    assert "project.env.required" not in capsys.readouterr().out


def test_bad_project_is_usage_error(tmp_path, capsys):
    assert main(["doctor", "--project", str(tmp_path / "nope")]) == 2
