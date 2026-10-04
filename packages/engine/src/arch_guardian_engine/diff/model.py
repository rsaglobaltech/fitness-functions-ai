"""Diff data model and abstract DiffSource."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class ChangeKind(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass(frozen=True)
class ChangedFile:
    """One file changed in a diff."""

    path: Path
    kind: ChangeKind
    additions: int
    deletions: int
    previous_path: Path | None = None  # for renames

    @property
    def is_deletion(self) -> bool:
        return self.kind is ChangeKind.DELETED


@dataclass(frozen=True)
class Diff:
    """A complete diff: list of changed files."""

    base_ref: str | None
    head_ref: str | None
    files: tuple[ChangedFile, ...]

    @property
    def total_changes(self) -> int:
        return sum(f.additions + f.deletions for f in self.files)


class DiffTooLargeError(RuntimeError):
    """Raised when a diff exceeds the configured size cap."""


class DiffSource(Protocol):
    """Anything that can produce a Diff against a repository."""

    def collect(self) -> Diff: ...
