"""GitHub Actions workflow commands: findings become inline PR annotations.

Works on any repository (no code-scanning / GHAS license needed).
Docs: https://docs.github.com/actions/reference/workflow-commands-for-github-actions
"""

from __future__ import annotations

from arch_guardian_engine.config import Severity
from arch_guardian_engine.findings import AnalysisReport, Finding
from arch_guardian_engine.paths import repo_uri

_COMMAND = {
    Severity.CRITICAL: "error",
    Severity.WARNING: "warning",
    Severity.SUGGESTION: "notice",
}


def _escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(value: str) -> str:
    return _escape_data(value).replace(":", "%3A").replace(",", "%2C")


def _annotation(f: Finding, prefix: str) -> str | None:
    command = _COMMAND.get(f.severity)
    if command is None:
        return None
    props = [f"file={_escape_property(repo_uri(prefix, f.location.file))}"]
    if f.location.line:
        props.append(f"line={f.location.line}")
        if f.location.end_line and f.location.end_line >= f.location.line:
            props.append(f"endLine={f.location.end_line}")
    props.append(f"title={_escape_property(f'[{f.rule_id}] {f.title}')}")
    body = f.message if not f.suggested_fix else f"{f.message}\nFix: {f.suggested_fix}"
    return f"::{command} {','.join(props)}::{_escape_data(body)}"


def to_github(report: AnalysisReport, *, path_prefix: str = "") -> str:
    lines = [a for f in report.findings if (a := _annotation(f, path_prefix)) is not None]
    if report.config_error:
        lines.append(f"::error title=arch-guardian::{_escape_data(report.config_error)}")
    lines.extend(f"::warning title=arch-guardian::{_escape_data(w)}" for w in report.warnings)
    return "\n".join(lines) + ("\n" if lines else "")
