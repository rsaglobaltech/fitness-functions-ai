"""Apply `.architecture.yaml` `exceptions` to a list of findings.

Matching rules:
    - `path` is a repo-relative glob (see `arch_guardian_engine.paths`).
    - `suppress_rules` entries match either the full rule id
      (`universal.circular_dependency`) or its short name
      (`circular_dependency`). An empty list suppresses every rule on the path.
    - Findings spanning several files (cycles) carry `member_files` metadata;
      they are suppressed only when *every* member is covered, so a legacy
      exception never hides a cycle that drags in non-legacy code.
    - An exception whose `expires` date is in the past is ignored and reported
      as a warning: expired debt must resurface, not stay silenced forever.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from arch_guardian_engine.config import ExceptionRule
from arch_guardian_engine.findings.model import MEMBER_FILES_KEY, Finding
from arch_guardian_engine.logging import get_logger
from arch_guardian_engine.paths import matches_glob

_log = get_logger(__name__)

__all__ = ["MEMBER_FILES_KEY", "SuppressionResult", "apply_exceptions"]


@dataclass(frozen=True)
class SuppressionResult:
    kept: tuple[Finding, ...]
    suppressed: tuple[Finding, ...]
    warnings: tuple[str, ...]


def _rule_matches(rule_id: str, suppress_rules: tuple[str, ...]) -> bool:
    if not suppress_rules:
        return True
    short = rule_id.rsplit(".", 1)[-1]
    return any(r in (rule_id, short) for r in suppress_rules)


def _is_suppressed(finding: Finding, rules: list[ExceptionRule]) -> bool:
    applicable = [r for r in rules if _rule_matches(finding.rule_id, r.suppress_rules)]
    if not applicable:
        return False
    return all(any(matches_glob(f, r.path) for r in applicable) for f in finding.files)


def _active_rules(
    exceptions: tuple[ExceptionRule, ...], today: date
) -> tuple[list[ExceptionRule], list[str]]:
    active: list[ExceptionRule] = []
    warnings: list[str] = []
    for exc in exceptions:
        if exc.expires is not None:
            try:
                expires = date.fromisoformat(exc.expires)
            except ValueError:
                warnings.append(
                    f"exception for '{exc.path}' has invalid expires '{exc.expires}'; ignored"
                )
                continue
            if expires < today:
                warnings.append(
                    f"exception for '{exc.path}' expired on {exc.expires} "
                    f"({exc.reason}); its findings are reported again"
                )
                continue
        active.append(exc)
    return active, warnings


def apply_exceptions(
    findings: tuple[Finding, ...] | list[Finding],
    exceptions: tuple[ExceptionRule, ...],
    *,
    today: date | None = None,
) -> SuppressionResult:
    """Split findings into kept / suppressed according to the declared exceptions."""
    active, warnings = _active_rules(exceptions, today or date.today())
    kept: list[Finding] = []
    suppressed: list[Finding] = []
    for f in findings:
        (suppressed if active and _is_suppressed(f, active) else kept).append(f)
    if suppressed or warnings:
        _log.info(
            "exceptions_applied",
            suppressed=len(suppressed),
            active_exceptions=len(active),
            expired_or_invalid=len(warnings),
        )
    return SuppressionResult(tuple(kept), tuple(suppressed), tuple(warnings))
