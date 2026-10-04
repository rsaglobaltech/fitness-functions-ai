"""Cyclomatic complexity per function.

Approach (see ADR-0001 §D3):
    `FunctionInfo.cyclomatic_complexity` already exposes the McCabe value
    computed during AST extraction. This detector just maps the metric to
    a Finding when it crosses a threshold.

Two levels:
    - complexity > warn_threshold (default 15) → severity WARNING
    - complexity > error_threshold (default 25) → severity CRITICAL

The thresholds are tunable per repo via `universal_rules.cyclomatic_complexity`
in `.architecture.yaml`.
"""

from __future__ import annotations

from arch_guardian_engine.ast_analyzer import RepoAnalysis
from arch_guardian_engine.config import Severity
from arch_guardian_engine.findings import Finding, FindingLocation, FindingSource

RULE_ID = "universal.cyclomatic_complexity"


def detect_cyclomatic_complexity(
    analysis: RepoAnalysis,
    *,
    warn_threshold: int = 15,
    error_threshold: int = 25,
    warn_severity: Severity = Severity.WARNING,
    error_severity: Severity = Severity.CRITICAL,
) -> list[Finding]:
    """Return one finding per function above the threshold."""
    findings: list[Finding] = []

    for module in analysis.modules.values():
        rel_path = str(module.path.relative_to(analysis.root))
        for fn in module.functions:
            cc = fn.cyclomatic_complexity
            if cc <= warn_threshold:
                continue
            severity = error_severity if cc > error_threshold else warn_severity
            findings.append(
                Finding(
                    rule_id=RULE_ID,
                    severity=severity,
                    title=f"High cyclomatic complexity: {fn.name} (CC={cc})",
                    message=(
                        f"Function '{fn.name}' has cyclomatic complexity {cc} "
                        f"(threshold {warn_threshold}). Difficult to test, "
                        "difficult to evolve."
                    ),
                    location=FindingLocation(
                        file=rel_path,
                        line=fn.start_line,
                        end_line=fn.end_line,
                        symbol=fn.name,
                    ),
                    source=FindingSource.UNIVERSAL,
                    suggested_fix=(
                        "Decompose the function into smaller helpers, replace "
                        "long conditional chains with table-driven dispatch or "
                        "polymorphism, and lift independent steps into pure "
                        "functions that can be tested in isolation."
                    ),
                    metadata={
                        "cyclomatic_complexity": cc,
                        "parameters": fn.parameters,
                        "loc": fn.loc,
                        "warn_threshold": warn_threshold,
                        "error_threshold": error_threshold,
                    },
                )
            )

    return findings
