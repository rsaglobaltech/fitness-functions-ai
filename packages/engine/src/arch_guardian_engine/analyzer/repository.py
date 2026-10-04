"""Repository analyzer: universal detectors + style rules from `.architecture.yaml`.

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

from arch_guardian_engine.ast_analyzer import RepoAnalysis, analyze_repo
from arch_guardian_engine.config import (
    ArchitectureProfile,
    ConfigError,
    Severity,
    UniversalRules,
)
from arch_guardian_engine.detectors import (
    detect_circular_dependencies,
    detect_cyclomatic_complexity,
    detect_god_objects,
)
from arch_guardian_engine.findings import AnalysisReport, Finding, apply_exceptions
from arch_guardian_engine.logging import get_logger
from arch_guardian_engine.resolver import resolve_style
from arch_guardian_engine.rules import detect_layer_violations, parse_layers

_log = get_logger(__name__)


@dataclass
class RepositoryAnalyzer:
    """Run universal detectors and declared style rules; return an AnalysisReport.

    `profile` overrides the repo's own `.architecture.yaml` (used to judge a
    PR's base with the head's configuration).

    Rule precedence: explicit `rules` passed by the caller > `universal_rules`
    from the repo's `.architecture.yaml` > built-in defaults. A rule whose
    severity is `off` is not run at all.
    """

    rules: UniversalRules | None = None
    today: date | None = None  # injectable clock for exception expiry
    apply_exceptions: bool = True
    profile: ArchitectureProfile | None = None
    jobs: int = 0  # parser processes; 0 = auto

    def analyze(self, repo_root: str | Path) -> AnalysisReport:
        start = perf_counter()
        root = Path(repo_root).resolve()

        resolved = resolve_style(root)
        profile = self.profile or resolved.profile
        config_error = resolved.config_error if self.profile is None else None
        rules = self.rules or (profile.universal_rules if profile else UniversalRules())
        ast = analyze_repo(root, exclude=profile.exclude if profile else (), jobs=self.jobs)

        findings = _universal_findings(ast, rules)
        rule_pack = None
        if profile is not None:
            rule_pack = (
                f"{profile.architecture.style.value}@{profile.architecture.rule_pack_version}"
            )
            try:
                findings.extend(_style_findings(ast, profile, rule_pack))
            except ConfigError as exc:
                config_error = config_error or str(exc)

        exceptions = profile.exceptions if profile and self.apply_exceptions else ()
        suppression = apply_exceptions(findings, exceptions, today=self.today)

        duration_ms = int((perf_counter() - start) * 1000)
        report = AnalysisReport(
            repo=str(root),
            resolved_style=resolved.style.value,
            resolution_source=resolved.source.value,
            rule_pack=rule_pack,
            divergence_warning=resolved.divergence_warning,
            config_error=config_error,
            findings=suppression.kept,
            suppressed_count=len(suppression.suppressed),
            warnings=suppression.warnings,
            duration_ms=duration_ms,
        ).sorted()

        _log.info(
            "analysis_completed",
            repo=str(root),
            modules=len(ast.modules),
            findings=len(report.findings),
            suppressed=report.suppressed_count,
            duration_ms=duration_ms,
            by_severity={k.value: v for k, v in report.by_severity.items()},
        )
        return report


def _universal_findings(ast: RepoAnalysis, rules: UniversalRules) -> list[Finding]:
    """Language-agnostic detectors; a rule set to `off` does not run."""
    findings: list[Finding] = []
    if rules.circular_dependencies is not Severity.OFF:
        findings.extend(detect_circular_dependencies(ast, severity=rules.circular_dependencies))
    god = rules.god_object_threshold
    if god.severity is not Severity.OFF:
        findings.extend(
            detect_god_objects(
                ast, severity=god.severity, max_methods=god.max_methods, max_loc=god.max_loc
            )
        )
    cc = rules.cyclomatic_complexity
    if cc.severity is not Severity.OFF:
        findings.extend(
            detect_cyclomatic_complexity(
                ast,
                warn_threshold=cc.max_per_function,
                error_threshold=cc.max_per_function * 2,
                warn_severity=cc.severity,
            )
        )
    return findings


def _style_findings(
    ast: RepoAnalysis, profile: ArchitectureProfile, rule_pack: str
) -> list[Finding]:
    """Rules declared in `layout`. Raises ConfigError on a malformed layout."""
    layers = parse_layers(profile.architecture.style, profile.layout)
    if not layers:
        return []
    severity = Severity.CRITICAL if profile.architecture.strict_mode else Severity.WARNING
    return detect_layer_violations(
        ast, layers, style=profile.architecture.style, severity=severity, rule_pack=rule_pack
    )
