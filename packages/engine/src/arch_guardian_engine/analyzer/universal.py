"""Universal analyzer: runs the language-agnostic detectors on a repository.

Why a plain class instead of LangGraph (see ADR-0001 §D7):
    The H2 pipeline is a straight sequence of pure functions. LangGraph adds
    value once we have retries / branches / LLM calls (H3). For now, plain
    composition stays out of the way.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from time import perf_counter

from arch_guardian_engine.ast_analyzer import analyze_repo
from arch_guardian_engine.config import Severity, UniversalRules
from arch_guardian_engine.detectors import (
    detect_circular_dependencies,
    detect_cyclomatic_complexity,
    detect_god_objects,
)
from arch_guardian_engine.findings import AnalysisReport, Finding, apply_exceptions
from arch_guardian_engine.logging import get_logger
from arch_guardian_engine.resolver import resolve_style

_log = get_logger(__name__)


@dataclass
class UniversalAnalyzer:
    """Run all universal detectors on a repository and return an AnalysisReport.

    Rule precedence: explicit `rules` passed by the caller > `universal_rules`
    from the repo's `.architecture.yaml` > built-in defaults. A rule whose
    severity is `off` is not run at all.
    """

    rules: UniversalRules | None = None
    today: date | None = None  # injectable clock for exception expiry

    def analyze(self, repo_root: str | Path) -> AnalysisReport:
        start = perf_counter()
        root = Path(repo_root).resolve()

        resolved = resolve_style(root)
        profile = resolved.profile
        rules = self.rules or (profile.universal_rules if profile else UniversalRules())
        ast = analyze_repo(root)

        findings: list[Finding] = []
        if rules.circular_dependencies is not Severity.OFF:
            findings.extend(detect_circular_dependencies(ast, severity=rules.circular_dependencies))
        if rules.god_object_threshold.severity is not Severity.OFF:
            findings.extend(
                detect_god_objects(
                    ast,
                    severity=rules.god_object_threshold.severity,
                    max_methods=rules.god_object_threshold.max_methods,
                    max_loc=rules.god_object_threshold.max_loc,
                )
            )
        if rules.cyclomatic_complexity.severity is not Severity.OFF:
            findings.extend(
                detect_cyclomatic_complexity(
                    ast,
                    warn_threshold=rules.cyclomatic_complexity.max_per_function,
                    error_threshold=rules.cyclomatic_complexity.max_per_function * 2,
                    warn_severity=rules.cyclomatic_complexity.severity,
                )
            )

        suppression = apply_exceptions(
            findings, profile.exceptions if profile else (), today=self.today
        )

        duration_ms = int((perf_counter() - start) * 1000)
        rule_pack = None
        if profile is not None:
            rule_pack = (
                f"{profile.architecture.style.value}@{profile.architecture.rule_pack_version}"
            )

        report = AnalysisReport(
            repo=str(root),
            resolved_style=resolved.style.value,
            resolution_source=resolved.source.value,
            rule_pack=rule_pack,
            divergence_warning=resolved.divergence_warning,
            findings=suppression.kept,
            suppressed_count=len(suppression.suppressed),
            warnings=suppression.warnings,
            duration_ms=duration_ms,
        ).sorted()

        _log.info(
            "universal_analysis_completed",
            repo=str(root),
            modules=len(ast.modules),
            findings=len(report.findings),
            suppressed=report.suppressed_count,
            duration_ms=duration_ms,
            by_severity={k.value: v for k, v in report.by_severity.items()},
        )
        return report
