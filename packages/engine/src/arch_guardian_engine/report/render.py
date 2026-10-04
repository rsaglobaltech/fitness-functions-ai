"""Format dispatch for reports."""

from __future__ import annotations

from enum import StrEnum

from arch_guardian_engine.findings import AnalysisReport
from arch_guardian_engine.report.sarif import to_sarif_json
from arch_guardian_engine.report.text import to_text


class OutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"
    SARIF = "sarif"


def render(report: AnalysisReport, fmt: OutputFormat, *, path_prefix: str = "") -> str:
    """Render `report`. `path_prefix` re-roots file paths (SARIF needs repo-root paths)."""
    if fmt is OutputFormat.JSON:
        return report.to_json()
    if fmt is OutputFormat.SARIF:
        return to_sarif_json(report, path_prefix=path_prefix)
    return to_text(report)
