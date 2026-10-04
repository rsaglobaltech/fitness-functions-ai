"""Analyse a repository, optionally reporting only what a change introduced.

Without `base`, this is a full scan (scheduled jobs, first adoption).

With `base`, the head is analysed and compared with the merge-base of
`base` and `head`, checked out in a throwaway git worktree. Only findings
absent from the merge-base are reported, so a PR is judged on what it adds,
not on the debt it inherits. The base is analysed with the *head's* rules and
layout and without exceptions, so a PR that tunes thresholds, declares layers
or removes an exception is compared like-for-like and is not flooded with old
debt.
"""

from __future__ import annotations

import sys
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from arch_guardian_engine.analyzer.repository import RepositoryAnalyzer
from arch_guardian_engine.config import UniversalRules
from arch_guardian_engine.diff import (
    LocalGitDiff,
    git_toplevel,
    merge_base,
    resolve_commit,
    worktree_at,
)
from arch_guardian_engine.findings import AnalysisReport
from arch_guardian_engine.findings.baseline import new_findings
from arch_guardian_engine.logging import get_logger
from arch_guardian_engine.resolver import resolve_style

_log = get_logger(__name__)


@dataclass(frozen=True)
class ChangeAnalysisRequest:
    path: Path
    base: str | None = None
    head: str = "HEAD"  # "HEAD" analyses the working tree as-is
    rules: UniversalRules | None = None
    today: date | None = None


def _renames_within(top: Path, sub: Path, base_sha: str, head: str) -> dict[str, str]:
    diff = LocalGitDiff(
        repo_root=top,
        base_ref=base_sha,
        head_ref=head,
        max_files=sys.maxsize,
        max_total_changes=sys.maxsize,
    ).collect()
    renames: dict[str, str] = {}
    for f in diff.files:
        if f.previous_path is None:
            continue
        try:
            old = f.previous_path.relative_to(sub).as_posix()
            new = f.path.relative_to(sub).as_posix()
        except ValueError:
            continue  # rename outside the analysed sub-tree
        renames[old] = new
    return renames


def analyze_changes(req: ChangeAnalysisRequest) -> AnalysisReport:
    """Run the universal analysis; see module docstring for base/head semantics."""
    path = req.path.resolve()
    if req.base is None and req.head == "HEAD":
        return RepositoryAnalyzer(rules=req.rules, today=req.today).analyze(path)

    top = git_toplevel(path)
    sub = path.relative_to(top)

    with ExitStack() as stack:
        if req.head == "HEAD":
            head_root = path
        else:
            head_sha = resolve_commit(top, req.head)
            head_root = stack.enter_context(worktree_at(top, head_sha)) / sub
        head_report = RepositoryAnalyzer(rules=req.rules, today=req.today).analyze(head_root)
        head_report = head_report.model_copy(update={"repo": str(path)})
        if req.base is None:
            return head_report

        head_profile = resolve_style(head_root).profile
        effective_rules = req.rules or (
            head_profile.universal_rules if head_profile else UniversalRules()
        )

    base_sha = merge_base(top, req.base, req.head)
    with worktree_at(top, base_sha) as base_wt:
        base_root = base_wt / sub
        base_findings = (
            RepositoryAnalyzer(rules=effective_rules, apply_exceptions=False, profile=head_profile)
            .analyze(base_root)
            .findings
            if base_root.is_dir()
            else ()
        )

    renames = _renames_within(top, sub, base_sha, req.head)
    fresh = new_findings(head_report.findings, base_findings, renames)
    _log.info(
        "baseline_applied",
        base=req.base,
        merge_base=base_sha,
        head_findings=len(head_report.findings),
        new_findings=len(fresh),
        renames=len(renames),
    )
    return head_report.model_copy(
        update={
            "findings": fresh,
            "base_ref": req.base,
            "baseline_count": len(head_report.findings) - len(fresh),
        }
    )
