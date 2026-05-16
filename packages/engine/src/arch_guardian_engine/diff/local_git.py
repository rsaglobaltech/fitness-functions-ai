"""DiffSource backed by a local `git` invocation.

Why subprocess `git` rather than a Python git library:
    - `git` is already installed on every dev machine and every CI runner that
      knows about Git. No extra dep, no version drift.
    - We need plumbing commands (`git diff --name-status`, `git diff
      --numstat`); these are stable and well-documented contracts.
    - Avoids the surface area of GitPython / dulwich which have caused
      compatibility issues in past projects.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from arch_guardian_engine.diff.model import (
    ChangedFile,
    ChangeKind,
    Diff,
    DiffTooLargeError,
)
from arch_guardian_engine.logging import get_logger

_log = get_logger(__name__)

_DEFAULT_MAX_FILES = 200
_DEFAULT_MAX_CHANGES = 10_000


_KIND_MAP: dict[str, ChangeKind] = {
    "A": ChangeKind.ADDED,
    "M": ChangeKind.MODIFIED,
    "D": ChangeKind.DELETED,
    "R": ChangeKind.RENAMED,
    "C": ChangeKind.RENAMED,  # treat copy as rename
}


@dataclass
class LocalGitDiff:
    """Collect a diff from a local git repository."""

    repo_root: Path
    base_ref: str = "HEAD~1"
    head_ref: str = "HEAD"
    max_files: int = _DEFAULT_MAX_FILES
    max_total_changes: int = _DEFAULT_MAX_CHANGES

    def _run(self, *args: str) -> str:
        # args are constants assembled here; not user-controlled. The "git"
        # binary is expected on PATH on every CI runner and dev box.
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(self.repo_root), *args],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def collect(self) -> Diff:
        name_status_raw = self._run(
            "diff", "--name-status", "-M", f"{self.base_ref}..{self.head_ref}"
        )
        numstat_raw = self._run("diff", "--numstat", "-M", f"{self.base_ref}..{self.head_ref}")

        numstats: dict[str, tuple[int, int]] = {}
        for line in numstat_raw.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            add_s, del_s, path = parts[0], parts[1], parts[-1]
            # Binary files report "-" instead of counts; treat as 0.
            adds = int(add_s) if add_s.isdigit() else 0
            dels = int(del_s) if del_s.isdigit() else 0
            numstats[path] = (adds, dels)

        files: list[ChangedFile] = []
        for line in name_status_raw.splitlines():
            parts = line.split("\t")
            kind_code = parts[0][:1]
            kind = _KIND_MAP.get(kind_code)
            if kind is None:
                continue
            if kind is ChangeKind.RENAMED and len(parts) >= 3:
                previous, new = parts[1], parts[2]
                adds, dels = numstats.get(new, (0, 0))
                files.append(
                    ChangedFile(
                        path=Path(new),
                        kind=kind,
                        additions=adds,
                        deletions=dels,
                        previous_path=Path(previous),
                    )
                )
            else:
                path = parts[-1]
                adds, dels = numstats.get(path, (0, 0))
                files.append(
                    ChangedFile(
                        path=Path(path),
                        kind=kind,
                        additions=adds,
                        deletions=dels,
                    )
                )

        if len(files) > self.max_files:
            raise DiffTooLargeError(
                f"diff has {len(files)} files (cap {self.max_files}). "
                "Big merges should be split or reviewed manually."
            )
        total = sum(f.additions + f.deletions for f in files)
        if total > self.max_total_changes:
            raise DiffTooLargeError(
                f"diff has {total} line changes (cap {self.max_total_changes})."
            )

        _log.info(
            "diff_collected",
            files=len(files),
            additions=sum(f.additions for f in files),
            deletions=sum(f.deletions for f in files),
            base=self.base_ref,
            head=self.head_ref,
        )
        return Diff(base_ref=self.base_ref, head_ref=self.head_ref, files=tuple(files))
