"""UniversalAnalyzer honours `.architecture.yaml`: rules, `off`, exceptions."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest
from arch_guardian_engine.analyzer import UniversalAnalyzer
from arch_guardian_engine.config import Severity, UniversalRules

PLANTED = Path(__file__).resolve().parents[1] / "fixtures" / "planted_violations"

_BASE = """\
schema_version: "1.0"
project:
  name: planted
  language: python
architecture:
  style: hexagonal
  rule_pack_version: "1.0.0"
"""


def _repo(tmp_path: Path, extra_yaml: str = "") -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(PLANTED, repo)
    (repo / ".architecture.yaml").write_text(_BASE + extra_yaml, encoding="utf-8")
    return repo


def _rules(report_findings: tuple) -> set[str]:  # type: ignore[type-arg]
    return {f.rule_id for f in report_findings}


@pytest.mark.unit
def test_yaml_universal_rules_are_applied(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "universal_rules:\n"
        "  circular_dependencies: warning\n"
        "  cyclomatic_complexity:\n"
        '    severity: "off"\n'
        "  god_object_threshold:\n"
        "    severity: critical\n"
        "    max_methods: 5\n"
        "    max_loc: 50\n",
    )
    report = UniversalAnalyzer().analyze(repo)
    assert "universal.cyclomatic_complexity" not in _rules(report.findings)
    cycles = [f for f in report.findings if f.rule_id == "universal.circular_dependency"]
    gods = [f for f in report.findings if f.rule_id == "universal.god_object"]
    assert cycles and all(f.severity is Severity.WARNING for f in cycles)
    assert gods and all(f.severity is Severity.CRITICAL for f in gods)
    assert report.rule_pack == "hexagonal@1.0.0"


@pytest.mark.unit
def test_explicit_rules_override_yaml(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 'universal_rules:\n  circular_dependencies: "off"\n')
    report = UniversalAnalyzer(rules=UniversalRules()).analyze(repo)
    assert "universal.circular_dependency" in _rules(report.findings)


@pytest.mark.unit
def test_exceptions_suppress_and_expired_ones_warn(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "exceptions:\n"
        '  - path: "src/billing/**"\n'
        '    reason: "billing rewrite in progress"\n'
        '    expires: "2026-12-31"\n'
        '  - path: "src/users/**"\n'
        '    reason: "users rewrite in progress"\n'
        '    suppress_rules: ["circular_dependency"]\n'
        '  - path: "src/shipping/**"\n'
        '    reason: "old exception"\n'
        '    expires: "2025-01-01"\n',
    )
    report = UniversalAnalyzer(today=date(2026, 6, 1)).analyze(repo)

    files_in_cycles = {
        f.metadata["member_files"]
        for f in report.findings
        if f.rule_id == "universal.circular_dependency"
    }
    # billing↔users is fully covered → suppressed; shipping↔reporting stays.
    assert all("src/billing" not in m for m in files_in_cycles)
    assert any("src/shipping" in m for m in files_in_cycles)
    assert report.suppressed_count >= 1
    assert any("expired on 2025-01-01" in w for w in report.warnings)
