"""Pydantic models for findings and analysis reports.

A `Finding` is one piece of feedback the engine returns about a piece of
code. Every detector — universal or rule-pack-specific — emits Findings of
this exact shape. The agreement is intentional: the publisher (GitHub bot,
GitLab note, CLI output) only knows how to render `Finding`, never the
internals of any detector.

`AnalysisReport` is the full envelope returned for one repository / PR.
It carries the findings plus metadata that the publisher needs to render
informational comments: which rule pack was loaded, how the style was
resolved, any divergence warning, total LLM cost so far, etc.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from arch_guardian_engine.config import Severity


class FindingSource(StrEnum):
    """Where a finding came from (used by dashboards and the publisher)."""

    UNIVERSAL = "universal"  # built-in rule (cycles, God Object, ...)
    RULE_PACK = "rule_pack"  # comes from a loaded rule pack
    LLM = "llm"  # produced by an LLM analysis step


class FindingLocation(BaseModel):
    """Where in the codebase the finding applies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str = Field(min_length=1)
    line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    symbol: str | None = None  # e.g. "OrderManager" / "calculate_rate"


class Finding(BaseModel):
    """Single piece of feedback from a detector."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str = Field(min_length=1, max_length=128)
    severity: Severity
    title: str = Field(min_length=1, max_length=256)
    message: str = Field(min_length=1)
    location: FindingLocation
    source: FindingSource
    rule_pack: str | None = None
    suggested_fix: str | None = None
    references: tuple[str, ...] = ()  # ADR URLs, docs, etc.
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @property
    def is_blocking(self) -> bool:
        """Plan: only CRITICAL severity blocks a PR by default."""
        return self.severity is Severity.CRITICAL


# Sort key: critical > warning > suggestion, then file, then line.
_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.WARNING: 1,
    Severity.SUGGESTION: 2,
    Severity.OFF: 3,
}


def _sort_key(f: Finding) -> tuple[int, str, int]:
    return (
        _SEVERITY_RANK.get(f.severity, 99),
        f.location.file,
        f.location.line or 0,
    )


class AnalysisReport(BaseModel):
    """Envelope returned by the engine for one analysis run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str
    resolved_style: str  # Style.value
    resolution_source: str  # ResolutionSource.value
    rule_pack: str | None = None  # "hexagonal@2.3.0" or None
    divergence_warning: str | None = None
    findings: tuple[Finding, ...] = ()
    llm_cost_usd: float = 0.0
    duration_ms: int = 0
    generated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def has_blocking(self) -> bool:
        return any(f.is_blocking for f in self.findings)

    @property
    def by_severity(self) -> dict[Severity, int]:
        counts: dict[Severity, int] = {}
        for f in self.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        return counts

    def sorted(self) -> AnalysisReport:
        """Return a copy with findings sorted by severity then location."""
        return self.model_copy(update={"findings": tuple(sorted(self.findings, key=_sort_key))})

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)
