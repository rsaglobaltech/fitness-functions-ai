"""Structured findings emitted by detectors and aggregated into a report."""

from arch_guardian_engine.findings.model import (
    AnalysisReport,
    Finding,
    FindingLocation,
    FindingSource,
)
from arch_guardian_engine.findings.suppression import (
    MEMBER_FILES_KEY,
    SuppressionResult,
    apply_exceptions,
)

__all__ = [
    "MEMBER_FILES_KEY",
    "AnalysisReport",
    "Finding",
    "FindingLocation",
    "FindingSource",
    "SuppressionResult",
    "apply_exceptions",
]
