"""Universal analyzer: runs the language-agnostic detectors on a repository.

Why a plain class instead of LangGraph (see ADR-0001 §D7):
    The H2 pipeline is a straight sequence of pure functions. LangGraph adds
    value once we have retries / branches / LLM calls (H3). For now, plain
    composition stays out of the way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

from arch_guardian_engine.ast_analyzer import analyze_repo
from arch_guardian_engine.config import UniversalRules
from arch_guardian_engine.detectors import (
    detect_circular_dependencies,
    detect_cyclomatic_complexity,
    detect_god_objects,
)
from arch_guardian_engine.findings import AnalysisReport, Finding
from arch_guardian_engine.logging import get_logger
from arch_guardian_engine.resolver import resolve_style

_log = get_logger(__name__)


@dataclass
class UniversalAnalyzer:
    """Run all universal detectors on a repository and return an AnalysisReport."""

    rules: UniversalRules = field(default_factory=UniversalRules)

    def analyze(self, repo_root: str | Path) -> AnalysisReport:
        start = perf_counter()
        root = Path(repo_root).resolve()

        resolved = resolve_style(root)
        ast = analyze_repo(root)

        findings: list[Finding] = []
        findings.extend(
            detect_circular_dependencies(
                ast,
                severity=self.rules.circular_dependencies,
            )
        )
        findings.extend(
            detect_god_objects(
                ast,
                severity=self.rules.god_object_threshold.severity,
                max_methods=self.rules.god_object_threshold.max_methods,
                max_loc=self.rules.god_object_threshold.max_loc,
            )
        )
        findings.extend(
            detect_cyclomatic_complexity(
                ast,
                warn_threshold=self.rules.cyclomatic_complexity.max_per_function,
                error_threshold=self.rules.cyclomatic_complexity.max_per_function * 2,
                warn_severity=self.rules.cyclomatic_complexity.severity,
            )
        )

        duration_ms = int((perf_counter() - start) * 1000)
        rule_pack = None
        if resolved.profile is not None:
            rule_pack = (
                f"{resolved.profile.architecture.style.value}@"
                f"{resolved.profile.architecture.rule_pack_version}"
            )

        report = AnalysisReport(
            repo=str(root),
            resolved_style=resolved.style.value,
            resolution_source=resolved.source.value,
            rule_pack=rule_pack,
            divergence_warning=resolved.divergence_warning,
            findings=tuple(findings),
            duration_ms=duration_ms,
        ).sorted()

        _log.info(
            "universal_analysis_completed",
            repo=str(root),
            modules=len(ast.modules),
            findings=len(report.findings),
            duration_ms=duration_ms,
            by_severity={k.value: v for k, v in report.by_severity.items()},
        )
        return report
