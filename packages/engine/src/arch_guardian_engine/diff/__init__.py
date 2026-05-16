"""PR / commit diff extraction.

`DiffSource` is the abstract interface every implementation honors. H2 ships
two implementations:

    - `LocalGitDiff`: runs `git diff` against the working tree / a base ref.
      Used by the CLI and unit tests; no network.
    - `GitHubPullRequestDiff`: hits the GitHub REST API for a given PR.
      Used by the CI integration (H5 lands in detail).

Both produce the same `Diff` shape: a list of changed files, each with the new
content (when available) and a header summary. We deliberately *do not* try
to parse hunks here — detectors operate on whole files, not line ranges.
"""

from arch_guardian_engine.diff.local_git import LocalGitDiff
from arch_guardian_engine.diff.model import (
    ChangedFile,
    ChangeKind,
    Diff,
    DiffSource,
    DiffTooLargeError,
)

__all__ = [
    "ChangeKind",
    "ChangedFile",
    "Diff",
    "DiffSource",
    "DiffTooLargeError",
    "LocalGitDiff",
]
