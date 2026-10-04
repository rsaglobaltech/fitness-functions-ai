"""Small git plumbing helpers: repo discovery, merge-base, throwaway worktrees.

All calls go through `run_git`, which turns failures into `GitError` carrying
git's own stderr so CLI users see *why* (shallow clone, unknown ref, ...).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from arch_guardian_engine.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

_log = get_logger(__name__)


class GitError(RuntimeError):
    """A git command failed; message includes git's stderr."""


def run_git(cwd: Path, *args: str) -> str:
    # Arguments are refs / paths passed as separate argv items, never through a
    # shell, so they cannot inject commands. `git` must be on PATH.
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(cwd), *args],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise GitError(f"git {' '.join(args)} failed: {detail}") from exc
    return result.stdout


def git_toplevel(path: Path) -> Path:
    """Root of the git working tree containing `path`."""
    return Path(run_git(path, "rev-parse", "--show-toplevel").strip()).resolve()


def resolve_commit(repo: Path, ref: str) -> str:
    """Full SHA for `ref`. Leading '-' is rejected so a ref is never read as an option."""
    if ref.startswith("-"):
        raise GitError(f"invalid ref: {ref!r}")
    return run_git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").strip()


def merge_base(repo: Path, base: str, head: str) -> str:
    """Commit where `head` forked from `base` (what a PR is compared against)."""
    base_sha = resolve_commit(repo, base)
    head_sha = resolve_commit(repo, head)
    try:
        return run_git(repo, "merge-base", base_sha, head_sha).strip()
    except GitError as exc:
        raise GitError(
            f"no merge-base between {base} and {head}. In CI, check out full history "
            "(actions/checkout with `fetch-depth: 0`)."
        ) from exc


@contextmanager
def worktree_at(repo: Path, commit: str) -> Iterator[Path]:
    """Check out `commit` into a temporary detached worktree; always cleaned up."""
    tmp = Path(tempfile.mkdtemp(prefix="arch-guardian-"))
    target = tmp / "wt"
    run_git(repo, "worktree", "add", "--detach", "--quiet", str(target), commit)
    try:
        yield target
    finally:
        try:
            run_git(repo, "worktree", "remove", "--force", str(target))
        except GitError as exc:  # pragma: no cover - best effort cleanup
            _log.warning("worktree_cleanup_failed", path=str(target), error=str(exc))
            run_git(repo, "worktree", "prune")
        shutil.rmtree(tmp, ignore_errors=True)
