"""Tests for the LocalGitDiff source.

Builds a real (tiny) git repo in a tmp dir and asserts the diff is parsed
correctly. We rely on the system `git` binary; if it's missing the tests
are skipped.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from arch_guardian_engine.diff import (
    ChangeKind,
    DiffTooLargeError,
    LocalGitDiff,
)


def _git_available() -> bool:
    return shutil.which("git") is not None


pytestmark = pytest.mark.skipif(not _git_available(), reason="git binary not on PATH")


def _init_repo(path: Path) -> None:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "t@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "t"],
        check=True,
        capture_output=True,
    )
    # First commit
    (path / "a.py").write_text("print(1)\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(path), "add", "a.py"], check=True, env=env, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        check=True,
        env=env,
        capture_output=True,
    )
    # Second commit: modify + add
    (path / "a.py").write_text("print(1)\nprint(2)\n", encoding="utf-8")
    (path / "b.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(path), "add", "a.py", "b.py"],
        check=True,
        env=env,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "second"],
        check=True,
        env=env,
        capture_output=True,
    )


@pytest.mark.unit
def test_local_git_diff_parses_modifications_and_additions(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    diff = LocalGitDiff(repo_root=tmp_path).collect()
    by_path = {str(f.path): f for f in diff.files}
    assert by_path["a.py"].kind is ChangeKind.MODIFIED
    assert by_path["a.py"].additions >= 1
    assert by_path["b.py"].kind is ChangeKind.ADDED


@pytest.mark.unit
def test_local_git_diff_raises_when_too_many_files(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    src = LocalGitDiff(repo_root=tmp_path, max_files=0)
    with pytest.raises(DiffTooLargeError):
        src.collect()
