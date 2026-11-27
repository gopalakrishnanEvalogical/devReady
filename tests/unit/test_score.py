import json
import xml.etree.ElementTree as ET
from pathlib import Path

import jsonschema
import pytest

from devready.cli import main
from devready.models import Result, Status
from devready.score import badge, compute, text

SCHEMA = json.loads((Path(__file__).parents[2] / "docs" / "schema-score.json").read_text())
MISSING = "DR_SCORE_TEST_MISSING"


def _r(*statuses):
    return [Result(f"a.c{i}", "T", Status(s), "x") for i, s in enumerate(statuses)]


def test_all_pass_is_100():
    d = compute(_r("pass", "pass", "pass"))
    assert d["score"] == 100 and d["evaluated"] == 3 and d["not_evaluated"] == 0


def test_warn_counts_half_and_fail_zero():
    assert compute(_r("pass", "warn"))["score"] == 75
    assert compute(_r("pass", "fail"))["score"] == 50
    assert compute(_r("fail", "fail"))["score"] == 0
    assert compute(_r("warn", "warn"))["score"] == 50


@pytest.mark.parametrize(
    "statuses",
    [
        ["pass"] * 7 + ["warn"],  # 93.75
        ["pass", "pass", "warn"],  # 83.33
        ["pass"] * 7 + ["warn"] * 2,  # 88.89
        ["warn"] + ["fail"] * 7,  # 6.25
        ["warn"] + ["fail"] * 15,  # 3.125
        ["pass", "warn", "fail"],  # 50
    ],
)
def test_rounding_matches_an_independent_hand_calculation(statuses):
    exact = 100 * (statuses.count("pass") + statuses.count("warn") / 2) / len(statuses)
    assert compute(_r(*statuses))["score"] == int(exact + 0.5)


def test_exact_halves_round_up_not_to_even():
    # 100 * 0.5 / 4 = 12.5 -> 13 (Python's round() would give 12, banker's rounding)
    assert compute(_r("warn", "fail", "fail", "fail"))["score"] == 13
    assert compute(_r("pass", "pass", "pass", "warn"))["score"] == 88  # 87.5


def test_skip_and_error_are_not_counted_as_passing():
    d = compute(_r("pass", "skip", "error", "fail"))
    assert d["score"] == 50 and d["evaluated"] == 2 and d["not_evaluated"] == 2
    assert d["counts"] == {"pass": 1, "warn": 0, "fail": 1, "skip": 1, "error": 1}


def test_nothing_evaluated_is_n_a_never_100():
    for statuses in ([], ["skip", "skip"], ["error"], ["skip", "error"]):
        d = compute(_r(*statuses))
        assert d["score"] is None and d["evaluated"] == 0
    assert "n/a" in text(compute(_r("skip")))
    assert "100" not in text(compute(_r("skip")))


def test_text_wording():
    out = text(compute(_r("pass", "warn", "warn", "fail", "skip")))
    assert out.splitlines()[0] == "DevReady score: 50 / 100"
    assert "2 warnings, 1 failure, 1 not evaluated." in out
    assert "devready check" in out
    assert "1 warning," in text(compute(_r("warn")))


def test_json_validates_against_the_schema():
    for statuses in ([], ["pass"], ["pass", "warn", "fail", "skip", "error"]):
        jsonschema.validate(compute(_r(*statuses)), SCHEMA)
    assert SCHEMA["properties"]["schema_version"] == {"const": 1}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**compute(_r("pass")), "extra": 1}, SCHEMA)


@pytest.mark.parametrize("score", [None, 0, 49, 50, 69, 70, 89, 90, 100])
def test_badge_is_well_formed_and_self_contained(score):
    svg = badge(score)
    root = ET.fromstring(svg)  # well-formed
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    lowered = svg.lower()
    assert svg.count("http") == 1 and 'xmlns="http://www.w3.org/2000/svg"' in svg  # namespace only
    for bad in ("href", "url(", "<image", "<script", "@import", "<style", "<a "):
        assert bad not in lowered
    assert ("n/a" if score is None else f"{score}%") in svg
    assert svg.isascii()


def test_badge_colour_follows_the_score():
    assert "#4c1" in badge(95) and "#e05d44" in badge(10) and "#9f9f9f" in badge(None)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.delenv(MISSING, raising=False)
    (tmp_path / ".devready.json").write_text(json.dumps({"env": [MISSING]}))
    (tmp_path / ".nvmrc").write_text("999\n")
    return tmp_path


def _json(capsys, *args):
    code = main(["score", "--format", "json", *args])
    return code, json.loads(capsys.readouterr().out)


def test_score_matches_a_hand_calculation_from_check(project, capsys):
    main(["check", "--project", str(project), "--format", "json", "--only", "project"])
    results = json.loads(capsys.readouterr().out)["results"]
    st = [r["status"] for r in results]
    evaluated = [s for s in st if s in ("pass", "warn", "fail")]
    points = sum({"pass": 1, "warn": 0.5, "fail": 0}[s] for s in evaluated)
    hand = int(100 * points / len(evaluated) + 0.5)
    code, data = _json(capsys, "--project", str(project), "--only", "project")
    assert code == 0 and data["score"] == hand  # a failing check alone does not make score exit 1
    assert data["evaluated"] == len(evaluated)
    assert data["not_evaluated"] == len(st) - len(evaluated)
    jsonschema.validate(data, SCHEMA)


def test_cli_text_default_and_exit_zero(project, capsys):
    assert main(["score", "--project", str(project), "--only", "project"]) == 0
    assert capsys.readouterr().out.startswith("DevReady score: ")


def test_min_boundary(project, capsys):
    _, data = _json(capsys, "--project", str(project), "--only", "project")
    s = data["score"]
    assert main(["score", "--project", str(project), "--only", "project", "--min", str(s)]) == 0
    assert main(["score", "--project", str(project), "--only", "project", "--min", str(s + 1)]) == 1
    assert main(["score", "--project", str(project), "--only", "project", "--min", "0"]) == 0
    capsys.readouterr()


def test_min_with_nothing_evaluated_fails_the_gate(tmp_path, capsys):
    args = ["score", "--project", str(tmp_path), "--only", "no.such.check"]
    assert main(args) == 0
    assert "n/a" in capsys.readouterr().out
    assert main([*args, "--min", "0"]) == 1


@pytest.mark.parametrize("bad", ["-1", "101", "abc", "5.5", ""])
def test_bad_min_is_usage_error(tmp_path, capsys, bad):
    assert main(["score", "--project", str(tmp_path), "--min", bad]) == 2
    capsys.readouterr()


def test_badge_and_json_cannot_be_combined(tmp_path, capsys):
    assert main(["score", "--project", str(tmp_path), "--badge", "--format", "json"]) == 2
    assert "--badge prints an SVG" in capsys.readouterr().err


def test_badge_output_is_the_svg(tmp_path, capsys):
    assert main(["score", "--project", str(tmp_path), "--badge", "--only", "no.such"]) == 0
    out = capsys.readouterr().out
    ET.fromstring(out)
    assert "n/a" in out


def test_bad_project_is_usage_error(tmp_path, capsys):
    assert main(["score", "--project", str(tmp_path / "nope")]) == 2
    capsys.readouterr()


def test_check_report_is_unchanged_by_score(tmp_path, capsys):
    main(["check", "--project", str(tmp_path), "--format", "json", "--only", "project"])
    assert "score" not in json.loads(capsys.readouterr().out)
