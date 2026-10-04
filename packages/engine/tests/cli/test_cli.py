"""End-to-end tests for the `guardian` CLI (exit codes, formats, outputs)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from arch_guardian_engine.cli import app
from typer.testing import CliRunner

from tests.conftest import GitRepo

PLANTED = Path(__file__).resolve().parents[1] / "fixtures" / "planted_violations"
runner = CliRunner()

_VALID_YAML = (
    'schema_version: "1.0"\n'
    "project:\n  name: x\n  language: python\n"
    'architecture:\n  style: hexagonal\n  rule_pack_version: "1.0.0"\n'
)


@pytest.mark.integration
def test_text_report_and_exit_1_on_critical() -> None:
    result = runner.invoke(app, ["analyze", str(PLANTED)])
    assert result.exit_code == 1
    assert "CRITICAL [universal.circular_dependency]" in result.stdout
    assert "arch-guardian: 2 critical" in result.stdout


@pytest.mark.integration
def test_fail_on_never_exits_0() -> None:
    assert runner.invoke(app, ["analyze", str(PLANTED), "--fail-on", "never"]).exit_code == 0


@pytest.mark.integration
def test_fail_on_warning_with_only_warnings(tmp_path: Path) -> None:
    body = "def f(x):\n" + "".join(f"    if x == {i}:\n        return {i}\n" for i in range(20))
    (tmp_path / "m.py").write_text(body, encoding="utf-8")
    assert runner.invoke(app, ["analyze", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["analyze", str(tmp_path), "--fail-on", "warning"]).exit_code == 1


@pytest.mark.integration
def test_json_stdout_is_clean_even_with_verbose_logs() -> None:
    result = runner.invoke(app, ["analyze", str(PLANTED), "-f", "json", "-v", "--fail-on", "never"])
    payload = json.loads(result.stdout)  # logs went to stderr, not stdout
    assert payload["resolved_style"] == "universal"
    assert len(payload["findings"]) == 5


@pytest.mark.integration
def test_sarif_written_to_file(tmp_path: Path) -> None:
    out = tmp_path / "reports" / "guardian.sarif"
    result = runner.invoke(
        app, ["analyze", str(PLANTED), "-f", "sarif", "-o", str(out), "--fail-on", "never"]
    )
    assert result.exit_code == 0
    assert result.stdout == ""
    sarif = json.loads(out.read_text(encoding="utf-8"))
    run = sarif["runs"][0]
    assert sarif["version"] == "2.1.0"
    rule_ids = [r["id"] for r in run["tool"]["driver"]["rules"]]
    assert len(rule_ids) == len(set(rule_ids))
    for res in run["results"]:
        assert rule_ids[res["ruleIndex"]] == res["ruleId"]
        assert res["partialFingerprints"]["archGuardian/v1"]
        assert res["level"] in {"error", "warning", "note"}
    # Fixture lives inside this git repo: URIs must be repo-root relative.
    uri = run["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert uri.startswith("packages/engine/tests/fixtures/planted_violations/src/")


@pytest.mark.integration
def test_invalid_architecture_yaml_exits_2_unless_allowed(tmp_path: Path) -> None:
    (tmp_path / ".architecture.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    strict = runner.invoke(app, ["analyze", str(tmp_path)])
    assert strict.exit_code == 2
    assert "invalid .architecture.yaml" in strict.stderr
    relaxed = runner.invoke(app, ["analyze", str(tmp_path), "--allow-invalid-config"])
    assert relaxed.exit_code == 0


@pytest.mark.integration
def test_valid_yaml_reports_rule_pack(tmp_path: Path) -> None:
    (tmp_path / ".architecture.yaml").write_text(_VALID_YAML, encoding="utf-8")
    result = runner.invoke(app, ["analyze", str(tmp_path)])
    assert result.exit_code == 0
    assert "style hexagonal@1.0.0" in result.stdout


@pytest.mark.integration
def test_base_mode_and_bad_ref(git_repo: GitRepo) -> None:
    git_repo.write("a.py", "from b import B\n")
    git_repo.write("b.py", "from a import A\n")
    git_repo.commit("cycle")
    ok = runner.invoke(app, ["analyze", str(git_repo.root), "--base", "main"])
    assert ok.exit_code == 0, ok.stdout
    assert "new vs main" in ok.stdout
    assert "1 pre-existing hidden" in ok.stdout

    bad = runner.invoke(app, ["analyze", str(git_repo.root), "--base", "does-not-exist"])
    assert bad.exit_code == 2
    assert "guardian:" in bad.stderr


@pytest.mark.integration
def test_base_outside_git_exits_2(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(tmp_path), "--base", "main"])
    assert result.exit_code == 2


@pytest.mark.unit
def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip()
