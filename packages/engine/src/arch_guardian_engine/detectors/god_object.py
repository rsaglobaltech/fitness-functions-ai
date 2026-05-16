"""Detect God Objects via metric thresholds.

Approach (see ADR-0001 §D4):
    A class is flagged when it crosses two of three thresholds:
        - public method count > max_methods (default 25)
        - total LOC > max_loc (default 500)
        - fan-out > max_fan_out (default 12)

    Requiring two-of-three keeps false positives low: a 600-line class with
    six methods is almost always a data class / value-object / config block
    and should not be flagged.

LCOM4 is deliberately out of scope for H2; see ADR for the rationale.
"""

from __future__ import annotations

from arch_guardian_engine.ast_analyzer import RepoAnalysis
from arch_guardian_engine.config import Severity
from arch_guardian_engine.findings import Finding, FindingLocation, FindingSource

RULE_ID = "universal.god_object"


def detect_god_objects(
    analysis: RepoAnalysis,
    *,
    severity: Severity = Severity.WARNING,
    max_methods: int = 25,
    max_loc: int = 500,
    max_fan_out: int = 12,
) -> list[Finding]:
    """Return one finding per class that trips at least two thresholds."""
    findings: list[Finding] = []
    graph = analysis.import_graph

    for module in analysis.modules.values():
        fan_out = graph.out_degree(module.module_id) if module.module_id in graph else 0
        for klass in module.classes:
            tripped: list[str] = []
            if klass.public_methods > max_methods:
                tripped.append(f"public_methods={klass.public_methods} (>{max_methods})")
            if klass.loc > max_loc:
                tripped.append(f"loc={klass.loc} (>{max_loc})")
            if fan_out > max_fan_out:
                tripped.append(f"module_fan_out={fan_out} (>{max_fan_out})")

            if len(tripped) < 2:
                continue

            findings.append(
                Finding(
                    rule_id=RULE_ID,
                    severity=severity,
                    title=f"God Object: {klass.name}",
                    message=(
                        f"Class '{klass.name}' trips multiple God Object thresholds: "
                        + ", ".join(tripped)
                    ),
                    location=FindingLocation(
                        file=str(module.path.relative_to(analysis.root)),
                        line=klass.start_line,
                        end_line=klass.end_line,
                        symbol=klass.name,
                    ),
                    source=FindingSource.UNIVERSAL,
                    suggested_fix=(
                        "Split the class along its responsibilities. Identify "
                        "method clusters that share state vs. those that "
                        "orchestrate; the orchestrator typically becomes a "
                        "service, the clusters become focused value/entity types."
                    ),
                    metadata={
                        "public_methods": klass.public_methods,
                        "total_methods": klass.total_methods,
                        "loc": klass.loc,
                        "module_fan_out": fan_out,
                    },
                )
            )

    return findings
