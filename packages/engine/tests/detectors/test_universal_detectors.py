"""Integration tests for universal detectors against the planted_violations repo."""

from __future__ import annotations

from pathlib import Path

import pytest
from arch_guardian_engine.analyzer import UniversalAnalyzer
from arch_guardian_engine.ast_analyzer import analyze_repo
from arch_guardian_engine.config import (
    CyclomaticComplexityRule,
    GodObjectThreshold,
    Severity,
    UniversalRules,
)
from arch_guardian_engine.detectors import (
    detect_circular_dependencies,
    detect_cyclomatic_complexity,
    detect_god_objects,
)
from arch_guardian_engine.findings import FindingSource

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PLANTED = FIXTURES / "planted_violations"


@pytest.mark.unit
def test_circular_dependency_detector_finds_both_cycles() -> None:
    analysis = analyze_repo(PLANTED)
    findings = detect_circular_dependencies(analysis)
    assert len(findings) == 2
    members = {f.metadata["members"] for f in findings}
    cycle_1 = ",".join(sorted(["src.billing.invoice", "src.users.account"]))
    cycle_2 = ",".join(sorted(["src.reporting.metrics", "src.shipping.dispatcher"]))
    assert cycle_1 in members
    assert cycle_2 in members
    assert all(f.is_blocking for f in findings)


@pytest.mark.unit
def test_god_object_detector_with_tuned_threshold() -> None:
    """Lower the LOC threshold so both god classes trip 2/3 metrics."""
    analysis = analyze_repo(PLANTED)
    findings = detect_god_objects(analysis, max_methods=25, max_loc=200)
    flagged = {f.location.symbol for f in findings}
    assert "OrderManager" in flagged
    # UserAdmin has many methods but small file; verify metric metadata.
    om = next(f for f in findings if f.location.symbol == "OrderManager")
    assert om.metadata["public_methods"] > 25


@pytest.mark.unit
def test_god_object_detector_skips_small_classes() -> None:
    analysis = analyze_repo(PLANTED)
    findings = detect_god_objects(analysis, max_methods=25, max_loc=200)
    # A 3-method test class would not appear because it trips 0 thresholds.
    assert all(f.metadata["public_methods"] > 25 for f in findings)


@pytest.mark.unit
def test_cyclomatic_complexity_finds_high_cc_functions() -> None:
    analysis = analyze_repo(PLANTED)
    findings = detect_cyclomatic_complexity(analysis, warn_threshold=10)
    fn_names = {f.location.symbol for f in findings}
    expected = {
        "calculate_rate",
        "summarize_complex",
        "compute_total",
        "categorize",
        "can_perform",
        "score_request",
    }
    assert expected.issubset(fn_names), f"missing: {expected - fn_names}"


@pytest.mark.unit
def test_universal_analyzer_catches_at_least_eight_of_ten() -> None:
    """Plan H2 criterion: detect ≥ 8/10 planted violations."""
    rules = UniversalRules(
        circular_dependencies=Severity.CRITICAL,
        god_object_threshold=GodObjectThreshold(
            severity=Severity.WARNING, max_methods=25, max_loc=200
        ),
        cyclomatic_complexity=CyclomaticComplexityRule(
            severity=Severity.WARNING, max_per_function=10
        ),
    )
    report = UniversalAnalyzer(rules=rules).analyze(PLANTED)
    rule_ids = [f.rule_id for f in report.findings]
    cycles = rule_ids.count("universal.circular_dependency")
    god = rule_ids.count("universal.god_object")
    complexity = rule_ids.count("universal.cyclomatic_complexity")
    caught = min(2, cycles) + min(2, god) + min(6, complexity)
    assert caught >= 8, (
        f"only caught {caught}/10 — cycles={cycles}, god={god}, complexity={complexity}"
    )


@pytest.mark.unit
def test_universal_analyzer_returns_sorted_report() -> None:
    rules = UniversalRules(
        cyclomatic_complexity=CyclomaticComplexityRule(max_per_function=10),
        god_object_threshold=GodObjectThreshold(max_methods=25, max_loc=200),
    )
    report = UniversalAnalyzer(rules=rules).analyze(PLANTED)
    severities = [f.severity for f in report.findings]
    # Critical-severity findings should come first.
    last_critical = max(
        (i for i, s in enumerate(severities) if s is Severity.CRITICAL),
        default=-1,
    )
    first_non_critical = next(
        (i for i, s in enumerate(severities) if s is not Severity.CRITICAL),
        len(severities),
    )
    assert last_critical < first_non_critical


@pytest.mark.unit
def test_universal_finding_source_is_universal() -> None:
    analysis = analyze_repo(PLANTED)
    for finding in detect_circular_dependencies(analysis):
        assert finding.source is FindingSource.UNIVERSAL
