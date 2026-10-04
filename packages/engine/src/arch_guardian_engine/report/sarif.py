"""SARIF 2.1.0 output, consumable by GitHub code scanning and most CI UIs.

Spec: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html
GitHub specifics honoured here:
    - artifact URIs are relative to the repository root (`path_prefix`);
    - `partialFingerprints` lets GitHub track an alert across commits.
"""

from __future__ import annotations

import json
from typing import Any

from arch_guardian_engine import __version__
from arch_guardian_engine.config import Severity
from arch_guardian_engine.findings import AnalysisReport, Finding

_LEVEL = {
    Severity.CRITICAL: "error",
    Severity.WARNING: "warning",
    Severity.SUGGESTION: "note",
    Severity.OFF: "none",
}
_FINGERPRINT_KEY = "archGuardian/v1"
_INFO_URI = "https://github.com/rsaglobaltech/fitness-functions-ai"


def _uri(prefix: str, file: str) -> str:
    prefix = prefix.strip("/")
    return f"{prefix}/{file}" if prefix and prefix != "." else file


def _rule(f: Finding) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "id": f.rule_id,
        "name": f.rule_id.rsplit(".", 1)[-1],
        "shortDescription": {"text": f.title.split(":", 1)[0]},
        "defaultConfiguration": {"level": _LEVEL[f.severity]},
        "properties": {"tags": ["architecture", "maintainability"]},
    }
    if f.suggested_fix:
        rule["help"] = {"text": f.suggested_fix}
    return rule


def _result(f: Finding, rule_index: int, prefix: str) -> dict[str, Any]:
    physical: dict[str, Any] = {
        "artifactLocation": {"uri": _uri(prefix, f.location.file), "uriBaseId": "%SRCROOT%"}
    }
    if f.location.line:
        region: dict[str, int] = {"startLine": f.location.line}
        if f.location.end_line and f.location.end_line >= f.location.line:
            region["endLine"] = f.location.end_line
        physical["region"] = region
    text = f.message if not f.suggested_fix else f"{f.message}\n\nFix: {f.suggested_fix}"
    return {
        "ruleId": f.rule_id,
        "ruleIndex": rule_index,
        "level": _LEVEL[f.severity],
        "message": {"text": text},
        "locations": [{"physicalLocation": physical}],
        "partialFingerprints": {_FINGERPRINT_KEY: f.fingerprint},
        "properties": {"severity": f.severity.value, "source": f.source.value},
    }


def to_sarif(report: AnalysisReport, *, path_prefix: str = "") -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    results: list[dict[str, Any]] = []
    for f in report.findings:
        if f.rule_id not in index:
            index[f.rule_id] = len(rules)
            rules.append(_rule(f))
        results.append(_result(f, index[f.rule_id], path_prefix))

    notes = [*report.warnings]
    if report.config_error:
        notes.insert(0, f"invalid .architecture.yaml: {report.config_error}")
    invocation: dict[str, Any] = {"executionSuccessful": report.config_error is None}
    if notes:
        invocation["toolExecutionNotifications"] = [
            {"level": "warning", "message": {"text": n}} for n in notes
        ]

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "arch-guardian",
                        "version": __version__,
                        "informationUri": _INFO_URI,
                        "rules": rules,
                    }
                },
                "invocations": [invocation],
                "results": results,
                "properties": {
                    "resolvedStyle": report.resolved_style,
                    "resolutionSource": report.resolution_source,
                    "rulePack": report.rule_pack,
                    "baseRef": report.base_ref,
                    "baselineCount": report.baseline_count,
                    "suppressedCount": report.suppressed_count,
                },
            }
        ],
    }


def to_sarif_json(report: AnalysisReport, *, path_prefix: str = "") -> str:
    return json.dumps(to_sarif(report, path_prefix=path_prefix), indent=2)
