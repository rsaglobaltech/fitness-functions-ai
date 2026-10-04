"""Tests for `.architecture.yaml` exception handling."""

from __future__ import annotations

from datetime import date

import pytest
from arch_guardian_engine.config import ExceptionRule, Severity
from arch_guardian_engine.findings import (
    MEMBER_FILES_KEY,
    Finding,
    FindingLocation,
    FindingSource,
    apply_exceptions,
)

TODAY = date(2026, 6, 1)


def _finding(file: str, rule_id: str = "universal.god_object", **meta: str) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=Severity.WARNING,
        title="t",
        message="m",
        location=FindingLocation(file=file),
        source=FindingSource.UNIVERSAL,
        metadata=dict(meta),
    )


def _exc(path: str, *rules: str, expires: str | None = None) -> ExceptionRule:
    return ExceptionRule(
        path=path, reason="legacy migration", expires=expires, suppress_rules=rules
    )


@pytest.mark.unit
def test_suppresses_by_short_and_full_rule_id() -> None:
    findings = [
        _finding("src/legacy/a.py"),
        _finding("src/legacy/b.py", "universal.cyclomatic_complexity"),
        _finding("src/new/c.py"),
    ]
    result = apply_exceptions(
        findings,
        (_exc("src/legacy/**", "god_object", "universal.cyclomatic_complexity"),),
        today=TODAY,
    )
    assert [f.location.file for f in result.kept] == ["src/new/c.py"]
    assert len(result.suppressed) == 2


@pytest.mark.unit
def test_rule_not_listed_is_kept() -> None:
    result = apply_exceptions(
        [_finding("src/legacy/a.py")],
        (_exc("src/legacy/**", "circular_dependency"),),
        today=TODAY,
    )
    assert len(result.kept) == 1


@pytest.mark.unit
def test_empty_suppress_rules_suppresses_everything_on_path() -> None:
    result = apply_exceptions([_finding("src/legacy/a.py")], (_exc("src/legacy/**"),), today=TODAY)
    assert result.kept == ()


@pytest.mark.unit
def test_expired_exception_is_ignored_and_warned() -> None:
    result = apply_exceptions(
        [_finding("src/legacy/a.py")],
        (_exc("src/legacy/**", expires="2026-05-31"),),
        today=TODAY,
    )
    assert len(result.kept) == 1
    assert "expired on 2026-05-31" in result.warnings[0]


@pytest.mark.unit
def test_exception_expiring_today_still_applies() -> None:
    result = apply_exceptions(
        [_finding("src/legacy/a.py")],
        (_exc("src/legacy/**", expires="2026-06-01"),),
        today=TODAY,
    )
    assert result.kept == ()


@pytest.mark.unit
def test_invalid_expiry_is_ignored_and_warned() -> None:
    result = apply_exceptions(
        [_finding("src/legacy/a.py")],
        (_exc("src/legacy/**", expires="someday"),),
        today=TODAY,
    )
    assert len(result.kept) == 1
    assert "invalid expires" in result.warnings[0]


@pytest.mark.unit
def test_cycle_only_suppressed_when_every_member_is_covered() -> None:
    partial = _finding(
        "src/legacy/a.py",
        "universal.circular_dependency",
        **{MEMBER_FILES_KEY: "src/legacy/a.py,src/new/b.py"},
    )
    full = _finding(
        "src/legacy/a.py",
        "universal.circular_dependency",
        **{MEMBER_FILES_KEY: "src/legacy/a.py,src/legacy/b.py"},
    )
    result = apply_exceptions([partial, full], (_exc("src/legacy/**"),), today=TODAY)
    assert result.kept == (partial,)
    assert result.suppressed == (full,)
