"""GitHub annotation format and --report extra outputs."""

from __future__ import annotations

from pathlib import Path

import pytest
from arch_guardian_engine.cli import app
from arch_guardian_engine.config import Severity
from arch_guardian_engine.findings import (
    AnalysisReport,
    Finding,
    FindingLocation,
    FindingSource,
)
from arch_guardian_engine.report.github import to_github
from typer.testing import CliRunner

runner = CliRunner()
COMPLEX = "def f(x):\n" + "".join(f"    if x == {i}:\n        return {i}\n" for i in range(20))


def _report(*findings: Finding, **extra: object) -> AnalysisReport:
    return AnalysisReport(
        repo="/r",
        resolved_style="universal",
        resolution_source="fallback_universal",
        findings=findings,
        **extra,  # type: ignore[arg-type]
    )


@pytest.mark.unit
def test_github_annotation_escaping_and_levels() -> None:
    f = Finding(
        rule_id="universal.god_object",
        severity=Severity.WARNING,
        title="God Object: A, B",
        message="50% bigger\nsecond line",
        location=FindingLocation(file="src/a.py", line=3, end_line=9),
        source=FindingSource.UNIVERSAL,
    )
    suggestion = f.model_copy(update={"severity": Severity.SUGGESTION})
    out = to_github(
        _report(f, suggestion, warnings=("exception expired",)), path_prefix="svc"
    ).splitlines()
    assert out[0] == (
        "::warning file=svc/src/a.py,line=3,endLine=9,"
        "title=[universal.god_object] God Object%3A A%2C B::50%25 bigger%0Asecond line"
    )
    assert out[1].startswith("::notice ")
    assert out[2] == "::warning title=arch-guardian::exception expired"


@pytest.mark.unit
def test_github_empty_report_is_empty() -> None:
    assert to_github(_report()) == ""


@pytest.mark.integration
def test_extra_reports_written_from_one_run(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(COMPLEX, encoding="utf-8")
    sarif, text = tmp_path / "out" / "g.sarif", tmp_path / "out" / "s.txt"
    result = runner.invoke(
        app,
        [
            "analyze",
            str(tmp_path),
            "-f",
            "github",
            "--report",
            f"sarif:{sarif}",
            "--report",
            f"text:{text}",
        ],
    )
    assert result.exit_code == 0
    assert result.stdout.startswith("::warning file=m.py,line=1")
    assert '"version": "2.1.0"' in sarif.read_text(encoding="utf-8")
    assert "1 warning" in text.read_text(encoding="utf-8")


@pytest.mark.unit
@pytest.mark.parametrize("spec", ["sarif", "sarif:", "pdf:x.pdf"])
def test_bad_report_spec_is_usage_error(tmp_path: Path, spec: str) -> None:
    result = runner.invoke(app, ["analyze", str(tmp_path), "--report", spec])
    assert result.exit_code == 2


@pytest.mark.integration
def test_exclude_skips_paths(tmp_path: Path) -> None:
    (tmp_path / ".architecture.yaml").write_text(
        'schema_version: "1.0"\nproject:\n  name: x\n  language: python\n'
        'architecture:\n  style: layered\n  rule_pack_version: "1.0.0"\n'
        'exclude: ["gen/**", "legacy_*.py"]\n',
        encoding="utf-8",
    )
    for rel in ("gen/deep/a.py", "legacy_b.py", "keep.py"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(COMPLEX, encoding="utf-8")
    result = runner.invoke(app, ["analyze", str(tmp_path), "-f", "github"])
    assert result.exit_code == 0, result.stderr
    assert [line.split(",")[0] for line in result.stdout.splitlines()] == ["::warning file=keep.py"]
