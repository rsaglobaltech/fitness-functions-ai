"""Tests for baseline diffing (only-new findings)."""

from __future__ import annotations

import pytest
from arch_guardian_engine.config import Severity
from arch_guardian_engine.findings import (
    MEMBER_FILES_KEY,
    Finding,
    FindingLocation,
    FindingSource,
)
from arch_guardian_engine.findings.baseline import new_findings


def _f(
    file: str,
    symbol: str = "fn",
    line: int = 1,
    severity: Severity = Severity.WARNING,
    rule_id: str = "universal.cyclomatic_complexity",
    **meta: str,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        title="t",
        message="m",
        location=FindingLocation(file=file, line=line, symbol=symbol),
        source=FindingSource.UNIVERSAL,
        metadata=dict(meta),
    )


@pytest.mark.unit
def test_fingerprint_ignores_line_shifts() -> None:
    assert new_findings([_f("a.py", line=40)], [_f("a.py", line=10)]) == ()


@pytest.mark.unit
def test_escalation_is_new() -> None:
    head = [_f("a.py", severity=Severity.CRITICAL)]
    assert new_findings(head, [_f("a.py")]) == tuple(head)


@pytest.mark.unit
def test_multiset_semantics_for_duplicate_fingerprints() -> None:
    head = [_f("a.py", "<anonymous>", 1), _f("a.py", "<anonymous>", 9)]
    assert len(new_findings(head, [_f("a.py", "<anonymous>", 1)])) == 1


@pytest.mark.unit
def test_renamed_file_keeps_its_old_findings_hidden() -> None:
    assert new_findings([_f("new/a.py")], [_f("old/a.py")], {"old/a.py": "new/a.py"}) == ()


@pytest.mark.unit
def test_renamed_cycle_member_is_mapped() -> None:
    cycle = "universal.circular_dependency"
    base = _f("a.py", "a", rule_id=cycle, **{MEMBER_FILES_KEY: "a.py,b.py"})
    head = _f("a.py", "a", rule_id=cycle, **{MEMBER_FILES_KEY: "a.py,z.py"})
    assert new_findings([head], [base], {"b.py": "z.py"}) == ()


@pytest.mark.unit
def test_shrinking_a_cycle_is_not_new_but_growing_it_is() -> None:
    cycle = "universal.circular_dependency"
    base = _f("a.py", "a", rule_id=cycle, **{MEMBER_FILES_KEY: "a.py,b.py,c.py"})
    shrunk = _f("a.py", "a", rule_id=cycle, **{MEMBER_FILES_KEY: "a.py,b.py"})
    grown = _f("a.py", "a", rule_id=cycle, **{MEMBER_FILES_KEY: "a.py,b.py,c.py,d.py"})
    assert new_findings([shrunk], [base]) == ()
    assert new_findings([grown], [base]) == (grown,)
