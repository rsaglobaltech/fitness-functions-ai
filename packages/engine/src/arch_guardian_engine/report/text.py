"""Plain-text report for terminals and CI logs (no colour codes, grep-friendly)."""

from __future__ import annotations

from arch_guardian_engine.config import Severity
from arch_guardian_engine.findings import AnalysisReport, Finding

_LABEL = {
    Severity.CRITICAL: "CRITICAL",
    Severity.WARNING: "WARNING",
    Severity.SUGGESTION: "SUGGESTION",
    Severity.OFF: "OFF",
}


def _location(f: Finding) -> str:
    loc = f.location.file
    if f.location.line:
        loc += f":{f.location.line}"
    return loc


def to_text(report: AnalysisReport) -> str:
    lines: list[str] = []
    for f in report.findings:
        lines.append(f"{_location(f)}: {_LABEL[f.severity]} [{f.rule_id}] {f.title}")
        lines.extend(f"    {line}" for line in f.message.splitlines())
        if f.suggested_fix:
            lines.append(f"    fix: {f.suggested_fix}")
        lines.append("")

    if report.config_error:
        lines.append(f"error: invalid .architecture.yaml: {report.config_error}")
    elif report.divergence_warning:
        lines.append(f"note: {report.divergence_warning}")
    lines.extend(f"warning: {w}" for w in report.warnings)

    counts = report.by_severity
    summary = ", ".join(
        f"{counts.get(s, 0)} {s.value}"
        for s in (Severity.CRITICAL, Severity.WARNING, Severity.SUGGESTION)
    )
    scope = f"new vs {report.base_ref}" if report.base_ref else "full scan"
    extras = []
    if report.baseline_count:
        extras.append(f"{report.baseline_count} pre-existing hidden")
    if report.suppressed_count:
        extras.append(f"{report.suppressed_count} suppressed by exceptions")
    tail = f" ({'; '.join(extras)})" if extras else ""
    style = report.rule_pack or f"{report.resolved_style} ({report.resolution_source})"
    lines.append(
        f"arch-guardian: {summary} — {scope}, style {style}, {report.duration_ms} ms{tail}"
    )
    return "\n".join(lines) + "\n"
