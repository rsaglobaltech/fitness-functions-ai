"""Detect circular dependencies between modules.

Algorithm (see ADR-0001 §D2):
    Use `networkx.strongly_connected_components` (Tarjan's algorithm) on the
    import DiGraph produced by the AST analyzer. Any strongly connected
    component with >= 2 nodes is, by definition, a dependency cycle.

We emit one Finding per cycle, anchored at the *lowest* module name
alphabetically so the finding has a stable location and dedups predictably
across runs.
"""

from __future__ import annotations

import networkx as nx

from arch_guardian_engine.ast_analyzer import RepoAnalysis
from arch_guardian_engine.config import Severity
from arch_guardian_engine.findings import Finding, FindingLocation, FindingSource

RULE_ID = "universal.circular_dependency"


def detect_circular_dependencies(
    analysis: RepoAnalysis,
    *,
    severity: Severity = Severity.CRITICAL,
) -> list[Finding]:
    """Return one finding per cyclic dependency SCC (size > 1)."""
    findings: list[Finding] = []

    sccs = (scc for scc in nx.strongly_connected_components(analysis.import_graph) if len(scc) > 1)
    for scc in sccs:
        ordered = sorted(scc)
        anchor_id = ordered[0]
        anchor_module = analysis.modules.get(anchor_id)
        anchor_path = (
            str(anchor_module.path.relative_to(analysis.root)) if anchor_module else anchor_id
        )

        message = "Modules form a dependency cycle:\n  " + " → ".join(ordered) + f" → {ordered[0]}"

        findings.append(
            Finding(
                rule_id=RULE_ID,
                severity=severity,
                title="Circular dependency between modules",
                message=message,
                location=FindingLocation(
                    file=anchor_path,
                    line=anchor_module.imports[0].line
                    if anchor_module and anchor_module.imports
                    else None,
                    symbol=anchor_id,
                ),
                source=FindingSource.UNIVERSAL,
                suggested_fix=(
                    "Break the cycle by extracting the shared abstraction into "
                    "a separate module, or invert one of the dependencies via "
                    "an interface owned by the downstream layer."
                ),
                metadata={
                    "scc_size": len(ordered),
                    "members": ",".join(ordered),
                },
            )
        )

    return findings
