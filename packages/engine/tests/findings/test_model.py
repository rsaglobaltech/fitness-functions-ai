"""Tests for the Finding / AnalysisReport models."""

from __future__ import annotations

import pytest
from arch_guardian_engine.config import Severity
from arch_guardian_engine.findings import (
    AnalysisReport,
    Finding,
    FindingLocation,
    FindingSource,
)


def _finding(severity: Severity, file: str, line: int) -> Finding:
    return Finding(
        rule_id="test.rule",
        severity=severity,
        title="t",
        message="m",
        location=FindingLocation(file=file, line=line),
        source=FindingSource.UNIVERSAL,
    )


@pytest.mark.unit
def test_finding_blocking_only_on_critical() -> None:
    assert _finding(Severity.CRITICAL, "a.py", 1).is_blocking
    assert not _finding(Severity.WARNING, "a.py", 1).is_blocking
    assert not _finding(Severity.SUGGESTION, "a.py", 1).is_blocking


@pytest.mark.unit
def test_report_sort_orders_by_severity_then_location() -> None:
    f1 = _finding(Severity.WARNING, "b.py", 1)
    f2 = _finding(Severity.CRITICAL, "z.py", 5)
    f3 = _finding(Severity.CRITICAL, "a.py", 2)
    report = AnalysisReport(
        repo="/x",
        resolved_style="universal",
        resolution_source="fallback_universal",
        findings=(f1, f2, f3),
    ).sorted()
    assert [f.location.file for f in report.findings] == ["a.py", "z.py", "b.py"]


@pytest.mark.unit
def test_report_has_blocking_reflects_findings() -> None:
    report = AnalysisReport(
        repo="/x",
        resolved_style="universal",
        resolution_source="fallback_universal",
        findings=(_finding(Severity.WARNING, "a.py", 1),),
    )
    assert not report.has_blocking
    report2 = report.model_copy(update={"findings": (_finding(Severity.CRITICAL, "a.py", 1),)})
    assert report2.has_blocking


@pytest.mark.unit
def test_report_by_severity_counts() -> None:
    report = AnalysisReport(
        repo="/x",
        resolved_style="universal",
        resolution_source="fallback_universal",
        findings=(
            _finding(Severity.CRITICAL, "a.py", 1),
            _finding(Severity.CRITICAL, "a.py", 2),
            _finding(Severity.WARNING, "a.py", 3),
        ),
    )
    counts = report.by_severity
    assert counts[Severity.CRITICAL] == 2
    assert counts[Severity.WARNING] == 1


@pytest.mark.unit
def test_report_to_json_round_trip() -> None:
    report = AnalysisReport(
        repo="/x",
        resolved_style="hexagonal",
        resolution_source="declared",
        findings=(_finding(Severity.WARNING, "a.py", 1),),
    )
    j = report.to_json()
    assert "hexagonal" in j
    assert "test.rule" in j
