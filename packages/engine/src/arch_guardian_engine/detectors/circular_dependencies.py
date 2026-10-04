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
from arch_guardian_engine.findings import (
    MEMBER_FILES_KEY,
    Finding,
    FindingLocation,
    FindingSource,
)

RULE_ID = "universal.circular_dependency"


def detect_circular_dependencies(
    analysis: RepoAnalysis,
    *,
    severity: Severity = Severity.CRITICAL,
) -> list[Finding]:
    """Return one finding per cyclic dependency SCC (size > 1)."""
    findings: list[Finding] = []

    graph = analysis.import_graph
    sccs = (scc for scc in nx.strongly_connected_components(graph) if len(scc) > 1)
    for scc in sccs:
        ordered = sorted(scc)
        anchor_id = ordered[0]
        anchor_module = analysis.modules.get(anchor_id)
        anchor_path = analysis.rel_path(anchor_id) if anchor_module else anchor_id
        member_files = sorted(analysis.rel_path(mid) for mid in ordered if mid in analysis.modules)

        cycle = _shortest_cycle(graph, scc, anchor_id)
        # Anchor at the import that starts the shortest cycle.
        import_lines: list[int] = graph.edges[cycle[0], cycle[1]].get("lines") or []
        path = " → ".join(cycle)
        if len(scc) == len(cycle) - 1:
            message = f"Modules form a dependency cycle:\n  {path}"
        else:
            message = (
                f"{len(scc)} modules are mutually dependent (one strongly connected "
                f"group). Shortest cycle through {anchor_id}:\n  {path}"
            )

        findings.append(
            Finding(
                rule_id=RULE_ID,
                severity=severity,
                title="Circular dependency between modules",
                message=message,
                location=FindingLocation(
                    file=anchor_path,
                    line=min(import_lines) if import_lines else None,
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
                    "shortest_cycle": path,
                    MEMBER_FILES_KEY: ",".join(member_files),
                },
            )
        )

    return findings


def _shortest_cycle(graph: nx.DiGraph[str], scc: set[str], anchor: str) -> list[str]:
    """Shortest real cycle through `anchor` inside its SCC, closed (first == last).

    One BFS on the reversed SCC gives every node's shortest path *to* the
    anchor; the best successor of the anchor closes the shortest loop.
    """
    sub = graph.subgraph(scc)
    to_anchor = nx.single_source_shortest_path(sub.reverse(copy=False), anchor)
    best = min(
        (s for s in sub.successors(anchor) if s in to_anchor),
        key=lambda s: (len(to_anchor[s]), s),
    )
    return [anchor, *reversed(to_anchor[best])]
